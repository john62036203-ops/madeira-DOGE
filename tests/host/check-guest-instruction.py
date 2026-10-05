#!/usr/bin/env python3
"""Exercise production x64 classification, IAT slots and safe fault diagnostics.

No guest binary is executed. A two-section image exposes the old largest-only
classification; data and ARM64 targets must still translate to their copies.
"""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
native = (root / 'build/ntdll-unix/virtual_ios.c').read_text()
process = (root / 'build/ntdll-unix/process_ios.c').read_text()


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start) + 2] + '\n'


first = native.index('#define IOS_JIT_MAX_MAPPINGS')
mapping = native[first:native.index('\n};', first) + 3]
functions = ''.join(function(native, signature) for signature in (
    'void ios_jit_set_text_section(',
    'static int ios_jit_code_bounds(',
    'void *ios_jit_translate_addr_for_owner(',
    'static int ios_va_is_x86_code(',
    'int ios_jit_guest_code_window(',
))
functions += function(process, 'static uint64_t ios_guest_instruction_read(')
functions += function(process, 'static void ios_guest_code_pair(')
functions += function(process, 'static int ios_guest_call_decode(')
functions += function(process, 'static const char *ios_guest_return_kind(')
functions += function(process, 'static void ios_guest_call_dump(')
functions += function(process, 'static void ios_guest_block_dump(')
functions += function(native, 'static unsigned ios_fex_branch_layout_offset(')
functions += function(process, 'static void ios_guest_branch_history_dump(')
functions += function(process, 'static int ios_dump_guest_instruction(')
loop_start = native.index('while (p < end_p)', native.index('/* ml102 FIX:'))
loop = native[loop_start:native.index('static int ml1017_said;', loop_start)]
assert 'ios_dump_guest_instruction( handle, exit_code, rip, cur_teb->Peb );' in process
assert 'ios_jit_mappings[slot].code_range_count = 0;' in native
assert 'memcpy( ios_jit_mappings[slot].code_ranges, m->code_ranges, sizeof m->code_ranges );' in native
assert 'cached = madeira_cfg_bool( "iat-noexec", 0 );' in native
assert 'if (text_size > ios_jit_mappings[i].text_size)' in functions

prefix = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
typedef void *HANDLE;
typedef int32_t LONG;
typedef uint64_t mach_vm_size_t;
typedef uintptr_t mach_vm_address_t;
#define STATUS_PRIVILEGED_INSTRUCTION ((LONG)0xc0000096u)
#define STATUS_ILLEGAL_INSTRUCTION ((LONG)0xc000001du)
#define NtCurrentProcess() ((HANDLE)(intptr_t)-1)
#define KERN_SUCCESS 0
static char output[65536];
static size_t output_size, reads;
static unsigned history_offset;
unsigned ios_fex_branch_history_offset(void) { return history_offset; }
static int empty_success;
static struct { uintptr_t low, high; } allowed[3], denied[4];
static unsigned allowed_count, denied_count;
static void permit(void *base, size_t size)
{
    assert(allowed_count < 3);
    allowed[allowed_count].low = (uintptr_t)base;
    allowed[allowed_count++].high = (uintptr_t)base + size;
}
static int fixture_mprotect(void *base, size_t size, int prot)
{
    int result = mprotect(base, size, prot);
    if (result) return result;
    if (prot == PROT_NONE)
    {
        assert(denied_count < 4);
        denied[denied_count].low = (uintptr_t)base;
        denied[denied_count++].high = (uintptr_t)base + size;
    }
    else for (unsigned i = 0; i < denied_count; i++)
        if (denied[i].low == (uintptr_t)base) denied[i].low = denied[i].high = 0;
    return 0;
}
#define mprotect fixture_mprotect
static int capture(int fd, const char *format, ...)
{
    assert(fd == 2);
    va_list args;
    va_start(args, format);
    int n = vsnprintf(output + output_size, sizeof(output) - output_size, format, args);
    va_end(args);
    assert(n >= 0 && (size_t)n < sizeof(output) - output_size);
    output_size += n;
    return n;
}
#define dprintf capture
static int mach_task_self(void) { return (int)getpid(); }
static int mach_vm_read_overwrite(int task, mach_vm_address_t address, mach_vm_size_t size,
                                  mach_vm_address_t destination, mach_vm_size_t *got)
{
    reads++;
    *got = 0;
    if (empty_success) return KERN_SUCCESS;
    assert(task == (int)getpid());
    int safe = 0;
    for (unsigned i = 0; i < allowed_count; i++)
        if (address >= allowed[i].low && address <= allowed[i].high && size <= allowed[i].high - address)
            safe = 1;
    if (!safe) return 1;
    for (unsigned i = 0; i < denied_count; i++)
        if (address < denied[i].high && address + size > denied[i].low) return 1;
    memcpy((void *)destination, (const void *)address, (size_t)size);
    *got = size;
    return KERN_SUCCESS;
}
''' + mapping + r'''
static struct ios_jit_mapping ios_jit_mappings[IOS_JIT_MAX_MAPPINGS];
static int ios_jit_mapping_count;
'''

suffix = r'''
static int sync_slots(uint64_t *slots, size_t count, void *sync_owner)
{
    uint64_t *p = slots, *end_p = slots + count;
    int x86skip = 0, execskip = 0, fixup_count = 0, region_is_exec = 0;
    uint64_t x86_first = 0, exec_first = 0;
''' + loop + r'''
    (void)x86_first; (void)exec_first;
    return fixup_count;
}
static void map(unsigned i, void *pe, void *copy, void *owner, unsigned machine)
{
    struct ios_jit_mapping *m = &ios_jit_mappings[i];
    memset(m, 0, sizeof(*m));
    m->pe_base = pe; m->jit_base = copy; m->size = 0x8000;
    m->owner_peb = owner; m->machine_valid = 1; m->machine_cached = machine;
    if ((int)i >= ios_jit_mapping_count) ios_jit_mapping_count = (int)i + 1;
}
static void reset_output(void) { output_size = reads = 0; output[0] = 0; }
int main(int argc, char **argv)
{
    assert(argc == 2);
    const size_t page = (size_t)sysconf(_SC_PAGESIZE);
    assert(page == 4096);
    unsigned char *pe = mmap(NULL, 0x8000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    unsigned char *parent = mmap(NULL, 0x8000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    unsigned char *child = mmap(NULL, 0x8000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(pe != MAP_FAILED && parent != MAP_FAILED && child != MAP_FAILED);
    permit(pe, 0x8000); permit(parent, 0x8000); permit(child, 0x8000);
    for (unsigned i = 0; i < 0x8000; i++) pe[i] = (unsigned char)i;
    memcpy(parent, pe, 0x8000); memcpy(child, pe, 0x8000);
    void *owner = (void *)0x4560;
    map(0, pe, parent, NULL, 0x8664);
    ios_jit_set_text_section(pe, 0x1000, 0x1000);
    ios_jit_set_text_section(pe, 0x4000, 0x2000);
    ios_jit_set_text_section(pe, 0x1000, 0x1000); /* duplicate load notification */
    struct ios_jit_mapping *m = &ios_jit_mappings[0];
    assert(m->code_range_count == 2 && m->text_offset == 0x4000 && m->text_size == 0x2000);
    map(1, pe, child, owner, 0x8664);
    ios_jit_mappings[1].code_range_count = m->code_range_count;
    memcpy(ios_jit_mappings[1].code_ranges, m->code_ranges, sizeof(m->code_ranges));
    uintptr_t b = (uintptr_t)pe;
    if (!strcmp(argv[1], "targets"))
    {
        uint64_t slots[] = {b + 0x1100, b + 0x4100, b + 0x3000, 0, 0x9999};
        assert(sync_slots(slots, 5, owner) == 1);
        assert(slots[0] == b + 0x1100 && slots[1] == b + 0x4100);
        assert(slots[2] == (uintptr_t)child + 0x3000 && slots[3] == 0 && slots[4] == 0x9999);
        assert(ios_va_is_x86_code(b + 0x1000) && ios_va_is_x86_code(b + 0x1fff));
        assert(!ios_va_is_x86_code(b + 0x2000) && !ios_va_is_x86_code(b + 0x3fff));
        assert(ios_va_is_x86_code(b + 0x4000) && ios_va_is_x86_code(b + 0x5fff));
        assert(!ios_va_is_x86_code(b + 0x6000));
        m->machine_cached = 0xaa64;
        slots[0] = b + 0x1100;
        assert(sync_slots(slots, 1, owner) == 1 && slots[0] == (uintptr_t)child + 0x1100);
        m->machine_cached = 0x8664;
        m->code_range_count = 0; /* compatibility with an older/partial registry */
        assert(!ios_va_is_x86_code(b + 0x1100) && ios_va_is_x86_code(b + 0x4100));
        m->machine_valid = 0;
        uint32_t lfanew = 0x80; uint16_t machine = 0x8664;
        memcpy(pe + 0x3c, &lfanew, 4); memcpy(pe + lfanew + 4, &machine, 2);
        reads = 0;
        assert(ios_va_is_x86_code(b + 0x4100) && reads == 2);
        assert(ios_va_is_x86_code(b + 0x4101) && reads == 2); /* header memoization */
        m->machine_valid = 0;
        assert(!mprotect(pe, page, PROT_NONE));
        assert(!ios_va_is_x86_code(b + 0x4100));
        assert(!mprotect(pe, page, PROT_READ | PROT_WRITE));
        puts("PASS: real IAT loop preserves both x64 code sections; data/ARM64 and owner routing remain intact");
    }
    else if (!strcmp(argv[1], "snapshot"))
    {
        uint64_t image = 0, start = 0; size_t length = 0;
        assert(ios_jit_guest_code_window(b + 0x1001, &image, &start, &length));
        assert(image == b && start == b + 0x1000 && length == 33);
        assert(ios_jit_guest_code_window(b + 0x1fff, &image, &start, &length));
        assert(start == b + 0x1fef && length == 17);
        assert(!ios_jit_guest_code_window(b + 0x2000, &image, &start, &length));
        m->unmapped = 1; ios_jit_mappings[1].unmapped = 1;
        assert(!ios_jit_guest_code_window(b + 0x1100, &image, &start, &length));
        m->unmapped = 0; ios_jit_mappings[1].unmapped = 0;
        size_t low, high;
        struct ios_jit_mapping malformed = *m;
        malformed.code_ranges[0].offset = SIZE_MAX - 10;
        malformed.code_ranges[0].size = 100;
        assert(!ios_jit_code_bounds(&malformed, 0x1100, &low, &high));
        malformed.code_range_count = IOS_JIT_MAX_CODE_RANGES + 1;
        assert(!ios_jit_code_bounds(&malformed, 0x1100, &low, &high));
        memset(malformed.code_ranges, 0, sizeof(malformed.code_ranges));
        malformed.code_range_count = IOS_JIT_MAX_CODE_RANGES;
        assert(ios_jit_code_bounds(&malformed, 0x4100, &low, &high)); /* largest-field fallback */
        reset_output();
        assert(!ios_dump_guest_instruction(NtCurrentProcess(), 161, b + 0x1100, owner));
        assert(!ios_dump_guest_instruction((HANDLE)0x88, STATUS_PRIVILEGED_INSTRUCTION, b + 0x1100, owner));
        assert(!reads && !output_size);
        child[0x1100] ^= 1;
        assert(ios_dump_guest_instruction(NtCurrentProcess(), STATUS_PRIVILEGED_INSTRUCTION, b + 0x1100, owner));
        assert(strstr(output, "rva=0x1100") && strstr(output, "opcode-offset=16"));
        assert(strstr(output, "snapshot=DIFFER") && reads == 96);
        assert(!memcmp(parent, pe, 0x8000)); /* parent copy must not supply the snapshot */
        child[0x1100] ^= 1;
        reset_output();
        ios_dump_guest_instruction(NtCurrentProcess(), STATUS_ILLEGAL_INSTRUCTION, b + 0x1100, owner);
        assert(strstr(output, "snapshot=MATCH"));
        reset_output();
        assert(!mprotect(child + 0x1000, page, PROT_NONE));
        ios_dump_guest_instruction(NtCurrentProcess(), STATUS_PRIVILEGED_INSTRUCTION, b + 0x1fff, owner);
        assert(strstr(output, "snapshot=INCOMPLETE") && strstr(output, "??"));
        assert(reads == 34); /* clipped to this section, no access into .data */
        assert(!mprotect(child + 0x1000, page, PROT_READ | PROT_WRITE));
        reset_output(); empty_success = 1;
        ios_dump_guest_instruction(NULL, STATUS_PRIVILEGED_INSTRUCTION, b + 0x1100, owner);
        assert(strstr(output, "snapshot=INCOMPLETE"));
        empty_success = 0;
        reset_output();
        for (unsigned i = 0; i < 64; i++)
            ios_dump_guest_instruction(NULL, STATUS_PRIVILEGED_INSTRUCTION, b + 0x1100, owner);
        assert(reads == 12 * 96); /* first four reports consumed above; 16 total */
        assert(!ios_dump_guest_instruction(NULL, STATUS_PRIVILEGED_INSTRUCTION, b + 0x1100, owner));
        assert(reads == 12 * 96); /* extended path also disabled by the exhausted report budget */
        reset_output(); unsigned char unused[48] = {0};
        assert(!ios_guest_instruction_read("invalid", UINT64_MAX - 2, 48, unused));
        assert(!ios_guest_instruction_read("invalid", b, 49, unused));
        assert(!reads && !output_size);
        puts("PASS: clipped code-only snapshots, correct child copy, inaccessible/short reads, bounded output and no guest mutation");
    }
    else if (!strcmp(argv[1], "calls"))
    {
        unsigned n = 0; int32_t relative = 0;
        unsigned char cb[8];
        memset(cb, 0xcc, sizeof(cb)); cb[7] = 0xff;
        assert(!ios_guest_call_decode(cb, &n, &relative)); /* FF at end has no ModR/M */
        const unsigned char forms[][7] = {
            {0xff,0xd0}, {0xff,0x50,0x7f}, {0xff,0x15,1,2,3,4},
            {0xff,0x14,0x85,1,2,3,4}, {0xff,0x94,0x24,1,2,3,4}, {0xff,0x14,0x24}
        };
        const unsigned lengths[] = {2,3,6,7,7,3};
        for (unsigned i = 0; i < 6; i++)
        {
            memset(cb, 0xcc, sizeof(cb));
            memcpy(cb + 8 - lengths[i], forms[i], lengths[i]);
            assert(ios_guest_call_decode(cb, &n, &relative) == 2 && n == lengths[i]);
        }
        memset(cb, 0xcc, sizeof(cb)); cb[6] = 0xff; cb[7] = 0x18; /* far CALL */
        assert(!ios_guest_call_decode(cb, &n, &relative));
        cb[7] = 0xe0; assert(!ios_guest_call_decode(cb, &n, &relative)); /* JMP */
        cb[7] = 0x15; assert(!ios_guest_call_decode(cb, &n, &relative)); /* missing disp32 */
        cb[7] = 0x14; assert(!ios_guest_call_decode(cb, &n, &relative)); /* missing SIB */
        memset(pe + 0x1100, 0x90, 0x40);
        uint64_t ret = b + 0x1108, target = b + 0x1400;
        relative = (int32_t)(target - ret);
        pe[0x1103] = 0xe8; memcpy(pe + 0x1104, &relative, 4);
        memcpy(child, pe, 0x8000);
        memset(parent + 0x1100, 0xcc, 0x40); /* using the parent would be DIFFER */
        reset_output();
        assert(!strcmp(ios_guest_return_kind(ret, &n, &relative), "CALL") && n == 5);
        assert(relative == (int32_t)(target - ret) && reads == 1);
        ios_guest_call_dump(ret, n, relative, 1, 0x38, target, owner);
        assert(strstr(output, "candidate sp+038") && strstr(output, "equals-fault=1"));
        assert(strstr(output, "call-site snapshot=MATCH") && strstr(output, "call-target snapshot=MATCH"));
        assert(pe[0x1103] == 0xe8 && child[0x1103] == 0xe8 && parent[0x1103] == 0xcc);
        child[0x1400] ^= 1;
        reset_output();
        ios_guest_call_dump(ret, 5, relative, 1, 0x38, 0, owner);
        assert(strstr(output, "equals-fault=0") && strstr(output, "call-target snapshot=DIFFER"));
        reset_output();
        ios_guest_call_dump(ret, 2, 0, 0, 0x50, target, owner);
        assert(strstr(output, "kind=FF/2") && !strstr(output, "direct-target"));
        reset_output();
        assert(!strcmp(ios_guest_return_kind(b + 0x3008, &n, &relative), "  ?"));
        assert(!strcmp(ios_guest_return_kind(b + 0x1005, &n, &relative), "  ?"));
        assert(!strcmp(ios_guest_return_kind(7, &n, &relative), "  ?") && !reads);
        empty_success = 1;
        assert(!strcmp(ios_guest_return_kind(ret, &n, &relative), "  ?"));
        empty_success = 0;
        reset_output();
        assert(!mprotect(pe + 0x1000, page, PROT_NONE));
        assert(!strcmp(ios_guest_return_kind(ret, &n, &relative), "  ?"));
        assert(!mprotect(pe + 0x1000, page, PROT_READ | PROT_WRITE));
        reset_output();
        ios_guest_call_dump(UINT64_MAX - 2, 5, 10, 1, 0, target, owner);
        ios_guest_call_dump(16, 5, INT32_MIN, 1, 0, target, owner);
        assert(!strstr(output, "direct-target") && !reads); /* overflow/underflow refused */
        reset_output();
        m->machine_cached = 0xaa64;
        assert(!strcmp(ios_guest_return_kind(ret, &n, &relative), "  ?") && !reads);
        puts("PASS: near-CALL shapes, seven-byte SIB, trailing FF bounds, guarded targets, child snapshots and no mutation");
    }
    else if (!strcmp(argv[1], "block"))
    {
        uint64_t block = (uint64_t)(uintptr_t)child + 0x7000;
        uint32_t offset = 64;
        struct { uint64_t size, rip, guest_size; uint32_t count, entries, spin;
                 uint8_t single, pad[3]; } tail = { .size=128, .rip=b+0x10d0,
                     .guest_size=0x80, .count=3, .entries=40, .single=0 };
        memcpy((void *)(uintptr_t)block, &offset, 4);
        memcpy((void *)(uintptr_t)(block + offset), &tail, sizeof(tail));
        reset_output();
        ios_guest_block_dump(block, b + 0x1100, owner);
        assert(strstr(output, "contains-fault=1") && strstr(output, "guest-size=128"));
        assert(strstr(output, "block-entry snapshot=MATCH") && strstr(output, "not compile history"));
        reset_output();
        ios_guest_block_dump(block, b + 0x4000, owner);
        assert(strstr(output, "contains-fault=0"));
        reset_output();
        tail.rip = b + 0x3000; /* metadata readable but guest entry is data */
        memcpy((void *)(uintptr_t)(block + offset), &tail, sizeof(tail));
        ios_guest_block_dump(block, tail.rip, owner);
        assert(reads == 2 && !strstr(output, "block-entry"));
        for (unsigned i = 0; i < 5; i++)
        {
            tail.rip=b+0x1100; tail.guest_size=1; tail.size=128; tail.count=3; tail.single=1;
            if (i == 0) tail.size=80;
            if (i == 1) tail.rip=UINT64_MAX;
            if (i == 2) tail.guest_size=0;
            if (i == 3) tail.count=65537;
            if (i == 4) tail.single=2;
            memcpy((void *)(uintptr_t)(block + offset), &tail, sizeof(tail));
            reset_output(); ios_guest_block_dump(block, b+0x1100, owner);
            assert(strstr(output, "tail unavailable/invalid") && reads == 2);
        }
        offset=UINT32_MAX; memcpy((void *)(uintptr_t)block, &offset, 4);
        reset_output(); ios_guest_block_dump(block, b+0x1100, owner);
        assert(strstr(output, "header unavailable/invalid") && reads == 1);
        reset_output(); ios_guest_block_dump(0, b+0x1100, owner);
        assert(!reads);
        offset=64; memcpy((void *)(uintptr_t)block, &offset, 4);
        reset_output(); empty_success=1;
        ios_guest_block_dump(block, b+0x1100, owner);
        assert(strstr(output, "header unavailable/invalid") && reads == 1);
        empty_success=0;
        assert(!mprotect(child+0x7000, page, PROT_NONE));
        reset_output(); ios_guest_block_dump(block, b+0x1100, owner);
        assert(strstr(output, "header unavailable/invalid"));
        assert(!mprotect(child+0x7000, page, PROT_READ | PROT_WRITE));
        puts("PASS: pinned FEX tail metadata, fault containment, code-only snapshots and malformed/inaccessible refusal");
    }
    else if (!strcmp(argv[1], "edges"))
    {
        uint64_t layout[3] = {UINT64_C(0x314744454742444d), 3800 | (UINT64_C(4096) << 32),
                             272 | (UINT64_C(8) << 32)};
        assert(ios_fex_branch_layout_offset(layout) == 3800);
        for (unsigned i=0;i<7;i++)
        {
            uint64_t bad[3]; memcpy(bad,layout,sizeof(bad));
            if (i==0) bad[0]++;
            if (i==1) bad[1]++;
            if (i==2) bad[1]=8 | (UINT64_C(4096)<<32);
            if (i==3) bad[1]=4088 | (UINT64_C(4096)<<32);
            if (i==4) bad[1]=3800 | (UINT64_C(65536)<<32);
            if (i==5) bad[2]++;
            if (i==6) bad[2]=272 | (UINT64_C(16)<<32);
            assert(!ios_fex_branch_layout_offset(bad));
        }
        struct { uint64_t magic, serial; struct { uint64_t source,target,block,hint; } edges[8]; } history = {0};
        unsigned char *frame = child+0x6000;
        history_offset=3800;
        history.magic=UINT64_C(0x314744454742444d);
        history.serial=10;
        for (unsigned i=0;i<8;i++)
        {
            history.edges[i].source=b+0x1100+i;
            history.edges[i].target=b+0x1800+i;
            history.edges[i].block=(uint64_t)(uintptr_t)child+0x7000;
            history.edges[i].hint=i&3;
        }
        memcpy(frame+history_offset,&history,sizeof(history));
        reset_output(); ios_guest_branch_history_dump(frame,b+0x1801,owner);
        assert(strstr(output,"serial=10 count=8 newest-first"));
        assert(strstr(output,"#0 source=") && strstr(output,"kind=call equals-fault=1"));
        assert(strstr(output,"#7 source=") && !strstr(output,"#8 source="));
        assert(strstr(output,"branch-source snapshot=MATCH"));
        history.serial=2;
        memcpy(frame+history_offset,&history,sizeof(history));
        reset_output(); ios_guest_branch_history_dump(frame,0,owner);
        assert(strstr(output,"count=2") && !strstr(output,"#2 source="));
        history.serial=0;
        memcpy(frame+history_offset,&history,sizeof(history));
        reset_output(); ios_guest_branch_history_dump(frame,0,owner);
        assert(reads==1 && strstr(output,"count=0") && !strstr(output,"#0 source="));
        history_offset=0;
        reset_output(); ios_guest_branch_history_dump(frame,0,owner);
        assert(!reads && strstr(output,"history unavailable"));
        history_offset=3800;
        history.magic=0;
        memcpy(frame+history_offset,&history,sizeof(history));
        reset_output(); ios_guest_branch_history_dump(frame,0,owner);
        assert(reads==1 && strstr(output,"history unavailable"));
        history.magic=UINT64_C(0x314744454742444d);
        reset_output(); ios_guest_branch_history_dump((void *)(uintptr_t)UINT64_MAX,0,owner);
        assert(!reads && strstr(output,"history unavailable"));
        empty_success=1;
        reset_output(); ios_guest_branch_history_dump(frame,0,owner);
        assert(reads==1 && strstr(output,"history unavailable"));
        empty_success=0;
        puts("PASS: versioned DATA layout, bounded live branch ordering, child snapshots, inactive/unreadable/overflow refusal");
    }
    else abort();
    assert(!munmap(pe, 0x8000) && !munmap(parent, 0x8000) && !munmap(child, 0x8000));
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='guest-instruction-') as directory:
    folder = Path(directory)
    code = prefix + functions + suffix
    cc = os.environ.get('CC', 'cc')
    flags = ['-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
             '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1', UBSAN_OPTIONS='halt_on_error=1')
    unit = folder / 'check.c'
    unit.write_text(code)
    binary = folder / 'check'
    subprocess.run([cc, *flags, str(unit), '-o', str(binary)], check=True)
    for case in ('targets', 'snapshot', 'calls', 'block', 'edges'):
        subprocess.run([str(binary), case], env=env, check=True)
    legacy = 'if (!ios_jit_code_bounds( &ios_jit_mappings[i], off, &t_off, &t_sz )) return 0;'
    assert code.count(legacy) == 1
    unit.write_text(code.replace(legacy, '''t_off = ios_jit_mappings[i].text_offset;
        t_sz = ios_jit_mappings[i].text_size;
        if (!t_sz || off < t_off || off >= t_off + t_sz) return 0;'''))
    subprocess.run([cc, *flags, str(unit), '-o', str(binary)], check=True)
    failed = subprocess.run([str(binary), 'targets'], env=env, capture_output=True, text=True)
    assert failed.returncode != 0 and 'sync_slots(slots, 5, owner) == 1' in failed.stderr, failed.stderr
    print('PASS: negative control rejects the original largest-only classification')
    boundary = 'for (k = 2; k <= 7; k++)'
    assert code.count(boundary) == 1
    unit.write_text(code.replace(boundary, 'for (k = 1; k <= 7; k++)'))
    subprocess.run([cc, *flags, str(unit), '-o', str(binary)], check=True)
    failed = subprocess.run([str(binary), 'calls'], env=env, capture_output=True, text=True)
    assert failed.returncode != 0 and 'stack-buffer-overflow' in failed.stderr, failed.stderr
    print('PASS: negative control catches the original trailing-FF out-of-bounds probe')
