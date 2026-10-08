#!/usr/bin/env python3
"""Let DXMT's own queue (D3D11/D3D10/D3D9) say which encoder a GPU fault hit.

patch-dxmt-gpu-fault-info.py gave winemetal's madeira_ctl ops 8 and 9 (a
command buffer created with MTLCommandBufferErrorOptionEncoderExecutionStatus,
and the faulted/affected encoders of a failed one), but only madeira_d3d12
used them. DXMT's CommandQueue still made its command buffers with plain
commandBuffer(), so a fault logged one line, "Device error at frame N", with
no encoder and no error code beyond the description. Devil May Cry 5 on build
174 (log 2026-10-08 08:13) lost frames 2321-2324 as
kIOGPUCommandBufferCallbackErrorInnocentVictim with nothing to say whether
the work that caused the GPU recovery was DXMT's at all.

This patch
  * creates each chunk's command buffer through op 8 (falls back to
    commandBuffer() when op 8 is not there: remote mode, the wow64 entry, a
    build without patch-dxmt-gpu-fault-info.py);
  * on a failed command buffer logs op 9's report,
    "GPU fault encoders at frame N: code C (...): [FAULTED] R3 1920x1080; ...";
    no [FAULTED] entry with a non-victim code means the culprit was outside
    this queue;
  * from the first fault on, labels the chunk's render, compute and blit
    encoders "R<i> <w>x<h>", "C<i>" and "B<i>" (i = position in the command
    buffer), so the next fault names the pass.

madeira.cfg gpu-fault-info = 0 turns all of it off (the same key
madeira_d3d12 reads). Idempotent; fails by name if an anchor moves (the dxmt
pin changed). Run from the repository root, after
patch-dxmt-gpu-fault-info.py.
"""
import pathlib
import sys

ROOT = pathlib.Path("research/dxmt/src")
MARKER = "madeira-bcd: D3D11 fault attribution"


def edit(rel, pairs):
    path = ROOT / rel
    s = path.read_text()
    if MARKER in s:
        print(f"{rel}: already patched")
        return
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f"patch-dxmt-d3d11-fault-info: anchor not found once in {rel}:\n{old}")
        s = s.replace(old, new)
    if MARKER not in s:
        sys.exit(f"patch-dxmt-d3d11-fault-info: marker missing after editing {rel}")
    path.write_text(s)
    print(f"{rel}: patched")


