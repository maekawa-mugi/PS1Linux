#!/usr/bin/env python3
"""Resolve PCSX-Redux GPU initcall trace tiles to function names.

Nine green squares followed by a red square means --index 9 (0-based).
Run from the PS1Linux repository root after bash build.sh --build-only.
"""
import argparse
import bisect
from pathlib import Path
import re
import struct
import subprocess


def get_initcalls(data):
    if len(data) < 52 or data[:6] != b'\x7fELF\x01\x01':
        raise ValueError("Expected little-endian ELF32 (linux/linux, not bin/kernel.exe)")
    file_type, machine = struct.unpack_from('<HH', data, 16)
    if (file_type, machine) != (2, 8):
        raise ValueError("Expected executable MIPS ELF")
    shoff = struct.unpack_from('<I', data, 32)[0]
    shentsize, shnum, shstridx = struct.unpack_from('<HHH', data, 46)
    if (not shoff or shentsize < 40 or shnum < 2 or
            shstridx >= shnum or shoff + shentsize * shnum > len(data)):
        raise ValueError("Missing or corrupt ELF section table")
    shdrs = [struct.unpack_from('<10I', data, shoff + i * shentsize)
             for i in range(shnum)]
    names_header = shdrs[shstridx]
    names_off, names_size = names_header[4:6]
    if names_off + names_size > len(data):
        raise ValueError("Corrupt ELF string section")
    names = data[names_off:names_off + names_size]
    for sh in shdrs:
        if sh[0] >= len(names):
            continue
        name = names[sh[0]:].split(b'\0', 1)[0]
        if name == b'.initcall.init':
            address, offset, size = sh[3:6]
            if not size or size % 4 or offset + size > len(data):
                raise ValueError("Corrupt .initcall.init section")
            return address, struct.unpack_from('<' + 'I' * (size // 4), data, offset)
    raise ValueError("No .initcall.init section in the linked kernel ELF")


def get_text_symbols(kernel, cross_nm, system_map):
    try:
        result = subprocess.run([cross_nm, '-n', str(kernel)], check=True,
                                capture_output=True, text=True)
        nm_output = result.stdout
    except (OSError, subprocess.CalledProcessError):
        if not system_map.is_file():
            raise ValueError("Cannot run cross nm and System.map does not exist")
        print("Using fallback symbol map:", system_map)
        nm_output = system_map.read_text(encoding='utf-8', errors='replace')
    symbols = []
    boundaries = {}
    for line in nm_output.splitlines():
        m = re.match(r'^\s*([0-9a-fA-F]+)\s+([a-zA-Z])\s+(\S+)', line)
        if not m:
            continue
        address, kind, name = int(m[1], 16), m[2], m[3]
        if name in ('__initcall_start', '__initcall_end'):
            boundaries[name] = address
        if kind in ('t', 'T') and not name.startswith('$'):
            symbols.append((address, name))
    if not symbols:
        raise ValueError("No function symbols found")
    return sorted(symbols), boundaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, default=Path('linux/linux'))
    parser.add_argument('--index', type=int, default=9,
                        help='0-based index of first red tile (default 9)')
    parser.add_argument('--context', type=int, default=4)
    parser.add_argument('--nm', default='mipsel-linux-nm')
    parser.add_argument('--map', type=Path, default=Path('linux/System.map'))
    args = parser.parse_args()
    if args.index < 0 or args.context < 0:
        parser.error("index and context must be nonnegative")
    try:
        start, calls = get_initcalls(args.elf.read_bytes())
        symbols, boundaries = get_text_symbols(args.elf, args.nm, args.map)
        if not 0 <= args.index < len(calls):
            raise ValueError("Initcall index out of range")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if boundaries.get('__initcall_start', start) != start:
        print("Note: section has alignment padding before __initcall_start")
    addresses = [addr for addr, _ in symbols]
    print("Kernel:", args.elf, "Initcalls:", len(calls))
    print("Ordinal  Index  Callback address  Nearest function symbol")
    first = max(0, args.index - args.context)
    last = min(len(calls), args.index + args.context + 1)
    for index in range(first, last):
        address = calls[index]
        pos = bisect.bisect_right(addresses, address) - 1
        if pos < 0:
            name = "<no text symbol found>"
        else:
            base, name = symbols[pos]
            if address != base:
                name += "+0x%x" % (address - base)
        note = "  <-- RED: this initcall has not returned" if index == args.index else ""
        print(f"{index+1:7d} {index:6d}  0x{address:08x}        {name}{note}")


if __name__ == '__main__':
    main()
