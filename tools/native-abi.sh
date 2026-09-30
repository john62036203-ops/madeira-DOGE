#!/bin/bash
# madeira-bcd: the native-ABI fingerprint of the checked-out commit.
#
# An update pack (docs/madeira-bcd.md, "Update packs") replaces PE DLLs on the
# phone without a new IPA. That is only safe while the pack's DLLs were built
# against the same native half the installed app carries: the unix sides they
# call (winemetal, the conversion service, ntdll), the structures they share
# (winemetal.h as patched, madeira_ir_abi.h) and the PE DLLs that pair with a
# unix side (ntdll, win32u, winemetal, DXMT's d3d11/dxgi). This prints a short
# hash of all of that, taken from git's index -- blob and submodule commit IDs,
# not the working tree -- so the full IPA build and the pack build compute the
# same value for the same sources whatever their build steps patch in place.
#
# The IPA stamps it into Info.plist (MadeiraNativeABI) and every pack carries
# it in madeira-pack.json; the app installs a pack only when the two match.
#
# Deliberately left OUT, because a pack may replace them: the D3D12 runtime's
# PE source (research/madeira-d3d12/src/pe) and its build script, and the PE
# files packs ship (madeira_d3d12.dll, d3d12.dll, xtajit64.dll, the D3D12 cube).
# Also out: docs and the workflows. A workflow change that alters the native
# build must bump EPOCH below.
#
# Usage: tools/native-abi.sh            -> 16 hex digits
#        tools/native-abi.sh --list     -> the entries that were hashed
set -eu
cd "$(git rev-parse --show-toplevel)"
EPOCH=1

entries() {
    echo "epoch $EPOCH"
    git ls-files -s -- \
        app build research/dxmt research/madeira-d3d12 \
        'tools/patch-*.py' wine FEX \
        ':(exclude)research/madeira-d3d12/src/pe' \
        ':(exclude,glob)app/Madeira/*-windows/madeira_d3d12.dll' \
        ':(exclude,glob)app/Madeira/*-windows/d3d12.dll' \
        ':(exclude,glob)app/Madeira/*-windows/xtajit64.dll' \
        ':(exclude,glob)app/Madeira/*-windows/d3d12-cube-x64.exe'
}

if [ "${1:-}" = "--list" ]; then entries; exit 0; fi
if command -v shasum > /dev/null 2>&1; then
    entries | shasum -a 256 | cut -c1-16
else
    entries | sha256sum | cut -c1-16
fi
