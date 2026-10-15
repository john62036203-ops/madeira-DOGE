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
global le_set, le_set_end, le_get, le_get_end, tls_get, tls_get_end, fls_get, fls_get_end
global srw_as, srw_as_end, srw_rs, srw_rs_end, srw_ax, srw_ax_end, mem_copy, mem_copy_end, mem_set, mem_set_end

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
; before any store, so overlapping buffers copy correctly. Larger n: native.
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
        ja      mem_copy_end
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
mem_copy_end:

; memset(dst rcx, c edx, n r8) for n <= 128. Larger n: native.
mem_set:
        cmp     r8, 128
        ja      mem_set_end
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
mem_set_end:

%ifidn __OUTPUT_FORMAT__, elf64
section .note.GNU-stack noalloc noexec nowrite progbits
%endif
