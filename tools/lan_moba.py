import argparse
import ctypes
import json
import os
import socket
import struct
import threading
import time
from ctypes import wintypes


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateNamedPipeW.restype = wintypes.HANDLE
k32.CreateNamedPipeW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
]
k32.ConnectNamedPipe.restype = wintypes.BOOL
k32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
k32.PeekNamedPipe.restype = wintypes.BOOL
k32.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
k32.ReadFile.restype = wintypes.BOOL
k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
k32.WriteFile.restype = wintypes.BOOL
k32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
ERROR_PIPE_CONNECTED = 535


def wstr(text):
    return text.encode("utf-16le") + b"\0\0"


def pipe_pkt(cmd, payload=b"", ver=0x0101):
    return struct.pack("<IHH", 8 + len(payload), cmd, ver) + payload


def tcp_pkt(ptl, payload=b""):
    return struct.pack("<HH", ptl, 4 + len(payload)) + payload


def ipv4_bytes(ip):
    return socket.inet_aton(ip)


def player_info(global_id, name, pos, side=0):
    info = bytearray(0x6F)
    info[0] = 1
    info[4] = 1
    struct.pack_into("<I", info, 5, global_id)
    info[9 : 9 + 0x60] = name.encode("utf-16le", "replace")[:0x5E].ljust(0x60, b"\0")
    info[0x69] = pos
    info[0x6A] = side
    return bytes(info)


