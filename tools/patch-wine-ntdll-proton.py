#!/usr/bin/env python3
"""madeira-doge: Proton's PE ntdll changes, for ntdll-proton.dll (an opt-in ntdll).

Two changes from Valve's Proton 11 Wine (ValveSoftware/wine proton_11.0), adapted
to this tree (willfaust/wine madeira-lgpl, Wine 11.4 plus the iOS changes):

  loader.c  3dcea33247 "ntdll: Match memory allocation layout for
            ThreadLocalStoragePointer" (Paul Gofman, CW-Bug-Id #24258). On
            Windows the TLS vector (TEB->ThreadLocalStoragePointer) and each TLS
            data block are allocated with two hidden pointer-sized fields in
            front: the vector's ptr[-2] holds its slot count, a block's ptr[-2]
            and ptr[-1] are zero. Programs and protectors that read those fields
            find garbage heap headers under Wine. Every allocation and free of the
            vector and the blocks goes through alloc_tls_memory / free_tls_memory.
            Proton's alloc_tls_slot hunks sit on top of its ProcessTlsInformation
            implementation, which this tree lacks; the same conversion is applied
            to this tree's alloc_tls_slot instead.
  heap.c    31d70e4e5d "ntdll: Keep more LFH block groups alive" (Rémi Bernon).
            A bin keeps as many released block groups as it ever had in use at
            once, instead of at most 32, so a program that frees and reallocates
            many small blocks in waves does not release and re-create groups.
            It keeps freed memory at its peak instead of returning it, so it is
            its own switch inside ntdll-proton.dll: MADEIRA_HEAP_LFH_KEEP=1, read
            once by the loader where the i386 heap policy is read (counting always
            runs; without the switch the old limit of 32 kept groups stays).

The shipped ntdll.dll is untouched. tools/build-wine-extra-dlls.sh first checks
that this tree, unpatched, rebuilds the shipped ntdll.dll apart from its time
stamps (--same-as), then builds the patched one and ships it as ntdll-proton.dll;
build/ntdll-unix/loader_ios.c maps it only with env.MADEIRA_NTDLL_PROTON = 1.

  patch-wine-ntdll-proton.py WINE           patch the wine tree in place
  patch-wine-ntdll-proton.py --same-as A B  A and B are the same image apart from time stamps
"""
import struct
import sys


def edit(path, edits):
    text = open(path, encoding="utf-8").read()
    for old, new, count in edits:
        found = text.count(old)
        if found != count:
            sys.exit("%s: expected %d match(es) of %r, found %d" % (path, count, old[:70], found))
        text = text.replace(old, new)
    open(path, "w", encoding="utf-8").write(text)


TLS_HELPERS = '''/*************************************************************************
 *		alloc_tls_memory
 *
 * madeira-doge (Proton 3dcea33247): memory for the TLS vector or a TLS data
 * block, with two hidden pointer-sized fields in front as on Windows: the
 * vector's ptr[-2] is its slot count, a block's ptr[-2] and ptr[-1] are zero.
 */
static void *alloc_tls_memory( BOOL vector, ULONG_PTR size )
{
    ULONG_PTR *ptr;

    if (!(ptr = RtlAllocateHeap( GetProcessHeap(), vector ? HEAP_ZERO_MEMORY : 0, size + sizeof(void *) * 2 ))) return NULL;
    ptr += 2;
    if (vector) ptr[-2] = size / sizeof(void *);
    else        ptr[-2] = ptr[-1] = 0;
    return ptr;
}


/*************************************************************************
 *		free_tls_memory
 *
 * madeira-doge (Proton 3dcea33247): free what alloc_tls_memory returned.
 */
static void free_tls_memory( void *ptr )
{
    if (!ptr) return;
    RtlFreeHeap( GetProcessHeap(), 0, (void **)ptr - 2 );
}


static BOOL alloc_tls_slot( LDR_DATA_TABLE_ENTRY *mod )
'''


