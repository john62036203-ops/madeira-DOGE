#!/bin/bash
# Build Wine PE DLLs that upstream's arm64ec-windows set does not ship but
# games import (and, since ml2106, xinput1_1-1_4 with host rumble; see below): older VC++ runtimes (Crysis's Bin64\Crysis64.exe needs
# msvcr80), D3DX9/10/11, d3d10, avifil32, XAudio2, dinput, RichEdit (the
# Rockstar Games SDK / Launcher installers load Msftedit.dll and gdiplus.dll). Configured the way
# upstream's build/wine-pe/build-ntdll.sh configures wine/build-arm64ec;
# stripped and padded by 64 KB past SizeOfImage like the shipped builtins.
# comctl32_v6: Common Controls 6 (TaskDialogIndirect, ordinal 345). Without it
# the amd64 Common-Controls assembly is never seeded (WineProcessBridge.m),
# x64 programs get the v5 comctl32, and RE Engine's error dialog died as
# "Unimplemented function COMCTL32.dll.345" instead of showing its message.
# Media Foundation for 64-bit games: winegstreamer and the byte stream handler /
# decoder front ends that forward to it (docs/MEDIA.md). RE Requiem's demo
# aborts with "Failed to create SourceReader with registered byte stream
# handler (c00d36c4)" when mfmp4srcsnk.dll and winegstreamer.dll are missing.
# The unix side is bound for 64-bit processes only with MADEIRA_WG_64BIT=1.
# mfmp4srcsnk/mfsrcsnk/winedmo are left out on purpose: winedmo has no unix
# side here, and with them missing the source resolver falls back to
# winegstreamer's byte stream handler, which is the path that has one.
# A DLL upstream already ships is never replaced. Run from the repository
# root; needs llvm-mingw on PATH (or MINGW) and the native wine tools.
#   usage: build-wine-extra-dlls.sh [native tools dir]
set -u
R="$(pwd)"
MINGW="${MINGW:-$R/toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin}"
export PATH="$MINGW:$PATH"
TOOLS="${1:-}"
B="${WINE_EC_BUILD:-$R/wine/build-arm64ec}"
SHIP="${SHIP_DIR:-$R/app/Madeira/arm64ec-windows}"
JOBS="$(sysctl -n hw.ncpu 2>/dev/null || nproc)"

WANT="msvcr70 msvcr71 msvcr80 msvcr90 msvcr100 msvcr110 msvcrt20 msvcrt40 msvcirt
      msvcp60 msvcp70 msvcp71 msvcp80 msvcp90 msvcp100 msvcp110 msvcp120
      vcomp vcomp90 vcomp100 vcomp110 vcomp120 vcomp140
      d3d10 d3d10_1 avifil32 msvfw32 dinput
      comctl32_v6
      wbemprox wbemdisp wmiutils
      riched20 riched32 msftedit gdiplus mlang usp10 cabinet sspicli msxml3 msxml6
      msasn1 wldp hnetcfg msctf xmllite netprofm d2d1 wmvcore winegstreamer
      xaudio2_0 xaudio2_1 xaudio2_2 xaudio2_3 xaudio2_4 xaudio2_5 xaudio2_6 xaudio2_7 xaudio2_8 xaudio2_9
      x3daudio1_0 x3daudio1_1 x3daudio1_2 x3daudio1_3 x3daudio1_4 x3daudio1_5 x3daudio1_6 x3daudio1_7
      xapofx1_1 xapofx1_2 xapofx1_3 xapofx1_4 xapofx1_5
      d3dcompiler_33 d3dcompiler_34 d3dcompiler_35 d3dcompiler_36 d3dcompiler_37 d3dcompiler_38
      d3dcompiler_39 d3dcompiler_40 d3dcompiler_41 d3dcompiler_42 d3dcompiler_46
      d3dx10_33 d3dx10_34 d3dx10_35 d3dx10_36 d3dx10_37 d3dx10_38 d3dx10_39 d3dx10_40 d3dx10_41 d3dx10_42 d3dx10_43
      d3dx11_42 d3dx11_43
      winegstreamer msmpeg2vdec wmadmod wmvdecod
      msauddecmft mp3dmod colorcnv resampledmo msvproc mferror"
for n in $(seq 24 42); do WANT="$WANT d3dx9_$n"; done

