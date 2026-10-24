#!/usr/bin/env python3
"""GetLastError / SetLastError / TlsGetValue for x64 callers run as x64 code.

After trycs-x64 (build 452) the busiest remaining emulator crossings in an
EXVS2 battle are these trivial calls ([xp-api-top], log 2026-10-25 01:17):
kernelbase GetLastError ~250k/s, TlsGetValue ~240k/s, ntdll
RtlSetLastWin32Error/RtlRestoreLastWin32Error ~250k/s. Each is one TEB load or
store in ARM64EC, but reaching it from the game is an x64 -> ARM64EC -> x64
round trip.

The x64-visible export of each is a 16-byte fast-forward sequence (FFS) in
.hexpthk ("mov rax,rsp; mov [rax+20h],rbx; push rbp; pop rbp; jmp <EC body>").
GetLastError / Set* are replaced in place by their x64 equivalent (9 bytes:
mov eax,gs:[68h] / mov gs:[68h],ecx; ret). TlsGetValue gets a jmp to x64 code
placed in the int3 padding after .hexpthk (VirtualSize grown to cover it);
it follows Wine's body: LastError = 0, slots 0-63 from TEB+1480h, 64..1087
from TlsExpansionSlots (TEB+1780h, 0 when absent), otherwise 0 with
ERROR_INVALID_PARAMETER. Source: tests/host/x64stubs/fastpaths.asm.

A patch is applied only when the export is an FFS of exactly that shape and
the padding is free; otherwise it is skipped with a warning. Idempotent.
Usage: patch-pe-x64-fastpaths.py <arm64ec-windows dir>
"""
import os
import struct
import sys

GET_LAST_ERROR = bytes.fromhex("658b042568000000c3")
SET_LAST_ERROR = bytes.fromhex("65890c2568000000c3")
TLS_GET_VALUE = bytes.fromhex(
    "65c70425680000000000000083f93f770c89c965488b04cd80140000c38d41c0"
    "3d00040000720f31c065c704256800000057000000c365488b1425801700004885"
    "d27405488b04c2c331c0c3")
FFS_HEAD = bytes.fromhex("488bc448895820555de9")

PATCHES = {
    "ntdll.dll": [("RtlGetLastWin32Error", "inline", GET_LAST_ERROR),
                  ("RtlSetLastWin32Error", "inline", SET_LAST_ERROR),
                  ("RtlRestoreLastWin32Error", "inline", SET_LAST_ERROR)],
    # kernelbase SetLastError forwards to ntdll RtlSetLastWin32Error; kernel32's
    # exports are jmp [IAT] stubs that land on these kernelbase FFS.
    "kernelbase.dll": [("GetLastError", "inline", GET_LAST_ERROR),
                       ("TlsGetValue", "cave", TLS_GET_VALUE)],
}
CAVE_ALIGN = 0x100


def sections(d):
    pe = struct.unpack_from("<I", d, 0x3c)[0]
    n = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    out = {}
    for i in range(n):
        o = pe + 24 + opt + i * 40
        name = bytes(d[o:o + 8]).rstrip(b"\0").decode("ascii", "replace")
        vs, va, rs, rp = struct.unpack_from("<IIII", d, o + 8)
        out[name] = (o, vs, va, rs, rp)
    return pe, out


def rva_to_off(secs, rva):
    for o, vs, va, rs, rp in secs.values():
        if va <= rva < va + max(vs, rs):
            return rp + (rva - va)
    return None


def exports(d, pe, secs):
    magic = struct.unpack_from("<H", d, pe + 24)[0]
    dd = pe + 24 + (112 if magic == 0x20b else 96)
    erva, esize = struct.unpack_from("<II", d, dd)
    eo = rva_to_off(secs, erva)
    nfun, nnames, afun, aname, aord = struct.unpack_from("<IIIII", d, eo + 20)
    fo, no, oo = rva_to_off(secs, afun), rva_to_off(secs, aname), rva_to_off(secs, aord)
    res = {}
    for i in range(nnames):
        nrva = struct.unpack_from("<I", d, no + i * 4)[0]
        nof = rva_to_off(secs, nrva)
        name = bytes(d[nof:d.index(b"\0", nof)]).decode("ascii", "replace")
        ordi = struct.unpack_from("<H", d, oo + i * 2)[0]
        frva = struct.unpack_from("<I", d, fo + ordi * 4)[0]
        if not (erva <= frva < erva + esize):   # skip forwarders
            res[name] = frva
    return res


