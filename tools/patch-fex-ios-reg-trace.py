#!/usr/bin/env python3
"""Guest register trace v1 (madeira-doge, diagnostic, default off).

At every FEX block exit, store the guest RIP pair, the 16 x86 GPRs (the
ARM64EC static registers), NZCV and the block header into a per-thread ring.
The ntdll-unix fault path reads it through the IosRegTraceLayout DATA export
and searches backwards for the first appearance of a suspicious value.

MADEIRA_FEX_REG_TRACE = <exe name> (or 1 = every executable) turns it on;
MADEIRA_FEX_REG_TRACE_ENTRIES = ring entries of the first thread (power of
two, default 65536 = 12 MB); later threads get 2048 entries. Applied after
patch-fex-ios-branch-history.py (its anchors are that patch's text).
No guest branch, instruction, flag or register is changed.
"""
from pathlib import Path
import sys

MARKER = "madeira-doge: guest register trace v1"
FRAME = "FEXCore/include/FEXCore/Core/CoreState.h"
BRANCH = "FEXCore/Source/Interface/Core/JIT/BranchOps.cpp"
MODULE = "Source/Windows/ARM64EC/Module.cpp"
EXPORT = "Source/Windows/ARM64EC/libarm64ecfex.def"

FRAME_ADD = '''
  /* madeira-doge: guest register trace v1. Ring entries are 192 bytes:
   * [0] source rip [1] target rip [2..17] rax..r15 [18] nzcv [19] serial [20] block. */
  struct IosRegTraceType {
    uint64_t Magic {0x3156525445524744ULL};
    uint64_t Serial {};
    uint64_t Mask {};
    uint64_t Base {};
  } IosRegTrace {};
'''
FRAME_DECL = '''extern uint32_t IosRegTraceEnabled; /* madeira-doge: guest register trace v1 */
static_assert(sizeof(CpuStateFrame::IosRegTraceType) == 32);
static_assert(offsetof(CpuStateFrame, IosRegTrace) % 8 == 0);
static_assert(offsetof(CpuStateFrame, IosRegTrace) + 32 <= 32760);
'''
BRANCH_ANCHOR = '''    add(ARMEmitter::Size::i64Bit, TMP2, TMP2, 1);
    str(TMP2, STATE, History + 8);
  }
#endif
'''
BRANCH_ADD = '''#if defined(FEX_IOS_HOST) && defined(ARCHITECTURE_arm64ec)
  /* madeira-doge: guest register trace v1. TMP1-3 only; stores and MRS leave
   * guest NZCV and every static register untouched. */
  if (FEXCore::Core::IosRegTraceEnabled) {
    using Frame = FEXCore::Core::CpuStateFrame;
    constexpr auto Trace = offsetof(Frame, IosRegTrace);
    ldr(TMP1, STATE, Trace + 16);
    ldr(TMP2, STATE, Trace + 8);
    and_(ARMEmitter::Size::i64Bit, TMP1, TMP1, TMP2);
    ldr(TMP3, STATE, Trace + 24);
    add(TMP3, TMP3, TMP1, ARMEmitter::ShiftType::LSL, 7);
    add(TMP3, TMP3, TMP1, ARMEmitter::ShiftType::LSL, 6);
    add(ARMEmitter::Size::i64Bit, TMP2, TMP2, 1);
    str(TMP2, STATE, Trace + 8);
    str(TMP2, TMP3, 19 * 8);
    for (size_t i = 0; i < 16; i += 2) {
      stp<ARMEmitter::IndexType::OFFSET>(StaticRegisters[i].X(), StaticRegisters[i + 1].X(), TMP3, static_cast<int32_t>(16 + i * 8));
    }
    uint64_t TraceTarget;
    if (IsInlineConstant(Op->NewRIP, &TraceTarget) || IsInlineEntrypointOffset(Op->NewRIP, &TraceTarget)) {
      InsertGuestRIPMove(TMP1, TraceTarget);
      str(TMP1, TMP3, 8);
    } else {
      str(GetReg(Op->NewRIP).X(), TMP3, 8);
    }
    const uint64_t TraceSource = DebugData->GuestOpcodes.empty() ? 0 : Entry + DebugData->GuestOpcodes.back().GuestEntryOffset;
    InsertGuestRIPMove(TMP1, TraceSource);
    str(TMP1, TMP3, 0);
    mrs(TMP1, ARMEmitter::SystemRegister::NZCV);
    str(TMP1, TMP3, 18 * 8);
    ldr(TMP1, STATE, offsetof(Frame, State.InlineJITBlockHeader));
    str(TMP1, TMP3, 20 * 8);
  }
#endif
'''
MODULE_ANCHOR = '''  sizeof(FEXCore::Core::CpuStateFrame::IosGuestBranchHistoryType) | (8ULL << 32),
};
#endif
'''
MODULE_ADD = '''
#ifdef FEX_IOS_HOST
/* madeira-doge: guest register trace v1. DATA, never a native-callable thunk. */
namespace FEXCore::Core { uint32_t IosRegTraceEnabled = 0; }
static uint32_t IosRegTraceThreads = 0;
static uint64_t IosRegTraceFirstEntries = 65536;
alignas(64) static uint8_t IosRegTraceFallback[64 * 192];
extern "C" const uint64_t IosRegTraceLayout[3] = {
  0x3156525445524744ULL,
  offsetof(FEXCore::Core::CpuStateFrame, IosRegTrace) |
    (static_cast<uint64_t>(sizeof(FEXCore::Core::CpuStateFrame)) << 32),
  192ULL | (24ULL << 32),
};
#endif
'''
INIT_ANCHOR = '''                   FEXCore::Core::IosGuestBranchTraceEnabled != 0, ExecutableName);
#endif
'''
INIT_ADD = '''#ifdef FEX_IOS_HOST
  {
    /* madeira-doge: guest register trace v1, before CTX/JIT creation. */
    const char* TraceOpt = getenv("MADEIRA_FEX_REG_TRACE");
    const fextl::string TraceName {ExecutableName};
    FEXCore::Core::IosRegTraceEnabled =
      TraceOpt && TraceOpt[0] && !(TraceOpt[0] == '0' && !TraceOpt[1]) &&
      ((TraceOpt[0] == '1' && !TraceOpt[1]) || _stricmp(TraceOpt, TraceName.c_str()) == 0);
    if (const char* Entries = getenv("MADEIRA_FEX_REG_TRACE_ENTRIES")) {
      uint64_t Want = strtoull(Entries, nullptr, 0);
      if (Want >= 1024 && Want <= (1ULL << 20) && !(Want & (Want - 1))) {
        IosRegTraceFirstEntries = Want;
      }
    }
    LogMan::Msg::IFmt("FEX: reg-trace-v1 madeira-doge enabled={} exe={} first-entries={}",
                      FEXCore::Core::IosRegTraceEnabled != 0, ExecutableName, IosRegTraceFirstEntries);
  }
#endif
'''
THREAD_ANCHOR = '''  CPUArea.StateFrame() = Thread->CurrentFrame;
'''
THREAD_ADD = '''#ifdef FEX_IOS_HOST
  if (FEXCore::Core::IosRegTraceEnabled) {
    /* madeira-doge: guest register trace v1. Never leave Base at 0: the JIT
     * stores unconditionally, so a failed allocation falls back to a small
     * shared ring (diagnostic only; entries may interleave). */
    auto& Trace = Thread->CurrentFrame->IosRegTrace;
    const bool First = __atomic_fetch_add(&IosRegTraceThreads, 1, __ATOMIC_RELAXED) == 0;
    uint64_t Entries = First ? IosRegTraceFirstEntries : 2048;
    void* TraceBase = nullptr;
    SIZE_T TraceSize = Entries * 192;
    if (NtAllocateVirtualMemoryNative(NtCurrentProcess(), &TraceBase, 0, &TraceSize, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE) != 0 ||
        !TraceBase) {
      TraceBase = IosRegTraceFallback;
      Entries = 64;
    }
    Trace.Serial = 0;
    Trace.Mask = Entries - 1;
    Trace.Base = reinterpret_cast<uint64_t>(TraceBase);
    LogMan::Msg::IFmt("FEX: reg-trace-v1 thread ring base={:#x} entries={} first={}", Trace.Base, Entries, First);
  }
#endif
'''

