BITS 64
; Windows x64 ABI: rcx, rdx, r8, r9, then stack at [rsp+0x28] after the call.
; Markers (patched at install): 0x11111111 = stride of a CBV/SRV/UAV/sampler descriptor,
; 0x22222222 = stride of an RTV/DSV entry, 0x33333333 = offsetof(mad_resource, heap),
; 0x44444444 = offsetof(mad_resource, gpu_address), 0x55555555 = offsetof(mad_resource, desc),
; 0x66666666 = offsetof(mad_resource, nv12_uv)

cds:                                     ; CopyDescriptorsSimple(This, n, dst, src, type)
    test edx, edx
    jz .ret
    test r8, r8
    jz .ret
    test r9, r9
    jz .ret
    mov eax, [rsp+0x28]                  ; type
    mov r10d, 0x11111111
    cmp eax, 2                           ; D3D12_DESCRIPTOR_HEAP_TYPE_RTV
    je .rtv
    cmp eax, 3                           ; D3D12_DESCRIPTOR_HEAP_TYPE_DSV
    jne .have
.rtv:
    mov r10d, 0x22222222
.have:
    mov eax, edx
    imul rax, r10                        ; bytes
    push rdi
    push rsi
    mov rdi, r8
    mov rsi, r9
    mov rcx, rax
    rep movsb
    pop rsi
    pop rdi
.ret:
    ret
cds_end:

ghp:                                     ; GetHeapProperties(This, props, flags) -> S_OK
    test rdx, rdx
    jz .flags
    mov eax, [rcx + 0x33333333]
    test eax, eax
    jnz .type
    mov eax, 1                           ; D3D12_HEAP_TYPE_DEFAULT
.type:
    mov [rdx], eax
    mov dword [rdx+4], 0
    mov dword [rdx+8], 0
    mov dword [rdx+12], 1
    mov dword [rdx+16], 1
.flags:
    test r8, r8
    jz .done
    mov dword [r8], 0
.done:
    xor eax, eax
    ret
ghp_end:

gdesc:                                   ; GetDesc(This, ret) -> ret
    lea r10, [rcx + 0x55555555]
    mov rax, [r10]
    mov [rdx], rax
    mov rax, [r10+8]
    mov [rdx+8], rax
    mov rax, [r10+16]
    mov [rdx+16], rax
    mov rax, [r10+24]
    mov [rdx+24], rax
    mov rax, [r10+32]
    mov [rdx+32], rax
    mov rax, [r10+40]
    mov [rdx+40], rax
    mov rax, [r10+48]
    mov [rdx+48], rax
    cmp qword [rcx + 0x66666666], 0
    je .out
    mov dword [rdx+32], 103              ; DXGI_FORMAT_NV12
.out:
    mov rax, rdx
    ret
gdesc_end:

ggva:                                    ; GetGPUVirtualAddress(This)
    mov rax, [rcx + 0x44444444]
    ret
ggva_end:
