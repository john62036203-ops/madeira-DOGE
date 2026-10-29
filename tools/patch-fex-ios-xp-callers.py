#!/usr/bin/env python3
"""madeira-doge: record the x64 caller next to each sampled x64->EC target.

The ml1131 probe in ExitFunctionEC appends every 64th x64->EC call target to the
IosXpFex ring (words 400..4495). FF15 (2026-10-30 logs) shows ~1 M/s of calls to
ntdll's RtlEnter/LeaveCriticalSection EC bodies although x64-fast has pointed the
x64 import slots at its stubs, so the callers are not known. This stores the
x64 return address ([sp] at the exit: ARM64EC keeps RSP in sp) in a parallel ring
at words 4496..8591; ntdll-unix's [xp-api-callers] report reads it.

usage: patch-fex-ios-xp-callers.py <FEX root>
"""
import pathlib, sys

root = pathlib.Path(sys.argv[1])
cpp = root / 'Source/Windows/ARM64EC/Module.cpp'
asm = root / 'Source/Windows/ARM64EC/Module.S'

c = cpp.read_text()
old = 'uint64_t IosXpFex[4496]'
if 'IosXpFex[8592]' not in c:
    if c.count(old) != 2:
        sys.exit('patch-fex-ios-xp-callers: IosXpFex declaration not found twice in Module.cpp')
    c = c.replace(old, 'uint64_t IosXpFex[8592]')
    cpp.write_text(c)

s = asm.read_text()
anchor = '  add x17, x16, #3200\n  str x9, [x17, x23, lsl #3]\n'
if 'madeira-doge xp-callers' not in s:
    if s.count(anchor) != 1:
        sys.exit('patch-fex-ios-xp-callers: ring store not found in Module.S')
    s = s.replace(anchor, anchor +
        '  // madeira-doge xp-callers: the x64 return address, same slot, ring at word 4496\n'
        '  ldr x4, [sp]\n'
        '  add x17, x16, #8, lsl #12\n'
        '  add x17, x17, #3200\n'
        '  str x4, [x17, x23, lsl #3]\n')
    asm.write_text(s)
print('patch-fex-ios-xp-callers: x64 caller ring at IosXpFex+4496 words')
