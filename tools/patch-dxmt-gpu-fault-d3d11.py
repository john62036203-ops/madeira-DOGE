#!/usr/bin/env python3
"""Name the encoder and shaders behind a GPU hang in DXMT's d3d11 (d3d11-src only).

Sekiro (log 2026-10-15 16:31): twice in three minutes the GPU stopped for ~10 s
and iOS reset it; DXMT only logged "Device error at frame N: Discarded (victim
of GPU error/recovery)", which names neither the encoder nor the shader. The
earlier 08:03 and 14:54 logs had the same resets (up to 32 s). madeira_ctl ops
8 and 9 (tools/patch-dxmt-gpu-fault-info.py) already give madeira_d3d12 that
attribution; this wires them into d3d11 as well. With MADEIRA_GPU_FAULT=1:

  * command buffers are created with encoder execution status (op 8);
  * every render/compute encoder is labelled "E<id> R|C cmds=<n> psos=<n>" and
    the pipelines it sets are remembered (the last ~10k encoders);
  * every d3d11 graphics/compute pipeline is remembered with the SHA-1 of its
    shaders (vs/ps or cs, first 16 hex digits);
  * on a device error, op 9's faulted/affected encoder list is logged as
    [gpu-fault], then each named encoder's pipelines and their shaders.

Unset, the only cost is one static flag test per encoder and per pipeline.
Geometry/tessellation pipelines are listed by handle only.

Applied by tools/build-d3d11-dll.sh to its COPIES of dxmt_command_queue.cpp,
dxmt_context.cpp and d3d11_pipeline.cpp, so only d3d11-src.dll
(env.MADEIRA_D3D11_SRC = 1) has it.
Usage: patch-dxmt-gpu-fault-d3d11.py <tree>/src
Idempotent; fails by name if an anchor moves.
"""
import pathlib
import sys

MARKER = "madeira-doge: gpu fault"
SRC = pathlib.Path(sys.argv[1])


def edit(rel, pairs):
    path = SRC / rel
    s = path.read_text()
    if MARKER in s:
        print(f"{rel}: gpu fault already patched")
        return
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f"patch-dxmt-gpu-fault-d3d11: anchor found {s.count(old)} times (want 1) in {rel}:\n{old}")
        s = s.replace(old, new)
    if MARKER not in s:
        sys.exit(f"patch-dxmt-gpu-fault-d3d11: marker missing after editing {rel}")
    path.write_text(s)
    print(f"{rel}: gpu fault patched")


edit("dxmt/dxmt_command_queue.cpp", [
    ("namespace dxmt {\n",
     r'''#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace dxmt {

/* madeira-doge: gpu fault (tools/patch-dxmt-gpu-fault-d3d11.py) */
bool
mad_gpu_fault_on() {
  static const bool on = [] {
    const bool v = env::getEnvVar("MADEIRA_GPU_FAULT") == "1";
    if (v)
      ERR("[gpu-fault] madeira-doge: encoder execution status on; encoders and pipelines recorded (MADEIRA_GPU_FAULT=1)");
    return v;
  }();
  return on;
}

namespace {
std::mutex mad_gf_mutex;
std::unordered_map<uint64_t, std::string> mad_gf_pso;           /* pipeline handle -> shaders */
std::unordered_map<uint64_t, std::vector<uint64_t>> mad_gf_enc; /* encoder id -> pipelines */

WMT::CommandBuffer
mad_gf_command_buffer(obj_handle_t queue) {
  struct madeira_ctl_args a = {};
  a.op = 8;
  a.ptr = (uint64_t)queue;
  MadeiraCtl(&a);
  if (a.ret && a.len)
    return WMT::CommandBuffer{(obj_handle_t)a.len};
  return WMT::CommandBuffer{MTLCommandQueue_commandBuffer(queue)};
}

void
mad_gf_report(obj_handle_t cmdbuf, uint64_t frame) {
  static char buf[4096];
  struct { uint64_t cb, buf, size; } t = {(uint64_t)cmdbuf, (uint64_t)(uintptr_t)buf, sizeof buf};
  struct madeira_ctl_args a = {};
  a.op = 9;
  a.ptr = (uint64_t)(uintptr_t)&t;
  buf[0] = 0;
  MadeiraCtl(&a);
  ERR("[gpu-fault] frame ", frame, ": ", a.ret ? buf : "(no encoder info: op 9 missing or remote Metal)");
  std::lock_guard<std::mutex> lock(mad_gf_mutex);
  for (const char *p = buf; (p = strstr(p, "] E")) != nullptr;) {
    char *end;
    const uint64_t id = strtoull(p + 3, &end, 10);
    p = end;
    auto enc = mad_gf_enc.find(id);
    if (enc == mad_gf_enc.end()) {
      ERR("[gpu-fault]   E", id, ": not recorded");
      continue;
    }
    ERR("[gpu-fault]   E", id, ": ", enc->second.size(), " pipeline(s)");
    for (uint64_t pso : enc->second) {
      char h[24];
      snprintf(h, sizeof h, "0x%llx", (unsigned long long)pso);
      auto d = mad_gf_pso.find(pso);
      ERR("[gpu-fault]     pso ", h, " ", d == mad_gf_pso.end() ? "(geometry/tessellation or internal)" : d->second);
    }
  }
}
} // namespace

void
mad_pso_note(obj_handle_t pso, const char *desc) {
  if (!mad_gpu_fault_on() || !pso)
    return;
  std::lock_guard<std::mutex> lock(mad_gf_mutex);
  mad_gf_pso[(uint64_t)pso] = desc;
}

void
mad_encoder_note(uint64_t id, std::vector<uint64_t> &&psos) {
  std::lock_guard<std::mutex> lock(mad_gf_mutex);
  if (mad_gf_enc.size() > 20000)
    std::erase_if(mad_gf_enc, [&](const auto &e) { return e.first + 10000 < id; });
  mad_gf_enc[id] = std::move(psos);
}
'''),
    ("  auto cmdbuf = commandQueue.commandBuffer();\n",
     "  auto cmdbuf = mad_gpu_fault_on() ? mad_gf_command_buffer(commandQueue.handle) : commandQueue.commandBuffer();\n"),
    ("      MarkDeviceError();\n",
     "      MarkDeviceError();\n"
     "      if (mad_gpu_fault_on())\n"
     "        mad_gf_report(chunk.attached_cmdbuf.handle, chunk.frame_);\n"),
])