def patch_dll(path, todo):
    d = bytearray(open(path, "rb").read())
    pe, secs = sections(d)
    if ".hexpthk" not in secs:
        print("::warning::%s: no .hexpthk; left alone" % path); return
    ho, hvs, hva, hrs, hrp = secs[".hexpthk"]
    exp = exports(d, pe, secs)
    cave_at = None
    done = []
    for name, kind, code in todo:
        rva = exp.get(name)
        if rva is None or not (hva <= rva < hva + hvs):
            print("::warning::%s: %s is not an x64 FFS export; skipped" % (os.path.basename(path), name)); continue
        off = rva_to_off(secs, rva)
        slot = bytes(d[off:off + 16])
        if kind == "inline" and slot[:len(code)] == code:
            done.append(name + " (already)"); continue
        if kind == "cave" and slot[0] == 0xe9:
            done.append(name + " (already)"); continue
        if slot[:10] != FFS_HEAD or slot[14:16] != b"\xcc\xcc":
            print("::warning::%s: %s FFS has an unexpected shape (%s); skipped" % (os.path.basename(path), name, slot.hex())); continue
        if kind == "inline":
            d[off:off + 16] = code + b"\xcc" * (16 - len(code))
        else:
            if cave_at is None:
                cave_at = (hva + hvs + CAVE_ALIGN - 1) & ~(CAVE_ALIGN - 1)
            end = cave_at + len(code)
            if end > hva + hrs or set(d[rva_to_off(secs, cave_at):rva_to_off(secs, end)]) != {0xcc}:
                print("::warning::%s: no free padding after .hexpthk for %s; skipped" % (os.path.basename(path), name)); continue
            co = rva_to_off(secs, cave_at)
            d[co:co + len(code)] = code
            d[off:off + 16] = b"\xe9" + struct.pack("<i", cave_at - (rva + 5)) + b"\xcc" * 11
            newvs = (end + 0xf) & ~0xf
            if newvs - hva > hvs:
                hvs = newvs - hva
                struct.pack_into("<I", d, ho + 8, hvs)
            cave_at = (end + 0xf) & ~0xf
        done.append(name)
    open(path, "wb").write(bytes(d))
    print("%s: x64 fast paths: %s" % (os.path.basename(path), ", ".join(done) or "none"))

# Part 2 (build 454): blobs at fixed RVAs (assembled with that org: tests/host/
# x64stubs/cs_ntdll.asm, wfso_kernelbase.asm), each FFS redirected to its entry.
# A redirect is applied only when the FFS still jumps to the expected ARM64EC
# body (same binary the blob was assembled against).
#   ntdll: uncontended RtlEnterCriticalSection / RtlLeaveCriticalSection in x64
#   (held by another thread, waiters to wake, or not owned -> the ARM64EC body);
#   kernelbase: WaitForSingleObject(h, 0) that times out calls SwitchToThread.
# EXVS2 battle, log 2026-10-25 01:55: 1.9M/s each of EnterCriticalSection,
# LeaveCriticalSection and WaitForSingleObject during a polling phase.
CS_BLOB = bytes.fromhex(
    "4889e048895820555de93e3cfdffcccc4889e048895820555de9ae41fdffcccc"
    "b8ffffffff31d2f00fb15108751765488b04254800000048894110c7410c0100"
    "000031c0c365488b0425480000004839411075acf0ff4108ff410c31c0c38b41"
    "0c83f8017f3b75a8c7410c0000000048c741100000000031c0bafffffffff00f"
    "b15108750331c0c365488b04254800000048894110c7410c01000000e96fffff"
    "ffff490cf0ff490831c0c3"
)
WFSO_BLOB = bytes.fromhex(
    "4889e048895820555de9d635feffcccc85d275ec4883ec28e8e3ffffff3d0201"
    "0000750ae8e7f6ffffb8020100004883c428c3"
)
BLOBS = {
    "ntdll.dll": (0x93c00, CS_BLOB, [("RtlEnterCriticalSection", 0x93c20, 0x6784c),
                                      ("RtlLeaveCriticalSection", 0x93c5e, 0x67dcc)]),
    "kernelbase.dll": (0x85450, WFSO_BLOB, [("WaitForSingleObject", 0x85460, 0x68a34)]),
}


def patch_blobs(path, spec):
    rva0, blob, redirects = spec
    d = bytearray(open(path, "rb").read())
    pe, secs = sections(d)
    ho, hvs, hva, hrs, hrp = secs[".hexpthk"]
    exp = exports(d, pe, secs)
    name = os.path.basename(path)
    o0 = rva_to_off(secs, rva0)
    if bytes(d[o0:o0 + len(blob)]) == blob:
        print("%s: x64 fast paths part 2 already applied" % name); return
    if not (hva <= rva0 and rva0 + len(blob) <= hva + hrs) or hva + hvs > rva0 or set(d[o0:o0 + len(blob)]) != {0xcc}:
        print("::warning::%s: blob area %#x is not free padding after .hexpthk; part 2 skipped" % (name, rva0)); return
    checks = []
    for ename, entry, ec in redirects:
        rva = exp.get(ename)
        off = rva_to_off(secs, rva) if rva is not None else None
        slot = bytes(d[off:off + 16]) if off is not None else b""
        if slot[:10] != FFS_HEAD or rva + 14 + struct.unpack_from("<i", slot, 10)[0] != ec:
            print("::warning::%s: %s FFS does not jump to %#x; part 2 skipped" % (name, ename, ec)); return
        checks.append((off, rva, entry))
    d[o0:o0 + len(blob)] = blob
    for off, rva, entry in checks:
        d[off:off + 16] = b"\xe9" + struct.pack("<i", entry - (rva + 5)) + b"\xcc" * 11
    end = (rva0 + len(blob) + 0xf) & ~0xf
    if end - hva > hvs:
        struct.pack_into("<I", d, ho + 8, end - hva)
    open(path, "wb").write(bytes(d))
    print("%s: x64 fast paths part 2: %s" % (name, ", ".join(r[0] for r in redirects)))


def main():
    base = sys.argv[1]
    for dll, todo in PATCHES.items():
        p = os.path.join(base, dll)
        if os.path.exists(p):
            patch_dll(p, todo)
            if dll in BLOBS:
                patch_blobs(p, BLOBS[dll])
        else:
            print("::warning::%s missing; skipped" % p)


main()
