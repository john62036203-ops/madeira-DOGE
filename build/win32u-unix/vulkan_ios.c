/*
 * win32u Vulkan loader + wineios Vulkan driver (madeira-doge, vulkan branch)
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

/* Wraps wine/dlls/win32u/vulkan.c (compiled unchanged) for the iOS port:
 *
 * 1. The host library.  Upstream dlopen()s SONAME_LIBVULKAN; the iOS tree
 *    is configured --without-vulkan, so until now this TU compiled to the
 *    "Wine was built without Vulkan support" branch.  Here SONAME_LIBVULKAN
 *    is defined and dlopen/dlsym/dlclose are routed to vulkan_mvk_ios.c,
 *    which answers from the statically linked MoltenVK -- only when the
 *    session has MADEIRA_VULKAN=1 (see that file).
 *
 * 2. The display-driver half (what winemac.drv/vulkan.c is on macOS): the
 *    surface for a HWND is a VkSurfaceKHR made with vkCreateMetalSurfaceEXT
 *    on the CAMetalLayer the app already keeps per window for DXMT
 *    (IOSDisplayShim.m's macdrv_functions: game mode = the full-screen
 *    layer, desktop mode = the window's compositor layer).  driver_ios.c
 *    installs winios_VulkanInit as the user driver's pVulkanInit.
 *
 * Everything below runs only after a program loaded vulkan-1.dll /
 * winevulkan.dll and called into it; D3D games never reach this file. */

#include <dlfcn.h>
#include <stdint.h>

void *madeira_vk_dlopen( const char *name, int mode );
void *madeira_vk_dlsym( void *handle, const char *name );
int madeira_vk_dlclose( void *handle );

#define dlopen  madeira_vk_dlopen
#define dlsym   madeira_vk_dlsym
#define dlclose madeira_vk_dlclose
#undef SONAME_LIBVULKAN
#define SONAME_LIBVULKAN "libMoltenVK.a (statically linked)"

#include "../../wine/dlls/win32u/vulkan.c"

#undef dlopen
#undef dlsym
#undef dlclose

/* ---- the wineios Vulkan driver ------------------------------------- */

/* IOSDisplayShim.m's table, by layout (the shim's header is Objective-C). */
typedef struct madeira_macdrv_opaque_metal_device *madeira_macdrv_metal_device;
typedef struct madeira_macdrv_opaque_metal_view *madeira_macdrv_metal_view;
typedef struct madeira_macdrv_opaque_metal_layer *madeira_macdrv_metal_layer;
typedef struct madeira_macdrv_opaque_view *madeira_macdrv_view;
typedef struct madeira_macdrv_opaque_window *madeira_macdrv_window;

struct madeira_macdrv_functions_t
{
    void (*macdrv_init_display_devices)( BOOL );
    void *(*get_win_data)( HWND hwnd );
    void (*release_win_data)( void *data );
    madeira_macdrv_window (*macdrv_get_cocoa_window)( HWND hwnd, BOOL require_on_screen );
    madeira_macdrv_metal_device (*macdrv_create_metal_device)( void );
    void (*macdrv_release_metal_device)( madeira_macdrv_metal_device d );
    madeira_macdrv_metal_view (*macdrv_view_create_metal_view)( madeira_macdrv_view v, madeira_macdrv_metal_device d );
    madeira_macdrv_metal_layer (*macdrv_view_get_metal_layer)( madeira_macdrv_metal_view v );
    void (*macdrv_view_release_metal_view)( madeira_macdrv_metal_view v );
    void (*on_main_thread)( void *block );
};
extern struct madeira_macdrv_functions_t macdrv_functions;

struct winios_vk_surface
{
    struct client_surface client;
    madeira_macdrv_metal_view view;
};

static void winios_vk_surface_destroy( struct client_surface *client )
{
    struct winios_vk_surface *surface = CONTAINING_RECORD( client, struct winios_vk_surface, client );
    if (surface->view && macdrv_functions.macdrv_view_release_metal_view)
        macdrv_functions.macdrv_view_release_metal_view( surface->view );
    surface->view = NULL;
}

static void winios_vk_surface_detach( struct client_surface *client ) { (void)client; }
static void winios_vk_surface_update( struct client_surface *client ) { (void)client; }
static void winios_vk_surface_present( struct client_surface *client, HDC hdc ) { (void)client; (void)hdc; }

static const struct client_surface_funcs winios_vk_surface_funcs =
{
    .destroy = winios_vk_surface_destroy,
    .detach = winios_vk_surface_detach,
    .update = winios_vk_surface_update,
    .present = winios_vk_surface_present,
};