def patch(wine):
    edit(wine + "/dlls/ntdll/loader.c", [
        ("static BOOL alloc_tls_slot( LDR_DATA_TABLE_ENTRY *mod )\n{", TLS_HELPERS + "{", 1),
        ("#ifdef __i386__\n        heap_init_madeira_policy();  /* environment ready, no guest threads yet */\n#endif\n",
         "#ifdef __i386__\n        heap_init_madeira_policy();  /* environment ready, no guest threads yet */\n#endif\n"
         "        heap_init_proton_policy();   /* madeira-doge: MADEIRA_HEAP_LFH_KEEP */\n", 1),
        # alloc_tls_slot: the grown vector and the new block of every running thread
        ("            void **new = RtlAllocateHeap( GetProcessHeap(), HEAP_ZERO_MEMORY, tls_module_count * sizeof(*new));",
         "            void **new = alloc_tls_memory( TRUE, tls_module_count * sizeof(*new) );", 1),
        ("        if (!(new_ptr = RtlAllocateHeap( GetProcessHeap(), 0, size + dir->SizeOfZeroFill ))) return -1;",
         "        if (!(new_ptr = alloc_tls_memory( FALSE, size + dir->SizeOfZeroFill ))) return -1;", 1),
        ("        RtlFreeHeap( GetProcessHeap(), 0,\n                     InterlockedExchangePointer( (void **)teb->ThreadLocalStoragePointer + i, new_ptr ));",
         "        free_tls_memory( InterlockedExchangePointer( (void **)teb->ThreadLocalStoragePointer + i, new_ptr ) );", 1),
        # alloc_thread_tls
        ("    if (!(pointers = RtlAllocateHeap( GetProcessHeap(), HEAP_ZERO_MEMORY,\n                                      tls_module_count * sizeof(*pointers) )))",
         "    if (!(pointers = alloc_tls_memory( TRUE, tls_module_count * sizeof(*pointers) )))", 1),
        ("        if (!(pointers[i] = RtlAllocateHeap( GetProcessHeap(), 0, size + dir->SizeOfZeroFill )))\n        {\n"
         "            while (i) RtlFreeHeap( GetProcessHeap(), 0, pointers[--i] );\n            RtlFreeHeap( GetProcessHeap(), 0, pointers );",
         "        if (!(pointers[i] = alloc_tls_memory( FALSE, size + dir->SizeOfZeroFill )))\n        {\n"
         "            while (i) free_tls_memory( pointers[--i] );\n            free_tls_memory( pointers );", 1),
        # LdrShutdownThread
        ("        for (i = 0; i < tls_module_count; i++) RtlFreeHeap( GetProcessHeap(), 0, pointers[i] );\n"
         "        RtlFreeHeap( GetProcessHeap(), 0, pointers );",
         "        for (i = 0; i < tls_module_count; i++) free_tls_memory( pointers[i] );\n"
         "        free_tls_memory( pointers );", 1),
    ])
    edit(wine + "/dlls/ntdll/heap.c", [
        ("    /* list of groups with free blocks */\n    SLIST_HEADER groups;\n",
         "    /* list of groups with free blocks */\n    SLIST_HEADER groups;\n"
         "    /* madeira-doge (Proton 31d70e4e5d): groups allocated, released, and the most in use at once */\n"
         "    LONG group_alloc;\n    LONG group_freed;\n    LONG group_max;\n", 1),
        ("/* acquire a group from the bin, thread takes ownership of a shared group or allocates a new one */\n",
         "/* madeira-doge (Proton 31d70e4e5d): MADEIRA_HEAP_LFH_KEEP=1 keeps as many released LFH groups\n"
         " * per bin as were ever in use at once (else at most 32). Read once by the loader before guest\n"
         " * threads run, never under a heap lock. */\n"
         "static LONG madeira_lfh_keep;\n\n"
         "void heap_init_proton_policy(void)\n{\n"
         "    UNICODE_STRING name, value;\n    WCHAR buffer[2];\n\n"
         "    RtlInitUnicodeString( &name, L\"MADEIRA_HEAP_LFH_KEEP\" );\n"
         "    value.Buffer = buffer;\n    value.MaximumLength = sizeof(buffer);\n"
         "    if (!RtlQueryEnvironmentVariable_U( NULL, &name, &value ) &&\n"
         "        value.Length == sizeof(WCHAR) && buffer[0] == '1') madeira_lfh_keep = 1;\n"
         "    if (madeira_lfh_keep) ERR( \"[heap-policy] lfh-keep=1 (Proton 31d70e4e5d)\\n\" );\n}\n\n"
         "/* acquire a group from the bin, thread takes ownership of a shared group or allocates a new one */\n", 1),
        ("    ULONG affinity = NtCurrentTeb()->HeapVirtualAffinity;\n    struct group *group;\n    SLIST_ENTRY *entry;\n",
         "    ULONG affinity = NtCurrentTeb()->HeapVirtualAffinity, count;\n    struct group *group;\n    SLIST_ENTRY *entry;\n", 1),
        ("        return CONTAINING_RECORD( entry, struct group, entry );\n\n    return group_allocate( heap, flags, block_size );",
         "        return CONTAINING_RECORD( entry, struct group, entry );\n\n"
         "    count = InterlockedIncrement( &bin->group_alloc ) - ReadNoFence( &bin->group_freed );\n"
         "    if (count > ReadAcquire( &bin->group_max )) WriteRelease( &bin->group_max, count );\n"
         "    return group_allocate( heap, flags, block_size );", 1),
        ("    if (RtlQueryDepthSList( &bin->groups ) <= ARRAY_SIZE(affinity_mapping))\n    {\n"
         "        RtlInterlockedPushEntrySList( &bin->groups, &group->entry );\n        return STATUS_SUCCESS;\n    }\n\n"
         "    return group_release( heap, flags, bin, group );",
         "    if (RtlQueryDepthSList( &bin->groups ) <= (madeira_lfh_keep ? (ULONG)ReadAcquire( &bin->group_max )\n"
         "                                                                : (ULONG)ARRAY_SIZE(affinity_mapping)))\n    {\n"
         "        RtlInterlockedPushEntrySList( &bin->groups, &group->entry );\n        return STATUS_SUCCESS;\n    }\n\n"
         "    InterlockedIncrement( &bin->group_freed );\n    return group_release( heap, flags, bin, group );", 1),
    ])
    edit(wine + "/dlls/ntdll/ntdll_misc.h", [
        ("extern void heap_init_madeira_policy(void);\n",
         "extern void heap_init_madeira_policy(void);\nextern void heap_init_proton_policy(void);\n", 1),
    ])
    print("patched dlls/ntdll/loader.c (TLS layout), heap.c (LFH groups, MADEIRA_HEAP_LFH_KEEP) and ntdll_misc.h")


