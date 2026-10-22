#!/usr/bin/env python3
"""ID3D11VideoDevice for DXMT's d3d11 (env.MADEIRA_D3D11_VIDEO), opt-in.

DYNASTY WARRIORS: ORIGINS demo (Steam 3273240) renders with D3D12, but when its
first movie should start (build 362 log 2026-10-22 12:35, right after the
loading) one of its job threads creates a D3D11 device, asks it for
ID3D11VideoDevice ({10ec4d5b-975a-4689-b9e4-d0aac30fe333}), gets
E_NOINTERFACE from DXMT ("D3D11Device: Unknown interface query", logged once),
destroys the device and starts over: 175 devices in ten seconds, each with its
dxmt-encode/finish threads. Then it stops trying and the game sits on a grey
frame at 60 fps for good, with input reaching its window. Wine's own d3d11
answers that query (with stubs); DXMT has no video interfaces at all.

env.MADEIRA_D3D11_VIDEO (read once per process, d3d11-src.dll only, so the
game also needs env.MADEIRA_D3D11_SRC = 1):
  unset/0  upstream: no ID3D11VideoDevice. Only logs the creation flags of
           the first devices ([d3d11-video] lines), so a log shows whether a
           game asks for D3D11_CREATE_DEVICE_VIDEO_SUPPORT.
  stub/1   the DXGI device answers ID3D11VideoDevice/ID3D11VideoDevice1 with
           an object that offers no hardware decoding: 0 decoder profiles,
           every format unsupported, creation calls E_NOTIMPL (as Wine's d3d11
           without a wined3d decoder). A game that checks for hardware decode
           should then take its software path. Every call is logged (first 200).
  fail     D3D11CreateDevice with D3D11_CREATE_DEVICE_VIDEO_SUPPORT fails with
           E_FAIL, as on a GPU without video support.

Idempotent; fails by name if an anchor moves. Run from the repository root;
the optional argument is another d3d11 source directory to patch instead of
dxmt/src/d3d11 (tools/build-d3d11-dll.sh patches its copy that way).
"""
import pathlib
import sys

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11")
MARKER = "madeira-doge: d3d11 video device"


def edit(rel, pairs):
    path = ROOT / rel
    s = path.read_text()
    if MARKER in s:
        print(f"{rel}: already patched (video device)")
        return
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f"patch-dxmt-video-device: anchor not found once in {rel}:\n{old}")
        s = s.replace(old, new)
    if MARKER not in s:
        sys.exit(f"patch-dxmt-video-device: marker missing after editing {rel}")
    path.write_text(s)
    print(f"{rel}: patched (video device)")