shipped() { ls "$SHIP" | tr 'A-Z' 'a-z' | grep -qx "$1.dll"; }
targets=""; todo=""
for d in $WANT; do
    [ -d "$R/wine/dlls/$d" ] || continue
    shipped "$d" && continue
    targets="$targets dlls/$d/arm64ec-windows/$d.dll"; todo="$todo $d"
done
# ml2106: the one exception to "never replaces a shipped DLL". xinput1_1-1_4
# (one source, dlls/xinput1_3/main.c) are rebuilt with
# tools/patch-wine-xinput-vibration.py, so XInputSetState reaches the host pad
# (docs/dualsense-output.md), and replace upstream's copies -- which were built
# from this same submodule without the patch. xinput9_1_0 forwards to
# xinput1_4 at run time. A failed build keeps the shipped copies (no rumble,
# nothing else changes). MADEIRA_XINPUT_RUMBLE_BUILD=0 skips it.
XI=""
if [ "${MADEIRA_XINPUT_RUMBLE_BUILD:-1}" != 0 ]; then
    for d in xinput1_1 xinput1_2 xinput1_3 xinput1_4; do
        [ -d "$R/wine/dlls/$d" ] || continue
        targets="$targets dlls/$d/arm64ec-windows/$d.dll"; XI="$XI $d"
    done
fi
[ -n "$todo$XI" ] || { echo "nothing to build"; exit 0; }

# The cached tree may have disabled winegstreamer because macOS has no
# GStreamer headers. Only its real PE frontend is needed here; the iOS unix
# backend already lives in libntdll_unix.a. Reconfigure that older cache too.
if [ ! -f "$B/Makefile" ] ||
   ! grep -q '^dlls/winegstreamer/arm64ec-windows/winegstreamer.dll:' "$B/Makefile"; then
    mkdir -p "$B"
    ( cd "$B" && "$R/wine/configure" --enable-archs=arm64ec --enable-winegstreamer --without-x --disable-tests \
          --without-freetype --without-gnutls ${TOOLS:+--with-wine-tools="$TOOLS"} ) > "$B.cfg.log" 2>&1 \
        || { tail -20 "$B.cfg.log"; echo "::error::wine arm64ec configure failed"; exit 1; }
