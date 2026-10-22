#!/usr/bin/env python3
"""madeira-doge: log what a game asks of a Media Foundation source reader.

DYNASTY WARRIORS: ORIGINS demo (build 368, logs 2026-10-22 18:43 and 18:57)
opens its VP9 movie through a source reader 245 times in a row: the media
source connects, SetCurrentMediaType's D3D sample allocator falls back to
system memory, and the reader is released again without a single picture
asked of the parser. Wine's TRACE output is compiled out of these builds, so
nothing says which call the game gave up after.

This patch wraps the IMFSourceReaderEx methods (and the async OnReadSample
delivery) with ERR-level lines `[mf-trace] madeira-doge ...`: the call, its
arguments that matter (stream, media subtype and frame size, service and
interface GUIDs) and the HRESULT; for a delivered sample, whether its first
buffer offers IMFDXGIBuffer. The creation attributes (async callback, D3D
manager, video processing switches) are logged once per reader. At most 400
lines per process; MADEIRA_MF_TRACE=0 turns it off.

Usage: patch-wine-mf-reader-trace.py wine/dlls/mfreadwrite/reader.c
(idempotent; run after tools/patch-wine-mf-reader-allocator.py by
tools/build-wine-extra-dlls.sh, which restores the file afterwards.)
"""
import sys

path = sys.argv[1]
src = open(path).read()
MARK = "madeira-doge: mf-trace"
if MARK in src:
    print("already patched (mf-trace)"); sys.exit(0)


def rep(old, new):
    global src
    if src.count(old) != 1:
        sys.exit("patch-wine-mf-reader-trace: anchor not found once:\n" + old)
    src = src.replace(old, new)


TOP = r'''/* madeira-doge: mf-trace -- see tools/patch-wine-mf-reader-trace.py */
static LONG mt_lines;
static int mt_on(void)
{
    static int on = -1;
    if (on < 0)
    {
        WCHAR v[8];
        DWORD n = GetEnvironmentVariableW(L"MADEIRA_MF_TRACE", v, ARRAY_SIZE(v));
        on = !(n && v[0] == '0');
    }
    return on && InterlockedIncrement(&mt_lines) <= 400;
}
#define MT(...) do { if (mt_on()) ERR("[mf-trace] madeira-doge " __VA_ARGS__); } while (0)

static const GUID mt_IID_IMFDXGIBuffer = {0xe7174cfa, 0x1c9e, 0x48b1, {0x88, 0x66, 0x62, 0x62, 0x26, 0xbf, 0xc2, 0x58}};

static const char *mt_type(IMFMediaType *type)
{
    GUID major = GUID_NULL, sub = GUID_NULL;
    UINT64 size = 0;
    if (!type) return "(null)";
    IMFMediaType_GetGUID(type, &MF_MT_MAJOR_TYPE, &major);
    IMFMediaType_GetGUID(type, &MF_MT_SUBTYPE, &sub);
    IMFMediaType_GetUINT64(type, &MF_MT_FRAME_SIZE, &size);
    return wine_dbg_sprintf("major %s sub %s %ux%u", debugstr_guid(&major), debugstr_guid(&sub),
            (unsigned)(size >> 32), (unsigned)size);
}

static const char *mt_sample(IMFSample *sample)
{
    IMFMediaBuffer *buffer = NULL;
    IUnknown *dxgi = NULL;
    DWORD count = 0;
    if (!sample) return "no sample";
    IMFSample_GetBufferCount(sample, &count);
    if (FAILED(IMFSample_GetBufferByIndex(sample, 0, &buffer))) return wine_dbg_sprintf("sample, %lu buffers, none readable", count);
    if (SUCCEEDED(IMFMediaBuffer_QueryInterface(buffer, &mt_IID_IMFDXGIBuffer, (void **)&dxgi))) IUnknown_Release(dxgi);
    IMFMediaBuffer_Release(buffer);
    return wine_dbg_sprintf("sample, %lu buffer(s), IMFDXGIBuffer %s", count, dxgi ? "yes" : "NO");
}

'''

