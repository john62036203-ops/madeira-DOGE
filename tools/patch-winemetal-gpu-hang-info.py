#!/usr/bin/env python3
"""Say which encoder (and shader) a GPU hang came from, for the D3D11 path.

Devil May Cry 5 (build 626, 2026-11-14) still stops about two minutes into
play: a command buffer waits 10 s and every buffer comes back "Discarded
(victim of GPU error/recovery)". The buffer that actually hung is never named.
tools/patch-dxmt-gpu-fault-info.py gave madeira_d3d12 encoder execution status;
DXMT's own command buffers never had it.

env.MADEIRA_GPU_HANG_INFO = 1 (per game, off by default):
  * every command buffer DXMT asks for is created with
    MTLCommandBufferErrorOptionEncoderExecutionStatus and, when it ends in an
    error, prints `[gpu-hang]` lines: the error code and text, then each
    encoder that did not complete (FAULTED / affected / pending / unknown) with
    its label (first 40 buffers with an error);
  * every render and compute encoder is labelled with the Metal functions its
    pipelines use (DXMT names them ps_<sha8>_<variant> / shader_<sha8>, the
    first 8 hex digits of the DXBC SHA-1), so a FAULTED line names the shader.
    Pipeline names are recorded through the gpu-trace pipeline table, which
    this switch now fills too.
env.MADEIRA_SKIP_CS_ENC = shader_<sha8>[,shader_<sha8>...] (experiment, off by
default; also turns the [gpu-hang] lines on): in every compute encoder that
sets one of these pipelines, the dispatches are dropped (fence updates kept,
so later encoders are not left waiting). env.MADEIRA_SKIP_CS_WAIT = 1 also
drops that encoder's fence waits. The game loses that encoder's work.
Native path only. Run after tools/patch-winemetal-gpu-trace.py. Idempotent;
fails by name if an anchor moves. Run from the repository root.
"""
import pathlib
import sys

NAME = "patch-winemetal-gpu-hang-info"
PATH = pathlib.Path("dxmt/src/winemetal/unix/winemetal_unix.c")
MARKER = "madeira-doge: gpu hang info"

