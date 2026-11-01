#!/usr/bin/env python3
"""madeira-doge: \\??\\GLOBALROOT\\??\\C:\\... file names.

On Windows \\??\\GLOBALROOT is a symbolic link to the root of the object
namespace, so \\??\\GLOBALROOT\\??\\C:\\dir\\file is the same file as
\\??\\C:\\dir\\file. Wine's nt_to_unix_file_name_no_root takes "GLOBALROOT" for
a DOS device name and fails with STATUS_OBJECT_PATH_NOT_FOUND (c000003a).

Age of Empires IV's protection (Aegis) opens its own RelicCardinal.exe that way
to read the data appended after the last section; without it its exception
handler declines every fake instruction and the game ends on an unhandled
c000001d (2026-11-02 00:56 log, MADEIRA_FILE_TRACE: two opens of
\\??\\GLOBALROOT\\??\\C:\\...\\RelicCardinal.exe, both c000003a).

The function now looks the name up without the \\??\\GLOBALROOT part (a local
copy of the attributes; the caller's are untouched). Only this exact form is
handled. Idempotent; exits non-zero when the anchor is missing.
Usage: patch-wine-globalroot.py [path/to/wine/dlls/ntdll/unix/file.c]
"""
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "wine/dlls/ntdll/unix/file.c"
src = open(path).read()
marker = "madeira-doge: [globalroot]"
if marker in src:
    print("patch-wine-globalroot: already applied")
    sys.exit(0)

anchor = (
    "    BOOLEAN is_unix = FALSE;\n"
    "\n"
    "    name     = attr->ObjectName->Buffer;\n"
    "    name_len = attr->ObjectName->Length / sizeof(WCHAR);\n"
    "\n"
    "    if (!name_len || name[0] != '\\\\') return STATUS_OBJECT_PATH_SYNTAX_BAD;\n"
)
if src.count(anchor) != 1:
    sys.exit("patch-wine-globalroot: anchor found %d times in %s" % (src.count(anchor), path))

new = (
    "    BOOLEAN is_unix = FALSE;\n"
    "    OBJECT_ATTRIBUTES gr_attr;  /* madeira-doge: [globalroot] */\n"
    "    UNICODE_STRING gr_name;\n"
    "\n"
    "    {\n"
    "        /* \\??\\GLOBALROOT\\??\\C:\\... is \\??\\C:\\... (Age of Empires IV's Aegis opens its own exe so) */\n"
    "        static const WCHAR grW[] = {'\\\\','?','?','\\\\','G','L','O','B','A','L','R','O','O','T',\n"
    "                                    '\\\\','?','?','\\\\'};\n"
    "        const UNICODE_STRING *on = attr->ObjectName;\n"
    "        if (on && on->Buffer && on->Length > sizeof(grW) &&\n"
    "            !wcsnicmp( on->Buffer, grW, ARRAY_SIZE(grW) ))\n"
    "        {\n"
    "            static int gr_n;\n"
    "            gr_name.Buffer = on->Buffer + 14;  /* the inner \\??\\ */\n"
    "            gr_name.Length = gr_name.MaximumLength = on->Length - 14 * sizeof(WCHAR);\n"
    "            gr_attr = *attr;\n"
    "            gr_attr.ObjectName = &gr_name;\n"
    "            attr = &gr_attr;\n"
    "            if (gr_n < 8 && ++gr_n <= 8)\n"
    "                fprintf( stderr, \"[globalroot] #%d %s -> without the \\\\??\\\\GLOBALROOT prefix\\n\",\n"
    "                         gr_n, debugstr_us( on ) );\n"
    "        }\n"
    "    }\n"
    "\n"
    "    name     = attr->ObjectName->Buffer;\n"
    "    name_len = attr->ObjectName->Length / sizeof(WCHAR);\n"
    "\n"
    "    if (!name_len || name[0] != '\\\\') return STATUS_OBJECT_PATH_SYNTAX_BAD;\n"
)
src = src.replace(anchor, new)
open(path, "w").write(src)
print("patch-wine-globalroot: \\??\\GLOBALROOT\\??\\ names resolve as \\??\\ in nt_to_unix_file_name_no_root")