HELPERS = r'''static HRESULT WINAPI mt_QueryInterface(IMFSourceReaderEx *iface, REFIID riid, void **out)
{
    HRESULT hr = src_reader_QueryInterface(iface, riid, out);
    MT("%p QueryInterface %s -> %#lx\n", iface, debugstr_guid(riid), hr);
    return hr;
}

static ULONG WINAPI mt_Release(IMFSourceReaderEx *iface)
{
    ULONG ref = src_reader_Release(iface);
    if (!ref) MT("%p Release -> 0 (reader destroyed)\n", iface);
    return ref;
}

static HRESULT WINAPI mt_GetStreamSelection(IMFSourceReaderEx *iface, DWORD index, BOOL *selected)
{
    HRESULT hr = src_reader_GetStreamSelection(iface, index, selected);
    MT("%p GetStreamSelection %#lx -> %#lx (%d)\n", iface, index, hr, SUCCEEDED(hr) && selected ? *selected : -1);
    return hr;
}

static HRESULT WINAPI mt_SetStreamSelection(IMFSourceReaderEx *iface, DWORD index, BOOL selection)
{
    HRESULT hr = src_reader_SetStreamSelection(iface, index, selection);
    MT("%p SetStreamSelection %#lx %d -> %#lx\n", iface, index, selection, hr);
    return hr;
}

static HRESULT WINAPI mt_GetNativeMediaType(IMFSourceReaderEx *iface, DWORD index, DWORD type_index, IMFMediaType **type)
{
    HRESULT hr = src_reader_GetNativeMediaType(iface, index, type_index, type);
    MT("%p GetNativeMediaType %#lx #%lu -> %#lx %s\n", iface, index, type_index, hr,
            SUCCEEDED(hr) && type ? mt_type(*type) : "");
    return hr;
}

static HRESULT WINAPI mt_GetCurrentMediaType(IMFSourceReaderEx *iface, DWORD index, IMFMediaType **type)
{
    HRESULT hr = src_reader_GetCurrentMediaType(iface, index, type);
    MT("%p GetCurrentMediaType %#lx -> %#lx %s\n", iface, index, hr, SUCCEEDED(hr) && type ? mt_type(*type) : "");
    return hr;
}

static HRESULT WINAPI mt_SetCurrentMediaType(IMFSourceReaderEx *iface, DWORD index, DWORD *reserved, IMFMediaType *type)
{
    HRESULT hr;
    MT("%p SetCurrentMediaType %#lx %s ...\n", iface, index, mt_type(type));
    hr = src_reader_SetCurrentMediaType(iface, index, reserved, type);
    MT("%p SetCurrentMediaType %#lx -> %#lx\n", iface, index, hr);
    return hr;
}

static HRESULT WINAPI mt_SetCurrentPosition(IMFSourceReaderEx *iface, REFGUID format, REFPROPVARIANT position)
{
    HRESULT hr = src_reader_SetCurrentPosition(iface, format, position);
    MT("%p SetCurrentPosition -> %#lx\n", iface, hr);
    return hr;
}

static HRESULT WINAPI mt_ReadSample(IMFSourceReaderEx *iface, DWORD index, DWORD flags, DWORD *actual_index,
        DWORD *stream_flags, LONGLONG *timestamp, IMFSample **sample)
{
    HRESULT hr = src_reader_ReadSample(iface, index, flags, actual_index, stream_flags, timestamp, sample);
    MT("%p ReadSample %#lx flags %#lx -> %#lx stream_flags %#lx %s\n", iface, index, flags, hr,
            stream_flags ? *stream_flags : 0, sample ? mt_sample(*sample) : "(async)");
    return hr;
}

static HRESULT WINAPI mt_Flush(IMFSourceReaderEx *iface, DWORD index)
{
    HRESULT hr = src_reader_Flush(iface, index);
    MT("%p Flush %#lx -> %#lx\n", iface, index, hr);
    return hr;
}

static HRESULT WINAPI mt_GetServiceForStream(IMFSourceReaderEx *iface, DWORD index, REFGUID service, REFIID riid, void **object)
{
    HRESULT hr = src_reader_GetServiceForStream(iface, index, service, riid, object);
    MT("%p GetServiceForStream %#lx service %s iid %s -> %#lx\n", iface, index, debugstr_guid(service),
            debugstr_guid(riid), hr);
    return hr;
}

static HRESULT WINAPI mt_GetPresentationAttribute(IMFSourceReaderEx *iface, DWORD index, REFGUID guid, PROPVARIANT *value)
{
    HRESULT hr = src_reader_GetPresentationAttribute(iface, index, guid, value);
    MT("%p GetPresentationAttribute %#lx %s -> %#lx\n", iface, index, debugstr_guid(guid), hr);
    return hr;
}

static HRESULT WINAPI mt_SetNativeMediaType(IMFSourceReaderEx *iface, DWORD index, IMFMediaType *type, DWORD *flags)
{
    HRESULT hr = src_reader_SetNativeMediaType(iface, index, type, flags);
    MT("%p SetNativeMediaType %#lx %s -> %#lx\n", iface, index, mt_type(type), hr);
    return hr;
}

static HRESULT WINAPI mt_AddTransformForStream(IMFSourceReaderEx *iface, DWORD index, IUnknown *transform)
{
    HRESULT hr = src_reader_AddTransformForStream(iface, index, transform);
    MT("%p AddTransformForStream %#lx -> %#lx\n", iface, index, hr);
    return hr;
}

static HRESULT WINAPI mt_RemoveAllTransformsForStream(IMFSourceReaderEx *iface, DWORD index)
{
    HRESULT hr = src_reader_RemoveAllTransformsForStream(iface, index);
    MT("%p RemoveAllTransformsForStream %#lx -> %#lx\n", iface, index, hr);
    return hr;
}

static HRESULT WINAPI mt_GetTransformForStream(IMFSourceReaderEx *iface, DWORD index, DWORD transform_index,
        GUID *category, IMFTransform **transform)
{
    HRESULT hr = src_reader_GetTransformForStream(iface, index, transform_index, category, transform);
    MT("%p GetTransformForStream %#lx #%lu -> %#lx\n", iface, index, transform_index, hr);
    return hr;
}

static const IMFSourceReaderExVtbl srcreader_vtbl =
{
    mt_QueryInterface,
    src_reader_AddRef,
    mt_Release,
    mt_GetStreamSelection,
    mt_SetStreamSelection,
    mt_GetNativeMediaType,
    mt_GetCurrentMediaType,
    mt_SetCurrentMediaType,
    mt_SetCurrentPosition,
    mt_ReadSample,
    mt_Flush,
    mt_GetServiceForStream,
    mt_GetPresentationAttribute,
    mt_SetNativeMediaType,
    mt_AddTransformForStream,
    mt_RemoveAllTransformsForStream,
    mt_GetTransformForStream,
};
'''

