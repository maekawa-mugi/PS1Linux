#!/usr/bin/env bash
# Build and run the PS1Linux kernel with the supplied MIPS cross-toolchain.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

menuconfig=0
run_after_build=1

build() {
    cd "$SCRIPT_DIR/linux"
    make mrproper
    cp Config .config
    if (( menuconfig )); then
        make menuconfig
    else
        make oldconfig
    fi
    make dep
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
  --menuconfig        Open interactive kernel configuration
  --no-menuconfig     Use the saved kernel config (default)
  --build-only        Build the kernel but do not launch no$psx
  -h, --help          Show this help
Without options, build with the saved Config and run.
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
        --menuconfig)
            menuconfig=1
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
