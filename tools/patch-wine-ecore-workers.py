#!/usr/bin/env python3
"""Opt-in: a process's worker threads go to the efficiency cores.

Sekiro on an iPhone 16 Pro Max (builds 140-142, logs 2026-10-06/07): while
loading, with one or two busy threads, the main thread's P-core runs at
3.8-3.9 GHz; in play, with the main thread and five job threads busy on all
six cores, the P cluster runs at 1.6-2.2 GHz and the game makes 13-19 frames a
second. The job threads spend about a quarter of their time on the second
P-core. This lets the P cluster be the main thread's alone, to see whether its
clock then stays up.

tools/patch-wine-thread-qos.py leaves every thread below the realtime band at
its pthread QoS (USER_INTERACTIVE). With env.MADEIRA_ECORE_WORKERS = 1, a
thread that is not its process's first thread and whose Windows base priority
is NORMAL or lower takes wineserver's Mach policies after all (throughput tier
1, importance 0), which is what put a NORMAL thread on the efficiency cores
before that patch. First threads, threads the game raised above NORMAL and the
realtime band are untouched. Unset, nothing changes. [thread-prio] lines say
which threads were moved.

Run after patch-wine-thread-qos.py, from the repository root. Idempotent;
fails by name if the anchor moves.
"""
import pathlib
import sys

PATH = pathlib.Path("wine/server/thread.c")
MARKER = "madeira-doge: E-core workers"

OLD = """        if (keep) return;
    }
#endif
"""
NEW = """        if (keep)
        {
            /* madeira-doge: E-core workers (tools/patch-wine-ecore-workers.py) */
            static int ecore = -1, moved;
            if (ecore < 0)
            {
                const char *w = getenv( "MADEIRA_ECORE_WORKERS" );
                ecore = w && w[0] == '1';
                if (ecore) fprintf( stderr, "[thread-prio] madeira-doge: worker threads at NORMAL or lower take the Mach policies "
                                            "(efficiency cores); first threads keep their QoS (env.MADEIRA_ECORE_WORKERS)\\n" );
            }
            if (!ecore || thread->base_priority > THREAD_PRIORITY_NORMAL ||
                thread == get_process_first_thread( thread->process )) return;
            if (moved < 64)
            {
                moved++;
                fprintf( stderr, "[thread-prio] madeira-doge tid=%04x base=%d: worker, Mach policies\\n",
                         thread->id, thread->base_priority );
            }
        }
    }
#endif
"""


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("thread.c: already patched")
        return 0
    if s.count(OLD) != 1:
        sys.exit(f"patch-wine-ecore-workers: anchor found {s.count(OLD)} times (want 1) in {PATH}; run patch-wine-thread-qos.py first")
    PATH.write_text(s.replace(OLD, NEW))
    print("thread.c: patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
