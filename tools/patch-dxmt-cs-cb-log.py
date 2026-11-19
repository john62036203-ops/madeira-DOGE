#!/usr/bin/env python3
"""Log the constants a compute dispatch is encoded with (God of War's luminance chain).

Build 643's [rb-map] log showed the game reading two different exposure results from the same computation, frame by
frame, in a still scene. This logs, on the encode thread, what the shared constants hold when a compute dispatch is
encoded: for every Dispatch whose constant buffer slot 1 is 672 bytes (ConstBuf__sharedConsts),

  [cs-cb] #n seq <s> grp <x>x<y> cb0 <len> <8 words> cb1 h <fnv of 672 bytes> r41 <word> r3 <4 floats> w <rows 8..18 .x>

Off unless env.MADEIRA_CS_CB_LOG = 1 (source-built d3d11 only: env.MADEIRA_D3D11_SRC = 1). 20000 lines a session.
Applied by tools/build-d3d11-dll.sh to its copy of the sources (argument: that d3d11 directory).
Idempotent; fails by name if an anchor moved.
"""
import pathlib
import sys

PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11") / "d3d11_context_impl.cpp"
MARKER = "madeira-doge: compute constants log"

OLD = """  Dispatch(UINT ThreadGroupCountX, UINT ThreadGroupCountY, UINT ThreadGroupCountZ) override {
    std::lock_guard<mutex_t> lock(mutex);

    if (!PreDispatch())
      return;
"""
NEW = OLD + """    /* madeira-doge: compute constants log (tools/patch-dxmt-cs-cb-log.py) */
    {
      static const bool cs_cb_log = env::getEnvVar("MADEIRA_CS_CB_LOG") == "1";
      if (cs_cb_log) {
        Rc<Buffer> cb0_buf, cb1_buf;
        UINT cb0_off = 0, cb0_len = 0, cb1_off = 0, cb1_num = 0;
        for (const auto &[slot, entry] : state_.ShaderStages[PipelineStage::Compute].ConstantBuffers) {
          if (slot == 0) {
            cb0_buf = entry.Buffer->buffer();
            cb0_off = entry.FirstConstant << 4;
            cb0_len = entry.NumConstants << 4;
          }
          if (slot == 1) {
            cb1_buf = entry.Buffer->buffer();
            cb1_off = entry.FirstConstant << 4;
            cb1_num = entry.NumConstants;
          }
        }
        if (cb1_buf.ptr() && cb1_num == 42) {
          EmitOP([cb0_buf, cb1_buf, cb0_off, cb0_len, cb1_off, ThreadGroupCountX,
                  ThreadGroupCountY](ArgumentEncodingContext &enc) {
            static uint32_t cs_cb_n;
            if (++cs_cb_n > 20000)
              return;
            uint32_t w0[8] = {0, 0, 0, 0, 0, 0, 0, 0};
            float r3[4] = {0.0f, 0.0f, 0.0f, 0.0f};
            float wt[11] = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
            uint32_t r41 = 0, h = 2166136261u, mapped = 0;
            if (cb0_buf.ptr() && cb0_len) {
              auto a0 = enc.access(cb0_buf, cb0_off, cb0_len, DXMT_ENCODER_RESOURCE_ACESS_READ);
              const char *p0 = reinterpret_cast<const char *>(a0.first->mappedMemory(0));
              if (p0)
                std::memcpy(w0, p0 + a0.second + cb0_off, cb0_len < 32 ? cb0_len : 32);
            }
            auto a1 = enc.access(cb1_buf, cb1_off, 672, DXMT_ENCODER_RESOURCE_ACESS_READ);
            const unsigned char *p1 = reinterpret_cast<const unsigned char *>(a1.first->mappedMemory(0));
            if (p1) {
              mapped = 1;
              p1 += a1.second + cb1_off;
              for (unsigned i = 0; i < 672; i++)
                h = (h ^ p1[i]) * 16777619u;
              std::memcpy(r3, p1 + 48, 16);
              std::memcpy(&r41, p1 + 656, 4);
              for (unsigned i = 0; i < 11; i++)
                std::memcpy(&wt[i], p1 + 16 * (8 + i), 4);
            }
            ERR("[cs-cb] #", cs_cb_n, " seq ", uint64_t(enc.currentSeqId()), " grp ", ThreadGroupCountX, "x",
                ThreadGroupCountY, " cb0 ", cb0_len, " ", w0[0], " ", w0[1], " ", w0[2], " ", w0[3], " ", w0[4], " ",
                w0[5], " ", w0[6], " ", w0[7], " cb1 ", mapped ? "h " : "unmapped ", h, " r41 ", r41, " r3 ", r3[0],
                " ", r3[1], " ", r3[2], " ", r3[3], " w ", wt[0], " ", wt[1], " ", wt[2], " ", wt[3], " ", wt[4], " ",
                wt[5], " ", wt[6], " ", wt[7], " ", wt[8], " ", wt[9], " ", wt[10]);
          });
        }
      }
    }
"""
INC_OLD = '#include "dxmt_staging.hpp"\n'
INC_NEW = '#include "dxmt_staging.hpp"\n#include "util_env.hpp" /* madeira-doge: compute constants log */\n#include <cstring>\n#include <cstdint>\n'


def main():
    src = PATH.read_text()
    if MARKER in src:
        print("cs-cb log: already applied")
        return 0
    for name, old in (("Dispatch", OLD), ("dxmt_staging include", INC_OLD)):
        if src.count(old) != 1:
            print(f"cs-cb log: anchor '{name}' found {src.count(old)} times in {PATH}", file=sys.stderr)
            return 1
    PATH.write_text(src.replace(OLD, NEW).replace(INC_OLD, INC_NEW))
    print("cs-cb log: applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
