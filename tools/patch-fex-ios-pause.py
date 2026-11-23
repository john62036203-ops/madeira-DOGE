#!/usr/bin/env python3
"""FEX: what x86 PAUSE compiles to on iOS (MADEIRA_FEX_PAUSE=wfe, isb, yield-os[:K], yield-sw[:K] or wait-os[:K[:U]]; opt-in).

madeira-doge, from Playport (playportdev/playport patches/fex 0083, PLA-455). FEX
compiles PAUSE (REP NOP) to YIELD, which Apple's cores treat as a NOP, so a guest
spin-wait loop runs flat out. The Witcher 3's render thread waits for the main
thread in such a loop; with PAUSE as WFE Playport measured 24.38 fps against 22.43
(Kaer Morhen save, 8 against 6 runs) and the E cores ran faster (1.23 -> 1.56 GHz):
the spinning thread no longer takes the power the others could use.

MADEIRA_FEX_PAUSE=wfe compiles PAUSE to WFE (the core waits for the next event:
another core's store to a monitored line, an interrupt, or the generic timer's event
stream); =isb to ISB, a short pipeline flush. Unset or anything else keeps YIELD,
byte for byte. Playport sets the mode in ProcessInit; here DEF_OP(Yield) reads the
variable once, the first time the process's JIT emits a PAUSE (every block is
compiled after the environment is set). FEX's code cache stays off, so no block
compiled under one mode runs under another.

yield-os and wait-os (Playport fex 0084 and 0086): WFE still holds the core, so under the power clamp, with the
efficiency cores full and threads queued, a spinning thread keeps a runnable one waiting. yield-os[:K] keeps YIELD and
makes every K-th PAUSE (default 128) a swtch_pri Mach trap (the core goes to a waiting thread, if any); wait-os[:K[:U]]
makes it a thread_switch that blocks the thread U microseconds (default 50). yield-sw[:K] (madeira-doge) makes it a
swtch Mach trap: like swtch_pri it lets a thread waiting for this core run, but it does not depress the caller's
priority, so the caller competes again at once (swtch_pri leaves it at the lowest priority until it next runs).

PAUSEs are counted per guest thread, as Playport does, in a word of the CPU state frame the thread already has
(IosLastCallbackLR, a diagnostic witness an ARM64EC thread writes only on a path it should never take), so the frame
layout is untouched. Until build 685 one process-wide word was counted instead: every 128th PAUSE of the whole
process trapped, whichever thread ran it, so a thread that spun twice for a lock could be the one taken off its core
(God of War, 2026-11-23: unrelated threads sampled in swtch_pri).

Applied by tools/build-xtajit64.sh (restores MiscOps.cpp after its build);
idempotent; a moved anchor refuses the patch and the build goes on without it.
Usage: patch-fex-ios-pause.py FEX-ROOT
"""
from pathlib import Path
import sys

MARKER = "madeira-doge pause-mode"
MISC = "FEXCore/Source/Interface/Core/JIT/MiscOps.cpp"

INCLUDE_ANCHOR = '#include "Interface/Core/JIT/JITClass.h"\n'
INCLUDE = "#include <cstdlib>\n#include <cstring>\n"

