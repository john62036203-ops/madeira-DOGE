#!/usr/bin/env python3
"""Available memory up to the app's own limit (opt-in, madeira.cfg avail-phys = 1).

get_performance_info() fills SystemPerformanceInformation.AvailablePages, which
GlobalMemoryStatusEx reports as ullAvailPhys, from the whole phone's free pages.
iOS ends the app at its own memory limit well before the phone runs out, so a
Windows program never sees memory run short. The value now passes through
ios_avail_phys() (build/ntdll-unix/virtual_ios.c), which with avail-phys = 1
returns what remains before this app's limit when that is smaller, and its
argument unchanged otherwise.

Same change as willfaust/wine madeira-lgpl 4ece89b5 (bahacan16's PR #37), which
is not in this repository's wine pin.
Usage: patch-wine-avail-phys.py wine/dlls/ntdll/unix/system.c
"""
import sys

path = sys.argv[1]
src = open(path).read()
if "ios_avail_phys" in src:
    print("already patched"); sys.exit(0)
anchor = "    info->AvailablePages      = freeram / page_size;\n"
if src.count(anchor) != 1:
    sys.exit("patch-wine-avail-phys: AvailablePages anchor not found exactly once")
src = src.replace(anchor, """#ifdef __APPLE__
    {
        /* madeira-doge: avail-phys (tools/patch-wine-avail-phys.py) */
        extern unsigned long long ios_avail_phys( unsigned long long host_free );
        freeram = ios_avail_phys( freeram );
    }
#endif
""" + anchor)
open(path, "w").write(src)
print("patched " + path)
