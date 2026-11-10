#!/usr/bin/env python3
"""FEX: what x86 PAUSE compiles to on iOS (MADEIRA_FEX_PAUSE=wfe or isb; opt-in).

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
  /* madeira-doge pause-mode (Playport fex 0083): MADEIRA_FEX_PAUSE=wfe or isb, what x86 PAUSE compiles to; unset or
   * anything else keeps YIELD, which Apple's cores treat as a NOP. Read once per process. */
  static const int PauseMode = [] {
    const char* Env = getenv("MADEIRA_FEX_PAUSE");
    const int Mode = Env && !strcmp(Env, "wfe") ? 1 : Env && !strcmp(Env, "isb") ? 2 : 0;
    if (Mode) {
      LogMan::Msg::IFmt("[fex-pause] PAUSE compiles to {} (MADEIRA_FEX_PAUSE)", Mode == 1 ? "WFE" : "ISB");
    }
    return Mode;
  }();
  if (PauseMode == 1) {
    wfe();
    return;
  }
  if (PauseMode == 2) {
    isb();
    return;
  }
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
        print("FEX: MADEIRA_FEX_PAUSE=wfe|isb picks what x86 PAUSE compiles to (opt-in; YIELD otherwise)")
