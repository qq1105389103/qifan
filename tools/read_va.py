import argparse
import struct
from pathlib import Path


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def sections(data):
    pe = u32(data, 0x3C)
    count = u16(data, pe + 6)
    opt_size = u16(data, pe + 20)
    image_base = u32(data, pe + 24 + 28)
    first = pe + 24 + opt_size
    out = []
    for i in range(count):
        off = first + i * 40
        name = data[off : off + 8].rstrip(b"\0").decode("ascii", "replace")
        rva = u32(data, off + 12)
        raw_size = u32(data, off + 16)
        raw = u32(data, off + 20)
        out.append((name, rva, raw, raw_size))
    return image_base, out


def va_to_off(image_base, secs, va):
    rva = va - image_base
    for _name, sec_rva, raw, raw_size in secs:
        if sec_rva <= rva < sec_rva + raw_size:
            return raw + (rva - sec_rva)
    raise SystemExit(f"VA 0x{va:x} is not in a raw section")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("va")
    ap.add_argument("-n", "--count", type=int, default=64)
    ap.add_argument("-w", "--width", type=int, choices=(1, 2, 4), default=1)
    args = ap.parse_args()

    data = Path(args.file).read_bytes()
    base, secs = sections(data)
    off = va_to_off(base, secs, int(args.va, 0))
    raw = data[off : off + args.count * args.width]
    print(f"va=0x{int(args.va, 0):08x} fileoff=0x{off:x}")
    for i in range(args.count):
        p = i * args.width
        if args.width == 1:
            val = raw[p]
        elif args.width == 2:
            val = u16(raw, p)
        else:
            val = u32(raw, p)
        print(f"{i:03d} 0x{val:0{args.width * 2}x}")


if __name__ == "__main__":
    main()
