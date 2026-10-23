#!/usr/bin/env python3
"""SM50GetRangeInfo reports each texture argument's DIMENSION in its Flags.

madeira-d3d12 binds the texture objects for a DXBC (airconv) shader from the
range table SM50GetRangeInfo returns. That table says whether the shader
declared an ARRAY texture (MTL_SM50_SHADER_ARGUMENT_TEXTURE_ARRAY) but not
whether it declared a 1D, 2D, 3D, cube or multisampled one, and madeira-d3d12
allocates every 1D/2D resource as a 2D array (ml932, for the DXIL converter's
ForceTextureArray). A texture bound with a type the shader did not declare
samples undefined values on Apple GPUs (EXVS2's whole UI, build 405-408), so
the PE side needs the dimension to choose the view type -- and to say when no
view can satisfy the shader (a 1D texture allocated as a 2D array).

Bits 7, 8, 9 and 12 of Flags are free in MTL_SM50_SHADER_ARGUMENT_FLAG:
  1 << 7   the shader declared a 1D texture (Texture1D / Texture1DArray)
  1 << 8   a 3D texture
  1 << 9   a cube (TextureCube / TextureCubeArray)
  1 << 12  a multisampled 2D texture
Buffers, texture buffers and plain 2D textures set none of them. The PE side
mirrors these in madeira_ir_abi.h (MADEIRA_IR_AIR_F_TEX_*). A converter without
this patch leaves the bits 0 and the PE side falls back to the array-only rule.

Idempotent; fails by name if an anchor moves. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/airconv/dxbc_converter.cpp")
MARKER = "madeira-doge: range dimension flags"

src = PATH.read_text()
if MARKER in src:
    print(f"{PATH}: already patched")
    sys.exit(0)

OLD_SRV = """    case SM50BindingType::SRV: {
      auto it = info.srvMap.find(arg.SM50BindingSlot);
      if (it != info.srvMap.end()) r = &it->second.range;
      break;
    }
    case SM50BindingType::UAV: {
      auto it = info.uavMap.find(arg.SM50BindingSlot);
      if (it != info.uavMap.end()) r = &it->second.range;
      break;
    }
    }
    if (pRanges && total < Capacity) {"""
NEW_SRV = """    case SM50BindingType::SRV: {
      auto it = info.srvMap.find(arg.SM50BindingSlot);
      if (it != info.srvMap.end()) { r = &it->second.range; dim = it->second.resource_type; }
      break;
    }
    case SM50BindingType::UAV: {
      auto it = info.uavMap.find(arg.SM50BindingSlot);
      if (it != info.uavMap.end()) { r = &it->second.range; dim = it->second.resource_type; }
      break;
    }
    }
    /* madeira-doge: range dimension flags -- the PE side picks the Metal view
     * type from these (see tools/patch-airconv-range-dim.py). */
    uint32_t dim_flags = 0;
    switch (dim) {
    case dxmt::shader::common::ResourceType::Texture1D:
    case dxmt::shader::common::ResourceType::Texture1DArray:
      dim_flags = 1u << 7; break;
    case dxmt::shader::common::ResourceType::Texture3D:
      dim_flags = 1u << 8; break;
    case dxmt::shader::common::ResourceType::TextureCube:
    case dxmt::shader::common::ResourceType::TextureCubeArray:
      dim_flags = 1u << 9; break;
    case dxmt::shader::common::ResourceType::Texture2DMultisampled:
    case dxmt::shader::common::ResourceType::Texture2DMultisampledArray:
      dim_flags = 1u << 12; break;
    default:
      break;
    }
    if (pRanges && total < Capacity) {"""
OLD_FLAGS = """      o.Flags = (uint32_t)arg.Flags;
      o.IsConstantBufferTable = is_cb_table;"""
NEW_FLAGS = """      o.Flags = (uint32_t)arg.Flags | dim_flags;
      o.IsConstantBufferTable = is_cb_table;"""
OLD_DECL = """  auto emit = [&](const MTL_SM50_SHADER_ARGUMENT &arg, uint32_t is_cb_table) {
    const dxmt::dxbc::ResourceRange *r = nullptr;"""
NEW_DECL = """  auto emit = [&](const MTL_SM50_SHADER_ARGUMENT &arg, uint32_t is_cb_table) {
    const dxmt::dxbc::ResourceRange *r = nullptr;
    dxmt::shader::common::ResourceType dim = dxmt::shader::common::ResourceType::NonApplicable;"""

for old, new in ((OLD_DECL, NEW_DECL), (OLD_SRV, NEW_SRV), (OLD_FLAGS, NEW_FLAGS)):
    if src.count(old) != 1:
        sys.exit(f"patch-airconv-range-dim: anchor found {src.count(old)} times (want 1) in {PATH}:\n{old}")
    src = src.replace(old, new)
PATH.write_text(src)
print(f"{PATH}: patched (SM50GetRangeInfo reports texture dimensions in Flags bits 7/8/9/12)")
