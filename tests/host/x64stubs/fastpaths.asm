; madeira-doge x64 fast paths (tools/patch-pe-x64-fastpaths.py): tiny Win32 calls the
; game makes hundreds of thousands of times a second, as x64 code at their x64
; export (FFS) so they never cross into ARM64EC. TEB: LastErrorValue +0x68,
; TlsSlots +0x1480, TlsExpansionSlots +0x1780 (x64 and ARM64EC share the TEB).
bits 64
get_last_error:                 ; 9 bytes, in place of the FFS
    mov     eax, [gs:0x68]
    ret
set_last_error:                 ; 9 bytes, in place of the FFS
    mov     [gs:0x68], ecx
    ret
tls_get_value:                  ; placed in the padding after .hexpthk
    mov     dword [gs:0x68], 0
    cmp     ecx, 0x3f
    ja      .ext
    mov     ecx, ecx
    mov     rax, [gs:0x1480 + rcx*8]
    ret
.ext:
    lea     eax, [rcx - 0x40]
    cmp     eax, 0x400
    jb      .exp
    xor     eax, eax
    mov     dword [gs:0x68], 87     ; ERROR_INVALID_PARAMETER
    ret
.exp:
    mov     rdx, [gs:0x1780]
    test    rdx, rdx
    jz      .zero
    mov     rax, [rdx + rax*8]
    ret
.zero:
    xor     eax, eax
    ret
