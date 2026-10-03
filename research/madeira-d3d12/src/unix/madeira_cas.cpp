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

unsigned rewrite(Module &m) {
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
        BasicBlock *loop = pre->splitBasicBlock(ci->getIterator(), "cas.retry");
        BasicBlock *cont = loop->splitBasicBlock(after->getIterator(), "cas.done");
        PHINode *n = PHINode::Create(i32, 2, "cas.n", &loop->front());
        new StoreInst(cmp0, expected, ci);
        loop->getTerminator()->eraseFromParent();
        IRBuilder<> b(loop);
        Value *cur = b.CreateLoad(ty, expected, "cas.cur");
        Value *failed = b.CreateICmpEQ(ci, ConstantInt::get(ci->getType(), 0), "cas.failed");
        Value *same = b.CreateICmpEQ(cur, cmp0, "cas.same");
        Value *n1 = b.CreateAdd(n, ConstantInt::get(i32, 1), "cas.n1");
        Value *more = b.CreateICmpULT(n1, ConstantInt::get(i32, 4096), "cas.more");
        Value *retry = b.CreateAnd(b.CreateAnd(failed, same), more, "cas.again");
        b.CreateCondBr(retry, loop, cont);
        n->addIncoming(ConstantInt::get(i32, 0), pre);
        n->addIncoming(n1, loop);
        done++;
    }
    return done;
}

}  // namespace

extern "C" int madeira_cas_fix(const void *lib, size_t len, void **out, size_t *out_len,
                               char *note, size_t note_cap)
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

    unsigned n = rewrite(**mod);
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
        /* The converter wraps its module (0x0B17C0DE: version, offset 20, size,
         * cpu type) and pads the section to 16 bytes; write the same shape. */
        SmallVector<char, 0> raw;
        { raw_svector_ostream os(raw); WriteBitcodeToFile(**mod, os, false, nullptr, true); }
        uint32_t w[5] = { 0x0B17C0DEu, 0, 20, (uint32_t)raw.size(), 0xffffffffu };
        if (bc_size >= 20) { uint32_t ow[5]; memcpy(ow, d + bc_off, 20); if (ow[0] == 0x0B17C0DEu) { w[1] = ow[1]; w[4] = ow[4]; } }
        nb.append((const char *)w, (const char *)w + 20);
        nb.append(raw.begin(), raw.end());
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
    if (note && note_cap) snprintf(note, note_cap, "%u weak compare-exchange(s) made strong (%llu -> %llu bytes of bitcode)", n,
                                   (unsigned long long)bc_size, (unsigned long long)nb.size());
    return 1;
}
