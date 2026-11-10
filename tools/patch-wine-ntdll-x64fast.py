#!/usr/bin/env python3
"""madeira-doge: ntdll-x64fast.dll, an opt-in ARM64EC ntdll with two x64 fast paths
from Playport (playportdev/playport, patches/wine-pe 0050 and 0052, adapted to this
tree, willfaust/wine madeira-lgpl):

  MADEIRA_X64_CS_FASTPATH=1   an x64 module's imports of Enter/LeaveCriticalSection
        (and the Rtl names) that resolve to ntdll's x64 export thunks go to two x64
        stubs FEX runs inline: a free section is taken, a section held once with no
        waiter is released, every other case jumps on to ntdll's export as before.
        Playport, RDR2: about 145,000 such calls a second, fps +2-6 %, CPU power
        -5 to -11 % together with its FEX batch2 (not ported).
  MADEIRA_X64_QPC_FASTPATH=1  an x64 module's import of QueryPerformanceCounter /
        RtlQueryPerformanceCounter (and KERNEL32's by name) goes to an x64 stub that
        gives what RtlQueryPerformanceCounter gives for the same count (RDTSC shifted
        by FEX's TSC scale from CPUID 15h, the offset from struct qpc_state, read
        under its sequence count, within a second of the last resync); anything else
        jumps on to the export. time.c keeps its state in struct qpc_state and writes
        a resync under the sequence count. tools/patch-fex-ios-rdtsc-selfsync.py makes
        FEX's RDTSC self-synchronizing under the same switch.

Each switch is read once per process by ntdll (RtlQueryEnvironmentVariable_U); unset
or anything but 1 changes nothing but the time.c state layout. The shipped ntdll.dll
is untouched: tools/build-wine-extra-dlls.sh builds this next to it after the same
"this tree rebuilds the shipped ntdll.dll" check as ntdll-proton.dll, and
build/ntdll-unix/loader_ios.c maps it only when one of the two switches is 1 (and
MADEIRA_NTDLL_PROTON is not).

  patch-wine-ntdll-x64fast.py WINE    patch the wine tree in place
"""
import sys


def edit(path, edits):
    text = open(path, encoding="utf-8").read()
    for old, new, count in edits:
        found = text.count(old)
        if found != count:
            sys.exit("%s: expected %d match(es) of %r, found %d" % (path, count, old[:70], found))
        text = text.replace(old, new)
    open(path, "w", encoding="utf-8").write(text)
    return text


MARKER = "madeira-doge (Playport wine-pe 0050)"

