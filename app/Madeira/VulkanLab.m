// The Vulkan lab and the address-space probe (vulkan branch). See VulkanLab.h.
//
// MoltenVK is linked statically (libMoltenVK.a, fetched by CI from the
// pinned KhronosGroup/MoltenVK release), so the vk* entry points resolve
// directly; no loader, no ICD, no dylib in the bundle. The triangle shaders are
// hand-assembled SPIR-V (tools/spv-asm.py -> VulkanLabShaders.h), so the test
// exercises the same SPIR-V -> MSL path a game's shaders will take.

#import "VulkanLab.h"
#import <QuartzCore/CAMetalLayer.h>
#import <Metal/Metal.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <mach/mach_time.h>
#include <sys/mman.h>
#include <sys/sysctl.h>
#include <os/proc.h>
#include <mach/mach_error.h>
#include <errno.h>
#include <math.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define VK_USE_PLATFORM_METAL_EXT 1
#include <vulkan/vulkan.h>
#include "VulkanLabShaders.h"

static atomic_bool g_stop;

typedef void (^LogBlock)(NSString *_Nonnull);

static void L(LogBlock log, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
static void L(LogBlock log, const char *fmt, ...) {
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    log([NSString stringWithUTF8String:buf]);
}

static const char *vkres(VkResult r) {
    switch (r) {
    case VK_SUCCESS: return "VK_SUCCESS";
    case VK_NOT_READY: return "VK_NOT_READY";
    case VK_TIMEOUT: return "VK_TIMEOUT";
    case VK_SUBOPTIMAL_KHR: return "VK_SUBOPTIMAL_KHR";
    case VK_ERROR_OUT_OF_HOST_MEMORY: return "VK_ERROR_OUT_OF_HOST_MEMORY";
    case VK_ERROR_OUT_OF_DEVICE_MEMORY: return "VK_ERROR_OUT_OF_DEVICE_MEMORY";
    case VK_ERROR_INITIALIZATION_FAILED: return "VK_ERROR_INITIALIZATION_FAILED";
    case VK_ERROR_DEVICE_LOST: return "VK_ERROR_DEVICE_LOST";
    case VK_ERROR_LAYER_NOT_PRESENT: return "VK_ERROR_LAYER_NOT_PRESENT";
    case VK_ERROR_EXTENSION_NOT_PRESENT: return "VK_ERROR_EXTENSION_NOT_PRESENT";
    case VK_ERROR_FEATURE_NOT_PRESENT: return "VK_ERROR_FEATURE_NOT_PRESENT";
    case VK_ERROR_INCOMPATIBLE_DRIVER: return "VK_ERROR_INCOMPATIBLE_DRIVER";
    case VK_ERROR_SURFACE_LOST_KHR: return "VK_ERROR_SURFACE_LOST_KHR";
    case VK_ERROR_OUT_OF_DATE_KHR: return "VK_ERROR_OUT_OF_DATE_KHR";
    case VK_ERROR_INVALID_SHADER_NV: return "VK_ERROR_INVALID_SHADER_NV";
    case VK_ERROR_FORMAT_NOT_SUPPORTED: return "VK_ERROR_FORMAT_NOT_SUPPORTED";
    default: return "VkResult";
    }
}

#define CHECK(expr, what) do { VkResult _r = (expr); \
    if (_r != VK_SUCCESS) { L(log, "%s: %s (%d)", what, vkres(_r), (int)_r); goto fail; } } while (0)

static int has_ext(const VkExtensionProperties *ext, uint32_t n, const char *name) {
    for (uint32_t i = 0; i < n; i++) if (!strcmp(ext[i].extensionName, name)) return 1;
    return 0;
}

/// The device extensions the PS4 renderer (shadPS4/Funnel-arm, what LSX4
/// builds on) and KytyPS5 ask for. Required ones first; the rest are
/// optional there but each one missing costs a fallback.
static const char *const kWantedDeviceExts[] = {
    "VK_KHR_swapchain", "VK_KHR_portability_subset",
    "VK_KHR_dynamic_rendering", "VK_KHR_synchronization2", "VK_KHR_timeline_semaphore",
    "VK_KHR_maintenance1", "VK_KHR_maintenance2", "VK_KHR_maintenance3", "VK_KHR_maintenance4",
    "VK_KHR_maintenance5", "VK_KHR_buffer_device_address", "VK_KHR_shader_float16_int8",
    "VK_KHR_16bit_storage", "VK_KHR_8bit_storage", "VK_KHR_shader_draw_parameters",
    "VK_KHR_push_descriptor", "VK_KHR_create_renderpass2", "VK_KHR_depth_stencil_resolve",
    "VK_KHR_imageless_framebuffer", "VK_KHR_fragment_shading_rate", "VK_KHR_workgroup_memory_explicit_layout",
    "VK_EXT_descriptor_indexing", "VK_EXT_extended_dynamic_state", "VK_EXT_extended_dynamic_state2",
    "VK_EXT_extended_dynamic_state3", "VK_EXT_vertex_input_dynamic_state", "VK_EXT_custom_border_color",
    "VK_EXT_border_color_swizzle", "VK_EXT_depth_clip_control", "VK_EXT_depth_range_unrestricted",
    "VK_EXT_color_write_enable", "VK_EXT_robustness2", "VK_EXT_host_query_reset",
    "VK_EXT_shader_demote_to_helper_invocation", "VK_EXT_primitive_topology_list_restart",
    "VK_EXT_provoking_vertex", "VK_EXT_fragment_shader_interlock", "VK_EXT_shader_stencil_export",
    "VK_EXT_index_type_uint8", "VK_EXT_texel_buffer_alignment", "VK_EXT_memory_budget",
    "VK_EXT_external_memory_host", "VK_EXT_conservative_rasterization", "VK_EXT_line_rasterization",
    "VK_EXT_image_view_min_lod", "VK_EXT_legacy_vertex_attributes", "VK_EXT_shader_object",
    "VK_EXT_transform_feedback", "VK_EXT_shader_atomic_float", "VK_EXT_shader_atomic_float2",
    "VK_AMD_shader_image_load_store_lod", "VK_AMD_gcn_shader", "VK_AMD_shader_trinary_minmax",
};

