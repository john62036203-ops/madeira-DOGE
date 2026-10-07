#!/usr/bin/env python3
"""eco-workers: the low QoS class for worker threads only.

ECO (ml1133, madeira.cfg eco = 1) runs every guest thread at a low QoS class
so the SoC spends less energy and keeps its clock longer; the main thread
slows down with the rest. Sekiro on an iPhone 16 Pro Max (build 144, log
2026-10-07 01:03) keeps one thread on a P-core about 80 % of the time and five
job threads at about 45 % each; in play the P cluster runs at 2.0-2.2 GHz
against 3.8-3.9 GHz while loading. madeira.cfg eco-workers = 1 gives the eco
class (eco-qos: utility by default, background, initiated) to threads started
by NtCreateThreadEx and leaves a process's first thread at USER_INTERACTIVE,
to see whether the main thread then keeps a higher clock. eco = 1 still wins
for every thread. Unset, nothing changes. eco-workers = N (2..16) leaves
every Nth worker at the normal class: with all workers low (build 146, log
2026-10-07 08:06) the P clock rose to about 3.1 GHz but one P-core sat idle
and the frame rate did not rise.

Patches wine/dlls/ntdll/unix/sync.c in place (build/ntdll-unix/thread_ios.c
marks the worker threads). Idempotent; fails by name if an anchor moves. Run
from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("wine/dlls/ntdll/unix/sync.c")
MARKER = "madeira-doge: eco-workers"

PAIRS = [
    ("""static __thread int ios_eco_seen;      /* generation this thread last applied */
""",
     """static __thread int ios_eco_seen;      /* generation this thread last applied */
/* madeira-doge: eco-workers (tools/patch-wine-eco-workers.py) */
static volatile int ios_eco_workers;   /* madeira.cfg eco-workers */
static __thread int ios_eco_worker;    /* 1 + this thread's start order; 0 = a process's first thread */
static int ios_eco_worker_seq;
void ios_eco_mark_worker(void) { ios_eco_worker = 1 + __atomic_fetch_add( &ios_eco_worker_seq, 1, __ATOMIC_RELAXED ); }
/* eco-workers = 1: every worker; N >= 2: every worker except each Nth, which keeps the normal class */
static int ios_eco_worker_low(void)
{
    int n = ios_eco_workers;
    if (!n || !ios_eco_worker) return 0;
    return n == 1 || ((ios_eco_worker - 1) % n) != 0;
}
"""),
    ("""    __atomic_store_n( &ios_eco_on, madeira_cfg_bool( "eco", 0 ) ? 1 : 0, __ATOMIC_RELEASE );
}
""",
     """    ios_eco_workers = (int)madeira_cfg_int( "eco-workers", 0 );
    if (ios_eco_workers < 0 || ios_eco_workers > 16) ios_eco_workers = 0;
    if (ios_eco_workers)
        fprintf( stderr, "[eco] madeira-doge: eco-workers = %d: threads other than a process's first%s run at %s\\n",
                 ios_eco_workers, ios_eco_workers > 1 ? " (each Nth excepted)" : "",
                 ios_eco_class == QOS_CLASS_BACKGROUND ? "background"
                 : ios_eco_class == QOS_CLASS_USER_INITIATED ? "user-initiated" : "utility" );
    __atomic_store_n( &ios_eco_on, madeira_cfg_bool( "eco", 0 ) ? 1 : 0, __ATOMIC_RELEASE );
}
"""),
    ("""    pthread_set_qos_class_self_np( ios_eco_on > 0 ? ios_eco_class : QOS_CLASS_USER_INTERACTIVE, 0 );
""",
     """    pthread_set_qos_class_self_np( ios_eco_on > 0 || ios_eco_worker_low() ? ios_eco_class
                                   : QOS_CLASS_USER_INTERACTIVE, 0 );
"""),
]


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("sync.c: already patched")
        return 0
    for old, new in PAIRS:
        if s.count(old) != 1:
            sys.exit(f"patch-wine-eco-workers: anchor found {s.count(old)} times (want 1) in {PATH}:\\n{old}")
        s = s.replace(old, new)
    PATH.write_text(s)
    print("sync.c: patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
