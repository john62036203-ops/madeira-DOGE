#!/usr/bin/env python3
"""Orphan-lock reaper: only a lock whose waiters have been parked for seconds.

ios_orphan_check (ml447) force-releases an exclusively held SRW lock that has
three or more parked waiters and no live thread's stamp, seen on three monitor
cycles in a row. A busy lock looks exactly like that at any instant: Sekiro's
D3D11 lock at 0x4f4d5d1f8 (build 149, log 2026-10-07 09:23) is contended tens
of thousands of times a second, was "reaped" seven times in five minutes, and
each of the five "[wmt-buf] updateContents on a buffer with no contents" lines
follows a reap of that lock by a few lines, as does the crash in d3d11
(+0x10d840). Releasing a lock its owner still holds lets a second thread into
the section.

An orphaned lock makes no progress, so its waiters stay parked. Require every
waiter on the address to have been parked for at least 5 seconds before a
strike counts; madeira.cfg lock-reap = 0 turns the reaper off.

Patches wine/dlls/ntdll/unix/sync.c in place. Idempotent; fails by name if an
anchor moves. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("wine/dlls/ntdll/unix/sync.c")
MARKER = "madeira-doge: orphan-age"

PAIRS = [
    ("""        for (j = 0; j < IOS_ALERT_WAITER_MAX; j++)
            if (ios_alert_waiters[j].addr == a) nsame++;
        if (nsame < 3) continue;
        {
            char *page = (char *)((ULONG_PTR)lock & ~0x3fffULL);
            if (msync( page, 0x4000, MS_ASYNC )) continue;
            word = *(volatile unsigned int *)(ULONG_PTR)lock;
        }
""",
     """        for (j = 0; j < IOS_ALERT_WAITER_MAX; j++)
            if (ios_alert_waiters[j].addr == a) nsame++;
        if (nsame < 3) continue;
        /* madeira-doge: orphan-age (tools/patch-wine-orphan-age.py) */
        {
            static int reap_on = -1;
            LARGE_INTEGER now;
            LONGLONG youngest = 0x7fffffffffffffffll;

            if (reap_on < 0)
            {
                reap_on = madeira_cfg_int( "lock-reap", 1 ) ? 1 : 0;
                if (!reap_on) dprintf( 2, "[lock-orphan] madeira-doge: lock-reap = 0, no lock is force-released\\n" );
            }
            if (!reap_on) continue;
            NtQuerySystemTime( &now );
            for (j = 0; j < IOS_ALERT_WAITER_MAX; j++)
                if (ios_alert_waiters[j].addr == a)
                {
                    LONGLONG age = now.QuadPart - (LONGLONG)ios_alert_waiters[j].since;
                    if (age < youngest) youngest = age;
                }
            if (youngest < 5 * 10000000ll)
            {
                /* waiters come and go: the lock is busy, not orphaned */
                for (j = 0; j < 8; j++)
                    if (susp[j].lock == lock) { susp[j].lock = 0; susp[j].strikes = 0; }
                continue;
            }
        }
        {
            char *page = (char *)((ULONG_PTR)lock & ~0x3fffULL);
            if (msync( page, 0x4000, MS_ASYNC )) continue;
            word = *(volatile unsigned int *)(ULONG_PTR)lock;
        }
"""),
]


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("sync.c: already patched")
        return 0
    for old, new in PAIRS:
        if s.count(old) != 1:
            sys.exit(f"patch-wine-orphan-age: anchor found {s.count(old)} times (want 1) in {PATH}:\n{old}")
        s = s.replace(old, new)
    PATH.write_text(s)
    print("sync.c: patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
