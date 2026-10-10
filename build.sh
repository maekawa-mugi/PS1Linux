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


# Print the checkout revision only after make AND elf2psx have succeeded.
# This reports the source tree used by the build, not a Git ID embedded in
# the resulting executable. The remote comparison is against cached refs;
# it cannot verify that GitHub has no newer commits without a git fetch.
show_build_revision() {
    local branch commit remote_commit
    commit=$(git -C "$SCRIPT_DIR" rev-parse --verify HEAD)
    branch=$(git -C "$SCRIPT_DIR" symbolic-ref --quiet --short HEAD || printf 'DETACHED')

    printf '\n============================================================\n'
    printf 'PS1Linux: build and PS-EXE conversion completed successfully\n'
    printf 'Output: %s\n' "$SCRIPT_DIR/bin/kernel.exe"
    printf 'Built checkout branch: %s\n' "$branch"
    printf 'Built checkout commit: %s\n' "$commit"

    if [[ "$branch" != DETACHED ]]; then
        remote_commit=$(git -C "$SCRIPT_DIR" rev-parse --verify "refs/remotes/origin/$branch^{commit}" 2>/dev/null || true)
        if [[ -n "$remote_commit" ]]; then
            printf 'Cached origin/%s: %s\n' "$branch" "$remote_commit"
            if [[ "$commit" != "$remote_commit" ]]; then
                printf 'WARNING: checkout differs from cached origin/%s\n' "$branch"
            fi
        else
            printf 'Remote check: origin/%s not fetched locally\n' "$branch"
        fi
    fi
    printf 'NOTE: Remote status is cached; run git fetch to check for new pushes.\n'
    if ! git -C "$SCRIPT_DIR" diff --quiet HEAD -- build.sh linux; then
        printf 'WARNING: tracked source changes are uncommitted (revision alone is insufficient).\n'
    fi
    printf '============================================================\n'
}

build() {
    local config_changed=0
    local need_dep=0
    cd "$SCRIPT_DIR/linux"

    # Preserve objects and generated dependencies by default.
    if (( full_build )); then
        make mrproper
        need_dep=1
    fi

    # oldconfig may legitimately normalize .config, so comparing it
    # directly to Config would cause a full dependency refresh on each
    # invocation. Compare the saved input instead.
    if [[ ! -f .config || ! -f .psx-dep-config ]] ||
       ! cmp -s Config .psx-dep-config; then
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
    show_build_revision
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