HELPERS = r'''
/* madeira-doge: d3d11 video device -- env.MADEIRA_D3D11_VIDEO (see
 * tools/patch-dxmt-video-device.py). 0 = upstream, 1 = stub, 2 = fail. */
int madeira_d3d11_video_mode() {
  static int mode = -1;
  if (mode < 0) {
    std::string v = env::getEnvVar("MADEIRA_D3D11_VIDEO");
    int m = 0;
    if (v == "1" || v == "stub")
      m = 1;
    else if (v == "fail" || v == "2")
      m = 2;
    mode = m;
    Logger::info(str::format("[d3d11-video] madeira-doge: MADEIRA_D3D11_VIDEO=",
                             v.empty() ? std::string("(unset)") : v, " mode=",
                             m == 1 ? "stub" : m == 2 ? "fail" : "upstream"));
  }
  return mode;
}

static std::atomic<uint32_t> madeira_video_log_count{0};
#define MADEIRA_VLOG(...)                                                       \
  do {                                                                         \
    if (madeira_video_log_count.fetch_add(1) < 200)                            \
      Logger::info(str::format("[d3d11-video] ", __VA_ARGS__));                \
  } while (0)

/* No hardware decoder: what Wine's d3d11 reports without a wined3d decoder. */
class MadeiraVideoDevice final : public ID3D11VideoDevice1 {
public:
  MadeiraVideoDevice(IUnknown *container) : container_(container) {}

  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **ppvObject) final {
    return container_->QueryInterface(riid, ppvObject);
  }
  ULONG STDMETHODCALLTYPE AddRef() final { return container_->AddRef(); }
  ULONG STDMETHODCALLTYPE Release() final { return container_->Release(); }

  HRESULT STDMETHODCALLTYPE CreateVideoDecoder(const D3D11_VIDEO_DECODER_DESC *pVideoDesc,
                                               const D3D11_VIDEO_DECODER_CONFIG *pConfig,
                                               ID3D11VideoDecoder **ppDecoder) final {
    if (ppDecoder) *ppDecoder = nullptr;
    if (pVideoDesc)
      MADEIRA_VLOG("CreateVideoDecoder profile=", str::format(pVideoDesc->Guid), " ",
                   pVideoDesc->SampleWidth, "x", pVideoDesc->SampleHeight,
                   " fmt=", (uint32_t)pVideoDesc->OutputFormat, " -> E_NOTIMPL");
    else
      MADEIRA_VLOG("CreateVideoDecoder (no desc) -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE CreateVideoProcessor(ID3D11VideoProcessorEnumerator *pEnum,
                                                 UINT RateConversionIndex,
                                                 ID3D11VideoProcessor **ppVideoProcessor) final {
    if (ppVideoProcessor) *ppVideoProcessor = nullptr;
    MADEIRA_VLOG("CreateVideoProcessor -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE CreateAuthenticatedChannel(D3D11_AUTHENTICATED_CHANNEL_TYPE ChannelType,
                                                       ID3D11AuthenticatedChannel **ppAuthenticatedChannel) final {
    if (ppAuthenticatedChannel) *ppAuthenticatedChannel = nullptr;
    MADEIRA_VLOG("CreateAuthenticatedChannel -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE CreateCryptoSession(const GUID *pCryptoType, const GUID *pDecoderProfile,
                                                const GUID *pKeyExchangeType,
                                                ID3D11CryptoSession **ppCryptoSession) final {
    if (ppCryptoSession) *ppCryptoSession = nullptr;
    MADEIRA_VLOG("CreateCryptoSession -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE CreateVideoDecoderOutputView(ID3D11Resource *pResource,
                                                         const D3D11_VIDEO_DECODER_OUTPUT_VIEW_DESC *pDesc,
                                                         ID3D11VideoDecoderOutputView **ppVDOVView) final {
    if (ppVDOVView) *ppVDOVView = nullptr;
    MADEIRA_VLOG("CreateVideoDecoderOutputView -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE CreateVideoProcessorInputView(ID3D11Resource *pResource,
                                                          ID3D11VideoProcessorEnumerator *pEnum,
                                                          const D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC *pDesc,
                                                          ID3D11VideoProcessorInputView **ppVPIView) final {
    if (ppVPIView) *ppVPIView = nullptr;
    MADEIRA_VLOG("CreateVideoProcessorInputView -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE CreateVideoProcessorOutputView(ID3D11Resource *pResource,
                                                           ID3D11VideoProcessorEnumerator *pEnum,
                                                           const D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC *pDesc,
                                                           ID3D11VideoProcessorOutputView **ppVPOView) final {
    if (ppVPOView) *ppVPOView = nullptr;
    MADEIRA_VLOG("CreateVideoProcessorOutputView -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE CreateVideoProcessorEnumerator(const D3D11_VIDEO_PROCESSOR_CONTENT_DESC *pDesc,
                                                           ID3D11VideoProcessorEnumerator **ppEnum) final {
    if (ppEnum) *ppEnum = nullptr;
    MADEIRA_VLOG("CreateVideoProcessorEnumerator -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  UINT STDMETHODCALLTYPE GetVideoDecoderProfileCount() final {
    MADEIRA_VLOG("GetVideoDecoderProfileCount -> 0");
    return 0;
  }
  HRESULT STDMETHODCALLTYPE GetVideoDecoderProfile(UINT Index, GUID *pDecoderProfile) final {
    MADEIRA_VLOG("GetVideoDecoderProfile ", Index, " -> E_INVALIDARG");
    return E_INVALIDARG;
  }
  HRESULT STDMETHODCALLTYPE CheckVideoDecoderFormat(const GUID *pDecoderProfile, DXGI_FORMAT Format,
                                                    WINBOOL *pSupported) final {
    if (!pSupported)
      return E_POINTER;
    *pSupported = FALSE;
    MADEIRA_VLOG("CheckVideoDecoderFormat profile=",
                 pDecoderProfile ? str::format(*pDecoderProfile) : std::string("(null)"),
                 " fmt=", (uint32_t)Format, " -> unsupported");
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE GetVideoDecoderConfigCount(const D3D11_VIDEO_DECODER_DESC *pDesc,
                                                       UINT *pCount) final {
    if (pCount) *pCount = 0;
    MADEIRA_VLOG("GetVideoDecoderConfigCount -> E_INVALIDARG");
    return E_INVALIDARG;
  }
  HRESULT STDMETHODCALLTYPE GetVideoDecoderConfig(const D3D11_VIDEO_DECODER_DESC *pDesc, UINT Index,
                                                  D3D11_VIDEO_DECODER_CONFIG *pConfig) final {
    MADEIRA_VLOG("GetVideoDecoderConfig -> E_INVALIDARG");
    return E_INVALIDARG;
  }
  HRESULT STDMETHODCALLTYPE GetContentProtectionCaps(const GUID *pCryptoType, const GUID *pDecoderProfile,
                                                     D3D11_VIDEO_CONTENT_PROTECTION_CAPS *pCaps) final {
    MADEIRA_VLOG("GetContentProtectionCaps -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE CheckCryptoKeyExchange(const GUID *pCryptoType, const GUID *pDecoderProfile,
                                                   UINT Index, GUID *pKeyExchangeType) final {
    MADEIRA_VLOG("CheckCryptoKeyExchange -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID guid, UINT DataSize, const void *pData) final {
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID guid, const IUnknown *pData) final {
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE GetCryptoSessionPrivateDataSize(const GUID *crypto_type, const GUID *decoder_profile,
                                                            const GUID *key_exchange_type, UINT *input_size,
                                                            UINT *output_size) final {
    MADEIRA_VLOG("GetCryptoSessionPrivateDataSize -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE GetVideoDecoderCaps(const GUID *decoder_profile, UINT sample_width,
                                                UINT sample_height, const DXGI_RATIONAL *framerate,
                                                UINT bitrate, const GUID *crypto_type,
                                                UINT *decoder_caps) final {
    if (decoder_caps) *decoder_caps = 0;
    MADEIRA_VLOG("GetVideoDecoderCaps ", sample_width, "x", sample_height, " -> E_INVALIDARG");
    return E_INVALIDARG;
  }
  HRESULT STDMETHODCALLTYPE CheckVideoDecoderDownsampling(const D3D11_VIDEO_DECODER_DESC *input_desc,
                                                          DXGI_COLOR_SPACE_TYPE input_colour_space,
                                                          const D3D11_VIDEO_DECODER_CONFIG *input_config,
                                                          const DXGI_RATIONAL *framerate,
                                                          const D3D11_VIDEO_SAMPLE_DESC *output_desc,
                                                          WINBOOL *supported, WINBOOL *real_time_hint) final {
    if (supported) *supported = FALSE;
    if (real_time_hint) *real_time_hint = FALSE;
    MADEIRA_VLOG("CheckVideoDecoderDownsampling -> E_INVALIDARG");
    return E_INVALIDARG;
  }
  HRESULT STDMETHODCALLTYPE RecommendVideoDecoderDownsampleParameters(
      const D3D11_VIDEO_DECODER_DESC *input_desc, DXGI_COLOR_SPACE_TYPE input_colour_space,
      const D3D11_VIDEO_DECODER_CONFIG *input_config, const DXGI_RATIONAL *framerate,
      D3D11_VIDEO_SAMPLE_DESC *recommended_output_desc) final {
    MADEIRA_VLOG("RecommendVideoDecoderDownsampleParameters -> E_INVALIDARG");
    return E_INVALIDARG;
  }

private:
  IUnknown *container_;
};

/**
 * \brief D3D11 device container
'''

edit("d3d11_device.cpp", [
    # helpers + the stub class, before the DXGI device container
    ("\n/**\n * \\brief D3D11 device container\n", HELPERS),
    # member
    ("  MTLD3D11DeviceImpl d3d11_device_;\n};\n\nCom<IMTLDXGIDevice> CreateD3D11Device(",
     "  MTLD3D11DeviceImpl d3d11_device_;\n"
     "  /* madeira-doge: d3d11 video device (MADEIRA_D3D11_VIDEO=stub) */\n"
     "  MadeiraVideoDevice video_device_{static_cast<IMTLDXGIDevice *>(this)};\n"
     "};\n\nCom<IMTLDXGIDevice> CreateD3D11Device("),
    # QueryInterface: answer the video interfaces in stub mode
    ("    if (riid == __uuidof(ID3D11Debug))\n      return E_NOINTERFACE;\n\n"
     "    if (riid == kRenderdocUUID || riid == kPixUUID || riid == kGpaUUID)\n      return E_NOINTERFACE;\n\n"
     "    if (logQueryInterfaceError(__uuidof(IMTLDXGIDevice), riid)) {\n"
     "      WARN(\"D3D11Device: Unknown interface query \", str::format(riid));\n",
     "    if (riid == __uuidof(ID3D11Debug))\n      return E_NOINTERFACE;\n\n"
     "    if (riid == kRenderdocUUID || riid == kPixUUID || riid == kGpaUUID)\n      return E_NOINTERFACE;\n\n"
     "    if (riid == __uuidof(ID3D11VideoDevice) || riid == __uuidof(ID3D11VideoDevice1)) {\n"
     "      int vmode = madeira_d3d11_video_mode();\n"
     "      MADEIRA_VLOG(\"QueryInterface \", str::format(riid), vmode == 1 ? \" -> stub\" : \" -> E_NOINTERFACE\");\n"
     "      if (vmode == 1) {\n"
     "        *ppvObject = ref_and_cast<ID3D11VideoDevice1>(&video_device_);\n"
     "        return S_OK;\n"
     "      }\n"
     "      return E_NOINTERFACE;\n"
     "    }\n\n"
     "    if (logQueryInterfaceError(__uuidof(IMTLDXGIDevice), riid)) {\n"
     "      WARN(\"D3D11Device: Unknown interface query \", str::format(riid));\n"),
])

edit("d3d11.cpp", [
    ("namespace dxmt {\nLogger Logger::s_instance(\"d3d11.log\");\n",
     "namespace dxmt {\nLogger Logger::s_instance(\"d3d11.log\");\n"
     "/* madeira-doge: d3d11 video device (d3d11_device.cpp) */\n"
     "int madeira_d3d11_video_mode();\n"),
    ("  if (!devFeatureLevel) {\n    Logger::err(str::format(\"Minimum required feature level \", minFeatureLevel,\n",
     "  {\n"
     "    static std::atomic<uint32_t> n{0};\n"
     "    int vmode = madeira_d3d11_video_mode();\n"
     "    bool video = (Flags & D3D11_CREATE_DEVICE_VIDEO_SUPPORT) != 0;\n"
     "    if (n.fetch_add(1) < 24)\n"
     "      Logger::info(str::format(\"[d3d11-video] D3D11CoreCreateDevice flags=0x\",\n"
     "                               str::format(std::hex, Flags), video ? \" VIDEO_SUPPORT\" : \"\",\n"
     "                               video && vmode == 2 ? \" -> E_FAIL (MADEIRA_D3D11_VIDEO=fail)\" : \"\"));\n"
     "    if (video && vmode == 2)\n"
     "      return E_FAIL;\n"
     "  }\n\n"
     "  if (!devFeatureLevel) {\n    Logger::err(str::format(\"Minimum required feature level \", minFeatureLevel,\n"),
])


