#!/bin/bash
# Build DXMT's NGX core (dxmt/src/nvngx) for arm64ec and ship it as nvngx.dll
# and _nvngx.dll.
#
# A game with DLSS Super Resolution asks NVIDIA's NGX core for it; DXMT's
# stand-in answers with the MetalFX temporal scaler through its d3d11
# (IMTLD3D11ContextExt::TemporalUpscale), which gets the game's colour, depth,
# motion vectors and jitter every frame. Upstream's DXMT build leaves the DLL
# out (meson install_tag 'nvext'), like nvapi64.dll. NVIDIA's client looks
# for either file name in the folder the registry names, which
# tools/patch-nvapi-dlss.py sets to the system directory with MADEIRA_DLSS=1;
# the app links every file of this folder into it.
#
# Built like tools/build-dxmt-nvapi.sh, after it (its import libraries are
# reused). Run from the repository root.
set -eu
R="$(pwd)"
MINGW="${MINGW:-$R/toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin}"
D="$R/dxmt"
U="$D/src/util"
SHIP="$R/app/Madeira/arm64ec-windows"
LIBS="$R/build/dxmt-nvapi"
OUT="$R/build/dxmt-nvngx"
mkdir -p "$OUT"

[ -f "$D/src/nvngx/nvngx.cpp" ] || { echo "::error::dxmt/src/nvngx is not there"; exit 1; }
[ -f "$LIBS/libdxgi.a" ] || { echo "::error::build/dxmt-nvapi/libdxgi.a is missing: run tools/build-dxmt-nvapi.sh first"; exit 1; }

# Patched copies (the submodule stays untouched): the session-log trace, the
# scratch-buffer answer and the void * <-> resource conversions.
cp "$D/src/nvngx/nvngx.cpp" "$OUT/nvngx.cpp"
cp "$D/src/nvngx/nvngx_parameter.hpp" "$OUT/nvngx_parameter.hpp"
python3 "$R/tools/patch-dxmt-nvngx.py" "$OUT/nvngx.cpp" "$OUT/nvngx_parameter.hpp"

{ echo "LIBRARY nvngx.dll"; echo "EXPORTS"; sed 's/^/    /' "$OUT/nvngx.cpp.exports"; } > "$OUT/nvngx.def"

"$MINGW/arm64ec-w64-mingw32-clang++" -std=c++20 -O2 -shared -o "$OUT/nvngx.dll" \
    "$OUT/nvngx.cpp" "$OUT/nvngx.def" \
    "$U/util_env.cpp" "$U/util_string.cpp" "$U/util_futex.cpp" "$U/thread.cpp" \
    "$U/com/com_guid.cpp" "$U/com/com_private_data.cpp" "$U/config/config.cpp" "$U/log/log.cpp" \
    -I"$OUT" -I"$D/include" -I"$D/libs" -I"$U" -I"$D/src/winemetal" -I"$D/src/nvngx" -I"$D/src/d3d11" -I"$D/src/dxgi" \
    -DNOMINMAX -D_WIN32_WINNT=0xa00 -DDXMT_IOS=1 -DDXMT_PAGE_SIZE=4096 -fblocks \
    -Wno-microsoft-exception-spec \
    -L"$LIBS" -lwinemetal -ldxgi -lntdll -static -Wl,--file-alignment=4096 -Wl,--section-alignment=16384 \
    2> "$OUT/nvngx.err" || { grep -m 20 "error" "$OUT/nvngx.err"; exit 1; }
"$MINGW/llvm-strip" --strip-debug "$OUT/nvngx.dll"

for sym in NVSDK_NGX_D3D11_Init NVSDK_NGX_D3D11_CreateFeature NVSDK_NGX_D3D11_EvaluateFeature NVSDK_NGX_D3D11_GetCapabilityParameters; do
    "$MINGW/llvm-readobj" --coff-exports "$OUT/nvngx.dll" | grep -q "Name: $sym\$" \
        || { echo "::error::nvngx.dll lacks $sym"; exit 1; }
done
grep -a -q "madeira-doge: NGX trace" "$OUT/nvngx.cpp" || { echo "::error::nvngx.cpp copy is not patched"; exit 1; }
cp "$OUT/nvngx.dll" "$SHIP/nvngx.dll"
cp "$OUT/nvngx.dll" "$SHIP/_nvngx.dll"
echo "::notice::nvngx.dll built from dxmt/src/nvngx ($(wc -c < "$OUT/nvngx.dll" | tr -d ' ') bytes) and shipped as nvngx.dll and _nvngx.dll"
