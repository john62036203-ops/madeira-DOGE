; x64 fast paths for hot Win32 imports (Wine semantics, see dlls/ntdll/sync.c,
; dlls/ntdll/error.c, dlls/kernelbase/thread.c). Each stub is position
; independent; the installer appends the original thunk's jump right after
; the stub ("fallback" = end of stub). TEB is gs:0.
;   RTL_CRITICAL_SECTION: +8 LockCount, +0xc RecursionCount, +0x10 OwningThread
;   TEB: +0x48 ClientId.UniqueThread, +0x68 LastErrorValue, +0x1480 TlsSlots,
;        +0x17c8 FlsSlots (TEB_FLS_DATA: +0x10 fls_data_chunks[0])
bits 64
default rel

global cs_enter, cs_enter_end, cs_leave, cs_leave_end, cs_try, cs_try_end
global cur_tid, cur_tid_end, cur_pid, cur_pid_end, cur_thr, cur_thr_end, cur_proc, cur_proc_end
global le_set, le_set_end, le_get, le_get_end, tls_get, tls_get_end, fls_get, fls_get_end
global srw_as, srw_as_end, srw_rs, srw_rs_end, srw_ax, srw_ax_end, mem_copy, mem_copy_end, mem_set, mem_set_end
global qpc, qpc_end, qpc_e_dis, qpc_e_freq, qpc_e_last, qpc_e_shift, qpc_e_off
global qpcx, qpcx_end, qpcx_e_base, qpcx_e_shift
global qpcw, qpcw_end, qpcw_e_stub, qpcw_e_data, qpcw_e_iv, qpcw_e_delay

cs_enter:
        mov     rdx, [gs:0x48]
        xor     r8d, r8d
        mov     eax, -1
        lock cmpxchg [rcx+8], r8d
        jne     .busy
.owned: mov     [rcx+0x10], rdx
        mov     dword [rcx+0xc], 1
        xor     eax, eax
        ret
.busy:  cmp     [rcx+0x10], rdx
        jne     .spin
        lock inc dword [rcx+8]
        inc     dword [rcx+0xc]
        xor     eax, eax
        ret
.spin:  mov     r9d, 0x5A5A5A5A         ; patched: spin iterations (0 = none)
        test    r9d, r9d
        jz      cs_enter_end
.again: pause
        mov     eax, [rcx+8]
        cmp     eax, -1
        jne     .held
        lock cmpxchg [rcx+8], r8d       ; eax == -1, r8d == 0
        je      .owned
.held:  test    eax, eax
        jg      cs_enter_end            ; more than one waiter: stop spinning
        dec     r9d
        jnz     .again
cs_enter_end:

cs_leave:
        mov     eax, [rcx+0xc]
        cmp     eax, 1
        jne     .notone
        cmp     dword [rcx+8], 0
        jne     cs_leave_end            ; waiters: the real call wakes one
        mov     rdx, [rcx+0x10]
        mov     qword [rcx+0x10], 0
        mov     dword [rcx+0xc], 0
        xor     eax, eax
        mov     r8d, -1
        lock cmpxchg [rcx+8], r8d       ; 0 -> -1 unless a waiter just arrived
        jne     .restore
        ret                             ; eax == 0
.restore:
        mov     dword [rcx+0xc], 1
        mov     [rcx+0x10], rdx
        jmp     cs_leave_end
.notone:
        jl      cs_leave_end            ; not acquired: let the real call report it
        dec     dword [rcx+0xc]
        lock dec dword [rcx+8]
        xor     eax, eax
        ret
cs_leave_end:

cs_try:
        mov     rdx, [gs:0x48]
        xor     r8d, r8d
        mov     eax, -1
        lock cmpxchg [rcx+8], r8d
        jne     .busy
        mov     [rcx+0x10], rdx
        mov     dword [rcx+0xc], 1
        mov     eax, 1
        ret
.busy:  cmp     [rcx+0x10], rdx
        jne     .fail
        lock inc dword [rcx+8]
        inc     dword [rcx+0xc]
        mov     eax, 1
        ret
.fail:  xor     eax, eax
        ret
cs_try_end:

le_set:
        mov     [gs:0x68], ecx
        ret
le_set_end:

le_get:
        mov     eax, [gs:0x68]
        ret
le_get_end:

; GetCurrentThreadId / GetCurrentProcessId: TEB ClientId (+0x48 thread, +0x40
; process); GetCurrentThread / GetCurrentProcess: the pseudo handles -2 / -1.
; EXVS2 2v2 (log 2026-10-25 12:58, build 465): kernel32 GetCurrentThreadId
; ~40k and GetCurrentThread ~10k x64 -> ARM64EC crossings a second.
cur_tid:
        mov     eax, [gs:0x48]
        ret
cur_tid_end:
cur_pid:
        mov     eax, [gs:0x40]
        ret
