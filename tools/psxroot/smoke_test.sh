#!/usr/bin/env bash
# Validate the tiny ext2 filesystem and the PS1Linux-specific BU header.
# Requires Python 3, e2fsprogs (e2fsck and debugfs).
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for cmd in python3 e2fsck debugfs; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Missing prerequisite: $cmd" >&2
        exit 2
    fi
done

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/root/sbin"
cp "$HERE/init-probe-v2.bflt" "$tmp/root/sbin/init"
chmod 755 "$tmp/root/sbin/init"

python3 "$HERE/mkpsxbu.py" --from-dir "$tmp/root" \
    --card-blocks 1024 --dev /dev/ttyS0:c:4:64:0600 \
    --out "$tmp/probe.mcd"

python3 - "$tmp/probe.mcd" "$tmp/root.ext2" <<'PY'
import pathlib
import struct
import sys

raw = pathlib.Path(sys.argv[1]).read_bytes()
if len(raw) != 128 * 1024:
    raise SystemExit(f"Incorrect card size: {len(raw)} bytes")
card_id, blocks, _, card_number = struct.unpack_from("<IIII", raw)
if (card_id, blocks, card_number) != (0x1234, 1024, 0):
    raise SystemExit("Incorrect PS1Linux BU header")
ext2 = raw[1024:]
if struct.unpack_from("<H", ext2, 1024 + 56)[0] != 0xEF53:
    raise SystemExit("Missing ext2 superblock at BU payload + 1024 bytes")
pathlib.Path(sys.argv[2]).write_bytes(ext2)
print("BU header, card size, and ext2 superblock offset: OK")
PY

# -n prevents writes. Nonzero return status indicates an ext2 error to fix.
e2fsck -fn "$tmp/root.ext2"
debugfs -R 'stat /sbin/init' "$tmp/root.ext2" 2>&1 | grep -q 'Inode:'
echo "ext2 metadata and /sbin/init inode: OK"
echo "This is a host-side image test, NOT proof of PS1 emulator boot."
