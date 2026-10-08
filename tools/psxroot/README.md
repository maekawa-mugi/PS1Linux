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

The kernel's default command line is `root=/dev/bu0 console=ttyS0`.
The generator **does not attach its output to an emulator**. Select the
generated `.mcd` in the emulator's first memory-card slot before booting.

Some emulators support only ordinary 128 KiB PlayStation cards. The generator's
default 8 MiB image is for emulators which explicitly support oversized cards.
For normal card compatibility, pass `--card-blocks 1024`.

If `PSX init OK` appears after the kernel mounts `/dev/bu0`, the included
probe userspace program reached its write syscall. A clean `e2fsck` alone
does not prove the PS1 memory-card protocol, kernel mount, or bFLT execution
works.
