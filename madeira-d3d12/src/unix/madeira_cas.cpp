/* madeira-doge: make the converter's compare-exchange strong.
 *
 * Apple's shader converter lowers a DXIL atomicCompareExchange (HLSL
 * InterlockedCompareExchange, which returns the ORIGINAL value) to
 *
 *     expected = compare;
 *     air.atomic.global.cmpxchg.weak(ptr, &expected, value, ...);
 *     original = expected;
 *
 * A WEAK compare-exchange may fail spuriously: nothing is stored, and
 * `expected` is left holding the current value -- which is `compare`. The
 * shader then reads "original == compare" and believes its store happened.
 *
 * RE Engine's Persistent*ClusterCulling pushes work items into a lock-free
 * queue exactly this way (CAS a slot from 0 to the item, then add to the
 * queue's count when the original was 0). One spurious failure leaves the count
 * one higher than the items actually queued, and every wave then loops waiting
 * for an item that does not exist until the GPU watchdog restarts the GPU: one
 * second a frame, "Discarded (victim of GPU error/recovery)".
 *
 * This pass reads the converter's metallib with the LLVM airconv already links,
 * wraps each weak compare-exchange in the usual retry loop
 *
 *     do { expected = compare; ok = cmpxchg.weak(...); }
 *     while (!ok && expected == compare);
 *
 * The intrinsic returns ZERO when the exchange happened: Apple's own compiler
 * lowers `bool ok = atomic_compare_exchange_weak_explicit(...)` to
 * `icmp eq i32 %call, 0` (measured by compiling a probe in CI and reading its
 * AIR). Builds 66-69 had this inverted and retried the successes.
 *
 * and writes the library back (same container, new bitcode, HASH and MDSZ
 * refreshed). The loop is bounded so a wrong assumption about the intrinsic's
 * return value cannot itself hang the GPU.
 *
 * Returns 1 and a malloc'd library when something was rewritten, 0 when the
 * library has no weak compare-exchange (nothing allocated), -1 when it has one
 * but could not be rewritten (note says why; the caller keeps the original). */
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <string>

#include "llvm/Bitcode/BitcodeReader.h"
#include "llvm/Bitcode/BitcodeWriter.h"
#include "llvm/IR/BasicBlock.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/DerivedTypes.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/LLVMContext.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/Verifier.h"
#include "llvm/Support/Error.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/raw_ostream.h"

#include "sha256.hpp"

using namespace llvm;