edit("dxmt/dxmt_context.cpp", [
    ("namespace dxmt {\n",
     r'''namespace dxmt {

/* madeira-doge: gpu fault (tools/patch-dxmt-gpu-fault-d3d11.py) */
bool mad_gpu_fault_on();
void mad_encoder_note(uint64_t id, std::vector<uint64_t> &&psos);

namespace {
std::atomic<uint64_t> mad_gf_next_encoder{1};

template <typename Encoder>
void
mad_gf_label(Encoder &encoder, char kind, const void *head, uint16_t setpso_type) {
  std::vector<uint64_t> psos;
  size_t cmds = 0;
  for (auto *c = (const wmtcmd_base *)head; c; c = (const wmtcmd_base *)c->next.ptr) {
    cmds++;
    if (c->type != setpso_type)
      continue;
    /* render and compute setpso share this layout */
    const uint64_t pso = (uint64_t)((const wmtcmd_render_setpso *)c)->pso;
    if (std::find(psos.begin(), psos.end(), pso) == psos.end())
      psos.push_back(pso);
  }
  const uint64_t id = mad_gf_next_encoder.fetch_add(1, std::memory_order_relaxed);
  char label[64];
  snprintf(label, sizeof label, "E%llu %c cmds=%zu psos=%zu", (unsigned long long)id, kind, cmds, psos.size());
  encoder.setLabel(WMT::String::string(label, WMTUTF8StringEncoding));
  mad_encoder_note(id, std::move(psos));
}
} // namespace
'''),
    ("      auto encoder = cmdbuf.renderCommandEncoder(render_pass_info);\n",
     "      auto encoder = cmdbuf.renderCommandEncoder(render_pass_info);\n"
     "      if (mad_gpu_fault_on())\n"
     "        mad_gf_label(encoder, 'R', &data->cmd_head, WMTRenderCommandSetPSO);\n"),
    ("      auto encoder = cmdbuf.computeCommandEncoder(false);\n",
     "      auto encoder = cmdbuf.computeCommandEncoder(false);\n"
     "      if (mad_gpu_fault_on())\n"
     "        mad_gf_label(encoder, 'C', &data->cmd_head, WMTComputeCommandSetPSO);\n"),
])

edit("d3d11/d3d11_pipeline.cpp", [
    ("namespace dxmt {\n",
     "namespace dxmt {\n\n"
     "/* madeira-doge: gpu fault (tools/patch-dxmt-gpu-fault-d3d11.py) */\n"
     "bool mad_gpu_fault_on();\n"
     "void mad_pso_note(obj_handle_t pso, const char *desc);\n"),
    # graphics: the shaders, then the pipeline handle once it exists
    ("""    } else {
      PixelShader = nullptr;
      ps_valid_render_targets = 0;
    }
  }
""",
     """    } else {
      PixelShader = nullptr;
      ps_valid_render_targets = 0;
    }
    if (mad_gpu_fault_on())
      mad_desc_ = "vs=" + pDesc->VertexShader->sha1().string().substr(0, 16) +
                  (pDesc->PixelShader ? " ps=" + pDesc->PixelShader->sha1().string().substr(0, 16) : std::string(" ps=-"));
  }
"""),
    ("""      ERR("Failed to create PSO: ", err.description().getUTF8String());
      return this;
    }
""",
     """      ERR("Failed to create PSO: ", err.description().getUTF8String());
      return this;
    }
    mad_pso_note(state_.handle, mad_desc_.c_str());
"""),
    ("  WMT::Reference<WMT::RenderPipelineState> state_;\n",
     "  WMT::Reference<WMT::RenderPipelineState> state_;\n  std::string mad_desc_;\n"),
    # compute
    ("    ComputeShader = shader->get_shader(ShaderVariantDefault{});\n",
     "    ComputeShader = shader->get_shader(ShaderVariantDefault{});\n"
     "    if (mad_gpu_fault_on())\n"
     "      mad_desc_ = \"cs=\" + shader->sha1().string().substr(0, 16);\n"),
    ("""      ERR("Failed to create compute PSO: ", err.description().getUTF8String());
      return this;
    }
""",
     """      ERR("Failed to create compute PSO: ", err.description().getUTF8String());
      return this;
    }
    mad_pso_note(state_.handle, mad_desc_.c_str());
"""),
    ("  WMT::Reference<WMT::ComputePipelineState> state_;\n",
     "  WMT::Reference<WMT::ComputePipelineState> state_;\n  std::string mad_desc_;\n"),
])
