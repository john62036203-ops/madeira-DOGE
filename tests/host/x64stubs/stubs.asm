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

; --- build 471: SetPipelineState / DrawIndexedInstanced ----------------------
; EXVS2 2v2 (log 2026-10-25 14:46, build 470): ~24k and ~23k x64 -> ARM64EC
; crossings a second; natively each is one mad_list_push and a few stores.
; Markers as srdt, plus 0x14141414 = MC_PSO, 0x15151515 = offsetof(mad_cmd, u.pso),
; 0x16161616 = MC_DRAW_INDEXED, 0x17171717 .. 0x1b1b1b1b = offsetof(mad_cmd,
; u.drawi.icount / inst / start / base / istart).

spso:                                    ; SetPipelineState(list, pso)
    cmp dword [rcx + 0x88888888], 0      ; closed
    jne .fb
    mov eax, [rcx + 0x99999999]          ; ncmds
    cmp eax, [rcx + 0xaaaaaaaa]          ; ccap
    jae .fb
    mov r10, [rcx + 0xbbbbbbbb]          ; cmds
    mov r11d, 0xcccccccc
    imul r11, rax
    add r10, r11                         ; c
    inc dword [rcx + 0x99999999]         ; ncmds++
    push rdi
    mov rdi, r10
    xor eax, eax
    mov ecx, 0xcccccccc
    rep stosb                            ; memset(c, 0, sizeof *c)
    pop rdi
    mov dword [r10], 0x14141414          ; c->kind = MC_PSO
    mov [r10 + 0x15151515], rdx          ; c->u.pso
    ret
.fb:
    jmp [rel .slot]
.slot: dq 0
spso_end:

dii:                                     ; DrawIndexedInstanced(list, icount, inst, start, [base], [istart])
    mov r10, 0x1313131313131313
    cmp dword [r10], 0                   ; g_scbv_on > 0 -> the native path latches static CBVs
    jg .fb
    cmp dword [rcx + 0x88888888], 0      ; closed
    jne .fb
    mov eax, [rcx + 0x99999999]          ; ncmds
    cmp eax, [rcx + 0xaaaaaaaa]          ; ccap
    jae .fb
    mov r10, [rcx + 0xbbbbbbbb]          ; cmds
    mov r11d, 0xcccccccc
    imul r11, rax
    add r10, r11                         ; c
    inc dword [rcx + 0x99999999]         ; ncmds++
    push rdi
    mov rdi, r10
    xor eax, eax
    mov ecx, 0xcccccccc
    rep stosb                            ; memset(c, 0, sizeof *c)
    pop rdi
    mov dword [r10], 0x16161616          ; c->kind = MC_DRAW_INDEXED
    mov [r10 + 0x17171717], edx          ; icount
    mov [r10 + 0x18181818], r8d          ; inst
    mov [r10 + 0x19191919], r9d          ; start
    mov eax, [rsp + 0x28]
    mov [r10 + 0x1a1a1a1a], eax          ; base
    mov eax, [rsp + 0x30]
    mov [r10 + 0x1b1b1b1b], eax          ; istart
    ret
.fb:
    jmp [rel .slot]
.slot: dq 0
dii_end:

; --- build 471: ResourceBarrier, the common case ----------------------------
; One transition barrier with no flags on a resource (EXVS2 2v2: ~64k calls a
; second); everything else (n != 1, UAV / aliasing, split barriers, a null
; resource) runs the native entry. Same classification and command folding as
; list_ResourceBarrier. Markers as srdt plus 0x1c1c1c1c = MC_BARRIER,
; 0x21212121 / 0x23232323 / 0x24242424 / 0x25252525 / 0x26262626 / 0x27272727 =
; offsetof(mad_cmd, u.barrier.res / n / all / cls / cls_noref / rank),
; 0x1d1d1d1d1d1d1d1d = &g_bc_war, 0x1e1e1e1e1e1e1e1e = &g_barriers.
; States: W = RENDER_TARGET|UNORDERED_ACCESS|DEPTH_WRITE|STREAM_OUT|COPY_DEST|
; RESOLVE_DEST = 0x151c; the attachment writers RENDER_TARGET|DEPTH_WRITE = 0x14.
; Classes: RAR 0, RAW_ATT 1, RAW_COPY 2, RAW_UAV 3, ALL 4, WAR 6, WAR_ATT 7.

