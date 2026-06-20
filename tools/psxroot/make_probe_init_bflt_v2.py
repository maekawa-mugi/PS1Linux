#!/usr/bin/env python3
from pathlib import Path
import shutil, subprocess, struct, sys
HERE=Path(__file__).resolve().parent
asm=HERE/'probe_init_v2.S'
obj=HERE/'probe_init_v2.o'
text=HERE/'probe_init_v2.text.bin'
out=HERE/'init-probe-v2.bflt'
clang=shutil.which('clang') or '/usr/local/swift/usr/bin/clang'
objcopy=shutil.which('llvm-objcopy') or '/usr/local/swift/usr/bin/llvm-objcopy'
asm.write_text(r'''
.set noreorder
.set noat
.text
.globl _start
_start:
    addiu $sp,$sp,-192

    # mark we reached user code by trying visible ttys.
    bal try_tty1
    nop
    bnez $s1,alive
    nop
    bal try_tty0
    nop
    bnez $s1,alive
    nop
    bal try_ttyS0
    nop
    bnez $s1,alive
    nop
    bal try_console
    nop
    bnez $s1,alive
    nop
    bal try_tty
    nop

alive:
    addiu $v0,$zero,29       # pause()
    syscall
    nop
    beq $zero,$zero,alive
    nop

try_tty1:
    lui $t0,0x7665           # /dev
    ori $t0,$t0,0x642f
    sw $t0,0($sp)
    lui $t0,0x7974           # /tty
    ori $t0,$t0,0x742f
    sw $t0,4($sp)
    ori $t0,$zero,0x0031     # 1\0
    sw $t0,8($sp)
    beq $zero,$zero,try_open
    nop
try_tty0:
    lui $t0,0x7665
    ori $t0,$t0,0x642f
    sw $t0,0($sp)
    lui $t0,0x7974
    ori $t0,$t0,0x742f
    sw $t0,4($sp)
    ori $t0,$zero,0x0030     # 0\0
    sw $t0,8($sp)
    beq $zero,$zero,try_open
    nop
try_ttyS0:
    lui $t0,0x7665
    ori $t0,$t0,0x642f
    sw $t0,0($sp)
    lui $t0,0x7974
    ori $t0,$t0,0x742f
    sw $t0,4($sp)
    ori $t0,$zero,0x3053     # S0\0
    sw $t0,8($sp)
    beq $zero,$zero,try_open
    nop
try_console:
    lui $t0,0x7665           # /dev
    ori $t0,$t0,0x642f
    sw $t0,0($sp)
    lui $t0,0x6e6f           # /con
    ori $t0,$t0,0x632f
    sw $t0,4($sp)
    lui $t0,0x656c           # sole
    ori $t0,$t0,0x6f73
    sw $t0,8($sp)
    ori $t0,$zero,0x0065     # e\0
    sw $t0,12($sp)
    beq $zero,$zero,try_open
    nop
try_tty:
    lui $t0,0x7665           # /dev
    ori $t0,$t0,0x642f
    sw $t0,0($sp)
    lui $t0,0x7974           # /tty
    ori $t0,$t0,0x742f
    sw $t0,4($sp)
    sw $zero,8($sp)
    beq $zero,$zero,try_open
    nop

try_open:
    addu $s1,$zero,$zero
    addu $a0,$sp,$zero
    addiu $a1,$zero,2        # O_RDWR
    addu $a2,$zero,$zero
    addiu $v0,$zero,5        # open
    syscall
    nop
    bnez $a3,try_ret
    nop
    addu $s0,$v0,$zero

    addiu $v0,$zero,63       # dup2(fd,0)
    addu $a0,$s0,$zero
    addu $a1,$zero,$zero
    syscall
    nop
    addiu $v0,$zero,63       # dup2(fd,1)
    addu $a0,$s0,$zero
    addiu $a1,$zero,1
    syscall
    nop
    addiu $v0,$zero,63       # dup2(fd,2)
    addu $a0,$s0,$zero
    addiu $a1,$zero,2
    syscall
    nop

    # "PSX init OK\n" at sp+64
    lui $t0,0x2058
    ori $t0,$t0,0x5350
    sw $t0,64($sp)
    lui $t0,0x7469
    ori $t0,$t0,0x6e69
    sw $t0,68($sp)
    lui $t0,0x0a4b
    ori $t0,$t0,0x4f20
    sw $t0,72($sp)

    addiu $v0,$zero,4        # write(1,msg,12)
    addiu $a0,$zero,1
    addiu $a1,$sp,64
    addiu $a2,$zero,12
    syscall
    nop
    addiu $s1,$zero,1
try_ret:
    jr $ra
    nop
''')
subprocess.check_call([clang,'-target','mipsel-unknown-linux','-march=mips1','-mabi=o32','-mno-abicalls','-fno-pic','-c',str(asm),'-o',str(obj)])
try:
    rel=subprocess.check_output(['readelf','-r',str(obj)],text=True)
    if 'There are no relocations' not in rel:
        raise SystemExit('unexpected relocations:\n'+rel)
except FileNotFoundError:
    pass
subprocess.check_call([objcopy,'-O','binary','-j','.text',str(obj),str(text)])
code=text.read_bytes()
HDR=64
# This old PS1Linux loader does: start_code = codep + text_start; pc = start_code + entry_point.
# Therefore code at file offset 64 needs text_start=64 and entry_point=0.
hdr = b'bFLT' + struct.pack('<10I5I',
    2,              # rev
    0,              # entry_point, relative to text_start
    HDR,            # text_start, file offset where code begins
    HDR+len(code),  # data_start; code_len in loader
    HDR+len(code),  # data_end
    HDR+len(code),  # bss_end
    4096,           # stack_size
    HDR+len(code),  # reloc_start
    0,              # reloc_count
    0x01000000,     # FLAT_FLAG_RAM
    0,0,0,0,0)
out.write_bytes(hdr+code)
print(f'wrote {out} ({out.stat().st_size} bytes), code {len(code)} bytes')
