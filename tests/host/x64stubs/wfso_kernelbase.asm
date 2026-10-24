; madeira-doge x64 fast paths, kernelbase part 2: WaitForSingleObject(h, 0) that
; times out yields the core once (SwitchToThread), so a thread polling a handle
; does not spin a P-core (EXVS2: 1.9M polls/s in battle, log 2026-10-25 01:55).
bits 64
org 0x180085450
wfso_orig:                          ; copy of the WaitForSingleObject FFS
    mov     rax, rsp
    mov     [rax+0x20], rbx
    push    rbp
    pop     rbp
    jmp     0x180068a34
    int3
    int3
wfso:
    test    edx, edx
    jnz     wfso_orig               ; a real wait: unchanged
    sub     rsp, 0x28
    call    wfso_orig
    cmp     eax, 0x102              ; WAIT_TIMEOUT
    jne     .done
    call    0x180084b60             ; SwitchToThread (x64 export)
    mov     eax, 0x102
.done:
    add     rsp, 0x28
    ret
