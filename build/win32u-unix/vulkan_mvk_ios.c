/*
 * MoltenVK bridge for win32u's Vulkan loader (madeira-doge, vulkan branch)
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 */

/* win32u's vulkan.c (compiled through vulkan_ios.c) reaches the host
 * Vulkan library with dlopen(SONAME_LIBVULKAN) + dlsym().  On iOS there is
 * no libvulkan: MoltenVK is statically linked into Madeira.app
 * (app/Madeira/libMoltenVK.a, the vulkan branch).  This file is the only
 * TU that includes the real Vulkan headers (Wine's wine/vulkan.h redefines
 * every type, so the two must never meet), and it hands out MoltenVK's
 * global entry points by name.
 *
 * Opt-in: the whole thing stays dormant unless the session environment
 * has MADEIRA_VULKAN=1 (game config `env.MADEIRA_VULKAN = 1`).  With it
 * unset the "dlopen" fails exactly as a Wine built without Vulkan, so
 * winevulkan's PE side answers VK_ERROR_INITIALIZATION_FAILED and games
 * that probe Vulkan fall back to D3D as they did with the old stand-in
 * vulkan-1.dll.  Nothing in the D3D11/D3D12 path is touched either way. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <vulkan/vulkan.h>

/* MoltenVK's global entry points, resolved by the static link. */
PFN_vkVoidFunction vkGetInstanceProcAddr( VkInstance instance, const char *name );
PFN_vkVoidFunction vkGetDeviceProcAddr( VkDevice device, const char *name );

static int madeira_vulkan_opted_in( void )
{
    /* read through a variable so the settings-catalog generator does not
     * turn this experiment into a Settings row */
    static const char key[] = "MADEIRA_VULKAN";
    static int opted = -1;
    if (opted < 0)
    {
        const char *e = getenv( key );
        opted = e && e[0] == '1' && !e[1];
    }
    return opted;
}

static char madeira_vk_handle_storage;

/* dlopen stand-in: a sentinel handle, or NULL when the experiment is off. */
void *madeira_vk_dlopen( const char *name, int mode )
{
    static int said;
    (void)mode;
    if (!madeira_vulkan_opted_in())
    {
        if (!said++)
            dprintf( 2, "[vulkan] madeira-doge: a program asked for Vulkan (%s); the MoltenVK path is OFF "
                        "(env.MADEIRA_VULKAN = 1 in the game's settings turns it on)\n", name ? name : "?" );
        return NULL;
    }
    if (!said++)
        dprintf( 2, "[vulkan] madeira-doge: MoltenVK (static) answers for %s (env.MADEIRA_VULKAN = 1)\n",
                 name ? name : "?" );
    return &madeira_vk_handle_storage;
}

/* ------------------------------------------------------------------------
 * Feature shim (MADEIRA_VULKAN_SPOOF, default on with MADEIRA_VULKAN=1;
 * MADEIRA_VULKAN_SPOOF=0 turns it off).
 *
 * KytyPS5's official Windows build requires seven features MoltenVK does not
 * have on Apple GPUs and refuses the device without them (build 532, 22:09
 * log: "Could not find suitable device: Apple A18 Pro GPU: colorWriteEnable,
 * image view minLod, depthClipEnable, shaderBufferInt64Atomics,
 * nullDescriptor, shaderCullDistance, depthBounds is not supported").  Its own
 * macOS build and MagnusPS5 (the iOS fork) treat them as optional: no depth
 * bounds test, static colour-write masks, default depth clipping.  This shim
 * does the same at the API boundary, below winevulkan:
 *   - feature queries report the seven as supported, and the device
 *     extension list also offers VK_EXT_color_write_enable,
 *     VK_EXT_image_view_min_lod and VK_EXT_depth_clip_enable;
 *   - vkCreateDevice drops the three extensions and clears the seven
 *     feature bits before MoltenVK sees them (it refuses unsupported ones);
 *   - graphics pipelines lose depthBoundsTestEnable and the DEPTH_BOUNDS /
 *     DEPTH_BOUNDS_TEST_ENABLE / COLOR_WRITE_ENABLE_EXT dynamic states;
 *     extension structs in pNext chains (colour-write, depth-clip, min-LOD)
 *     are left in place -- MoltenVK ignores sTypes it does not know;
 *   - vkCmdSetDepthBounds(TestEnable) and vkCmdSetColorWriteEnableEXT are
 *     no-ops.
 * Null descriptors, 64-bit buffer atomics and cull distances are only
 * claimed: a shader or descriptor update that really uses them can still
 * fail; the log says what was spoofed.  Structures are edited in place (they
 * are winevulkan's converted copies or the program's own, rebuilt per call). */