OLD_VTBL = '''static const IMFSourceReaderExVtbl srcreader_vtbl =
{
    src_reader_QueryInterface,
    src_reader_AddRef,
    src_reader_Release,
    src_reader_GetStreamSelection,
    src_reader_SetStreamSelection,
    src_reader_GetNativeMediaType,
    src_reader_GetCurrentMediaType,
    src_reader_SetCurrentMediaType,
    src_reader_SetCurrentPosition,
    src_reader_ReadSample,
    src_reader_Flush,
    src_reader_GetServiceForStream,
    src_reader_GetPresentationAttribute,
    src_reader_SetNativeMediaType,
    src_reader_AddTransformForStream,
    src_reader_RemoveAllTransformsForStream,
    src_reader_GetTransformForStream,
};
'''
rep(OLD_VTBL, HELPERS)
rep('WINE_DEFAULT_DEBUG_CHANNEL(mfplat);\n', 'WINE_DEFAULT_DEBUG_CHANNEL(mfplat);\n\n' + TOP)

# async deliveries
rep('''            if (report_sample)
                IMFSourceReaderCallback_OnReadSample(reader->async_callback, status, stream_index, stream_flags,
                        timestamp, sample);''',
'''            if (report_sample)
            {
                MT("%p OnReadSample (read) status %#lx stream %lu flags %#lx %s\\n", &reader->IMFSourceReaderEx_iface,
                        status, stream_index, stream_flags, mt_sample(sample));
                IMFSourceReaderCallback_OnReadSample(reader->async_callback, status, stream_index, stream_flags,
                        timestamp, sample);
            }''')
rep('''                IMFSourceReaderCallback_OnReadSample(reader->async_callback, response->status, response->stream_index,
                        response->stream_flags, response->timestamp, response->sample);''',
'''                MT("%p OnReadSample (ready) status %#lx stream %lu flags %#lx %s\\n", &reader->IMFSourceReaderEx_iface,
                        response->status, response->stream_index, response->stream_flags, mt_sample(response->sample));
                IMFSourceReaderCallback_OnReadSample(reader->async_callback, response->status, response->stream_index,
                        response->stream_flags, response->timestamp, response->sample);''')

# creation attributes
rep('''            if (unk)
                IUnknown_Release(unk);
        }
    }
''', '''            if (unk)
                IUnknown_Release(unk);
        }
        {
            UINT32 vp = 0, avp = 0, dxva = 0, hw = 0;
            IMFAttributes_GetUINT32(attributes, &MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING, &vp);
            IMFAttributes_GetUINT32(attributes, &MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING, &avp);
            IMFAttributes_GetUINT32(attributes, &MF_SOURCE_READER_DISABLE_DXVA, &dxva);
            IMFAttributes_GetUINT32(attributes, &MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, &hw);
            MT("%p created: async %s, device manager %s, video processing %u, advanced %u, disable dxva %u, hw transforms %u\\n",
                    &object->IMFSourceReaderEx_iface, object->async_callback ? "yes" : "no",
                    object->flags & SOURCE_READER_DXGI_DEVICE_MANAGER ? "DXGI" :
                    object->flags & SOURCE_READER_D3D9_DEVICE_MANAGER ? "D3D9" : "none", vp, avp, dxva, hw);
        }
    }
''')
if MARK not in src:
    sys.exit("patch-wine-mf-reader-trace: marker missing")
open(path, "w").write(src)
print("mf-trace patched")