HELPER = r'''/* madeira-doge: gpu hang info (tools/patch-winemetal-gpu-hang-info.py) */
static const char *madeira_gt_pso_name(obj_handle_t pso);
static int mad_ghi_on(void) {
  static int v = -1;
  if (v < 0) {
    const char *e = getenv("MADEIRA_GPU_HANG_INFO");
    const char *k = getenv("MADEIRA_SKIP_CS_ENC");
    v = ((e && *e && *e != '0') || (k && *k)) ? 1 : 0;
    if (v) fprintf(stderr, "[gpu-hang] MADEIRA_GPU_HANG_INFO on: encoder execution status + shader-named encoders\n");
  }
  return v;
}
static const char *mad_ghi_state(MTLCommandEncoderErrorState s) {
  switch (s) {
  case MTLCommandEncoderErrorStateCompleted: return "completed";
  case MTLCommandEncoderErrorStateAffected: return "affected";
  case MTLCommandEncoderErrorStatePending: return "pending";
  case MTLCommandEncoderErrorStateFaulted: return "FAULTED";
  default: return "unknown";
  }
}
static unsigned mad_ghi_reported;
static id<MTLCommandBuffer> mad_ghi_command_buffer(id<MTLCommandQueue> queue) {
  MTLCommandBufferDescriptor *desc = [MTLCommandBufferDescriptor new];
  desc.errorOptions = MTLCommandBufferErrorOptionEncoderExecutionStatus;
  id<MTLCommandBuffer> cb = [queue commandBufferWithDescriptor:desc];
  [desc release];
  if (!cb) return [queue commandBuffer];
  [cb addCompletedHandler:^(id<MTLCommandBuffer> done) {
    NSError *err = done.error;
    if (!err) return;
    if (__atomic_fetch_add(&mad_ghi_reported, 1, __ATOMIC_RELAXED) >= 40) return;
    @autoreleasepool {
      NSError *un = err.userInfo[NSUnderlyingErrorKey];
      const char *ld = err.localizedDescription.UTF8String;
      NSArray *infos = err.userInfo[MTLCommandBufferEncoderInfoErrorKey];
      unsigned completed = 0, shown = 0;
      fprintf(stderr, "[gpu-hang] cb %p queue %p code=%ld '%.160s' under=%ld '%.120s' encoders=%lu\n",
              (void *)done, (void *)done.commandQueue, (long)err.code, ld ? ld : "",
              un ? (long)un.code : 0L, un && un.localizedDescription.UTF8String ? un.localizedDescription.UTF8String : "",
              (unsigned long)infos.count);
      NSUInteger idx = 0;
      for (id<MTLCommandBufferEncoderInfo> info in infos) {
        if (info.errorState == MTLCommandEncoderErrorStateCompleted) { completed++; idx++; continue; }
        if (shown < 24 || info.errorState == MTLCommandEncoderErrorStateFaulted) {
          NSString *sp = info.debugSignposts.count ? [info.debugSignposts componentsJoinedByString:@","] : nil;
          fprintf(stderr, "[gpu-hang]   enc #%lu %s '%.200s'%s%.200s\n", (unsigned long)idx, mad_ghi_state(info.errorState),
                  info.label.UTF8String ? info.label.UTF8String : "", sp ? " signposts=" : "", sp ? sp.UTF8String : "");
          shown++;
        }
        idx++;
      }
      fprintf(stderr, "[gpu-hang]   %u encoders completed\n", completed);
    }
  }];
  return cb;
}
/* Label an encoder with the Metal functions of the pipelines its commands set. */
static void mad_ghi_label(int compute, obj_handle_t encoder, const struct wmtcmd_base *c) {
  char names[6][24];
  unsigned n = 0, extra = 0, cmds = 0;
  for (; c; c = c->next.ptr) {
    obj_handle_t pso = 0;
    cmds++;
    if (compute && c->type == WMTComputeCommandSetPSO) pso = ((const struct wmtcmd_compute_setpso *)c)->pso;
    else if (!compute && c->type == WMTRenderCommandSetPSO) pso = ((const struct wmtcmd_render_setpso *)c)->pso;
    if (!pso) continue;
    const char *nm = madeira_gt_pso_name(pso);
    unsigned i = 0;
    for (; i < n; i++) if (!strcmp(names[i], nm)) break;
    if (i < n) continue;
    if (n < 6) snprintf(names[n++], sizeof names[0], "%s", nm);
    else extra++;
  }
  if (!n) return;
  char label[200];
  int w = snprintf(label, sizeof label, "%s %u cmds:", compute ? "C" : "R", cmds);
  for (unsigned i = 0; i < n && w > 0 && (size_t)w < sizeof label; i++)
    w += snprintf(label + w, sizeof label - w, " %s", names[i]);
  if (extra && w > 0 && (size_t)w < sizeof label) snprintf(label + w, sizeof label - w, " +%u", extra);
  @autoreleasepool {
    [(id<MTLCommandEncoder>)encoder setLabel:[NSString stringWithUTF8String:label]];
  }
}
/* MADEIRA_SKIP_CS_ENC: 0 = encode normally, 1 = drop dispatches, 2 = also drop fence waits. */
static int mad_ghi_skip_mode(const struct wmtcmd_base *c) {
  static int init;
  static char list[512];
  static int wait_too;
  if (!init) {
    const char *k = getenv("MADEIRA_SKIP_CS_ENC");
    const char *w = getenv("MADEIRA_SKIP_CS_WAIT");
    if (k) snprintf(list, sizeof list, ",%s,", k);
    wait_too = (w && *w == '1');
    init = 1;
    if (list[0]) fprintf(stderr, "[gpu-hang] MADEIRA_SKIP_CS_ENC=%s wait=%d\n", k, wait_too);
  }
  if (!list[0]) return 0;
  for (; c; c = c->next.ptr) {
    if (c->type != WMTComputeCommandSetPSO) continue;
    obj_handle_t pso = ((const struct wmtcmd_compute_setpso *)c)->pso;
    if (!pso) continue;
    char key[32];
    snprintf(key, sizeof key, ",%s,", madeira_gt_pso_name(pso));
    if (strstr(list, key)) {
      static unsigned told;
      if (told++ < 8) fprintf(stderr, "[gpu-hang] skipping a compute encoder that sets %s (#%u)\n", key, told);
      return wait_too ? 2 : 1;
    }
  }
  return 0;
}

'''

