import argparse
import struct
from pathlib import Path


def read_u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def read_u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def pe_sections(data):
    pe = read_u32(data, 0x3C)
    n = read_u16(data, pe + 6)
    opt = read_u16(data, pe + 20)
    image_base = read_u32(data, pe + 24 + 28)
    sec0 = pe + 24 + opt
    out = []
    for i in range(n):
        o = sec0 + i * 40
        name = data[o:o + 8].rstrip(b"\0").decode("ascii", "replace")
        vsize = read_u32(data, o + 8)
        rva = read_u32(data, o + 12)
        raw_size = read_u32(data, o + 16)
        raw = read_u32(data, o + 20)
        out.append((name, rva, vsize, raw, raw_size))
    return image_base, out


def fileoff_to_va(image_base, sections, off):
    for _, rva, vsize, raw, raw_size in sections:
        if raw <= off < raw + raw_size:
            return image_base + rva + (off - raw)
    return None


def va_to_fileoff(sections, va, image_base):
    rva = va - image_base
    for _, srva, _, raw, raw_size in sections:
        if srva <= rva < srva + raw_size:
            return raw + (rva - srva)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("offset", help="file offset of target, hex or decimal")
    args = ap.parse_args()

    data = Path(args.file).read_bytes()
    image_base, sections = pe_sections(data)
    target_off = int(args.offset, 0)
    target_va = fileoff_to_va(image_base, sections, target_off)
    if target_va is None:
        raise SystemExit("offset not in a section")

    needle = struct.pack("<I", target_va)
    print(f"target fileoff=0x{target_off:x} va=0x{target_va:x}")
    for i in range(0, len(data) - 4):
        if data[i:i + 4] == needle:
            va = fileoff_to_va(image_base, sections, i)
            where = f"fileoff=0x{i:x}"
            if va:
                where += f" va=0x{va:x}"
            print(where)


if __name__ == "__main__":
    main()
