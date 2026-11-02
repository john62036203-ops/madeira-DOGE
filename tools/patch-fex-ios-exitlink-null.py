#!/usr/bin/env python3
"""madeira-doge: the ExitFunctionLinker stub survives a zeroed Pointers.ExitFunctionLink.

The dispatcher's ExitFunctionLinker stub (Dispatcher.cpp) calls
Arm64JITCore::ExitFunctionLink through the per-thread frame slot
Pointers.ExitFunctionLink (STATE+0x638): `ldr x2, [x28, #0x638]; blr x2`. Age of
Empires IV (Aegis-protected) dies 2-4 minutes into loading with pc=0 and
lr=<stub+0x4>, x28 = the thread's own CpuStateFrame, on different threads and
after the frame's State.rip was read fine by the fault handler -- so the slot
was zeroed after Arm64JITCore's constructor filled it (2026-11-02 12:49, 13:47,
23:03, 23:08 logs; the host-heap zero-fill census says 0 pages). Who writes the
zero is not known yet.

This patch (FEX_IOS_HOST only):
  Dispatcher.cpp  after the slot load the stub does `cbnz x2, ok; ldr x2, =IosExitFunctionLinkNull`
                  so a zero slot diverts to the C++ helper instead of branching to 0.
  JITClass.h      Arm64JITCore::ExitFunctionLink made public for the helper.
  JIT.cpp         IosExitFunctionLinkNull(Frame, Record): logs [exitlink-null] with the
                  frame, thread, record, guest RIP and the first 24 words of Pointers
                  (to say whether one slot or the whole table was wiped), refills
                  Pointers.ExitFunctionLink and, when Frame->Thread is intact, continues
                  through the real ExitFunctionLink; a wiped Thread pointer is reported and
                  the process is ended with an honest fault at 0xdeaf.

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-exitlink-null.py FEX   (the submodule root)
Idempotent; fails by name if an anchor moved.
"""
import sys

root = sys.argv[1] if len(sys.argv) > 1 else "FEX"
MARK = "madeira-doge: [exitlink-null]"


def edit(path, edits):
    s = open(path).read()
    if MARK in s:
        print("patch-fex-ios-exitlink-null: already applied to " + path)
        return
    for old, new in edits:
        if s.count(old) != 1:
            sys.exit("patch-fex-ios-exitlink-null: anchor found %d times in %s: %r" % (s.count(old), path, old[:60]))
        s = s.replace(old, new)
    open(path, "w").write(s)


disp = root + "/FEXCore/Source/Interface/Core/Dispatcher/Dispatcher.cpp"
edit(disp, [
    ("#include <CodeEmitter/Emitter.h>\n",
     "#include <CodeEmitter/Emitter.h>\n"
     "#ifdef FEX_IOS_HOST\n"
     "/* " + MARK + ": JIT.cpp */\n"
     "extern \"C\" uint64_t IosExitFunctionLinkNull(FEXCore::Core::CpuStateFrame* Frame, void* Record);\n"
     "#endif\n"),
    ("  ARMEmitter::ForwardLabel l_CompileSingleStep;\n\n  // Push all the register we need to save\n",
     "  ARMEmitter::ForwardLabel l_CompileSingleStep;\n"
     "#ifdef FEX_IOS_HOST\n"
     "  ARMEmitter::ForwardLabel l_IosExitLinkNull;   /* " + MARK + " */\n"
     "#endif\n\n  // Push all the register we need to save\n"),
    ("      ldr(ARMEmitter::XReg::x2, STATE_PTR(CpuStateFrame, Pointers.ExitFunctionLink));\n"
     "      if (!CTX->Config.DisableVixlIndirectCalls) [[unlikely]] {\n"
     "        GenerateIndirectRuntimeCall<uintptr_t, void*, void*>(ARMEmitter::Reg::r2);\n",
     "      ldr(ARMEmitter::XReg::x2, STATE_PTR(CpuStateFrame, Pointers.ExitFunctionLink));\n"
     "#ifdef FEX_IOS_HOST\n"
     "      {\n"
     "        /* " + MARK + ": a zeroed slot goes to the helper, never to address 0 */\n"
     "        ARMEmitter::ForwardLabel IosExitLinkOk;\n"
     "        (void)cbnz(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r2, &IosExitLinkOk);\n"
     "        ldr(ARMEmitter::XReg::x2, &l_IosExitLinkNull);\n"
     "        (void)Bind(&IosExitLinkOk);\n"
     "      }\n"
     "#endif\n"
     "      if (!CTX->Config.DisableVixlIndirectCalls) [[unlikely]] {\n"
     "        GenerateIndirectRuntimeCall<uintptr_t, void*, void*>(ARMEmitter::Reg::r2);\n"),
    ("  FEXCore::Utils::MemberFunctionToPointerCast PMFCompileSingleStep(&FEXCore::Context::ContextImpl::CompileSingleStep);\n"
     "  dc64(PMFCompileSingleStep.GetConvertedPointer());\n",
     "  FEXCore::Utils::MemberFunctionToPointerCast PMFCompileSingleStep(&FEXCore::Context::ContextImpl::CompileSingleStep);\n"
     "  dc64(PMFCompileSingleStep.GetConvertedPointer());\n"
     "#ifdef FEX_IOS_HOST\n"
     "  (void)Bind(&l_IosExitLinkNull);   /* " + MARK + " */\n"
     "  dc64(reinterpret_cast<uint64_t>(&IosExitFunctionLinkNull));\n"
     "#endif\n"),
])