def slot_sides(args):
    try:
        return {int(k): int(v) for k, v in json.loads(args.slot_sides or "{}").items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def player_table(players, local_id):
    infos = b"".join(player_info(pid, name, pos, side) for pid, name, pos, side in players)
    return struct.pack("<II", local_id, len(players)) + infos


def session_info(args, session_type=None):
    session = bytearray(range(60)) if os.environ.get("LAN_MOBA_SESSION_PATTERN") else bytearray(60)
    if not os.environ.get("LAN_MOBA_SESSION_PATTERN"):
        struct.pack_into("<I", session, 0, args.session_id)
        session[4:8] = b"\1\1\1\1"
        session[8:40] = args.map.encode("mbcs", "replace")[:31].ljust(32, b"\0")
        session[44] = args.session_type if session_type is None else session_type
        session[45] = min(255, len(room_slots(args)))
        struct.pack_into("<III", session, 47, 1, 1, 1)
    return bytes(session)


def a002(args):
    fixed = wstr(args.map).ljust(32, b"\0")
    host = ipv4_bytes(args.server_ip) + struct.pack("<H", args.port)
    host += struct.pack("<BBII", args.pos, 0, args.session_id, args.user_id)
    payload = struct.pack("<H", 0x386) + fixed + host + wstr(args.name)
    return pipe_pkt(0xA002, payload)


def check(ok, what):
    if not ok:
        raise OSError(ctypes.get_last_error(), what)


def pipe_server(args, stop):
    path = "\\\\.\\pipe\\" + args.pipe
    while not stop.is_set():
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
        print(f"pipe connected {path}", flush=True)
        buf = ctypes.create_string_buffer(4096)
        got = ctypes.c_ulong()
        try:
            while not stop.is_set():
                if k32.PeekNamedPipe(h, None, 0, None, ctypes.byref(got), None) and got.value:
                    n = ctypes.c_ulong()
                    ok = k32.ReadFile(h, buf, min(got.value, 4096), ctypes.byref(n), None)
                    if ok and n.value:
                        data = bytes(buf.raw[: n.value])
                        print(f"pipe recv {data.hex(' ')}", flush=True)
                        if len(data) >= 8 and data[4:6] == b"\x01\xa0":
                            out = a002(args)
                            n2 = ctypes.c_ulong()
                            k32.WriteFile(h, out, len(out), ctypes.byref(n2), None)
                            print(f"pipe send A002 {n2.value} bytes", flush=True)
                time.sleep(0.05)
        finally:
            k32.CloseHandle(h)


def room_slots(args):
    slots = [int(x) for x in args.slots.split(",") if x.strip()]
    return slots or [1]


def login_reply(args, client_ip, global_id):
    now = int(time.time())
    login = struct.pack("<III", now, 1, struct.unpack("<I", socket.inet_aton(client_ip))[0])
    join = struct.pack("<13I", global_id, 0, global_id, now, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    control = struct.pack("<IBBIH", args.control_start, args.fps, args.control_turn, args.keep_alive, 0)
    sides = slot_sides(args)
    players = [(pos, f"player{pos}", pos, sides.get(pos, 0)) for pos in room_slots(args)]
    print(f"login reply global_id={global_id} players={players} sides={sides}", flush=True)
    option_pairs = [(0, 0)] + [(pid, 0) for pid, _, _, _ in players]
    options = struct.pack("<B", len(option_pairs)) + b"".join(struct.pack("<BB", key, val) for key, val in option_pairs)
    session = session_info(args)
    print(f"session0141 {session.hex(' ')}", flush=True)
    packets = [
        tcp_pkt(0x012D, login),
        tcp_pkt(0x013A, join),
        tcp_pkt(0x006B, struct.pack("<BH", 0, global_id)),
        tcp_pkt(0x006C, struct.pack("<I", global_id)),
        tcp_pkt(0x0133, control),
        *[tcp_pkt(0x0150, player_info(pid, name, pos, side)) for pid, name, pos, side in players],
        tcp_pkt(0x0130, player_table(players, global_id)),
        tcp_pkt(0x0141, session),
        tcp_pkt(0x0142, options),
    ]
    return packets


def turn_packet(turn, kind=2, commands=b""):
    return tcp_pkt(0x0138, struct.pack("<IB", turn, kind) + commands)


def turn_block_payload(turn, slots, tick_ms=0, commands=b""):
    if commands:
        return struct.pack("<IB", int(turn), 2) + commands
    entries = b"".join(struct.pack("<IBI", int(slot), 100, int(tick_ms)) for slot in slots)
    return struct.pack("<IBI", int(turn), len(slots), 0) + entries + commands


def h2c_cmd(cmd, payload=b""):
    return struct.pack("<H", 2 + len(payload)) + struct.pack("<H", cmd) + payload


def buy_item_cmd(payload, global_id):
    if len(payload) < 20:
        return b""
    count = min(struct.unpack_from("<I", payload, 12)[0], (len(payload) - 20) // 8)
    record = bytearray(0x3D)
    struct.pack_into("<I", record, 0, global_id)
    record[4:12] = payload[0:8]
    record[12:16] = payload[8:12]
    struct.pack_into("<I", record, 0x35, count)
    return h2c_cmd(0x013C, bytes(record) + payload[20 : 20 + count * 8])


class Client:
    def __init__(self, conn, addr, global_id):
        self.conn = conn
        self.addr = addr
        self.global_id = global_id
        self.loaded = False
        self.alive = True
        self.send_lock = threading.Lock()
        self.client_data = bytearray()

    def send(self, data):
        with self.send_lock:
            self.conn.sendall(data)


class GameRoom:
    def __init__(self, args):
        self.args = args
        self.expected_players = max(1, args.players)
        self.fps = args.fps
        self.clients = []
        self.pending = bytearray()
        self.turn = 1
        self.started = False
        self.lock = threading.Lock()
        self.used_slots = set()

    def slot_for_addr(self, addr):
        raw = getattr(self.args, "ip_slots", "")
        try:
            ip_slots = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            ip_slots = dict(part.split("=", 1) for part in raw.split(",") if "=" in part)
        slot = int(ip_slots.get(addr[0], 0) or 0)
        if not slot:
            for candidate in room_slots(self.args):
                if candidate not in self.used_slots:
                    slot = candidate
                    break
        self.used_slots.add(slot)
        return slot or 1

    def add(self, client):
        with self.lock:
            self.clients.append(client)

    def remove(self, client):
        with self.lock:
            client.alive = False
            self.used_slots.discard(client.global_id)
            self.clients = [c for c in self.clients if c is not client]

    def mark_loaded(self, client):
        with self.lock:
            client.loaded = True
            already_started = self.started
        if already_started:
            client.send(tcp_pkt(0x0138, turn_block_payload(0, room_slots(self.args), 0)))

    def queue_commands(self, payload):
        if len(payload) <= 5:
            return
        with self.lock:
            self.pending.extend(payload[5:])

    def queue_raw_commands(self, payload):
        if not payload:
            return
        with self.lock:
            self.pending.extend(payload)

    def broadcast(self, data):
        with self.lock:
            clients = [c for c in self.clients if c.alive and c.loaded]
        for client in clients:
            try:
                client.send(data)
            except OSError:
                client.alive = False

    def tick(self, stop):
        delay = max(1, self.args.control_turn) / max(1, self.fps)
        next_tick = time.time() + delay
        while not stop.is_set():
            time.sleep(max(0, next_tick - time.time()))
            next_tick += delay
            with self.lock:
                clients = [c for c in self.clients if c.alive and c.loaded]
                if not clients:
                    continue
                if not self.started:
                    if len(clients) < self.expected_players:
                        continue
                    packet = tcp_pkt(0x0138, turn_block_payload(0, room_slots(self.args), 0))
                    self.started = True
                    print(f"game start players={len(clients)}", flush=True)
                else:
                    commands = bytes(self.pending)
                    tick_ms = int(self.turn * max(1, self.args.control_turn) * 1000 / max(1, self.fps))
                    packet_turn = self.turn
                    packet = tcp_pkt(0x0138, turn_block_payload(packet_turn, room_slots(self.args), tick_ms, commands))
                    if commands or self.turn <= 20 or self.turn % self.fps == 0:
                        print(f"send turn {self.turn} target={packet_turn} ms={tick_ms} cmds={len(commands)}", flush=True)
                    self.pending.clear()
                    self.turn += 1
            for client in clients:
                try:
                    client.send(packet)
                except OSError:
                    client.alive = False


def handle_client(args, conn, addr, client, room, stop):
    print(f"tcp connected {addr} global_id={client.global_id}", flush=True)
    conn.settimeout(0.5)
    buf = b""
    try:
        while not stop.is_set():
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except ConnectionResetError:
                return
            if not chunk:
                return
            buf += chunk
            while len(buf) >= 4:
                ptl, size = struct.unpack_from("<HH", buf)
                if size < 4 or len(buf) < size:
                    break
                packet, buf = buf[:size], buf[size:]
                print(f"tcp recv 0x{ptl:04x} len={size}", flush=True)
                if ptl == 0x0259:
                    for out in login_reply(args, addr[0], client.global_id):
                        client.send(out)
                elif ptl == 0x025D:
                    client.send(tcp_pkt(0x006B, struct.pack("<BH", 0, client.global_id)))
                elif ptl == 0x025F:
                    client.send(tcp_pkt(0x0146))
                    if args.state_wait:
                        payload = struct.pack("<BI", args.state_wait, 0)
                        print(f"send GameEventStateWait state={args.state_wait}", flush=True)
                        client.send(tcp_pkt(0x0160, payload))
                    room.mark_loaded(client)
                    print(f"client loaded global_id={client.global_id}", flush=True)
                elif ptl == 0x026A:
                    payload = packet[4:]
                    print(f"start ack global_id={client.global_id} {payload.hex(' ')}", flush=True)
                elif ptl == 0x025A:
                    payload = packet[4:]
                    if len(payload) >= 4:
                        n = struct.unpack_from("<H", payload, 2)[0]
                        data = payload[4 : 4 + n]
                        commands = struct.pack("<HHBBH", n + 6, 0x012E, payload[0], payload[1], n) + data
                        print(f"queue cmd25a global_id={client.global_id} flag={payload[0]} seq={payload[1]} raw={n} bytes={len(commands)} head={commands[:18].hex(' ')}", flush=True)
                        room.queue_raw_commands(commands)
                elif ptl == 0x0269:
                    payload = packet[4:]
                    if len(payload) >= 3:
                        n = struct.unpack_from("<H", payload, 1)[0]
                        data = payload[3 : 3 + n]
                        if payload[0] == 1:
                            client.client_data.clear()
                        client.client_data.extend(data)
                        print(f"client data global_id={client.global_id} flag={payload[0]} bytes={len(data)} head={data[:16].hex(' ')}", flush=True)
                elif ptl == 0x0265:
                    data = bytes(client.client_data)
                    out = tcp_pkt(0x026B, struct.pack("<HI", 1, client.global_id) + data)
                    print(f"send client data global_id={client.global_id} bytes={len(data)}", flush=True)
                    room.broadcast(out)
                elif ptl == 0x0263:
                    payload = packet[4:]
                    commands = buy_item_cmd(payload, client.global_id)
                    if commands:
                        fields = struct.unpack_from("<5I", payload, 0)
                        print(f"queue cmd263 global_id={client.global_id} fields={fields} raw={len(payload)} bytes={len(commands)} head={commands[:22].hex(' ')}", flush=True)
                        room.queue_raw_commands(commands)
                elif ptl in (0x0008, 0x0267):
                    pass
                else:
                    payload = packet[4:]
                    print(f"tcp unknown 0x{ptl:04x} payload={payload[:32].hex(' ')}", flush=True)
    finally:
        room.remove(client)
        print(f"tcp disconnected {addr}", flush=True)


def tcp_server(args, stop):
    room = GameRoom(args)
    threading.Thread(target=room.tick, args=(stop,), daemon=True).start()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((args.listen, args.port))
        s.listen()
        s.settimeout(0.5)
        print(f"tcp listening {args.listen}:{args.port}", flush=True)
        while not stop.is_set():
            try:
                conn, addr = s.accept()
            except socket.timeout:
                continue
            client = Client(conn, addr, room.slot_for_addr(addr))
            room.add(client)
            threading.Thread(target=handle_client, args=(args, conn, addr, client, room, stop), daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipe", default="lanprobe")
    ap.add_argument("--map", default="7F_1000026")
    ap.add_argument("--server-ip", default="127.0.0.1", help="IP written into A002 for clients to connect to")
    ap.add_argument("--listen", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=7000)
    ap.add_argument("--name", default="player1")
    ap.add_argument("--pos", type=int, default=1)
    ap.add_argument("--user-id", type=int, default=1)
    ap.add_argument("--session-id", type=int, default=1)
    ap.add_argument("--session-type", type=int, default=0)
    ap.add_argument("--players", type=int, default=1, help="loaded clients required before the room starts")
    ap.add_argument("--slots", default="1", help="comma-separated player positions in this room")
    ap.add_argument("--ip-slots", default="", help="JSON or ip=slot CSV mapping client IPs to player positions")
    ap.add_argument("--slot-sides", default="", help="JSON mapping player position to side")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--control-start", type=int, default=0)
    ap.add_argument("--control-turn", type=int, default=1)
    ap.add_argument("--keep-alive", type=int, default=0)
    ap.add_argument("--state-wait", type=int, default=0)
    ap.add_argument("--no-pipe", action="store_true")
    ap.add_argument("--no-tcp", action="store_true")
    args = ap.parse_args()

    stop = threading.Event()
    threads = []
    if not args.no_tcp:
        threads.append(threading.Thread(target=tcp_server, args=(args, stop), daemon=True))
    if not args.no_pipe:
        threads.append(threading.Thread(target=pipe_server, args=(args, stop), daemon=True))
    for t in threads:
        t.start()
    print("press Ctrl+C to stop", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
