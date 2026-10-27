import struct
def s(t):
    b=t.encode()+b'\0'; b+=b'\0'*((4-len(b)%4)%4)
    return list(struct.unpack('<%dI'%(len(b)//4),b))
def f(x): return struct.unpack('<I',struct.pack('<f',x))[0]
class M:
    def __init__(s): s.ins=[]; s.n=1
    def id(s): s.n+=1; return s.n-1
    def op(s,code,*ops): s.ins.append((code,list(ops)))
    def words(s):
        out=[0x07230203,0x00010000,0,s.n,0]
        for c,o in s.ins: out.append(((1+len(o))<<16)|c); out+=o
        return out
# opcodes
Cap,MemModel,Entry,ExecMode,TVoid,TFloat,TVec,TPtr,TFn,Const,Var,Load,Store,Deco,Func,FuncEnd,Label,Ret,CConstruct,CExtract=17,14,15,16,19,22,23,32,33,43,59,61,62,71,54,56,248,253,80,81
Input,Output=1,3
def vs():
    m=M(); void,fnt,fl,v2,v3,v4=[m.id() for _ in range(6)]
    pi2,pi3,po3,po4=[m.id() for _ in range(4)]
    inPos,inCol,vCol,glPos,f0,f1,main,lab=[m.id() for _ in range(8)]
    m.op(Cap,1); m.op(MemModel,0,1)
    m.op(Entry,0,main,*s("main"),glPos,inPos,inCol,vCol)
    m.op(Deco,glPos,11,0); m.op(Deco,inPos,30,0); m.op(Deco,inCol,30,1); m.op(Deco,vCol,30,0)
    m.op(TVoid,void); m.op(TFn,fnt,void); m.op(TFloat,fl,32)
    m.op(TVec,v2,fl,2); m.op(TVec,v3,fl,3); m.op(TVec,v4,fl,4)
    m.op(TPtr,pi2,Input,v2); m.op(TPtr,pi3,Input,v3); m.op(TPtr,po3,Output,v3); m.op(TPtr,po4,Output,v4)
    m.op(Var,pi2,inPos,Input); m.op(Var,pi3,inCol,Input); m.op(Var,po3,vCol,Output); m.op(Var,po4,glPos,Output)
    m.op(Const,fl,f0,f(0.0)); m.op(Const,fl,f1,f(1.0))
    m.op(Func,void,main,0,fnt); m.op(Label,lab)
    p,px,py,pos,c=[m.id() for _ in range(5)]
    m.op(Load,v2,p,inPos); m.op(CExtract,fl,px,p,0); m.op(CExtract,fl,py,p,1)
    m.op(CConstruct,v4,pos,px,py,f0,f1); m.op(Store,glPos,pos)
    m.op(Load,v3,c,inCol); m.op(Store,vCol,c)
    m.op(Ret); m.op(FuncEnd); return m.words()
def fs():
    m=M(); void,fnt,fl,v3,v4,pi3,po4,vCol,outCol,f1,main,lab=[m.id() for _ in range(12)]
    m.op(Cap,1); m.op(MemModel,0,1)
    m.op(Entry,4,main,*s("main"),vCol,outCol); m.op(ExecMode,main,7)
    m.op(Deco,vCol,30,0); m.op(Deco,outCol,30,0)
    m.op(TVoid,void); m.op(TFn,fnt,void); m.op(TFloat,fl,32); m.op(TVec,v3,fl,3); m.op(TVec,v4,fl,4)
    m.op(TPtr,pi3,Input,v3); m.op(TPtr,po4,Output,v4)
    m.op(Var,pi3,vCol,Input); m.op(Var,po4,outCol,Output); m.op(Const,fl,f1,f(1.0))
    m.op(Func,void,main,0,fnt); m.op(Label,lab)
    c,r,g,b,o=[m.id() for _ in range(5)]
    m.op(Load,v3,c,vCol); m.op(CExtract,fl,r,c,0); m.op(CExtract,fl,g,c,1); m.op(CExtract,fl,b,c,2)
    m.op(CConstruct,v4,o,r,g,b,f1); m.op(Store,outCol,o); m.op(Ret); m.op(FuncEnd); return m.words()
def carr(name,w):
    lines=[f"static const uint32_t {name}[{len(w)}] = {{"]
    for i in range(0,len(w),8): lines.append("    "+", ".join("0x%08x"%x for x in w[i:i+8])+",")
    lines.append("};"); return "\n".join(lines)
# sanity: walk instructions
for name,w in (("vs",vs()),("fs",fs())):
    i=5
    while i<len(w):
        n=w[i]>>16; assert n>0; i+=n
    assert i==len(w), name
    print(name, len(w), "words ok, bound", w[3])
open("shaders.h","w").write("// Hand-assembled SPIR-V 1.0 (tools/spv-asm.py): pass-through position+colour.\n#include <stdint.h>\n"+carr("kVulkanLabVS",vs())+"\n"+carr("kVulkanLabFS",fs())+"\n")
