import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox


ROOT = Path(__file__).resolve().parents[1]
GAME_DIR = r"E:\Desktop\Game\原创单机v1.1\原创v1.1\gametest"
MAP = "7F_1000026"
PIPE = "lanprobe"
GAME_PORT = 7000
LOBBY_PORT = 7001
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
LAN_LOG = ROOT / "launcher_lan_moba.log"
LAN_ERR = ROOT / "launcher_lan_moba.err"


def read_map_text(map_name):
    data = (Path(GAME_DIR) / "map" / map_name / f"{map_name}.map").read_bytes()
    for encoding in ("utf-8", "mbcs"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", "ignore")


def load_map_slot_sides(map_name):
    text = read_map_text(map_name)
    bars = {int(i): int(pid) for i, pid in re.findall(r"bar(\d+)_player_id=(\d+)", text)}
    side_counts = {int(i): int(n) for i, n in re.findall(r"side(\d+)_num=(\d+)", text)}
    if not bars:
        return {1: 1}
    slot_sides = {}
    side = 1
    left = side_counts.get(side, len(bars))
    for _bar, player_id in sorted(bars.items()):
        while left <= 0 and side < 8:
            side += 1
            left = side_counts.get(side, 0)
        slot_sides[player_id] = side
        left -= 1
    return slot_sides


MAP_SLOT_SIDES = load_map_slot_sides(MAP)
MAP_SLOTS = tuple(MAP_SLOT_SIDES)
MAP_SLOT_SET = set(MAP_SLOTS)


def valid_slot(value):
    try:
        slot = int(value)
    except (TypeError, ValueError):
        return MAP_SLOTS[0]
    return slot if slot in MAP_SLOT_SET else MAP_SLOTS[0]


def free_slot(wanted, used):
    wanted = valid_slot(wanted)
    if wanted not in used:
        return wanted
    return next((slot for slot in MAP_SLOTS if slot not in used), 0)


def valid_slots(values):
    slots = []
    for value in values:
        slot = valid_slot(value)
        if slot not in slots:
            slots.append(slot)
    return slots or [MAP_SLOTS[0]]


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        s.close()


def line(sock, obj):
    sock.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))


def kill_old_lan_moba():
    try:
        import psutil
    except ImportError:
        return
    me = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            if proc.info["pid"] != me and any(Path(arg).name == "lan_moba.py" for arg in cmdline):
                proc.kill()
        except (psutil.Error, OSError):
            pass


