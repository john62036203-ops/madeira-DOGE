#!/usr/bin/env python3
"""Probe Metal 4 placement-sparse buffers from winemetal (MadeiraCtl op 40).

madeira-d3d12 backs D3D12 reserved (tiled) resources fully, so a 64 MB
reserved buffer the game maps 161 tiles of costs 64 MB of memory that iOS wires
whenever the GPU runs (Monster Hunter Wilds, 2026-10-18: 400-512 MB of reserved
buffers live, the device dies at ~5 GB wired). Real tiling needs Metal 4
placement-sparse buffers, whose tiles are mapped onto a placement heap through
an MTL4CommandQueue. Before rewriting the tiled path, this answers on device:

  - does the device answer the Metal 4 selectors (looked up at run time, so the
    file builds with any SDK);
  - can a placement heap, a placement-sparse buffer and an MTL4 queue be made;
  - after mapping tile 0 through the MTL4 queue, does a CLASSIC command buffer
    (the queue madeira-d3d12 uses), ordered after the mapping by a shared
    event, write and read that tile correctly;
  - what a read of an UNMAPPED tile does (command buffer error or a value).

madeira-d3d12 calls it once per device when madeira.cfg sparse-probe = 1. Every
step prints a [sparse-probe] line; ret is a bit mask (see the code).
Idempotent; fails by name if an anchor moved. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/winemetal/unix/winemetal_unix.c")
MARKER = "madeira-doge: Metal 4 sparse probe"

FUNC_ANCHOR = "static NTSTATUS _madeira_ctl(void *args) {\n"
FUNC = r'''/* madeira-doge: Metal 4 sparse probe (tools/patch-dxmt-sparse-probe.py). */
#include <objc/message.h>
#include <objc/runtime.h>
struct madeira_sparse_op { NSUInteger mode; NSRange range; NSUInteger heap_offset; };   /* MTL4UpdateSparseBufferMappingOperation */
static int madeira_sparse_wait(id<MTLCommandBuffer> cb, double seconds) {
  int i;
  for (i = 0; i < (int)(seconds * 100); i++) {
    MTLCommandBufferStatus st = [cb status];
    if (st == MTLCommandBufferStatusCompleted || st == MTLCommandBufferStatusError) return 1;
    usleep(10000);
  }
  return 0;
}
static uint32_t madeira_sparse_probe(id<MTLDevice> dev) {
  uint32_t r = 0;
  if (!dev || wmtr_enabled()) return 0;
  @autoreleasepool {
    SEL s_new_sparse = sel_registerName("newBufferWithLength:options:placementSparsePageSize:");
    SEL s_new_q4 = sel_registerName("newMTL4CommandQueue");
    SEL s_tile = sel_registerName("sparseTileSizeInBytesForSparsePageSize:");
    SEL s_heap_page = sel_registerName("setMaxCompatiblePlacementSparsePageSize:");
    SEL s_update = sel_registerName("updateBufferMappings:heap:operations:count:");
    SEL s_signal = sel_registerName("signalEvent:value:");
    int has_sparse = [dev respondsToSelector:s_new_sparse], has_q4 = [dev respondsToSelector:s_new_q4];
    int has_tile = [dev respondsToSelector:s_tile];
    NSUInteger page = 102;   /* MTLSparsePageSize64 */
    NSUInteger tile = 65536;
    MTLHeapDescriptor *hd;
    id<MTLHeap> heap = nil;
    id<MTLBuffer> sb = nil, rb = nil;
    id q4 = nil;
    id<MTLSharedEvent> ev = nil;
    id<MTLCommandQueue> cq = nil;
    id<MTLResidencySet> rs = nil;
    fprintf(stderr, "[sparse-probe] madeira-doge: %s: newBuffer...placementSparsePageSize %s, newMTL4CommandQueue %s, "
                    "sparseTileSizeInBytesForSparsePageSize %s\n", [[dev name] UTF8String],
            has_sparse ? "yes" : "NO", has_q4 ? "yes" : "NO", has_tile ? "yes" : "NO");
    if (!has_sparse || !has_q4) return 1;
    if (has_tile) tile = ((NSUInteger (*)(id, SEL, NSUInteger))objc_msgSend)(dev, s_tile, page);
    hd = [[MTLHeapDescriptor alloc] init];
    hd.type = MTLHeapTypePlacement; hd.storageMode = MTLStorageModePrivate; hd.size = 4 * tile;
    if ([hd respondsToSelector:s_heap_page]) ((void (*)(id, SEL, NSUInteger))objc_msgSend)(hd, s_heap_page, page);
    heap = [dev newHeapWithDescriptor:hd];
    [hd release];
    sb = ((id (*)(id, SEL, NSUInteger, NSUInteger, NSUInteger))objc_msgSend)(dev, s_new_sparse, 16 * tile,
                                                                            (NSUInteger)MTLResourceStorageModePrivate, page);
    rb = [dev newBufferWithLength:2 * tile options:MTLResourceStorageModeShared];
    q4 = ((id (*)(id, SEL))objc_msgSend)(dev, s_new_q4);
    ev = [dev newSharedEvent];
    cq = [dev newCommandQueue];
    fprintf(stderr, "[sparse-probe] tile %lu bytes; heap %p, sparse buffer %p (gpu 0x%llx), MTL4 queue %p (update %s, signal %s)\n",
            (unsigned long)tile, heap, sb, sb ? (unsigned long long)[sb gpuAddress] : 0ull, q4,
            (q4 && [q4 respondsToSelector:s_update]) ? "yes" : "NO", (q4 && [q4 respondsToSelector:s_signal]) ? "yes" : "NO");
    if (!heap || !sb || !rb || !q4 || !ev || !cq || ![q4 respondsToSelector:s_update] || ![q4 respondsToSelector:s_signal]) goto done;
    r |= 2;
    {
      MTLResidencySetDescriptor *rd = [[MTLResidencySetDescriptor alloc] init];
      NSError *err = nil;
      rs = [dev newResidencySetWithDescriptor:rd error:&err];
      [rd release];
      if (rs) { [rs addAllocation:heap]; [rs addAllocation:sb]; [rs addAllocation:rb]; [rs commit]; [cq addResidencySet:rs]; }
    }
    {
      struct madeira_sparse_op op = { 0 /* MTLSparseTextureMappingModeMap */, NSMakeRange(0, 1), 0 };
      ((void (*)(id, SEL, id, id, const void *, NSUInteger))objc_msgSend)(q4, s_update, sb, heap, &op, 1);
      ((void (*)(id, SEL, id, uint64_t))objc_msgSend)(q4, s_signal, ev, 1);
      r |= 4;
    }
    {
      id<MTLCommandBuffer> cb = [cq commandBuffer];
      id<MTLBlitCommandEncoder> be;
      const unsigned char *p = [rb contents];
      [cb encodeWaitForEvent:ev value:1];
      be = [cb blitCommandEncoder];
      [be fillBuffer:rb range:NSMakeRange(0, 2 * tile) value:0x11];
      [be fillBuffer:sb range:NSMakeRange(0, tile) value:0x5a];
      [be copyFromBuffer:sb sourceOffset:0 toBuffer:rb destinationOffset:0 size:tile];
      [be endEncoding];
      [cb commit];
      if (!madeira_sparse_wait(cb, 3.0)) {
        fprintf(stderr, "[sparse-probe] mapped tile: classic command buffer did not finish in 3 s (the event wait never released?)\n");
        goto done;
      }
      if ([cb status] == MTLCommandBufferStatusError) {
        fprintf(stderr, "[sparse-probe] mapped tile: command buffer ERROR: %s\n", [[[cb error] description] UTF8String]);
        goto done;
      }
      fprintf(stderr, "[sparse-probe] mapped tile: wrote 0x5a, read back %02x %02x .. %02x (%s)\n", p[0], p[1], p[tile - 1],
              (p[0] == 0x5a && p[tile - 1] == 0x5a) ? "CORRECT" : "WRONG");
      if (p[0] == 0x5a && p[tile - 1] == 0x5a) r |= 8;
    }
    {
      id<MTLCommandBuffer> cb = [cq commandBuffer];
      id<MTLBlitCommandEncoder> be = [cb blitCommandEncoder];
      const unsigned char *p = [rb contents];
      [be fillBuffer:rb range:NSMakeRange(tile, tile) value:0x11];
      [be copyFromBuffer:sb sourceOffset:5 * tile toBuffer:rb destinationOffset:tile size:tile];
      [be endEncoding];
      [cb commit];
      if (!madeira_sparse_wait(cb, 3.0)) {
        fprintf(stderr, "[sparse-probe] unmapped tile: command buffer did not finish in 3 s\n");
        goto done;
      }
      if ([cb status] == MTLCommandBufferStatusError)
        fprintf(stderr, "[sparse-probe] unmapped tile: command buffer ERROR: %s\n", [[[cb error] description] UTF8String]);
      else {
        r |= 16;
        if (p[tile] == 0 && p[2 * tile - 1] == 0) r |= 32;
        fprintf(stderr, "[sparse-probe] unmapped tile: read %02x .. %02x (%s)\n", p[tile], p[2 * tile - 1],
                (r & 32) ? "zeros, as D3D12 Tier 2 wants" : "not zeros");
      }
    }
  done:
    fprintf(stderr, "[sparse-probe] result 0x%x (1 API missing, 2 objects made, 4 mapping sent, 8 mapped tile correct, "
                    "16 unmapped read survived, 32 unmapped read zeros)\n", r);
    if (rs) [rs release];
    if (cq) [cq release];
    if (ev) [ev release];
    if (q4) [q4 release];
    if (rb) [rb release];
    if (sb) [sb release];
    if (heap) [heap release];
  }
  return r;
}
'''

CASE_ANCHOR = """  case 2: {
    char v[512];
    if (madeira_cfg_get(a->name, v, sizeof v)) {"""
CASE = """  case 40:    /* madeira-doge: Metal 4 sparse probe; ptr = MTLDevice */
    a->ret = madeira_sparse_probe((id<MTLDevice>)(uintptr_t)a->ptr);
    break;
"""


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("winemetal_unix.c: sparse probe already present")
        return 0
    for name, anchor in (("_madeira_ctl", FUNC_ANCHOR), ("case 2", CASE_ANCHOR)):
        if s.count(anchor) != 1:
            sys.exit(f"patch-dxmt-sparse-probe: anchor '{name}' not found exactly once in {PATH}")
    s = s.replace(FUNC_ANCHOR, FUNC + FUNC_ANCHOR, 1)
    s = s.replace(CASE_ANCHOR, CASE + CASE_ANCHOR, 1)
    PATH.write_text(s)
    print("winemetal_unix.c: sparse probe added (MadeiraCtl op 40)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
