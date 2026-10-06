#!/usr/bin/env python3
"""Print the text of a hard error the game raises.

NtRaiseHardError is a stub: a game that reports a fatal condition through it
(the message box of last resort) leaves "NtRaiseHardError ...: stub" in the log
and nothing of what it meant to say. MHR's Sunbreak demo (build 142, log
2026-10-07 00:18) raised 0x50000018 with four parameters and ended itself with
exit code 0xdeadc0de; the text is the only account of why. The stub now prints
each string parameter as a [hard-error] line (UTF-8, at most 400 characters
each, first 8 errors of a process). The return value is unchanged.

Patches wine/dlls/ntdll/unix/system.c in place. Idempotent; fails by name if
the anchor moves. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("wine/dlls/ntdll/unix/system.c")
MARKER = "madeira-doge: hard error text"

OLD = """    FIXME( "%#08x %u %#x %p %u %p: stub\\n", status, count, params_mask, params, option, response );
    return STATUS_NOT_IMPLEMENTED;
"""
NEW = """    FIXME( "%#08x %u %#x %p %u %p: stub\\n", status, count, params_mask, params, option, response );
    {   /* madeira-doge: hard error text (tools/patch-wine-harderror-text.py) */
        static int said;
        ULONG i;
        if (params && said < 8)
        {
            said++;
            for (i = 0; i < count && i < 8; i++)
            {
                if (params_mask & (1u << i))
                {
                    const UNICODE_STRING *us = params[i];
                    char out[1300];
                    unsigned int n = 0, j, len;
                    if (!us || !us->Buffer) continue;
                    len = us->Length / sizeof(WCHAR);
                    for (j = 0; j < len && j < 400 && n + 4 < sizeof(out); j++)
                    {
                        unsigned int c = us->Buffer[j];
                        if (c == '\\n' || c == '\\r') out[n++] = ' ';
                        else if (c < 0x20) out[n++] = '?';
                        else if (c < 0x80) out[n++] = (char)c;
                        else if (c < 0x800) { out[n++] = (char)(0xc0 | (c >> 6)); out[n++] = (char)(0x80 | (c & 0x3f)); }
                        else { out[n++] = (char)(0xe0 | (c >> 12)); out[n++] = (char)(0x80 | ((c >> 6) & 0x3f)); out[n++] = (char)(0x80 | (c & 0x3f)); }
                    }
                    out[n] = 0;
                    fprintf( stderr, "[hard-error] madeira-doge status=%08x param %u text (%u chars): %s\\n",
                             (unsigned int)status, (unsigned int)i, len, out );
                }
                else
                    fprintf( stderr, "[hard-error] madeira-doge status=%08x param %u value: %p\\n",
                             (unsigned int)status, (unsigned int)i, params[i] );
            }
        }
    }
    return STATUS_NOT_IMPLEMENTED;
"""


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("system.c: already patched")
        return 0
    if s.count(OLD) != 1:
        sys.exit(f"patch-wine-harderror-text: anchor found {s.count(OLD)} times (want 1) in {PATH}")
    PATH.write_text(s.replace(OLD, NEW))
    print("system.c: patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
