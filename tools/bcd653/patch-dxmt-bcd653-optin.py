#!/usr/bin/env python3
"""DXMT: BCD 0.1.653's three Direct3D 11 crash fixes, opt-in (env.MADEIRA_DXMT_BCD_FIXES = 1).

Runs BCD's patch scripts (copied unchanged from BCD 0.1.653) and then makes each
depend on one switch, read once per process:

  * patch-dxmt-texture-limit.py: CreateTexture1D/2D/3D refuse a size
    Direct3D 11 refuses (E_INVALIDARG) instead of handing it to Metal, which
    aborted the process (The Witness, Tomb Raider, Transformers, Danganronpa).
  * patch-dxmt-update-subresource-staging.py: UpdateSubresource(1) on a
    STAGING buffer is dropped instead of crashing the encode thread (FIFA 23).
  * patch-dxmt-d11-swapchain-rotation.py: IDXGISwapChain1::SetRotation /
    GetRotation answer the identity rotation instead of ending the process
    (SDL2 games such as The Battle for Wesnoth).

Unset or 0: each path is exactly as before.

Applied by tools/build-d3d11-dll.sh to its copy of the d3d11 sources, so it is in
the 64-bit d3d11-src.dll a game gets with env.MADEIRA_D3D11_SRC = 1 (the committed
d3d11.dll and the i386 farm are not touched; these scripts live in tools/bcd653/
so the farm's cache key, which hashes tools/patch-dxmt-*.py, does not change).
madeira-doge fork-local build patch; not a contribution to DXMT.
Usage: patch-dxmt-bcd653-optin.py <d3d11 source dir>   (default: dxmt/src/d3d11)
Idempotent and all-or-nothing (the three files are restored when any step fails); fails by name when an anchor moved.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

MARK = "madeira-doge bcd653-optin"
HELPER = '''#ifndef MADEIRA_DXMT_BCD_FIXES_DEFINED
#define MADEIRA_DXMT_BCD_FIXES_DEFINED
/* %s: env.MADEIRA_DXMT_BCD_FIXES = 1 turns on BCD 0.1.653's Direct3D 11 crash fixes (texture limit, UpdateSubresource
 * on a staging buffer, swap chain rotation); unset or 0 = as before. */
static inline bool MadeiraDxmtBcdFixes() {
  static const bool on = dxmt::env::getEnvVar("MADEIRA_DXMT_BCD_FIXES") == "1";
  return on;
}
#endif
''' % MARK


def one(s, old, new, what, path):
    if s.count(old) != 1:
        sys.exit("patch-dxmt-bcd653-optin: %s not found once in %s (%d times; DXMT or BCD's patch changed)" % (what, path.name, s.count(old)))
    return s.replace(old, new)


def main():
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11").resolve()
    files = {k: d / v for k, v in (("dev", "d3d11_device.cpp"), ("ctx", "d3d11_context_impl.cpp"), ("sc", "d3d11_swapchain.cpp"))}
    if all(MARK in p.read_text() for p in files.values()):
        print("d3d11: BCD 0.1.653 fixes already in, opt-in; nothing to do")
        return
    saved = {k: p.read_text() for k, p in files.items()}
    try:
        apply(d, files)
    except SystemExit:
        for k, p in files.items():   # all or nothing: never BCD's fixes without the switch
            p.write_text(saved[k])
        raise


def apply(d, files):
    here = Path(__file__).resolve().parent
    # BCD's scripts patch ./dxmt/src/d3d11/...: run them in a scratch directory whose dxmt/src/d3d11 is the target.
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "dxmt", "src"))
        os.symlink(str(d), os.path.join(tmp, "dxmt", "src", "d3d11"))
        for p in ("texture-limit", "update-subresource-staging", "d11-swapchain-rotation"):
            r = subprocess.run([sys.executable, str(here / ("patch-dxmt-%s.py" % p))], cwd=tmp)
            if r.returncode:
                sys.exit("patch-dxmt-bcd653-optin: patch-dxmt-%s.py did not apply" % p)

    p = files["dev"]; s = p.read_text()
    s = one(s, '#include "com/com_guid.hpp"\n', '#include "util_env.hpp"\n#include "com/com_guid.hpp"\n', "the include block", p)
    s = one(s, "\nnamespace dxmt {\n", "\n" + HELPER + "\nnamespace dxmt {\n", "namespace dxmt", p)
    s = one(s, "    if (pDesc->Width > 16384u || pDesc->ArraySize > 2048u) {\n",
            "    if (MadeiraDxmtBcdFixes() && (pDesc->Width > 16384u || pDesc->ArraySize > 2048u)) {   /* %s */\n" % MARK, "the 1D limit", p)
    s = one(s, "      if (pDesc->Width > 16384u || pDesc->Height > 16384u || pDesc->ArraySize > 2048u) {\n",
            "      if (MadeiraDxmtBcdFixes() && (pDesc->Width > 16384u || pDesc->Height > 16384u || pDesc->ArraySize > 2048u)) {   /* %s */\n" % MARK, "the 2D limit", p)
    s = one(s, "    if (pDesc->Width > 2048u || pDesc->Height > 2048u || pDesc->Depth > 2048u) {\n",
            "    if (MadeiraDxmtBcdFixes() && (pDesc->Width > 2048u || pDesc->Height > 2048u || pDesc->Depth > 2048u)) {   /* %s */\n" % MARK, "the 3D limit", p)
    p.write_text(s)

    p = files["ctx"]; s = p.read_text()
    s = one(s, '#include "Metal.hpp"\n', '#include "Metal.hpp"\n#include "util_env.hpp"\n' + HELPER, "the include block", p)
    s = one(s, "        if (!dst_rc) {\n", "        if (!dst_rc && MadeiraDxmtBcdFixes()) {   /* %s */\n" % MARK, "the staging check", p)
    p.write_text(s)

    p = files["sc"]; s = p.read_text()
    s = one(s, '#include "util_env.hpp"\n', '#include "util_env.hpp"\n' + HELPER, "util_env.hpp", p)
    s = one(s, "  SetRotation(DXGI_MODE_ROTATION Rotation) final {\n",
            "  SetRotation(DXGI_MODE_ROTATION Rotation) final {\n    if (!MadeiraDxmtBcdFixes()) { IMPLEMENT_ME; }   /* %s: off = as before */\n" % MARK, "SetRotation", p)
    s = one(s, "  GetRotation(DXGI_MODE_ROTATION *pRotation) final {\n",
            "  GetRotation(DXGI_MODE_ROTATION *pRotation) final {\n    if (!MadeiraDxmtBcdFixes()) { IMPLEMENT_ME; }   /* %s: off = as before */\n" % MARK, "GetRotation", p)
    p.write_text(s)
    print("d3d11: BCD 0.1.653 texture limit, staging UpdateSubresource and swap chain rotation fixes, opt-in with env.MADEIRA_DXMT_BCD_FIXES = 1")


if __name__ == "__main__":
    main()
