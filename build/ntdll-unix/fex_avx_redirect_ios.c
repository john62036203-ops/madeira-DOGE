/*
 * madeira-doge: give the AVX FEX module to the Steam GAME only, not to the
 * Madeira Dock host or Valve's client.
 *
 * The AVX opt-in is a separately built FEX module, xtajit64-avx.dll
 * (tools/build-xtajit64.sh). It is built from the FEX submodule, which is NOT
 * the source of the shipped xtajit64.dll (the WoW64 series' build). Linking it
 * in as system32\xtajit64.dll for a whole Dock session therefore also moved
 * dockhost.exe and steamclient64.dll onto a different FEX, and the first such
 * session hung inside steamclient64's import loading (20+ Dock sessions on the
 * shipped module never did).
 *
 * In a Dock session WineProcessBridge.m now leaves xtajit64.dll alone and sets
 * MADEIRA_FEX_AVX_GAME_ONLY=1. Every Wine process opens its ARM64EC emulator
 * as C:\windows\system32\xtajit64.dll (PE ntdll load_arm64ec_module); here
 * that one open is pointed at xtajit64-avx.dll (already in system32 and
 * sysx64, linked from the arm64ec-windows bundle) when the opening process's
 * image lives under a \steamapps\common\ folder. The loader still records the
 * module under its requested name, so nothing else sees a difference.
 *
 * file.c is compiled with NtCreateFile/NtOpenFile renamed to
 * wine_impl_NtCreateFile/wine_impl_NtOpenFile (build.sh), and these wrappers
 * take the real names, so the syscall table and every other caller reach them.
 */
#include "config.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "ntstatus.h"
#define WIN32_NO_STATUS
#include "windef.h"
#include "winbase.h"
#include "winternl.h"

#ifndef ARRAY_SIZE
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#endif

NTSTATUS WINAPI wine_impl_NtCreateFile( HANDLE *handle, ACCESS_MASK access, OBJECT_ATTRIBUTES *attr,
                                        IO_STATUS_BLOCK *io, LARGE_INTEGER *alloc_size,
                                        ULONG attributes, ULONG sharing, ULONG disposition,
                                        ULONG options, void *ea_buffer, ULONG ea_length );
NTSTATUS WINAPI wine_impl_NtOpenFile( HANDLE *handle, ACCESS_MASK access, OBJECT_ATTRIBUTES *attr,
                                      IO_STATUS_BLOCK *io, ULONG sharing, ULONG options );

static int fex_avx_game_only = -1;

static WCHAR lower_w( WCHAR c )
{
    return (c >= 'A' && c <= 'Z') ? (WCHAR)(c + ('a' - 'A')) : c;
}

/* Case-insensitive: does s (len chars) end with the ASCII suffix? */
static BOOL ends_with_ci( const WCHAR *s, size_t len, const char *suffix )
{
    size_t n = strlen( suffix ), i;
    if (len < n) return FALSE;
    for (i = 0; i < n; i++)
        if (lower_w( s[len - n + i] ) != (WCHAR)suffix[i]) return FALSE;
    return TRUE;
}

static BOOL contains_ci( const WCHAR *s, size_t len, const char *needle )
{
    size_t n = strlen( needle ), i, j;
    if (len < n) return FALSE;
    for (i = 0; i + n <= len; i++)
    {
        for (j = 0; j < n; j++)
            if (lower_w( s[i + j] ) != (WCHAR)needle[j]) break;
        if (j == n) return TRUE;
    }
    return FALSE;
}

static BOOL current_image_is_steam_game( char *image, size_t image_size )
{
    TEB *teb = NtCurrentTeb();
    PEB *peb = teb ? teb->Peb : NULL;
    RTL_USER_PROCESS_PARAMETERS *pp = peb ? peb->ProcessParameters : NULL;
    const WCHAR *path;
    size_t len, k, start = 0, o = 0;

    if (!pp || !(path = pp->ImagePathName.Buffer)) return FALSE;
    if (!(pp->Flags & PROCESS_PARAMS_FLAG_NORMALIZED))
        path = (const WCHAR *)((const char *)pp + (ULONG_PTR)path);
    len = pp->ImagePathName.Length / sizeof(WCHAR);
    for (k = 0; k < len; k++) if (path[k] == '\\' || path[k] == '/') start = k + 1;
    for (k = start; k < len && o + 1 < image_size; k++)
        image[o++] = path[k] < 128 ? (char)path[k] : '?';
    image[o] = 0;
    return contains_ci( path, len, "\\steamapps\\common\\" );
}