namespace {

uint64_t rd64(const uint8_t *p) { uint64_t v; memcpy(&v, p, 8); return v; }
void wr64(uint8_t *p, uint64_t v) { memcpy(p, &v, 8); }

/* MTLB header (metallib_writer.hpp): magic and versions in 16 bytes, then nine
 * uint64: file size, function list offset/size, public metadata offset/size,
 * private metadata offset/size, bitcode offset/size. */
enum { H_FILESIZE = 16, H_FL_OFF = 24, H_FL_SIZE = 32, H_PUB_OFF = 40, H_BC_OFF = 72, H_BC_SIZE = 80, H_SIZE = 88 };

unsigned rewrite(Module &m, int mode) {
    std::vector<CallInst *> sites;
    for (Function &f : m) {
        if (!f.isDeclaration()) continue;
        StringRef n = f.getName();
        if (!n.startswith("air.atomic.") || !n.contains(".cmpxchg.weak.")) continue;
        for (User *u : f.users())
            if (auto *ci = dyn_cast<CallInst>(u))
                if (ci->getCalledFunction() == &f) sites.push_back(ci);
    }
    unsigned done = 0;
    for (CallInst *ci : sites) {
        if (ci->arg_size() < 3 || !ci->getType()->isIntegerTy()) continue;
        Value *expected = ci->getArgOperand(1);
        Type *ty = ci->getArgOperand(2)->getType();
        auto *ept = dyn_cast<PointerType>(expected->getType());
        if (!ept || !ty->isIntegerTy()) continue;
        if (!ept->isOpaque() && ept->getNonOpaquePointerElementType() != ty) continue;
        Instruction *after = ci->getNextNode();
        if (!after) continue;
        BasicBlock *pre = ci->getParent();
        LLVMContext &ctx = m.getContext();
        IntegerType *i32 = Type::getInt32Ty(ctx);

        /* The comparand is whatever the converter stored into `expected`. */
        LoadInst *cmp0 = new LoadInst(ty, expected, "cas.cmp", ci);
        if (mode == 4 && ci->use_empty()) {
            /* No back edge: four attempts in a row, each entered only when the
             * one before failed without the value having changed. */
            BasicBlock *cur_bb = pre->splitBasicBlock(ci->getIterator(), "cas.try0");
            BasicBlock *cont4 = cur_bb->splitBasicBlock(after->getIterator(), "cas.done");
            CallInst *call = ci;
            for (int k = 0; k < 4; k++) {
                new StoreInst(cmp0, expected, call);
                if (k == 3) break;                       /* the last attempt falls through to cas.done */
                BasicBlock *next = BasicBlock::Create(ctx, "cas.try", cur_bb->getParent(), cont4);
                cur_bb->getTerminator()->eraseFromParent();
                IRBuilder<> b4(cur_bb);
                Value *c4 = b4.CreateLoad(ty, expected, "cas.cur");
                Value *f4 = b4.CreateICmpNE(call, ConstantInt::get(call->getType(), 0), "cas.failed");
                Value *s4 = b4.CreateICmpEQ(c4, cmp0, "cas.same");
                b4.CreateCondBr(b4.CreateAnd(f4, s4, "cas.again"), next, cont4);
                CallInst *nc = cast<CallInst>(ci->clone());
                next->getInstList().push_back(nc);
                BranchInst::Create(cont4, next);
                call = nc; cur_bb = next;
            }
            done++;
            continue;
        }
        BasicBlock *loop = pre->splitBasicBlock(ci->getIterator(), "cas.retry");
        BasicBlock *cont = loop->splitBasicBlock(after->getIterator(), "cas.done");
        PHINode *n = PHINode::Create(i32, 2, "cas.n", &loop->front());
        new StoreInst(cmp0, expected, ci);
        loop->getTerminator()->eraseFromParent();
        IRBuilder<> b(loop);
        Value *cur = b.CreateLoad(ty, expected, "cas.cur");
        Value *failed = b.CreateICmpNE(ci, ConstantInt::get(ci->getType(), 0), "cas.failed");
        Value *same = b.CreateICmpEQ(cur, cmp0, "cas.same");
        Value *n1 = b.CreateAdd(n, ConstantInt::get(i32, 1), "cas.n1");
        Value *more = b.CreateICmpULT(n1, ConstantInt::get(i32, 4096), "cas.more");
        /* mode 1 (diagnostic): the same loop shape without reading the intrinsic's result. */
        Value *retry = mode == 1 ? b.CreateAnd(b.CreateAnd(same, b.CreateICmpULT(n1, ConstantInt::get(i32, 2))), more, "cas.again")
                                 : b.CreateAnd(b.CreateAnd(failed, same), more, "cas.again");
        b.CreateCondBr(retry, loop, cont);
        n->addIncoming(ConstantInt::get(i32, 0), pre);
        n->addIncoming(n1, loop);
        done++;
    }
    return done;
}

/* madeira-doge: run each thread of a Persistent*ClusterCulling kernel as a wave
 * of ONE lane. The shader shares its queue bookkeeping across the wave (the
 * first lane does one atomic for everybody, the others read its result with
 * WaveReadLaneFirst / WaveReadLaneAt), which is only right when Metal's SIMD
 * group reconverges inside the loop the way a D3D wave does; when it does not,
 * the queue's count leaks and every wave spins until the GPU watchdog fires.
 * With one lane a ballot is the lane's own bit, a prefix count is zero and "the
 * first lane" is the lane itself.
 *
 * Three things have to change together (builds up to 106 did only the first,
 * which left the kernel culling one item in 32 of one chunk in 32, and could
 * leave threads waiting at the barrier for threads that had returned):
 *   - the wave intrinsics and the lane index;
 *   - the lane COUNT. The converter folds WaveGetLaneCount() to 32, so it is
 *     found by shape: chunks = (n + 31) >> 5, min(32, 32), the chunk's first
 *     item ((task - 1) >> 13) & 0x7ffe0 with its end at + 32, and the item
 *     loop's step of 32. Each becomes its one-lane form. If the shapes are not
 *     all there, nothing is changed and the kernel keeps its waves;
 *   - the group-sync barrier at the end of the loop: one-lane waves leave the
 *     loop at different times, and a thread group barrier must not be reached
 *     by only some of its threads. The memory fence before it stays. */
static bool is_c(const Value *v, uint64_t c) {
    auto *ci = dyn_cast<ConstantInt>(v);
    return ci && ci->getBitWidth() <= 64 && ci->getZExtValue() == c;
}
bool scalarize(Module &m, Function *kernel, unsigned &ncalls, std::string &why) {
    std::vector<std::pair<CallInst *, int>> sites;   /* 0 ballot, 1 pass arg 0 through, 2 true */
    for (Function &f : m) {
        if (!f.isDeclaration()) continue;
        StringRef n = f.getName();
        if (!n.startswith("air.simd_")) continue;
        int kind;
        if (n.startswith("air.simd_ballot")) kind = 0;
        else if (n.startswith("air.simd_broadcast") || n.startswith("air.simd_shuffle")) kind = 1;
        else if (n.startswith("air.simd_is_first")) kind = 2;
        else { why = "unhandled " + n.str(); return false; }
        for (User *u : f.users()) {
            auto *ci = dyn_cast<CallInst>(u);
            if (!ci || ci->getCalledFunction() != &f) { why = "non-call use of " + n.str(); return false; }
            if (kind == 0 && (ci->arg_size() < 1 || !ci->getArgOperand(0)->getType()->isIntegerTy(1) || !ci->getType()->isIntegerTy())) { why = "ballot shape"; return false; }
            if (kind == 1 && (ci->arg_size() < 1 || ci->getArgOperand(0)->getType() != ci->getType())) { why = "broadcast shape"; return false; }
            if (kind == 2 && !ci->getType()->isIntegerTy(1)) { why = "is_first shape"; return false; }
            sites.push_back({ci, kind});
        }
    }
    if (sites.empty()) { why = "no simd calls"; return false; }
    if (!kernel) { why = "no kernel function"; return false; }
    /* The lane count, by shape. Everything is matched before anything is changed. */
    std::vector<Instruction *> ceil_sites, step_adds, end_adds, barriers;
    std::vector<CallInst *> min_sites;
    BinaryOperator *chunk_and = nullptr; unsigned nchunk = 0;
    for (BasicBlock &bb : *kernel)
        for (Instruction &i : bb) {
            if (auto *ci = dyn_cast<CallInst>(&i)) {
                Function *cf = ci->getCalledFunction();
                if (!cf) continue;
                if (cf->getName().startswith("air.min.u.i32") && ci->arg_size() == 2 && is_c(ci->getArgOperand(0), 32) && is_c(ci->getArgOperand(1), 32)) min_sites.push_back(ci);
                else if (cf->getName().startswith("air.wg.barrier")) barriers.push_back(ci);
                continue;
            }
            auto *bo = dyn_cast<BinaryOperator>(&i);
            if (!bo || !bo->getType()->isIntegerTy(32)) continue;
            if (bo->getOpcode() == Instruction::LShr && is_c(bo->getOperand(1), 5)) {
                auto *ad = dyn_cast<BinaryOperator>(bo->getOperand(0));
                if (ad && ad->getOpcode() == Instruction::Add && is_c(ad->getOperand(1), 31)) ceil_sites.push_back(bo);
            } else if (bo->getOpcode() == Instruction::And && is_c(bo->getOperand(1), 524256)) {
                auto *sh = dyn_cast<BinaryOperator>(bo->getOperand(0));
                if (sh && sh->getOpcode() == Instruction::LShr && is_c(sh->getOperand(1), 13) && sh->hasOneUse()) { chunk_and = bo; nchunk++; }
            } else if (bo->getOpcode() == Instruction::Add && is_c(bo->getOperand(1), 32)) {
                auto *ph = dyn_cast<PHINode>(bo->getOperand(0));
                if (ph) for (Value *iv : ph->incoming_values()) if (iv == bo) { step_adds.push_back(bo); break; }
            }
        }
    if (ceil_sites.size() != 1 || min_sites.empty() || nchunk != 1 || step_adds.size() != 1) {
        why = "lane count shapes: " + std::to_string(ceil_sites.size()) + " ceil, " + std::to_string(min_sites.size()) + " min, " +
              std::to_string(nchunk) + " chunk, " + std::to_string(step_adds.size()) + " step";
        return false;
    }
    for (User *u : chunk_and->users()) {
        auto *ub = dyn_cast<BinaryOperator>(u);
        if (ub && ub->getOpcode() == Instruction::Add && ub->getOperand(0) == chunk_and && is_c(ub->getOperand(1), 32)) end_adds.push_back(ub);
        else if (ub && ub->getOpcode() == Instruction::Shl && ub->getOperand(0) == chunk_and) continue;
        else { why = "chunk base has a use that is neither its shift nor its end"; return false; }
    }
    if (end_adds.size() != 1) { why = "chunk end: " + std::to_string(end_adds.size()) + " found"; return false; }
    {
        IntegerType *i32 = Type::getInt32Ty(m.getContext());
        BinaryOperator *ce = cast<BinaryOperator>(ceil_sites[0]);
        Instruction *ca = cast<Instruction>(ce->getOperand(0));
        ce->replaceAllUsesWith(ca->getOperand(0));                                             /* chunks = n */
        ce->eraseFromParent();
        if (ca->use_empty()) ca->eraseFromParent();
        for (CallInst *mc : min_sites) { mc->replaceAllUsesWith(ConstantInt::get(i32, 1)); mc->eraseFromParent(); }   /* min(32, lanes) = 1 */
        cast<BinaryOperator>(chunk_and->getOperand(0))->setOperand(1, ConstantInt::get(i32, 18));
        chunk_and->setOperand(1, ConstantInt::get(i32, 16383));                               /* first item = chunk */
        end_adds[0]->setOperand(1, ConstantInt::get(i32, 1));                                  /* end = chunk + 1 */
        step_adds[0]->setOperand(1, ConstantInt::get(i32, 1));                                 /* next item */
        for (Instruction *bi : barriers) bi->eraseFromParent();
    }
    /* The lane index: the kernel argument tagged air.thread_index_in_simdgroup. */
    if (NamedMDNode *k = m.getNamedMetadata("air.kernel"))
        if (k->getNumOperands() && k->getOperand(0)->getNumOperands() > 2)
            if (auto *args = dyn_cast_or_null<MDNode>(k->getOperand(0)->getOperand(2).get()))
                for (const MDOperand &ao : args->operands()) {
                    auto *an = dyn_cast_or_null<MDNode>(ao.get());
                    if (!an || an->getNumOperands() < 2) continue;
                    auto *tag = dyn_cast_or_null<MDString>(an->getOperand(1).get());
                    auto *idx = dyn_cast_or_null<ConstantAsMetadata>(an->getOperand(0).get());
                    if (!tag || !idx || tag->getString() != "air.thread_index_in_simdgroup") continue;
                    uint64_t i = cast<ConstantInt>(idx->getValue())->getZExtValue();
                    if (kernel && i < kernel->arg_size()) {
                        Argument *a = kernel->getArg((unsigned)i);
                        a->replaceAllUsesWith(Constant::getNullValue(a->getType()));
                    }
                }
    for (auto &s : sites) {
        CallInst *ci = s.first; Value *v;
        if (s.second == 0) v = CastInst::CreateZExtOrBitCast(ci->getArgOperand(0), ci->getType(), "lane.ballot", ci);
        else if (s.second == 1) v = ci->getArgOperand(0);
        else v = ConstantInt::getTrue(ci->getType());
        ci->replaceAllUsesWith(v);
        ci->eraseFromParent();
    }
    ncalls = (unsigned)sites.size();
    return true;
}

int g_scalar = 0;

}  // namespace

