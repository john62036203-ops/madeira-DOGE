#!/usr/bin/env python3
"""Pass 8: who writes CUserFriends' byte at +0x15 (SetPersonaState returns early when it is set)."""
import re, struct, subprocess, sys
from pathlib import Path
path = Path(sys.argv[1]); raw = path.read_bytes()
pe = struct.unpack_from('<I', raw, 0x3c)[0]; opt = pe+24
base = struct.unpack_from('<Q', raw, opt+24)[0]
def dis(a, b):
    return subprocess.run(['objdump','-d','-M','intel','--no-show-raw-insn','--start-address=%#x'%(base+a),'--stop-address=%#x'%(base+b),str(path)],capture_output=True,text=True).stdout.splitlines()
lines = dis(0x9d0000, 0x9f0000)
print("lines", len(lines))
hits = [i for i,l in enumerate(lines) if re.search(r'BYTE PTR \[r\w+\+0x15\],', l) and 'mov' in l]
print("writes to +0x15:", len(hits))
for i in hits:
    print("\n----"); print("\n".join(lines[max(0,i-25):i+6]))
print("\n==== SetPersonaState impl full")
print("\n".join(dis(0x9e6200, 0x9e6400)))
print("\n==== init after AutoSignIntoFriends")
print("\n".join(dis(0x9dab10, 0x9dac80)))
