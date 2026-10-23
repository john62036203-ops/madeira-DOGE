#!/usr/bin/env python3
"""madeira-doge shared-tex: an unshareable D3D11 shared texture gets a handle
D3D12 in the same process can open (env.MADEIRA_D3D11_SHARE_LOCAL, default on).

See madeira-d3d12/src/madeira_shared_tex.h for the why (DYNASTY WARRIORS:
ORIGINS hands its movie pictures from D3D11 to D3D12 through a legacy shared
texture; build 394 log 2026-10-23 17:13: "shared 2D texture fmt=90 1280x720
... NO mach port", then "GetSharedHandle ... -> E_INVALIDARG", 60 times).

When DXMT's shared path has no mach port, the texture is now recorded in the
process's shared-texture table (its Metal texture retained) and created with
that handle as its global handle, so GetSharedHandle answers it. The entry is
dropped and the texture released when the D3D11 texture is destroyed.
madeira-d3d12's OpenSharedHandle opens such handles.
MADEIRA_D3D11_SHARE_LOCAL=0 keeps the old "continuing unshared" behaviour.

Applied by tools/build-d3d11-dll.sh to its copy (d3d11-src.dll; the game needs
env.MADEIRA_D3D11_SRC = 1). The table code is inlined from the header so the
DXMT tree needs no new include path. Idempotent; fails by name if an anchor
moves.
"""
import pathlib
import sys

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11")
REPO = pathlib.Path(__file__).resolve().parents[1]
HEADER = (REPO / "madeira-d3d12/src/madeira_shared_tex.h").read_text()
MARKER = "madeira-doge: shared-tex local"

rel = "d3d11_texture_device.cpp"
path = ROOT / rel
s = path.read_text()
if MARKER in s:
    print(f"{rel}: already patched (shared-tex local)")
    sys.exit(0)


def rep(old, new):
    global s
    if s.count(old) != 1:
        sys.exit(f"patch-dxmt-share-local: anchor not found once in {rel}:\n{old}")
    s = s.replace(old, new)


rep('#include "config/config.hpp"   /* ml675: d3d11.mipClampBC */\n',
    '#include "config/config.hpp"   /* ml675: d3d11.mipClampBC */\n'
    '/* madeira-doge: shared-tex local -- table from madeira-d3d12/src/madeira_shared_tex.h */\n'
    + HEADER +
    '\nstatic bool madeira_share_local_on() {\n'
    '  static int on = -1;\n'
    '  if (on < 0) on = dxmt::env::getEnvVar("MADEIRA_D3D11_SHARE_LOCAL") != "0";\n'
    '  return on;\n'
    '}\n')

# destructor: drop the entry, release the retained texture
rep('''  ~DeviceTexture() {
    if (local_kmt_) {''',
    '''  ~DeviceTexture() {
    if (!local_kmt_ && madeira_stx_is_handle(global_kmt_)) {   /* madeira-doge: shared-tex local */
      UINT64 tex = madeira_stx_unregister(global_kmt_);
      if (tex) NSObject_release((obj_handle_t)tex);
    }
    if (local_kmt_) {''')

# creation: register instead of continuing unshared
rep('''      static bool said = false;
      if (!said) { said = true; ERR("DeviceTexture: no mach port for a shared texture; continuing unshared"); }
      initialize(std::move(allocation));
      auto *tex = ref(new DeviceTexture<tag>(&finalDesc, std::move(texture), pDevice));''',
    '''      static bool said = false;
      UINT32 local_handle = 0;
      if constexpr (std::is_same_v<typename tag::DESC1, D3D11_TEXTURE2D_DESC1>) {
        if (madeira_share_local_on() && !(finalDesc.MiscFlags & D3D11_RESOURCE_MISC_SHARED_NTHANDLE)) {
          obj_handle_t th = allocation->texture().handle;
          if (th) {
            NSObject_retain(th);
            local_handle = madeira_stx_register((UINT64)th, (UINT32)finalDesc.Format, finalDesc.Width,
                                                finalDesc.Height, finalDesc.MipLevels, finalDesc.ArraySize);
            if (!local_handle) NSObject_release(th);
          }
          static std::atomic<uint32_t> n_local{0};
          if (n_local.fetch_add(1) < 16)
            ERR("DeviceTexture: shared texture without a mach port -> in-process handle 0x",
                str::format(std::hex, local_handle), local_handle ? " (D3D12 OpenSharedHandle can open it)" : " (table full)");
        }
      }
      if (!local_handle && !said) { said = true; ERR("DeviceTexture: no mach port for a shared texture; continuing unshared"); }
      initialize(std::move(allocation));
      auto *tex = local_handle
          ? ref(new DeviceTexture<tag>(&finalDesc, std::move(texture), 0, (D3DKMT_HANDLE)local_handle, pDevice))
          : ref(new DeviceTexture<tag>(&finalDesc, std::move(texture), pDevice));''')

if MARKER not in s:
    sys.exit("patch-dxmt-share-local: marker missing")
path.write_text(s)
print(f"{rel}: patched (shared-tex local)")
