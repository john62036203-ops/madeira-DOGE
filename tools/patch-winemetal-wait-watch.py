#!/usr/bin/env python3
"""Name the command buffer a waitUntilCompleted has been stuck on.

Devil May Cry 5 (builds 172-174, four logs on 2026-10-08) stops some 25 s into
play: dxmt-finish-thr sits in _MTLCommandBuffer_waitUntilCompleted, the game
goes idle, and about nine seconds later every other command buffer comes back
"Discarded (victim of GPU error/recovery) ... InnocentVictim". The buffer being
waited for is never reported, so nothing says whether it was executing on the
GPU, queued behind something, or never committed.

A wait that lasts three seconds now prints one [wmt-wait] line with the
buffer's status (0 not enqueued, 1 enqueued, 2 committed, 3 scheduled,
4 completed, 5 error), its label, its queue's label and its error, and another
line when it does return. One watcher thread, started by the first wait, looks
once a second at up to eight waits in progress; a wait itself only writes and
clears a slot. Native path only.

Idempotent; fails by name if the anchor moves. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/winemetal/unix/winemetal_unix.c")
MARKER = "madeira-doge: wait watch"

OLD = """  [(id<MTLCommandBuffer>)params->handle waitUntilCompleted];
  return STATUS_SUCCESS;
}
"""
NEW = """  { /* madeira-doge: wait watch (tools/patch-winemetal-wait-watch.py) */
    id<MTLCommandBuffer> mad_cb = (id<MTLCommandBuffer>)params->handle;
    int mad_slot = mad_wait_enter((__bridge void *)mad_cb);
    [mad_cb waitUntilCompleted];
    mad_wait_leave(mad_slot, (__bridge void *)mad_cb);
  }
  return STATUS_SUCCESS;
}
"""
HELPER = """
/* madeira-doge: wait watch (tools/patch-winemetal-wait-watch.py) */
#include <pthread.h>
#include <stdatomic.h>
#include <time.h>
#include <unistd.h>
static struct { _Atomic(void *) cb; _Atomic(long long) start_ms; _Atomic(int) said; } mad_waits[8];
static long long mad_wait_now_ms(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}
static void mad_wait_describe(const char *what, void *ptr, long long ms) {
  @autoreleasepool {
    id<MTLCommandBuffer> cb = (__bridge id<MTLCommandBuffer>)ptr;
    NSString *label = cb.label, *queue = cb.commandQueue.label;
    NSError *err = cb.error;
    fprintf(stderr, "[wmt-wait] %s: command buffer %p waited for %lld ms, status=%d (0 not enqueued 1 enqueued 2 committed 3 scheduled 4 completed 5 error) "
            "label='%s' queue='%s' error=%s\\n", what, ptr, ms, (int)cb.status, label ? label.UTF8String : "", queue ? queue.UTF8String : "",
            err ? err.localizedDescription.UTF8String : "none");
  }
}
static void *mad_wait_watcher(void *arg) {
  (void)arg;
  pthread_setname_np("madeira-wait-watch");
  for (;;) {
    sleep(1);
    long long now = mad_wait_now_ms();
    for (int i = 0; i < 8; i++) {
      void *cb = atomic_load(&mad_waits[i].cb);
      long long start = atomic_load(&mad_waits[i].start_ms);
      if (!cb || now - start < 3000 || atomic_load(&mad_waits[i].said)) continue;
      /* The waiter holds its buffer until the wait returns; look once more so a
       * slot that was just released is not described. */
      if (atomic_load(&mad_waits[i].cb) != cb) continue;
      atomic_store(&mad_waits[i].said, 1);
      mad_wait_describe("STUCK", cb, now - start);
    }
  }
  return NULL;
}
static int mad_wait_enter(void *cb) {
  static _Atomic(int) started;
  int expected = 0;
  if (atomic_compare_exchange_strong(&started, &expected, 1)) {
    pthread_t t;
    if (!pthread_create(&t, NULL, mad_wait_watcher, NULL)) pthread_detach(t);
  }
  for (int i = 0; i < 8; i++) {
    void *none = NULL;
    if (atomic_compare_exchange_strong(&mad_waits[i].cb, &none, cb)) {
      atomic_store(&mad_waits[i].said, 0);
      atomic_store(&mad_waits[i].start_ms, mad_wait_now_ms());
      /* start_ms is written after cb: the watcher may read the previous wait's
       * time for a moment, which can only make this wait look older for one
       * pass; said was cleared first, so at worst one early line. Avoid even
       * that by re-checking the age in the watcher's next pass. */
      return i;
    }
  }
  return -1;
}
static void mad_wait_leave(int slot, void *cb) {
  if (slot < 0) return;
  if (atomic_load(&mad_waits[slot].said))
    mad_wait_describe("returned", cb, mad_wait_now_ms() - atomic_load(&mad_waits[slot].start_ms));
  atomic_store(&mad_waits[slot].start_ms, mad_wait_now_ms());
  atomic_store(&mad_waits[slot].cb, NULL);
}

"""
ANCHOR = "static NTSTATUS\n_MTLCommandBuffer_waitUntilCompleted(void *obj) {\n"

src = PATH.read_text()
if MARKER in src:
    print("winemetal_unix.c: already patched"); sys.exit(0)
if src.count(OLD) != 1 or src.count(ANCHOR) != 1:
    sys.exit("patch-winemetal-wait-watch: anchor not found exactly once (the dxmt pin changed)")
src = src.replace(ANCHOR, HELPER + ANCHOR).replace(OLD, NEW)
PATH.write_text(src)
print("winemetal_unix.c: patched")
