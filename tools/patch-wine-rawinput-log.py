#!/usr/bin/env python3
"""[rawinput]: say whether a game uses Raw Input, and for what.

Sora no Kiseki the 1st (demo, builds 152-155, 2026-10-07) shows its title menu
and takes no input: it never reads XInput, and with player 1 as a HID DualSense
it opens the device twice and never reads a report. Raw Input (WM_INPUT) is
the remaining way a game reads a pad, keys and the mouse, and nothing in the
log named it. Print the registrations (usage page, usage, flags, target), the
device list's size and the device-info queries, each capped.

Patches wine/dlls/win32u/rawinput.c in place. Idempotent; fails by name if an
anchor moves. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("wine/dlls/win32u/rawinput.c")
MARKER = "madeira-doge: rawinput-log"

PAIRS = [
    ("""#include <stdbool.h>
#include <pthread.h>
""",
     """#include <stdbool.h>
#include <pthread.h>
#include <stdio.h>   /* madeira-doge: rawinput-log (tools/patch-wine-rawinput-log.py) */
"""),
    ("""    pthread_mutex_unlock( &rawinput_mutex );

    if (!device_list)
    {
        *device_count = count;
        return 0;
    }
""",
     """    pthread_mutex_unlock( &rawinput_mutex );

    {
        static int logged;
        if (logged++ < 8)
            fprintf( stderr, "[rawinput] GetRawInputDeviceList -> %u devices (caller room %u, %s)\\n",
                     count, *device_count, device_list ? "filling" : "counting" );
    }

    if (!device_list)
    {
        *device_count = count;
        return 0;
    }
"""),
    ("""    TRACE( "handle %p, command %#x, data %p, data_size %p.\\n", handle, command, data, data_size );

    if (!data_size)
    {
        RtlSetLastWin32Error( ERROR_NOACCESS );
        return ~0u;
""",
     """    TRACE( "handle %p, command %#x, data %p, data_size %p.\\n", handle, command, data, data_size );

    {
        static int logged;   /* command: 0x20000005 preparsed, 0x20000007 name, 0x2000000b info */
        if (logged++ < 24)
            fprintf( stderr, "[rawinput] GetRawInputDeviceInfo handle=%p command=%#x\\n", handle, command );
    }

    if (!data_size)
    {
        RtlSetLastWin32Error( ERROR_NOACCESS );
        return ~0u;
"""),
    ("""        TRACE( "device %u: page %#x, usage %#x, flags %#x, target %p.\\n", i, devices[i].usUsagePage,
               devices[i].usUsage, devices[i].dwFlags, devices[i].hwndTarget );
""",
     """        TRACE( "device %u: page %#x, usage %#x, flags %#x, target %p.\\n", i, devices[i].usUsagePage,
               devices[i].usUsage, devices[i].dwFlags, devices[i].hwndTarget );
        {
            static int logged;   /* page 1: usage 2 mouse, 4 joystick, 5 gamepad, 6 keyboard */
            if (logged++ < 16)
                fprintf( stderr, "[rawinput] register %u/%u: page %#x usage %#x flags %#x target %p\\n", i + 1,
                         device_count, devices[i].usUsagePage, devices[i].usUsage, (unsigned)devices[i].dwFlags,
                         devices[i].hwndTarget );
        }
"""),
]


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("rawinput.c: already patched")
        return 0
    for old, new in PAIRS:
        if s.count(old) != 1:
            sys.exit(f"patch-wine-rawinput-log: anchor found {s.count(old)} times (want 1) in {PATH}:\n{old}")
        s = s.replace(old, new)
    PATH.write_text(s)
    print("rawinput.c: patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
