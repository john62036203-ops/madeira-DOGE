#!/usr/bin/env python3
"""NtProtectVirtualMemory's [exec-req] path leaves the syscall callback; no Wine runs.

The shipped PE ntdll (app/Madeira/arm64ec-windows/ntdll.dll, built from the wine
fork's dlls/ntdll/signal_arm64ec.c) returns from its ml283 [exec-req] probe
without leave_syscall_callback(), so CHPE_V2_CPU_AREA_INFO::InSyscallCallback
stays set and the next memory notifications on that thread never reach the
emulator (docs/gta5-child-crash.md section 8). build/ntdll-unix/virtual_ios.c
ios_patch_execreq_leave retargets the probe's three exits in the pool copy.

This check compiles the production patch code against the REAL ntdll.dll laid
out as an image, with a model of the JIT pool (one RX/RW alias, owner-aware
translation, a child copy, an x18-patched instruction), and checks:
  - the probe is found exactly once, at VA 0x1800573b8;
  - MADEIRA_EXECREQ_LEAVE unset/0: nothing is written (one "off" line);
  - =1: the three branches hold the expected words, the image is untouched, a
    second call is a no-op, a child's copy is patched without touching the
    parent's, and a copy that differs from the image is refused;
  - control flow: walking the function from the probe's syscall result to `ret`,
    the UNPATCHED code has a path that never reaches the InSyscallCallback clear
    (the bug), the patched code has none;
  - ios_image_section_describe names .text / .data of the image and the
    [prot-img] / [guest-rip-sec] call sites are in place.
Needs python3 and a C compiler (AddressSanitizer/UBSan when available).
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
native = (root / 'build/ntdll-unix/virtual_ios.c').read_text()
loader = (root / 'build/ntdll-unix/loader_ios.c').read_text()
signal = (root / 'build/ntdll-unix/signal_arm64_ios.c').read_text()
ntdll = root / 'app/Madeira/arm64ec-windows/ntdll.dll'


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2] + '\n'


def between(source, first, last):
    start = source.index(first)
    return source[start:source.index(last, start) + len(last)] + '\n'


# Call sites: the session's ntdll (load_ntdll_functions), the EC child ntdll,
# and a pseudo-process child's private copy before it runs.
assert loader.count('ios_patch_execreq_leave( module );') == 2, 'session and EC-child ntdll must be patched'
child = function(loader, 'DECLSPEC_EXPORT void wine_ios_child_main(')
assert child.index('ios_jit_copy_module_for_child(pLdrInitializeThunk, child_peb)') \
    < child.index('ios_patch_execreq_leave_current( pLdrInitializeThunk )') \
    < child.index('server_init_process_done();'), 'the child copy must be patched before the child runs'
protect = function(native, 'static NTSTATUS ios_na_inner_NtProtectVirtualMemory( HANDLE process, PVOID *addr_ptr, SIZE_T *size_ptr,')
# build 327: insc= was always 1 inside the syscall (the wrapper sets the flag
# before it on the notified path too), so [prot-img] no longer prints it.
assert '[prot-img] #%d tid=%04x' in protect and 'status=%#x | %s' in protect and 'insc=%d' not in protect
assert protect.index('[prot-img]') < protect.index('server_leave_uninterrupted_section( &virtual_mutex, &sigset );')
assert '[guest-rip-sec] rip=%p' in signal

code = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static void sys_icache_invalidate( void *p, size_t n ) { (void)p; (void)n; }
void *ios_jit_rx_base_global, *ios_jit_rw_base_global;
size_t ios_jit_pool_size_global;
'''
code += between(native, '#define IOS_JIT_MAX_MAPPINGS', '\n};')
code += 'static struct ios_jit_mapping ios_jit_mappings[IOS_JIT_MAX_MAPPINGS];\n'
code += 'static int ios_jit_mapping_count = 0;\n'
code += r'''
static void *cur_peb;
/* owner-aware, as in virtual_ios.c: the current process's copy, else the NULL-owner one */
void *ios_jit_translate_addr( void *addr )
{
    int i, fb = -1;
    uintptr_t a = (uintptr_t)addr;
    for (i = 0; i < ios_jit_mapping_count; i++)
    {
        uintptr_t b = (uintptr_t)ios_jit_mappings[i].pe_base;
        if (a < b || a >= b + ios_jit_mappings[i].size) continue;
        if (ios_jit_mappings[i].owner_peb == cur_peb) { fb = i; break; }
        if (!ios_jit_mappings[i].owner_peb && fb < 0) fb = i;
    }
    if (fb < 0) return addr;
    return (char *)ios_jit_mappings[fb].jit_base + (a - (uintptr_t)ios_jit_mappings[fb].pe_base);
}
'''
code += between(native, '#define IOS_EXECREQ_WORDS 17u', 'snprintf( buf, len, "%soutside every section (rva %#x, %u sections)", where, off, nsec );\n        return 1;\n    }\n    return 0;\n}')
code += r'''
#define PREF 0x180000000ull
static unsigned char *load_image( const char *path, uint32_t *size_out )
{
    FILE *f = fopen( path, "rb" );
    long n; unsigned char *file, *img; uint32_t lfanew, soi, soh; uint16_t nsec, optsz; unsigned i;
    assert( f );
    fseek( f, 0, SEEK_END ); n = ftell( f ); fseek( f, 0, SEEK_SET );
    file = malloc( n ); assert( fread( file, 1, n, f ) == (size_t)n ); fclose( f );
    memcpy( &lfanew, file + 0x3c, 4 );
    memcpy( &nsec, file + lfanew + 6, 2 ); memcpy( &optsz, file + lfanew + 20, 2 );
    memcpy( &soi, file + lfanew + 24 + 56, 4 ); memcpy( &soh, file + lfanew + 24 + 60, 4 );
    img = aligned_alloc( 0x10000, (soi + 0xffff) & ~0xffffu ); memset( img, 0, soi );
    memcpy( img, file, soh );
    for (i = 0; i < nsec; i++)
    {
        const unsigned char *sh = file + lfanew + 24 + optsz + 40 * i;
        uint32_t vs, va, rs, ro;
        memcpy( &vs, sh + 8, 4 ); memcpy( &va, sh + 12, 4 ); memcpy( &rs, sh + 16, 4 ); memcpy( &ro, sh + 20, 4 );
        memcpy( img + va, file + ro, rs < vs || !vs ? rs : vs );
    }
    free( file );
    *size_out = soi;
    return img;
}

static void dump( const char *tag, const unsigned char *fn )
{
    unsigned i;
    printf( "%s", tag );
    for (i = 0; i < 0x180 / 4; i++) printf( " %08x", ((const uint32_t *)fn)[i] );
    printf( "\n" );
}

int main( int argc, char **argv )
{
    uint32_t soi, rva, want[3];
    unsigned char *img = load_image( argv[1], &soi ), *pool, *orig;
    const int on = argc > 2 && !strcmp( argv[2], "on" );
    char buf[160];
    unsigned long long ib = 0;

    pool = aligned_alloc( 0x10000, 4 * 0x200000 ); memset( pool, 0, 4 * 0x200000 );
    ios_jit_rx_base_global = ios_jit_rw_base_global = pool;
    ios_jit_pool_size_global = 4 * 0x200000;
    /* the session copy (owner NULL) and a child's private copy */
    memcpy( pool, img, soi );
    memcpy( pool + 0x200000, img, soi );
    ios_jit_mappings[0].pe_base = img; ios_jit_mappings[0].jit_base = pool; ios_jit_mappings[0].size = soi;
    ios_jit_mappings[1].pe_base = img; ios_jit_mappings[1].jit_base = pool + 0x200000; ios_jit_mappings[1].size = soi;
    ios_jit_mappings[1].owner_peb = (void *)0x10999c000ull;
    ios_jit_mapping_count = 2;
    orig = malloc( soi ); memcpy( orig, img, soi );

    rva = ios_execreq_find( img );
    printf( "probe rva %#x va %#llx\n", rva, PREF + rva );
    assert( rva && PREF + rva == 0x1800573b8ull );
    /* the x18 patcher rewrites the clear's `ldr x8,[x18,#0x1788]` in every copy */
    ((uint32_t *)(pool + rva + IOS_EXECREQ_CLEAR))[0] = 0x14001234;
    ((uint32_t *)(pool + 0x200000 + rva + IOS_EXECREQ_CLEAR))[0] = 0x14001234;
    dump( "before", pool + rva );

    if (!on)
    {
        assert( ios_patch_execreq_leave( img ) == 0 );
        assert( ios_patch_execreq_leave( img ) == 0 );
        assert( !memcmp( pool + rva, img + rva, IOS_EXECREQ_CLEAR ) );
        printf( "off: nothing written\n" );
        return 0;
    }

    ios_execreq_patched_words( want );
    printf( "words %08x %08x %08x\n", want[0], want[1], want[2] );
    assert( want[0] == 0x54000780 && want[1] == 0xb400088b && want[2] == 0x14000038 );

    /* session copy */
    cur_peb = (void *)0x71ffff0000ull;
    assert( ios_patch_execreq_leave( img ) == 1 );
    assert( ((uint32_t *)(pool + rva))[1] == want[0] );
    assert( ((uint32_t *)(pool + rva))[4] == want[1] );
    assert( ((uint32_t *)(pool + rva))[16] == want[2] );
    assert( !memcmp( img, orig, soi ) );                                   /* image untouched */
    assert( !memcmp( pool + 0x200000 + rva, orig + rva, IOS_EXECREQ_CLEAR ) ); /* child copy untouched */
    assert( ios_patch_execreq_leave( img ) == 0 );                         /* idempotent */
    dump( "after", pool + rva );

    /* the child's private copy, through the shared image */
    cur_peb = (void *)0x10999c000ull;
    assert( ios_patch_execreq_leave_current( img + 0x32d18 ) == 1 );
    assert( ((uint32_t *)(pool + 0x200000 + rva))[16] == want[2] );
    assert( ios_patch_execreq_leave_current( img + 0x32d18 ) == 0 );
    assert( ios_patch_execreq_leave_current( (void *)0x10000 ) == -1 );

    /* a copy that differs from the image is left alone */
    memcpy( pool + 0x200000, img, soi );
    ((uint32_t *)(pool + 0x200000 + rva))[8] ^= 1;
    assert( ios_patch_execreq_leave( img ) == -1 );
    assert( ((uint32_t *)(pool + 0x200000 + rva))[16] == ios_execreq_sig[16] );
    memcpy( pool + 0x200000, img, soi );
    ((uint32_t *)(pool + 0x200000 + rva + IOS_EXECREQ_CLEAR))[2] = 0xd503201f;   /* clear gone */
    assert( ios_patch_execreq_leave( img ) == -1 );

    /* section names */
    assert( ios_image_section_describe( (uintptr_t)img + rva, buf, sizeof(buf), &ib ) && ib == (uintptr_t)img );
    printf( "text: %s\n", buf );
    assert( strstr( buf, "'.text'" ) && strstr( buf, "(R-X CODE)" ) );
    assert( ios_image_section_describe( (uintptr_t)img + 0xd0010, buf, sizeof(buf), NULL ) );
    printf( "data: %s\n", buf );
    assert( strstr( buf, "'.data'" ) && strstr( buf, "(RW-)" ) );
    assert( !ios_image_section_describe( 0x10000, buf, sizeof(buf), NULL ) );
    /* a pool address is named with its copy and that copy's owner (build 327:
     * the child died in the parent's ntdll copy + 0x87050) */
    ib = 0;
    assert( ios_image_section_describe( (uintptr_t)pool + 0x200000 + 0x87050, buf, sizeof(buf), &ib ) &&
            ib == (uintptr_t)img );
    printf( "pool: %s\n", buf );
    assert( strstr( buf, "POOL copy" ) && strstr( buf, "owner=0x10999c000" ) && strstr( buf, "rva 0x87050" ) );

    /* an image without the probe */
    memset( img + rva, 0, 4 );
    assert( ios_patch_execreq_leave( img ) == -1 );
    printf( "on: patched, idempotent, child copy, refusals\n" );
    return 0;
}
'''


def walk(words, start, clear):
    """Every path from `start` to `ret`: does each one pass `clear`?
    words: dict offset->insn (function-relative). Calls (bl/blr) return."""
    bad = []
    seen = set()
    stack = [(start, False)]
    while stack:
        pc, cleared = stack.pop()
        if (pc, cleared) in seen:
            continue
        seen.add((pc, cleared))
        if pc == clear:
            cleared = True
        w = words.get(pc)
        assert w is not None, hex(pc)
        succ = []
        if w == 0xd65f03c0:                                   # ret
            if not cleared:
                bad.append(pc)
            continue
        if pc == clear:                                       # x18 trampoline: returns to the next insn
            succ = [pc + 4]
        elif (w & 0xfc000000) == 0x14000000:                  # b
            imm = w & 0x03ffffff
            imm -= (1 << 26) if imm & (1 << 25) else 0
            succ = [pc + imm * 4]
        elif (w & 0xff000010) == 0x54000000 or (w & 0x7e000000) == 0x34000000:   # b.cond / cbz / cbnz
            imm = (w >> 5) & 0x7ffff
            imm -= (1 << 19) if imm & (1 << 18) else 0
            succ = [pc + 4, pc + imm * 4]
        elif (w & 0x7e000000) == 0x36000000:                  # tbz / tbnz
            imm = (w >> 5) & 0x3fff
            imm -= (1 << 14) if imm & (1 << 13) else 0
            succ = [pc + 4, pc + imm * 4]
        else:                                                 # anything else, calls included, falls through
            succ = [pc + 4]
        for s in succ:
            stack.append((s, cleared))
    return bad


with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    source = folder / 'check.c'
    source.write_text(code)
    executable = folder / 'check'
    cc = os.environ.get('CC', 'cc')
    flags = [cc, '-std=gnu11', '-Wall', '-Wextra', '-Wno-unused-function', '-Wno-unused-parameter',
             '-Werror', '-g', str(source), '-o', str(executable)]
    sanitize = ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']
    if subprocess.run(flags[:1] + sanitize + flags[1:], capture_output=True).returncode == 0:
        print('built with AddressSanitizer/UBSan')
    else:
        subprocess.run(flags, check=True)
        print('built without sanitizers')

    for value, mode in [(None, 'off'), ('0', 'off'), ('', 'off'), ('1', 'on')]:
        env = dict(os.environ)
        env.pop('MADEIRA_EXECREQ_LEAVE', None)
        if value is not None:
            env['MADEIRA_EXECREQ_LEAVE'] = value
        result = subprocess.run([str(executable), str(ntdll), mode], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        out, err = result.stdout, result.stderr
        print(f'MADEIRA_EXECREQ_LEAVE={value!r}: ' + out.strip().splitlines()[-1])
        if mode == 'off':
            assert err.count('[execreq-leave] off') == 1 and 'now clears' not in err, err
            continue
        assert err.count('[execreq-leave] ntdll') >= 2 and 'now clears InSyscallCallback (rva 0x573b8' in err, err
        assert 'differs from the image at +0x20' in err and 'the blocks the patch branches to differ' in err, err
        assert 'not found exactly once' in err, err

        def words_of(tag):
            line = next(l for l in out.splitlines() if l.startswith(tag + ' '))
            return {i * 4: int(x, 16) for i, x in enumerate(line.split()[1:])}

        before, after = words_of('before'), words_of('after')
        # the probe's paths start after its own syscall and log line (VA 0x1800573b8 = +0x0)
        bug = walk(before, 0x0, 0x120)
        fixed = walk(after, 0x0, 0x120)
        print(f'unpatched: {len(bug)} path end(s) without the clear; patched: {len(fixed)}')
        assert bug, 'the unpatched probe should reach ret without clearing InSyscallCallback'
        assert not fixed, f'patched probe still reaches ret without the clear: {fixed}'
print('PASS: the [exec-req] leave fix is opt-in, exact, idempotent and per copy, and closes every path')
