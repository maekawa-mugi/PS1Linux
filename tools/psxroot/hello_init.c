/* PS1Linux MIPS-I/noMMU C init smoke test without a C library.
 * Direct Linux 2.4 syscalls. No global variables, absolute calls, or rodata.
 */
typedef unsigned long word;

static __attribute__((always_inline)) inline long psx_call3(
        word number, word arg0, word arg1, word arg2)
{
    register word v0 __asm__("$2") = number;
    register word a0 __asm__("$4") = arg0;
    register word a1 __asm__("$5") = arg1;
    register word a2 __asm__("$6") = arg2;
    register word a3 __asm__("$7");
    __asm__ volatile("syscall" : "+r"(v0), "=r"(a3)
                     : "r"(a0), "r"(a1), "r"(a2) : "memory");
    return a3 ? -(long)v0 : (long)v0;
}

__attribute__((noreturn, used, section(".text.start")))
void _start(void)
{
    volatile char path[16];
    volatile char msg[14];
    long fd;

    /* Stack-local strings avoid absolute .rodata address relocations. */
    path[0]='/'; path[1]='d'; path[2]='e'; path[3]='v'; path[4]='/';
    path[5]='c'; path[6]='o'; path[7]='n'; path[8]='s'; path[9]='o';
    path[10]='l'; path[11]='e'; path[12]=0;
    fd=psx_call3(5,(word)path,2,0);  /* open("/dev/console", O_RDWR) */
    if (fd < 0) {
        path[5]='t'; path[6]='t'; path[7]='y'; path[8]='1'; path[9]=0;
        fd=psx_call3(5,(word)path,2,0);  /* /dev/tty1 */
    }
    if (fd < 0) {
        path[8]='0';
        fd=psx_call3(5,(word)path,2,0);  /* /dev/tty0 */
    }
    if (fd >= 0) {
        psx_call3(63,(word)fd,1,0); /* dup2(fd, stdout) */
        psx_call3(63,(word)fd,2,0); /* dup2(fd, stderr) */
        msg[0]='P'; msg[1]='S'; msg[2]='1'; msg[3]=' ';
        msg[4]='C'; msg[5]=' '; msg[6]='i'; msg[7]='n';
        msg[8]='i'; msg[9]='t'; msg[10]=' '; msg[11]='O';
        msg[12]='K'; msg[13]='\n';
        psx_call3(4,1,(word)msg,14); /* write(stdout, ...) */
    }

    /* Use PC-relative BEQ: MIPS J would encode an unsafe absolute target. */
    __asm__ volatile(".set push\n.set noreorder\n"
                     "1: addiu $2,$0,29\n"
                     "syscall\n"
                     "beq $0,$0,1b\n"
                     "nop\n.set pop" : : : "memory");
    __builtin_unreachable();
}
