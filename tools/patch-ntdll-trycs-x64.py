#!/usr/bin/env python3
"""ntdll RtlTryEnterCriticalSection for x64 callers runs as x64 code.

EXVS2 (vsac29) polls TryEnterCriticalSection on a held lock 12-31 million
times a second in battle ([xp-api] x64->EC 26M/s; [xp-api-top] ntdll+0x67d10,
the ARM64EC body of RtlTryEnterCriticalSection; log 2026-10-24 23:32). Every
call from the game crosses from the emulator into ARM64EC and back, returns
"held" at once, and the polling threads keep the P-cores busy, heating the SoC
into its 1.26 GHz clamp.

The x64-visible export of RtlTryEnterCriticalSection is a fast-forward
sequence in .hexpthk (... jmp <EC body>). It is replaced by a jmp to x64 code
placed in the int3 padding after .hexpthk (VirtualSize grown to cover it):
the same try (lock cmpxchg on LockCount, owner = TEB ClientId.UniqueThread,
recursion), and, when another thread holds the lock, up to 64 pause rounds
waiting for it to come free, then one NtYieldExecution (the fork's adaptive
yield: a long streak of yields sleeps yield-sleep-us) before returning FALSE.
ARM64EC callers (RtlEnterCriticalSection etc.) keep the native body.
Source: tests/host/x64stubs/trycs.asm (nasm -f bin, org 0x180093b00).

Applies to the tracked app/Madeira/arm64ec-windows/ntdll.dll only when every
byte it expects is there (FFS, NtYieldExecution stub, padding); otherwise it
prints a warning and leaves the file alone. Idempotent.
Usage: patch-ntdll-trycs-x64.py app/Madeira/arm64ec-windows/ntdll.dll
"""
import struct
import sys

FFS_RVA = 0x92740
FFS_OLD = bytes.fromhex("488bc448895820555de9c255fdffcccc")   # jmp 0x180067d10
YIELD_RVA = 0x858c0
YIELD_STUB = bytes.fromhex("4c8bd1b846000000f604250803fe7f01")  # NtYieldExecution, syscall 0x46
CODE_RVA = 0x93b00
CODE = bytes.fromhex(
    "b8ffffffff31d2f00fb15108751a65488b04254800000048894110c7410c0100"
    "0000b801000000c365488b04254800000048394110750df0ff4108ff410cb801"
    "000000c341b840000000f390837908ff750eb8ffffffff31d2f00fb1510874ae"
    "41ffc875e54883ec28e8521dffff4883c42831c0c3"
)
HEXPTHK = b".hexpthk"
NEW_VSIZE = 0x3c00


def main():
    path = sys.argv[1]
    d = bytearray(open(path, "rb").read())
    pe = struct.unpack_from("<I", d, 0x3c)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    sec = None
    for i in range(nsec):
        o = pe + 24 + opt + i * 40
        if bytes(d[o:o + 8]).rstrip(b"\0") == HEXPTHK:
            sec = o
    if sec is None:
        print("::warning::patch-ntdll-trycs-x64: no .hexpthk section; ntdll left alone"); return
    vsize, va, rsize, rptr = struct.unpack_from("<IIII", d, sec + 8)
    if va != rptr or not (va <= FFS_RVA < va + vsize) or CODE_RVA + len(CODE) > va + rsize:
        print("::warning::patch-ntdll-trycs-x64: unexpected .hexpthk layout; ntdll left alone"); return
    jmp = b"\xe9" + struct.pack("<i", CODE_RVA - (FFS_RVA + 5))
    if bytes(d[FFS_RVA:FFS_RVA + 5]) == jmp and bytes(d[CODE_RVA:CODE_RVA + len(CODE)]) == CODE:
        print("already patched"); return
    if bytes(d[FFS_RVA:FFS_RVA + 16]) != FFS_OLD:
        print("::warning::patch-ntdll-trycs-x64: RtlTryEnterCriticalSection FFS differs (ntdll rebuilt?); left alone"); return
    if bytes(d[YIELD_RVA:YIELD_RVA + 16]) != YIELD_STUB:
        print("::warning::patch-ntdll-trycs-x64: NtYieldExecution stub not where expected; left alone"); return
    if set(d[CODE_RVA:va + NEW_VSIZE]) != {0xcc} or vsize > CODE_RVA - va:
        print("::warning::patch-ntdll-trycs-x64: no free padding after .hexpthk; left alone"); return
    # rel32 of the call to NtYieldExecution inside CODE
    call_at = CODE.index(bytes.fromhex("e8521dffff"))
    assert CODE_RVA + call_at + 5 + struct.unpack_from("<i", CODE, call_at + 1)[0] == YIELD_RVA
    d[CODE_RVA:CODE_RVA + len(CODE)] = CODE
    d[FFS_RVA:FFS_RVA + 5] = jmp
    struct.pack_into("<I", d, sec + 8, NEW_VSIZE)
    open(path, "wb").write(bytes(d))
    print("patched %s: RtlTryEnterCriticalSection x64 export -> x64 body at rva %#x (%d bytes)" % (path, CODE_RVA, len(CODE)))


main()