EDITS = {
    FRAME: (
        ("  } IosGuestBranchHistory {};\n", "  } IosGuestBranchHistory {};\n" + FRAME_ADD),
        ("extern uint32_t IosGuestBranchTraceEnabled;\n", "extern uint32_t IosGuestBranchTraceEnabled;\n" + FRAME_DECL),
    ),
    BRANCH: ((BRANCH_ANCHOR, BRANCH_ANCHOR + BRANCH_ADD),),
    MODULE: (
        (MODULE_ANCHOR, MODULE_ANCHOR + MODULE_ADD),
        (INIT_ANCHOR, INIT_ANCHOR + INIT_ADD),
        (THREAD_ANCHOR, THREAD_ANCHOR + THREAD_ADD),
    ),
    EXPORT: (("  IosGuestBranchTraceLayout DATA\n", "  IosGuestBranchTraceLayout DATA\n  ; madeira-doge: guest register trace v1\n  IosRegTraceLayout DATA\n"),),
}


def patch(sources):
    results = {}
    for name, edits in EDITS.items():
        source = sources[name]
        if MARKER in source:
            if not all(source.count(after) == 1 for _, after in edits):
                raise ValueError("partial or changed overlay: " + name)
            results[name] = source
            continue
        for before, _ in edits:
            if source.count(before) != 1:
                raise ValueError("anchor changed: " + name + ": " + before[:80])
        for before, after in edits:
            source = source.replace(before, after, 1)
        results[name] = source
    return results


if __name__ == "__main__":
    root = Path(sys.argv[1])
    sources = {name: (root / name).read_text() for name in EDITS}
    try:
        results = patch(sources)
    except ValueError as error:
        sys.exit("patch-fex-ios-reg-trace: " + str(error))
    for name, result in results.items():
        if result != sources[name]:
            (root / name).write_text(result)
    print("FEX ARM64EC: guest register trace v1 (MADEIRA_FEX_REG_TRACE); guest state unchanged")