typedef struct {
    float x, y, r, g, b;
} Vertex;

/// Pure C (no ObjC locals) so the goto-based cleanup is legal under ARC.
static void lab_run(void *metal_layer, LogBlock log) {
    VkInstance instance = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkSurfaceKHR surface = VK_NULL_HANDLE;
    VkSwapchainKHR swapchain = VK_NULL_HANDLE;
    VkImageView views[8] = {0};
    VkFramebuffer fbs[8] = {0};
    VkRenderPass rp = VK_NULL_HANDLE;
    VkShaderModule vs = VK_NULL_HANDLE, fs = VK_NULL_HANDLE;
    VkPipelineLayout layout = VK_NULL_HANDLE;
    VkPipeline pipeline = VK_NULL_HANDLE;
    VkBuffer vb = VK_NULL_HANDLE;
    VkDeviceMemory vbmem = VK_NULL_HANDLE, bigmem = VK_NULL_HANDLE;
    VkCommandPool pool = VK_NULL_HANDLE;
    VkSemaphore semAcquire = VK_NULL_HANDLE, semRender = VK_NULL_HANDLE;
    VkFence fence = VK_NULL_HANDLE;
    VkExtensionProperties *iexts = NULL, *dexts = NULL;
    VkSurfaceFormatKHR *formats = NULL;
    VkPresentModeKHR *modes = NULL;
    VkImage images[8];
    VkCommandBuffer cmds[8];
    uint32_t nimages = 0, nviews = 0, nfbs = 0, ncmds = 0;
    Vertex *mapped = NULL;

    // 1. The instance.
    uint32_t apiver = VK_API_VERSION_1_0;
    vkEnumerateInstanceVersion(&apiver);
    L(log, "MoltenVK statically linked; instance API %u.%u.%u, header %u",
      VK_VERSION_MAJOR(apiver), VK_VERSION_MINOR(apiver), VK_VERSION_PATCH(apiver), VK_HEADER_VERSION);

    uint32_t niexts = 0;
    CHECK(vkEnumerateInstanceExtensionProperties(NULL, &niexts, NULL), "vkEnumerateInstanceExtensionProperties");
    iexts = calloc(niexts, sizeof *iexts);
    CHECK(vkEnumerateInstanceExtensionProperties(NULL, &niexts, iexts), "vkEnumerateInstanceExtensionProperties");
    int have_portability = has_ext(iexts, niexts, "VK_KHR_portability_enumeration");
    int have_pdp2 = has_ext(iexts, niexts, "VK_KHR_get_physical_device_properties2");
    L(log, "instance extensions: %u (surface %d, metal_surface %d, portability_enumeration %d, physical_device_properties2 %d)",
      niexts, has_ext(iexts, niexts, "VK_KHR_surface"), has_ext(iexts, niexts, "VK_EXT_metal_surface"),
      have_portability, have_pdp2);
    if (!has_ext(iexts, niexts, "VK_EXT_metal_surface")) { L(log, "no VK_EXT_metal_surface: cannot present"); goto fail; }

    const char *ienabled[4];
    uint32_t nienabled = 0;
    ienabled[nienabled++] = "VK_KHR_surface";
    ienabled[nienabled++] = "VK_EXT_metal_surface";
    if (have_portability) ienabled[nienabled++] = "VK_KHR_portability_enumeration";
    if (have_pdp2) ienabled[nienabled++] = "VK_KHR_get_physical_device_properties2";

    VkApplicationInfo app = { .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .pApplicationName = "Madeira Vulkan lab",
                              .applicationVersion = 1, .pEngineName = "Madeira", .engineVersion = 1,
                              .apiVersion = apiver };
    VkInstanceCreateInfo ici = { .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app,
                                 .flags = have_portability ? VK_INSTANCE_CREATE_ENUMERATE_PORTABILITY_BIT_KHR : 0,
                                 .enabledExtensionCount = nienabled, .ppEnabledExtensionNames = ienabled };
    CHECK(vkCreateInstance(&ici, NULL, &instance), "vkCreateInstance");
    L(log, "instance created");

    // 2. The physical device.
    uint32_t npd = 0;
    CHECK(vkEnumeratePhysicalDevices(instance, &npd, NULL), "vkEnumeratePhysicalDevices");
    if (npd == 0) { L(log, "no physical device"); goto fail; }
    VkPhysicalDevice pds[4];
    if (npd > 4) npd = 4;
    CHECK(vkEnumeratePhysicalDevices(instance, &npd, pds), "vkEnumeratePhysicalDevices");
    VkPhysicalDevice pd = pds[0];

    VkPhysicalDeviceProperties props;
    vkGetPhysicalDeviceProperties(pd, &props);
    L(log, "device: %s (type %d, vendor 0x%x), API %u.%u.%u, driver (MoltenVK) %u.%u.%u", props.deviceName,
      (int)props.deviceType, props.vendorID, VK_VERSION_MAJOR(props.apiVersion), VK_VERSION_MINOR(props.apiVersion),
      VK_VERSION_PATCH(props.apiVersion), VK_VERSION_MAJOR(props.driverVersion), VK_VERSION_MINOR(props.driverVersion),
      VK_VERSION_PATCH(props.driverVersion));
    const VkPhysicalDeviceLimits *lim = &props.limits;
    L(log, "limits: image2D %u, image3D %u, allocations %u, bound descriptor sets %u, push constants %u B, sampled images/stage %u, storage buffers/stage %u",
      lim->maxImageDimension2D, lim->maxImageDimension3D, lim->maxMemoryAllocationCount, lim->maxBoundDescriptorSets,
      lim->maxPushConstantsSize, lim->maxPerStageDescriptorSampledImages, lim->maxPerStageDescriptorStorageBuffers);
    L(log, "limits: uniform range %u, storage range %u, ubo align %llu, ssbo align %llu, texel align %llu, compute workgroup %u x %u x %u (%u invocations), timestamp period %.3f ns, viewports %u, vertex attrs %u, color attachments %u",
      lim->maxUniformBufferRange, lim->maxStorageBufferRange, (unsigned long long)lim->minUniformBufferOffsetAlignment,
      (unsigned long long)lim->minStorageBufferOffsetAlignment, (unsigned long long)lim->minTexelBufferOffsetAlignment,
      lim->maxComputeWorkGroupSize[0], lim->maxComputeWorkGroupSize[1], lim->maxComputeWorkGroupSize[2],
      lim->maxComputeWorkGroupInvocations, lim->timestampPeriod, lim->maxViewports, lim->maxVertexInputAttributes,
      lim->maxColorAttachments);

    VkPhysicalDeviceFeatures feat;
    vkGetPhysicalDeviceFeatures(pd, &feat);
    L(log, "features: int64 %d int16 %d float64 %d geometry %d tessellation %d fragmentStoresAndAtomics %d vertexStoresAndAtomics %d logicOp %d dualSrcBlend %d independentBlend %d depthBounds %d depthClamp %d wideLines %d multiViewport %d anisotropy %d imageCubeArray %d textureCompressionBC %d shaderStorageImageWriteWithoutFormat %d shaderStorageImageReadWithoutFormat %d clip/cull distance %d/%d multiDrawIndirect %d drawIndirectFirstInstance %d robustBufferAccess %d",
      feat.shaderInt64, feat.shaderInt16, feat.shaderFloat64, feat.geometryShader, feat.tessellationShader,
      feat.fragmentStoresAndAtomics, feat.vertexPipelineStoresAndAtomics, feat.logicOp, feat.dualSrcBlend,
      feat.independentBlend, feat.depthBounds, feat.depthClamp, feat.wideLines, feat.multiViewport,
      feat.samplerAnisotropy, feat.imageCubeArray, feat.textureCompressionBC,
      feat.shaderStorageImageWriteWithoutFormat, feat.shaderStorageImageReadWithoutFormat, feat.shaderClipDistance,
      feat.shaderCullDistance, feat.multiDrawIndirect, feat.drawIndirectFirstInstance, feat.robustBufferAccess);

    VkPhysicalDeviceMemoryProperties mem;
    vkGetPhysicalDeviceMemoryProperties(pd, &mem);
    for (uint32_t i = 0; i < mem.memoryHeapCount; i++)
        L(log, "memory heap %u: %.1f GB%s", i, (double)mem.memoryHeaps[i].size / (1024.0 * 1024 * 1024),
          (mem.memoryHeaps[i].flags & VK_MEMORY_HEAP_DEVICE_LOCAL_BIT) ? " device-local" : "");
    for (uint32_t i = 0; i < mem.memoryTypeCount; i++)
        L(log, "memory type %u: heap %u flags 0x%x", i, mem.memoryTypes[i].heapIndex, mem.memoryTypes[i].propertyFlags);

    uint32_t nqf = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(pd, &nqf, NULL);
    VkQueueFamilyProperties qf[8];
    if (nqf > 8) nqf = 8;
    vkGetPhysicalDeviceQueueFamilyProperties(pd, &nqf, qf);
    uint32_t gfx = UINT32_MAX;
    for (uint32_t i = 0; i < nqf; i++) {
        L(log, "queue family %u: flags 0x%x, %u queues, timestamp bits %u", i, qf[i].queueFlags, qf[i].queueCount,
          qf[i].timestampValidBits);
        if (gfx == UINT32_MAX && (qf[i].queueFlags & VK_QUEUE_GRAPHICS_BIT)) gfx = i;
    }
    if (gfx == UINT32_MAX) { L(log, "no graphics queue"); goto fail; }

    uint32_t ndexts = 0;
    CHECK(vkEnumerateDeviceExtensionProperties(pd, NULL, &ndexts, NULL), "vkEnumerateDeviceExtensionProperties");
    dexts = calloc(ndexts, sizeof *dexts);
    CHECK(vkEnumerateDeviceExtensionProperties(pd, NULL, &ndexts, dexts), "vkEnumerateDeviceExtensionProperties");
    {
        char have[2048] = "", miss[2048] = "";
        for (size_t i = 0; i < sizeof kWantedDeviceExts / sizeof *kWantedDeviceExts; i++) {
            const char *n = kWantedDeviceExts[i] + 3;   // drop the VK_ prefix to fit
            char *dst = has_ext(dexts, ndexts, kWantedDeviceExts[i]) ? have : miss;
            size_t len = strlen(dst);
            if (len + strlen(n) + 2 < 2048) { if (len) dst[len++] = ' '; strcpy(dst + len, n); }
        }
        L(log, "device extensions: %u total", ndexts);
        L(log, "wanted, present: %s", have);
        L(log, "wanted, missing: %s", miss[0] ? miss : "(none)");
    }
    int have_subset = has_ext(dexts, ndexts, "VK_KHR_portability_subset");
    if (!has_ext(dexts, ndexts, "VK_KHR_swapchain")) { L(log, "no VK_KHR_swapchain"); goto fail; }

    // 3. The device and its queue.
    float prio = 1.0f;
    VkDeviceQueueCreateInfo qci = { .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = gfx,
                                    .queueCount = 1, .pQueuePriorities = &prio };
    const char *denabled[2] = { "VK_KHR_swapchain", "VK_KHR_portability_subset" };
    VkDeviceCreateInfo dci = { .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1,
                               .pQueueCreateInfos = &qci, .enabledExtensionCount = have_subset ? 2u : 1u,
                               .ppEnabledExtensionNames = denabled };
    CHECK(vkCreateDevice(pd, &dci, NULL, &device), "vkCreateDevice");
    VkQueue queue;
    vkGetDeviceQueue(device, gfx, 0, &queue);
    L(log, "device created (queue family %u)", gfx);

    // A device-local allocation of the size a game's VRAM pool starts at.
    {
        uint32_t type = UINT32_MAX;
        for (uint32_t i = 0; i < mem.memoryTypeCount; i++)
            if (mem.memoryTypes[i].propertyFlags & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT) { type = i; break; }
        if (type != UINT32_MAX) {
            VkMemoryAllocateInfo mai = { .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                                         .allocationSize = 256ull << 20, .memoryTypeIndex = type };
            VkResult r = vkAllocateMemory(device, &mai, NULL, &bigmem);
            L(log, "256 MB device-local allocation: %s", vkres(r));
            if (r == VK_SUCCESS) { vkFreeMemory(device, bigmem, NULL); bigmem = VK_NULL_HANDLE; }
        }
    }

    // 4. The surface on the sheet's CAMetalLayer.
    VkMetalSurfaceCreateInfoEXT sci = { .sType = VK_STRUCTURE_TYPE_METAL_SURFACE_CREATE_INFO_EXT, .pLayer = (__bridge const CAMetalLayer *)metal_layer };
    CHECK(vkCreateMetalSurfaceEXT(instance, &sci, NULL, &surface), "vkCreateMetalSurfaceEXT");
    VkBool32 supported = VK_FALSE;
    CHECK(vkGetPhysicalDeviceSurfaceSupportKHR(pd, gfx, surface, &supported), "vkGetPhysicalDeviceSurfaceSupportKHR");
    if (!supported) { L(log, "surface not supported on the graphics queue"); goto fail; }
    VkSurfaceCapabilitiesKHR caps;
    CHECK(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(pd, surface, &caps), "vkGetPhysicalDeviceSurfaceCapabilitiesKHR");
    uint32_t nformats = 0, nmodes = 0;
    CHECK(vkGetPhysicalDeviceSurfaceFormatsKHR(pd, surface, &nformats, NULL), "vkGetPhysicalDeviceSurfaceFormatsKHR");
    formats = calloc(nformats, sizeof *formats);
    CHECK(vkGetPhysicalDeviceSurfaceFormatsKHR(pd, surface, &nformats, formats), "vkGetPhysicalDeviceSurfaceFormatsKHR");
    CHECK(vkGetPhysicalDeviceSurfacePresentModesKHR(pd, surface, &nmodes, NULL), "vkGetPhysicalDeviceSurfacePresentModesKHR");
    modes = calloc(nmodes, sizeof *modes);
    CHECK(vkGetPhysicalDeviceSurfacePresentModesKHR(pd, surface, &nmodes, modes), "vkGetPhysicalDeviceSurfacePresentModesKHR");
    {
        char m[128] = "";
        for (uint32_t i = 0; i < nmodes; i++) {
            const char *n = modes[i] == VK_PRESENT_MODE_FIFO_KHR ? "fifo" : modes[i] == VK_PRESENT_MODE_IMMEDIATE_KHR ? "immediate"
                          : modes[i] == VK_PRESENT_MODE_MAILBOX_KHR ? "mailbox" : modes[i] == VK_PRESENT_MODE_FIFO_RELAXED_KHR ? "fifo-relaxed" : "other";
            if (strlen(m) + strlen(n) + 2 < sizeof m) { if (m[0]) strcat(m, " "); strcat(m, n); }
        }
        L(log, "surface: extent %ux%u, images %u..%u, %u formats (first 0x%x), present modes: %s", caps.currentExtent.width,
          caps.currentExtent.height, caps.minImageCount, caps.maxImageCount, nformats, nformats ? formats[0].format : 0, m);
    }
    VkFormat fmt = VK_FORMAT_B8G8R8A8_UNORM;
    VkColorSpaceKHR cs = VK_COLOR_SPACE_SRGB_NONLINEAR_KHR;
    int fmt_ok = 0;
    for (uint32_t i = 0; i < nformats; i++) if (formats[i].format == fmt) { cs = formats[i].colorSpace; fmt_ok = 1; }
    if (!fmt_ok && nformats) { fmt = formats[0].format; cs = formats[0].colorSpace; }
    VkExtent2D extent = caps.currentExtent;
    if (extent.width == 0 || extent.width == UINT32_MAX) {
        CGSize ds = ((__bridge CAMetalLayer *)metal_layer).drawableSize;
        extent.width = (uint32_t)ds.width; extent.height = (uint32_t)ds.height;
    }
    if (extent.width == 0 || extent.height == 0) { L(log, "surface has no size yet"); goto fail; }

    // 5. The swapchain and its views.
    uint32_t want = caps.minImageCount + 1;
    if (caps.maxImageCount && want > caps.maxImageCount) want = caps.maxImageCount;
    if (want > 8) want = 8;
    VkSwapchainCreateInfoKHR swci = { .sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR, .surface = surface,
                                      .minImageCount = want, .imageFormat = fmt, .imageColorSpace = cs,
                                      .imageExtent = extent, .imageArrayLayers = 1,
                                      .imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT,
                                      .imageSharingMode = VK_SHARING_MODE_EXCLUSIVE,
                                      .preTransform = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR,
                                      .compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR,
                                      .presentMode = VK_PRESENT_MODE_FIFO_KHR, .clipped = VK_TRUE };
    CHECK(vkCreateSwapchainKHR(device, &swci, NULL, &swapchain), "vkCreateSwapchainKHR");
    CHECK(vkGetSwapchainImagesKHR(device, swapchain, &nimages, NULL), "vkGetSwapchainImagesKHR");
    if (nimages > 8) nimages = 8;
    CHECK(vkGetSwapchainImagesKHR(device, swapchain, &nimages, images), "vkGetSwapchainImagesKHR");
    L(log, "swapchain: %u images, %ux%u, format 0x%x", nimages, extent.width, extent.height, fmt);

    VkAttachmentDescription att = { .format = fmt, .samples = VK_SAMPLE_COUNT_1_BIT,
                                    .loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp = VK_ATTACHMENT_STORE_OP_STORE,
                                    .stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE, .stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE,
                                    .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED, .finalLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR };
    VkAttachmentReference ref = { .attachment = 0, .layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL };
    VkSubpassDescription sub = { .pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS, .colorAttachmentCount = 1, .pColorAttachments = &ref };
    VkSubpassDependency dep = { .srcSubpass = VK_SUBPASS_EXTERNAL, .dstSubpass = 0,
                                .srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
                                .dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
                                .srcAccessMask = 0, .dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT };
    VkRenderPassCreateInfo rpci = { .sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO, .attachmentCount = 1, .pAttachments = &att,
                                    .subpassCount = 1, .pSubpasses = &sub, .dependencyCount = 1, .pDependencies = &dep };
    CHECK(vkCreateRenderPass(device, &rpci, NULL, &rp), "vkCreateRenderPass");

    for (uint32_t i = 0; i < nimages; i++) {
        VkImageViewCreateInfo ivci = { .sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = images[i],
                                       .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = fmt,
                                       .subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 } };
        CHECK(vkCreateImageView(device, &ivci, NULL, &views[i]), "vkCreateImageView");
        nviews++;
        VkFramebufferCreateInfo fbci = { .sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO, .renderPass = rp,
                                         .attachmentCount = 1, .pAttachments = &views[i], .width = extent.width,
                                         .height = extent.height, .layers = 1 };
        CHECK(vkCreateFramebuffer(device, &fbci, NULL, &fbs[i]), "vkCreateFramebuffer");
        nfbs++;
    }

    // 6. The pipeline: hand-assembled SPIR-V through MoltenVK's SPIR-V -> MSL path.
    VkShaderModuleCreateInfo vsci = { .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof kVulkanLabVS, .pCode = kVulkanLabVS };
    VkShaderModuleCreateInfo fsci = { .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof kVulkanLabFS, .pCode = kVulkanLabFS };
    CHECK(vkCreateShaderModule(device, &vsci, NULL, &vs), "vkCreateShaderModule(vertex)");
    CHECK(vkCreateShaderModule(device, &fsci, NULL, &fs), "vkCreateShaderModule(fragment)");
    VkPipelineShaderStageCreateInfo stages[2] = {
        { .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_VERTEX_BIT, .module = vs, .pName = "main" },
        { .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_FRAGMENT_BIT, .module = fs, .pName = "main" },
    };
    VkVertexInputBindingDescription bind = { .binding = 0, .stride = sizeof(Vertex), .inputRate = VK_VERTEX_INPUT_RATE_VERTEX };
    VkVertexInputAttributeDescription attrs[2] = {
        { .location = 0, .binding = 0, .format = VK_FORMAT_R32G32_SFLOAT, .offset = 0 },
        { .location = 1, .binding = 0, .format = VK_FORMAT_R32G32B32_SFLOAT, .offset = 8 },
    };
    VkPipelineVertexInputStateCreateInfo vi = { .sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO,
                                                .vertexBindingDescriptionCount = 1, .pVertexBindingDescriptions = &bind,
                                                .vertexAttributeDescriptionCount = 2, .pVertexAttributeDescriptions = attrs };
    VkPipelineInputAssemblyStateCreateInfo ia = { .sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,
                                                  .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST };
    VkViewport vp = { 0, 0, (float)extent.width, (float)extent.height, 0, 1 };
    VkRect2D sc = { { 0, 0 }, extent };
    VkPipelineViewportStateCreateInfo vps = { .sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO,
                                              .viewportCount = 1, .pViewports = &vp, .scissorCount = 1, .pScissors = &sc };
    VkPipelineRasterizationStateCreateInfo rs = { .sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,
                                                  .polygonMode = VK_POLYGON_MODE_FILL, .cullMode = VK_CULL_MODE_NONE,
                                                  .frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE, .lineWidth = 1.0f };
    VkPipelineMultisampleStateCreateInfo ms = { .sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,
                                                .rasterizationSamples = VK_SAMPLE_COUNT_1_BIT };
    VkPipelineColorBlendAttachmentState cba = { .colorWriteMask = 0xf };
    VkPipelineColorBlendStateCreateInfo cb = { .sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
                                               .attachmentCount = 1, .pAttachments = &cba };
    VkPipelineLayoutCreateInfo plci = { .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO };
    CHECK(vkCreatePipelineLayout(device, &plci, NULL, &layout), "vkCreatePipelineLayout");
    VkGraphicsPipelineCreateInfo gpci = { .sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, .stageCount = 2, .pStages = stages,
                                          .pVertexInputState = &vi, .pInputAssemblyState = &ia, .pViewportState = &vps,
                                          .pRasterizationState = &rs, .pMultisampleState = &ms, .pColorBlendState = &cb,
                                          .layout = layout, .renderPass = rp, .subpass = 0 };
    uint64_t t0 = mach_absolute_time();
    CHECK(vkCreateGraphicsPipelines(device, VK_NULL_HANDLE, 1, &gpci, NULL, &pipeline), "vkCreateGraphicsPipelines");
    {
        mach_timebase_info_data_t tb; mach_timebase_info(&tb);
        L(log, "pipeline created (SPIR-V -> MSL -> Metal) in %.1f ms",
          (double)(mach_absolute_time() - t0) * tb.numer / tb.denom / 1e6);
    }

    // 7. The vertex buffer, host-visible and mapped for the whole run.
    VkBufferCreateInfo bci = { .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = sizeof(Vertex) * 3,
                               .usage = VK_BUFFER_USAGE_VERTEX_BUFFER_BIT, .sharingMode = VK_SHARING_MODE_EXCLUSIVE };
    CHECK(vkCreateBuffer(device, &bci, NULL, &vb), "vkCreateBuffer");
    VkMemoryRequirements req;
    vkGetBufferMemoryRequirements(device, vb, &req);
    uint32_t htype = UINT32_MAX;
    for (uint32_t i = 0; i < mem.memoryTypeCount; i++) {
        VkMemoryPropertyFlags f = mem.memoryTypes[i].propertyFlags;
        if ((req.memoryTypeBits & (1u << i)) && (f & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT) && (f & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) { htype = i; break; }
    }
    if (htype == UINT32_MAX) { L(log, "no host-visible coherent memory type"); goto fail; }
    VkMemoryAllocateInfo vmai = { .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = req.size, .memoryTypeIndex = htype };
    CHECK(vkAllocateMemory(device, &vmai, NULL, &vbmem), "vkAllocateMemory(vertex)");
    CHECK(vkBindBufferMemory(device, vb, vbmem, 0), "vkBindBufferMemory");
    CHECK(vkMapMemory(device, vbmem, 0, VK_WHOLE_SIZE, 0, (void **)&mapped), "vkMapMemory");

    // 8. Command buffers, one per swapchain image, re-recorded each frame.
    VkCommandPoolCreateInfo cpci = { .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
                                     .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, .queueFamilyIndex = gfx };
    CHECK(vkCreateCommandPool(device, &cpci, NULL, &pool), "vkCreateCommandPool");
    VkCommandBufferAllocateInfo cbai = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = pool,
                                         .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = nimages };
    CHECK(vkAllocateCommandBuffers(device, &cbai, cmds), "vkAllocateCommandBuffers");
    ncmds = nimages;
    VkSemaphoreCreateInfo semci = { .sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO };
    CHECK(vkCreateSemaphore(device, &semci, NULL, &semAcquire), "vkCreateSemaphore");
    CHECK(vkCreateSemaphore(device, &semci, NULL, &semRender), "vkCreateSemaphore");
    VkFenceCreateInfo fci = { .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, .flags = VK_FENCE_CREATE_SIGNALED_BIT };
    CHECK(vkCreateFence(device, &fci, NULL, &fence), "vkCreateFence");

    // 9. Draw for about two seconds: a triangle whose colours cycle, so a stuck
    // frame is visible to the eye as well as in the numbers.
    mach_timebase_info_data_t tb; mach_timebase_info(&tb);
    uint64_t start = mach_absolute_time(), last = start;
    double worst_ms = 0;
    uint32_t frames = 0;
    for (;;) {
        if (atomic_load(&g_stop)) break;
        double elapsed = (double)(mach_absolute_time() - start) * tb.numer / tb.denom / 1e9;
        if (elapsed > 2.5 || frames >= 600) break;

        CHECK(vkWaitForFences(device, 1, &fence, VK_TRUE, 1000000000ull), "vkWaitForFences");
        CHECK(vkResetFences(device, 1, &fence), "vkResetFences");

        float h = (float)elapsed;   // hue phase
        Vertex tri[3] = {
            { 0.0f, -0.6f, 0.5f + 0.5f * sinf(h * 2.0f),        0.5f + 0.5f * sinf(h * 2.0f + 2.1f), 0.5f + 0.5f * sinf(h * 2.0f + 4.2f) },
            { 0.6f,  0.6f, 0.5f + 0.5f * sinf(h * 2.0f + 2.1f), 0.5f + 0.5f * sinf(h * 2.0f + 4.2f), 0.5f + 0.5f * sinf(h * 2.0f) },
            { -0.6f, 0.6f, 0.5f + 0.5f * sinf(h * 2.0f + 4.2f), 0.5f + 0.5f * sinf(h * 2.0f),        0.5f + 0.5f * sinf(h * 2.0f + 2.1f) },
        };
        memcpy(mapped, tri, sizeof tri);

        uint32_t idx = 0;
        VkResult ar = vkAcquireNextImageKHR(device, swapchain, 1000000000ull, semAcquire, VK_NULL_HANDLE, &idx);
        if (ar == VK_ERROR_OUT_OF_DATE_KHR) { L(log, "swapchain out of date after %u frames", frames); break; }
        if (ar != VK_SUCCESS && ar != VK_SUBOPTIMAL_KHR) { L(log, "vkAcquireNextImageKHR: %s", vkres(ar)); goto fail; }

        VkCommandBuffer cmd = cmds[idx];
        VkCommandBufferBeginInfo bi = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT };
        CHECK(vkResetCommandBuffer(cmd, 0), "vkResetCommandBuffer");
        CHECK(vkBeginCommandBuffer(cmd, &bi), "vkBeginCommandBuffer");
        VkClearValue clear = { .color = { { 0.05f, 0.05f, 0.15f, 1.0f } } };
        VkRenderPassBeginInfo rbi = { .sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, .renderPass = rp, .framebuffer = fbs[idx],
                                      .renderArea = { { 0, 0 }, extent }, .clearValueCount = 1, .pClearValues = &clear };
        vkCmdBeginRenderPass(cmd, &rbi, VK_SUBPASS_CONTENTS_INLINE);
        vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline);
        VkDeviceSize off = 0;
        vkCmdBindVertexBuffers(cmd, 0, 1, &vb, &off);
        vkCmdDraw(cmd, 3, 1, 0, 0);
        vkCmdEndRenderPass(cmd);
        CHECK(vkEndCommandBuffer(cmd), "vkEndCommandBuffer");

        VkPipelineStageFlags wait = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
        VkSubmitInfo si = { .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .waitSemaphoreCount = 1, .pWaitSemaphores = &semAcquire,
                            .pWaitDstStageMask = &wait, .commandBufferCount = 1, .pCommandBuffers = &cmd,
                            .signalSemaphoreCount = 1, .pSignalSemaphores = &semRender };
        CHECK(vkQueueSubmit(queue, 1, &si, fence), "vkQueueSubmit");
        VkPresentInfoKHR pi = { .sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, .waitSemaphoreCount = 1, .pWaitSemaphores = &semRender,
                                .swapchainCount = 1, .pSwapchains = &swapchain, .pImageIndices = &idx };
        VkResult pr = vkQueuePresentKHR(queue, &pi);
        if (pr == VK_ERROR_OUT_OF_DATE_KHR) { L(log, "present: out of date after %u frames", frames); break; }
        if (pr != VK_SUCCESS && pr != VK_SUBOPTIMAL_KHR) { L(log, "vkQueuePresentKHR: %s", vkres(pr)); goto fail; }

        uint64_t now = mach_absolute_time();
        double ms = (double)(now - last) * tb.numer / tb.denom / 1e6;
        if (frames > 2 && ms > worst_ms) worst_ms = ms;
        last = now;
        frames++;
    }
    vkQueueWaitIdle(queue);
    {
        double total = (double)(mach_absolute_time() - start) * tb.numer / tb.denom / 1e9;
        L(log, "RESULT: %u frames in %.2f s = %.1f fps (worst frame %.1f ms), %ux%u, FIFO", frames, total,
          total > 0 ? frames / total : 0.0, worst_ms, extent.width, extent.height);
        L(log, "MoltenVK works inside Madeira on this device: instance, device, surface, swapchain, SPIR-V pipeline, present");
    }
    goto cleanup;

