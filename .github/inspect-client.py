#!/usr/bin/env python3
"""Second pass: which IClientEngine getter returns the IClientFriendsMap object.
Finds code that stores each *Map vtable (constructor) and the stores of the
constructed object into the per-user interface record."""
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
def disasm(rva, length):
    return subprocess.run(['objdump','-d','-M','intel','--start-address=%#x'%(base+rva),'--stop-address=%#x'%(base+rva+length),str(path)],capture_output=True,text=True).stdout
text = next((va,size) for name,va,size in [(raw[opt+optional_size+i*40:opt+optional_size+i*40+8].rstrip(b'\0').decode(),)+struct.unpack_from('<II',raw,opt+optional_size+i*40+12) for i in range(sections)] if name=='.text')
def lea_refs(target_rva):
    """rvas of 'lea r64,[rip+disp]' (48/4c 8d xx disp32) whose target is target_rva"""
    out=[]
    va,size=text
    for m in re.finditer(rb'[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]', image[va:va+size]):
        p=va+m.start(); disp=struct.unpack_from('<i',image,p+3)[0]
        if p+7+disp==target_rva: out.append(p)
    return out
for cls in ['IClientUserMap','IClientFriendsMap','IClientUtilsMap','IClientGameServerMap','IClientAppsMap','IClientMatchmakingMap','IClientBillingMap']:
    try: vt=vtable(cls)
    except Exception as e: print("no vtable",cls,e); continue
    refs=lea_refs(vt)
    print("\n==== %s vtable %#x; code refs: %s"%(cls,vt,[hex(r) for r in refs]))
    for r in refs:
        print("-- around %#x"%r); print(disasm(r-96, 96+160))

print("\n\n######## PASS 3: factory functions and their callers")
va,size=text
def func_start(rva):
    p=rva
    while p>va:
        # previous function ends with ret/jmp followed by int3 padding, or 16-aligned after int3 run
        if image[p-1]==0xcc and image[p]!=0xcc: return p
        p-=1
    return None
def callers(fstart):
    out=[]
    for m in re.finditer(rb'\xe8', image[va:va+size]):
        p=va+m.start(); disp=struct.unpack_from('<i',image,p+1)[0]
        if p+5+disp==fstart: out.append(p)
    return out
for cls in ['IClientUserMap','IClientFriendsMap','IClientUtilsMap','IClientAppsMap','IClientMatchmakingMap','IClientBillingMap']:
    vt=vtable(cls); refs=lea_refs(vt)
    for r in refs:
        fs=func_start(r); cs=callers(fs) if fs else []
        print("\n==== %s ctor ref %#x, function start %s, callers %s"%(cls,r,hex(fs) if fs else None,[hex(c) for c in cs]))
        for c in cs[:6]:
            print("-- caller %#x"%c); print(disasm(c-24, 24+72))