cur_pid_end:
cur_thr:
        mov     rax, -2
        ret
cur_thr_end:
cur_proc:
        mov     rax, -1
        ret
cur_proc_end:

tls_get:
        cmp     ecx, 64
        jae     tls_get_end
        mov     ecx, ecx
        mov     dword [gs:0x68], 0
        mov     rax, [gs:0x1480+rcx*8]
        ret
tls_get_end:

fls_get:
        lea     eax, [rcx-1]
        cmp     eax, 14                 ; index 1..15 live in chunk 0
        ja      fls_get_end
        mov     rax, [gs:0x17c8]
        test    rax, rax
        jz      fls_get_end
        mov     rax, [rax+0x10]
        test    rax, rax
        jz      .done                   ; no chunk yet: NULL, success
        mov     ecx, ecx
        mov     rax, [rax+rcx*8+8]
.done:  mov     dword [gs:0x68], 0
        ret
fls_get_end:

; SRW locks (dlls/ntdll/sync.c struct srw_lock, one 32-bit word):
;   bits 0..15 exclusive_waiters (bit 0 = held exclusive), bits 16..31 owners.
; Shared acquire: no exclusive holder or waiter -> owners + 1.
srw_as:
        mov     eax, [rcx]
.retry: test    ax, ax
        jnz     srw_as_end
        lea     edx, [rax+0x10000]
        lock cmpxchg [rcx], edx
        jne     .retry
        ret
srw_as_end:

; Shared release with nobody waiting (exclusive_waiters == 0): owners - 1, no
; wake needed (shared waiters only wait while exclusive_waiters != 0).
srw_rs:
        mov     eax, [rcx]
.retry: test    ax, ax
        jnz     srw_rs_end
        cmp     eax, 0x10000
        jb      srw_rs_end              ; not owned shared: Wine reports it
        lea     edx, [rax-0x10000]
        lock cmpxchg [rcx], edx
        jne     .retry
        ret
srw_rs_end:

; Exclusive acquire of a free lock: 0 -> owners 1 | held.
srw_ax:
        xor     eax, eax
        mov     edx, 0x00010001
        lock cmpxchg [rcx], edx
        jne     srw_ax_end
        ret
srw_ax_end:

; memcpy/memmove(dst rcx, src rdx, n r8) for n <= 128: every load happens
; before any store, so overlapping buffers copy correctly. Larger n: see .big.
mem_copy:
        mov     rax, rcx
        cmp     r8, 16
        jb      .lt16
        cmp     r8, 32
        ja      .gt32
        movdqu  xmm0, [rdx]
        movdqu  xmm1, [rdx+r8-16]
        movdqu  [rcx], xmm0
        movdqu  [rcx+r8-16], xmm1
        ret
.gt32:  cmp     r8, 64
        ja      .gt64
        movdqu  xmm0, [rdx]
        movdqu  xmm1, [rdx+16]
        movdqu  xmm2, [rdx+r8-32]
        movdqu  xmm3, [rdx+r8-16]
        movdqu  [rcx], xmm0
        movdqu  [rcx+16], xmm1
        movdqu  [rcx+r8-32], xmm2
        movdqu  [rcx+r8-16], xmm3
        ret
.gt64:  cmp     r8, 128
        ja      .big
        movdqu  xmm0, [rdx]
        movdqu  xmm1, [rdx+16]
        movdqu  xmm2, [rdx+32]
        movdqu  xmm3, [rdx+48]
        movdqu  xmm4, [rdx+r8-64]
        movdqu  xmm5, [rdx+r8-48]
        mov     r9, [rdx+r8-32]
        mov     r10, [rdx+r8-24]
        mov     r11, [rdx+r8-16]
        mov     rax, [rdx+r8-8]
        movdqu  [rcx], xmm0
        movdqu  [rcx+16], xmm1
        movdqu  [rcx+32], xmm2
        movdqu  [rcx+48], xmm3
        movdqu  [rcx+r8-64], xmm4
        movdqu  [rcx+r8-48], xmm5
        mov     [rcx+r8-32], r9
        mov     [rcx+r8-24], r10
        mov     [rcx+r8-16], r11
        mov     [rcx+r8-8], rax
        mov     rax, rcx
        ret
.lt16:  cmp     r8, 8
        jb      .lt8
        mov     r9, [rdx]
        mov     r10, [rdx+r8-8]
        mov     [rcx], r9
        mov     [rcx+r8-8], r10
        ret
.lt8:   cmp     r8, 4
        jb      .lt4
        mov     r9d, [rdx]
        mov     r10d, [rdx+r8-4]
        mov     [rcx], r9d
        mov     [rcx+r8-4], r10d
        ret
