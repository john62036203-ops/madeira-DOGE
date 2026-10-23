/* madeira-doge shared-tex: D3D11 shared textures opened by D3D12 in the same process.
 *
 * DYNASTY WARRIORS: ORIGINS demo (build 394 log 2026-10-23 17:13) decodes its
 * movie with D3D11 and hands each picture to its D3D12 renderer through a
 * D3D11 texture created with D3D11_RESOURCE_MISC_SHARED (B8G8R8A8_TYPELESS,
 * 1280x720): IDXGIResource::GetSharedHandle, then ID3D12Device::OpenSharedHandle.
 * DXMT shares through a mach port and the D3DKMT layer; on iOS there is no
 * mach port for such a texture, so it was kept unshared and GetSharedHandle
 * failed (E_INVALIDARG). The game dropped the movie and retried for good.
 *
 * Both runtimes live in the game's process and use the same Metal device, so
 * the texture object itself can be handed over. DXMT (tools/patch-dxmt-share-
 * local.py, d3d11-src.dll) records an unshareable shared texture here and
 * answers GetSharedHandle with a handle naming the entry; madeira-d3d12's
 * OpenSharedHandle looks the handle up and makes a resource over a view of the
 * same Metal texture. The table is a small named section so neither DLL has
 * to export anything to the other.
 *
 * Handles are 0x7d000000 | slot << 8 | generation: never a real D3DKMT
 * handle (those are 0x40000000-based) and never a Windows handle value.
 * C and C++. */
#ifndef MADEIRA_SHARED_TEX_H
#define MADEIRA_SHARED_TEX_H

#include <windows.h>

#define MADEIRA_STX_MAX 64
#define MADEIRA_STX_BASE 0x7d000000u
#define MADEIRA_STX_MAGIC 0x31585453u   /* "STX1" */

struct madeira_stx_entry {
    volatile LONG handle;          /* 0 = free, 1 = being filled, else the handle */
    UINT32 format, width, height, mips, array;
    UINT64 texture;                /* winemetal obj_handle_t of the MTLTexture (retained by the D3D11 side) */
};

struct madeira_stx_table {
    UINT32 magic;
    volatile LONG gen;
    struct madeira_stx_entry e[MADEIRA_STX_MAX];
};

static inline struct madeira_stx_table *madeira_stx_get(void) {
    static struct madeira_stx_table *volatile table;
    struct madeira_stx_table *t = table;
    if (!t) {
        HANDLE m = CreateFileMappingW(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0,
                                      (DWORD)sizeof(struct madeira_stx_table), L"Local\\madeira-shared-tex-v1");
        if (!m) return NULL;
        t = (struct madeira_stx_table *)MapViewOfFile(m, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(struct madeira_stx_table));
        if (!t) return NULL;
        if (t->magic != MADEIRA_STX_MAGIC) InterlockedCompareExchange((volatile LONG *)&t->magic, (LONG)MADEIRA_STX_MAGIC, 0);
        table = t;
    }
    return t;
}

static inline int madeira_stx_is_handle(UINT64 h) {
    return (h & 0xff000000u) == MADEIRA_STX_BASE && !(h >> 32) && ((h >> 8) & 0xff) < MADEIRA_STX_MAX;
}

/* Returns the handle, or 0 when the table is full or cannot be mapped. */
static inline UINT32 madeira_stx_register(UINT64 texture, UINT32 format, UINT32 width, UINT32 height, UINT32 mips, UINT32 array) {
    struct madeira_stx_table *t = madeira_stx_get();
    unsigned i;
    if (!t || !texture) return 0;
    for (i = 0; i < MADEIRA_STX_MAX; i++) {
        struct madeira_stx_entry *e = &t->e[i];
        if (InterlockedCompareExchange(&e->handle, 1, 0) == 0) {
            UINT32 h = MADEIRA_STX_BASE | (i << 8) | ((UINT32)InterlockedIncrement(&t->gen) & 0xff);
            e->format = format; e->width = width; e->height = height; e->mips = mips; e->array = array;
            e->texture = texture;
            MemoryBarrier();
            e->handle = (LONG)h;
            return h;
        }
    }
    return 0;
}

/* Copies the entry; 0 when the handle names nothing (any more). */
static inline int madeira_stx_lookup(UINT64 h, struct madeira_stx_entry *out) {
    struct madeira_stx_table *t;
    struct madeira_stx_entry *e;
    if (!madeira_stx_is_handle(h) || !(t = madeira_stx_get())) return 0;
    e = &t->e[(h >> 8) & 0xff];
    if ((UINT32)e->handle != (UINT32)h) return 0;
    *out = *e;
    MemoryBarrier();
    return (UINT32)e->handle == (UINT32)h;
}

/* Frees the entry; returns its texture (for the caller to release), or 0. */
static inline UINT64 madeira_stx_unregister(UINT64 h) {
    struct madeira_stx_table *t;
    struct madeira_stx_entry *e;
    UINT64 tex;
    if (!madeira_stx_is_handle(h) || !(t = madeira_stx_get())) return 0;
    e = &t->e[(h >> 8) & 0xff];
    if ((UINT32)e->handle != (UINT32)h) return 0;
    tex = e->texture;
    if (InterlockedCompareExchange(&e->handle, 1, (LONG)h) != (LONG)h) return 0;
    e->texture = 0;
    MemoryBarrier();
    e->handle = 0;
    return tex;
}

#endif
