#!/usr/bin/env python3
"""readback-swap (BCD 0.1.573) in madeira_d3d12.c: 1, the default, is the
behaviour so far (upload-swap moves UPLOAD and READBACK buffers of 8 MB or more
to the file tier); 0 keeps READBACK buffers on Metal-owned storage while UPLOAD
buffers stay as upload-swap says. Source checks plus a host build of the reader.
"""
from pathlib import Path
import os, shutil, subprocess, sys, tempfile

root = Path(__file__).resolve().parents[2]
src = (root / "madeira-d3d12/src/pe/madeira_d3d12.c").read_text()
catalog = (root / "app/Madeira/ConfigCatalog.generated.swift").read_text()
ok = True


def check(what, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


def block(start, end="\n}\n"):
    i = src.index(start)
    return src[i:src.index(end, i) + len(end)]


rbs = block("static int mad_readback_swap_on(void) {")
check("on by default (as before)", 'mad_cfg_int_pe("readback-swap", 1)' in rbs)
up = ('if (!r->buffer && heap_type != D3D12_HEAP_TYPE_DEFAULT && info.length >= (8u << 20) && mad_upload_swap_on() &&\n'
      '            (heap_type != D3D12_HEAP_TYPE_READBACK || mad_readback_swap_on())) {')
check("upload-swap's condition: only READBACK buffers ask readback-swap", up in src and src.count("mad_readback_swap_on()") == 1)
check("upload-swap itself unchanged (default 1)", 'mad_cfg_int_pe("upload-swap", 1)' in block("static int mad_upload_swap_on(void) {"))
check("settings catalog: readback-swap (default 1)",
      'ConfigOption(key: "readback-swap", title: "", kind: .int, defaultValue: "1", category: "Direct3D 12"' in catalog)
check("no BCD config name", "bcd.cfg" not in src)

harness = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
static long long g_v; static int g_set, g_logs;
static long long mad_cfg_int_pe(const char *key, long long dflt) { return !strcmp(key, "readback-swap") && g_set ? g_v : dflt; }
static void d3d12_log(const char *fmt, ...) { va_list ap; va_start(ap, fmt); g_logs++; vprintf(fmt, ap); va_end(ap); }
%s
int main(int argc, char **argv) {
    int on;
    if (argc > 1) { g_set = 1; g_v = atoll(argv[1]); }
    on = mad_readback_swap_on();
    if (mad_readback_swap_on() != on) return 3;
    printf("RESULT on=%%d logs=%%d\n", on, g_logs);
    return 0;
}
'''
cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
if not cc:
    print("note: no host C compiler; the reader was not built")
else:
    with tempfile.TemporaryDirectory() as tmp:
        c = os.path.join(tmp, "t.c"); exe = os.path.join(tmp, "t")
        with open(c, "w") as f:
            f.write(harness % rbs)
        r = subprocess.run([cc, "-std=c99", "-Wall", "-Werror", "-o", exe, c], capture_output=True, text=True)
        check("reader builds on the host", r.returncode == 0)
        if r.returncode:
            print(r.stderr)
        else:
            def run(*args):
                out = subprocess.run([exe] + [str(a) for a in args], capture_output=True, text=True)
                line = [l for l in out.stdout.splitlines() if l.startswith("RESULT")]
                return out.returncode, (line[0] if line else out.stdout)
            check("unset: on, silent", run() == (0, "RESULT on=1 logs=0"))
            check("1: on, silent", run(1) == (0, "RESULT on=1 logs=0"))
            check("0: off, one line", run(0) == (0, "RESULT on=0 logs=1"))
            check("2: on", run(2) == (0, "RESULT on=1 logs=0"))
sys.exit(0 if ok else 1)