def stamp_offsets(data, path):
    """File offsets of the 4-byte time stamps: the COFF header's and each debug directory entry's."""
    if data[:2] != b"MZ":
        sys.exit("%s: not a PE image" % path)
    pe = struct.unpack_from("<I", data, 0x3c)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        sys.exit("%s: not a PE image" % path)
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    optsz = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    if struct.unpack_from("<H", data, opt)[0] != 0x20b:
        sys.exit("%s: not a PE32+ image" % path)
    offsets = [pe + 8]
    ndirs = struct.unpack_from("<I", data, opt + 108)[0]
    if ndirs > 6:
        rva, size = struct.unpack_from("<II", data, opt + 112 + 8 * 6)
        if size:
            for i in range(nsec):
                s = opt + optsz + 40 * i
                vsz, va, rsz, raw = struct.unpack_from("<IIII", data, s + 8)
                if va <= rva < va + max(vsz, rsz):
                    base = rva - va + raw
                    offsets += [base + 28 * k + 4 for k in range(size // 28)]
                    break
    return offsets


def same_as(a, b):
    da, db = bytearray(open(a, "rb").read()), bytearray(open(b, "rb").read())
    if len(da) != len(db):
        sys.exit("same-as: %s is %d bytes, %s %d" % (a, len(da), b, len(db)))
    for path, buf in ((a, da), (b, db)):
        for o in stamp_offsets(buf, path):
            buf[o:o + 4] = b"\0\0\0\0"
    if da != db:
        diff = [i for i, (x, y) in enumerate(zip(da, db)) if x != y]
        sys.exit("same-as: %s and %s differ in %d bytes beyond their time stamps (first at %#x)" % (a, b, len(diff), diff[0]))
    print("same-as: %s and %s are identical apart from their time stamps" % (a, b))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--same-as":
        same_as(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 2 and not sys.argv[1].startswith("-"):
        patch(sys.argv[1])
    else:
        sys.exit(__doc__)
