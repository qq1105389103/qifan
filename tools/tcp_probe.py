import argparse
import socket
import struct
import time
from pathlib import Path


def pkt(ptl, payload=b""):
    return struct.pack("<HH", ptl, 4 + len(payload)) + payload


def auto_login_reply():
    # Minimal server-to-client bootstrap packets recovered from game.exe.
    now = int(time.time())
    login = struct.pack("<III", now, 1, 0x0100007F)
    join = struct.pack("<13I", 1, 0, 1, now, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    control = struct.pack("<IBBIH", 1, 20, 1, 15, 0)
    session = struct.pack("<I B 3B 13I", 1, 1, 1, 1, 1, *([0] * 13))
    return [
        pkt(0x012D, login),
        pkt(0x013A, join),
        pkt(0x0133, control),
        pkt(0x0141, session),
    ]


def turn_packet(turn, kind=2, commands=b""):
    return pkt(0x0138, struct.pack("<IB", turn, kind) + commands)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7000)
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--log", default="tcp_probe.log")
    ap.add_argument("--auto-reply", action="store_true")
    args = ap.parse_args()

    log = Path(args.log)
    end = time.time() + args.seconds
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((args.host, args.port))
        s.listen()
        s.settimeout(0.5)
        log.write_text(f"listening {args.host}:{args.port}\n", encoding="utf-8")
        while time.time() < end:
            try:
                c, addr = s.accept()
            except socket.timeout:
                continue
            log.write_text(log.read_text(encoding="utf-8") + f"connect {addr}\n", encoding="utf-8")
            c.settimeout(0.5)
            with c:
                loaded = False
                frame = 1
                while time.time() < end:
                    try:
                        data = c.recv(4096)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    log.write_text(log.read_text(encoding="utf-8") + f"recv {len(data)} {data.hex(' ')}\n", encoding="utf-8")
                    if args.auto_reply and len(data) >= 4:
                        ptl, size = struct.unpack_from("<HH", data)
                        if ptl == 0x0259:
                            for out in auto_login_reply():
                                c.sendall(out)
                                log.write_text(log.read_text(encoding="utf-8") + f"send {len(out)} {out.hex(' ')}\n", encoding="utf-8")
                        elif ptl == 0x025D:
                            out = pkt(0x006B, b"\0\1\0")
                            c.sendall(out)
                            log.write_text(log.read_text(encoding="utf-8") + f"send {len(out)} {out.hex(' ')}\n", encoding="utf-8")
                            if loaded:
                                out = turn_packet(frame)
                                c.sendall(out)
                                log.write_text(log.read_text(encoding="utf-8") + f"send {len(out)} {out.hex(' ')}\n", encoding="utf-8")
                                frame += 1
                        elif ptl == 0x025F:
                            loaded = True
                            out = pkt(0x0146)
                            c.sendall(out)
                            log.write_text(log.read_text(encoding="utf-8") + f"send {len(out)} {out.hex(' ')}\n", encoding="utf-8")
                            out = turn_packet(0, 3)
                            c.sendall(out)
                            log.write_text(log.read_text(encoding="utf-8") + f"send {len(out)} {out.hex(' ')}\n", encoding="utf-8")
                            out = turn_packet(frame)
                            c.sendall(out)
                            log.write_text(log.read_text(encoding="utf-8") + f"send {len(out)} {out.hex(' ')}\n", encoding="utf-8")
                            frame += 1


if __name__ == "__main__":
    main()
