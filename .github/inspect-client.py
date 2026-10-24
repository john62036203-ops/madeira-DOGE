#!/usr/bin/env python3
"""Locate IClientEngine::GetIClientFriends and IClientFriends::SetPersonaState in a
steamclient64.dll by RTTI vtables + RIP-relative IPC strings. Read-only; no execution.
usage: find-presence.py steamclient64.dll"""
import hashlib, re, struct, subprocess, sys
from pathlib import Path

path = Path(sys.argv[1])
raw = path.read_bytes()
print("sha256", hashlib.sha256(raw).hexdigest())
pe = struct.unpack_from('<I', raw, 0x3c)[0]
assert raw[pe:pe+4] == b'PE\0\0'
sections = struct.unpack_from('<H', raw, pe+6)[0]
optional_size = struct.unpack_from('<H', raw, pe+20)[0]
opt = pe+24
base = struct.unpack_from('<Q', raw, opt+24)[0]
image_size, headers = struct.unpack_from('<II', raw, opt+56)
image = bytearray(image_size); image[:headers] = raw[:headers]
secs = []
for i in range(sections):
    h = opt+optional_size+i*40
    name = raw[h:h+8].rstrip(b'\0').decode()
    va, size, offset = struct.unpack_from('<III', raw, h+12)
    image[va:va+size] = raw[offset:offset+size]
    secs.append((name, va, size, offset))

def vtable(name):
    pattern = b'.?AV'+name.encode()+b'@@\0'
    td = image.index(pattern)-16
    candidates=[]
    for ref in re.finditer(re.escape(struct.pack('<I', td)), image):
        col=ref.start()-12
        if col < 0: continue
        signature, offset, _, _, _, self_rva = struct.unpack_from('<6I', image, col)
        if signature != 1 or offset != 0 or self_rva != col: continue
        for v in re.finditer(re.escape(struct.pack('<Q', base+col)), image):
            candidates.append(v.start()+8)
    assert len(candidates) == 1, (name, candidates)
    return candidates[0]

def slot_rva(table, slot):
    return struct.unpack_from('<Q', image, table+8*slot)[0]-base

def cstr(rva, n=48):
    end = image.index(b'\0', rva)
    s = image[rva:end]
    return s[:n].decode('latin1')

def disasm(rva, length=320):
    out = subprocess.run(['objdump', '-d', '-M', 'intel', '--start-address=%#x' % (base+rva),
                          '--stop-address=%#x' % (base+rva+length), str(path)],
                         capture_output=True, text=True).stdout
    return out

def strings_referenced(rva, length=320):
    found = []
    for m in re.finditer(r'lea\s+\w+,\[rip\+0x([0-9a-f]+)\]\s*#\s*0x([0-9a-f]+)', disasm(rva, length)):
        target = int(m.group(2), 16) - base
        if 0 <= target < image_size:
            try:
                s = cstr(target)
                if s and all(32 <= ord(c) < 127 for c in s): found.append((target, s))
            except ValueError: pass
    return found

# RTTI names with Friends
names = sorted(set(m.group(0).decode() for m in re.finditer(rb'\.\?AV[A-Za-z0-9_]*Friends[A-Za-z0-9_]*@@', image)))
print("RTTI classes with Friends:", names)

eng = vtable('CSteamClient')
print("CSteamClient vtable rva %#x" % (eng - 0))
for slot in range(0, 24):
    rva = slot_rva(eng, slot)
    refs = strings_referenced(rva, 200)
    print("  engine slot %2d rva %#x" % (slot, rva), [s for _, s in refs][:4])

for cls in ['IClientFriendsMap', 'IClientFriends']:
    try:
        fr = vtable(cls)
    except (ValueError, AssertionError) as e:
        print("no single vtable for", cls, e); continue
    print(cls, "vtable rva %#x" % fr)
    for slot in range(0, 40):
        rva = slot_rva(fr, slot)
        refs = strings_referenced(rva, 240)
        tag = [s for _, s in refs if 'Persona' in s or 'Status' in s]
        print("  friends slot %2d rva %#x" % (slot, rva), ([s for _, s in refs][:3]), '<==' if tag else '')

# Full listings for offline review (no DLL leaves the runner).
print("\n==== STRINGS ====")
for key in [b'SetPersonaState', b'GetIClientFriends', b'GetPersonaState', b'ClientFriends']:
    for m in re.finditer(re.escape(key), image):
        print("%s at rva %#x: %r" % (key.decode(), m.start(), bytes(image[max(0,m.start()-24):m.start()+40])))
print("\n==== ENGINE WRAPPERS ====")
for slot in range(0, 24):
    rva = slot_rva(eng, slot)
    print("\n-- engine slot %d rva %#x" % (slot, rva)); print(disasm(rva, 160))
for cls in ['IClientFriendsMap', 'IClientFriends']:
    try: fr = vtable(cls)
    except Exception: continue
    print("\n==== %s WRAPPERS ====" % cls)
    for slot in range(0, 40):
        rva = slot_rva(fr, slot)
        print("\n-- friends slot %d rva %#x" % (slot, rva)); print(disasm(rva, 260))
