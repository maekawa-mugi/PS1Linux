#!/usr/bin/env python3
"""
mkpsxbu.py - build PS1Linux bu.c-compatible memory-card root images.

This is a clean-room generator derived from linux/drivers/block/bu.c and bu.h.
It does NOT attempt to recreate the lost psx-mcard 0.8.2 source.

Output layout, from bu.c:
  physical block size: 128 bytes
  physical block 0: bu_first_block_t header
  physical blocks 1..7: reserved / hidden from Linux block device
  physical block 8 onward: raw Linux block device contents

The PS1Linux kernel command line in this repo is root=/dev/bu0 console=ttyS0.
The configured filesystem is ext2, so this tool can either wrap a prebuilt ext2
image or build a tiny ext2 rev1 image directly from a directory.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import stat
import struct
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

BU_ID = 0x1234
CARD_BLOCK_SIZE = 128
BU_FIRST_BLOCKS = 8
EXT2_BLOCK_SIZE = 1024
EXT2_SUPER_MAGIC = 0xEF53
EXT2_GOOD_OLD_FIRST_INO = 11
EXT2_GOOD_OLD_INODE_SIZE = 128
EXT2_DYNAMIC_REV = 1
EXT2_FEATURE_INCOMPAT_FILETYPE = 0x0002

# ext2 file types for directory entries
EXT2_FT_UNKNOWN = 0
EXT2_FT_REG_FILE = 1
EXT2_FT_DIR = 2
EXT2_FT_CHRDEV = 3
EXT2_FT_BLKDEV = 4
EXT2_FT_FIFO = 5
EXT2_FT_SOCK = 6
EXT2_FT_SYMLINK = 7

# Linux mode bits
S_IFSOCK = 0o140000
S_IFLNK  = 0o120000
S_IFREG  = 0o100000
S_IFBLK  = 0o060000
S_IFDIR  = 0o040000
S_IFCHR  = 0o020000
S_IFIFO  = 0o010000

ROOT_INO = 2
FIRST_NORMAL_INO = EXT2_GOOD_OLD_FIRST_INO


def ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


def align4(n: int) -> int:
    return (n + 3) & ~3


def set_bit(buf: bytearray, bit: int) -> None:
    buf[bit // 8] |= 1 << (bit % 8)


def is_bit_set(buf: bytes | bytearray, bit: int) -> bool:
    return bool(buf[bit // 8] & (1 << (bit % 8)))


def parse_int(s: str) -> int:
    return int(s, 0)


def old_kdev(major: int, minor: int) -> int:
    # Linux 2.4 kdev_t_to_nr() is the old 8:8 dev_t encoding.
    return ((major & 0xff) << 8) | (minor & 0xff)


@dataclasses.dataclass
class Node:
    path: str
    name: str
    kind: str  # dir, file, symlink, char, block, fifo, sock
    mode: int
    uid: int = 0
    gid: int = 0
    data: bytes = b""
    link_target: str = ""
    rdev: int = 0
    children: List["Node"] = dataclasses.field(default_factory=list)
    ino: int = 0
    blocks: List[int] = dataclasses.field(default_factory=list)
    indirect_block: int = 0
    size: int = 0
    links: int = 1

    def file_type(self) -> int:
        return {
            "file": EXT2_FT_REG_FILE,
            "dir": EXT2_FT_DIR,
            "char": EXT2_FT_CHRDEV,
            "block": EXT2_FT_BLKDEV,
            "fifo": EXT2_FT_FIFO,
            "sock": EXT2_FT_SOCK,
            "symlink": EXT2_FT_SYMLINK,
        }.get(self.kind, EXT2_FT_UNKNOWN)


def mode_kind(st_mode: int) -> Tuple[str, int]:
    perm = stat.S_IMODE(st_mode)
    if stat.S_ISDIR(st_mode):
        return "dir", S_IFDIR | perm
    if stat.S_ISREG(st_mode):
        return "file", S_IFREG | perm
    if stat.S_ISLNK(st_mode):
        return "symlink", S_IFLNK | perm
    if stat.S_ISCHR(st_mode):
        return "char", S_IFCHR | perm
    if stat.S_ISBLK(st_mode):
        return "block", S_IFBLK | perm
    if stat.S_ISFIFO(st_mode):
        return "fifo", S_IFIFO | perm
    if stat.S_ISSOCK(st_mode):
        return "sock", S_IFSOCK | perm
    raise ValueError(f"unsupported file type mode=0o{st_mode:o}")


def read_tree(root: Path, include_default_devs: bool) -> Node:
    root = root.resolve()
    if not root.is_dir():
        raise SystemExit(f"--from-dir must be a directory: {root}")

    def rec(p: Path, rel: str) -> Node:
        st = os.lstat(p)
        kind, mode = mode_kind(st.st_mode)
        node = Node(path=rel or "/", name=p.name if rel else "", kind=kind, mode=mode,
                    uid=st.st_uid & 0xffff, gid=st.st_gid & 0xffff)
        if kind == "dir":
            for child in sorted(p.iterdir(), key=lambda x: x.name):
                if child.name in (".", ".."):
                    continue
                node.children.append(rec(child, f"{rel}/{child.name}" if rel else child.name))
        elif kind == "file":
            node.data = p.read_bytes()
            node.size = len(node.data)
        elif kind == "symlink":
            node.link_target = os.readlink(p)
            node.data = node.link_target.encode("utf-8")
            node.size = len(node.data)
        elif kind in ("char", "block"):
            node.rdev = old_kdev(os.major(st.st_rdev), os.minor(st.st_rdev))
        return node

    root_node = rec(root, "")
    root_node.ino = ROOT_INO
    root_node.mode = S_IFDIR | (stat.S_IMODE(root_node.mode) or 0o755)

    if include_default_devs:
        dev = next((c for c in root_node.children if c.name == "dev" and c.kind == "dir"), None)
        if dev is None:
            dev = Node(path="dev", name="dev", kind="dir", mode=S_IFDIR | 0o755)
            root_node.children.append(dev)
        existing = {c.name for c in dev.children}
        if "console" not in existing:
            dev.children.append(Node(path="dev/console", name="console", kind="char",
                                     mode=S_IFCHR | 0o600, rdev=old_kdev(5, 1)))
        if "null" not in existing:
            dev.children.append(Node(path="dev/null", name="null", kind="char",
                                     mode=S_IFCHR | 0o666, rdev=old_kdev(1, 3)))
        dev.children.sort(key=lambda n: n.name)
        root_node.children.sort(key=lambda n: n.name)

    return root_node


def walk(node: Node) -> Iterable[Node]:
    yield node
    if node.kind == "dir":
        for c in node.children:
            yield from walk(c)


def find_node(root: Node, path: str) -> Optional[Node]:
    for n in walk(root):
        if n.path == path.strip("/") or (path == "/" and n.path == "/"):
            return n
    return None


def add_manifest_dev(root: Node, spec: str) -> None:
    # Format: /path:type:major:minor:mode, e.g. /dev/ttyS0:c:4:64:0600
    parts = spec.split(":")
    if len(parts) != 5:
        raise SystemExit(f"bad --dev spec {spec!r}; use /path:c|b:major:minor:mode")
    path, typ, maj, minr, mode_s = parts
    path = path.strip("/")
    if not path or "/" not in path:
        raise SystemExit(f"bad --dev path {path!r}; use something like /dev/ttyS0")
    kind = {"c": "char", "b": "block"}.get(typ)
    if not kind:
        raise SystemExit(f"bad --dev type {typ!r}; use c or b")
    parent_path, name = path.rsplit("/", 1)
    parent = find_node(root, parent_path)
    if parent is None:
        # create missing parent directories one by one
        cur = root
        sofar = ""
        for component in parent_path.split("/"):
            sofar = f"{sofar}/{component}" if sofar else component
            nxt = next((c for c in cur.children if c.name == component and c.kind == "dir"), None)
            if nxt is None:
                nxt = Node(path=sofar, name=component, kind="dir", mode=S_IFDIR | 0o755)
                cur.children.append(nxt)
                cur.children.sort(key=lambda n: n.name)
            cur = nxt
        parent = cur
    if parent.kind != "dir":
        raise SystemExit(f"parent of --dev is not a directory: /{parent_path}")
    parent.children = [c for c in parent.children if c.name != name]
    perm = int(mode_s, 8)
    parent.children.append(Node(path=path, name=name, kind=kind,
                                mode=(S_IFCHR if kind == "char" else S_IFBLK) | perm,
                                rdev=old_kdev(parse_int(maj), parse_int(minr))))
    parent.children.sort(key=lambda n: n.name)


class Ext2Builder:
    def __init__(self, fs_bytes: int, root: Node, inode_count: int = 128):
        if fs_bytes % EXT2_BLOCK_SIZE != 0:
            raise SystemExit("ext2 payload must be a multiple of 1024 bytes")
        self.fs_bytes = fs_bytes
        self.block_count = fs_bytes // EXT2_BLOCK_SIZE
        if self.block_count < 32:
            raise SystemExit("ext2 payload is too small; need at least 32 KiB")
        self.inode_count = max(32, align4(inode_count))
        if self.inode_count % 8:
            self.inode_count += 8 - (self.inode_count % 8)
        self.root = root
        self.now = int(time.time())
        self.img = bytearray(fs_bytes)
        self.inode_table_blocks = ceil_div(self.inode_count * EXT2_GOOD_OLD_INODE_SIZE, EXT2_BLOCK_SIZE)
        self.super_block = 1
        self.gdt_block = 2
        self.block_bitmap_block = 3
        self.inode_bitmap_block = 4
        self.inode_table_start = 5
        self.first_data_block = self.inode_table_start + self.inode_table_blocks
        self.next_data_block = self.first_data_block
        if self.first_data_block >= self.block_count:
            raise SystemExit("not enough blocks after inode table")
        self.block_bitmap = bytearray(EXT2_BLOCK_SIZE)
        self.inode_bitmap = bytearray(EXT2_BLOCK_SIZE)
        self.used_blocks: set[int] = set()
        self.used_inodes: set[int] = set()

    def alloc_block(self) -> int:
        if self.next_data_block >= self.block_count:
            raise SystemExit("root tree does not fit in this memory-card image")
        b = self.next_data_block
        self.next_data_block += 1
        self.used_blocks.add(b)
        return b

    def assign_inodes(self) -> None:
        next_ino = FIRST_NORMAL_INO
        self.root.ino = ROOT_INO
        for node in walk(self.root):
            if node is self.root:
                continue
            if next_ino > self.inode_count:
                raise SystemExit(f"too many inodes for tiny ext2 image; increase inode_count")
            node.ino = next_ino
            next_ino += 1
        # Mark reserved inodes 1..10 and all real inodes.
        for ino in range(1, FIRST_NORMAL_INO):
            self.used_inodes.add(ino)
        for node in walk(self.root):
            self.used_inodes.add(node.ino)

    def prepare_nodes(self) -> None:
        for node in walk(self.root):
            if node.kind == "dir":
                node.size = EXT2_BLOCK_SIZE
                node.blocks = [self.alloc_block()]
            elif node.kind == "file":
                needed = ceil_div(len(node.data), EXT2_BLOCK_SIZE)
                node.blocks = [self.alloc_block() for _ in range(needed)]
                if needed > 12:
                    node.indirect_block = self.alloc_block()
                node.size = len(node.data)
            elif node.kind == "symlink":
                data = node.link_target.encode("utf-8")
                node.data = data
                node.size = len(data)
                if len(data) > 60:
                    needed = ceil_div(len(data), EXT2_BLOCK_SIZE)
                    node.blocks = [self.alloc_block() for _ in range(needed)]
                    if needed > 12:
                        node.indirect_block = self.alloc_block()
            else:
                node.size = 0

        for node in walk(self.root):
            if node.kind == "dir":
                subdirs = sum(1 for c in node.children if c.kind == "dir")
                node.links = 2 + subdirs
            else:
                node.links = 1

    def write_at_block(self, block: int, data: bytes) -> None:
        start = block * EXT2_BLOCK_SIZE
        self.img[start:start + len(data)] = data

    def write_file_data(self, node: Node) -> None:
        if node.kind not in ("file", "symlink") or not node.blocks:
            return
        for i, b in enumerate(node.blocks):
            chunk = node.data[i * EXT2_BLOCK_SIZE:(i + 1) * EXT2_BLOCK_SIZE]
            self.write_at_block(b, chunk)
        if node.indirect_block:
            ptrs = bytearray(EXT2_BLOCK_SIZE)
            for i, b in enumerate(node.blocks[12:]):
                struct.pack_into("<I", ptrs, i * 4, b)
            self.write_at_block(node.indirect_block, ptrs)

    def dir_entry(self, ino: int, name: str, ftype: int, rec_len: int) -> bytes:
        nb = name.encode("utf-8")
        if len(nb) > 255:
            raise SystemExit(f"filename too long: {name!r}")
        return struct.pack("<IHBB", ino, rec_len, len(nb), ftype) + nb + bytes(rec_len - 8 - len(nb))

    def write_dir_data(self, node: Node, parent_ino: int) -> None:
        entries = [(node.ino, ".", EXT2_FT_DIR), (parent_ino, "..", EXT2_FT_DIR)]
        entries.extend((c.ino, c.name, c.file_type()) for c in node.children)
        parts: List[bytes] = []
        used = 0
        for i, (ino, name, ft) in enumerate(entries):
            name_len = len(name.encode("utf-8"))
            min_len = align4(8 + name_len)
            if i == len(entries) - 1:
                rec_len = EXT2_BLOCK_SIZE - used
            else:
                rec_len = min_len
            if used + rec_len > EXT2_BLOCK_SIZE:
                raise SystemExit(f"directory too large for one-block writer: /{node.path}")
            parts.append(self.dir_entry(ino, name, ft, rec_len))
            used += rec_len
        self.write_at_block(node.blocks[0], b"".join(parts))

    def write_all_data(self) -> None:
        parent: Dict[int, int] = {self.root.ino: self.root.ino}
        for node in walk(self.root):
            if node.kind == "dir":
                for c in node.children:
                    parent[c.ino] = node.ino
        for node in walk(self.root):
            if node.kind == "dir":
                self.write_dir_data(node, parent.get(node.ino, self.root.ino))
            else:
                self.write_file_data(node)

    def inode_bytes(self, node: Node) -> bytes:
        i_block = [0] * 15
        if node.kind in ("char", "block"):
            i_block[0] = node.rdev
        elif node.kind == "symlink" and node.size <= 60:
            raw = node.link_target.encode("utf-8")[:60]
            padded = raw + bytes(60 - len(raw))
            i_block = list(struct.unpack("<15I", padded))
        else:
            for i, b in enumerate(node.blocks[:12]):
                i_block[i] = b
            if node.indirect_block:
                i_block[12] = node.indirect_block
        block_units = 0
        if node.kind in ("file", "dir") or (node.kind == "symlink" and node.blocks):
            allocated = len(node.blocks) + (1 if node.indirect_block else 0)
            block_units = allocated * (EXT2_BLOCK_SIZE // 512)
        fields = [
            node.mode & 0xffff,
            node.uid & 0xffff,
            node.size & 0xffffffff,
            self.now, self.now, self.now,
            0,  # dtime
            node.gid & 0xffff,
            node.links & 0xffff,
            block_units,
            0,  # flags
            0,  # osd1
        ]
        out = bytearray(128)
        struct.pack_into("<HHIIIIIHHIII", out, 0, *fields)
        struct.pack_into("<15I", out, 40, *i_block)
        # generation, file_acl, dir_acl/size_high, faddr remain zero.
        return bytes(out)

    def write_inodes(self) -> None:
        for node in walk(self.root):
            ino = node.ino
            idx = ino - 1
            offset = self.inode_table_start * EXT2_BLOCK_SIZE + idx * EXT2_GOOD_OLD_INODE_SIZE
            self.img[offset:offset + 128] = self.inode_bytes(node)

    def write_bitmaps(self) -> Tuple[int, int, int]:
        # ext2 with 1 KiB blocks has first_data_block=1. Bitmap bit 0 represents block 1.
        system_blocks = set(range(1, self.first_data_block))
        all_used_blocks = system_blocks | self.used_blocks
        for b in sorted(all_used_blocks):
            if b < 1 or b >= self.block_count:
                raise SystemExit(f"internal block out of range: {b}")
            set_bit(self.block_bitmap, b - 1)
        # Mark bitmap padding after last valid block as used.
        valid_data_bits = self.block_count - 1
        for bit in range(valid_data_bits, EXT2_BLOCK_SIZE * 8):
            set_bit(self.block_bitmap, bit)

        for ino in sorted(self.used_inodes):
            if ino < 1 or ino > self.inode_count:
                raise SystemExit(f"internal inode out of range: {ino}")
            set_bit(self.inode_bitmap, ino - 1)
        for bit in range(self.inode_count, EXT2_BLOCK_SIZE * 8):
            set_bit(self.inode_bitmap, bit)

        self.write_at_block(self.block_bitmap_block, self.block_bitmap)
        self.write_at_block(self.inode_bitmap_block, self.inode_bitmap)

        used_block_count = len(all_used_blocks)
        free_blocks = (self.block_count - 1) - used_block_count
        free_inodes = self.inode_count - len(self.used_inodes)
        used_dirs = sum(1 for n in walk(self.root) if n.kind == "dir")
        return free_blocks, free_inodes, used_dirs

    def write_super_and_gdt(self, free_blocks: int, free_inodes: int, used_dirs: int) -> None:
        sb = bytearray(EXT2_BLOCK_SIZE)
        volume = b"PSXROOT".ljust(16, b"\0")
        uuid = bytes.fromhex("70737862752d726f6f74667300000000")  # psxbu-rootfs\0\0...
        # Superblock starts at logical block 1, offset 1024.
        struct.pack_into(
            "<13I6H4I2HIHH3I16s16s64sI",
            sb,
            0,
            self.inode_count,              # s_inodes_count
            self.block_count,              # s_blocks_count, includes block 0
            0,                             # s_r_blocks_count
            free_blocks,                   # s_free_blocks_count
            free_inodes,                   # s_free_inodes_count
            1,                             # s_first_data_block for 1 KiB ext2
            0,                             # s_log_block_size -> 1024
            0,                             # s_log_frag_size
            8192,                          # s_blocks_per_group
            8192,                          # s_frags_per_group
            self.inode_count,              # s_inodes_per_group
            0,                             # s_mtime
            self.now,                      # s_wtime
            0,                             # s_mnt_count
            0xffff,                        # s_max_mnt_count (-1)
            EXT2_SUPER_MAGIC,              # s_magic
            1,                             # s_state: clean
            1,                             # s_errors: continue
            0,                             # s_minor_rev_level
            self.now,                      # s_lastcheck
            0,                             # s_checkinterval
            0,                             # s_creator_os Linux
            EXT2_DYNAMIC_REV,              # s_rev_level
            0, 0,                          # default reserved uid/gid
            FIRST_NORMAL_INO,              # s_first_ino
            EXT2_GOOD_OLD_INODE_SIZE,      # s_inode_size
            0,                             # s_block_group_nr
            0,                             # s_feature_compat
            EXT2_FEATURE_INCOMPAT_FILETYPE,# s_feature_incompat
            0,                             # s_feature_ro_compat
            uuid,
            volume,
            bytes(64),
            0,                             # s_algorithm_usage_bitmap
        )
        self.write_at_block(self.super_block, sb)

        gd = bytearray(EXT2_BLOCK_SIZE)
        struct.pack_into(
            "<IIIHHHHIII",
            gd,
            0,
            self.block_bitmap_block,
            self.inode_bitmap_block,
            self.inode_table_start,
            free_blocks,
            free_inodes,
            used_dirs,
            0,
            0, 0, 0,
        )
        self.write_at_block(self.gdt_block, gd)

    def build(self) -> bytes:
        self.assign_inodes()
        self.prepare_nodes()
        self.write_all_data()
        self.write_inodes()
        free_blocks, free_inodes, used_dirs = self.write_bitmaps()
        self.write_super_and_gdt(free_blocks, free_inodes, used_dirs)
        return bytes(self.img)


def validate_ext2(img: bytes) -> None:
    if len(img) < 2048:
        raise SystemExit("ext2 image is too small")
    magic = struct.unpack_from("<H", img, 1024 + 56)[0]
    if magic != EXT2_SUPER_MAGIC:
        raise SystemExit(f"input does not look like ext2: magic=0x{magic:04x}, expected 0xef53")
    log_block_size = struct.unpack_from("<I", img, 1024 + 24)[0]
    if log_block_size != 0:
        raise SystemExit("this PS1Linux config is safest with 1 KiB ext2 block size; got another block size")


def build_card(ext2_payload: bytes, card_blocks: int, serial: int, number: int) -> bytes:
    if card_blocks < BU_FIRST_BLOCKS + 256:
        raise SystemExit("card block count is implausibly small")
    if card_blocks > 65536:
        raise SystemExit("bu.c uses a 16-bit block number with floor disabled; max practical card-blocks is 65536")
    total_bytes = card_blocks * CARD_BLOCK_SIZE
    payload_bytes = (card_blocks - BU_FIRST_BLOCKS) * CARD_BLOCK_SIZE
    if len(ext2_payload) > payload_bytes:
        raise SystemExit(f"ext2 payload ({len(ext2_payload)} bytes) does not fit; max is {payload_bytes}")
    out = bytearray(total_bytes)
    # bu_first_block_t is read by a mipsel kernel, so all fields are little-endian u32.
    struct.pack_into("<IIII", out, 0, BU_ID, card_blocks, serial & 0xffffffff, number & 0xffffffff)
    out[BU_FIRST_BLOCKS * CARD_BLOCK_SIZE:BU_FIRST_BLOCKS * CARD_BLOCK_SIZE + len(ext2_payload)] = ext2_payload
    return bytes(out)


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description="Build PS1Linux bu.c-compatible memory-card ext2 rootfs images")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-ext2", type=Path, help="wrap an existing raw 1 KiB-block ext2 image")
    src.add_argument("--from-dir", type=Path, help="build a tiny ext2 image from a directory, then wrap it")
    p.add_argument("-o", "--out", type=Path, required=True, help="output .mcd file")
    p.add_argument("--card-blocks", type=parse_int, default=65536,
                   help="128-byte physical blocks claimed by the card; 1024=real 128KiB card, 65536=8MiB emulator card (default)")
    p.add_argument("--serial", type=parse_int, default=0x00010000)
    p.add_argument("--number", type=parse_int, default=0,
                   help="joined-card sequence number; default kernel config ignores it, large-card mode expects 0,1,...")
    p.add_argument("--inode-count", type=parse_int, default=128, help="inodes in generated ext2 image")
    p.add_argument("--no-default-devs", action="store_true", help="do not auto-add /dev/console and /dev/null")
    p.add_argument("--dev", action="append", default=[], help="add device node: /path:c|b:major:minor:mode, e.g. /dev/ttyS0:c:4:64:0600")
    args = p.parse_args(argv)

    payload_bytes = (args.card_blocks - BU_FIRST_BLOCKS) * CARD_BLOCK_SIZE
    if payload_bytes % EXT2_BLOCK_SIZE != 0:
        raise SystemExit("payload size is not divisible by 1024; choose card-blocks divisible by 8")

    if args.from_ext2:
        ext2_img = args.from_ext2.read_bytes()
        validate_ext2(ext2_img)
        ext2_img = ext2_img + bytes(payload_bytes - len(ext2_img))
    else:
        root = read_tree(args.from_dir, include_default_devs=not args.no_default_devs)
        for spec in args.dev:
            add_manifest_dev(root, spec)
        builder = Ext2Builder(payload_bytes, root, inode_count=args.inode_count)
        ext2_img = builder.build()
        validate_ext2(ext2_img)

    card = build_card(ext2_img, args.card_blocks, args.serial, args.number)
    args.out.write_bytes(card)
    ext2_off = BU_FIRST_BLOCKS * CARD_BLOCK_SIZE
    print(f"wrote {args.out} ({len(card)} bytes)")
    print(f"BU header: id=0x{BU_ID:04x}, size/card_blocks={args.card_blocks}, serial=0x{args.serial:x}, number={args.number}")
    print(f"Linux /dev/bu0 payload starts at physical offset {ext2_off} bytes; ext2 superblock at {ext2_off + 1024} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
