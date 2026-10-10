#!/usr/bin/env bash
# Build and run the PS1Linux kernel with the supplied MIPS cross-toolchain.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

menuconfig=0
run_after_build=1
full_build=0
# Compile independent units in parallel. The 2.4 makefiles are old:
# if their ordering fails on a given toolchain, use --jobs 1.
jobs=$(( $(nproc) * 2 ))

build() {
    local config_changed=0
    local need_dep=0
    cd "$SCRIPT_DIR/linux"

    # Preserve objects and generated dependencies by default.
    if (( full_build )); then
        make mrproper
        need_dep=1
    fi

    # Avoid rebuilding every object by rewriting .config on each run.
    if [[ ! -f .config ]] || ! cmp -s Config .config; then
        cp Config .config
        config_changed=1
    fi
    if (( menuconfig )); then
        make menuconfig
        config_changed=1
    elif (( config_changed )) || [[ ! -f include/linux/autoconf.h ]]; then
        make oldconfig
    fi

    if (( config_changed )) ||
       [[ ! -f .depend || ! -f include/config/MARKER ]] ||
       [[ ! -f .psx-dep-config ]]; then
        need_dep=1
    elif ! cmp -s Config .psx-dep-config; then
        need_dep=1
    fi
    if (( need_dep )); then
        make dep
        cp Config .psx-dep-config
    fi

    # Keep the log and propagate build failures even with tee.
    make -j"$jobs" 2>&1 | tee "$SCRIPT_DIR/build.log"
    cd "$SCRIPT_DIR"
    tools/elf2psx/elf2psx -p linux/linux bin/kernel.exe
}

delete() {
    rm -f "$SCRIPT_DIR/bin/kernel.exe"
    cd "$SCRIPT_DIR/linux"
    make mrproper
    rm -f .psx-dep-config
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
  --fast              Incremental build (default)
  --full              Clean and regenerate dependencies before building
  --jobs=N            Set parallel make jobs (default: nproc * 2)
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
        --fast)
            full_build=0
            ;;
        --full)
            full_build=1
            ;;
        --jobs)
            printf '%s\n' 'Use --jobs=N to set a parallel job count' >&2
            exit 2
            ;;
        --jobs=*)
            jobs=${arg#--jobs=}
            if [[ ! "$jobs" =~ ^[1-9][0-9]*$ ]]; then
                printf 'Invalid --jobs value: %s\n' "$jobs" >&2
                exit 2
            fi
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