static VkResult winios_vulkan_surface_create( HWND hwnd, const struct vulkan_instance *instance,
                                              VkSurfaceKHR *handle, struct client_surface **client )
{
    static unsigned said;
    struct winios_vk_surface *surface;
    VkMetalSurfaceCreateInfoEXT info = { .sType = VK_STRUCTURE_TYPE_METAL_SURFACE_CREATE_INFO_EXT };
    madeira_macdrv_metal_device dev;
    VkResult res;

    if (!instance->p_vkCreateMetalSurfaceEXT)
    {
        dprintf( 2, "[vulkan] madeira-doge: surface for hwnd=%p refused: the instance has no "
                    "vkCreateMetalSurfaceEXT (VK_EXT_metal_surface not enabled)\n", hwnd );
        return VK_ERROR_EXTENSION_NOT_PRESENT;
    }
    if (!macdrv_functions.macdrv_view_create_metal_view || !macdrv_functions.macdrv_view_get_metal_layer)
    {
        dprintf( 2, "[vulkan] madeira-doge: surface for hwnd=%p refused: no display shim\n", hwnd );
        return VK_ERROR_INITIALIZATION_FAILED;
    }
    if (!(surface = client_surface_create( sizeof(*surface), &winios_vk_surface_funcs, hwnd )))
        return VK_ERROR_OUT_OF_HOST_MEMORY;

    dev = macdrv_functions.macdrv_create_metal_device ? macdrv_functions.macdrv_create_metal_device() : NULL;
    /* the shim carries the HWND in the "view" argument (IOSDisplayShim.m) */
    surface->view = macdrv_functions.macdrv_view_create_metal_view( (madeira_macdrv_view)hwnd, dev );
    if (!surface->view)
    {
        dprintf( 2, "[vulkan] madeira-doge: no CAMetalLayer for hwnd=%p\n", hwnd );
        client_surface_release( &surface->client );
        return VK_ERROR_INITIALIZATION_FAILED;
    }
    info.pLayer = (const void *)macdrv_functions.macdrv_view_get_metal_layer( surface->view );

    res = instance->p_vkCreateMetalSurfaceEXT( instance->host.instance, &info, NULL, handle );
    if (res != VK_SUCCESS)
    {
        dprintf( 2, "[vulkan] madeira-doge: vkCreateMetalSurfaceEXT for hwnd=%p failed: %d\n", hwnd, res );
        client_surface_release( &surface->client );
        return res;
    }
    if (said++ < 8)
        dprintf( 2, "[vulkan] madeira-doge: Metal surface for hwnd=%p layer=%p surface=0x%llx\n",
                 hwnd, info.pLayer, (unsigned long long)*handle );
    *client = &surface->client;
    return VK_SUCCESS;
}

static VkBool32 winios_get_physical_device_presentation_support( struct vulkan_physical_device *physical_device,
                                                                 uint32_t index )
{
    (void)physical_device; (void)index;
    return VK_TRUE;
}

static void winios_map_instance_extensions( struct vulkan_instance_extensions *extensions )
{
    /* VK_KHR_win32_surface is what the program asks for; MoltenVK offers
     * VK_EXT_metal_surface.  Same pairing as winemac.drv. */
    if (extensions->has_VK_KHR_win32_surface) extensions->has_VK_EXT_metal_surface = 1;
    if (extensions->has_VK_EXT_metal_surface) extensions->has_VK_KHR_win32_surface = 1;
}

static void winios_map_device_extensions( struct vulkan_device_extensions *extensions )
{
    (void)extensions;
}

static const struct vulkan_driver_funcs winios_vulkan_driver_funcs =
{
    .p_vulkan_surface_create = winios_vulkan_surface_create,
    .p_get_physical_device_presentation_support = winios_get_physical_device_presentation_support,
    .p_map_instance_extensions = winios_map_instance_extensions,
    .p_map_device_extensions = winios_map_device_extensions,
};

UINT winios_VulkanInit( UINT version, void *vulkan_handle, const struct vulkan_driver_funcs **driver_funcs )
{
    if (version != WINE_VULKAN_DRIVER_VERSION)
    {
        dprintf( 2, "[vulkan] madeira-doge: version mismatch, win32u wants %u, this driver has %u\n",
                 version, WINE_VULKAN_DRIVER_VERSION );
        return STATUS_INVALID_PARAMETER;
    }
    if (!vulkan_handle) return STATUS_NOT_IMPLEMENTED;
    dprintf( 2, "[vulkan] madeira-doge: wineios Vulkan driver (Metal surfaces on the app's CAMetalLayer) installed\n" );
    *driver_funcs = &winios_vulkan_driver_funcs;
    return STATUS_SUCCESS;
}
