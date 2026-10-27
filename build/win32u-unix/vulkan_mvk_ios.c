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

void *madeira_vk_dlsym( void *handle, const char *name )
{
    if (handle != &madeira_vk_handle_storage || !name) return NULL;
    if (!strcmp( name, "vkGetInstanceProcAddr" )) return (void *)vkGetInstanceProcAddr;
    if (!strcmp( name, "vkGetDeviceProcAddr" )) return (void *)vkGetDeviceProcAddr;
    return (void *)vkGetInstanceProcAddr( NULL, name );
}

int madeira_vk_dlclose( void *handle )
{
    (void)handle;
    return 0;
}
