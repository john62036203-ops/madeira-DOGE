#!/usr/bin/env python3
"""Metal 4 placement-sparse buffers for D3D12 reserved buffers (MadeiraCtl ops 41-43).

The probe (tools/patch-dxmt-sparse-probe.py, op 40) showed on an A18 Pro /
iOS 27 that a placement-sparse buffer whose tiles are mapped through an
MTL4CommandQueue works from the classic queue madeira-d3d12 uses, and that an
unmapped tile reads zeros (build 250, 2026-10-18 23:51, result 0x3e). These
ops let madeira-d3d12 (madeira.cfg d3d12-sparse = 1) give reserved buffers
memory only for the tiles the application maps:

  41  new sparse buffer     in: device, length       out: buffer, gpu, tile
  42  new pool heap         in: device, length       out: heap
  43  update mappings       in: device, buffer, heap, ops, count,
                                wait_event/wait_value (the MTL4 queue waits for
                                it first: work committed before the mapping
                                change finishes before it), signal_event/
                                signal_value (signalled after; later classic
                                command buffers wait for it)

ptr points at struct madeira_sparse_args (twelve uint64). The ops array holds
{mode, location, length, heap_offset} quadruples of uint64 in tiles, the
layout of MTL4UpdateSparseBufferMappingOperation. Metal 4 selectors are looked
up at run time, so the file builds with any SDK. Requires the probe patch
(anchors on its case 40). Idempotent; fails by name if an anchor moved.
Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/winemetal/unix/winemetal_unix.c")
MARKER = "madeira-doge: Metal 4 sparse buffers"

FUNC_ANCHOR = "static NTSTATUS _madeira_ctl(void *args) {\n"
FUNC = r'''/* madeira-doge: Metal 4 sparse buffers (tools/patch-dxmt-sparse-buffers.py). */
struct madeira_sparse_args {
  uint64_t device, length, buffer, gpu, tile, heap, ops, count, wait_event, wait_value, signal_event, signal_value;
};
static id g_madeira_sparse_q4;
static uint32_t madeira_sparse_ctl(uint32_t op, struct madeira_sparse_args *s) {
  id<MTLDevice> dev;
  if (!s || !s->device || wmtr_enabled()) return 0;
  dev = (id<MTLDevice>)(uintptr_t)s->device;
  @autoreleasepool {
    NSUInteger page = 102;   /* MTLSparsePageSize64 */
    switch (op) {
    case 41: {
      SEL sel = sel_registerName("newBufferWithLength:options:placementSparsePageSize:");
      SEL st = sel_registerName("sparseTileSizeInBytesForSparsePageSize:");
      id<MTLBuffer> b;
      if (![dev respondsToSelector:sel]) return 0;
      b = ((id (*)(id, SEL, NSUInteger, NSUInteger, NSUInteger))objc_msgSend)(dev, sel, (NSUInteger)s->length,
                                                                             (NSUInteger)MTLResourceStorageModePrivate, page);
      if (!b) return 0;
      s->buffer = (uint64_t)(uintptr_t)b;
      s->gpu = [b gpuAddress];
      s->tile = [dev respondsToSelector:st] ? ((NSUInteger (*)(id, SEL, NSUInteger))objc_msgSend)(dev, st, page) : 65536;
      return 1;
    }
    case 42: {
      SEL sp = sel_registerName("setMaxCompatiblePlacementSparsePageSize:");
      MTLHeapDescriptor *hd = [[MTLHeapDescriptor alloc] init];
      id<MTLHeap> h;
      hd.type = MTLHeapTypePlacement; hd.storageMode = MTLStorageModePrivate; hd.size = (NSUInteger)s->length;
      hd.hazardTrackingMode = MTLHazardTrackingModeUntracked;
      if ([hd respondsToSelector:sp]) ((void (*)(id, SEL, NSUInteger))objc_msgSend)(hd, sp, page);
      h = [dev newHeapWithDescriptor:hd];
      [hd release];
      if (!h) return 0;
      s->heap = (uint64_t)(uintptr_t)h;
      return 1;
    }
    case 43: {
      SEL su = sel_registerName("updateBufferMappings:heap:operations:count:");
      SEL ss = sel_registerName("signalEvent:value:");
      SEL sw = sel_registerName("waitForEvent:value:");
      if (!g_madeira_sparse_q4) {
        SEL sq = sel_registerName("newMTL4CommandQueue");
        if (![dev respondsToSelector:sq]) return 0;
        g_madeira_sparse_q4 = ((id (*)(id, SEL))objc_msgSend)(dev, sq);
        if (!g_madeira_sparse_q4) return 0;
      }
      if (!s->buffer || !s->heap || !s->ops || !s->count || ![g_madeira_sparse_q4 respondsToSelector:su]) return 0;
      if (s->wait_event && s->wait_value && [g_madeira_sparse_q4 respondsToSelector:sw])
        ((void (*)(id, SEL, id, uint64_t))objc_msgSend)(g_madeira_sparse_q4, sw, (id)(uintptr_t)s->wait_event, s->wait_value);
      ((void (*)(id, SEL, id, id, const void *, NSUInteger))objc_msgSend)(g_madeira_sparse_q4, su, (id)(uintptr_t)s->buffer,
                                                                        (id)(uintptr_t)s->heap, (const void *)(uintptr_t)s->ops,
                                                                        (NSUInteger)s->count);
      if (s->signal_event && [g_madeira_sparse_q4 respondsToSelector:ss])
        ((void (*)(id, SEL, id, uint64_t))objc_msgSend)(g_madeira_sparse_q4, ss, (id)(uintptr_t)s->signal_event, s->signal_value);
      return 1;
    }
    }
  }
  return 0;
}
'''

CASE_ANCHOR = "  case 40:    /* madeira-doge: Metal 4 sparse probe; ptr = MTLDevice */\n"
CASE = """  case 41: case 42: case 43:   /* madeira-doge: Metal 4 sparse buffers; ptr = struct madeira_sparse_args */
    a->ret = madeira_sparse_ctl(a->op, (struct madeira_sparse_args *)(uintptr_t)a->ptr);
    break;
"""


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("winemetal_unix.c: sparse buffers already present")
        return 0
    for name, anchor in (("_madeira_ctl", FUNC_ANCHOR), ("case 40 (run patch-dxmt-sparse-probe.py first)", CASE_ANCHOR)):
        if s.count(anchor) != 1:
            sys.exit(f"patch-dxmt-sparse-buffers: anchor '{name}' not found exactly once in {PATH}")
    s = s.replace(FUNC_ANCHOR, FUNC + FUNC_ANCHOR, 1)
    s = s.replace(CASE_ANCHOR, CASE + CASE_ANCHOR, 1)
    PATH.write_text(s)
    print("winemetal_unix.c: sparse buffers added (MadeiraCtl ops 41-43)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
