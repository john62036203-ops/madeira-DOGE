#!/usr/bin/env python3
"""Zero-timeout waits answered locally yield the core more often.

EXVS2 battles have phases where a thread polls WaitForSingleObject(h, 0)
(with an EnterCriticalSection / LeaveCriticalSection pair around it) up to
7 million times a second for 10-15 s ([xp-api] wait1 7M/s, x64->EC 17-21M/s,
fps 0.1-20; logs 2026-10-25 01:55, 02:10). The fastsync poll peek answers
"not signaled" from the sync cell without a server call and yields only one
poll in 64 (MADEIRA_FS_PEEK_YIELD), so the poller keeps a P-core busy and
starves the thread it waits for.

Patched (wine/dlls/ntdll/unix/sync.c, madeira_peek_budget): one peeked poll
in N yields, N = madeira.cfg poll-yield-every (power of two, default 4; 64 is
the old behaviour, 0 = never). NtYieldExecution is the fork's adaptive yield:
after a streak of yields (yield-streak, 256) it sleeps yield-sleep-us (100),
so a pure polling loop drops from millions of iterations a second to a few
thousand while a poll that is answered soon still returns at once.

Unix side only: no PE export changes (build 454 crashed changing the
EnterCriticalSection FFS that ARM64EC code also calls). Idempotent.
Usage: patch-wine-poll-yield.py wine/dlls/ntdll/unix/sync.c
"""
import sys

MARKER = "madeira-doge poll-yield"

path = sys.argv[1]
src = open(path).read()
if MARKER in src:
    print("already patched"); sys.exit(0)

anchor = "    if (!(s & (MADEIRA_FS_PEEK_YIELD - 1))) NtYieldExecution();\n"
if src.count(anchor) != 1:
    sys.exit("patch-wine-poll-yield: madeira_peek_budget yield anchor not found exactly once")

src = src.replace(anchor, """    {   /* madeira-doge poll-yield (tools/patch-wine-poll-yield.py) */
        static int mask = -2;
        if (mask == -2)
        {
            long long v = madeira_cfg_int( "poll-yield-every", 4 );   /* one peeked zero-timeout poll in N yields (power of two; 64 = old; 0 = never) */
            int m = 1;
            if (v <= 0) m = 0;
            else { while (m < v && m < 1024) m <<= 1; }
            mask = m ? m - 1 : -1;
        }
        if (mask >= 0 && !(s & (unsigned int)mask)) NtYieldExecution();
    }
""")

open(path, "w").write(src)
print("patched " + path)
