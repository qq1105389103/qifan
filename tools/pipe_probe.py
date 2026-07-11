import argparse
import ctypes
import struct
import time
from pathlib import Path


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
ERROR_PIPE_CONNECTED = 535


def check(ok, what):
    if not ok:
        raise OSError(ctypes.get_last_error(), what)


def wstr(text):
    return text.encode("utf-16le") + b"\0\0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="lanprobe")
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--log", default="pipe_probe.log")
    ap.add_argument("--send-a002", action="store_true")
    ap.add_argument("--a002-new", action="store_true")
    args = ap.parse_args()

    log = Path(args.log)
    path = "\\\\.\\pipe\\" + args.name
    log.write_text(f"listening {path}\n", encoding="utf-8")
    h = k32.CreateNamedPipeW(
        path,
        PIPE_ACCESS_DUPLEX,
        PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
        1,
        4096,
        4096,
        0,
        None,
    )
    if h == INVALID_HANDLE_VALUE:
        check(False, "CreateNamedPipeW")

    ok = k32.ConnectNamedPipe(h, None)
    err = ctypes.get_last_error()
    if not ok and err != ERROR_PIPE_CONNECTED:
        check(False, "ConnectNamedPipe")
    log.write_text(log.read_text(encoding="utf-8") + "connected\n", encoding="utf-8")

    buf = ctypes.create_string_buffer(4096)
    got = ctypes.c_ulong()
    end = time.time() + args.seconds
    while time.time() < end:
        ok = k32.PeekNamedPipe(h, None, 0, None, ctypes.byref(got), None)
        if ok and got.value:
            n = ctypes.c_ulong()
            ok = k32.ReadFile(h, buf, min(got.value, 4096), ctypes.byref(n), None)
            if ok and n.value:
                data = bytes(buf.raw[: n.value])
                line = f"recv {n.value} {data.hex(' ')}\n"
                log.write_text(log.read_text(encoding="utf-8") + line, encoding="utf-8")
                if args.send_a002 and len(data) >= 8 and data[4:6] == b"\x01\xa0":
                    if args.a002_new:
                        fixed = b"7F_1000026\0".ljust(64, b"\0")
                        fixed = fixed[:0x3C] + bytes([127, 0, 0, 1])
                        tail = struct.pack("<HBBII", 7000, 1, 0, 1, 1) + b"player1\0"
                        payload = struct.pack("<H", 0x387) + fixed + tail
                    else:
                        fixed = wstr("7F_1000026").ljust(32, b"\0")
                        host = bytes([127, 0, 0, 1]) + struct.pack("<H", 7000) + b"\x01\x00" + struct.pack("<II", 1, 1)
                        payload = struct.pack("<H", 0x386) + fixed + host + wstr("player1")
                    pkt = struct.pack("<IHH", 8 + len(payload), 0xA002, 0x0101) + payload
                    n2 = ctypes.c_ulong()
                    k32.WriteFile(h, pkt, len(pkt), ctypes.byref(n2), None)
                    log.write_text(log.read_text(encoding="utf-8") + f"send {n2.value} {pkt.hex(' ')}\n", encoding="utf-8")
        time.sleep(0.05)

    k32.CloseHandle(h)


if __name__ == "__main__":
    main()
