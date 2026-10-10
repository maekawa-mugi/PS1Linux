#!/usr/bin/env python3
"""Convert only relocation-free MIPS-I ELF32 text to PS1Linux bFLT rev2.

Not a general elf2flt converter: libc-linked ELF needs relocation handling.
"""
import argparse
import struct
from pathlib import Path


def convert(elf: bytes) -> bytes:
    if len(elf) < 52 or elf[:4] != b'\x7fELF' or elf[4:6] != b'\x01\x01':
        raise ValueError('expected little-endian ELF32')
    if struct.unpack_from('<H', elf, 16)[0] != 2 or struct.unpack_from('<H', elf, 18)[0] != 8:
        raise ValueError('expected executable ELF for MIPS')
    if struct.unpack_from('<I', elf, 24)[0] != 0:
        raise ValueError('entry address must be zero (use flat_v2.ld)')
    shoff = struct.unpack_from('<I', elf, 32)[0]
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', elf, 46)
    if not shoff or shentsize < 40 or not 0 < shnum < 200 or shstrndx >= shnum or shoff + shentsize * shnum > len(elf):
        raise ValueError('bad ELF section table')
    sections = [struct.unpack_from('<10I', elf, shoff + shentsize * n) for n in range(shnum)]
    strings = sections[shstrndx]
    if strings[4] + strings[5] > len(elf):
        raise ValueError('invalid section names')
    strtab = elf[strings[4]:strings[4] + strings[5]]

    def name(section):
        off = section[0]
        if off >= len(strtab):
            raise ValueError('invalid section name offset')
        return strtab[off:].split(b'\0', 1)[0].decode('ascii')

    text = None
    for s in sections:
        secname = name(s)
        typ, flags, vaddr, offset, size = s[1:6]
        if typ in (4, 9) and size:
            raise ValueError('ELF has unresolved relocation entries: ' + secname)
        if (flags & 2) and size and secname != '.text':
            raise ValueError('ELF contains unsupported alloc section: ' + secname)
        if secname == '.text':
            if typ != 1 or not (flags & 2) or vaddr != 0 or not size or offset + size > len(elf):
                raise ValueError('invalid .text section or origin')
            text = elf[offset:offset + size]
    if text is None or len(text) % 4:
        raise ValueError('missing or unaligned MIPS text')
    for i in range(0, len(text), 4):
        opcode = struct.unpack_from('<I', text, i)[0] >> 26
        if opcode in (2, 3):
            raise ValueError(f'absolute J/JAL at .text+0x{i:x}; unsupported without relocation')
    header_size = 64
    data_start = header_size + len(text)
    header = b'bFLT' + struct.pack('<15I',
        2, 0, header_size, data_start, data_start, data_start,
        4096, data_start, 0, 0x01000000, 0, 0, 0, 0, 0)
    assert len(header) == header_size
    return header + text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elf', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = convert(args.elf.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result)
    print(f'wrote {args.output}: {len(result)} bytes, bFLT rev2, {len(result) - 64} bytes of MIPS-I code')


if __name__ == '__main__':
    main()