# --- ID3D11VideoContext on the immediate context (stub mode) -----------------
# Build 364 log 13:50 (stub): the game takes the ID3D11VideoDevice, then asks
# the immediate context for ID3D11VideoContext ({61f21c45-...}), gets
# E_NOINTERFACE and destroys the device again (150 rounds).
VCTX_HEADER = r'''#pragma once
/* madeira-doge: d3d11 video device -- ID3D11VideoContext stub for the
 * immediate context (env.MADEIRA_D3D11_VIDEO=stub). Generated from
 * llvm-mingw 20260421's d3d11.h by tools/patch-dxmt-video-device.py's author;
 * no video processor or decoder can exist, so every call is a no-op/E_NOTIMPL. */
#include "d3d11_4.h"
#include "log/log.hpp"
#include "util_string.hpp"
#include <atomic>

namespace dxmt {

inline void madeira_vctx_log(const char *what) {
  static std::atomic<uint32_t> n{0};
  if (n.fetch_add(1) < 200)
    Logger::info(str::format("[d3d11-video] VideoContext::", what));
}

class MadeiraVideoContext final : public ID3D11VideoContext {
public:
  MadeiraVideoContext(ID3D11DeviceContext *container) : container_(container) {}

  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **ppvObject) final {
    return container_->QueryInterface(riid, ppvObject);
  }
  ULONG STDMETHODCALLTYPE AddRef() final { return container_->AddRef(); }
  ULONG STDMETHODCALLTYPE Release() final { return container_->Release(); }

  void STDMETHODCALLTYPE GetDevice(ID3D11Device **ppDevice) final { container_->GetDevice(ppDevice); }
  HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID guid, UINT *pDataSize, void *pData) final {
    return container_->GetPrivateData(guid, pDataSize, pData);
  }
  HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID guid, UINT DataSize, const void *pData) final {
    return container_->SetPrivateData(guid, DataSize, pData);
  }
  HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID guid, const IUnknown *pData) final {
    return container_->SetPrivateDataInterface(guid, pData);
  }

  HRESULT STDMETHODCALLTYPE GetDecoderBuffer(ID3D11VideoDecoder *decoder, D3D11_VIDEO_DECODER_BUFFER_TYPE type, UINT *buffer_size, void **buffer) final {
    madeira_vctx_log("GetDecoderBuffer -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE ReleaseDecoderBuffer(ID3D11VideoDecoder *decoder, D3D11_VIDEO_DECODER_BUFFER_TYPE type) final {
    madeira_vctx_log("ReleaseDecoderBuffer -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE DecoderBeginFrame(ID3D11VideoDecoder *decoder, ID3D11VideoDecoderOutputView *view, UINT key_size, const void *key) final {
    madeira_vctx_log("DecoderBeginFrame -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE DecoderEndFrame(ID3D11VideoDecoder *decoder) final {
    madeira_vctx_log("DecoderEndFrame -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE SubmitDecoderBuffers(ID3D11VideoDecoder *decoder, UINT buffers_count, const D3D11_VIDEO_DECODER_BUFFER_DESC *buffer_desc) final {
    madeira_vctx_log("SubmitDecoderBuffers -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE DecoderExtension(ID3D11VideoDecoder *decoder, const D3D11_VIDEO_DECODER_EXTENSION *extension) final {
    madeira_vctx_log("DecoderExtension -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  void STDMETHODCALLTYPE VideoProcessorSetOutputTargetRect(ID3D11VideoProcessor *processor, WINBOOL enable, const RECT *rect) final { madeira_vctx_log("VideoProcessorSetOutputTargetRect"); }
  void STDMETHODCALLTYPE VideoProcessorSetOutputBackgroundColor(ID3D11VideoProcessor *processor, WINBOOL y_cb_cr, const D3D11_VIDEO_COLOR *color) final { madeira_vctx_log("VideoProcessorSetOutputBackgroundColor"); }
  void STDMETHODCALLTYPE VideoProcessorSetOutputColorSpace(ID3D11VideoProcessor *processor, const D3D11_VIDEO_PROCESSOR_COLOR_SPACE *color_space) final { madeira_vctx_log("VideoProcessorSetOutputColorSpace"); }
  void STDMETHODCALLTYPE VideoProcessorSetOutputAlphaFillMode(ID3D11VideoProcessor *processor, D3D11_VIDEO_PROCESSOR_ALPHA_FILL_MODE alpha_fill_mode, UINT stream_idx) final { madeira_vctx_log("VideoProcessorSetOutputAlphaFillMode"); }
  void STDMETHODCALLTYPE VideoProcessorSetOutputConstriction(ID3D11VideoProcessor *processor, WINBOOL enable, SIZE size) final { madeira_vctx_log("VideoProcessorSetOutputConstriction"); }
  void STDMETHODCALLTYPE VideoProcessorSetOutputStereoMode(ID3D11VideoProcessor *processor, WINBOOL enable) final { madeira_vctx_log("VideoProcessorSetOutputStereoMode"); }
  HRESULT STDMETHODCALLTYPE VideoProcessorSetOutputExtension(ID3D11VideoProcessor *processor, const GUID *guid, UINT data_size, void *data) final {
    madeira_vctx_log("VideoProcessorSetOutputExtension -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  void STDMETHODCALLTYPE VideoProcessorGetOutputTargetRect(ID3D11VideoProcessor *processor, WINBOOL *enabled, RECT *rect) final { madeira_vctx_log("VideoProcessorGetOutputTargetRect"); }
  void STDMETHODCALLTYPE VideoProcessorGetOutputBackgroundColor(ID3D11VideoProcessor *processor, WINBOOL *y_cb_cr, D3D11_VIDEO_COLOR *color) final { madeira_vctx_log("VideoProcessorGetOutputBackgroundColor"); }
  void STDMETHODCALLTYPE VideoProcessorGetOutputColorSpace(ID3D11VideoProcessor *processor, D3D11_VIDEO_PROCESSOR_COLOR_SPACE *color_space) final { madeira_vctx_log("VideoProcessorGetOutputColorSpace"); }
  void STDMETHODCALLTYPE VideoProcessorGetOutputAlphaFillMode(ID3D11VideoProcessor *processor, D3D11_VIDEO_PROCESSOR_ALPHA_FILL_MODE *alpha_fill_mode, UINT *stream_idx) final { madeira_vctx_log("VideoProcessorGetOutputAlphaFillMode"); }
  void STDMETHODCALLTYPE VideoProcessorGetOutputConstriction(ID3D11VideoProcessor *processor, WINBOOL *enabled, SIZE *size) final { madeira_vctx_log("VideoProcessorGetOutputConstriction"); }
  void STDMETHODCALLTYPE VideoProcessorGetOutputStereoMode(ID3D11VideoProcessor *processor, WINBOOL *enabled) final { madeira_vctx_log("VideoProcessorGetOutputStereoMode"); }
  HRESULT STDMETHODCALLTYPE VideoProcessorGetOutputExtension(ID3D11VideoProcessor *processor, const GUID *guid, UINT data_size, void *data) final {
    madeira_vctx_log("VideoProcessorGetOutputExtension -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  void STDMETHODCALLTYPE VideoProcessorSetStreamFrameFormat(ID3D11VideoProcessor *processor, UINT stream_idx, D3D11_VIDEO_FRAME_FORMAT format) final { madeira_vctx_log("VideoProcessorSetStreamFrameFormat"); }
  void STDMETHODCALLTYPE VideoProcessorSetStreamColorSpace(ID3D11VideoProcessor *processor, UINT stream_idx, const D3D11_VIDEO_PROCESSOR_COLOR_SPACE *color_space) final { madeira_vctx_log("VideoProcessorSetStreamColorSpace"); }
  void STDMETHODCALLTYPE VideoProcessorSetStreamOutputRate(ID3D11VideoProcessor *processor, UINT stream_idx, D3D11_VIDEO_PROCESSOR_OUTPUT_RATE rate, WINBOOL repeat, const DXGI_RATIONAL *custom_rate) final { madeira_vctx_log("VideoProcessorSetStreamOutputRate"); }
  void STDMETHODCALLTYPE VideoProcessorSetStreamSourceRect(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL enable, const RECT *rect) final { madeira_vctx_log("VideoProcessorSetStreamSourceRect"); }
  void STDMETHODCALLTYPE VideoProcessorSetStreamDestRect(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL enable, const RECT *rect) final { madeira_vctx_log("VideoProcessorSetStreamDestRect"); }
  void STDMETHODCALLTYPE VideoProcessorSetStreamAlpha(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL enable, float alpha) final { madeira_vctx_log("VideoProcessorSetStreamAlpha"); }
  void STDMETHODCALLTYPE VideoProcessorSetStreamPalette(ID3D11VideoProcessor *processor, UINT stream_idx, UINT entry_count, const UINT *entries) final { madeira_vctx_log("VideoProcessorSetStreamPalette"); }
  void STDMETHODCALLTYPE VideoProcessorSetStreamPixelAspectRatio(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL enable, const DXGI_RATIONAL *src_aspect_ratio, const DXGI_RATIONAL *dst_aspect_ratio) final { madeira_vctx_log("VideoProcessorSetStreamPixelAspectRatio"); }
  void STDMETHODCALLTYPE VideoProcessorSetStreamLumaKey(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL enable, float lower, float upper) final { madeira_vctx_log("VideoProcessorSetStreamLumaKey"); }
  void STDMETHODCALLTYPE VideoProcessorSetStreamStereoFormat(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL enable, D3D11_VIDEO_PROCESSOR_STEREO_FORMAT format, WINBOOL left_view_frame0, WINBOOL base_view_frame0, D3D11_VIDEO_PROCESSOR_STEREO_FLIP_MODE flip_mode, int mono_offset) final { madeira_vctx_log("VideoProcessorSetStreamStereoFormat"); }
  void STDMETHODCALLTYPE VideoProcessorSetStreamAutoProcessingMode(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL enable) final { madeira_vctx_log("VideoProcessorSetStreamAutoProcessingMode"); }
  void STDMETHODCALLTYPE VideoProcessorSetStreamFilter(ID3D11VideoProcessor *processor, UINT stream_idx, D3D11_VIDEO_PROCESSOR_FILTER filter, WINBOOL enable, int level) final { madeira_vctx_log("VideoProcessorSetStreamFilter"); }
  HRESULT STDMETHODCALLTYPE VideoProcessorSetStreamExtension(ID3D11VideoProcessor *processor, UINT stream_idx, const GUID *guid, UINT data_size, void *data) final {
    madeira_vctx_log("VideoProcessorSetStreamExtension -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  void STDMETHODCALLTYPE VideoProcessorGetStreamFrameFormat(ID3D11VideoProcessor *processor, UINT stream_idx, D3D11_VIDEO_FRAME_FORMAT *format) final { madeira_vctx_log("VideoProcessorGetStreamFrameFormat"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamColorSpace(ID3D11VideoProcessor *processor, UINT stream_idx, D3D11_VIDEO_PROCESSOR_COLOR_SPACE *color_space) final { madeira_vctx_log("VideoProcessorGetStreamColorSpace"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamOutputRate(ID3D11VideoProcessor *processor, UINT stream_idx, D3D11_VIDEO_PROCESSOR_OUTPUT_RATE *rate, WINBOOL *repeat, DXGI_RATIONAL *custom_rate) final { madeira_vctx_log("VideoProcessorGetStreamOutputRate"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamSourceRect(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL *enabled, RECT *rect) final { madeira_vctx_log("VideoProcessorGetStreamSourceRect"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamDestRect(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL *enabled, RECT *rect) final { madeira_vctx_log("VideoProcessorGetStreamDestRect"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamAlpha(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL *enabled, float *alpha) final { madeira_vctx_log("VideoProcessorGetStreamAlpha"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamPalette(ID3D11VideoProcessor *processor, UINT stream_idx, UINT entry_count, UINT *entries) final { madeira_vctx_log("VideoProcessorGetStreamPalette"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamPixelAspectRatio(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL *enabled, DXGI_RATIONAL *src_aspect_ratio, DXGI_RATIONAL *dst_aspect_ratio) final { madeira_vctx_log("VideoProcessorGetStreamPixelAspectRatio"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamLumaKey(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL *enabled, float *lower, float *upper) final { madeira_vctx_log("VideoProcessorGetStreamLumaKey"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamStereoFormat(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL *enabled, D3D11_VIDEO_PROCESSOR_STEREO_FORMAT *format, WINBOOL *left_view_frame0, WINBOOL *base_view_frame0, D3D11_VIDEO_PROCESSOR_STEREO_FLIP_MODE *flip_mode, int *mono_offset) final { madeira_vctx_log("VideoProcessorGetStreamStereoFormat"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamAutoProcessingMode(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL *enabled) final { madeira_vctx_log("VideoProcessorGetStreamAutoProcessingMode"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamFilter(ID3D11VideoProcessor *processor, UINT stream_idx, D3D11_VIDEO_PROCESSOR_FILTER filter, WINBOOL *enabled, int *level) final { madeira_vctx_log("VideoProcessorGetStreamFilter"); }
  HRESULT STDMETHODCALLTYPE VideoProcessorGetStreamExtension(ID3D11VideoProcessor *processor, UINT stream_idx, const GUID *guid, UINT data_size, void *data) final {
    madeira_vctx_log("VideoProcessorGetStreamExtension -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE VideoProcessorBlt(ID3D11VideoProcessor *processor, ID3D11VideoProcessorOutputView *view, UINT frame_idx, UINT stream_count, const D3D11_VIDEO_PROCESSOR_STREAM *streams) final {
    madeira_vctx_log("VideoProcessorBlt -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE NegotiateCryptoSessionKeyExchange(ID3D11CryptoSession *session, UINT data_size, void *data) final {
    madeira_vctx_log("NegotiateCryptoSessionKeyExchange -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  void STDMETHODCALLTYPE EncryptionBlt(ID3D11CryptoSession *session, ID3D11Texture2D *src_surface, ID3D11Texture2D *dst_surface, UINT iv_size, void *iv) final { madeira_vctx_log("EncryptionBlt"); }
  void STDMETHODCALLTYPE DecryptionBlt(ID3D11CryptoSession *session, ID3D11Texture2D *src_surface, ID3D11Texture2D *dst_surface, D3D11_ENCRYPTED_BLOCK_INFO *block_info, UINT key_size, const void *key, UINT iv_size, void *iv) final { madeira_vctx_log("DecryptionBlt"); }
  void STDMETHODCALLTYPE StartSessionKeyRefresh(ID3D11CryptoSession *session, UINT random_number_size, void *random_number) final { madeira_vctx_log("StartSessionKeyRefresh"); }
  void STDMETHODCALLTYPE FinishSessionKeyRefresh(ID3D11CryptoSession *session) final { madeira_vctx_log("FinishSessionKeyRefresh"); }
  HRESULT STDMETHODCALLTYPE GetEncryptionBltKey(ID3D11CryptoSession *session, UINT key_size, void *key) final {
    madeira_vctx_log("GetEncryptionBltKey -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE NegotiateAuthenticatedChannelKeyExchange(ID3D11AuthenticatedChannel *channel, UINT data_size, void *data) final {
    madeira_vctx_log("NegotiateAuthenticatedChannelKeyExchange -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE QueryAuthenticatedChannel(ID3D11AuthenticatedChannel *channel, UINT input_size, const void *input, UINT output_size, void *output) final {
    madeira_vctx_log("QueryAuthenticatedChannel -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  HRESULT STDMETHODCALLTYPE ConfigureAuthenticatedChannel(ID3D11AuthenticatedChannel *channel, UINT input_size, const void *input, D3D11_AUTHENTICATED_CONFIGURE_OUTPUT *output) final {
    madeira_vctx_log("ConfigureAuthenticatedChannel -> E_NOTIMPL");
    return E_NOTIMPL;
  }
  void STDMETHODCALLTYPE VideoProcessorSetStreamRotation(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL enable, D3D11_VIDEO_PROCESSOR_ROTATION rotation) final { madeira_vctx_log("VideoProcessorSetStreamRotation"); }
  void STDMETHODCALLTYPE VideoProcessorGetStreamRotation(ID3D11VideoProcessor *processor, UINT stream_idx, WINBOOL *enable, D3D11_VIDEO_PROCESSOR_ROTATION *rotation) final { madeira_vctx_log("VideoProcessorGetStreamRotation"); }

private:
  ID3D11DeviceContext *container_;
};

} // namespace dxmt

'''
hp = ROOT / "d3d11_video_context_stub.hpp"
if not hp.exists() or MARKER not in hp.read_text():
    hp.write_text(VCTX_HEADER)
    print("d3d11_video_context_stub.hpp: written")

edit("d3d11_context_imm.cpp", [
    ("class MTLD3D11ImmediateContext : public ImmediateContextBase {\n",
     "} // namespace dxmt\n"
     "/* madeira-doge: d3d11 video device -- VideoContext stub */\n"
     "#include \"d3d11_video_context_stub.hpp\"\n"
     "namespace dxmt {\n"
     "int madeira_d3d11_video_mode();\n\n"
     "class MTLD3D11ImmediateContext : public ImmediateContextBase {\n"),
    ("    if (riid == __uuidof(ID3D11Multithread)) {\n      *ppvObject = ref(&d3dmt_);\n      return S_OK;\n    }\n",
     "    if (riid == __uuidof(ID3D11Multithread)) {\n      *ppvObject = ref(&d3dmt_);\n      return S_OK;\n    }\n\n"
     "    if (riid == __uuidof(ID3D11VideoContext) && madeira_d3d11_video_mode() == 1) {\n"
     "      madeira_vctx_log(\"QueryInterface ID3D11VideoContext -> stub\");\n"
     "      vctx_.AddRef();\n"
     "      *ppvObject = static_cast<ID3D11VideoContext *>(&vctx_);\n"
     "      return S_OK;\n"
     "    }\n"),
    ("  D3D11Multithread d3dmt_;\n  bool ignore_map_flag_no_wait_;\n",
     "  D3D11Multithread d3dmt_;\n"
     "  MadeiraVideoContext vctx_{static_cast<ID3D11DeviceContext *>(this)};\n"
     "  bool ignore_map_flag_no_wait_;\n"),
])
