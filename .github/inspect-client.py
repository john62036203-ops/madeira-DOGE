#!/usr/bin/env python3
"""Pass 5: IPC method names of every slot of the client's *Map interfaces (friends, user, utils)."""
import hashlib, re, struct, subprocess, sys
from pathlib import Path
path = Path(sys.argv[1]); raw = path.read_bytes()
print("sha256", hashlib.sha256(raw).hexdigest())
pe = struct.unpack_from('<I', raw, 0x3c)[0]
sections = struct.unpack_from('<H', raw, pe+6)[0]; optional_size = struct.unpack_from('<H', raw, pe+20)[0]; opt = pe+24
base = struct.unpack_from('<Q', raw, opt+24)[0]; image_size, headers = struct.unpack_from('<II', raw, opt+56)
image = bytearray(image_size); image[:headers] = raw[:headers]
for i in range(sections):
    h = opt+optional_size+i*40; va, size, offset = struct.unpack_from('<III', raw, h+12); image[va:va+size] = raw[offset:offset+size]
def vtable(name):
    td = image.index(b'.?AV'+name.encode()+b'@@\0')-16; c=[]
    for ref in re.finditer(re.escape(struct.pack('<I', td)), image):
        col=ref.start()-12
        if col<0: continue
        sig, off, _, _, _, self_rva = struct.unpack_from('<6I', image, col)
        if sig!=1 or off!=0 or self_rva!=col: continue
        for v in re.finditer(re.escape(struct.pack('<Q', base+col)), image): c.append(v.start()+8)
    assert len(c)==1,(name,c); return c[0]
def name_of(rva, length=200):
    """First printable C string a RIP-relative LEA in the wrapper points at, other than the interface name."""
    code = image[rva:rva+length]
    for m in re.finditer(rb'[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]', code):
        p = rva+m.start(); t = p+7+struct.unpack_from('<i', image, p+3)[0]
        if not (0 <= t < image_size): continue
        e = image.find(b'\0', t, t+80)
        if e <= t: continue
        s = image[t:e]
        if all(32 <= b < 127 for b in s) and len(s) >= 4 and not s.startswith(b'IClient') and b'\\' not in s:
            return s.decode()
    return '?'
for cls, n in [('IClientFriendsMap', 260), ('IClientUserMap', 330), ('IClientUtilsMap', 160)]:
    vt = vtable(cls)
    print("\n==== %s vtable %#x" % (cls, vt))
    for slot in range(n):
        q = struct.unpack_from('<Q', image, vt+8*slot)[0]
        if not (base <= q < base+image_size): print("end at", slot); break
        print("%3d %#x %s" % (slot, q-base, name_of(q-base)))
print("\n==== strings")
for key in [rb'FriendsUI', rb'nofriendsui', rb'SignIntoFriends', rb'SetPersonaState', rb'PersonaStateDesired', rb'friends network', rb'ChangeStatus', rb'GamesPlayed']:
    for m in list(re.finditer(key, image))[:6]:
        a = max(0, m.start()-40); print(key.decode(), hex(m.start()), bytes(image[a:m.start()+60]))