fi
# widl looks for imported typelibs (stdole2.tlb) under aarch64-windows, its
# arch dir for ARM64EC, but an arm64ec-only tree builds them under
# arm64ec-windows; without this riched20, hnetcfg and wbemdisp fail with
# "cannot find stdole2.tlb".
mkdir -p "$B/dlls/stdole2.tlb" && ln -sfn arm64ec-windows "$B/dlls/stdole2.tlb/aarch64-windows"
# msvcr*: mirror the data exports into the PE mapping (see the script).
python3 "$R/tools/patch-wine-msvcrt-datasync.py" "$R/wine/dlls/msvcrt/main.c"
# d2d1: DC render targets without IDXGISurface1 (DXMT), see the script.
case " $todo " in *" d2d1 "*) python3 "$R/tools/patch-wine-d2d1-dc-readback.py" "$R/wine/dlls/d2d1/dc_render_target.c" ;; esac
# madeira-doge: the second exception. mfreadwrite is rebuilt with
# tools/patch-wine-mf-reader-allocator.py (a source reader whose D3D sample
# allocator cannot be set up returns system-memory samples; Monster Hunter
# Rise read an error 500 times a second for ever). Its delay import of mf.dll
# becomes a plain import for the reason given below. A failed build keeps the
# shipped copy. MADEIRA_MF_READER_BUILD=0 skips it.
MFR=0
if [ "${MADEIRA_MF_READER_BUILD:-1}" != 0 ] && [ -f "$R/wine/dlls/mfreadwrite/reader.c" ] && shipped mf; then
    if python3 "$R/tools/patch-wine-mf-reader-allocator.py" "$R/wine/dlls/mfreadwrite/reader.c"; then
        MFR=1
        sed -i.bak -e '/^DELAYIMPORTS[[:space:]]*=/d' -e 's/^\(IMPORTS[[:space:]]*=.*\)$/\1 mf/' "$R/wine/dlls/mfreadwrite/Makefile.in" && rm -f "$R/wine/dlls/mfreadwrite/Makefile.in.bak"
        rm -f "$B/dlls/mfreadwrite/arm64ec-windows/mfreadwrite.dll" "$B/dlls/mfreadwrite"/arm64ec-windows/*.o
        targets="$targets dlls/mfreadwrite/arm64ec-windows/mfreadwrite.dll"
    else
        echo "::warning::mfreadwrite allocator patch did not apply; shipped mfreadwrite.dll kept"
    fi
fi
# madeira-doge: the third exception. windows.gaming.input is rebuilt with
# tools/patch-wine-wgi-host-pads.patch (willfaust/wine e656d1e8): with
# MADEIRA_WGI_HOST_PADS=1 each connected XInput slot is also a
# Windows.Gaming.Input Gamepad, for games that read pads only through WGI
# (Horizon Zero Dawn). Off by default. A failed patch or build keeps the shipped
# copy. MADEIRA_WGI_BUILD=0 skips it.
WGI=0
if [ "${MADEIRA_WGI_BUILD:-1}" != 0 ] && [ -f "$R/wine/dlls/windows.gaming.input/provider.c" ]; then
    if git -C "$R/wine" apply "$R/tools/patch-wine-wgi-host-pads.patch"; then
        WGI=1
        rm -f "$B/dlls/windows.gaming.input/arm64ec-windows/windows.gaming.input.dll" "$B/dlls/windows.gaming.input"/arm64ec-windows/*.o
        targets="$targets dlls/windows.gaming.input/arm64ec-windows/windows.gaming.input.dll"
    else
        echo "::warning::windows.gaming.input host-pads patch did not apply; shipped copy kept"
    fi
fi
xi_patched=0
if [ -n "$XI" ]; then
    python3 "$R/tools/patch-wine-xinput-vibration.py" "$R/wine/dlls/xinput1_3/main.c" && xi_patched=1
    # Old objects from an unpatched build must not satisfy make.
    for d in $XI; do rm -f "$B/dlls/$d/arm64ec-windows/$d.dll" "$B/dlls/$d"/arm64ec-windows/*.o; done
fi
# Delay imports become plain imports. lld's ARM64EC delay-load stub is x64 code
# inside .text (`lea rax, __imp_aux_X; jmp __tailMerge`), and the pool copy
# Madeira runs ARM64EC code from relocates the delay IAT to the stub's POOL
# address, so the first call executes x64 code outside the emulator's
# executable ranges: NoExec, then an unhandled c0000005 (Rockstar Games
# Launcher in d2d1's DWriteCreateFactory stub, 2026-10-03 19:42 log). Only
# when every delayed DLL ships or is built here; otherwise the module is left
# as it is.
undelayed=""
for d in $todo; do
    mk="$R/wine/dlls/$d/Makefile.in"
    delayed="$(sed -n 's/^DELAYIMPORTS[[:space:]]*=[[:space:]]*//p' "$mk")"
    [ -n "$delayed" ] && grep -q "^IMPORTS" "$mk" || continue
    ok=1
    for i in $delayed; do
        shipped "$i" || case " $todo " in *" $i "*) ;; *) ok=0 ;; esac
    done
    [ "$ok" = 1 ] || continue
    sed -i.bak -e '/^DELAYIMPORTS[[:space:]]*=/d' -e "s/^\(IMPORTS[[:space:]]*=.*\)\$/\1 $delayed/" "$mk" && rm -f "$mk.bak"
    undelayed="$undelayed $d"
done
make -C "$B" -k -j"$JOBS" $targets > "$B.build.log" 2>&1
git -C "$R/wine" checkout -- dlls/msvcrt/main.c dlls/xinput1_3/main.c dlls/d2d1/dc_render_target.c
git -C "$R/wine" checkout -- dlls/mfreadwrite/reader.c dlls/mfreadwrite/Makefile.in
git -C "$R/wine" checkout -- dlls/windows.gaming.input/main.c dlls/windows.gaming.input/provider.c
if [ "$WGI" = 1 ]; then
    f="$B/dlls/windows.gaming.input/arm64ec-windows/windows.gaming.input.dll"
    if [ -f "$f" ]; then
        cp "$f" "$SHIP/windows.gaming.input.dll.tmp"
        "$MINGW/llvm-strip" "$SHIP/windows.gaming.input.dll.tmp"
        python3 - "$SHIP/windows.gaming.input.dll.tmp" <<'PY'
import struct, sys
p = sys.argv[1]; d = open(p, 'rb').read()
pe = struct.unpack_from('<I', d, 0x3c)[0]
target = struct.unpack_from('<I', d, pe + 24 + 56)[0] + 0x10000
if len(d) < target:
    open(p, 'ab').write(b'\0' * (target - len(d)))