OLD = "DEF_OP(Yield) {\n  yield();\n}\n"
NEW = '''DEF_OP(Yield) {
#ifdef FEX_IOS_HOST
  /* madeira-doge pause-mode (Playport fex 0083, 0084, 0086): MADEIRA_FEX_PAUSE picks what x86 PAUSE compiles to.
   * wfe, isb: that instruction. yield-os[:K]: YIELD, and every K-th PAUSE of a thread (default 128, 1-4095) a
   * swtch_pri Mach trap, which runs another runnable thread on this core if one waits and leaves the caller at the
   * lowest priority until it next runs. yield-sw[:K]: the same with the swtch trap, which does not depress the
   * caller. wait-os[:K[:U]]: the trap is thread_switch with SWITCH_OPTION_DISPATCH_CONTENTION, which blocks the
   * thread for U microseconds (default 50, 1-5000) whatever else is runnable. Unset or anything else keeps YIELD,
   * which Apple's cores treat as a NOP. Read once per process. The count is the thread's own (a word of its frame). */
  struct PauseOption {
    int Mode;
    uint32_t After;
    uint32_t Usec;
  };
  static const PauseOption Pause = [] {
    PauseOption O {0, 128, 50};
    const char* Env = getenv("MADEIRA_FEX_PAUSE");
    if (!Env) {
      return O;
    }
    auto Number = [](const char*& P, uint32_t Max, uint32_t& Out) {
      uint32_t V = 0;
      const char* Start = P;
      for (; *P && *P != ':'; ++P) {
        if (*P < '0' || *P > '9') {
          return false;
        }
        V = V * 10 + static_cast<uint32_t>(*P - '0');
        if (V > Max) {
          return false;
        }
      }
      if (P == Start || !V) {
        return false;
      }
      Out = V;
      return true;
    };
    if (!strcmp(Env, "wfe")) {
      O.Mode = 1;
    } else if (!strcmp(Env, "isb")) {
      O.Mode = 2;
    } else if (!strncmp(Env, "yield-os", 8) || !strncmp(Env, "yield-sw", 8) || !strncmp(Env, "wait-os", 7)) {
      const bool Wait = Env[0] == 'w';
      const bool Sw = !Wait && Env[6] == 's';
      const char* P = Env + (Wait ? 7 : 8);
      bool Good = true;
      if (*P == ':') {
        ++P;
        Good = Number(P, 4095, O.After);
        if (Good && Wait && *P == ':') {
          ++P;
          Good = Number(P, 5000, O.Usec);
        }
      }
      if (Good && !*P) {
        O.Mode = Wait ? 4 : Sw ? 5 : 3;
      }
    }
    if (O.Mode == 1 || O.Mode == 2) {
      LogMan::Msg::IFmt("[fex-pause] PAUSE compiles to {} (MADEIRA_FEX_PAUSE)", O.Mode == 1 ? "WFE" : "ISB");
    } else if (O.Mode) {
      LogMan::Msg::IFmt("[fex-pause] PAUSE is YIELD and every {}th one of a thread {} (MADEIRA_FEX_PAUSE={})", O.After,
                        O.Mode == 3 ? "gives the core up (swtch_pri)" :
                        O.Mode == 5 ? "lets a waiting thread in (swtch)" : "blocks the thread (thread_switch)",
                        Env);
    } else {
      LogMan::Msg::IFmt("[fex-pause] MADEIRA_FEX_PAUSE={} not understood: PAUSE stays YIELD", Env);
    }
    return O;
  }();
  if (Pause.Mode == 1) {
    wfe();
    return;
  }
  if (Pause.Mode == 2) {
    isb();
    return;
  }
#ifdef ARCHITECTURE_arm64ec
  if (Pause.Mode >= 3) {
    /* Darwin's Mach traps keep every register but x0 and set no flags the guest holds; x0, x1, x2 and x16 are
     * saved in TMP1-TMP4 (x10-x13 on ARM64EC) around the trap. SUB and CBZ, not CMP: NZCV is the guest's.
     * The count is this thread's: IosLastCallbackLR of its frame (see the patch's notes). */
    static_assert(offsetof(FEXCore::Core::CpuStateFrame, IosLastCallbackLR) % 8 == 0 &&
                  offsetof(FEXCore::Core::CpuStateFrame, IosLastCallbackLR) <= 32760,
                  "the PAUSE count is loaded with a scaled LDR");
    ARMEmitter::ForwardLabel Trap;
    ARMEmitter::ForwardLabel Done;
    ldr(TMP2, STATE, offsetof(FEXCore::Core::CpuStateFrame, IosLastCallbackLR));
    add(ARMEmitter::Size::i64Bit, TMP2, TMP2, 1);
    sub(ARMEmitter::Size::i64Bit, TMP3, TMP2, Pause.After);
    lsr(ARMEmitter::Size::i64Bit, TMP3, TMP3, 63); /* 0 once the count reached K (a stale witness value traps at once) */
    (void)cbz(ARMEmitter::Size::i64Bit, TMP3, &Trap);
    str(TMP2, STATE, offsetof(FEXCore::Core::CpuStateFrame, IosLastCallbackLR));
    yield();
    (void)b(&Done);

    (void)Bind(&Trap);
    str(ARMEmitter::XReg::zr, STATE, offsetof(FEXCore::Core::CpuStateFrame, IosLastCallbackLR));
    mov(ARMEmitter::Size::i64Bit, TMP1, ARMEmitter::Reg::r0);
    mov(ARMEmitter::Size::i64Bit, TMP2, ARMEmitter::Reg::r16);
    if (Pause.Mode == 4) {
      mov(ARMEmitter::Size::i64Bit, TMP3, ARMEmitter::Reg::r1);
      mov(ARMEmitter::Size::i64Bit, TMP4, ARMEmitter::Reg::r2);
      movz(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r0, 0);          /* MACH_PORT_NULL */
      movz(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r1, 3);          /* SWITCH_OPTION_DISPATCH_CONTENTION */
      movz(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r2, Pause.Usec); /* microseconds */
      movn(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r16, 60);        /* thread_switch, trap -61 */
    } else if (Pause.Mode == 5) {
      movn(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r16, 59);        /* swtch, trap -60 */
    } else {
      movn(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r16, 58);        /* swtch_pri, trap -59 */
    }
    svc(0x80);
    mov(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r0, TMP1);
    mov(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r16, TMP2);
    if (Pause.Mode == 4) {
      mov(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r1, TMP3);
      mov(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r2, TMP4);
    }
    (void)Bind(&Done);
    return;
  }
#endif
#endif
  yield();
}
'''


def patch(src):
    if MARKER in src:
        if src.count(NEW) != 1:
            raise ValueError("partial or changed pause-mode")
        return src
    if src.count(INCLUDE_ANCHOR) != 1 or src.count(OLD) != 1:
        raise ValueError("MiscOps.cpp's include or DEF_OP(Yield) not found once (FEX changed)")
    return src.replace(INCLUDE_ANCHOR, INCLUDE_ANCHOR + INCLUDE, 1).replace(OLD, NEW, 1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[-1])
    path = Path(sys.argv[1]) / MISC
    source = path.read_text()
    try:
        result = patch(source)
    except ValueError as error:
        sys.exit("patch-fex-ios-pause: " + str(error))
    if result == source:
        print("patch-fex-ios-pause: already in")
    else:
        path.write_text(result)
        print("FEX: MADEIRA_FEX_PAUSE=wfe|isb|yield-os[:K]|yield-sw[:K]|wait-os[:K[:U]] picks what x86 PAUSE compiles to (opt-in; YIELD otherwise)")
