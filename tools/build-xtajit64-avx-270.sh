#!/bin/bash
# Build the AVX FEX module (xtajit64-avx.dll) the way upstream build 270 builds
# its xtajit64.dll: FEX at the revision build 270 pins (willfaust/FEX 26859e1,
# the same checkout tools/build-xtajit-wow64.sh uses, FEX-wow64/) with all of
# build 270's FEX fixes plus the MADEIRA_FEX_AVX opt-in. Only
# xtajit64-avx.dll is replaced; the shipped xtajit64.dll stays.
#
# Why: tools/build-xtajit64.sh builds xtajit64-avx.dll from this tree's FEX
# submodule (0f8edf8) with nothing but the AVX patch. Two RE Engine games run
# on it (RE Requiem demo, Onimusha demo -- both need AVX, both die with
# c000001d without it) crashed walking a std::map whose node pointers were
# zero or garbage. Build 270 fixed FEX writing into the game's own memory:
#  - patch-fex-ios-ircap-tls.py: the IR-capture mark was a thread_local that
#    landed in the main executable's TLS[0] block and zeroed +0x8..+0xf on
#    every block compile;
#  - patch-fex-ios-mapview-selfshared.py, patch-fex-ios-intervals-reentry.py:
#    two self-deadlocks on FEX's code-invalidation locks;
#  - patch-fex-ios-teb-tsd.py, patch-fex-ios-cpuid-index.py.
# Run from the repo root after build-xtajit64.sh. On any failure the
# xtajit64-avx.dll already in place stays.
set -eu
R="$(pwd)"
MINGW="${MINGW:-$R/toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin}"
export PATH="$MINGW:$PATH"
REV="${FEX_WOW64_REV:-26859e184ad90f0e811d7f8bbd943a4b1573a2c3}"
F="${FEX_WOW64_SRC:-$R/FEX-wow64}"
B="${FEX_AVX270_BUILD:-$F/build-arm64ec}"
SHIP="$R/app/Madeira/arm64ec-windows/xtajit64.dll"
AVX="$R/app/Madeira/arm64ec-windows/xtajit64-avx.dll"
JOBS="$(sysctl -n hw.ncpu 2>/dev/null || nproc)"
SUBS="External/vixl Source/Common/cpp-optparse External/fmt External/drm-headers External/xxhash
      External/Catch2 External/Vulkan-Headers External/jemalloc_glibc External/tracy External/range-v3
      External/zydis External/unordered_dense External/rpmalloc"

# ------------------------------------------------------------- the checkout
if [ "$(git -C "$F" rev-parse HEAD 2>/dev/null)" != "$REV" ]; then
    if [ ! -d "$F/.git" ]; then
        rm -rf "$F.tmp"
        git clone -q --no-checkout "$R/FEX" "$F.tmp"
        if [ -d "$F" ]; then mv "$F.tmp/.git" "$F/.git"; rm -rf "$F.tmp"; else mv "$F.tmp" "$F"; fi
    fi
    git -C "$F" remote set-url origin https://github.com/willfaust/FEX.git
    git -C "$F" fetch -q origin "$REV"
    git -C "$F" checkout -q -f --detach "$REV"
fi
# shellcheck disable=SC2086
git -C "$F" submodule update --init --recursive $SUBS > "$F.avx-submodules.log" 2>&1 \
    || { tail -20 "$F.avx-submodules.log"; exit 1; }

# --------------------------------------------------------------- the patches
PATCHED="Source/Windows/ARM64EC/Module.cpp Source/Windows/Common/InvalidationTracker.h
         Source/Windows/Common/InvalidationTracker.cpp FEXCore/Source/Interface/IR/PassManager.cpp
         Source/Windows/Common/Priv.h FEXCore/Source/Interface/Core/CPUID.cpp
         Source/Windows/Common/CPUFeatures.cpp"