extern "C" void madeira_cas_scalar(int on) { g_scalar = on; }

/* mode: 2 = the real fix, 1 = loop without the result, 0 = read and write the
 * module unchanged, -1 = 2 for libraries with several call sites and 0,1,2 in
 * turn for the ones with a single site (a compile-acceptance experiment);
 * 4 = the fix as four straight-line attempts instead of a loop. */
extern "C" int madeira_cas_fix(const void *lib, size_t len, void **out, size_t *out_len,
                               char *note, size_t note_cap, int mode)
{
    const uint8_t *d = (const uint8_t *)lib;
    *out = nullptr; *out_len = 0;
    if (note && note_cap) note[0] = 0;
    if (len < H_SIZE || memcmp(d, "MTLB", 4)) return 0;
    uint64_t fl_off = rd64(d + H_FL_OFF), pub_off = rd64(d + H_PUB_OFF);
    uint64_t bc_off = rd64(d + H_BC_OFF), bc_size = rd64(d + H_BC_SIZE);
    if (bc_off < H_SIZE || bc_size < 8 || bc_off > len || bc_size > len - bc_off) return 0;
    /* The bitcode section must come after the function list and the metadata
     * (it does in every library the converter writes); whatever follows it is
     * carried over unchanged. */
    if (fl_off < H_SIZE || pub_off > bc_off || fl_off + 4 > pub_off) return 0;
    size_t tail_off = (size_t)(bc_off + bc_size), tail_len = len - tail_off;

    LLVMContext ctx;
    ctx.setOpaquePointers(false);   /* AIR is typed-pointer IR; keep it that way on the way out */
    auto mb = MemoryBuffer::getMemBuffer(StringRef((const char *)d + bc_off, (size_t)bc_size), "air", false);
    auto mod = parseBitcodeFile(mb->getMemBufferRef(), ctx);
    if (!mod) {
        std::string e = toString(mod.takeError());
        /* Not an error for the caller unless there was something to fix; the
         * reader failing means nothing can be said either way. */
        if (note && note_cap) snprintf(note, note_cap, "bitcode reader: %.160s", e.c_str());
        return 0;
    }
    bool has = false;
    for (Function &f : **mod)
        if (f.isDeclaration() && f.getName().startswith("air.atomic.") && f.getName().contains(".cmpxchg.weak.")) has = true;
    if (!has) return 0;

    unsigned nsites = 0;
    for (Function &f : **mod)
        if (f.isDeclaration() && f.getName().startswith("air.atomic.") && f.getName().contains(".cmpxchg.weak."))
            for (User *u : f.users()) if (isa<CallInst>(u)) nsites++;
    if (mode < 0) mode = 2;
    std::string kname = "?"; Function *kfn = nullptr;
    if (NamedMDNode *k = (*mod)->getNamedMetadata("air.kernel"))
        if (k->getNumOperands() && k->getOperand(0)->getNumOperands())
            if (auto *cm = dyn_cast_or_null<ConstantAsMetadata>(k->getOperand(0)->getOperand(0).get()))
                if (auto *kf = dyn_cast<Function>(cm->getValue())) { kname = kf->getName().str(); kfn = kf; }
    unsigned nsimd = 0; std::string swhy; bool scal = false;
    if (g_scalar && kname.find("ClusterCulling") != std::string::npos) scal = scalarize(**mod, kfn, nsimd, swhy);
    unsigned n = mode == 0 ? nsites : rewrite(**mod, mode);
    if (!n) { if (note && note_cap) snprintf(note, note_cap, "weak compare-exchange present but no call site matched"); return -1; }
    {
        std::string verr; raw_string_ostream vs(verr);
        if (verifyModule(**mod, &vs)) {
            if (note && note_cap) snprintf(note, note_cap, "verifier: %.200s", vs.str().c_str());
            return -1;
        }
    }
    SmallVector<char, 0> nb;
    {
        /* For an Apple triple LLVM's writer already emits the 0x0B17C0DE wrapper
         * and pads to 16 bytes -- the shape the converter's own section has.
         * (Wrapping it a second time is what made Metal's compiler service
         * crash on every rewritten library in builds 66-68.) */
        raw_svector_ostream os(nb);
        WriteBitcodeToFile(**mod, os, false, nullptr, true);
    }
    {
        uint32_t m0 = 0; if (nb.size() >= 4) memcpy(&m0, nb.data(), 4);
        if (m0 != 0x0B17C0DEu) {   /* not wrapped (non-Apple triple): wrap and pad it here */
            SmallVector<char, 0> raw; raw.swap(nb);
            uint32_t w[5] = { 0x0B17C0DEu, 0, 20, (uint32_t)raw.size(), 0xffffffffu };
            nb.append((const char *)w, (const char *)w + 20);
            nb.append(raw.begin(), raw.end());
        }
        while (nb.size() & 15) nb.push_back(0);
    }

    /* HASH (32 bytes) and MDSZ (8 bytes) in the one function's tag list. */
    static const char hash_tag[6] = { 'H', 'A', 'S', 'H', 0x20, 0x00 };
    static const char mdsz_tag[6] = { 'M', 'D', 'S', 'Z', 0x08, 0x00 };
    size_t hash_at = 0, mdsz_at = 0; unsigned nhash = 0, nmdsz = 0;
    for (size_t i = (size_t)fl_off; i + 6 <= (size_t)pub_off; i++) {
        if (!memcmp(d + i, hash_tag, 6) && i + 38 <= (size_t)pub_off) { hash_at = i + 6; nhash++; }
        if (!memcmp(d + i, mdsz_tag, 6) && i + 14 <= (size_t)pub_off) { mdsz_at = i + 6; nmdsz++; }
    }
    if (nhash != 1 || nmdsz != 1) {
        if (note && note_cap) snprintf(note, note_cap, "function list has %u HASH and %u MDSZ tags (one of each expected)", nhash, nmdsz);
        return -1;
    }
    /* Was the old HASH the SHA-256 of the whole bitcode section? Only then is it
     * known how to refresh it. */
    {
        auto oh = compute_sha256_hash(d + bc_off, (size_t)bc_size);
        if (memcmp(&oh, d + hash_at, 32)) {
            if (note && note_cap) snprintf(note, note_cap, "HASH is not the SHA-256 of the bitcode section (%llu bytes, MDSZ %llu, %zu bytes follow it)",
                                           (unsigned long long)bc_size, (unsigned long long)rd64(d + mdsz_at), tail_len);
            return -1;
        }
    }

    size_t total = (size_t)bc_off + nb.size() + tail_len;
    uint8_t *o = (uint8_t *)malloc(total);
    if (!o) return -1;
    memcpy(o, d, (size_t)bc_off);
    memcpy(o + bc_off, nb.data(), nb.size());
    if (tail_len) memcpy(o + bc_off + nb.size(), d + tail_off, tail_len);
    wr64(o + H_FILESIZE, total);
    wr64(o + H_BC_SIZE, nb.size());
    if (rd64(d + mdsz_at) == bc_size) wr64(o + mdsz_at, nb.size());
    {   /* RLST (reflection list) holds an absolute file offset to what follows the bitcode. */
        static const char rlst_tag[6] = { 'R', 'L', 'S', 'T', 0x10, 0x00 };
        for (size_t i = (size_t)fl_off; i + 22 <= (size_t)bc_off; i++)
            if (!memcmp(d + i, rlst_tag, 6) && rd64(d + i + 6) == tail_off) wr64(o + i + 6, (uint64_t)bc_off + nb.size());
    }
    {
        auto h = compute_sha256_hash((const uint8_t *)nb.data(), nb.size());
        memcpy(o + hash_at, &h, 32);
    }
    *out = o; *out_len = total;
    if (note && note_cap) snprintf(note, note_cap, "'%s' mode %d: %u weak compare-exchange(s) %s; %s%s (%u wave calls) (%llu -> %llu bytes of bitcode)", kname.c_str(), mode, n,
                                   mode == 2 ? "made strong (loop)" : mode == 4 ? "made strong (four attempts, no loop)" : mode == 1 ? "looped without the result (diagnostic)" : "left as they were, module rewritten only (diagnostic)",
                                   scal ? "one-lane waves" : g_scalar ? "waves untouched: " : "waves untouched", scal ? "" : swhy.c_str(), nsimd,
                                   (unsigned long long)bc_size, (unsigned long long)nb.size());
    return 1;
}
