#!/usr/bin/env python3
"""madeira.cfg x64-fast (build/ntdll-unix/x64fast_ios.h).

1. The stub bytes in the header equal tests/host/x64fast/stubs.asm assembled.
2. patch.c runs the header's installer on the shipped ntdll/kernelbase/kernel32
   and follows every patched entry back to its original target.
3. stress.c runs the stubs natively (x86-64 Linux, gs = a fake TEB) against
   Wine's C critical-section code with several threads on one section.
Needs nasm and gcc on x86-64; otherwise it says so and passes."""
import os, platform, re, shutil, subprocess, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
D = os.path.join(ROOT, "tests", "host", "x64fast")
HDR = os.path.join(ROOT, "build", "ntdll-unix", "x64fast_ios.h")
DLLS = os.path.join(ROOT, "app", "Madeira", "arm64ec-windows")
STUBS = ["cs_enter", "cs_leave", "cs_try", "le_set", "le_get", "tls_get", "fls_get"]

if not (shutil.which("nasm") and shutil.which("gcc") and platform.machine() in ("x86_64", "AMD64")):
    print("note: nasm/gcc on x86-64 unavailable, x64-fast checks skipped")
    sys.exit(0)

tmp = tempfile.mkdtemp()
run = lambda *a, **k: subprocess.run(a, check=True, capture_output=True, text=True, **k)
run("nasm", "-f", "elf64", os.path.join(D, "stubs.asm"), "-o", os.path.join(tmp, "stubs.o"))
run("nasm", "-f", "bin", os.path.join(D, "stubs.asm"), "-o", os.path.join(tmp, "stubs.bin"))
syms = {}
for line in run("nm", os.path.join(tmp, "stubs.o")).stdout.splitlines():
    p = line.split()
    if len(p) == 3 and p[1] == "T":
        syms[p[2]] = int(p[0], 16)
blob = open(os.path.join(tmp, "stubs.bin"), "rb").read()
hdr = open(HDR).read()
bad = 0
for n in STUBS:
    m = re.search(r"x64f_%s\[\d+\] = \{([^}]*)\}" % n, hdr)
    got = bytes(int(x, 16) for x in re.findall(r"0x[0-9a-f]{2}", m.group(1))) if m else b""
    want = blob[syms[n]:syms[n + "_end"]]
    ok = got == want
    bad += not ok
    print("ok  " if ok else "FAIL", "header bytes of", n, "match stubs.asm")
enter = blob[syms["cs_enter"]:syms["cs_enter_end"]]
spin_at = int(re.search(r"#define X64F_SPIN_AT (\d+)", hdr).group(1))
ok = enter[spin_at:spin_at + 4] == b"\x5a" * 4
bad += not ok
print("ok  " if ok else "FAIL", "X64F_SPIN_AT points at the spin count")

for f in ("ntdll.dll", "kernelbase.dll", "kernel32.dll"):
    shutil.copy(os.path.join(DLLS, f), tmp)
run("gcc", "-O1", "-w", "-o", os.path.join(tmp, "patch"), os.path.join(D, "patch.c"))
r = subprocess.run([os.path.join(tmp, "patch")] + [os.path.join(tmp, f) for f in ("ntdll.dll", "kernelbase.dll", "kernel32.dll")],
                   capture_output=True, text=True)
print(r.stdout.rstrip())
ok = r.returncode == 0 and "PASS" in r.stdout
bad += not ok
print("ok  " if ok else "FAIL", "installer patches the shipped DLLs and keeps every original target")

run("gcc", "-O2", "-pthread", "-o", os.path.join(tmp, "stress"), os.path.join(D, "stress.c"), os.path.join(tmp, "stubs.o"))
for threads, spin in ((1, 0), (4, 0), (4, 200), (8, 50)):
    r = subprocess.run([os.path.join(tmp, "stress"), str(threads), str(spin)], capture_output=True, text=True,
                       env=dict(os.environ, ITERS="300000"))
    ok = r.returncode == 0 and "PASS" in r.stdout
    bad += not ok
    print("ok  " if ok else "FAIL", r.stdout.strip() or r.stderr.strip())
print("FAILED" if bad else "PASSED")
sys.exit(1 if bad else 0)
