#!/usr/bin/env python3
"""madeira-doge: tools/patch-wine-ntdll-x64fast.py (ntdll-x64fast.dll, Playport's x64
critical-section and QueryPerformanceCounter stubs) on a copy of the pinned wine tree:
it applies, a second run changes nothing, time.c keeps no old qpc_* name, both switches
are read only through RtlQueryEnvironmentVariable_U and must be "1"; the build script
builds it after the stock check and restores time.c; the unix loader and the app map
it only with either switch 1 and MADEIRA_NTDLL_PROTON not 1. With a clang that knows
arm64ec-pc-windows-msvc, loader.c and time.c are syntax-checked after the patch."""
from pathlib import Path
import shutil, subprocess, sys, tempfile

root = Path(__file__).resolve().parents[2]
ok = True


def check(what, cond, detail=""):
    global ok
    print(("PASS: " if cond else "FAIL: ") + what + (("\n      " + str(detail)[:1500]) if detail and not cond else ""))
    ok = ok and bool(cond)


nt = root / "wine/dlls/ntdll"
if not (nt / "loader.c").is_file():
    print("FAIL: the wine submodule has no dlls/ntdll/loader.c")
    sys.exit(1)
with tempfile.TemporaryDirectory() as tmp:
    w = Path(tmp) / "wine"
    shutil.copytree(root / "wine/include", w / "include")
    (w / "dlls").mkdir(parents=True)
    shutil.copytree(nt, w / "dlls/ntdll", ignore=shutil.ignore_patterns("unix"))
    tool = [sys.executable, str(root / "tools/patch-wine-ntdll-x64fast.py"), str(w)]
    r1 = subprocess.run(tool, capture_output=True, text=True)
    check("the patch applies to the pinned wine", r1.returncode == 0, r1.stdout + r1.stderr)
    after = {f: (w / "dlls/ntdll" / f).read_text() for f in ("loader.c", "time.c", "ntdll_misc.h")}
    r2 = subprocess.run(tool, capture_output=True, text=True)
    check("a second run changes nothing", r2.returncode == 0 and "already in" in r2.stdout
          and after == {f: (w / "dlls/ntdll" / f).read_text() for f in after}, r2.stdout + r2.stderr)
    t = after["time.c"]
    check("time.c: RtlQueryPerformanceCounter keeps its state in struct qpc_state, resyncs under its sequence count",
          not any(n in t for n in ("qpc_freq", "qpc_last_sync", "qpc_offset")) and "qpc_resync( off, c1 )" in t
          and "struct qpc_state qpc_state" in t)
    l = after["loader.c"]
    check("loader.c: both switches read through RtlQueryEnvironmentVariable_U, on only for \"1\"",
          l.count("val.Length && buf[0] == '1'") - (nt / "loader.c").read_text().count("val.Length && buf[0] == '1'") == 2 and 'L"MADEIRA_X64_CS_FASTPATH"' in l and 'L"MADEIRA_X64_QPC_FASTPATH"' in l)
    check("loader.c: only x64 modules without ARM64EC metadata are rebound",
          l.count("nt->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64 || arm64ec_get_module_metadata( importer )") == 2
          and "else if (!imp_metadata)\n" in l)
    clang = shutil.which("clang")
    if clang:
        inc = Path(tmp) / "inc"
        inc.mkdir()
        (inc / "config.h").write_text("")
        for f in ("loader.c", "time.c"):
            r = subprocess.run([clang, "--target=arm64ec-pc-windows-msvc", "-fsyntax-only", "-nostdinc", "-I" + str(inc),
                                "-I" + str(w / "include"), "-I" + str(w / "include/msvcrt"), "-I" + str(w / "dlls/ntdll"),
                                "-D__WINESRC__", "-D_NTSYSTEM_", "-D_UCRT", "-DWINE_NO_LONG_TYPES", "-fno-builtin",
                                "-Wno-everything", str(w / "dlls/ntdll" / f)], capture_output=True, text=True)
            if "unknown target" in r.stderr or "unsupported" in r.stderr:
                print("NOTE: this clang has no arm64ec target; syntax not checked")
                break
            check("%s compiles (-fsyntax-only, arm64ec) after the patch" % f, r.returncode == 0,
                  "\n".join(x for x in r.stderr.splitlines() if "error" in x)[:1500])
    else:
        print("NOTE: no clang; syntax not checked")

sh = (root / "tools/build-wine-extra-dlls.sh").read_text()
check("the build script builds ntdll-x64fast.dll after the stock check and restores time.c",
      'patch-wine-ntdll-x64fast.py" "$R/wine"' in sh and 'ntp_ship "$SHIP/ntdll-x64fast.dll.tmp"' in sh
      and sh.index("--same-as") < sh.index("patch-wine-ntdll-x64fast.py")
      and sh.count("dlls/ntdll/exception.c dlls/ntdll/time.c") == 2)
ld = (root / "build/ntdll-unix/loader_ios.c").read_text()
br = (root / "app/Madeira/WineProcessBridge.m").read_text()
check("the unix loader and the app map ntdll-x64fast.dll only with a switch 1 and PROTON not 1",
      "ntdll-x64fast.dll" in ld and 'getenv( "MADEIRA_X64_CS_FASTPATH" )' in ld
      and ld.index('getenv( "MADEIRA_NTDLL_PROTON" )') < ld.index('"%s%s/ntdll-x64fast.dll"')
      and "ntdll-x64fast.dll" in br and br.index("} else if (ntProtonOn) {") < br.index("ntdll-x64fast.dll"))
print("PASS: ntdll-x64fast" if ok else "FAILED: ntdll-x64fast")
sys.exit(0 if ok else 1)