static int madeira_vk_spoof( void )
{
    static const char key[] = "MADEIRA_VULKAN_SPOOF";
    static int on = -1;
    if (on < 0)
    {
        const char *e = getenv( key );
        on = !(e && e[0] == '0' && !e[1]);
        dprintf( 2, "[vulkan] madeira-doge: feature shim %s (env.MADEIRA_VULKAN_SPOOF)\n", on ? "ON" : "off" );
    }
    return on;
}

static const char *const spoof_exts[] = { "VK_EXT_color_write_enable", "VK_EXT_image_view_min_lod",
                                          "VK_EXT_depth_clip_enable" };

static PFN_vkGetPhysicalDeviceFeatures real_GetPhysicalDeviceFeatures;
static PFN_vkGetPhysicalDeviceFeatures2 real_GetPhysicalDeviceFeatures2;
static PFN_vkGetPhysicalDeviceFeatures2 real_GetPhysicalDeviceFeatures2KHR;
static PFN_vkEnumerateDeviceExtensionProperties real_EnumerateDeviceExtensionProperties;
static PFN_vkCreateDevice real_CreateDevice;
static PFN_vkCreateGraphicsPipelines real_CreateGraphicsPipelines;

static void spoof_features( VkPhysicalDeviceFeatures *f )
{
    f->depthBounds = VK_TRUE;
    f->shaderCullDistance = VK_TRUE;
}

static void spoof_chain( void *pnext )
{
    VkBaseOutStructure *s;
    for (s = pnext; s; s = s->pNext)
    {
        switch ((int)s->sType)
        {
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES:
            ((VkPhysicalDeviceVulkan12Features *)s)->shaderBufferInt64Atomics = VK_TRUE; break;
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_ATOMIC_INT64_FEATURES:
            ((VkPhysicalDeviceShaderAtomicInt64Features *)s)->shaderBufferInt64Atomics = VK_TRUE; break;
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT:
            ((VkPhysicalDeviceRobustness2FeaturesEXT *)s)->nullDescriptor = VK_TRUE; break;
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_COLOR_WRITE_ENABLE_FEATURES_EXT:
            ((VkPhysicalDeviceColorWriteEnableFeaturesEXT *)s)->colorWriteEnable = VK_TRUE; break;
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_VIEW_MIN_LOD_FEATURES_EXT:
            ((VkPhysicalDeviceImageViewMinLodFeaturesEXT *)s)->minLod = VK_TRUE; break;
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DEPTH_CLIP_ENABLE_FEATURES_EXT:
            ((VkPhysicalDeviceDepthClipEnableFeaturesEXT *)s)->depthClipEnable = VK_TRUE; break;
        default: break;
        }
    }
}