# --- Command queue: op 8 command buffers, op 9 report -------------------------
edit("dxmt/dxmt_command_queue.cpp", [
    ("#include <atomic>\n#include <chrono>\n",
     "#include <atomic>\n#include <chrono>\n#include <cstdio>\n#include <cstdlib>\n#include <cstring>\n"),
    ("namespace dxmt {\n\n",
     "namespace dxmt {\n\n"
     "/* madeira-bcd: D3D11 fault attribution (tools/patch-dxmt-d3d11-fault-info.py).\n"
     " * Set at the first failed command buffer; dxmt_context.cpp labels encoders\n"
     " * while it is set. */\n"
     "std::atomic<bool> g_mad_fault_labels{false};\n"
     "\n"
     "static bool\n"
     "MadFaultInfoOn() {\n"
     "  static const bool on = [] {\n"
     "    struct madeira_ctl_args a;\n"
     "    char v[64];\n"
     "    memset(&a, 0, sizeof a);\n"
     "    v[0] = 0;\n"
     "    a.op = 2;\n"
     "    a.ptr = (uint64_t)(uintptr_t)v;\n"
     "    a.len = sizeof v;\n"
     "    snprintf(a.name, sizeof a.name, \"gpu-fault-info\");\n"
     "    MadeiraCtl(&a);\n"
     "    return !(a.ret && v[0]) || strtol(v, nullptr, 0) != 0;\n"
     "  }();\n"
     "  return on;\n"
     "}\n"
     "\n"
     "/* madeira_ctl op 8: a command buffer whose error lists its encoders. */\n"
     "static WMT::CommandBuffer\n"
     "MadNewCommandBuffer(WMT::CommandQueue queue) {\n"
     "  if (MadFaultInfoOn()) {\n"
     "    struct madeira_ctl_args a;\n"
     "    memset(&a, 0, sizeof a);\n"
     "    a.op = 8;\n"
     "    a.ptr = (uint64_t)queue.handle;\n"
     "    MadeiraCtl(&a);\n"
     "    if (a.ret == 1 && a.len)\n"
     "      return WMT::CommandBuffer{(obj_handle_t)a.len};\n"
     "  }\n"
     "  return queue.commandBuffer();\n"
     "}\n"
     "\n"
     "/* madeira_ctl op 9: the error code and the faulted/affected encoders. */\n"
     "static void\n"
     "MadReportFault(WMT::CommandBuffer cmdbuf, uint64_t frame) {\n"
     "  static std::atomic<unsigned> said{0};\n"
     "  struct { uint64_t cb, buf, size; } t;\n"
     "  struct madeira_ctl_args a;\n"
     "  char out[2048];\n"
     "  if (!MadFaultInfoOn())\n"
     "    return;\n"
     "  if (!g_mad_fault_labels.exchange(true))\n"
     "    ERR(\"GPU fault: labelling every render/compute/blit encoder from now on\");\n"
     "  if (said.fetch_add(1) >= 40)\n"
     "    return;\n"
     "  out[0] = 0;\n"
     "  t.cb = (uint64_t)cmdbuf.handle;\n"
     "  t.buf = (uint64_t)(uintptr_t)out;\n"
     "  t.size = sizeof out;\n"
     "  memset(&a, 0, sizeof a);\n"
     "  a.op = 9;\n"
     "  a.ptr = (uint64_t)(uintptr_t)&t;\n"
     "  MadeiraCtl(&a);\n"
     "  if (a.ret == 1 && out[0])\n"
     "    ERR(\"GPU fault encoders at frame \", frame, \": \", out);\n"
     "}\n\n"),
    ("  auto cmdbuf = commandQueue.commandBuffer();\n",
     "  auto cmdbuf = MadNewCommandBuffer(commandQueue);\n"),
    ("      MarkDeviceError();\n",
     "      MadReportFault(chunk.attached_cmdbuf, chunk.frame_);\n"
     "      MarkDeviceError();\n"),
])


# --- Encoder labels after the first fault -------------------------------------
LABEL = (
    "      if (g_mad_fault_labels.load(std::memory_order_relaxed)) {\n"
    "        char label[48];\n"
    "        {fmt}\n"
    "        encoder.setLabel(WMT::String::string(label, WMTUTF8StringEncoding));\n"
    "      }\n"
)

edit("dxmt/dxmt_context.cpp", [
    ("#include \"dxmt_mem_census.hpp\"\n",
     "#include \"dxmt_mem_census.hpp\"\n#include <atomic>\n#include <cstdio>\n"),
    ("ArgumentEncodingContext::flushCommands(WMT::CommandBuffer cmdbuf, uint64_t seqId, uint64_t event_seq_id) {\n",
     "ArgumentEncodingContext::flushCommands(WMT::CommandBuffer cmdbuf, uint64_t seqId, uint64_t event_seq_id) {\n"
     "  /* madeira-bcd: D3D11 fault attribution -- set in dxmt_command_queue.cpp */\n"
     "  extern std::atomic<bool> g_mad_fault_labels;\n"),
    ("      auto encoder = cmdbuf.renderCommandEncoder(render_pass_info);\n",
     "      auto encoder = cmdbuf.renderCommandEncoder(render_pass_info);\n"
     + LABEL.replace("{fmt}",
                     "snprintf(label, sizeof label, \"R%u %ux%u\", encoder_count - encoder_index,\n"
                     "                 render_pass_info.render_target_width, render_pass_info.render_target_height);")),
    ("      auto encoder = cmdbuf.computeCommandEncoder(false);\n",
     "      auto encoder = cmdbuf.computeCommandEncoder(false);\n"
     + LABEL.replace("{fmt}", "snprintf(label, sizeof label, \"C%u\", encoder_count - encoder_index);")),
    ("      auto encoder = cmdbuf.blitCommandEncoder();\n      encoder.encodeCommands(&data->cmd_head);\n",
     "      auto encoder = cmdbuf.blitCommandEncoder();\n"
     + LABEL.replace("{fmt}", "snprintf(label, sizeof label, \"B%u\", encoder_count - encoder_index);")
     + "      encoder.encodeCommands(&data->cmd_head);\n"),
])
