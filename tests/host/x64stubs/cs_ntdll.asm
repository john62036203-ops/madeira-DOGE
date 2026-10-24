; madeira-doge x64 fast paths, ntdll part 2 (tools/patch-pe-x64-fastpaths.py):
; uncontended RtlEnterCriticalSection / RtlLeaveCriticalSection as x64 code.
; Contended or unusual cases jump to a copy of the original FFS (the ARM64EC body).
; CRITICAL_SECTION: LockCount +8, RecursionCount +0xc, OwningThread +0x10;
; TEB ClientId.UniqueThread = gs:[0x48].
bits 64
org 0x180093c00
enter_orig:                         ; copy of the RtlEnterCriticalSection FFS
    mov     rax, rsp
    mov     [rax+0x20], rbx
    push    rbp
    pop     rbp
    jmp     0x18006784c
    int3
    int3
leave_orig:                         ; copy of the RtlLeaveCriticalSection FFS
    mov     rax, rsp
    mov     [rax+0x20], rbx
    push    rbp
    pop     rbp
    jmp     0x180067dcc
    int3
    int3
enter:
    mov     eax, -1
    xor     edx, edx
    lock cmpxchg [rcx+8], edx       ; free: LockCount -1 -> 0
    jne     .held
    mov     rax, [gs:0x48]
    mov     [rcx+0x10], rax
    mov     dword [rcx+0xc], 1
    xor     eax, eax
    ret
.held:
    mov     rax, [gs:0x48]
    cmp     [rcx+0x10], rax
    jne     enter_orig              ; another owner: spin / wait in ARM64EC
    lock inc dword [rcx+8]
    inc     dword [rcx+0xc]
    xor     eax, eax
    ret
leave:
    mov     eax, [rcx+0xc]
    cmp     eax, 1
    jg      .nested
    jne     leave_orig              ; not owned: the ARM64EC body reports it
    mov     dword [rcx+0xc], 0
    mov     qword [rcx+0x10], 0
    xor     eax, eax
    mov     edx, -1
    lock cmpxchg [rcx+8], edx       ; no waiter: LockCount 0 -> -1
    jne     .waiters
    xor     eax, eax
    ret
.waiters:                           ; undo, let the ARM64EC body release and wake
    mov     rax, [gs:0x48]
    mov     [rcx+0x10], rax
    mov     dword [rcx+0xc], 1
    jmp     leave_orig
.nested:
    dec     dword [rcx+0xc]
    lock dec dword [rcx+8]
    xor     eax, eax
    ret