LOADER_CODE = """
/* madeira-doge (Playport wine-pe 0050): MADEIRA_X64_CS_FASTPATH=1 (off by default). Each x64 call of
 * EnterCriticalSection or LeaveCriticalSection costs an x64->EC transition into
 * ntdll, about 145,000 a second in RDR2, and almost every one finds the
 * section free (a few hundred a second contend). With the switch, an x64
 * module's imports of the two go to x64 stubs that FEX runs inline: Enter
 * takes a free section (LockCount -1 -> 0), Leave releases a section held once
 * with no waiter (LockCount 0 -> -1); every other case jumps on to ntdll's
 * export, as the import did before. Offsets are the x64 RTL_CRITICAL_SECTION's
 * (LockCount 0x8, RecursionCount 0xc, OwningThread 0x10); the owner is the
 * TEB's ClientId.UniqueThread, gs:0x48. Leave clears the owner before the
 * release and restores it if a waiter came, as RtlLeaveCriticalSection expects
 * to find the section held. Each stub ends in jmp *0(%rip) and its target. */
static const BYTE x64_cs_enter_code[] =
{
    0xb8, 0xff, 0xff, 0xff, 0xff,                   /* 00: mov $-1,%eax */
    0x31, 0xd2,                                     /* 05: xor %edx,%edx */
    0xf0, 0x0f, 0xb1, 0x51, 0x08,                   /* 07: lock cmpxchg %edx,0x8(%rcx) */
    0x75, 0x17,                                     /* 0c: jne 25 */
    0x65, 0x48, 0x8b, 0x04, 0x25, 0x48, 0, 0, 0,    /* 0e: mov %gs:0x48,%rax */
    0x48, 0x89, 0x41, 0x10,                         /* 17: mov %rax,0x10(%rcx) */
    0xc7, 0x41, 0x0c, 0x01, 0, 0, 0,                /* 1b: movl $1,0xc(%rcx) */
    0x31, 0xc0,                                     /* 22: xor %eax,%eax */
    0xc3,                                           /* 24: ret */
    0xff, 0x25, 0, 0, 0, 0,                         /* 25: jmp *0(%rip) */
};
static const BYTE x64_cs_leave_code[] =
{
    0x83, 0x79, 0x0c, 0x01,                         /* 00: cmpl $1,0xc(%rcx) */
    0x75, 0x3a,                                     /* 04: jne 40 */
    0x83, 0x79, 0x08, 0x00,                         /* 06: cmpl $0,0x8(%rcx) */
    0x75, 0x34,                                     /* 0a: jne 40 */
    0xc7, 0x41, 0x0c, 0, 0, 0, 0,                   /* 0c: movl $0,0xc(%rcx) */
    0x48, 0xc7, 0x41, 0x10, 0, 0, 0, 0,             /* 13: movq $0,0x10(%rcx) */
    0x31, 0xc0,                                     /* 1b: xor %eax,%eax */
    0xba, 0xff, 0xff, 0xff, 0xff,                   /* 1d: mov $-1,%edx */
    0xf0, 0x0f, 0xb1, 0x51, 0x08,                   /* 22: lock cmpxchg %edx,0x8(%rcx) */
    0x75, 0x03,                                     /* 27: jne 2c */
    0x31, 0xc0,                                     /* 29: xor %eax,%eax */
    0xc3,                                           /* 2b: ret */
    0x65, 0x48, 0x8b, 0x04, 0x25, 0x48, 0, 0, 0,    /* 2c: mov %gs:0x48,%rax */
    0x48, 0x89, 0x41, 0x10,                         /* 35: mov %rax,0x10(%rcx) */
    0xc7, 0x41, 0x0c, 0x01, 0, 0, 0,                /* 39: movl $1,0xc(%rcx) */
    0xff, 0x25, 0, 0, 0, 0,                         /* 40: jmp *0(%rip) */
};
C_ASSERT( sizeof(x64_cs_enter_code) == 0x2b && sizeof(x64_cs_leave_code) == 0x46 );
/* the x64 export thunk ntdll's exports start with (see arm64x_check_call) */
static const BYTE x64_cs_export_thunk[] = { 0x48, 0x8b, 0xc4, 0x48, 0x89, 0x58, 0x20, 0x55, 0x5d, 0xe9 };

static BOOL x64_cs_fastpath_on(void)
{
    static int on = -1;
    if (on < 0)
    {
        UNICODE_STRING nm, val;
        WCHAR buf[8];
        RtlInitUnicodeString( &nm, L"MADEIRA_X64_CS_FASTPATH" );
        val.Buffer = buf; val.Length = 0; val.MaximumLength = sizeof(buf);
        on = (!RtlQueryEnvironmentVariable_U( NULL, &nm, &val ) && val.Length && buf[0] == '1');
    }
    return on;
}

/* The x64 stub for an x64 module's import of name resolved to target, or NULL
 * to keep target. The page is made once a process, with both stubs and their
 * targets, ntdll's two exports, before any of it runs. */
static void *x64_cs_stub_for( HMODULE importer, const char *name, void *target )
{
    static BYTE *stubs;   /* enter at 0, leave at 0x80 */
    static void *targets[2];
    static BOOL tried;
    const IMAGE_NT_HEADERS *nt = RtlImageNtHeader( importer );
    LDR_DATA_TABLE_ENTRY *mod;
    int leave;

    if (!strcmp( name, "EnterCriticalSection" ) || !strcmp( name, "RtlEnterCriticalSection" )) leave = 0;
    else if (!strcmp( name, "LeaveCriticalSection" ) || !strcmp( name, "RtlLeaveCriticalSection" )) leave = 1;
    else return NULL;
    if (!x64_cs_fastpath_on()) return NULL;
    if (!nt || nt->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64 || arm64ec_get_module_metadata( importer ))
        return NULL;
    if (LdrFindEntryForAddress( target, &mod ) || mod->DdagNode != node_ntdll) return NULL;

    if (!tried)
    {
        const IMAGE_EXPORT_DIRECTORY *exports;
        DWORD exp_size;
        void *base = NULL;
        SIZE_T size = 0x1000;
        ULONG old;

        tried = TRUE;
        if (!(exports = RtlImageDirectoryEntryToData( mod->DllBase, TRUE, IMAGE_DIRECTORY_ENTRY_EXPORT, &exp_size )))
            return NULL;
        targets[0] = find_named_export( mod->DllBase, exports, exp_size, "RtlEnterCriticalSection", -1, NULL, NULL, FALSE );
        targets[1] = find_named_export( mod->DllBase, exports, exp_size, "RtlLeaveCriticalSection", -1, NULL, NULL, FALSE );
        if (!targets[0] || !targets[1] ||
            memcmp( targets[0], x64_cs_export_thunk, sizeof(x64_cs_export_thunk) ) ||
            memcmp( targets[1], x64_cs_export_thunk, sizeof(x64_cs_export_thunk) ))
        {
            ERR( "[x64-cs] ntdll's exports %p %p are not x64 export thunks; the switch is off\\n",
                 targets[0], targets[1] );
            return NULL;
        }
        if (NtAllocateVirtualMemory( NtCurrentProcess(), &base, 0, &size, MEM_RESERVE | MEM_COMMIT,
                                     PAGE_EXECUTE_READWRITE ))
        {
            ERR( "[x64-cs] no page for the stubs; the switch is off\\n" );
            return NULL;
        }
        memcpy( base, x64_cs_enter_code, sizeof(x64_cs_enter_code) );
        memcpy( (BYTE *)base + sizeof(x64_cs_enter_code), &targets[0], sizeof(void *) );
        memcpy( (BYTE *)base + 0x80, x64_cs_leave_code, sizeof(x64_cs_leave_code) );
        memcpy( (BYTE *)base + 0x80 + sizeof(x64_cs_leave_code), &targets[1], sizeof(void *) );
        NtProtectVirtualMemory( NtCurrentProcess(), &base, &size, PAGE_EXECUTE_READ, &old );
        stubs = base;
        ERR( "[x64-cs] x64 critical-section stubs at %p for %p %p (MADEIRA_X64_CS_FASTPATH)\\n",
             stubs, targets[0], targets[1] );
    }
    if (!stubs || target != targets[leave]) return NULL;
    return leave ? stubs + 0x80 : stubs;
}

/* madeira-doge (Playport wine-pe 0052): MADEIRA_X64_QPC_FASTPATH=1 (off by default). RDR2 calls
 * QueryPerformanceCounter about 40,000 times a second, each an x64->EC
 * transition into ntdll. With the switch, an x64 module's import of it (or
 * of RtlQueryPerformanceCounter) goes to an x64 stub that gives what
 * RtlQueryPerformanceCounter gives for the same count: ticks(count) + offset
 * from struct qpc_state (time.c), read while its seq is even and unchanged,
 * and only within a second of the last resync. Anything else (no state yet,
 * a resync writing or due, an unknown RDTSC scale) jumps on to ntdll's
 * export, the import's address before, which resyncs.
 *
 * The count is RDTSC's shifted right by x64_tsc_shift. FEX's RDTSC is the
 * generic timer shifted left by its TSC scale, which CPUID 15h gives
 * (EBX / EAX = 2^scale, ECX = the timer's frequency); the stub reads it on
 * its first call and keeps the shift, or 0xfe when ECX is not CNTFRQ or the
 * ratio is no power of two. The divisions are RtlQueryPerformanceCounter's,
 * 64-bit as in C. FEX makes RDTSC self-synchronizing (ISB) under the same
 * switch, as qpc_read_cntvct is, so a thread's counts never go back.
 * Arguments: rcx counter; rax, rcx, rdx and r8-r11 are written, rbx is
 * saved around CPUID. The stub ends in its state pointer and target. */
static const BYTE x64_qpc_code[] =
{
    0x49, 0x89, 0xcb,                               /* 00: mov r11,rcx */
    0x4c, 0x8b, 0x05, 0xc6, 0x00, 0x00, 0x00,       /* 03: mov r8,[rip+0xc6] */
    0x41, 0x0f, 0xb6, 0x48, 0x04,                   /* 0a: movzx ecx,byte [r8+0x4] */
    0x80, 0xf9, 0xfe,                               /* 0f: cmp cl,0xfe */
    0x0f, 0x84, 0xaf, 0x00, 0x00, 0x00,             /* 12: je c7 */
    0x77, 0x74,                                     /* 18: ja 8e */
    0x0f, 0x31,                                     /* 1a: rdtsc */
    0x48, 0xc1, 0xe2, 0x20,                         /* 1c: shl rdx,0x20 */
    0x89, 0xc0,                                     /* 20: mov eax,eax */
    0x48, 0x09, 0xd0,                               /* 22: or rax,rdx */
    0x48, 0xd3, 0xe8,                               /* 25: shr rax,cl */
    0x45, 0x8b, 0x08,                               /* 28: mov r9d,[r8] */
    0x41, 0xf7, 0xc1, 0x01, 0x00, 0x00, 0x00,       /* 2b: test r9d,0x1 */
    0x0f, 0x85, 0x8f, 0x00, 0x00, 0x00,             /* 32: jne c7 */
    0x0f, 0xae, 0xe8,                               /* 38: lfence */
    0x4d, 0x8b, 0x50, 0x08,                         /* 3b: mov r10,[r8+0x8] */
    0x49, 0x8b, 0x48, 0x18,                         /* 3f: mov rcx,[r8+0x18] */
    0x49, 0x8b, 0x50, 0x10,                         /* 43: mov rdx,[r8+0x10] */
    0x0f, 0xae, 0xe8,                               /* 47: lfence */
    0x45, 0x3b, 0x08,                               /* 4a: cmp r9d,[r8] */
    0x75, 0x78,                                     /* 4d: jne c7 */
    0x4d, 0x85, 0xd2,                               /* 4f: test r10,r10 */
    0x74, 0x73,                                     /* 52: je c7 */
    0x48, 0x85, 0xc9,                               /* 54: test rcx,rcx */
    0x74, 0x6e,                                     /* 57: je c7 */
    0x49, 0x89, 0xc1,                               /* 59: mov r9,rax */
    0x49, 0x29, 0xc9,                               /* 5c: sub r9,rcx */
    0x4d, 0x39, 0xd1,                               /* 5f: cmp r9,r10 */
    0x73, 0x63,                                     /* 62: jae c7 */
    0x48, 0x89, 0xd1,                               /* 64: mov rcx,rdx */
    0x31, 0xd2,                                     /* 67: xor edx,edx */
    0x49, 0xf7, 0xf2,                               /* 69: div r10 */
    0x4c, 0x69, 0xc8, 0x80, 0x96, 0x98, 0x00,       /* 6c: imul r9,rax,0x989680 */
    0x48, 0x69, 0xc2, 0x80, 0x96, 0x98, 0x00,       /* 73: imul rax,rdx,0x989680 */
    0x31, 0xd2,                                     /* 7a: xor edx,edx */
    0x49, 0xf7, 0xf2,                               /* 7c: div r10 */
    0x4c, 0x01, 0xc8,                               /* 7f: add rax,r9 */
    0x48, 0x01, 0xc8,                               /* 82: add rax,rcx */
    0x49, 0x89, 0x03,                               /* 85: mov [r11],rax */
    0xb8, 0x01, 0x00, 0x00, 0x00,                   /* 88: mov eax,0x1 */
    0xc3,                                           /* 8d: ret */
    0x53,                                           /* 8e: push rbx */
    0xb8, 0x15, 0x00, 0x00, 0x00,                   /* 8f: mov eax,0x15 */
    0x31, 0xc9,                                     /* 94: xor ecx,ecx */
    0x0f, 0xa2,                                     /* 96: cpuid */
    0x41, 0xb9, 0xfe, 0x00, 0x00, 0x00,             /* 98: mov r9d,0xfe */
    0x83, 0xf8, 0x01,                               /* 9e: cmp eax,0x1 */
    0x75, 0x1f,                                     /* a1: jne c2 */
    0x8d, 0x53, 0xff,                               /* a3: lea edx,[rbx-0x1] */
    0x85, 0xdb,                                     /* a6: test ebx,ebx */
    0x74, 0x18,                                     /* a8: je c2 */
    0x85, 0xda,                                     /* aa: test edx,ebx */
    0x75, 0x14,                                     /* ac: jne c2 */
    0x49, 0x8b, 0x50, 0x08,                         /* ae: mov rdx,[r8+0x8] */
    0x48, 0x85, 0xd2,                               /* b2: test rdx,rdx */
    0x74, 0x0f,                                     /* b5: je c6 */
    0x89, 0xc9,                                     /* b7: mov ecx,ecx */
    0x48, 0x39, 0xca,                               /* b9: cmp rdx,rcx */
    0x75, 0x04,                                     /* bc: jne c2 */
    0x44, 0x0f, 0xbc, 0xcb,                         /* be: bsf r9d,ebx */
    0x45, 0x88, 0x48, 0x04,                         /* c2: mov byte [r8+0x4],r9b */
    0x5b,                                           /* c6: pop rbx */
    0x4c, 0x89, 0xd9,                               /* c7: mov rcx,r11 */
    0xff, 0x25, 0x08, 0x00, 0x00, 0x00,             /* ca: jmp [rip+0x8] */
};
C_ASSERT( sizeof(x64_qpc_code) == 0xd0 );

static BOOL x64_qpc_fastpath_on(void)
{
    static int on = -1;
    if (on < 0)
    {
        UNICODE_STRING nm, val;
        WCHAR buf[8];
        RtlInitUnicodeString( &nm, L"MADEIRA_X64_QPC_FASTPATH" );
        val.Buffer = buf; val.Length = 0; val.MaximumLength = sizeof(buf);
        on = (!RtlQueryEnvironmentVariable_U( NULL, &nm, &val ) && val.Length && buf[0] == '1');
    }
    return on;
}

/* The x64 stub for an x64 module's import of name resolved to target, or NULL
 * to keep target; the stub's page is made once a process, before it runs. */
static void *x64_qpc_stub_for( HMODULE importer, const char *dll, const char *name, void *target )
{
    static BYTE *stub;
    static void *qpc_target, *qpc_ec;
    static BOOL tried;
    const IMAGE_NT_HEADERS *nt;
    LDR_DATA_TABLE_ENTRY *mod;
    BOOL by_name = FALSE;

    if (strcmp( name, "QueryPerformanceCounter" ) && strcmp( name, "RtlQueryPerformanceCounter" )) return NULL;
    if (!x64_qpc_fastpath_on()) return NULL;
    nt = RtlImageNtHeader( importer );
    if (!nt || nt->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64 || arm64ec_get_module_metadata( importer ))
        return NULL;
    if (LdrFindEntryForAddress( target, &mod ) || mod->DdagNode != node_ntdll)
    {
        /* KERNEL32's QueryPerformanceCounter is a "-import" export (x64 code, jmp [rip+d]
         * through KERNEL32's import of kernelbase's, which is forwarded to ntdll's
         * RtlQueryPerformanceCounter): the same function by Wine's spec files, so it is
         * bound by name. Following the jump bound nothing on the phone (RDR2 run x3); the
         * first such import logs what it resolved to. */
        static int logged;

        if (_stricmp( dll, "kernel32.dll" ) || strcmp( name, "QueryPerformanceCounter" )) return NULL;
        if (!logged++)
        {
            const BYTE *code = target;
            BOOL found = !LdrFindEntryForAddress( target, &mod );

            ERR( "[x64-qpc] KERNEL32.QueryPerformanceCounter resolved to %p (%s, code %02x %02x): bound by name\\n",
                 target, found ? debugstr_w( mod->BaseDllName.Buffer ) : "no module",
                 found ? code[0] : 0, found ? code[1] : 0 );
        }
        by_name = TRUE;
    }

    if (!tried)
    {
        const IMAGE_EXPORT_DIRECTORY *exports;
        DWORD exp_size;
        void *base = NULL, *state = &qpc_state;
        SIZE_T size = 0x1000;
        ULONG old;

        WINE_MODREF *ntdll = find_basename_module( L"ntdll.dll" );

        tried = TRUE;
        if (!ntdll || !(exports = RtlImageDirectoryEntryToData( ntdll->ldr.DllBase, TRUE,
                                                                 IMAGE_DIRECTORY_ENTRY_EXPORT, &exp_size )))
            return NULL;
        qpc_target = find_named_export( ntdll->ldr.DllBase, exports, exp_size, "RtlQueryPerformanceCounter", -1, NULL, NULL, FALSE );
        if (!qpc_target || memcmp( qpc_target, x64_cs_export_thunk, sizeof(x64_cs_export_thunk) ))
        {
            ERR( "[x64-qpc] ntdll's RtlQueryPerformanceCounter %p is not an x64 export thunk; the switch is off\\n",
                 qpc_target );
            return NULL;
        }
        if (NtAllocateVirtualMemory( NtCurrentProcess(), &base, 0, &size, MEM_RESERVE | MEM_COMMIT,
                                     PAGE_EXECUTE_READWRITE ))
        {
            ERR( "[x64-qpc] no page for the stub; the switch is off\\n" );
            return NULL;
        }
        memcpy( base, x64_qpc_code, sizeof(x64_qpc_code) );
        memcpy( (BYTE *)base + sizeof(x64_qpc_code), &state, sizeof(void *) );
        memcpy( (BYTE *)base + sizeof(x64_qpc_code) + sizeof(void *), &qpc_target, sizeof(void *) );
        NtProtectVirtualMemory( NtCurrentProcess(), &base, &size, PAGE_EXECUTE_READ, &old );
        stub = base;
        /* the export thunk ends in jmp rel32 to the ARM64EC function, which an import may hold too */
        qpc_ec = (BYTE *)qpc_target + sizeof(x64_cs_export_thunk) + 4 +
                 *(const INT32 *)((BYTE *)qpc_target + sizeof(x64_cs_export_thunk));
        ERR( "[x64-qpc] x64 QueryPerformanceCounter stub at %p for %p, state %p (MADEIRA_X64_QPC_FASTPATH)\\n",
             stub, qpc_target, state );
    }
    if (!stub || (!by_name && target != qpc_target && target != qpc_ec)) return NULL;
    return stub;
}
"""

