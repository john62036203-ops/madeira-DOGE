#!/usr/bin/env python3
"""FEX (ARM64EC module): EnterEC pops the call-ret entry of an indirect CALL into ARM64EC code
(MADEIRA_FEX_EC_CALLRET_POP=1; opt-in).

madeira-doge, from Playport patches/fex/0060 (https://github.com/playportdev/playport, The Playport authors,
GPL-3.0-or-later). An indirect guest CALL that reaches ARM64EC code goes through the dispatcher after pushing a
call-ret entry (its return address and the host label after the branch). The callee returns through EnterEC,
which on iOS never pops that entry, so each such call leaves one entry behind and every guest RET above it
pops the wrong one and misses until the live-window guard resets the stack (Playport: RDR2 makes about
500,000 x64->EC calls a second; one worker had 64,878 net entries leaked).

With MADEIRA_FEX_EC_CALLRET_POP=1, EnterEC does what upstream FEX's does: when the top entry is for the
address being returned to, it pops it, writes the pointer back to the frame and returns to its host label.
The trap flag, a stack outside the live window [base + 2 MiB, base + 6 MiB), another address and a (0,0)
entry fall through to the existing path. A "FEX: ec-callret-pop" line is logged at process start.
Unset (default) the dispatcher is emitted as before, byte for byte. Does nothing while
MADEIRA_FEX_CALLRET_ELIDE=1 (no stack to pop).

Applied by tools/build-xtajit64.sh after the BCD EC overlays (ec-ret's anchors) and callret-elide.
Usage: patch-fex-ios-ec-callret-pop.py FEX-ROOT
Idempotent; fails by name when an anchor moved (the build then goes on without it).
"""
import sys
from pathlib import Path

MARK = "madeira-doge ec-callret-pop"

EMIT_H = "FEXCore/Source/Interface/Core/ArchHelpers/Arm64Emitter.h"
EMIT_CPP = "FEXCore/Source/Interface/Core/ArchHelpers/Arm64Emitter.cpp"
DISP = "FEXCore/Source/Interface/Core/Dispatcher/Dispatcher.cpp"
MODULE = "Source/Windows/ARM64EC/Module.cpp"