PY
        mv "$SHIP/windows.gaming.input.dll.tmp" "$SHIP/windows.gaming.input.dll"
        echo "::notice::windows.gaming.input with host pads (MADEIRA_WGI_HOST_PADS): shipped DLL replaced"
    else
        echo "::warning::windows.gaming.input did not build; shipped copy kept"
        grep -m 10 "windows.gaming.input.*error\|error.*windows.gaming.input" "$B.build.log"
    fi
fi
if [ "$MFR" = 1 ]; then
    f="$B/dlls/mfreadwrite/arm64ec-windows/mfreadwrite.dll"
    if [ -f "$f" ]; then
        cp "$f" "$SHIP/mfreadwrite.dll.tmp"
        "$MINGW/llvm-strip" "$SHIP/mfreadwrite.dll.tmp"
        python3 - "$SHIP/mfreadwrite.dll.tmp" <<'PY'
import struct, sys
p = sys.argv[1]; d = open(p, 'rb').read()
pe = struct.unpack_from('<I', d, 0x3c)[0]
target = struct.unpack_from('<I', d, pe + 24 + 56)[0] + 0x10000
if len(d) < target:
    open(p, 'ab').write(b'\0' * (target - len(d)))
PY
        mv "$SHIP/mfreadwrite.dll.tmp" "$SHIP/mfreadwrite.dll"
        echo "::notice::mfreadwrite with the allocator fallback: shipped DLL replaced"
    else
        echo "::warning::mfreadwrite did not build; shipped copy kept"
        grep -m 10 "mfreadwrite.*error\|error.*mfreadwrite" "$B.build.log"
    fi
fi
for d in $undelayed; do git -C "$R/wine" checkout -- "dlls/$d/Makefile.in"; done
[ -n "$undelayed" ] && echo "::notice::delay imports linked as plain imports:$undelayed"
xi_built=0; xi_failed=""
if [ "$xi_patched" = 1 ]; then
    for d in $XI; do
        f="$B/dlls/$d/arm64ec-windows/$d.dll"
        if [ ! -f "$f" ]; then xi_failed="$xi_failed $d"; continue; fi
        cp "$f" "$SHIP/$d.dll.tmp"
        "$MINGW/llvm-strip" "$SHIP/$d.dll.tmp"
        python3 - "$SHIP/$d.dll.tmp" <<'PY'
import struct, sys
p = sys.argv[1]; d = open(p, 'rb').read()
pe = struct.unpack_from('<I', d, 0x3c)[0]
target = struct.unpack_from('<I', d, pe + 24 + 56)[0] + 0x10000
if len(d) < target:
    open(p, 'ab').write(b'\0' * (target - len(d)))
PY
        mv "$SHIP/$d.dll.tmp" "$SHIP/$d.dll"
        xi_built=$((xi_built + 1))
    done
    echo "::notice::xinput with host rumble (ml2106): replaced $xi_built shipped DLLs${xi_failed:+ (failed, shipped copy kept:$xi_failed)}"
elif [ -n "$XI" ]; then
    echo "::warning::xinput rumble patch did not apply; shipped xinput DLLs kept"
fi
built=0; failed=""
for d in $todo; do
    f="$B/dlls/$d/arm64ec-windows/$d.dll"
    if [ ! -f "$f" ]; then failed="$failed $d"; continue; fi
    cp "$f" "$SHIP/$d.dll.tmp"
    "$MINGW/llvm-strip" "$SHIP/$d.dll.tmp"
    python3 - "$SHIP/$d.dll.tmp" <<'PY'
import struct, sys
p = sys.argv[1]; d = open(p, 'rb').read()
pe = struct.unpack_from('<I', d, 0x3c)[0]
target = struct.unpack_from('<I', d, pe + 24 + 56)[0] + 0x10000
if len(d) < target:
    open(p, 'ab').write(b'\0' * (target - len(d)))
PY
    mv "$SHIP/$d.dll.tmp" "$SHIP/$d.dll"
    built=$((built + 1))
done
echo "::notice::built $built extra Wine DLLs for arm64ec${failed:+ (failed:$failed)}"
[ -n "$failed" ] && grep -m 10 "error" "$B.build.log"