QPC_STATE = """
#if defined(__aarch64__) || defined(__arm64ec__)
/* madeira-doge (Playport wine-pe 0052): RtlQueryPerformanceCounter's state (time.c).
 * MADEIRA_X64_QPC_FASTPATH's x64 stub (loader.c) reads it at these offsets: a value
 * is ticks(count) + offset only while seq is even and unchanged across the reads. */
struct qpc_state
{
    volatile LONG seq;       /* 0x00: odd while a resync writes offset and last_sync */
    BYTE x64_tsc_shift;      /* 0x04: the stub's own, RDTSC over the count: 0xff unknown, 0xfe unusable */
    ULONGLONG freq;          /* 0x08: CNTFRQ, set once */
    LONGLONG offset;         /* 0x10: ticks to add, 100 ns */
    ULONGLONG last_sync;     /* 0x18: the count at the last resync, 0 before the first */
};
C_ASSERT( FIELD_OFFSET( struct qpc_state, x64_tsc_shift ) == 0x04 && FIELD_OFFSET( struct qpc_state, freq ) == 0x08 &&
          FIELD_OFFSET( struct qpc_state, offset ) == 0x10 && FIELD_OFFSET( struct qpc_state, last_sync ) == 0x18 );
extern struct qpc_state qpc_state;
#endif
"""

QPC_RESYNC = """
/* madeira-doge (Playport wine-pe 0052): the offset to add after a resync that
 * measured off at count c1: written with c1 as last_sync unless another thread is
 * writing them (it then uses the offset already there, its own on the first sync). */
static LONGLONG qpc_resync( LONGLONG off, ULONGLONG c1 )
{
    LONG seq = qpc_state.seq;

    if ((seq & 1) || InterlockedCompareExchange( &qpc_state.seq, seq + 1, seq ) != seq)
        return qpc_state.last_sync ? qpc_state.offset : off;
    if (!qpc_state.last_sync || off > qpc_state.offset + TICKSPERSEC / 1000) qpc_state.offset = off;
    qpc_state.last_sync = c1;
    off = qpc_state.offset;
    InterlockedExchange( &qpc_state.seq, seq + 2 );
    return off;
}
"""


def patch(wine):
    loader = wine + "/dlls/ntdll/loader.c"
    if MARKER in open(loader, encoding="utf-8").read():
        print("patch-wine-ntdll-x64fast: already in")
        return
    edit(loader, [
        ("    return selected;\n}\n#endif\n\nstatic BOOL import_dll(",
         "    return selected;\n}\n\n" + LOADER_CODE + "#endif\n\nstatic BOOL import_dll(", 1),
        ("    DWORD protect_old;\n\n    thunk_list = get_rva( module, (DWORD)descr->FirstThunk );",
         "    DWORD protect_old;\n#ifdef __arm64ec__\n    unsigned int x64_cs_slots = 0;   /* MADEIRA_X64_CS_FASTPATH / _QPC_FASTPATH */\n#endif\n\n"
         "    thunk_list = get_rva( module, (DWORD)descr->FirstThunk );", 1),
        ("                }\n            }\n#endif\n            TRACE_(imports)(\"--- %s %s.%d = %p\\n\",",
         "                }\n            }\n"
         "            else if (!imp_metadata)\n"
         "            {   /* madeira-doge (Playport): x64 fast paths, each off unless its switch is 1 */\n"
         "                void *stub = x64_cs_stub_for( module, (const char *)pe_name->Name,\n"
         "                                              (void *)thunk_list->u1.Function );\n"
         "                if (!stub) stub = x64_qpc_stub_for( module, name, (const char *)pe_name->Name,\n"
         "                                                    (void *)thunk_list->u1.Function );\n"
         "                if (stub)\n"
         "                {\n"
         "                    thunk_list->u1.Function = (ULONG_PTR)stub;\n"
         "                    x64_cs_slots++;\n"
         "                }\n"
         "            }\n"
         "#endif\n            TRACE_(imports)(\"--- %s %s.%d = %p\\n\",", 1),
        ("done:\n    /* restore old protection of the import address table */",
         "done:\n#ifdef __arm64ec__\n    if (x64_cs_slots)\n"
         "        ERR( \"[x64-cs] %s: %u of its %s imports go to the x64 stubs\\n\",\n"
         "             debugstr_w(wm->ldr.BaseDllName.Buffer), x64_cs_slots, name );\n#endif\n"
         "    /* restore old protection of the import address table */", 1),
    ])
    edit(wine + "/dlls/ntdll/ntdll_misc.h", [
        ("extern void ios_xp_nt_init(void);\n",
         "extern void ios_xp_nt_init(void);\n" + QPC_STATE, 1),
    ])
    text = edit(wine + "/dlls/ntdll/time.c", [
        ("static ULONGLONG qpc_freq, qpc_last_sync;\nstatic LONGLONG qpc_offset;\n",
         "struct qpc_state qpc_state = { .x64_tsc_shift = 0xff };   /* madeira-doge: ntdll_misc.h */\n", 1),
        ("    return (c / qpc_freq) * TICKSPERSEC + (c % qpc_freq) * TICKSPERSEC / qpc_freq;\n}\n",
         "    return (c / qpc_state.freq) * TICKSPERSEC + (c % qpc_state.freq) * TICKSPERSEC / qpc_state.freq;\n}\n"
         + QPC_RESYNC, 1),
        ("    ULONGLONG c;\n\n    if (qpc_disabled) goto slow;\n    if (!qpc_freq)\n",
         "    ULONGLONG c;\n    LONGLONG offset;\n\n    if (qpc_disabled) goto slow;\n    if (!qpc_state.freq)\n", 1),
        ("        qpc_freq = f;\n", "        qpc_state.freq = f;\n", 1),
        ("    if (!qpc_last_sync || c - qpc_last_sync >= qpc_freq)\n",
         "    if (!qpc_state.last_sync || c - qpc_state.last_sync >= qpc_state.freq)\n", 1),
        ("        if (!qpc_last_sync || off > qpc_offset + TICKSPERSEC / 1000) qpc_offset = off;\n"
         "        qpc_last_sync = c1;\n        c = c1;\n    }\n"
         "    counter->QuadPart = (LONGLONG)qpc_to_ticks( c ) + qpc_offset;\n",
         "        offset = qpc_resync( off, c1 );\n        c = c1;\n    }\n"
         "    else offset = qpc_state.offset;\n"
         "    counter->QuadPart = (LONGLONG)qpc_to_ticks( c ) + offset;\n", 1),
        ("t1 = qpc_freq / 1000000;", "t1 = qpc_state.freq / 1000000;", 1),
    ])
    for old in ("qpc_freq", "qpc_last_sync", "qpc_offset"):
        if old in text:
            sys.exit("time.c: %s still used after the edits" % old)
    print("ntdll: MADEIRA_X64_CS_FASTPATH / MADEIRA_X64_QPC_FASTPATH x64 stubs (ntdll-x64fast.dll)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[-1].strip())
    patch(sys.argv[1])