def edits(root):
    elide = "CallRetStackUsed()" in (root / EMIT_H).read_text()
    cond = "IosEcCallRetPop && CallRetStackUsed()" if elide else "IosEcCallRetPop"
    return {
        EMIT_H: [(
            'extern "C" uint32_t IosEcReturnWithRet;\n',
            'extern "C" uint32_t IosEcReturnWithRet;\n'
            f'// {MARK} (Playport 0060): EnterEC pops the call-ret entry an indirect guest CALL into ARM64EC code\n'
            '// pushed, when it is for the address being returned to. Set before the dispatcher is emitted\n'
            '// (MADEIRA_FEX_EC_CALLRET_POP=1); 0 leaves the call-ret stack alone there.\n'
            'extern "C" uint32_t IosEcCallRetPop;\n',
        )],
        EMIT_CPP: [(
            'extern "C" uint32_t IosEcReturnWithRet = 0;\n',
            'extern "C" uint32_t IosEcReturnWithRet = 0;\n'
            f'// {MARK}: see IosEcCallRetPop in Arm64Emitter.h.\n'
            'extern "C" uint32_t IosEcCallRetPop = 0;\n',
        )],
        DISP: [(
            '  if (IosEcReturnWithRet) {\n',
            f'  if ({cond}) {{\n'
            f'    // {MARK} (Playport 0060): an indirect guest CALL into ARM64EC code pushed a call-ret entry (its\n'
            '    // return address and the host label after its branch) and the callee returns here: pop it as\n'
            "    // upstream's EnterEC does when the top entry is for this return address. The trap flag, a stack out\n"
            '    // of the live window (the CALL sites\' guard in BranchOps.cpp), another address or a (0,0) entry\n'
            '    // fall through.\n'
            '    ARMEmitter::ForwardLabel l_NoPop;\n'
            '    ldrb(TMP1, STATE_PTR(CpuStateFrame, State.flags[X86State::RFLAG_TF_RAW_LOC]));\n'
            '    (void)cbnz(ARMEmitter::Size::i32Bit, TMP1, &l_NoPop);\n'
            '    ldr(TMP1, STATE, offsetof(FEXCore::Core::CpuStateFrame, State.callret_sp_base));\n'
            '    add(ARMEmitter::Size::i64Bit, TMP1, TMP1, 0x200000);\n'
            '    sub(ARMEmitter::Size::i64Bit, TMP1, REG_CALLRET_SP, TMP1);\n'
            '    lsr(ARMEmitter::Size::i64Bit, TMP1, TMP1, 22);\n'
            '    (void)cbnz(ARMEmitter::Size::i64Bit, TMP1, &l_NoPop);\n'
            '    ldp<ARMEmitter::IndexType::OFFSET>(TMP1, TMP2, REG_CALLRET_SP);\n'
            '    sub(ARMEmitter::Size::i64Bit, TMP1, TMP1, EC_CALL_CHECKER_PC_REG);\n'
            '    (void)cbnz(ARMEmitter::Size::i64Bit, TMP1, &l_NoPop);\n'
            '    (void)cbz(ARMEmitter::Size::i64Bit, TMP2, &l_NoPop);\n'
            '    add(ARMEmitter::Size::i64Bit, REG_CALLRET_SP, REG_CALLRET_SP, 0x10);\n'
            '    str(REG_CALLRET_SP, STATE, offsetof(FEXCore::Core::CpuStateFrame, State.callret_sp));\n'
            '    ret(TMP2);\n'
            '    (void)Bind(&l_NoPop);\n'
            '  }\n'
            '  if (IosEcReturnWithRet) {\n',
        )],
        MODULE: [(
            'extern "C" uint32_t IosEcReturnWithRet;\n',
            'extern "C" uint32_t IosEcReturnWithRet;\n'
            f'extern "C" uint32_t IosEcCallRetPop; /* {MARK} */\n',
        ), (
            '    LogMan::Msg::IFmt("FEX: ec-ret-v1 madeira-bcd enabled={}", IosEcReturnWithRet != 0);\n',
            '    LogMan::Msg::IFmt("FEX: ec-ret-v1 madeira-bcd enabled={}", IosEcReturnWithRet != 0);\n'
            f'    /* {MARK} (Playport 0060): MADEIRA_FEX_EC_CALLRET_POP=1; off by default. */\n'
            '    const char* PopOpt = getenv("MADEIRA_FEX_EC_CALLRET_POP");\n'
            '    IosEcCallRetPop = PopOpt && strcmp(PopOpt, "1") == 0;\n'
            '    LogMan::Msg::IFmt("FEX: ec-callret-pop enabled={}", IosEcCallRetPop != 0);\n',
        )],
    }


def main(argv):
    if len(argv) != 2:
        print(f"usage: {argv[0]} FEX-ROOT", file=sys.stderr)
        return 2
    root = Path(argv[1])
    texts = {rel: (root / rel).read_text() for rel in (EMIT_H, EMIT_CPP, DISP, MODULE)}
    if all(MARK in t for t in texts.values()):
        print("ec-callret-pop: already applied")
        return 0
    if any(MARK in t for t in texts.values()):
        print("patch-fex-ios-ec-callret-pop.py: partial overlay", file=sys.stderr)
        return 1
    out = {}
    for rel, pairs in edits(root).items():
        t = texts[rel]
        for old, new in pairs:
            if t.count(old) != 1:
                print(f"patch-fex-ios-ec-callret-pop.py: {rel}: anchor moved: {old.strip()[:70]!r}", file=sys.stderr)
                return 1
            t = t.replace(old, new, 1)
        out[rel] = t
    for rel, t in out.items():
        (root / rel).write_text(t)
    print("FEX ARM64EC: EnterEC call-ret pop opt-in (MADEIRA_FEX_EC_CALLRET_POP=1)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
