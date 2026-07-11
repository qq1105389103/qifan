import argparse
import re
from pathlib import Path


def ascii_strings(data, min_len):
    for m in re.finditer(rb"[\x20-\x7e]{" + str(min_len).encode() + rb",}", data):
        yield m.start(), m.group().decode("ascii", "replace")


def utf16le_strings(data, min_len):
    pat = rb"(?:[\x20-\x7e]\x00){" + str(min_len).encode() + rb",}"
    for m in re.finditer(pat, data):
        yield m.start(), m.group().decode("utf-16le", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("-k", "--keyword", action="append", default=[])
    ap.add_argument("-n", "--min-len", type=int, default=4)
    args = ap.parse_args()

    data = Path(args.file).read_bytes()
    keywords = [k.lower() for k in args.keyword]
    rows = list(ascii_strings(data, args.min_len)) + list(utf16le_strings(data, args.min_len))
    rows.sort()
    for off, s in rows:
        if keywords and not any(k in s.lower() for k in keywords):
            continue
        print(f"{off:08x}  {s}")


if __name__ == "__main__":
    main()
