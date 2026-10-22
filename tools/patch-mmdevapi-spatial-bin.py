#!/usr/bin/env python3
"""Binary fallback for tools/patch-wine-spatialaudio-eos.py: patch the two
ISpatialAudioObject stubs straight into the SHIPPED mmdevapi.dll.

The source rebuild of mmdevapi does not reproduce the shipped bytes (build 359:
same section sizes and identical .pdata/.data/.reloc, but .text differs), so
the source patch cannot replace it safely. When the rebuilt (unstripped) stock
DLL has the same .pdata as the shipped one, every function sits at the same
RVA in both, and the symbol table of the rebuilt DLL names where
SAO_SetEndOfStream and SAO_IsActive start in the shipped DLL. Their bodies are
overwritten with:

  SAO_SetEndOfStream(iface, frames):  *(int *)(iface + 12) = 1; return S_OK;
  SAO_IsActive(iface, active):        if (!active) return E_POINTER;
                                      *active = !*(int *)(iface + 12); return S_OK;

Offset 12 is the padding after `LONG ref` in SpatialAudioObjectImpl (vtable 0,
ref 8, sa_stream 16), zero from calloc. Only x0, x1, x8 are used (ARM64EC-safe).

usage: patch-mmdevapi-spatial-bin.py STOCK_UNSTRIPPED.dll SHIPPED.dll OUT.dll [llvm-symbolizer]
Without a COFF symbol table (lld keeps only DWARF), every .pdata function start
is named with llvm-symbolizer from the stock DLL's DWARF instead.
"""
import struct
import subprocess
import sys

SET_EOS = [0x52800028, 0xB9000C08, 0x52800000, 0xD65F03C0]
IS_ACTIVE = [0xB40000E1, 0xB9400C08, 0x7100011F, 0x1A9F17E8, 0xB9000028,
             0x52800000, 0xD65F03C0, 0x52880060, 0x72B00000, 0xD65F03C0]


def pe(data):
    off = struct.unpack_from("<I", data, 0x3c)[0]
    nsec, = struct.unpack_from("<H", data, off + 6)
    symptr, nsym = struct.unpack_from("<II", data, off + 12)
    optsz, = struct.unpack_from("<H", data, off + 20)
    secs = []
    for i in range(nsec):
        s = off + 24 + optsz + 40 * i
        name = data[s:s + 8].rstrip(b"\0").decode("latin-1")
        vsz, va, rsz, raw = struct.unpack_from("<IIII", data, s + 8)
        secs.append((name, va, vsz, raw, rsz))
    return secs, symptr, nsym


def section(secs, name):
    for s in secs:
        if s[0] == name:
            return s
    sys.exit("patch-mmdevapi-spatial-bin: no %s section" % name)


def symbolize(path, data, begins, tool):
    off = struct.unpack_from("<I", data, 0x3c)[0]
    base, = struct.unpack_from("<Q", data, off + 24 + 24)
    addrs = "\n".join("%#x" % (base + b) for b in begins) + "\n"
    out = subprocess.run([tool, "--obj=" + path, "--functions=linkage", "--no-inlines"],
                         input=addrs, capture_output=True, text=True, check=True).stdout
    blocks = [b for b in out.strip().split("\n\n")]
    names = {}
    for b, blk in zip(begins, blocks):
        fn = blk.split("\n")[0].strip()
        names.setdefault(fn, b)
    return names


def symbols(data, secs, symptr, nsym):
    if not symptr or not nsym:
        return {}
    strtab = symptr + 18 * nsym
    out = {}
    i = 0
    while i < nsym:
        e = symptr + 18 * i
        raw = data[e:e + 8]
        if raw[:4] == b"\0\0\0\0":
            o, = struct.unpack_from("<I", raw, 4)
            end = data.index(b"\0", strtab + o)
            name = data[strtab + o:end].decode("latin-1")
        else:
            name = raw.rstrip(b"\0").decode("latin-1")
        value, secno = struct.unpack_from("<Ih", data, e + 8)
        naux = data[e + 17]
        if 0 < secno <= len(secs):
            out.setdefault(name, secs[secno - 1][1] + value)
        i += 1 + naux
    return out


def rva_to_off(secs, rva):
    for name, va, vsz, raw, rsz in secs:
        if va <= rva < va + max(vsz, rsz):
            return raw + rva - va
    sys.exit("patch-mmdevapi-spatial-bin: rva %#x is in no section" % rva)


def main():
    stock = open(sys.argv[1], "rb").read()
    ship = bytearray(open(sys.argv[2], "rb").read())
    ssecs, symptr, nsym = pe(stock)
    hsecs, _, _ = pe(ship)
    sp, hp = section(ssecs, ".pdata"), section(hsecs, ".pdata")
    if sp[1] != hp[1] or sp[2] != hp[2] or stock[sp[3]:sp[3] + sp[2]] != bytes(ship[hp[3]:hp[3] + hp[2]]):
        sys.exit("patch-mmdevapi-spatial-bin: .pdata differs, function addresses cannot be trusted")
    st, ht = section(ssecs, ".text"), section(hsecs, ".text")
    if (st[1], st[2]) != (ht[1], ht[2]):
        sys.exit("patch-mmdevapi-spatial-bin: .text placement differs")
    syms = symbols(stock, ssecs, symptr, nsym)
    begins = sorted(struct.unpack_from("<I", ship, hp[3] + 8 * k)[0] for k in range(hp[2] // 8))
    if not any(n in syms for n in ("SAO_SetEndOfStream", "SAO_IsActive")):
        if len(sys.argv) < 5:
            sys.exit("patch-mmdevapi-spatial-bin: no COFF symbols and no llvm-symbolizer given")
        syms = symbolize(sys.argv[1], stock, begins, sys.argv[4])
    for name, code in (("SAO_SetEndOfStream", SET_EOS), ("SAO_IsActive", IS_ACTIVE)):
        cands = [syms[n] for n in (name, "_" + name, "#" + name) if n in syms]
        if not cands:
            sys.exit("patch-mmdevapi-spatial-bin: symbol %s not found" % name)
        rva = cands[0]
        if rva not in begins:
            sys.exit("patch-mmdevapi-spatial-bin: %s at %#x has no .pdata entry" % (name, rva))
        nxt = [b for b in begins if b > rva]
        room = (nxt[0] if nxt else ht[1] + ht[2]) - rva
        if room < 4 * len(code):
            sys.exit("patch-mmdevapi-spatial-bin: %s has %d bytes, the patch needs %d" % (name, room, 4 * len(code)))
        off = rva_to_off(hsecs, rva)
        ship[off:off + 4 * len(code)] = struct.pack("<%dI" % len(code), *code)
        print("patch-mmdevapi-spatial-bin: %s at rva %#x (%d bytes room) patched" % (name, rva, room))
    open(sys.argv[3], "wb").write(ship)


if __name__ == "__main__":
    main()
