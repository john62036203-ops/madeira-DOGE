#!/usr/bin/env python3
"""madeira-doge: a source reader whose D3D sample allocator cannot be set up
hands out system-memory samples instead of failing every read.

Monster Hunter Rise (Sunbreak demo, build 172 log of 2026-10-08) gives the
source reader a DXGI device manager and asks for NV12. The reader then makes a
video sample allocator for NV12 D3D11 textures; DXMT has no NV12 texture
("creating a texture of invalid format: 103"), InitializeSampleAllocatorEx
fails with E_INVALIDARG, and Wine only warns. From then on every ReadSample
finds the decoded sample, asks the uninitialised allocator for a texture
sample, fails, and answers MF_SOURCE_READERF_ERROR with no sample while keeping
the decoded one queued: the game retried about 500 times a second for as long
as it ran (11 minutes at 1 FPS after its loading screen).

With this patch a failed initialisation releases the allocator, so
media_stream_pop_response returns the decoded sample as it is (a system-memory
buffer, which IMFMediaBuffer::Lock and IMF2DBuffer serve like any other).
MADEIRA_MF_READER_ALLOCATOR=keep restores Wine's behaviour.

Usage: patch-wine-mf-reader-allocator.py wine/dlls/mfreadwrite/reader.c
(idempotent; tools/build-wine-extra-dlls.sh applies it around its build and
restores the file afterwards.)
"""
import sys

path = sys.argv[1]
src = open(path).read()
if "madeira-doge: no D3D samples" in src:
    print("already patched"); sys.exit(0)

old = '''        WARN("Failed to initialize sample allocator, hr %#lx.\\n", hr);
    }
'''
new = '''        WARN("Failed to initialize sample allocator, hr %#lx.\\n", hr);
        /* madeira-doge: no D3D samples for this type (DXMT has no NV12 texture);
         * hand out the decoder's system-memory samples instead of an error on
         * every read. See tools/patch-wine-mf-reader-allocator.py. */
        {
            WCHAR keep[8];
            DWORD n = GetEnvironmentVariableW(L"MADEIRA_MF_READER_ALLOCATOR", keep, ARRAY_SIZE(keep));
            if (!(n == 4 && keep[0] == 'k'))
            {
                ERR("madeira-doge: no D3D samples for stream %u (hr %#lx); the reader returns system-memory samples.\\n", index, hr);
                IMFVideoSampleAllocatorEx_Release(stream->allocator);
                stream->allocator = NULL;
                hr = S_OK;
            }
        }
    }
'''
if src.count(old) != 1:
    print("patch-wine-mf-reader-allocator: anchor not found", file=sys.stderr); sys.exit(1)
open(path, "w").write(src.replace(old, new))
print("patched", path)