fail:
    L(log, "FAILED (see the line above)");
cleanup:
    if (device) vkDeviceWaitIdle(device);
    if (mapped) vkUnmapMemory(device, vbmem);
    if (fence) vkDestroyFence(device, fence, NULL);
    if (semRender) vkDestroySemaphore(device, semRender, NULL);
    if (semAcquire) vkDestroySemaphore(device, semAcquire, NULL);
    if (ncmds) vkFreeCommandBuffers(device, pool, ncmds, cmds);
    if (pool) vkDestroyCommandPool(device, pool, NULL);
    if (vb) vkDestroyBuffer(device, vb, NULL);
    if (vbmem) vkFreeMemory(device, vbmem, NULL);
    if (bigmem) vkFreeMemory(device, bigmem, NULL);
    if (pipeline) vkDestroyPipeline(device, pipeline, NULL);
    if (layout) vkDestroyPipelineLayout(device, layout, NULL);
    if (fs) vkDestroyShaderModule(device, fs, NULL);
    if (vs) vkDestroyShaderModule(device, vs, NULL);
    for (uint32_t i = 0; i < nfbs; i++) vkDestroyFramebuffer(device, fbs[i], NULL);
    for (uint32_t i = 0; i < nviews; i++) vkDestroyImageView(device, views[i], NULL);
    if (rp) vkDestroyRenderPass(device, rp, NULL);
    if (swapchain) vkDestroySwapchainKHR(device, swapchain, NULL);
    if (device) vkDestroyDevice(device, NULL);
    if (surface) vkDestroySurfaceKHR(instance, surface, NULL);
    if (instance) vkDestroyInstance(instance, NULL);
    free(iexts); free(dexts); free(formats); free(modes);
    L(log, "lab finished, everything released");
}