git -C "$F" diff --name-only | while read -r f; do git -C "$F" checkout -- "$f"; done
# shellcheck disable=SC2086
restore() { git -C "$F" checkout -- $PATCHED 2>/dev/null || true; }
trap restore EXIT
python3 "$R/tools/patch-fex-ios-mapview-selfshared.py" "$F/Source/Windows/ARM64EC/Module.cpp"
python3 "$R/tools/patch-fex-ios-intervals-reentry.py" "$F/Source/Windows/Common"
python3 "$R/tools/patch-fex-ios-ircap-tls.py" "$F/FEXCore/Source/Interface/IR/PassManager.cpp"
python3 "$R/tools/patch-fex-ios-teb-tsd.py" "$F/Source/Windows/Common/Priv.h"
python3 "$R/tools/patch-fex-ios-cpuid-index.py" "$F/FEXCore/Source/Interface/Core/CPUID.cpp"
python3 "$R/tools/patch-fex-ios-avx.py" "$F/Source/Windows/Common/CPUFeatures.cpp"

# ----------------------------------------------------------------- the build
# Build 270's options for the ARM64EC module (its tools/build-xtajit64.sh).
cmake -S "$F" -B "$B" -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$F/Data/CMake/toolchain_mingw.cmake" \
    -DMINGW_TRIPLE=arm64ec-w64-mingw32 -DTUNE_CPU=cortex-a78 \
    -DFEX_IOS_HOST_BUILD=ON \
    -DCMAKE_C_FLAGS=-DFEX_IOS_HOST=1 -DCMAKE_CXX_FLAGS=-DFEX_IOS_HOST=1 \
    -DCMAKE_ASM_FLAGS=-DFEX_IOS_HOST=1 \
    -DENABLE_LTO=OFF -DENABLE_FEX_ALLOCATOR=ON -DENABLE_JEMALLOC_GLIBC_ALLOC=ON \
    -DBUILD_FEXCONFIG=OFF -DENABLE_CCACHE=OFF -DBUILD_TESTING=OFF -DBUILD_THUNKS=OFF \
    -DENABLE_ASSERTIONS=OFF -DCMAKE_POLICY_VERSION_MINIMUM=3.5 > "$B.cfg.log" 2>&1 \
    || { tail -30 "$B.cfg.log"; exit 1; }
cmake --build "$B" --target arm64ecfex -j"$JOBS" > "$B.build.log" 2>&1 \
    || { grep -m 20 "error" "$B.build.log"; exit 1; }
NEW="$B/Bin/libarm64ecfex.dll"

# ------------------------------------------------- same interface, then ship
# Every export the shipped module has must be there, except IosAliasStats (a
# diagnostic counter of the WoW64 series' build that the unix side reads only
# if present; build 270's module does not have it either).
"$MINGW/llvm-readobj" --coff-exports "$SHIP" | awk '$1 == "Name:" && $2 != "IosAliasStats" { print $2 }' | sort > "$B.want-exports"
"$MINGW/llvm-readobj" --coff-exports "$NEW" | awk '$1 == "Name:" { print $2 }' | sort > "$B.have-exports"
missing="$(comm -23 "$B.want-exports" "$B.have-exports" | tr '\n' ' ')"
if [ -n "$missing" ]; then
    echo "::warning::the build-270 AVX module lacks exports the shipped xtajit64.dll has ($missing) -- keeping the previous xtajit64-avx.dll"
    exit 1
fi
# The transition code must be the iOS one (Module.S built with FEX_IOS_HOST
# has the ios_ffs_no_bypass path; the stock ExitToX64 crashed every x64 entry).
if ! "$MINGW/llvm-objdump" -d --no-show-raw-insn "$NEW" | grep -q "<ios_ffs_no_bypass>:"; then
    echo "::warning::the build-270 AVX module's ExitToX64 is not the iOS variant -- keeping the previous xtajit64-avx.dll"
    exit 1
fi
cp "$NEW" "$AVX"
echo "::notice::xtajit64-avx.dll rebuilt from FEX ${REV:0:7} with build 270's FEX fixes (IRCapRIP TLS, map-view and IntervalsLock self-deadlocks, TEB from TSD) and the AVX opt-in"
