#!/usr/bin/env bash
# Build and run the PS1Linux kernel with the supplied MIPS cross-toolchain.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

menuconfig=1
run_after_build=1

build() {
    cd "$SCRIPT_DIR/linux"
    make mrproper
    cp Config .config
    make dep
    if (( menuconfig )); then
        make menuconfig
    fi
    make 2>&1 | tee "$SCRIPT_DIR/build.log"
    cd "$SCRIPT_DIR"
    tools/elf2psx/elf2psx -p linux/linux bin/kernel.exe
}

delete() {
    rm -f "$SCRIPT_DIR/bin/kernel.exe"
    cd "$SCRIPT_DIR/linux"
    make mrproper
}

run() {
    cd "$SCRIPT_DIR"
    exec wine './tools/no$psx/NO$PSX.EXE' bin/kernel.exe
}

usage() {
    cat <<'HELP'
Usage: ./build.sh [options]
  -r, --run           Run the already built kernel (no rebuild)
  -d, --delete        Remove kernel.exe and clean kernel build files
  --no-menuconfig     Skip the interactive configuration step
  --build-only        Build the kernel but do not launch no$psx
  -h, --help          Show this help
Without options, build, ask for menuconfig, and run (as before).
HELP
}

for arg in "$@"; do
    case "$arg" in
        -r|--run)
            run
            ;;
        -d|--delete|-deleteall)
            delete
            exit 0
            ;;
        --no-menuconfig)
            menuconfig=0
            ;;
        --build-only)
            run_after_build=0
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown argument: %s\n' "$arg" >&2
            usage >&2
            exit 2
            ;;
    esac
done

build
if (( run_after_build )); then
    run
fi