static void unspoof_chain( const void *pnext )
{
    VkBaseOutStructure *s;
    for (s = (VkBaseOutStructure *)pnext; s; s = s->pNext)
    {
        switch ((int)s->sType)
        {
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2:
            ((VkPhysicalDeviceFeatures2 *)s)->features.depthBounds = VK_FALSE;
            ((VkPhysicalDeviceFeatures2 *)s)->features.shaderCullDistance = VK_FALSE;
            break;
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES:
            ((VkPhysicalDeviceVulkan12Features *)s)->shaderBufferInt64Atomics = VK_FALSE; break;
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_ATOMIC_INT64_FEATURES:
            ((VkPhysicalDeviceShaderAtomicInt64Features *)s)->shaderBufferInt64Atomics = VK_FALSE; break;
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT:
            ((VkPhysicalDeviceRobustness2FeaturesEXT *)s)->nullDescriptor = VK_FALSE; break;
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_COLOR_WRITE_ENABLE_FEATURES_EXT:
            ((VkPhysicalDeviceColorWriteEnableFeaturesEXT *)s)->colorWriteEnable = VK_FALSE; break;
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_VIEW_MIN_LOD_FEATURES_EXT:
            ((VkPhysicalDeviceImageViewMinLodFeaturesEXT *)s)->minLod = VK_FALSE; break;
        case VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DEPTH_CLIP_ENABLE_FEATURES_EXT:
            ((VkPhysicalDeviceDepthClipEnableFeaturesEXT *)s)->depthClipEnable = VK_FALSE; break;
        default: break;
        }
    }
}

static void VKAPI_CALL shim_GetPhysicalDeviceFeatures( VkPhysicalDevice pd, VkPhysicalDeviceFeatures *f )
{
    real_GetPhysicalDeviceFeatures( pd, f );
    spoof_features( f );
}

static void VKAPI_CALL shim_GetPhysicalDeviceFeatures2( VkPhysicalDevice pd, VkPhysicalDeviceFeatures2 *f )
{
    static int said;
    real_GetPhysicalDeviceFeatures2( pd, f );
    spoof_features( &f->features );
    spoof_chain( f->pNext );
    if (!said++)
        dprintf( 2, "[vulkan] madeira-doge: feature query answered with depthBounds, shaderCullDistance, "
                    "shaderBufferInt64Atomics, nullDescriptor, colorWriteEnable, minLod, depthClipEnable spoofed on\n" );
}

static void VKAPI_CALL shim_GetPhysicalDeviceFeatures2KHR( VkPhysicalDevice pd, VkPhysicalDeviceFeatures2 *f )
{
    real_GetPhysicalDeviceFeatures2KHR( pd, f );
    spoof_features( &f->features );
    spoof_chain( f->pNext );
}

static VkResult VKAPI_CALL shim_EnumerateDeviceExtensionProperties( VkPhysicalDevice pd, const char *layer,
                                                                     uint32_t *count, VkExtensionProperties *props )
{
    uint32_t n = 0, total, i, j, k;
    VkExtensionProperties *all;
    VkResult r;

    if (layer) return real_EnumerateDeviceExtensionProperties( pd, layer, count, props );
    if ((r = real_EnumerateDeviceExtensionProperties( pd, NULL, &n, NULL )) != VK_SUCCESS) return r;
    if (!(all = calloc( n + 3, sizeof(*all) ))) return VK_ERROR_OUT_OF_HOST_MEMORY;
    if ((r = real_EnumerateDeviceExtensionProperties( pd, NULL, &n, all )) < 0) { free( all ); return r; }
    total = n;
    for (k = 0; k < 3; k++)
    {
        for (i = 0; i < n; i++) if (!strcmp( all[i].extensionName, spoof_exts[k] )) break;
        if (i == n)
        {
            snprintf( all[total].extensionName, sizeof(all[total].extensionName), "%s", spoof_exts[k] );
            all[total++].specVersion = 1;
        }
    }
    if (!props) { *count = total; free( all ); return VK_SUCCESS; }
    j = *count < total ? *count : total;
    memcpy( props, all, j * sizeof(*props) );
    *count = j;
    free( all );
    return j < total ? VK_INCOMPLETE : VK_SUCCESS;
}