rb:                                      ; ResourceBarrier(list, n, barriers)
    cmp edx, 1
    jne .fb
    cmp dword [r8], 0                    ; D3D12_RESOURCE_BARRIER_TYPE_TRANSITION
    jne .fb
    cmp dword [r8 + 4], 0                ; no BEGIN_ONLY / END_ONLY
    jne .fb
    mov r9, [r8 + 8]                     ; Transition.pResource
    test r9, r9
    jz .fb
    cmp dword [rcx + 0x88888888], 0      ; closed
    jne .fb
    mov eax, [r8 + 20]                   ; StateBefore
    mov r10d, [r8 + 24]                  ; StateAfter
    mov edx, 4                           ; BC_ALL
    test r10d, r10d
    jz .cls
    test eax, eax
    jz .cls
    test r10d, 0x151c
    jz .readafter
    test eax, 0x151c
    jnz .cls                             ; writer -> writer
    mov edx, 7                           ; BC_WAR_ATT
    test r10d, 0xffffffeb
    jz .cls
    mov edx, 6                           ; BC_WAR
    jmp .cls
.readafter:
    xor edx, edx                         ; BC_RAR
    test eax, 0x151c
    jz .cls
    mov edx, 1                           ; BC_RAW_ATT
    test eax, 0xffffffeb
    jz .cls
    mov edx, 2                           ; BC_RAW_COPY
    cmp eax, 0x400
    je .cls
    mov edx, 3                           ; BC_RAW_UAV
    cmp eax, 8
    je .cls
    mov edx, 4                           ; BC_ALL
.cls:
    mov eax, [rcx + 0x99999999]          ; ncmds
    test eax, eax
    jz .push
    lea r11d, [rax - 1]
    imul r11, r11, 0xcccccccc
    add r11, [rcx + 0xbbbbbbbb]          ; the last command
    cmp dword [r11], 0x1c1c1c1c          ; MC_BARRIER: fold into it
    jne .push
    mov r10, r11
    jmp .have
.push:
    cmp eax, [rcx + 0xaaaaaaaa]          ; ccap
    jae .fb
    mov r10, [rcx + 0xbbbbbbbb]
    mov r11d, 0xcccccccc
    imul r11, rax
    add r10, r11
    inc dword [rcx + 0x99999999]         ; ncmds++
    push rdi
    push rcx
    mov rdi, r10
    xor eax, eax
    mov ecx, 0xcccccccc
    rep stosb
    pop rcx
    pop rdi
    mov dword [r10], 0x1c1c1c1c          ; c->kind = MC_BARRIER
.have:
    cmp dword [r10 + 0x23232323], 0      ; n == 0
    jne .noinit
    cmp dword [r10 + 0x24242424], 0      ; && !all
    jne .noinit
    mov byte [r10 + 0x26262626], 255     ; cls_noref = BC_NONE
.noinit:
    mov r11d, 3                          ; rank: ALL 3, WAR 1, RAR 0, RAW 2
    cmp edx, 4
    je .rk
    mov r11d, 1
    cmp edx, 6
    jae .rk
    xor r11d, r11d
    test edx, edx
    jz .rk
    mov r11d, 2
.rk:
    cmp r11b, [r10 + 0x27272727]
    jbe .rkdone
    mov [r10 + 0x27272727], r11b
.rkdone:
    cmp edx, 6
    jb .nowar
    mov r11, 0x1d1d1d1d1d1d1d1d
    lock inc dword [r11]                 ; g_bc_war
.nowar:
    mov r11, 0x1e1e1e1e1e1e1e1e
    lock inc dword [r11]                 ; g_barriers
    mov eax, [r10 + 0x23232323]          ; n
    cmp eax, 8
    jae .overflow
    mov [r10 + rax + 0x25252525], dl     ; cls[n]
    mov [r10 + rax*8 + 0x21212121], r9   ; res[n]
    inc dword [r10 + 0x23232323]
    ret
.overflow:
    mov dword [r10 + 0x24242424], 1      ; all
    mov byte [r10 + 0x26262626], 4       ; cls_noref = BC_ALL
    ret
.fb:
    jmp [rel .slot]
.slot: dq 0
rb_end:
