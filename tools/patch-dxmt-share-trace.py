#!/usr/bin/env python3
"""madeira-doge: log DXMT's shared-texture and 2D texture failures ([d3d11-share]).

DYNASTY WARRIORS: ORIGINS demo (build 369 log 2026-10-22 20:24, [mf-trace]):
each movie attempt creates a synchronous source reader with a DXGI device
manager, selects the video stream, sets NV12, reads the current type and the
duration (MF_PD_DURATION) and then releases the reader without a single
ReadSample. Between those calls the only D3D11 message is "DeviceTexture: no
mach port for a shared texture; continuing unshared" (printed once per
process), so the game likely gives up on the shared texture: GetSharedHandle /
CreateSharedHandle on such a texture fail (it has no KMT handle), or its own
NV12 texture cannot be made.

This patch prints, at most 60 times each:
  * every shared texture created (format, size, bind and misc flags) and
    whether it got a mach port;
  * GetSharedHandle / CreateSharedHandle failures on a device texture;
  * OpenSharedResource / OpenSharedResource1 / OpenSharedResourceByName and
    their HRESULT;
  * CheckFormatSupport answers for the video formats (NV12, P010, YUY2, ...);
  * every CreateTexture2D that fails, with its descriptor.

Applied by tools/build-d3d11-dll.sh to its copy (d3d11-src.dll, needs
env.MADEIRA_D3D11_SRC = 1). Idempotent; fails by name if an anchor moves.
"""
import pathlib
import sys

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11")
MARKER = "madeira-doge: d3d11-share trace"


def edit(rel, pairs):
    path = ROOT / rel
    s = path.read_text()
    if MARKER in s:
        print(f"{rel}: already patched (share trace)")
        return
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f"patch-dxmt-share-trace: anchor not found once in {rel}:\n{old}")
        s = s.replace(old, new)
    if MARKER not in s:
        sys.exit(f"patch-dxmt-share-trace: marker missing after editing {rel}")
    path.write_text(s)
    print(f"{rel}: patched (share trace)")


LOG = '''
/* madeira-doge: d3d11-share trace (tools/patch-dxmt-share-trace.py) */
#define MADEIRA_SHARE_LOG(...)                                                  \\
  do {                                                                         \\
    static std::atomic<uint32_t> madeira_share_n{0};                           \\
    if (madeira_share_n.fetch_add(1) < 60)                                     \\
      Logger::err(str::format("[d3d11-share] ", __VA_ARGS__));                 \\
  } while (0)
'''

edit("d3d11_texture_device.cpp", [
    ('#include "config/config.hpp"   /* ml675: d3d11.mipClampBC */\n',
     '#include "config/config.hpp"   /* ml675: d3d11.mipClampBC */\n#include <atomic>\n' + LOG),
    # shared texture creation
    ('''    auto allocation = texture->allocate(flags);

    mach_port_t mach_port = allocation->machPort;
    if (!mach_port) {''',
     '''    auto allocation = texture->allocate(flags);

    mach_port_t mach_port = allocation->machPort;
    if constexpr (std::is_same_v<typename tag::DESC1, D3D11_TEXTURE2D_DESC1>)
      MADEIRA_SHARE_LOG("shared 2D texture fmt=", (uint32_t)finalDesc.Format, " ", finalDesc.Width, "x",
                        finalDesc.Height, " mips=", finalDesc.MipLevels, " array=", finalDesc.ArraySize,
                        " bind=0x", str::format(std::hex, finalDesc.BindFlags), " misc=0x",
                        str::format(std::hex, finalDesc.MiscFlags), " usage=", (uint32_t)finalDesc.Usage,
                        mach_port ? " mach port ok" : " NO mach port (kept unshared)");
    if (!mach_port) {'''),
    # GetSharedHandle
    ('''    if (!global_kmt_) {
      return E_INVALIDARG;
    }

    *pSharedHandle = reinterpret_cast<HANDLE>(global_kmt_);''',
     '''    if (!global_kmt_) {
      MADEIRA_SHARE_LOG("GetSharedHandle on a texture without a KMT handle -> E_INVALIDARG (misc=0x",
                        str::format(std::hex, this->desc.MiscFlags), ")");
      return E_INVALIDARG;
    }

    *pSharedHandle = reinterpret_cast<HANDLE>(global_kmt_);'''),
    # CreateSharedHandle
    ('''    InitReturnPtr(pNTHandle);
    if (!local_kmt_)
      return E_INVALIDARG;
''',
     '''    InitReturnPtr(pNTHandle);
    if (!local_kmt_) {
      MADEIRA_SHARE_LOG("CreateSharedHandle on a texture without a KMT handle -> E_INVALIDARG (misc=0x",
                        str::format(std::hex, this->desc.MiscFlags), ")");
      return E_INVALIDARG;
    }
'''),
    # failed CreateTexture2D
    ('''                      ID3D11Texture2D1 **ppTexture) {
  return CreateDeviceTextureInternal<tag_texture_2d>(pDevice, pDesc,
                                                     pInitialData, ppTexture);
}''',
     '''                      ID3D11Texture2D1 **ppTexture) {
  HRESULT hr = CreateDeviceTextureInternal<tag_texture_2d>(pDevice, pDesc,
                                                           pInitialData, ppTexture);
  if (FAILED(hr) && pDesc)
    MADEIRA_SHARE_LOG("CreateTexture2D failed hr=0x", str::format(std::hex, (uint32_t)hr), " fmt=",
                      (uint32_t)pDesc->Format, " ", pDesc->Width, "x", pDesc->Height, " bind=0x",
                      str::format(std::hex, pDesc->BindFlags), " misc=0x", str::format(std::hex, pDesc->MiscFlags),
                      " usage=", (uint32_t)pDesc->Usage);
  return hr;
}'''),
])

edit("d3d11_device.cpp", [
    ('#include "config/config.hpp"   /* ml670: d3d11.mipClampBC */\n',
     '#include "config/config.hpp"   /* ml670: d3d11.mipClampBC */\n' + LOG),
    ('''  OpenSharedResource(HANDLE hResource, REFIID ReturnedInterface, void **ppResource) override {
    return ImportSharedTexture(this, hResource, ReturnedInterface, ppResource);
  }''',
     '''  OpenSharedResource(HANDLE hResource, REFIID ReturnedInterface, void **ppResource) override {
    HRESULT hr = ImportSharedTexture(this, hResource, ReturnedInterface, ppResource);
    MADEIRA_SHARE_LOG("OpenSharedResource handle=", (uint64_t)(uintptr_t)hResource, " iid=",
                      str::format(ReturnedInterface), " -> 0x", str::format(std::hex, (uint32_t)hr));
    return hr;
  }'''),
    ('''  OpenSharedResource1(HANDLE hResource, REFIID ReturnedInterface, void **ppResource) override {
    return ImportSharedTextureFromNtHandle(this, hResource, ReturnedInterface, ppResource);
  }''',
     '''  OpenSharedResource1(HANDLE hResource, REFIID ReturnedInterface, void **ppResource) override {
    HRESULT hr = ImportSharedTextureFromNtHandle(this, hResource, ReturnedInterface, ppResource);
    MADEIRA_SHARE_LOG("OpenSharedResource1 handle=", (uint64_t)(uintptr_t)hResource, " iid=",
                      str::format(ReturnedInterface), " -> 0x", str::format(std::hex, (uint32_t)hr));
    return hr;
  }'''),
    ('''    return ImportSharedTextureByName(this, lpName, dwDesiredAccess, ReturnedInterface, ppResource);''',
     '''    HRESULT hr = ImportSharedTextureByName(this, lpName, dwDesiredAccess, ReturnedInterface, ppResource);
    MADEIRA_SHARE_LOG("OpenSharedResourceByName -> 0x", str::format(std::hex, (uint32_t)hr));
    return hr;'''),
    ('''    MTL_DXGI_FORMAT_DESC metal_format;
    if (FAILED(MTLQueryDXGIFormat(GetMTLDevice(), Format, metal_format))) {
      return E_INVALIDARG;
    }

    UINT outFormatSupport = 0;
''',
     '''    MTL_DXGI_FORMAT_DESC metal_format;
    if (FAILED(MTLQueryDXGIFormat(GetMTLDevice(), Format, metal_format))) {
      if (Format >= DXGI_FORMAT_AYUV && Format <= DXGI_FORMAT_P208)
        MADEIRA_SHARE_LOG("CheckFormatSupport video format ", (uint32_t)Format, " -> E_INVALIDARG");
      return E_INVALIDARG;
    }
    if (Format >= DXGI_FORMAT_AYUV && Format <= DXGI_FORMAT_P208)
      MADEIRA_SHARE_LOG("CheckFormatSupport video format ", (uint32_t)Format, " -> known to Metal");

    UINT outFormatSupport = 0;
'''),
])
