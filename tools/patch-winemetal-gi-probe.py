#!/usr/bin/env python3
"""God of War darkening: what the luminance compute shader reads from the GI
volumes. OFF unless `env.MADEIRA_GI_PROBE = 1` is in the game file.

The game's luminancePartAio compute shader (64x1x1 threads) writes four floats
the CPU reads back every frame ([rb-buf] 16 bytes). The second one is the GI
ambient luminance at the camera: the camera position (sharedConsts, 672 bytes,
row 40) is tested against up to four GI volumes (giVolumeConstants, 2192
bytes), an RGBA8 3D indirection texture is loaded, and an RGBA16F 3D atlas is
sampled. When the picture goes black that value is ~100x smaller than usual.
This probe records the inputs so the lookup can be redone on a PC:

  [gi-probe] #n ...        at most every 2 s (300 times), at a compute
                           dispatch that used a 2192-byte buffer: the buffer
                           lengths used since the previous dispatch and the 3D
                           textures this encoder used so far, in order.
  [gi-probe] cb2 rNNN: ... the 2192-byte buffer as hex words, 8 rows a line,
                           only when it changed since the last probe.
  [gi-probe] cb1 ...       row 40 of the latest 672-byte buffer any encoder
                           used (hex words).
  [gi-probe] tex3d #n ...  every distinct 3D texture a compute encoder uses
                           (64 at most): format, size, mips, storage mode.
  [gi-probe] dumped ...    level 0 of such a texture written once to
                           Documents/shader-dump/gi-tex-<id>-<w>x<h>x<d>-f<fmt>.bin
                           (MADEIRA_SHADER_DUMP_DIR overrides), a second or
                           more after it was first seen so its upload is done;
                           64 MB a texture, 300 MB in all.

After each CAP (tools/patch-winemetal-gpu-trace-cap.py) the small 3D textures
(up to 4 MB: the colour-grading LUTs, 32x32x32 RGBA8 inputs and the 64x64x64
RGB10A2 output) are written again as gi-tex-...-c<n>.bin, and the LUT blend
pass's constants are logged once: `[gi-probe] lbp c<n> ...` (28 hex words).

Costs: one blocking GPU readback per dumped texture. Needs
tools/patch-winemetal-gpu-trace.py first. Native only; not in the i386 farm
key. Idempotent; fails by name if an anchor moves. Run from the repository
root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/winemetal/unix/winemetal_unix.c")
MARKER = "madeira-doge: gi probe"
NAME = "patch-winemetal-gi-probe"

HELPERS = r'''/* madeira-doge: gi probe (tools/patch-winemetal-gi-probe.py) -- opt-in record
 * of what God of War's luminance compute shader reads from the GI volumes. */
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
static int madeira_gi_mode = -1;            /* -1 unread, 0 off, 1 on */
static int madeira_gi_on(void) {
  if (madeira_gi_mode < 0) {
    const char *e = getenv("MADEIRA_GI_PROBE");
    madeira_gi_mode = (e && e[0] == '1') ? 1 : 0;
    if (madeira_gi_mode)
      fprintf(stderr, "[gi-probe] madeira-doge on: GI volume constants and 3D textures of the luminance "
                      "compute shader (MADEIRA_GI_PROBE)\n");
  }
  return madeira_gi_mode;
}

struct madeira_gi_tex { uintptr_t ptr; unsigned w, h, d, fmt; double first; int dumped; unsigned gen; };
static struct madeira_gi_tex madeira_gi_texs[64];
static unsigned madeira_gi_ntex;
static unsigned long long madeira_gi_dump_bytes;
static id<MTLCommandQueue> madeira_gi_queue;
static id<MTLBuffer> madeira_gi_cb1;        /* latest 672-byte buffer, retained */
static unsigned madeira_gi_cap_gen;         /* bumped by each CAP (tools/patch-winemetal-gpu-trace-cap.py) */
static void madeira_gi_cap(void) { madeira_gi_cap_gen++; }

static unsigned madeira_gi_bpp(unsigned fmt) {
  switch ((MTLPixelFormat)fmt) {
  case MTLPixelFormatR8Unorm: return 1;
  case MTLPixelFormatRG16Float: return 4;
  case MTLPixelFormatRGBA8Unorm: case MTLPixelFormatRGBA8Unorm_sRGB: case MTLPixelFormatBGRA8Unorm: return 4;
  case MTLPixelFormatRGB10A2Unorm: return 4;   /* the colour-grading LUT the game blends (64x64x64) */
  case MTLPixelFormatRGBA16Float: return 8;
  case MTLPixelFormatRGBA32Float: return 16;
  default: return 0;
  }
}

static void madeira_gi_dump_tex(id<MTLTexture> t, struct madeira_gi_tex *e) {
  unsigned bpp = madeira_gi_bpp(e->fmt);
  unsigned long long bytes = (unsigned long long)e->w * e->h * e->d * bpp;
  unsigned long tid = madeira_gt_id(t);
  e->dumped = 1;
  e->gen = madeira_gi_cap_gen;
  if (!bpp || !bytes || bytes > (64ull << 20) || madeira_gi_dump_bytes + bytes > (300ull << 20)) {
    fprintf(stderr, "[gi-probe] not dumped t%05lx fmt %u %ux%ux%u (%llu bytes; format not handled or over the cap)\n",
            tid, e->fmt, e->w, e->h, e->d, bytes);
    return;
  }
  char dir[900], path[1024];
  const char *o = getenv("MADEIRA_SHADER_DUMP_DIR"), *docs = getenv("MADEIRA_DOCS_DIR"), *home = getenv("HOME");
  if (o && *o) snprintf(dir, sizeof dir, "%s", o);
  else if (docs && *docs) snprintf(dir, sizeof dir, "%s/shader-dump", docs);
  else if (home && *home) snprintf(dir, sizeof dir, "%s/Documents/shader-dump", home);
  else return;
  mkdir(dir, 0755);
  if (madeira_gi_cap_gen)
    snprintf(path, sizeof path, "%s/gi-tex-%05lx-%ux%ux%u-f%u-c%u.bin", dir, tid, e->w, e->h, e->d, e->fmt, madeira_gi_cap_gen);
  else
    snprintf(path, sizeof path, "%s/gi-tex-%05lx-%ux%ux%u-f%u.bin", dir, tid, e->w, e->h, e->d, e->fmt);
  @autoreleasepool {
    id<MTLDevice> dev = t.device;
    if (!madeira_gi_queue) madeira_gi_queue = [dev newCommandQueue];
    id<MTLBuffer> buf = [dev newBufferWithLength:(NSUInteger)bytes options:MTLResourceStorageModeShared];
    if (!madeira_gi_queue || !buf) {
      fprintf(stderr, "[gi-probe] not dumped t%05lx (no queue or buffer)\n", tid);
      [buf release];
      return;
    }
    id<MTLCommandBuffer> cb = [madeira_gi_queue commandBuffer];
    id<MTLBlitCommandEncoder> b = [cb blitCommandEncoder];
    [b copyFromTexture:t
                 sourceSlice:0
                 sourceLevel:0
                sourceOrigin:MTLOriginMake(0, 0, 0)
                  sourceSize:MTLSizeMake(e->w, e->h, e->d)
                    toBuffer:buf
           destinationOffset:0
      destinationBytesPerRow:(NSUInteger)e->w * bpp
    destinationBytesPerImage:(NSUInteger)e->w * e->h * bpp];
    [b endEncoding];
    [cb commit];
    [cb waitUntilCompleted];
    int ok = 0;
    if (cb.status == MTLCommandBufferStatusCompleted) {
      int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
      if (fd >= 0) {
        const uint8_t *p = (const uint8_t *)[buf contents];
        unsigned long long done = 0;
        while (p && done < bytes) {
          ssize_t n = write(fd, p + done, (size_t)(bytes - done));
          if (n <= 0) break;
          done += (unsigned long long)n;
        }
        close(fd);
        ok = done == bytes;
      }
    }
    if (ok) madeira_gi_dump_bytes += bytes;
    fprintf(stderr, "[gi-probe] %s t%05lx fmt %u %ux%ux%u %llu bytes -> %s\n", ok ? "dumped" : "dump FAILED", tid,
            e->fmt, e->w, e->h, e->d, bytes, path);
    [buf release];
  }
}

static void madeira_gi_note_tex(id<MTLTexture> t, unsigned long *seen, unsigned *nseen) {
  unsigned long tid = madeira_gt_id(t);
  unsigned i;
  for (i = 0; i < *nseen; i++) if (seen[i] == tid) break;
  if (i == *nseen && *nseen < 16) seen[(*nseen)++] = tid;
  unsigned w = (unsigned)t.width, h = (unsigned)t.height, d = (unsigned)t.depth, fmt = (unsigned)t.pixelFormat;
  double now = madeira_gt_now();
  struct madeira_gi_tex *e = NULL;
  for (i = 0; i < madeira_gi_ntex; i++) {
    struct madeira_gi_tex *x = &madeira_gi_texs[i];
    if (x->ptr == (uintptr_t)t && x->w == w && x->h == h && x->d == d && x->fmt == fmt) { e = x; break; }
  }
  if (!e) {
    if (madeira_gi_ntex >= 64) return;
    e = &madeira_gi_texs[madeira_gi_ntex++];
    e->ptr = (uintptr_t)t; e->w = w; e->h = h; e->d = d; e->fmt = fmt; e->first = now; e->dumped = 0;
    fprintf(stderr, "[gi-probe] tex3d #%u t%05lx%s fmt %u %ux%ux%u mips %lu storage %lu usage 0x%lx\n", madeira_gi_ntex,
            tid, t.parentTexture ? "v" : "", fmt, w, h, d, (unsigned long)t.mipmapLevelCount,
            (unsigned long)t.storageMode, (unsigned long)t.usage);
    return;
  }
  if (!e->dumped && now - e->first > 1.0) madeira_gi_dump_tex(t, e);
  /* after a CAP: small 3D textures (the colour LUTs) are written again, as they stand now */
  else if (e->dumped && e->gen != madeira_gi_cap_gen &&
           (unsigned long long)w * h * d * madeira_gi_bpp(fmt) <= (4ull << 20))
    madeira_gi_dump_tex(t, e);
}

static void madeira_gi_note_buffer(id<MTLBuffer> b) {
  if ([b length] != 672 || b == madeira_gi_cb1) return;
  [madeira_gi_cb1 release];
  madeira_gi_cb1 = [b retain];
}

static void madeira_gi_probe(id<MTLBuffer> cb2, const unsigned long *seen, unsigned nseen, const char *lens) {
  static double last;
  static unsigned probes;
  static uint32_t last_hash;
  double now = madeira_gt_now();
  if (probes >= 300 || now - last < 2.0) return;
  last = now;
  probes++;
  char line[400];
  int o = 0;
  for (unsigned i = 0; i < nseen && o < (int)sizeof line - 12; i++) o += snprintf(line + o, sizeof line - o, " t%05lx", seen[i]);
  if (!o) snprintf(line, sizeof line, " -");
  fprintf(stderr, "[gi-probe] #%u cb2 b%05lx storage %lu buffers since the last dispatch:%s tex3d in this encoder:%s\n", probes,
          madeira_gt_id(cb2), (unsigned long)cb2.storageMode, lens[0] ? lens : " -", line);
  const uint32_t *p = (const uint32_t *)[cb2 contents];
  if (!p) {
    fprintf(stderr, "[gi-probe] cb2 is not CPU-visible\n");
  } else {
    uint32_t hsh = 2166136261u;
    for (unsigned i = 0; i < 548; i++) hsh = (hsh ^ p[i]) * 16777619u;
    if (hsh == last_hash) {
      fprintf(stderr, "[gi-probe] cb2 unchanged\n");
    } else {
      last_hash = hsh;
      for (unsigned r = 0; r < 137; r += 8) {
        o = 0;
        for (unsigned i = r * 4; i < (r + 8) * 4 && i < 548; i++) o += snprintf(line + o, sizeof line - o, " %08x", p[i]);
        fprintf(stderr, "[gi-probe] cb2 r%03u:%s\n", r, line);
      }
    }
  }
  const uint32_t *q = madeira_gi_cb1 ? (const uint32_t *)[madeira_gi_cb1 contents] : NULL;
  if (q)
    fprintf(stderr, "[gi-probe] cb1 b%05lx r040: %08x %08x %08x %08x\n", madeira_gt_id(madeira_gi_cb1), q[160], q[161],
            q[162], q[163]);
  else
    fprintf(stderr, "[gi-probe] cb1: no CPU-visible 672-byte buffer seen yet\n");
}

/* kind 1: a compute encoder's batch; kind 0: a render encoder's (only its
 * 672-byte buffers matter). */
static void madeira_gi_walk(int kind, obj_handle_t enc, const struct wmtcmd_base *c) {
  static obj_handle_t cenc;
  static id<MTLBuffer> cb2;                 /* 2192-byte buffer used since the last dispatch, retained */
  static unsigned long seen[16];
  static unsigned nseen;
  static char lens[200];
  static int leno;
  static id<MTLBuffer> b256;                /* latest 256-byte buffer used since the last dispatch, retained */
  static int lut_out;                       /* a writable RGB10A2 3D texture was used since the last dispatch */
  static unsigned lbp_gen;
  if (kind == 0) {
    for (; c; c = c->next.ptr) {
      if ((enum WMTRenderCommandType)c->type != WMTRenderCommandUseResource) continue;
      id r = (id)((const struct wmtcmd_render_useresource *)c)->resource;
      if (r && ![r conformsToProtocol:@protocol(MTLTexture)]) madeira_gi_note_buffer((id<MTLBuffer>)r);
    }
    return;
  }
  if (enc != cenc) {
    cenc = enc;
    [cb2 release];
    cb2 = nil;
    [b256 release];
    b256 = nil;
    lut_out = 0;
    nseen = 0;
    leno = 0;
    lens[0] = 0;
  }
  for (; c; c = c->next.ptr) {
    switch ((enum WMTComputeCommandType)c->type) {
    case WMTComputeCommandUseResource: {
      id r = (id)((const struct wmtcmd_compute_useresource *)c)->resource;
      if (!r) break;
      if ([r conformsToProtocol:@protocol(MTLTexture)]) {
        id<MTLTexture> t = (id<MTLTexture>)r;
        if (t.textureType == MTLTextureType3D) {
          madeira_gi_note_tex(t, seen, &nseen);
          if (t.pixelFormat == MTLPixelFormatRGB10A2Unorm &&
              (((const struct wmtcmd_compute_useresource *)c)->usage & 2))
            lut_out = 1;
        }
      } else {
        id<MTLBuffer> b = (id<MTLBuffer>)r;
        unsigned long len = (unsigned long)[b length];
        madeira_gi_note_buffer(b);
        if (len == 2192 && b != cb2) {
          [cb2 release];
          cb2 = [b retain];
        }
        if (len == 256 && b != b256) {
          [b256 release];
          b256 = [b retain];
        }
        if (leno < (int)sizeof lens - 12) leno += snprintf(lens + leno, sizeof lens - leno, " %lu", len);
      }
      break;
    }
    case WMTComputeCommandDispatch: case WMTComputeCommandDispatchThreads: case WMTComputeCommandDispatchIndirect:
      if (cb2) {
        madeira_gi_probe(cb2, seen, nseen, lens);
        [cb2 release];
        cb2 = nil;
      }
      if (lut_out && b256 && lbp_gen != madeira_gi_cap_gen) {
        /* the LUT blend pass (ConstBuf__lbp, 112 bytes): weights and count, once per CAP */
        const uint32_t *q = (const uint32_t *)[b256 contents];
        lbp_gen = madeira_gi_cap_gen;
        if (q) {
          char ln[300];
          int o = 0;
          for (unsigned i = 0; i < 28; i++) o += snprintf(ln + o, sizeof ln - o, " %08x", q[i]);
          fprintf(stderr, "[gi-probe] lbp c%u b%05lx:%s\n", madeira_gi_cap_gen, madeira_gt_id(b256), ln);
        } else
          fprintf(stderr, "[gi-probe] lbp c%u: constants not CPU-visible\n", madeira_gi_cap_gen);
      }
      [b256 release];
      b256 = nil;
      lut_out = 0;
      leno = 0;
      lens[0] = 0;
      break;
    default:
      break;
    }
  }
}

'''

PAIRS = [
    ("static void madeira_gt_end_encoder(obj_handle_t enc) {\n",
     HELPERS + "static void madeira_gt_end_encoder(obj_handle_t enc) {\n", 1),
    ("  if (madeira_gt_tracing) madeira_gt_walk(1, params->encoder, next);   /* madeira-bcd: gpu trace */\n",
     "  if (madeira_gt_tracing) madeira_gt_walk(1, params->encoder, next);   /* madeira-bcd: gpu trace */\n"
     "  if (madeira_gi_on()) madeira_gi_walk(1, params->encoder, next);   /* madeira-doge: gi probe */\n", 1),
    ("  if (madeira_gt_tracing) madeira_gt_walk(0, params->encoder, next);   /* madeira-bcd: gpu trace */\n",
     "  if (madeira_gt_tracing) madeira_gt_walk(0, params->encoder, next);   /* madeira-bcd: gpu trace */\n"
     "  if (madeira_gi_on()) madeira_gi_walk(0, params->encoder, next);   /* madeira-doge: gi probe */\n", 1),
]


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("winemetal_unix.c: already patched")
        return 0
    if "madeira-bcd: gpu trace" not in s:
        sys.exit(f"{NAME}: 'madeira-bcd: gpu trace' missing -- run tools/patch-winemetal-gpu-trace.py first")
    for old, new, want in PAIRS:
        n = s.count(old)
        if n != want:
            sys.exit(f"{NAME}: anchor found {n} times (want {want}) in {PATH}:\n{old}")
        s = s.replace(old, new)
    PATH.write_text(s)
    print("winemetal_unix.c: patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
