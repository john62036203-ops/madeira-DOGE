#!/usr/bin/env python3
"""Print the whole text of a game's fatal report, not its first 110 characters.

signal_arm64ec.c's ml812 dump prints the message of the 0x4000/0x8000
software-report exceptions (Unreal's LowLevelFatalError) through
ios_exc_dump_str, which stops at 110 characters -- the source path alone
fills that, so the reason is cut off (Dynasty Warriors 3 Complete Edition
Remastered demo, build 282, log 2026-10-20 22:22: "LowLevelFatalError
[File:F:\\EpicGames\\UnrealEngine\\Engine\\Source\\Runtime\\RHICore\\Private\\
RHICoreTransientResou"). After that line the rest of the string (up to 1100
characters) is printed as "[exc] ml812   FATAL report text +N: ..." lines of
110 characters, until the terminator.

Patches wine/dlls/ntdll/signal_arm64ec.c in place. Idempotent; fails by name
if the anchor moves. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("wine/dlls/ntdll/signal_arm64ec.c")
MARKER = "madeira-doge: whole fatal text"

OLD = """                        ios_exc_dump_str( "FATAL report message", msg, 200, 1 );
"""
NEW = """                    {   /* madeira-doge: whole fatal text (tools/patch-wine-fatal-text.py) */
                        static WCHAR fw[1100];
                        SIZE_T fg = 0, fn, fi, fo;
                        ios_exc_dump_str( "FATAL report message", msg, 200, 1 );
                        if (NtReadVirtualMemory( GetCurrentProcess(), (void *)msg, fw, sizeof(fw), &fg ) || !fg)
                        {
                            fg = 0;   /* a page edge: try the first 4 KB-aligned part */
                            NtReadVirtualMemory( GetCurrentProcess(), (void *)msg, fw,
                                                 0x1000 - (msg & 0xfff), &fg );
                        }
                        fn = fg / sizeof(WCHAR);
                        for (fi = 0; fi < fn && fw[fi]; fi++) ;
                        fn = fi;
                        for (fo = 110; fo < fn; fo += 110)
                        {
                            char line[112];
                            SIZE_T k;
                            for (k = 0; k < 110 && fo + k < fn; k++)
                            {
                                WCHAR c = fw[fo + k];
                                line[k] = (c >= 32 && c < 127) ? (char)c : '.';
                            }
                            line[k] = 0;
                            ERR( "[exc] ml812   FATAL report text +%u: \\"%s\\"\\n", (unsigned int)fo, line );
                        }
                    }
"""


def main():
    if not PATH.exists():
        sys.exit(f"patch-wine-fatal-text: {PATH} not found (run from the repository root)")
    src = PATH.read_text()
    if MARKER in src:
        print("patch-wine-fatal-text: already applied")
        return
    if src.count(OLD) != 1:
        sys.exit("patch-wine-fatal-text: anchor 'FATAL report message' call not found exactly once")
    PATH.write_text(src.replace(OLD, NEW))
    print("patch-wine-fatal-text: applied")


if __name__ == "__main__":
    main()
