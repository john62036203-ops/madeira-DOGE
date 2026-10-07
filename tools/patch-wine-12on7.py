#!/usr/bin/env python3
"""A missing 12on7\\d3d12.dll stays missing.

Monster Hunter Rise (demo, build 165, log 2026-10-07 19:09) asks for
"12on7\\d3d12.dll" (Direct3D 12 for Windows 7). The file does not exist, and
the loader's mixed-arch fallback drops the folder and hands back
C:\\windows\\sysx64\\d3d12.dll. The game then treats our d3d12 as the Windows 7
one, asks its device for ID3D12DeviceDownlevel, is refused, and calls a
D3D12CreateDevice pointer it never filled (address 0).

The fallback lives in the PE ntdll, which is not rebuilt, so this is done at
the file layer: after a failed open of ...\\12on7\\d3d12.dll, the same thread's
next open of ...\\sysx64\\d3d12.dll reports "not found" once.
env MADEIRA_12ON7_DENY=0 turns it off.

Applied after tools/patch-wine-file-trace.py (same file). Idempotent; exits
non-zero when an anchor is missing.
Usage: patch-wine-12on7.py [path/to/wine/dlls/ntdll/unix/file.c]
"""
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "wine/dlls/ntdll/unix/file.c"
src = open(path).read()
marker = "madeira-doge: [12on7]"
if marker in src:
    print("patch-wine-12on7: already patched")
    sys.exit(0)

helper = r'''#ifdef WINE_IOS
/* madeira-doge: [12on7] (tools/patch-wine-12on7.py). */
static int madeira_12on7_tail( const WCHAR *w, unsigned int wl, const char *tail )
{
    unsigned int tl = strlen( tail ), i;
    if (!w || wl < tl) return 0;
    for (i = 0; i < tl; i++)
    {
        WCHAR c = w[wl - tl + i];
        if (c >= 'A' && c <= 'Z') c += 32;
        if (c == '/') c = '\\';
        if (c != (WCHAR)(unsigned char)tail[i]) return 0;
    }
    return 1;
}

static void madeira_12on7_gate( unsigned int *status, HANDLE *handle, const UNICODE_STRING *nt,
                                const OBJECT_ATTRIBUTES *attr )
{
    static int on = -1;
    static volatile unsigned int pending_tid;
    static volatile void *pending_peb;
    const WCHAR *w = NULL;
    unsigned int wl = 0, tid;

    if (on < 0)
    {
        const char *e = getenv( "MADEIRA_12ON7_DENY" );
        on = !(e && e[0] == '0');
    }
    if (!on) return;
    if (nt && nt->Buffer) { w = nt->Buffer; wl = nt->Length / sizeof(WCHAR); }
    else if (attr && attr->ObjectName && attr->ObjectName->Buffer)
    { w = attr->ObjectName->Buffer; wl = attr->ObjectName->Length / sizeof(WCHAR); }
    if (wl < 9 || !madeira_12on7_tail( w, wl, "d3d12.dll" )) return;
    tid = HandleToULong( NtCurrentTeb()->ClientId.UniqueThread );
    if (madeira_12on7_tail( w, wl, "\\12on7\\d3d12.dll" ))
    {
        if (*status)
        {
            pending_peb = NtCurrentTeb()->Peb;
            pending_tid = tid;
        }
        return;
    }
    if (!madeira_12on7_tail( w, wl, "\\sysx64\\d3d12.dll" )) return;
    if (pending_tid != tid || pending_peb != (void *)NtCurrentTeb()->Peb) return;
    pending_tid = 0;
    pending_peb = NULL;
    if (*status) return;
    if (handle && *handle) { NtClose( *handle ); *handle = 0; }
    *status = STATUS_OBJECT_NAME_NOT_FOUND;
    dprintf( 2, "[12on7] the missing 12on7\\d3d12.dll is not replaced by the system d3d12.dll "
             "(MADEIRA_12ON7_DENY=0 restores the fallback)\n" );
}
#endif

'''

anchor_fn = "NTSTATUS WINAPI NtCreateFile( HANDLE *handle, ACCESS_MASK access, OBJECT_ATTRIBUTES *attr,"
if src.count(anchor_fn) != 1:
    sys.exit("patch-wine-12on7: NtCreateFile anchor not found")
first = min(i for i in (src.find("static NTSTATUS create_file("), src.find(anchor_fn)) if i >= 0)
line_start = src.rfind("\n/***", 0, first)
ins = line_start + 1 if line_start >= 0 else first
src = src[:ins] + helper + src[ins:]

call_anchor = '    madeira_file_trace( "open", status, &nt_name, attr, disposition, access );\n'
if src.count(call_anchor) != 1:
    sys.exit("patch-wine-12on7: file-trace call anchor not found (apply patch-wine-file-trace.py first)")
src = src.replace(call_anchor, "    madeira_12on7_gate( &status, handle, &nt_name, attr );\n" + call_anchor)

open(path, "w").write(src)
print("patch-wine-12on7: applied")
