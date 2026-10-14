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

section .note.GNU-stack noalloc noexec nowrite progbits