class Lobby:
    def __init__(self, app):
        self.app = app
        self.host = False
        self.sock = None
        self.server = None
        self.clients = {}
        self.players = []
        self.lock = threading.Lock()

    def host_lobby(self, name, slot=1):
        self.host = True
        slot = valid_slot(slot)
        self.app.player_id = slot
        self.players = [{"id": slot, "name": name, "ready": True, "host": True}]
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("0.0.0.0", LOBBY_PORT))
        self.server.listen()
        threading.Thread(target=self.accept_loop, daemon=True).start()
        self.app.post(("state", self.players, f"已开房：{lan_ip()}:{LOBBY_PORT}"))

    def join_lobby(self, host, name, slot=0):
        self.host = False
        self.sock = socket.create_connection((host, LOBBY_PORT), timeout=5)
        line(self.sock, {"cmd": "join", "name": name, "slot": slot})
        threading.Thread(target=self.read_loop, args=(self.sock, None), daemon=True).start()

    def accept_loop(self):
        while True:
            try:
                sock, addr = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self.read_loop, args=(sock, None, addr[0]), daemon=True).start()

    def read_loop(self, sock, player_id, peer_ip=None):
        buf = b""
        while True:
            try:
                data = sock.recv(4096)
            except OSError:
                data = b""
            if not data:
                if self.host and player_id:
                    self.drop(player_id)
                return
            buf += data
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                msg = json.loads(raw.decode("utf-8"))
                if self.host:
                    player_id = self.host_msg(sock, player_id, msg, peer_ip)
                else:
                    self.client_msg(msg)

    def host_msg(self, sock, player_id, msg, peer_ip=None):
        if msg.get("cmd") == "join" and not player_id:
            with self.lock:
                used = {p["id"] for p in self.players}
                player_id = free_slot(msg.get("slot"), used)
                if not player_id:
                    line(sock, {"cmd": "error", "message": "room full"})
                    sock.close()
                    return None
                self.clients[player_id] = (sock, peer_ip or "")
                self.players.append({"id": player_id, "name": msg.get("name", f"player{player_id}"), "ready": False})
            line(sock, {"cmd": "you", "id": player_id})
            self.broadcast()
        elif msg.get("cmd") == "ready" and player_id:
            with self.lock:
                for p in self.players:
                    if p["id"] == player_id:
                        p["ready"] = bool(msg.get("ready"))
            self.broadcast()
        return player_id

    def client_msg(self, msg):
        if msg.get("cmd") == "state":
            self.app.post(("state", msg["players"], "已连接大厅"))
        elif msg.get("cmd") == "you":
            self.app.player_id = msg["id"]
        elif msg.get("cmd") == "error":
            self.app.post(("status", msg.get("message", "lobby error")))
        elif msg.get("cmd") == "start":
            self.app.post(("start", msg))

    def drop(self, player_id):
        with self.lock:
            self.clients.pop(player_id, None)
            self.players = [p for p in self.players if p["id"] != player_id]
        self.broadcast()

    def broadcast(self):
        msg = {"cmd": "state", "players": self.players}
        self.app.post(("state", self.players, "大厅已更新"))
        for sock, _ in list(self.clients.values()):
            try:
                line(sock, msg)
            except OSError:
                pass

    def ready(self, ready):
        if self.host:
            return
        line(self.sock, {"cmd": "ready", "ready": ready})

    def start(self, server_ip):
        players = list(self.players)
        start_players = [p for p in players if p.get("host") or p["ready"]]
        slots = [p["id"] for p in start_players]
        ip_slots = {"127.0.0.1": self.app.player_id, lan_ip(): self.app.player_id, server_ip: self.app.player_id}
        ip_slots.update({ip: pid for pid, (_, ip) in self.clients.items() if ip})
        msg = {"cmd": "start", "server_ip": server_ip, "players": len(start_players), "slots": slots}
        for p in start_players:
            if p["id"] in self.clients:
                line(self.clients[p["id"]][0], msg)
        self.app.start_game(server_ip, len(start_players), self.app.player_id, slots, ip_slots)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("LAN MOBA 启动器")
        self.events = queue.Queue()
        self.lobby = Lobby(self)
        self.players = []
        self.player_id = 1
        self.procs = []
        self.build()
        self.root.after(100, self.pump)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build(self):
        tk.Label(self.root, text="昵称").grid(row=0, column=0, sticky="w")
        self.name = tk.Entry(self.root)
        self.name.insert(0, "player1")
        self.name.grid(row=0, column=1, sticky="ew")
        tk.Label(self.root, text="房主IP").grid(row=1, column=0, sticky="w")
        self.host_ip = tk.Entry(self.root)
        self.host_ip.insert(0, lan_ip())
        self.host_ip.grid(row=1, column=1, sticky="ew")
        tk.Label(self.root, text="Slot").grid(row=2, column=0, sticky="w")
        self.slot = tk.Spinbox(self.root, values=MAP_SLOTS, width=6)
        self.slot.delete(0, tk.END)
        self.slot.insert(0, "1")
        self.slot.grid(row=2, column=1, sticky="w")
        self.host_btn = tk.Button(self.root, text="开房", command=self.host)
        self.host_btn.grid(row=3, column=0, sticky="ew")
        self.join_btn = tk.Button(self.root, text="加入", command=self.join)
        self.join_btn.grid(row=3, column=1, sticky="ew")
        self.ready_var = tk.BooleanVar()
        self.ready_btn = tk.Checkbutton(self.root, text="准备", variable=self.ready_var, command=self.ready)
        self.ready_btn.grid(row=4, column=0, sticky="ew")
        self.start_btn = tk.Button(self.root, text="开始", command=self.start, state="disabled")
        self.start_btn.grid(row=4, column=1, sticky="ew")
        self.listbox = tk.Listbox(self.root, width=42, height=8)
        self.listbox.grid(row=5, column=0, columnspan=2, sticky="nsew")
        self.status = tk.StringVar(value="未连接")
        tk.Label(self.root, textvariable=self.status).grid(row=6, column=0, columnspan=2, sticky="w")
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(5, weight=1)

    def post(self, item):
        self.events.put(item)

    def pump(self):
        while not self.events.empty():
            kind, *data = self.events.get()
            if kind == "state":
                self.players, text = data
                self.draw_players()
                self.status.set(text)
            elif kind == "start":
                msg = data[0]
                self.start_game(msg["server_ip"], msg["players"], self.player_id, msg.get("slots"))
            elif kind == "status":
                self.status.set(data[0])
        self.root.after(100, self.pump)

    def draw_players(self):
        self.listbox.delete(0, tk.END)
        for p in self.players:
            mark = "房主" if p["id"] == 1 else ("准备" if p["ready"] else "未准备")
            self.listbox.insert(tk.END, f"{p['id']}. {p['name']}  {mark}")
        self.start_btn.config(state="normal" if self.lobby.host else "disabled")

    def slot_value(self):
        return valid_slot(self.slot.get())

    def host(self):
        try:
            self.lobby.host_lobby(self.name.get().strip() or "player1", self.slot_value())
        except OSError as e:
            messagebox.showerror("开房失败", str(e))

    def join(self):
        try:
            self.lobby.join_lobby(self.host_ip.get().strip(), self.name.get().strip() or "player", self.slot_value())
        except OSError as e:
            messagebox.showerror("加入失败", str(e))

    def ready(self):
        self.lobby.ready(self.ready_var.get())

    def start(self):
        self.lobby.start(self.host_ip.get().strip() or lan_ip())

    def start_game(self, server_ip, players, pos, slots=None, ip_slots=None):
        pos = valid_slot(pos)
        name = self.name.get().strip() or f"player{pos}"
        kill_old_lan_moba()
        pipe = f"{PIPE}_{os.getpid()}_{int(time.time() * 1000)}"
        slots = valid_slots(slots or MAP_SLOTS[:players])
        if pos not in slots:
            slots.insert(0, pos)
        self.write_config(pos, slots)
        py = sys.executable
        base = [py, str(ROOT / "tools" / "lan_moba.py"), "--pipe", pipe, "--server-ip", server_ip, "--port", str(GAME_PORT), "--map", MAP, "--name", name, "--pos", str(pos), "--user-id", str(pos)]
        if self.lobby.host:
            base += ["--players", str(players), "--slots", ",".join(map(str, slots))]
            base += ["--ip-slots", json.dumps(ip_slots or {"127.0.0.1": 1})]
            base += ["--slot-sides", json.dumps(MAP_SLOT_SIDES)]
        else:
            base += ["--no-tcp"]
        LAN_LOG.write_text("", encoding="utf-8")
        LAN_ERR.write_text("", encoding="utf-8")
        out = LAN_LOG.open("a", encoding="utf-8")
        err = LAN_ERR.open("a", encoding="utf-8")
        self.procs.append(subprocess.Popen(base, cwd=str(ROOT), creationflags=CREATE_NO_WINDOW, stdout=out, stderr=err))
        time.sleep(0.8)
        exe = Path(GAME_DIR) / "core" / "game.exe"
        self.procs.append(subprocess.Popen([str(exe), MAP, "/testgamebyeditor=", f"/pipe={pipe}", f"/mapfile={MAP}", f"mapname={MAP}"], cwd=GAME_DIR))
        self.status.set("游戏已启动")

    def write_config(self, pos, slots=None):
        pos = valid_slot(pos)
        slots = valid_slots(slots or [pos])
        game_dir = Path(GAME_DIR)
        config = game_dir / "config.lua"
        pairs = "".join(f"{{{slot} , 0}}," for slot in slots)
        config.write_bytes(
            f"tempConfigLuaMapOptionInfo = {{ {{0 , 0}},{pairs}}}\n"
            f"SetCurrentControlID({pos})".encode("mbcs"),
        )

    def start_single_game(self, pos):
        game_dir = Path(GAME_DIR)
        self.write_config(pos, [pos])
        exe = game_dir / "core" / "game.exe"
        self.procs.append(subprocess.Popen([str(exe), MAP, "/testgamebyeditor="], cwd=GAME_DIR))
        self.status.set("单机模式已启动")

    def close(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
        self.root.destroy()


def self_test():
    payload = {"cmd": "state", "players": [{"id": 1, "name": "p", "ready": True}]}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert json.loads(data.decode("utf-8")) == payload
    assert ",".join(map(str, [1, 3])) == "1,3"
    assert valid_slot(9) == 1
    assert free_slot(1, {1, 2}) == 3
    assert valid_slots([1, 9, 20, 20]) == [1, 20]
    assert MAP_SLOT_SIDES[1] == 1
    assert Path(GAME_DIR).exists()
    assert (Path(GAME_DIR) / "core" / "game.exe").exists()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        App().root.mainloop()
