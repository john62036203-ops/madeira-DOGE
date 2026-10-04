// madeira-bcd: helper kernels for madeira_d3d12.dll, compiled to a metallib in
// CI (tools/build-madeira-d3d12-dll.sh) and embedded in the DLL.
#include <metal_stdlib>
using namespace metal;

struct mad_tess_ind_params {
    uint count;          // argument records
    uint rec_words;      // record stride in 32-bit words (ExecuteIndirect ByteStride / 4)
    uint verts_per_tg;   // patches per object threadgroup x control points per patch
    uint pad;
};

// One D3D12 DRAW_ARGUMENTS / DRAW_INDEXED_ARGUMENTS record (vertex or index
// count first, instance count second) -> MTLDispatchThreadgroupsIndirectArguments
// for the converter's tessellation emulation: ceil(count / verts_per_tg) object
// threadgroups by the instance count. Output records are 16 bytes apart.
kernel void mad_tess_indirect_args(device const uint *args [[buffer(0)]],
                                   device uint *out [[buffer(1)]],
                                   constant mad_tess_ind_params &p [[buffer(2)]],
                                   uint i [[thread_position_in_grid]])
{
    if (i >= p.count)
        return;
    device const uint *a = args + i * p.rec_words;
    uint n = a[0], inst = a[1];
    device uint *o = out + i * 4;
    o[0] = p.verts_per_tg ? (n + p.verts_per_tg - 1) / p.verts_per_tg : 0;
    o[1] = inst;
    o[2] = 1;
    o[3] = 0;
}

// Diagnostics: copy the first n words of an argument record (indirect draw or
// dispatch arguments the GPU wrote) to a CPU-visible ring, read seconds later.
kernel void mad_probe_words(device const uint *src [[buffer(0)]],
                            device uint *dst [[buffer(1)]],
                            constant uint &n [[buffer(2)]],
                            uint i [[thread_position_in_grid]])
{
    if (i < n)
        dst[i] = src[i];
}

// A mesh render pipeline must have a fragment function even when the D3D12
// pipeline has no pixel shader (depth-only tessellated or geometry draws):
// Metal asserts "fragmentFunction must not be nil" and aborts the process.
fragment void mad_null_fragment()
{
}

// madeira-doge: the RE Engine draws its interface (menus, text, movies) into a
// separate premultiplied-alpha sRGB target and, with an upscaler / frame
// generation configured, leaves putting it on screen to a vendor component
// that does not run here; the final blit then carries only the scene. This
// kernel lays that target over the backbuffer inside the blit's viewport.
// Opt-in: madeira.cfg gui-overlay = 1.
struct mad_gui_params {
    uint x0, y0, w, h;
};

// D3D12 2D textures are created as 2D ARRAY textures here (one slice): binding
// one to a plain texture2d parameter reads a single constant colour.
kernel void mad_gui_over(texture2d_array<float> gui [[texture(0)]],
                         texture2d_array<float> bb [[texture(1)]],
                         texture2d<float, access::write> dst [[texture(2)]],
                         constant mad_gui_params &p [[buffer(0)]],
                         uint2 gid [[thread_position_in_grid]])
{
    constexpr sampler smp(filter::linear, address::clamp_to_edge);
    if (gid.x >= dst.get_width() || gid.y >= dst.get_height())
        return;
    float4 s = bb.read(gid, 0);
    if (p.w != 0 && p.h != 0 && gid.x >= p.x0 && gid.y >= p.y0 && gid.x < p.x0 + p.w && gid.y < p.y0 + p.h) {
        float2 uv = (float2(gid - uint2(p.x0, p.y0)) + 0.5f) / float2(p.w, p.h);
        float4 g = gui.sample(smp, uv, 0, level(0));     // sRGB target: linear, premultiplied
        float a = saturate(g.a);
        float3 c = a > 1e-5f ? saturate(g.rgb / a) : float3(0.0f);
        float3 lo = c * 12.92f;
        float3 hi = 1.055f * pow(c, float3(1.0f / 2.4f)) - 0.055f;
        float3 enc = float3(c.x <= 0.0031308f ? lo.x : hi.x, c.y <= 0.0031308f ? lo.y : hi.y, c.z <= 0.0031308f ? lo.z : hi.z);
        s.rgb = enc * a + s.rgb * (1.0f - a);
    }
    dst.write(s, gid);
}

// madeira-doge: Metal has no un-normalised 10:10:10:2 vertex format, and a
// uint4 vertex input refuses UInt1010102Normalized. RE Engine stores bone
// indices that way (DXGI_FORMAT_R10G10B10A2_UINT), so the element is unpacked
// into a ushort4 stream here and the pipeline reads that instead.
struct mad_u10_params {
    uint eoff, stride, count, pad;
};
kernel void mad_u1010102(device const uchar *src [[buffer(0)]],
                         device ushort *dst [[buffer(1)]],
                         constant mad_u10_params &p [[buffer(2)]],
                         uint gid [[thread_position_in_grid]]) {
    if (gid >= p.count) return;
    uint o = p.eoff + gid * p.stride;
    uint v = uint(src[o]) | (uint(src[o + 1]) << 8) | (uint(src[o + 2]) << 16) | (uint(src[o + 3]) << 24);
    dst[gid * 4 + 0] = ushort(v & 1023u);
    dst[gid * 4 + 1] = ushort((v >> 10) & 1023u);
    dst[gid * 4 + 2] = ushort((v >> 20) & 1023u);
    dst[gid * 4 + 3] = ushort(v >> 30);
}