void MadeiraVulkanLabRun(CALayer *layer, void (^log)(NSString *), void (^done)(void)) {
    atomic_store(&g_stop, false);
    void *raw = (__bridge_retained void *)layer;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        lab_run(raw, log);
        CFRelease(raw);
        done();
    });
}

void MadeiraVulkanLabStop(void) {
    atomic_store(&g_stop, true);
}

// ---------------------------------------------------------------------------
// The address-space probe.

static const char *kern_str(kern_return_t k) {
    switch (k) {
    case KERN_SUCCESS: return "ok";
    case KERN_NO_SPACE: return "KERN_NO_SPACE";
    case KERN_INVALID_ADDRESS: return "KERN_INVALID_ADDRESS";
    case KERN_INVALID_ARGUMENT: return "KERN_INVALID_ARGUMENT";
    case KERN_RESOURCE_SHORTAGE: return "KERN_RESOURCE_SHORTAGE";
    default: return mach_error_string(k);
    }
}

static void probe_run(LogBlock log) {
    uint64_t physmem = 0;
    size_t sz = sizeof physmem;
    sysctlbyname("hw.memsize", &physmem, &sz, NULL, 0);
    L(log, "physical memory %.1f GB, available to this process now %.2f GB (os_proc_available_memory)",
      physmem / (1024.0 * 1024 * 1024), os_proc_available_memory() / (1024.0 * 1024 * 1024));

    // 1. The map as it is: highest mapped address and the five largest holes.
    mach_vm_address_t addr = 0, prev_end = 0, top = 0;
    mach_vm_size_t size = 0, total_mapped = 0;
    struct { mach_vm_address_t start; mach_vm_size_t len; } holes[5] = {{0}};
    unsigned regions = 0;
    for (;;) {
        vm_region_basic_info_data_64_t info;
        mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
        mach_port_t obj = MACH_PORT_NULL;
        kern_return_t k = mach_vm_region(mach_task_self(), &addr, &size, VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info, &count, &obj);
        if (k != KERN_SUCCESS) break;
        if (obj != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), obj);
        if (addr > prev_end) {
            mach_vm_size_t gap = addr - prev_end;
            for (int i = 0; i < 5; i++)
                if (gap > holes[i].len) {
                    for (int j = 4; j > i; j--) holes[j] = holes[j - 1];
                    holes[i].start = prev_end; holes[i].len = gap;
                    break;
                }
        }
        total_mapped += size;
        prev_end = addr + size;
        top = prev_end;
        regions++;
        addr = prev_end;
        if (regions > 200000) break;
    }
    L(log, "map: %u regions, %.2f GB mapped, highest mapped end 0x%llx (%.0f GB)", regions,
      total_mapped / (1024.0 * 1024 * 1024), (unsigned long long)top, top / (1024.0 * 1024 * 1024));
    for (int i = 0; i < 5; i++)
        if (holes[i].len)
            L(log, "hole %d: 0x%llx .. 0x%llx (%.1f GB)", i + 1, (unsigned long long)holes[i].start,
              (unsigned long long)(holes[i].start + holes[i].len), holes[i].len / (1024.0 * 1024 * 1024));

    // 2. One piece, anywhere: how large a PROT_NONE reservation iOS 27 grants.
    uint64_t best = 0;
    for (uint64_t gb = 1; gb <= 512; gb *= 2) {
        size_t len = (size_t)(gb << 30);
        void *p = mmap(NULL, len, PROT_NONE, MAP_PRIVATE | MAP_ANON | MAP_NORESERVE, -1, 0);
        if (p == MAP_FAILED) { L(log, "reserve %llu GB anywhere: errno %d (%s)", (unsigned long long)gb, errno, strerror(errno)); break; }
        L(log, "reserve %llu GB anywhere: ok at 0x%llx", (unsigned long long)gb, (unsigned long long)(uintptr_t)p);
        munmap(p, len);
        best = gb;
    }
    L(log, "largest single reservation: %llu GB", (unsigned long long)best);

    // 3. The fixed addresses console emulators want. Only a free range is
    // taken (VM_FLAGS_FIXED without overwrite), then released.
    struct { const char *why; uint64_t addr; uint64_t gb; } fixed[] = {
        { "PS4 eboot image base (0x400000, 64 MB)", 0x400000ull, 0 },
        { "PS4 image + heap (0x400000, 1 GB)", 0x400000ull, 1 },
        { "low guest range (0x200000000, 8 GB)", 0x200000000ull, 8 },
        { "shadPS4 system-managed (0x800000000, 32 GB)", 0x800000000ull, 32 },
        { "shadPS4 USER_MIN (0x1000000000, 64 GB)", 0x1000000000ull, 64 },
        { "shadPS4 USER_MIN (0x1000000000, 32 GB)", 0x1000000000ull, 32 },
        { "shadPS4 USER_MIN (0x1000000000, 16 GB)", 0x1000000000ull, 16 },
        { "0x2000000000, 64 GB", 0x2000000000ull, 64 },
        { "0x4000000000, 128 GB", 0x4000000000ull, 128 },
        { "0x6000000000, 64 GB", 0x6000000000ull, 64 },
    };
    for (size_t i = 0; i < sizeof fixed / sizeof *fixed; i++) {
        mach_vm_address_t a = fixed[i].addr;
        mach_vm_size_t len = fixed[i].gb ? (fixed[i].gb << 30) : (64ull << 20);
        kern_return_t k = mach_vm_allocate(mach_task_self(), &a, len, VM_FLAGS_FIXED);
        if (k == KERN_SUCCESS) {
            L(log, "fixed %s: ok", fixed[i].why);
            mach_vm_deallocate(mach_task_self(), a, len);
        } else {
            L(log, "fixed %s: %s", fixed[i].why, kern_str(k));
        }
    }

    // 4. The top of the usable address space, by bisection.
    {
        uint64_t lo = 1ull << 32, hi = 1ull << 47;
        while (hi - lo > (1ull << 24)) {
            uint64_t mid = (lo + hi) / 2 & ~0xFFFFull;
            mach_vm_address_t a = mid;
            kern_return_t k = mach_vm_allocate(mach_task_self(), &a, 1 << 20, VM_FLAGS_FIXED);
            if (k == KERN_SUCCESS) { mach_vm_deallocate(mach_task_self(), a, 1 << 20); lo = mid; }
            else if (k == KERN_NO_SPACE) {
                // Occupied or above the map: tell them apart by trying to read the region.
                mach_vm_address_t ra = mid; mach_vm_size_t rs = 0;
                vm_region_basic_info_data_64_t info; mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64; mach_port_t obj = MACH_PORT_NULL;
                kern_return_t rk = mach_vm_region(mach_task_self(), &ra, &rs, VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info, &count, &obj);
                if (obj != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), obj);
                if (rk == KERN_SUCCESS && ra <= mid) lo = mid;   // mapped: still inside the map
                else hi = mid;
            } else hi = mid;
        }
        L(log, "usable address space ends near 0x%llx (%.0f GB)", (unsigned long long)lo, lo / (1024.0 * 1024 * 1024));
    }
    L(log, "probe finished, everything released");
}

void MadeiraAddressSpaceProbe(void (^log)(NSString *), void (^done)(void)) {
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        probe_run(log);
        done();
    });
}
