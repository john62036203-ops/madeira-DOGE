#!/usr/bin/env python3
"""A Metal buffer that could not be made is named, and not written through.

Sekiro (build 140, three runs on 2026-10-06) stopped after one to two minutes
of play. Each run had the same lead-up: memmove to address 0 from
_MTLBuffer_updateContents (the buffer, or its contents, was nil), several
times, then a wild write inside d3d11 on the same thread. Nothing recorded
which request Metal had refused, or why.

_MTLDevice_newBuffer now prints a [wmt-buf] line when Metal returns no buffer
(size, options, whether the memory was the caller's, its alignment, what the
device has allocated), and tries a Metal-allocated request once more.
_MTLBuffer_updateContents leaves a buffer with no contents alone and says so
instead of faulting. Native path only; the remote path is not touched.

Idempotent; fails by name if an anchor moves. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/winemetal/unix/winemetal_unix.c")
MARKER = "madeira-doge: nil buffer"

PAIRS = [
    ("""  params->ret = (obj_handle_t)buffer;
  info->gpu_address = [buffer gpuAddress];
  if (wmt_stale_probe_on()) wmt_freed_set((uintptr_t)buffer, 0);   /* ml1156: a new buffer at a recycled address is alive */
""",
     """  if (!buffer) { /* madeira-doge: nil buffer (tools/patch-winemetal-nil-buffer.py) */
    static unsigned long refused;
    const int own = info->memory.ptr != NULL;
    if (++refused <= 16 || (refused % 256) == 0)
      fprintf(stderr, "[wmt-buf] madeira-doge: Metal made no buffer: %llu bytes, options 0x%x, %s memory %p "
                      "(page offset 0x%llx, length %% 16K = 0x%llx), device has %llu MB allocated (%lu so far)\\n",
              (unsigned long long)info->length, (unsigned)info->options, own ? "caller's" : "Metal's",
              info->memory.ptr, (unsigned long long)((uintptr_t)info->memory.ptr & 0x3fff),
              (unsigned long long)(info->length & 0x3fff),
              (unsigned long long)([device currentAllocatedSize] >> 20), refused);
    if (!own) {
      buffer = [device newBufferWithLength:info->length options:(enum MTLResourceOptions)info->options];
      info->memory.ptr = [buffer storageMode] == MTLStorageModePrivate ? NULL : [buffer contents];
      if (refused <= 16)
        fprintf(stderr, "[wmt-buf] madeira-doge: second request %s\\n", buffer ? "made it" : "refused as well");
    }
  }
  params->ret = (obj_handle_t)buffer;
  info->gpu_address = [buffer gpuAddress];
  if (wmt_stale_probe_on()) wmt_freed_set((uintptr_t)buffer, 0);   /* ml1156: a new buffer at a recycled address is alive */
"""),
    ("""  memcpy((void *)((char *)[(id<MTLBuffer>)params->buffer contents] + params->offset), params->data.ptr, params->length);
#if !TARGET_OS_IOS
""",
     """  { /* madeira-doge: nil buffer -- no contents, no copy */
    char *dst = (char *)[(id<MTLBuffer>)params->buffer contents];
    if (!dst) {
      static unsigned long dropped;
      if (++dropped <= 16 || (dropped % 1024) == 0)
        fprintf(stderr, "[wmt-buf] madeira-doge: updateContents on a buffer with no contents (handle 0x%llx, "
                        "offset %llu, length %llu): not written (%lu so far)\\n",
                (unsigned long long)params->buffer, (unsigned long long)params->offset,
                (unsigned long long)params->length, dropped);
      return STATUS_SUCCESS;
    }
    memcpy(dst + params->offset, params->data.ptr, params->length);
  }
#if !TARGET_OS_IOS
"""),
]


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("winemetal_unix.c: already patched")
        return 0
    for old, new in PAIRS:
        if s.count(old) != 1:
            sys.exit(f"patch-winemetal-nil-buffer: anchor found {s.count(old)} times (want 1) in {PATH}:\\n{old}")
        s = s.replace(old, new)
    PATH.write_text(s)
    print("winemetal_unix.c: patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
