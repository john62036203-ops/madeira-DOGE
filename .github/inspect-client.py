#!/usr/bin/env python3
"""Pass 12: CUserFriends vtable, and which vtables hold SetPersonaState impl 0x9e61d0 / forced-offline 0x9dd260."""
import re, struct, subprocess, sys
from pathlib import Path
path = Path(sys.argv[1]); raw = path.read_bytes()
pe = struct.unpack_from('<I', raw, 0x3c)[0]; opt = pe+24
sections = struct.unpack_from('<H', raw, pe+6)[0]; optional_size = struct.unpack_from('<H', raw, pe+20)[0]
base = struct.unpack_from('<Q', raw, opt+24)[0]; image_size, headers = struct.unpack_from('<II', raw, opt+56)
image = bytearray(image_size); image[:headers] = raw[:headers]
for i in range(sections):
    h = opt+optional_size+i*40; va, size, offset = struct.unpack_from('<III', raw, h+12); image[va:va+size] = raw[offset:offset+size]
print("base", hex(base))
def vtables(name):
    td = image.index(b'.?AV'+name.encode()+b'@@\0')-16; c=[]
    for ref in re.finditer(re.escape(struct.pack('<I', td)), image):
        col=ref.start()-12
        if col<0: continue
        sig, off, _, _, _, self_rva = struct.unpack_from('<6I', image, col)
        if sig!=1 or self_rva!=col: continue
        for v in re.finditer(re.escape(struct.pack('<Q', base+col)), image): c.append((v.start()+8, off))
    return c
for name in ['CUserFriends','CClientFriends','CUser']:
    try: vs=vtables(name)
    except ValueError: print(name,"no RTTI"); continue
    print(name, [(hex(v),off) for v,off in vs])
    for v,off in vs:
        for slot in range(400):
            q=struct.unpack_from('<Q',image,v+8*slot)[0]
            if not (base<=q<base+image_size): print("  vt %#x ends at %d"%(v,slot)); break
            if q-base in (0x9e61d0,0x9dd260,0x9e6200): print("  vt %#x slot %d -> %#x"%(v,slot,q-base))
# any 8-byte pointer anywhere to the two functions
for t in (0x9e61d0,0x9dd260):
    print("ptr refs to %#x:"%t, [hex(m.start()) for m in re.finditer(re.escape(struct.pack('<Q',base+t)), image)][:10])
def dis(a, n):
    return subprocess.run(['objdump','-d','-M','intel','--no-show-raw-insn','--start-address=%#x'%(base+a),'--stop-address=%#x'%(base+a+n),str(path)],capture_output=True,text=True).stdout
print("\n==== 0x9e61d0"); print(dis(0x9e61d0, 0x40))
# who calls 0x9dd260 through 'jmp' thunks or call [reg]: list e8/e9 to it again incl. 5-byte jmps from thunks
va,size=[(struct.unpack_from('<I',raw,opt+optional_size+i*40+12)[0],struct.unpack_from('<I',raw,opt+optional_size+i*40+8)[0]) for i in range(sections) if raw[opt+optional_size+i*40:opt+optional_size+i*40+8].rstrip(b'\0')==b'.text'][0]
for t in (0x9dd260, 0x9dd240, 0x9dd250):
    hits=[]
    for m in re.finditer(rb'[\xe8\xe9]', image[va:va+size]):
        p=va+m.start()
        if p+5+struct.unpack_from('<i',image,p+1)[0]==t: hits.append(hex(p))
    print("direct calls/jmps to %#x:"%t, hits[:10])
print("\n==== before 0x9dd260"); print(dis(0x9dd200, 0x60))
