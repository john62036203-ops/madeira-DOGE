/*
 * madeira-doge: wraps wine/dlls/win32u/window.c (compiled unchanged) and adds
 * the opt-in window clamp, env.MADEIRA_WINDOW_CLAMP = 1.
 *
 * A game in "borderless window" mode sizes its top-level window from its own
 * saved resolution and ignores the desktop: Monster Hunter Wilds opens
 * 1926x1112 on a 1280x720 desktop (2026-10-17 14:18 and 2026-10-18 logs) and
 * renders at that size, which on an 8 GB phone is the memory wall. The in-game
 * Options are the only way to lower it, and the game dies before they can be
 * reached. With the clamp on, a top-level window asked to be larger than the
 * desktop (NtUserCreateWindowEx or NtUserSetWindowPos) is given the desktop
 * size at 0,0 instead; the program sees an ordinary WM_SIZE and most engines
 * rebuild their swap chain and render targets at the new client size. Child
 * windows, windows that fit, and sessions without the switch are untouched.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NtUserCreateWindowEx upstream_NtUserCreateWindowEx
#define NtUserSetWindowPos   upstream_NtUserSetWindowPos
#include "../../wine/dlls/win32u/window.c"
#undef NtUserCreateWindowEx
#undef NtUserSetWindowPos

static int ios_window_clamp_on(void)
{
    static int on = -1;
    if (on < 0)
    {
        const char *e = getenv( "MADEIRA_WINDOW_CLAMP" );   /* 1: a top-level window larger than the desktop is sized to the desktop */
        on = e && e[0] == '1';
    }
    return on;
}

/* Clamp cx/cy (and x/y) to the desktop; 1 if anything changed. */
static int ios_window_clamp( const char *who, HWND hwnd, INT *x, INT *y, INT *cx, INT *cy )
{
    int sw = get_system_metrics( SM_CXSCREEN ), sh = get_system_metrics( SM_CYSCREEN );
    int changed = 0;
    static unsigned n;

    if (sw <= 0 || sh <= 0) return 0;
    if (*cx > sw) { *cx = sw; *x = 0; changed = 1; }
    if (*cy > sh) { *cy = sh; *y = 0; changed = 1; }
    if (changed && n++ < 16)
        fprintf( stderr, "[window-clamp] madeira-doge: %s hwnd %p asked for %dx%d, larger than the %dx%d desktop -- "
                 "sized to the desktop at 0,0 (env.MADEIRA_WINDOW_CLAMP)\n", who, hwnd, *cx, *cy, sw, sh );
    return changed;
}

HWND WINAPI NtUserCreateWindowEx( DWORD ex_style, UNICODE_STRING *class_name,
                                  UNICODE_STRING *version, UNICODE_STRING *window_name,
                                  DWORD style, INT x, INT y, INT cx, INT cy,
                                  HWND parent, HMENU menu, HINSTANCE class_instance, void *params,
                                  DWORD flags, HINSTANCE instance, const WCHAR *class, BOOL ansi )
{
    if (ios_window_clamp_on() && !(style & WS_CHILD) && cx > 0 && cy > 0 &&
        cx != CW_USEDEFAULT && cy != CW_USEDEFAULT)
    {
        int cw = cx, ch = cy, cxp = x, cyp = y;
        if (ios_window_clamp( "CreateWindowEx", 0, &cxp, &cyp, &cw, &ch ))
        {
            cx = cw; cy = ch;
            if (x != CW_USEDEFAULT) x = cxp;
            if (y != CW_USEDEFAULT) y = cyp;
        }
    }
    return upstream_NtUserCreateWindowEx( ex_style, class_name, version, window_name, style, x, y, cx, cy,
                                          parent, menu, class_instance, params, flags, instance, class, ansi );
}

BOOL WINAPI NtUserSetWindowPos( HWND hwnd, HWND after, INT x, INT y, INT cx, INT cy, UINT flags )
{
    if (ios_window_clamp_on() && !(flags & SWP_NOSIZE) && cx > 0 && cy > 0 &&
        !(get_window_long( hwnd, GWL_STYLE ) & WS_CHILD))
    {
        int cw = cx, ch = cy, cxp = x, cyp = y;
        if (ios_window_clamp( "SetWindowPos", hwnd, &cxp, &cyp, &cw, &ch ))
        {
            cx = cw; cy = ch;
            if (flags & SWP_NOMOVE) { flags &= ~SWP_NOMOVE; x = 0; y = 0; }   /* the given x,y meant nothing */
            else { x = cxp; y = cyp; }
        }
    }
    return upstream_NtUserSetWindowPos( hwnd, after, x, y, cx, cy, flags );
}