.lt4:   test    r8, r8
        jz      .done
        movzx   r9d, byte [rdx]
        movzx   r10d, byte [rdx+r8-1]
        mov     r11, r8
        shr     r11, 1
        movzx   r11d, byte [rdx+r11]
        mov     rdx, r8
        shr     rdx, 1
        mov     [rcx], r9b
        mov     [rcx+r8-1], r10b
        mov     [rcx+rdx], r11b
.done:  ret
; 128 < n <= 32 KB, no forward overlap (dst - src >= n, unsigned): rep movsb,
; which FEX runs as its own unrolled memcpy loop -- no exit to ARM64EC.
; Anything else (dst ahead of src inside the buffer, or larger): native.
.big:   cmp     r8, 32768
        ja      mem_copy_end
        mov     rax, rcx
        sub     rax, rdx
        cmp     rax, r8
        jb      mem_copy_end
        mov     r9, rdi
        mov     r10, rsi
        mov     rdi, rcx
        mov     rsi, rdx
        mov     rax, rcx
        mov     rcx, r8
        rep movsb
        mov     rdi, r9
        mov     rsi, r10
        ret
mem_copy_end:

; memset(dst rcx, c edx, n r8) for n <= 128; larger n: see .big.
mem_set:
        cmp     r8, 128
        ja      .big
        movzx   edx, dl
        mov     r9, 0x0101010101010101
        imul    rdx, r9
        mov     rax, rcx
        cmp     r8, 16
        jb      .lt16
        movq    xmm0, rdx
        punpcklqdq xmm0, xmm0
        cmp     r8, 32
        ja      .gt32
        movdqu  [rcx], xmm0
        movdqu  [rcx+r8-16], xmm0
        ret
.gt32:  cmp     r8, 64
        ja      .gt64
        movdqu  [rcx], xmm0
        movdqu  [rcx+16], xmm0
        movdqu  [rcx+r8-32], xmm0
        movdqu  [rcx+r8-16], xmm0
        ret
.gt64:  movdqu  [rcx], xmm0
        movdqu  [rcx+16], xmm0
        movdqu  [rcx+32], xmm0
        movdqu  [rcx+48], xmm0
        movdqu  [rcx+r8-64], xmm0
        movdqu  [rcx+r8-48], xmm0
        movdqu  [rcx+r8-32], xmm0
        movdqu  [rcx+r8-16], xmm0
        ret
.lt16:  cmp     r8, 8
        jb      .lt8
        mov     [rcx], rdx
        mov     [rcx+r8-8], rdx
        ret
.lt8:   cmp     r8, 4
        jb      .lt4
        mov     [rcx], edx
        mov     [rcx+r8-4], edx
        ret
.lt4:   test    r8, r8
        jz      .done
        mov     r9, r8
        shr     r9, 1
        mov     [rcx], dl
        mov     [rcx+r8-1], dl
        mov     [rcx+r9], dl
.done:  ret
; 128 < n <= 32 KB: rep stosb (FEX's unrolled memset loop). Larger: native.
.big:   cmp     r8, 32768
        ja      mem_set_end
        mov     r9, rdi
        mov     r10, rcx
        mov     rdi, rcx
        movzx   eax, dl
        mov     rcx, r8
        rep stosb
        mov     rdi, r9
        mov     rax, r10
        ret
mem_set_end:

; RtlQueryPerformanceCounter(counter rcx), Wine's iOS user-mode path (ml1117,
; dlls/ntdll/time.c): ticks(c) + qpc_offset with c = CNTVCT_EL0. FEX's rdtsc
; is CNTVCT_EL0 << TSCScale (SmallTSCScale), so c = tsc >> TSCScale (imm8 set
; by the installer). The four rip-relative loads are ntdll's own statics
; (qpc_disabled, qpc_freq, qpc_last_sync, qpc_offset); the installer points
; them there. A resync that is due (c - last >= freq, or no sync yet), the
; disabled path, and a wrong shift (c far outside the window) all run Wine's
; code, which resyncs exactly as before.
qpc:
        cmp     byte [rel qpc_d_dis], 0
qpc_e_dis:
        jne     qpc_end
        mov     r8, [rel qpc_d_freq]
qpc_e_freq:
        test    r8, r8
        jz      qpc_end
        mov     r9, [rel qpc_d_last]
qpc_e_last:
        test    r9, r9
        jz      qpc_end
        rdtsc
        shl     rdx, 32
        or      rax, rdx
        shr     rax, 6
qpc_e_shift:
        mov     r11, rax
        sub     rax, r9
        cmp     rax, r8
        jae     qpc_end
        mov     rax, r11
        xor     edx, edx
        div     r8
        imul    r11, rax, 10000000
        imul    rax, rdx, 10000000
        xor     edx, edx
        div     r8
        add     rax, r11
        add     rax, [rel qpc_d_off]
qpc_e_off:
        mov     [rcx], rax
        mov     eax, 1
        ret
