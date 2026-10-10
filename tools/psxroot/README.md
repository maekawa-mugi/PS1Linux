# PS1Linux rootfs smoke test

Run the host-side generator check on a Linux machine with Python 3 and
`e2fsprogs`:

```sh
bash tools/psxroot/smoke_test.sh
```

The check builds a **128 KiB** (1024 x 128-byte sectors) test memory-card image
containing the existing `init-probe-v2.bflt` at `/sbin/init`. It verifies:

- The driver-specific BU header (`0x1234`) and declared card size.
- The 1 KiB reserved prefix before the ext2 payload.
- The ext2 superblock, using read-only `e2fsck -fn`.
- The presence of `/sbin/init`, using `debugfs`.

The kernel's default command line is `root=/dev/bu0 console=tty0`.
The generator **does not attach its output to an emulator**. Select the
generated `.mcd` in the emulator's first memory-card slot before booting.

Some emulators support only ordinary 128 KiB PlayStation cards. The generator's
default 8 MiB image is for emulators which explicitly support oversized cards.
For normal card compatibility, pass `--card-blocks 1024`.

If `PSX init OK` appears after the kernel mounts `/dev/bu0`, the included
probe userspace program reached its write syscall. A clean `e2fsck` alone
does not prove the PS1 memory-card protocol, kernel mount, or bFLT execution
works.


## PlayStation GPU console and PS2DEV C init

The generator now creates `/dev/console` (char 5:1), `/dev/null` (1:3),
`/dev/tty0` (4:0), and `/dev/tty1` (4:1) by default. On PlayStation,
PID 1 tries `/dev/console` first and falls back to `/dev/tty1`, then
`/dev/tty0` for standard input/output/error. The separate SIO UART
is `/dev/ttyS0` (4:64) and is not needed for GPU console output.

Build the libc-free C init with the **PS2DEV IOP** compiler (not EE/R5900):

```sh
command -v mipsel-none-elf-gcc
bash tools/psxroot/build_c_probe.sh

mkdir -p rootfs-c/sbin
cp tools/psxroot/init-c-v2.bflt rootfs-c/sbin/init
chmod 755 rootfs-c/sbin/init
python3 tools/psxroot/mkpsxbu.py --from-dir rootfs-c \
    --card-blocks 65536 --inode-count 512 --out rootfs-c-8mb.mcd
```

Attach `rootfs-c-8mb.mcd` to memory-card slot 1 in an emulator and boot
the rebuilt `bin/kernel.exe`. If the GPU VT can be opened, the standalone
PID 1 program should print `PS1 C init OK` and pause. A successful image
build alone does not prove emulator execution.

To build with another toolchain prefix, set `TOOL_PREFIX`.
For host-only smoke testing with LLVM MIPS tools:

```sh
CC=clang LD=ld.lld EXTRA_CC_FLAGS='-target mipsel-none-elf' \
    EXTRA_LD_FLAGS='-m elf32ltsmip' bash tools/psxroot/build_c_probe.sh
```

The minimal C init uses direct Linux 2.4 syscall numbers and only stack
storage. The strict ELF-to-bFLT converter rejects live data sections,
runtime relocations, and absolute MIPS J/JAL instructions. It deliberately
does **not** handle arbitrary C applications or BusyBox yet: those need
proper data layout, address relocations, and a small Linux-compatible libc.