cls = root + "/FEXCore/Source/Interface/Core/JIT/JITClass.h"
edit(cls, [
    ("  static uint64_t ExitFunctionLink(FEXCore::Core::CpuStateFrame* Frame, FEXCore::Context::ExitFunctionLinkData* Record);\n",
     "public:\n"
     "  /* " + MARK + ": called by IosExitFunctionLinkNull (JIT.cpp) */\n"
     "  static uint64_t ExitFunctionLink(FEXCore::Core::CpuStateFrame* Frame, FEXCore::Context::ExitFunctionLinkData* Record);\n"
     "private:\n"),
])

jit = root + "/FEXCore/Source/Interface/Core/JIT/JIT.cpp"
edit(jit, [
    ("uint64_t Arm64JITCore::ExitFunctionLink(FEXCore::Core::CpuStateFrame* Frame, FEXCore::Context::ExitFunctionLinkData* Record) {\n",
     "#ifdef FEX_IOS_HOST\n"
     "/* " + MARK + ": the dispatcher's ExitFunctionLinker found Pointers.ExitFunctionLink == 0\n"
     " * (see tools/patch-fex-ios-exitlink-null.py). Say what the table looks like, refill the slot\n"
     " * and carry on through the real linker when the frame still names its thread. */\n"
     "extern \"C\" uint64_t IosExitFunctionLinkNull(FEXCore::Core::CpuStateFrame* Frame, void* RecordV) {\n"
     "  static std::atomic<int> N {0};\n"
     "  auto Record = static_cast<FEXCore::Context::ExitFunctionLinkData*>(RecordV);\n"
     "  const int n = N.fetch_add(1, std::memory_order_relaxed);\n"
     "  if (n < 16) {\n"
     "    const uint64_t* P = reinterpret_cast<const uint64_t*>(&Frame->Pointers);\n"
     "    uint64_t Teb = 0;\n"
     "#if defined(ARCHITECTURE_arm64ec)\n"
     "    __asm volatile(\"mov %0, x18\" : \"=r\"(Teb));\n"
     "#endif\n"
     "    LogMan::Msg::EFmt(\"[exitlink-null] #{} frame={:#x} thread={:#x} teb={:#x} record={:#x} guest_rip={:#x} state.rip={:#x} \"\n"
     "                      \"ret_stack={:#x} insyscall={:#x} sigref={} rev=exitlink-null\",\n"
     "                      n, reinterpret_cast<uint64_t>(Frame), reinterpret_cast<uint64_t>(Frame->Thread), Teb,\n"
     "                      reinterpret_cast<uint64_t>(Record), Record ? Record->GuestRIP : 0, Frame->State.rip,\n"
     "                      Frame->ReturningStackLocation, Frame->InSyscallInfo, Frame->SignalHandlerRefCounter);\n"
     "    for (int i = 0; i < 24; i += 4) {\n"
     "      LogMan::Msg::EFmt(\"[exitlink-null]   Pointers+{:#x}: {:#x} {:#x} {:#x} {:#x}\", i * 8, P[i], P[i + 1], P[i + 2], P[i + 3]);\n"
     "    }\n"
     "  }\n"
     "  Frame->Pointers.ExitFunctionLink = reinterpret_cast<uintptr_t>(&Arm64JITCore::ExitFunctionLink);\n"
     "  if (!Frame->Thread || !Record) {\n"
     "    LogMan::Msg::EFmt(\"[exitlink-null] frame has no thread/record -- cannot continue; honest fault at 0xdeaf\");\n"
     "    *reinterpret_cast<volatile uint64_t*>(0xdeafULL) = reinterpret_cast<uint64_t>(Frame);\n"
     "  }\n"
     "  return Arm64JITCore::ExitFunctionLink(Frame, Record);\n"
     "}\n"
     "#endif\n\n"
     "uint64_t Arm64JITCore::ExitFunctionLink(FEXCore::Core::CpuStateFrame* Frame, FEXCore::Context::ExitFunctionLinkData* Record) {\n"),
])
print("patch-fex-ios-exitlink-null: ExitFunctionLinker diverts a zero Pointers.ExitFunctionLink to IosExitFunctionLinkNull ([exitlink-null])")
