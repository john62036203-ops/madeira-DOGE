; madeira-doge trycs-x64 (tools/patch-ntdll-trycs-x64.py): RtlTryEnterCriticalSection
; as x64 code, so a game polling a held lock never crosses into ARM64EC.
; Assembled at 0x180093b00 in ntdll.dll; NtYieldExecution's x64 syscall stub
; is at 0x1800858c0.
bits 64
default rel
org 0x180093b00
try_enter:
    mov     eax, -1
    xor     edx, edx
    lock cmpxchg [rcx+8], edx          ; LockCount -1 -> 0
    jne     .held
.got:
    mov     rax, [gs:0x48]             ; TEB ClientId.UniqueThread
    mov     [rcx+0x10], rax            ; OwningThread
    mov     dword [rcx+0xc], 1         ; RecursionCount
    mov     eax, 1
    ret
.held:
    mov     rax, [gs:0x48]
    cmp     [rcx+0x10], rax
    jne     .spin
    lock inc dword [rcx+8]             ; recursive acquire
    inc     dword [rcx+0xc]
    mov     eax, 1
    ret
.spin:                                 ; wait natively for a short while
    mov     r8d, 64
.loop:
    pause
    cmp     dword [rcx+8], -1
    jne     .next
    mov     eax, -1
    xor     edx, edx
    lock cmpxchg [rcx+8], edx
    je      .got
.next:
    dec     r8d
    jnz     .loop
    sub     rsp, 40                    ; then give the core away once
    call    0x1800858c0                ; NtYieldExecution (adaptive yield: a streak sleeps)
    add     rsp, 40
    xor     eax, eax
    ret
