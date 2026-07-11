import argparse
import socket
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7000)
    ap.add_argument("--seconds", type=int, default=25)
    ap.add_argument("--log", default="probe_server.log")
    args = ap.parse_args()

    end = time.time() + args.seconds
    log = Path(args.log)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((args.host, args.port))
        s.settimeout(0.5)
        log.write_text(f"listening {args.host}:{args.port}\n", encoding="utf-8")
        while time.time() < end:
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                continue
            line = f"recv {addr} {len(data)} {data.hex(' ')}\n"
            log.write_text(log.read_text(encoding="utf-8") + line, encoding="utf-8")


if __name__ == "__main__":
    main()