PAIRS = [
    ("static NTSTATUS\n_MTLCommandQueue_commandBuffer(void *obj) {\n",
     HELPER + "static NTSTATUS\n_MTLCommandQueue_commandBuffer(void *obj) {\n", 1),
    ("  params->ret = (obj_handle_t)[(id<MTLCommandQueue>)params->handle commandBuffer];\n",
     "  params->ret = (obj_handle_t)(mad_ghi_on() ? mad_ghi_command_buffer((id<MTLCommandQueue>)params->handle)   /* madeira-doge: gpu hang info */\n"
     "                                           : [(id<MTLCommandQueue>)params->handle commandBuffer]);\n", 1),
    ("  if (!madeira_gt_on() || !pso || !fn) return;\n",
     "  if (!(madeira_gt_on() || mad_ghi_on()) || !pso || !fn) return;   /* madeira-doge: gpu hang info fills it too */\n", 1),
    ("  if (madeira_gt_tracing) madeira_gt_walk(1, params->encoder, next);   /* madeira-bcd: gpu trace */\n",
     "  if (madeira_gt_tracing) madeira_gt_walk(1, params->encoder, next);   /* madeira-bcd: gpu trace */\n"
     "  if (mad_ghi_on()) mad_ghi_label(1, params->encoder, next);   /* madeira-doge: gpu hang info */\n", 1),
    ("  if (madeira_gt_tracing) madeira_gt_walk(0, params->encoder, next);   /* madeira-bcd: gpu trace */\n",
     "  if (madeira_gt_tracing) madeira_gt_walk(0, params->encoder, next);   /* madeira-bcd: gpu trace */\n"
     "  if (mad_ghi_on()) mad_ghi_label(0, params->encoder, next);   /* madeira-doge: gpu hang info */\n", 1),
]

POST = [
    ("  if (mad_ghi_on()) mad_ghi_label(1, params->encoder, next);   /* madeira-doge: gpu hang info */\n",
     "  if (mad_ghi_on()) mad_ghi_label(1, params->encoder, next);   /* madeira-doge: gpu hang info */\n"
     "  const int mad_skip = mad_ghi_on() ? mad_ghi_skip_mode(next) : 0;   /* madeira-doge: MADEIRA_SKIP_CS_ENC */\n", 1, "post"),
    ("      if (threadgroup_size.width == 0 && madeira_null_pso_skip()) break;   /* madeira-doge: steamac null-pso (0006) */\n",
     "      if (threadgroup_size.width == 0 && madeira_null_pso_skip()) break;   /* madeira-doge: steamac null-pso (0006) */\n"
     "      if (mad_skip) break;   /* madeira-doge: MADEIRA_SKIP_CS_ENC */\n", 3, "all"),
    ("    case WMTComputeCommandWaitForFence: {\n      struct wmtcmd_compute_fence_op *body = (struct wmtcmd_compute_fence_op *)next;\n",
     "    case WMTComputeCommandWaitForFence: {\n      struct wmtcmd_compute_fence_op *body = (struct wmtcmd_compute_fence_op *)next;\n"
     "      if (mad_skip == 2) break;   /* madeira-doge: MADEIRA_SKIP_CS_WAIT */\n", 1, "all"),
]


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("winemetal_unix.c: already patched")
        return 0
    if "madeira-bcd: gpu trace (tools/patch-winemetal-gpu-trace.py)" not in s:
        sys.exit(f"{NAME}: run tools/patch-winemetal-gpu-trace.py first")
    for old, new, want in PAIRS:
        n = s.count(old)
        if n != want:
            sys.exit(f"{NAME}: anchor found {n} times (want {want}) in {PATH}:\n{old}")
        s = s.replace(old, new, 1)
    for old, new, want, mode in POST:
        n = s.count(old)
        if n != want:
            sys.exit(f"{NAME}: anchor found {n} times (want {want}) in {PATH}:\n{old}")
        s = s.replace(old, new) if mode == "all" else s.replace(old, new, 1)
    PATH.write_text(s)
    print("winemetal_unix.c: patched (MADEIRA_GPU_HANG_INFO)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
