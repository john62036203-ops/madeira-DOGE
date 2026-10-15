#!/usr/bin/env python3
"""Log every failed command buffer of the process, cause or victim (MADEIRA_GPU_CAUSE=1).

Sekiro (logs 2026-10-15, builds 197-199): every one to three minutes the GPU
stops for ~10 s and iOS restarts it. DXMT logs only its own main-queue buffers,
and all of them say "Discarded (victim of GPU error/recovery)
(kIOGPUCommandBufferCallbackErrorInnocentVictim)": the work that caused the
restart is not among them. MetalFX off did not change it, and neither did the
strong compare-exchange (tools/patch-airconv-cas-retry.py).

With MADEIRA_GPU_CAUSE=1 every command buffer committed through winemetal --
DXMT's main queue, its resource-initializer upload queue, the presenter and
MetalFX, whatever queue they use -- gets a completion handler. A buffer that
ends in error is logged as

  [gpu-cause] CAUSE|victim cb=<ptr> queue=<ptr> '<queue label>' '<cb label>'
              gpu=<start>..<end> (<ms> ms) code=<n> '<description>'

with GPU times on the same clock for every queue, so the buffer that ran
longest before the restart stands out even when Metal calls it a victim. New
queues are logged once as "[gpu-cause] queue #<n> = <ptr>" in creation order.
At most 400 lines; a tally line every 25 errors. If no CAUSE line ever appears
while victims do, the restart came from outside this process's buffers.

Native only (winemetal). Run after tools/patch-winemetal-gpu-trace.py.
Idempotent; fails by name if an anchor moves. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/winemetal/unix/winemetal_unix.c")
MARKER = "madeira-doge: gpu cause"

HELPERS = r'''/* madeira-doge: gpu cause (tools/patch-winemetal-gpu-cause.py) */
static int madeira_gpu_cause_on(void) {
  static int on = -1;
  if (on < 0) {
    const char *e = getenv("MADEIRA_GPU_CAUSE");
    on = (e && e[0] == '1') ? 1 : 0;
    if (on)
      fprintf(stderr, "[gpu-cause] madeira-doge: logging every failed command buffer (MADEIRA_GPU_CAUSE=1)\n");
  }
  return on;
}
static _Atomic(int) g_mad_gc_lines, g_mad_gc_queues, g_mad_gc_cause, g_mad_gc_victim;
static void madeira_gpu_cause_attach(id<MTLCommandBuffer> cmdbuf) {
  [cmdbuf addCompletedHandler:^(id<MTLCommandBuffer> b) {
    NSError *err = b.error;
    if (b.status != MTLCommandBufferStatusError || !err)
      return;
    @autoreleasepool {
      const char *desc = err.localizedDescription.UTF8String;
      int victim = desc && strstr(desc, "InnocentVictim") != NULL;
      int n = victim ? atomic_fetch_add(&g_mad_gc_victim, 1) + 1 : atomic_fetch_add(&g_mad_gc_cause, 1) + 1;
      if (atomic_fetch_add(&g_mad_gc_lines, 1) >= 400)
        return;
      id<MTLCommandQueue> q = b.commandQueue;
      double s = b.GPUStartTime, e = b.GPUEndTime;
      fprintf(stderr, "[gpu-cause] %s #%d cb=%p queue=%p '%.40s' '%.40s' gpu=%.3f..%.3f (%.1f ms) code=%ld '%.200s'\n",
              victim ? "victim" : "CAUSE", n, (void *)b, (void *)q,
              q.label.UTF8String ? q.label.UTF8String : "", b.label.UTF8String ? b.label.UTF8String : "",
              s, e, (s > 0.0 && e > s) ? (e - s) * 1000.0 : 0.0, (long)err.code, desc ? desc : "?");
      int tot = atomic_load(&g_mad_gc_cause) + atomic_load(&g_mad_gc_victim);
      if (tot % 25 == 0)
        fprintf(stderr, "[gpu-cause] tally: %d causes, %d victims\n", atomic_load(&g_mad_gc_cause),
                atomic_load(&g_mad_gc_victim));
    }
  }];
}

static NTSTATUS
_MTLDevice_newCommandQueue(void *obj) {'''


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("winemetal_unix.c: gpu cause already patched")
        return 0
    pairs = [
        ("""static NTSTATUS
_MTLDevice_newCommandQueue(void *obj) {""", HELPERS),
        ("""  params->ret = (obj_handle_t)[(id<MTLDevice>)params->handle newCommandQueueWithMaxCommandBufferCount:params->arg];
  return STATUS_SUCCESS;
}""",
         """  params->ret = (obj_handle_t)[(id<MTLDevice>)params->handle newCommandQueueWithMaxCommandBufferCount:params->arg];
  if (madeira_gpu_cause_on())   /* madeira-doge: gpu cause */
    fprintf(stderr, "[gpu-cause] queue #%d = %p (max %llu command buffers)\\n", atomic_fetch_add(&g_mad_gc_queues, 1) + 1,
            (void *)params->ret, (unsigned long long)params->arg);
  return STATUS_SUCCESS;
}"""),
        ("""  [(id<MTLCommandBuffer>)params->handle commit];
  madeira_gt_after_commit(params->handle);   /* madeira-bcd: gpu trace */""",
         """  if (madeira_gpu_cause_on())   /* madeira-doge: gpu cause */
    madeira_gpu_cause_attach((id<MTLCommandBuffer>)params->handle);
  [(id<MTLCommandBuffer>)params->handle commit];
  madeira_gt_after_commit(params->handle);   /* madeira-bcd: gpu trace */"""),
    ]
    for old, new in pairs:
        if s.count(old) != 1:
            print(f"::error::{PATH}: gpu cause anchor found {s.count(old)} times (want 1):\n{old}")
            return 1
        s = s.replace(old, new)
    if MARKER not in s:
        print(f"::error::{PATH}: gpu cause marker missing")
        return 1
    PATH.write_text(s)
    print("winemetal_unix.c: gpu cause patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