# madeira-doge: ntdll-proton.dll, a new file next to the shipped ntdll.dll (which
# stays): this tree's ntdll with tools/patch-wine-ntdll-proton.py (Proton 11's TLS
# vector/block layout, and its LFH group retention behind MADEIRA_HEAP_LFH_KEEP=1).
# The unix loader maps it only with env.MADEIRA_NTDLL_PROTON = 1
# (build/ntdll-unix/loader_ios.c). Built only when this tree, unpatched, first
# rebuilds the shipped ntdll.dll apart from its time stamps -- otherwise a source
# build could differ from what every game runs in more than the patch. The method
# (flags, the byte check, strip and pad) follows BCD's ntdll-sync.dll. The tree and
# the ntdll objects are restored afterwards. MADEIRA_NTDLL_PROTON_BUILD=0 skips it.
if [ "${MADEIRA_NTDLL_PROTON_BUILD:-1}" != 0 ] && [ -f "$SHIP/ntdll.dll" ] && [ -f "$R/wine/dlls/ntdll/loader.c" ]; then
    nt="$B/dlls/ntdll/arm64ec-windows/ntdll.dll"
    ntflags="-g -O2"
    ntsrc="$(sed -n 's/^srcdir = //p' "$B/Makefile")"
    case "$ntsrc" in /*) ntflags="$ntflags -ffile-prefix-map=$ntsrc=.. -fno-file-reproducible" ;; esac
    ntp_make() {
        rm -f "$nt" "$B"/dlls/ntdll/arm64ec-windows/*.o
        make -C "$B" -j"$JOBS" arm64ec_CFLAGS="$ntflags" x86_64_CFLAGS="$ntflags" \
            dlls/ntdll/arm64ec-windows/ntdll.dll >> "$B.ntdll-proton.log" 2>&1 && [ -f "$nt" ]
    }
    # stripped and padded to SizeOfImage + 0x50000, as build/wine-pe/build-ntdll.sh does
    ntp_ship() {
        cp "$nt" "$1" && "$MINGW/arm64ec-w64-mingw32-strip" "$1" && python3 - "$1" <<'PY'
import struct, sys
p = sys.argv[1]; d = open(p, 'rb').read()
pe = struct.unpack_from('<I', d, 0x3c)[0]
target = struct.unpack_from('<I', d, pe + 24 + 56)[0] + 0x50000
if len(d) > target:
    raise SystemExit("ntdll is larger than SizeOfImage + 0x50000")
open(p, 'ab').write(b'\0' * (target - len(d)))
PY
    }
    : > "$B.ntdll-proton.log"
    if ntp_make && ntp_ship "$B/ntdll-stock.dll" &&
       python3 "$R/tools/patch-wine-ntdll-proton.py" --same-as "$B/ntdll-stock.dll" "$SHIP/ntdll.dll" >> "$B.ntdll-proton.log" 2>&1; then
        if python3 "$R/tools/patch-wine-ntdll-proton.py" "$R/wine" >> "$B.ntdll-proton.log" 2>&1 &&
           ntp_make && ntp_ship "$SHIP/ntdll-proton.dll.tmp"; then
            mv "$SHIP/ntdll-proton.dll.tmp" "$SHIP/ntdll-proton.dll"
            echo "::notice::ntdll-proton.dll (Proton 11 TLS layout; LFH retention with MADEIRA_HEAP_LFH_KEEP=1): built next to the shipped ntdll.dll, mapped only with env.MADEIRA_NTDLL_PROTON = 1"
        else
            rm -f "$SHIP/ntdll-proton.dll.tmp"
            echo "::warning::ntdll-proton.dll :: did not build; not shipped (games map the shipped ntdll.dll) :: $(grep -m 6 -E 'error|expected' "$B.ntdll-proton.log" | tr '\n' ' ' | cut -c1-900)"
        fi
    else
        echo "::warning::ntdll-proton.dll :: this tree does not rebuild the shipped ntdll.dll apart from time stamps; not shipped :: $(grep -m 4 -E 'same-as|error' "$B.ntdll-proton.log" | tr '\n' ' ' | cut -c1-900)"
    fi
    git -C "$R/wine" checkout -- dlls/ntdll/loader.c dlls/ntdll/heap.c dlls/ntdll/ntdll_misc.h
    rm -f "$nt" "$B"/dlls/ntdll/arm64ec-windows/*.o "$B/ntdll-stock.dll"
fi
exit 0
