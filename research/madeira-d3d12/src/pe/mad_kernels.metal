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
