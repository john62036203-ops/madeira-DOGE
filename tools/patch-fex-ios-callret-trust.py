#!/usr/bin/env python3
"""Opt-in: a RET takes the call-return stack's prediction on iOS again.

Madeira ml305 made every RET pop its call-return stack entry and then take
the L1 lookup anyway, while a wrong-branch crash was being hunted. Playport
(github.com/playportdev/playport, patches/fex/0006, The Playport authors,
GPL-3.0-or-later) takes upstream FEX's branch again and measured 5-7 % fewer
instructions a frame in Hollow Knight, on that title only. Here the same one
line is taken only when env.MADEIRA_CALLRET_TRUST = 1, read once per process,
so a game can be compared with and without it; unset, the emitted code is
what it was.

Fork-local build patch (tools/build-xtajit64.sh).
Usage: patch-fex-ios-callret-trust.py FEX/FEXCore/Source/Interface/Core/JIT/BranchOps.cpp
Idempotent; fails by name if the anchor moved.
"""
import sys

path = sys.argv[1]
s = open(path).read()
if "MADEIRA_CALLRET_TRUST" in s:
    print("already patched"); sys.exit(0)

old = """      (void)SkipFullLookup;
#else
      (void)cbz(ARMEmitter::Size::i64Bit, TMP1, &SkipFullLookup);
#endif
"""
new = """      /* madeira-doge (tools/patch-fex-ios-callret-trust.py), after Playport's
       * patches/fex/0006: env.MADEIRA_CALLRET_TRUST = 1 takes the prediction. */
      {
        static const bool MadTrust = [] {
          const char* E = getenv("MADEIRA_CALLRET_TRUST");
          const bool On = E && E[0] == '1';
          LogMan::Msg::EFmt("[callret] madeira-doge: a RET {} its call-return stack entry (env.MADEIRA_CALLRET_TRUST)",
                            On ? "branches to" : "does not trust");
          return On;
        }();
        if (MadTrust) {
          (void)cbz(ARMEmitter::Size::i64Bit, TMP1, &SkipFullLookup);
        }
      }
      (void)SkipFullLookup;
#else
      (void)cbz(ARMEmitter::Size::i64Bit, TMP1, &SkipFullLookup);
#endif
"""
if s.count(old) != 1:
    sys.exit("patch-fex-ios-callret-trust: anchor not found exactly once")
s = s.replace(old, new)
inc = '#include "Interface/Core/JIT/JITClass.h"\n'
if s.count(inc) != 1:
    sys.exit("patch-fex-ios-callret-trust: include anchor not found exactly once")
s = s.replace(inc, inc + "#include <FEXCore/Utils/LogManager.h>\n#include <cstdlib>\n")
open(path, "w").write(s)
print("patched")