/* Returns TRUE and fills *redirect (backed by buf) when this open should go to
 * xtajit64-avx.dll instead. */
static BOOL fex_avx_redirect( const OBJECT_ATTRIBUTES *attr, UNICODE_STRING *redirect,
                              WCHAR *buf, size_t buf_chars )
{
    static const char suffix[] = "\\xtajit64.dll";
    static const WCHAR avx_tail[] = { 'x','t','a','j','i','t','6','4','-','a','v','x','.','d','l','l' };
    const UNICODE_STRING *name;
    size_t len, keep;
    char image[64];

    if (fex_avx_game_only < 0)
    {
        const char *e = getenv( "MADEIRA_FEX_AVX_GAME_ONLY" );
        fex_avx_game_only = (e && e[0] == '1') ? 1 : 0;
    }
    if (!fex_avx_game_only || !attr || !(name = attr->ObjectName) || !name->Buffer) return FALSE;
    len = name->Length / sizeof(WCHAR);
    if (!ends_with_ci( name->Buffer, len, suffix )) return FALSE;
    if (!current_image_is_steam_game( image, sizeof(image) )) return FALSE;

    keep = len - (sizeof("xtajit64.dll") - 1);   /* everything up to and including the last '\' */
    if (keep + ARRAY_SIZE(avx_tail) > buf_chars) return FALSE;
    memcpy( buf, name->Buffer, keep * sizeof(WCHAR) );
    memcpy( buf + keep, avx_tail, sizeof(avx_tail) );
    redirect->Buffer = buf;
    redirect->Length = (USHORT)((keep + ARRAY_SIZE(avx_tail)) * sizeof(WCHAR));
    redirect->MaximumLength = redirect->Length;
    dprintf( 2, "[fex-avx] %s: xtajit64.dll -> xtajit64-avx.dll (AVX/AVX2 for the game only)\n", image );
    return TRUE;
}

NTSTATUS WINAPI NtCreateFile( HANDLE *handle, ACCESS_MASK access, OBJECT_ATTRIBUTES *attr,
                              IO_STATUS_BLOCK *io, LARGE_INTEGER *alloc_size,
                              ULONG attributes, ULONG sharing, ULONG disposition,
                              ULONG options, void *ea_buffer, ULONG ea_length )
{
    WCHAR buf[MAX_PATH + 32];
    UNICODE_STRING redirect;

    if (fex_avx_redirect( attr, &redirect, buf, ARRAY_SIZE(buf) ))
    {
        OBJECT_ATTRIBUTES alt = *attr;
        NTSTATUS status;
        alt.ObjectName = &redirect;
        status = wine_impl_NtCreateFile( handle, access, &alt, io, alloc_size, attributes, sharing,
                                         disposition, options, ea_buffer, ea_length );
        if (status != STATUS_OBJECT_NAME_NOT_FOUND && status != STATUS_OBJECT_PATH_NOT_FOUND)
            return status;
        dprintf( 2, "[fex-avx] xtajit64-avx.dll not found (%08x) -- using xtajit64.dll\n", (unsigned int)status );
    }
    return wine_impl_NtCreateFile( handle, access, attr, io, alloc_size, attributes, sharing,
                                   disposition, options, ea_buffer, ea_length );
}

NTSTATUS WINAPI NtOpenFile( HANDLE *handle, ACCESS_MASK access, OBJECT_ATTRIBUTES *attr,
                            IO_STATUS_BLOCK *io, ULONG sharing, ULONG options )
{
    return NtCreateFile( handle, access, attr, io, NULL, 0, sharing, FILE_OPEN, options, NULL, 0 );
}
