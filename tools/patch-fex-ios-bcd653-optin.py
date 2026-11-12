#!/usr/bin/env python3
"""FEX ARM64EC: BCD 0.1.653's three exit/thread crash fixes, opt-in (MADEIRA_FEX_BCD_FIXES=1).

Runs BCD's patch scripts (tools/patch-fex-ios-notify-nocpuarea.py,
patch-fex-ios-process-term.py, patch-fex-ios-threadterm-clear-area.py, copied
unchanged from BCD 0.1.653) and then makes each of them depend on one switch,
read once in ProcessInit after the CRT is up:

  * no-CPU-area guards: a native ARM64 thread of an ARM64EC session (services.exe,
    cmd.exe, conhost.exe ...) has no CPU area; FEX's memory hooks read NULL+0x38
    for it and the program died at its first memory call.
  * process-term: once NtTerminateProcess(0) starts the process's end, the memory
    hooks stop using the emulator's tracker (BCD: about 3 % of exits faulted at
    0xf0 in InvalidateAlignedInterval).
  * ThreadTerm clears the CPU area's thread-state slots once the state is
    destroyed (an exception afterwards read the freed state).

Unset or 0: every hook behaves exactly as before (HasCPUArea() answers true,
ProcessTerm stays empty in effect, ThreadTerm leaves the slots). A [fex-bcd-fixes]
line says when it is on.

madeira-doge fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-bcd653-optin.py FEX
Idempotent; fails by name when an anchor moved (the build then goes on without it).
"""
import subprocess, sys
from pathlib import Path

MARK = "madeira-doge bcd653-optin"


def one(s, old, new, what):
    if s.count(old) != 1:
        sys.exit("patch-fex-ios-bcd653-optin: %s not found once (%d times; FEX or BCD's patch changed)" % (what, s.count(old)))
    return s.replace(old, new)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[-1])
    fex = Path(sys.argv[1])
    path = fex / "Source/Windows/ARM64EC/Module.cpp"
    if MARK in path.read_text():
        print("ARM64EC/Module.cpp: BCD 0.1.653 fixes already in, opt-in; nothing to do")
        return
    saved = path.read_text()
    try:
        apply(fex, path)
    except SystemExit:
        path.write_text(saved)   # all or nothing: never BCD's fixes without the switch
        raise


def apply(fex, path):
    here = Path(__file__).resolve().parent
    for p in ("notify-nocpuarea", "process-term", "threadterm-clear-area"):
        r = subprocess.run([sys.executable, str(here / ("patch-fex-ios-%s.py" % p)), str(fex)])
        if r.returncode:
            sys.exit("patch-fex-ios-bcd653-optin: patch-fex-ios-%s.py did not apply" % p)
    s = path.read_text()
    # The switch, at file scope before BCD's HasCPUArea().
    s = one(s, "inline bool HasCPUArea() {\n",
            "// %s: MADEIRA_FEX_BCD_FIXES=1 (read in ProcessInit) turns on the three BCD 0.1.653 fixes below; false = as before.\n"
            "static bool MadeiraFexBcdFixes = false;\n"
            "inline bool HasCPUArea() {\n"
            "  if (!MadeiraFexBcdFixes) {   // %s: off -- every thread counts as having an area, as before\n"
            "    return true;\n"
            "  }\n" % (MARK, MARK), "HasCPUArea()")
    s = one(s, "  if (!After) {\n    FexProcessTerminating.store(true, std::memory_order_relaxed);\n",
            "  if (!After && MadeiraFexBcdFixes) {   // %s\n    FexProcessTerminating.store(true, std::memory_order_relaxed);\n" % MARK,
            "ProcessTerm's start")
    s = one(s, "  CPUArea.ThreadState() = nullptr;\n  CPUArea.StateFrame() = nullptr;\n",
            "  if (MadeiraFexBcdFixes) {   // %s\n    CPUArea.ThreadState() = nullptr;\n    CPUArea.StateFrame() = nullptr;\n  }\n" % MARK,
            "ThreadTerm's slot clearing")
    # Read the switch once the CRT is up (getenv before ucrtbase's DllMain recursed, ml797).
    s = one(s, "  FEX::Windows::Logging::Init();\n\n#ifdef FEX_IOS_HOST\n  /* Recorder emitted only for this executable, before CTX/JIT creation. */\n",
            "  FEX::Windows::Logging::Init();\n"
            "  {   // %s\n"
            "    const char* BcdEnv = getenv(\"MADEIRA_FEX_BCD_FIXES\");\n"
            "    MadeiraFexBcdFixes = BcdEnv && BcdEnv[0] == '1';\n"
            "    if (MadeiraFexBcdFixes) {\n"
            "      LogMan::Msg::IFmt(\"[fex-bcd-fixes] MADEIRA_FEX_BCD_FIXES=1: no-CPU-area guards, process-term and ThreadTerm slot clearing (BCD 0.1.653) are on\");\n"
            "    }\n"
            "  }\n"
            "\n#ifdef FEX_IOS_HOST\n  /* Recorder emitted only for this executable, before CTX/JIT creation. */\n" % MARK,
            "ProcessInit's Logging::Init")
    path.write_text(s)
    print("ARM64EC/Module.cpp: BCD 0.1.653 no-CPU-area, process-term and ThreadTerm fixes, opt-in with MADEIRA_FEX_BCD_FIXES=1")


if __name__ == "__main__":
    main()
