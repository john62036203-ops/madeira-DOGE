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

gdhis:                                   ; GetDescriptorHandleIncrementSize(This, type)
    mov eax, 0x11111111                  ; CBV_SRV_UAV (0) and SAMPLER (1)
    cmp edx, 2
    jb .done
    cmp edx, 3
    ja .done
    mov eax, 0x22222222                  ; RTV (2) and DSV (3)
.done:
    ret
gdhis_end:

; --- build 450: list-side entries -----------------------------------------
; Markers: 0x77777777 = MAD_ROOT_PARAM_MAX, 0x88888888 = offsetof(mad_list, closed),
; 0x99999999 = offsetof(mad_list, ncmds), 0xaaaaaaaa = offsetof(mad_list, ccap),
; 0xbbbbbbbb = offsetof(mad_list, cmds), 0xcccccccc = sizeof(struct mad_cmd),
; 0xdddddddd = MC_ROOT, 0xeeeeeeee = offsetof(mad_cmd, u.root.index), 0x12121212 = offsetof(mad_cmd, u.root.value)
; 0x1313131313131313 = &g_scbv_on (8 bytes). The qword after each `jmp [rip+0]` holds the native entry.

srdt:                                    ; SetGraphicsRootDescriptorTable(list, index, handle)
    cmp edx, 0x77777777
    jae .fb
    cmp dword [rcx + 0x88888888], 0      ; closed
    jne .fb
    mov eax, [rcx + 0x99999999]          ; ncmds
    cmp eax, [rcx + 0xaaaaaaaa]          ; ccap
    jae .fb
    mov r10, 0x1313131313131313
    cmp dword [r10], 0                   ; g_scbv_on > 0 -> the native path records its table
    jg .fb
    mov r10, [rcx + 0xbbbbbbbb]          ; cmds
    mov r11d, 0xcccccccc
    imul r11, rax                        ; ncmds * sizeof cmd
    add r10, r11                         ; c
    inc dword [rcx + 0x99999999]         ; ncmds++
    push rdi
    mov rdi, r10
    xor eax, eax
    mov ecx, 0xcccccccc
    rep stosb                            ; memset(c, 0, sizeof *c)
    pop rdi
    mov dword [r10], 0xdddddddd          ; c->kind = MC_ROOT
    mov [r10 + 0xeeeeeeee], edx          ; c->u.root.index
    mov [r10 + 0x12121212], r8           ; c->u.root.value
    ret
.fb:
    jmp [rel .slot]
.slot: dq 0
srdt_end:

cd:                                      ; CopyDescriptors(This, ndst, dsts, dst_sizes, [nsrc], [srcs], [src_sizes], [type])
    cmp edx, 1
    jne .fb
    mov eax, [rsp+0x28]                  ; nsrc
    cmp eax, 1
    jne .fb
    mov r10, [r8]                        ; dsts[0].ptr
    mov r11, [rsp+0x30]
    mov r11, [r11]                       ; srcs[0].ptr
    test r10, r10
    jz .ret
    test r11, r11
    jz .ret
    mov eax, 1
    test r9, r9
    jz .dok
    mov eax, [r9]                        ; dst_sizes[0]
.dok:
    mov edx, 1
    mov rcx, [rsp+0x38]                  ; src_sizes
    test rcx, rcx
    jz .sok
    mov edx, [rcx]
.sok:
    cmp eax, edx
    cmova eax, edx                       ; take = min
    test eax, eax
    jz .ret
    mov ecx, [rsp+0x40]                  ; type
    mov r9d, 0x11111111
    cmp ecx, 2
    je .rtv
    cmp ecx, 3
    jne .have
.rtv:
    mov r9d, 0x22222222
.have:
    imul rax, r9
    push rdi
    push rsi
    mov rdi, r10
    mov rsi, r11
    mov rcx, rax
    rep movsb
    pop rsi
    pop rdi
.ret:
    ret
.fb:
    jmp [rel .slot]
.slot: dq 0
cd_end:
