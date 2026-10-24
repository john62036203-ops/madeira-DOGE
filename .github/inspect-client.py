#!/usr/bin/env python3
"""Pass 10: strings the friends-UI gate checks."""
import re, struct, subprocess, sys
from pathlib import Path
path = Path(sys.argv[1]); raw = path.read_bytes()
pe = struct.unpack_from('<I', raw, 0x3c)[0]; opt = pe+24
sections = struct.unpack_from('<H', raw, pe+6)[0]; optional_size = struct.unpack_from('<H', raw, pe+20)[0]
base = struct.unpack_from('<Q', raw, opt+24)[0]; image_size, headers = struct.unpack_from('<II', raw, opt+56)
image = bytearray(image_size); image[:headers] = raw[:headers]
for i in range(sections):
    h = opt+optional_size+i*40; va, size, offset = struct.unpack_from('<III', raw, h+12); image[va:va+size] = raw[offset:offset+size]
def cs(t):
    e=image.find(b'\0',t,t+200); return image[t:e].decode('latin1') if e>t else ''
for rva in (0x974d8c0, 0x974d8b8, 0x974d8c8, 0x9755788, 0x974d8d0):
    q=struct.unpack_from('<Q',image,rva)[0]
    print(hex(rva), hex(q), repr(cs(q-base)) if base<=q<base+image_size else '(runtime)')
for rva in (0x1285b40, 0x1285b70, 0x1285bc8, 0x12ed1a0, 0x12efa08, 0x1145f20, 0x1285b20, 0x1285b30):
    print(hex(rva), repr(cs(rva)))
# who writes 0x974d8c0 (lea/mov [rip+..],reg) — show code
def dis(a, n):
    return subprocess.run(['objdump','-d','-M','intel','--no-show-raw-insn','--start-address=%#x'%(base+a),'--stop-address=%#x'%(base+a+n),str(path)],capture_output=True,text=True).stdout
out=subprocess.run(['objdump','-d','-M','intel','--no-show-raw-insn',str(path)],capture_output=True,text=True).stdout.splitlines()
for i,l in enumerate(out):
    if re.search(r'mov\s+QWORD PTR \[rip\+0x[0-9a-f]+\],\w+\s+# 0x13974d8(c0|b8)', l):
        print("\n-- writer"); print("\n".join(out[max(0,i-6):i+2]))
