#!/usr/bin/env python3
import re, subprocess, sys
out=subprocess.run(['objdump','-d','-M','intel','--no-show-raw-insn',sys.argv[1]],capture_output=True,text=True).stdout.splitlines()
for key in ('0x13974d8c0','0x13974d8b8','0x13974d8d0'):
    idx=[i for i,l in enumerate(out) if key in l]
    print("\n==== %s: %d refs"%(key,len(idx)))
    for i in idx[:12]:
        print("--"); print("\n".join(out[max(0,i-5):i+2]))
