#!/usr/bin/env python3
"""Pass 9: what condition forces the persona offline (CUserFriends +0x15)."""
import re, struct, subprocess, sys
from pathlib import Path
path = Path(sys.argv[1]); raw = path.read_bytes()
pe = struct.unpack_from('<I', raw, 0x3c)[0]; opt = pe+24
sections = struct.unpack_from('<H', raw, pe+6)[0]; optional_size = struct.unpack_from('<H', raw, pe+20)[0]
base = struct.unpack_from('<Q', raw, opt+24)[0]; image_size, headers = struct.unpack_from('<II', raw, opt+56)
image = bytearray(image_size); image[:headers] = raw[:headers]
text=None
for i in range(sections):
    h = opt+optional_size+i*40; va, size, offset = struct.unpack_from('<III', raw, h+12); image[va:va+size] = raw[offset:offset+size]
    if raw[h:h+8].rstrip(b'\0')==b'.text': text=(va,size)
def dis(a, n):
    return subprocess.run(['objdump','-d','-M','intel','--no-show-raw-insn','--start-address=%#x'%(base+a),'--stop-address=%#x'%(base+a+n),str(path)],capture_output=True,text=True).stdout
def calls_to(t):
    va,size=text; out=[]
    for m in re.finditer(rb'[\xe8\xe9]', image[va:va+size]):
        p=va+m.start()
        if p+5+struct.unpack_from('<i',image,p+1)[0]==t: out.append(p)
    return out
def cstr_at(t):
    e=image.find(b'\0',t,t+120)
    s=image[t:e] if e>t else b''
    return s.decode('latin1') if s and all(32<=b<127 for b in s) else None
def strings_in(a,n):
    out=[]
    for m in re.finditer(r'lea\s+\w+,\[rip\+0x[0-9a-f]+\]\s*#\s*0x([0-9a-f]+)', dis(a,n)):
        t=int(m.group(1),16)-base
        if 0<=t<image_size:
            s=cstr_at(t)
            if s: out.append(s)
    return out
for name,t in [('cond4 query 0x997730',0x997730),('gate 0x68f550',0x68f550)]:
    print("\n==== %s"%name); print(dis(t,260)); print("strings:", strings_in(t,400))
print("\n==== callers of forced-offline 0x9dd260:", [hex(c) for c in calls_to(0x9dd260)])
for c in calls_to(0x9dd260)[:8]:
    print("\n-- caller %#x strings nearby %s"%(c, strings_in(c-600, 700)[:12])); print(dis(c-120, 160))
# vtable references (function pointers) to 0x9dd260
refs=[m.start() for m in re.finditer(re.escape(struct.pack('<Q', base+0x9dd260)), image)]
print("\n==== data refs to 0x9dd260:", [hex(r) for r in refs])
# what else calls cond query with edx=4 and nearby strings: find "mov edx,0x4" right before call 0x997730
va,size=text
c4=[c for c in calls_to(0x997730)]
print("\n==== calls to cond query: %d"%len(c4))
for c in c4[:40]:
    d=dis(c-24,29)
    m=re.findall(r'mov\s+edx,0x([0-9a-f]+)', d)
    print(hex(c), "edx", m[-1] if m else '?', strings_in(c-300, 360)[:4])