static VkResult VKAPI_CALL shim_CreateDevice( VkPhysicalDevice pd, const VkDeviceCreateInfo *ci,
                                              const VkAllocationCallbacks *alloc, VkDevice *dev )
{
    uint32_t i, k, kept = 0, dropped = 0;
    const char **names = (const char **)ci->ppEnabledExtensionNames;
    VkResult r;

    for (i = 0; i < ci->enabledExtensionCount; i++)
    {
        int drop = 0;
        for (k = 0; k < 3; k++) if (names[i] && !strcmp( names[i], spoof_exts[k] )) drop = 1;
        if (drop) { dropped++; continue; }
        names[kept++] = names[i];
    }
    ((VkDeviceCreateInfo *)ci)->enabledExtensionCount = kept;
    if (ci->pEnabledFeatures)
    {
        ((VkPhysicalDeviceFeatures *)ci->pEnabledFeatures)->depthBounds = VK_FALSE;
        ((VkPhysicalDeviceFeatures *)ci->pEnabledFeatures)->shaderCullDistance = VK_FALSE;
    }
    unspoof_chain( ci->pNext );
    r = real_CreateDevice( pd, ci, alloc, dev );
    dprintf( 2, "[vulkan] madeira-doge: vkCreateDevice with %u extension(s) (%u spoofed one(s) dropped), "
                "spoofed features cleared -> %d\n", kept, dropped, (int)r );
    return r;
}

static VkResult VKAPI_CALL shim_CreateGraphicsPipelines( VkDevice dev, VkPipelineCache cache, uint32_t n,
                                                         const VkGraphicsPipelineCreateInfo *ci,
                                                         const VkAllocationCallbacks *alloc, VkPipeline *out )
{
    static unsigned long long fixed;
    uint32_t i, j, kept;
    for (i = 0; i < n; i++)
    {
        const VkPipelineDepthStencilStateCreateInfo *ds = ci[i].pDepthStencilState;
        const VkPipelineDynamicStateCreateInfo *dy = ci[i].pDynamicState;
        if (ds && ds->depthBoundsTestEnable)
        {
            ((VkPipelineDepthStencilStateCreateInfo *)ds)->depthBoundsTestEnable = VK_FALSE;
            fixed++;
        }
        if (dy && dy->pDynamicStates)
        {
            VkDynamicState *st = (VkDynamicState *)dy->pDynamicStates;
            for (j = kept = 0; j < dy->dynamicStateCount; j++)
            {
                if (st[j] == VK_DYNAMIC_STATE_DEPTH_BOUNDS || st[j] == VK_DYNAMIC_STATE_DEPTH_BOUNDS_TEST_ENABLE ||
                    st[j] == VK_DYNAMIC_STATE_COLOR_WRITE_ENABLE_EXT)
                    continue;
                st[kept++] = st[j];
            }
            if (kept != dy->dynamicStateCount) fixed++;
            ((VkPipelineDynamicStateCreateInfo *)dy)->dynamicStateCount = kept;
        }
    }
    if (fixed && (fixed <= 4 || !(fixed % 1000)))
        dprintf( 2, "[vulkan] madeira-doge: %llu pipeline state(s) without depth bounds / colour-write enable so far\n", fixed );
    return real_CreateGraphicsPipelines( dev, cache, n, ci, alloc, out );
}

static void VKAPI_CALL shim_CmdSetDepthBounds( VkCommandBuffer cb, float lo, float hi ) { (void)cb; (void)lo; (void)hi; }
static void VKAPI_CALL shim_CmdSetDepthBoundsTestEnable( VkCommandBuffer cb, VkBool32 e ) { (void)cb; (void)e; }
static void VKAPI_CALL shim_CmdSetColorWriteEnableEXT( VkCommandBuffer cb, uint32_t n, const VkBool32 *e ) { (void)cb; (void)n; (void)e; }

