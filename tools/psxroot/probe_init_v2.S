
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