qpc_end:
; placeholders only (the installer rewrites the four displacements)
qpc_d_dis:  db 0
            align 8
qpc_d_freq: dq 0
qpc_d_last: dq 0
qpc_d_off:  dq 0

;
; qpcx: QueryPerformanceCounter from the stub's own state (imm64 before
; qpcx_e_base: +0 the counter frequency, +8 the offset in 100 ns ticks, both
; set by the installer from CNTFRQ_EL0, CNTVCT_EL0 and Wine's monotonic
; counter, the same calibration Wine's RtlQueryPerformanceCounter does, and
; refreshed from the unix side). Used when ntdll's ARM64EC code runs from
; per-process JIT-pool copies: Wine's statics live in each copy, so neither
; the image's (never written) nor one copy's (another process's) can be read
; here. EXVS2 builds 465 (image statics) and 468 (the launcher's pool copy):
; the stub fell back to the EC body on every call, 260k crossings/s. No
; fallback: the counter and the clock are global.
qpcx:
        mov     r10, 0x5a5a5a5a5a5a5a5a
qpcx_e_base:
        rdtsc
        shl     rdx, 32
        or      rax, rdx
        shr     rax, 6
qpcx_e_shift:
        mov     r8, [r10]
        xor     edx, edx
        div     r8
        imul    r11, rax, 10000000
        imul    rax, rdx, 10000000
        xor     edx, edx
        div     r8
        add     rax, r11
        add     rax, [r10+8]
        mov     [rcx], rax
        mov     eax, 1
        ret
qpcx_end:

;
; qpcw: spin throttle in front of the qpc stub (madeira.cfg qpc-spin-sleep-us).
; EXVS2 (log 2026-10-25 09:53, build 458): one game thread calls
; QueryPerformanceCounter 300-600k times a second, every call < 1 us after the
; previous one ([xp-api-qpc] 100% <1us): a busy-wait on the clock that keeps a
; P-core at 100% and heats the SoC into its 1.26 GHz clamp. The wrapper follows
; one thread at a time (the last caller, taken over when the followed one has
; not called for 1 ms); once that thread has made 256 calls each < 1 us apart,
; every 16th call sleeps NtDelayExecution(FALSE, -interval) before returning.
; A sleep does not break the run (the call after it counts as tight); a gap of
; 1 us or more does. Other threads' calls are never delayed. Fix-ups by the
; installer: the rel32 before qpcw_e_stub (-> the qpc stub), the imm32 before
; qpcw_e_iv (relative interval, 100 ns units) and the rel32 before
; qpcw_e_delay (-> ntdll's x64 NtDelayExecution syscall stub), and the imm64
; before qpcw_e_data: the address of the 24-byte state (+0 last count, +8 tid,
; +12 run, +16 slept), which must be WRITABLE memory -- build 462 kept it next
; to the code in ntdll's .hexpthk tail, which is read-only on the device, and
; the launcher died at its first QPC call (log 2026-10-25 11:48, c0000005
; writing ntdll+0x93ea8). State is shared (one followed thread); races only
; blur the heuristic.
qpcw:
        push    rbx
        sub     rsp, 0x30
        mov     rbx, rcx
        call    qpcw
qpcw_e_stub:
        mov     r9, 0x5a5a5a5a5a5a5a5a
qpcw_e_data:
        mov     rcx, [rbx]
        mov     edx, [gs:0x48]
        cmp     edx, [r9+8]
        je      qpcw_same
        mov     r8, rcx
        sub     r8, [r9]
        cmp     r8, 10000
        jb      qpcw_done
        mov     [r9+8], edx
        mov     dword [r9+12], 0
        mov     byte [r9+16], 0
        mov     [r9], rcx
        jmp     qpcw_done
qpcw_same:
        mov     r8, rcx
        sub     r8, [r9]
        mov     [r9], rcx
        cmp     byte [r9+16], 0
        mov     byte [r9+16], 0
        jne     qpcw_tight
        cmp     r8, 10
        jae     qpcw_reset
qpcw_tight:
        inc     dword [r9+12]
        mov     eax, [r9+12]
        cmp     eax, 256
        jb      qpcw_done
        test    eax, 15
        jnz     qpcw_done
        mov     byte [r9+16], 1
        mov     qword [rsp+0x28], -1000
qpcw_e_iv:
        xor     ecx, ecx
        lea     rdx, [rsp+0x28]
        call    qpcw
qpcw_e_delay:
        jmp     qpcw_done
qpcw_reset:
        mov     dword [r9+12], 0
qpcw_done:
        mov     eax, 1
        add     rsp, 0x30
        pop     rbx
        ret
qpcw_end:

%ifidn __OUTPUT_FORMAT__, elf64
section .note.GNU-stack noalloc noexec nowrite progbits
%endif