/* Returns the shim for an intercepted name (fetching the real entry once), else NULL. */
static PFN_vkVoidFunction madeira_vk_intercept( const char *name, PFN_vkVoidFunction real )
{
    if (!name || !madeira_vk_spoof()) return NULL;
    if (!strcmp( name, "vkGetPhysicalDeviceFeatures" ))
    { if (!real_GetPhysicalDeviceFeatures) real_GetPhysicalDeviceFeatures = (void *)real;
      return real_GetPhysicalDeviceFeatures ? (PFN_vkVoidFunction)shim_GetPhysicalDeviceFeatures : NULL; }
    if (!strcmp( name, "vkGetPhysicalDeviceFeatures2" ))
    { if (!real_GetPhysicalDeviceFeatures2) real_GetPhysicalDeviceFeatures2 = (void *)real;
      return real_GetPhysicalDeviceFeatures2 ? (PFN_vkVoidFunction)shim_GetPhysicalDeviceFeatures2 : NULL; }
    if (!strcmp( name, "vkGetPhysicalDeviceFeatures2KHR" ))
    { if (!real_GetPhysicalDeviceFeatures2KHR) real_GetPhysicalDeviceFeatures2KHR = (void *)real;
      return real_GetPhysicalDeviceFeatures2KHR ? (PFN_vkVoidFunction)shim_GetPhysicalDeviceFeatures2KHR : NULL; }
    if (!strcmp( name, "vkEnumerateDeviceExtensionProperties" ))
    { if (!real_EnumerateDeviceExtensionProperties) real_EnumerateDeviceExtensionProperties = (void *)real;
      return real_EnumerateDeviceExtensionProperties ? (PFN_vkVoidFunction)shim_EnumerateDeviceExtensionProperties : NULL; }
    if (!strcmp( name, "vkCreateDevice" ))
    { if (!real_CreateDevice) real_CreateDevice = (void *)real;
      return real_CreateDevice ? (PFN_vkVoidFunction)shim_CreateDevice : NULL; }
    if (!strcmp( name, "vkCreateGraphicsPipelines" ))
    { if (!real_CreateGraphicsPipelines) real_CreateGraphicsPipelines = (void *)real;
      return real_CreateGraphicsPipelines ? (PFN_vkVoidFunction)shim_CreateGraphicsPipelines : NULL; }
    if (!strcmp( name, "vkCmdSetDepthBounds" )) return (PFN_vkVoidFunction)shim_CmdSetDepthBounds;
    if (!strcmp( name, "vkCmdSetDepthBoundsTestEnable" ) || !strcmp( name, "vkCmdSetDepthBoundsTestEnableEXT" ))
        return (PFN_vkVoidFunction)shim_CmdSetDepthBoundsTestEnable;
    if (!strcmp( name, "vkCmdSetColorWriteEnableEXT" )) return (PFN_vkVoidFunction)shim_CmdSetColorWriteEnableEXT;
    return NULL;
}

static PFN_vkVoidFunction VKAPI_CALL madeira_vk_GetDeviceProcAddr( VkDevice device, const char *name );

static PFN_vkVoidFunction VKAPI_CALL madeira_vk_GetInstanceProcAddr( VkInstance instance, const char *name )
{
    PFN_vkVoidFunction real, shim;
    if (name && !strcmp( name, "vkGetInstanceProcAddr" )) return (PFN_vkVoidFunction)madeira_vk_GetInstanceProcAddr;
    real = vkGetInstanceProcAddr( instance, name );
    if (name && !strcmp( name, "vkGetDeviceProcAddr" )) return real ? (PFN_vkVoidFunction)madeira_vk_GetDeviceProcAddr : NULL;
    if ((shim = madeira_vk_intercept( name, real ))) return shim;
    return real;
}

static PFN_vkVoidFunction VKAPI_CALL madeira_vk_GetDeviceProcAddr( VkDevice device, const char *name )
{
    PFN_vkVoidFunction real, shim;
    if (name && !strcmp( name, "vkGetDeviceProcAddr" )) return (PFN_vkVoidFunction)madeira_vk_GetDeviceProcAddr;
    real = vkGetDeviceProcAddr( device, name );
    if ((shim = madeira_vk_intercept( name, real ))) return shim;
    return real;
}

void *madeira_vk_dlsym( void *handle, const char *name )
{
    if (handle != &madeira_vk_handle_storage || !name) return NULL;
    if (!strcmp( name, "vkGetInstanceProcAddr" )) return (void *)madeira_vk_GetInstanceProcAddr;
    if (!strcmp( name, "vkGetDeviceProcAddr" )) return (void *)madeira_vk_GetDeviceProcAddr;
    return (void *)madeira_vk_GetInstanceProcAddr( NULL, name );
}

int madeira_vk_dlclose( void *handle )
{
    (void)handle;
    return 0;
}
