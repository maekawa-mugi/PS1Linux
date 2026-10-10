#!/usr/bin/env bash
# libc-free MIPS-I C program for the PS1Linux bFLT rev2 loader.
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
prefix="${TOOL_PREFIX:-mipsel-none-elf-}"
cc="${CC:-${prefix}gcc}"
ld="${LD:-${prefix}ld}"
extra_cc=()
extra_ld=()
if [[ -n "${EXTRA_CC_FLAGS:-}" ]]; then read -r -a extra_cc <<< "$EXTRA_CC_FLAGS"; fi
if [[ -n "${EXTRA_LD_FLAGS:-}" ]]; then read -r -a extra_ld <<< "$EXTRA_LD_FLAGS"; fi
out="${1:-$here/init-c-v2.bflt}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
"$cc" "${extra_cc[@]}" -march=mips1 -mabi=32 -G0 -mno-abicalls -fno-pic \
    -Os -ffreestanding -fno-builtin -fno-stack-protector \
    -fno-jump-tables -fno-unwind-tables -fno-asynchronous-unwind-tables \
    -c "$here/hello_init.c" -o "$tmp/hello_init.o"
"$ld" "${extra_ld[@]}" -T "$here/flat_v2.ld" "$tmp/hello_init.o" -o "$tmp/hello_init.elf"
python3 "$here/elf_to_bflt_v2.py" "$tmp/hello_init.elf" "$out"
