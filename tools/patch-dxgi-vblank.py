#!/usr/bin/env python3
"""madeira-doge: IDXGIOutput::WaitForVBlank waits for the next 60 Hz tick.

DXMT returns S_OK at once. Gundam EXVS2 IB (vsac29_Release.exe) runs a
"RefreshCountThread" that loops on WaitForVBlank and increments a 32-bit
vblank counter the game paces itself by: with no wait it counted ~44 million
"vblanks" a second (dxgi.dll+0x7fc0 = 44M calls/s in [xp-api-top]), the
counter wrapped after ~97 s and the game stopped presenting for good (build
381, 2026-10-23 02:37 log: Present #5930 at t+99 s, then nothing). On the PC
the same game needs a frame limiter on GPUs whose driver returns early too.

The wait lands on a fixed 1/60 s grid of QueryPerformanceCounter time, like a
real 60 Hz display: Sleep for all but the last millisecond, then yield.
Patches a copy of src/dxgi/dxgi_output.cpp in place; idempotent.
"""
import sys

OLD = "WaitForVBlank() final { return S_OK; }"
NEW = """WaitForVBlank() final {
    /* madeira-doge: wait for the next 60 Hz tick (tools/patch-dxgi-vblank.py) */
    static LARGE_INTEGER freq;
    LARGE_INTEGER now;
    if (!freq.QuadPart) QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&now);
    const LONGLONG period = freq.QuadPart / 60 ? freq.QuadPart / 60 : 1;
    const LONGLONG next = (now.QuadPart / period + 1) * period;
    for (;;) {
      QueryPerformanceCounter(&now);
      const LONGLONG left = next - now.QuadPart;
      if (left <= 0) break;
      const LONGLONG ms = left * 1000 / freq.QuadPart;
      if (ms > 1) Sleep((DWORD)(ms - 1));
      else SwitchToThread();
    }
    return S_OK;
  }"""

def main(path):
    s = open(path, encoding="utf-8").read()
    if "tools/patch-dxgi-vblank.py" in s:
        return 0
    if s.count(OLD) != 1:
        print("patch-dxgi-vblank: anchor not found once in", path, file=sys.stderr)
        return 1
    open(path, "w", encoding="utf-8").write(s.replace(OLD, NEW))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
