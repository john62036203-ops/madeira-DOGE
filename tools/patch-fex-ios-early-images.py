#!/usr/bin/env python3
"""Register the images the loader mapped before xtajit64 existed.

FEX's InvalidationTracker learns an image's executable sections from
NotifyMapViewOfSection (queued as PendingImageMaps until ProcessInit) or from
PE ntdll's loader-boundary arm64ec_notify_image_map (which needs the module's
NotifyImageMap export, i.e. xtajit64 already loaded). ucrtbase.dll,
kernel32.dll and kernelbase.dll are mapped by the loader BEFORE xtajit64 is,
on a path that reaches neither, so in every process their sections are
missing from XIntervals (no "[iOS-xins]" line for them in any log). That does
not matter while x64 code only calls their EC entry points through the
dispatcher, but an x64 caller that lands on one of their x64 thunks -- the
`jmp [rip+slot]` fast-forward sequence of an export, e.g. kernel32+0x35f60
GetModuleHandleA called from libwinpthread-1.dll (KytyPS5's kyty_emulator.exe,
2026-10-28 07:57 / 09:39 logs) -- gets "[iOS-xquery] MISS", "NoExec
instruction in entry block", and the process dies on the NoExec trampoline's
null read (c0000005 at addr 0).

Now ProcessInit, after replaying the pending maps, walks the PEB loader list
(InLoadOrderModuleList) and registers every module that is not the main image
or ntdll (both already done). HandleImageMap is idempotent, so a module that
did reach a notification is merely re-inserted. Log line:
"[early-images] madeira-doge N module(s) from the loader list".

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-early-images.py FEX/Source/Windows/ARM64EC/Module.cpp
Idempotent; fails by name if the anchor moved.
"""
import sys

path = sys.argv[1]
s = open(path).read()

MARK = "[early-images] madeira-doge"
if MARK in s:
    print("patch-fex-ios-early-images: already applied")
    sys.exit(0)

old = """  /* ml190: replay any image maps that arrived before the trackers existed. */
  for (size_t i = 0; i < PendingImageMapCount; i++) {
    HandleImageMap(PendingImageMaps[i]);
  }
  PendingImageMapCount = 0;
"""
new = """  /* ml190: replay any image maps that arrived before the trackers existed. */
  for (size_t i = 0; i < PendingImageMapCount; i++) {
    HandleImageMap(PendingImageMaps[i]);
  }
  PendingImageMapCount = 0;

  /* madeira-doge (tools/patch-fex-ios-early-images.py): the loader mapped
   * ucrtbase/kernel32/kernelbase before this module existed and that path
   * reaches neither NotifyMapViewOfSection nor NotifyImageMap, so their
   * sections were never in the tracker; an x64 caller landing on one of
   * their x64 export thunks got "NoExec instruction in entry block". Walk
   * the PEB loader list (InLoadOrderModuleList at PEB_LDR_DATA+0x10, DllBase
   * at LDR_DATA_TABLE_ENTRY+0x30 -- raw offsets, independent of the header)
   * and register whatever is loaded; HandleImageMap is idempotent. */
  {
    auto* Peb = reinterpret_cast<__TEB*>(NtCurrentTeb())->Peb;
    auto* Ldr = reinterpret_cast<uint8_t*>(Peb->LdrData);
    unsigned Registered = 0;
    if (Ldr) {
      auto* Head = reinterpret_cast<LIST_ENTRY*>(Ldr + 0x10);
      unsigned Walked = 0;
      for (auto* E = Head->Flink; E && E != Head && Walked < 1024; E = E->Flink, Walked++) {
        const uint64_t Base = *reinterpret_cast<const uint64_t*>(reinterpret_cast<const uint8_t*>(E) + 0x30);
        if (!Base || Base == reinterpret_cast<uint64_t>(MainModule) || Base == NtDllBase) {
          continue;
        }
        HandleImageMap(Base);
        Registered++;
      }
    }
    LogMan::Msg::EFmt("[early-images] madeira-doge {} module(s) from the loader list registered with the tracker", Registered);
  }
"""
if old not in s:
    sys.exit("patch-fex-ios-early-images: anchor not found in %s" % path)
s = s.replace(old, new, 1)
open(path, "w").write(s)
print("patch-fex-ios-early-images: applied")
