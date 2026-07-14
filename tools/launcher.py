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
from tkinter import filedialog, messagebox, ttk


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else ROOT
SETTINGS = APP_DIR / "lan_launcher.json"
MAP_CACHE = APP_DIR / "lan_map_cache.json"
GAME_DIR = r"E:\Desktop\Game\原创单机v1.1\原创v1.1\gametest"
DEFAULT_MAP = "7F_1000026"
PIPE = "lanprobe"
GAME_PORT = 7000
LOBBY_PORT = 7001
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
LAN_LOG = APP_DIR / "launcher_lan_moba.log"
LAN_ERR = APP_DIR / "launcher_lan_moba.err"


def read_map_text(map_name, game_dir=None):
    data = (Path(game_dir or GAME_DIR) / "map" / map_name / f"{map_name}.map").read_bytes()
    return data.decode("mbcs", "ignore")


def load_map_slot_sides(map_name, game_dir=None):
    text = read_map_text(map_name, game_dir)
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


def clean_text(text):
    keep = []
    for ch in text.replace("\0", " "):
        if "\u4e00" <= ch <= "\u9fff" or ch.isascii() and ch.isprintable() or ch in "·，。！？、：；（）《》【】":
            keep.append(ch)
        else:
            keep.append(" ")
    return re.sub(r"\s+", " ", "".join(keep)).strip()


def load_map_info(map_name, game_dir=None):
    text = read_map_text(map_name, game_dir)
    info = {"id": map_name, "title": map_name, "desc": "", "options": [], "slot_sides": load_map_slot_sides(map_name, game_dir)}
    start = text.find("PLAYER_MODE_NUM")
    tail = text[start:] if start >= 0 else text
    parts = tail.split("\x02")
    if parts:
        head = parts[0]
        if "\n" in head:
            info["desc"] = clean_text(head.split("\n", 1)[1])[:240]
    bm = tail.find("BM")
    if bm > 0:
        candidates = re.findall(r"[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9· _-]{1,30}", clean_text(tail[max(0, bm - 80) : bm]))
        if candidates:
            info["title"] = candidates[-1]
    defaults_part = next((p for p in parts if "#T#" in p), "")
    choices_part = next((p for p in parts if "@" in p and "#" in p), "")
    defaults = []
    for chunk in defaults_part.split("#T#")[1:]:
        cols = [x for x in chunk.split("#") if x]
        if len(cols) >= 2:
            defaults.append((clean_text(cols[0]), clean_text(cols[1])))
    choices = []
    for count, body in re.findall(r"@(\d+)#([^@\x02]+)", choices_part):
        rows = [clean_text(x) for x in body.split("#") if x]
        choices.append(rows[: int(count)])
    for idx, (name, default) in enumerate(defaults, 1):
        rows = choices[idx - 1] if idx - 1 < len(choices) else [default]
        try:
            default_index = rows.index(default)
        except ValueError:
            rows.insert(0, default)
            default_index = 0
        info["options"].append({"id": idx, "name": name, "choices": rows, "default": default_index})
    for choice in sorted({x for rows in choices for x in rows}, key=len, reverse=True):
        if info["title"].startswith(choice) and len(info["title"]) > len(choice) + 1:
            info["title"] = info["title"][len(choice) :]
            break
    return info


def _map_file(game_dir, map_name):
    return Path(game_dir or GAME_DIR) / "map" / map_name / f"{map_name}.map"


def map_stamp(game_dir, map_name):
    stat = _map_file(game_dir, map_name).stat()
    return {"size": stat.st_size, "mtime": int(stat.st_mtime)}


def cache_key(game_dir):
    try:
        return str(Path(game_dir).resolve())
    except OSError:
        return str(Path(game_dir))


def read_map_cache():
    try:
        return json.loads(MAP_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_map_cache(cache):
    try:
        MAP_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def normalize_map_info(info):
    info = dict(info)
    info["slot_sides"] = {int(k): int(v) for k, v in (info.get("slot_sides") or {1: 1}).items()}
    options = []
    for opt in info.get("options") or []:
        options.append(
            {
                "id": int(opt.get("id", 0)),
                "name": str(opt.get("name", "")),
                "choices": [str(x) for x in opt.get("choices", [])],
                "default": int(opt.get("default", 0)),
            }
        )
    info["options"] = options
    info["_loaded"] = True
    return info


def scan_maps(game_dir):
    root = Path(game_dir) / "map"
    maps = []
    for folder in sorted(root.glob("7F_*")):
        if (folder / f"{folder.name}.map").exists():
            maps.append({"id": folder.name, "title": folder.name, "desc": "", "options": [], "slot_sides": {1: 1}, "_loaded": False})
    return maps


def build_map_cache(game_dir=GAME_DIR):
    game_dir = Path(game_dir)
    key = cache_key(game_dir)
    cache = {k: v for k, v in read_map_cache().items() if v}
    maps = []
    for item in scan_maps(game_dir):
        try:
            info = load_map_info(item["id"], game_dir)
            info["stamp"] = map_stamp(game_dir, item["id"])
            maps.append(normalize_map_info(info))
        except OSError:
            pass
    cache[key] = maps
    write_map_cache(cache)
    return maps


def cached_maps(game_dir):
    game_dir = Path(game_dir)
    key = cache_key(game_dir)
    cached = read_map_cache().get(key)
    if cached:
        return [normalize_map_info(info) for info in cached]
    return build_map_cache(game_dir)


try:
    MAP_SLOT_SIDES = load_map_slot_sides(DEFAULT_MAP)
except OSError:
    MAP_SLOT_SIDES = {1: 1}
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


def _usable_lan_ip(ip):
    parts = [int(x) for x in ip.split(".")]
    return parts[0] not in (0, 127, 169) and ip != "172.18.0.1"


def _add_ip(ips, ip):
    if ip and _usable_lan_ip(ip) and ip not in ips:
        ips.append(ip)


def _gateway_ips(ipconfig_text):
    ips = []
    for block in re.split(r"\r?\n\r?\n", ipconfig_text):
        if not re.search(r"Default Gateway|默认网关", block):
            continue
        if not re.search(r"(Default Gateway|默认网关)[ .。]*:\s*[0-9]", block):
            continue
        ips.extend(re.findall(r"(?:IPv4 Address|IPv4 地址)[ .。]*:\s*([0-9.]+)", block))
    return ips


def local_ips():
    ips = []
    for target in ("1.1.1.1", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 1))
            _add_ip(ips, s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()
    if sys.platform == "win32":
        try:
            text = subprocess.check_output(["ipconfig"], encoding="mbcs", errors="ignore", creationflags=CREATE_NO_WINDOW)
            for ip in _gateway_ips(text):
                _add_ip(ips, ip)
            for ip in re.findall(r"(?:IPv4 Address|IPv4 地址)[ .。]*:\s*([0-9.]+)", text):
                _add_ip(ips, ip)
        except (OSError, subprocess.SubprocessError):
            pass
    for host in (socket.gethostname(), socket.getfqdn()):
        try:
            for ip in socket.gethostbyname_ex(host)[2]:
                _add_ip(ips, ip)
        except OSError:
            pass
    return ips or ["127.0.0.1"]


def lan_ip():
    return local_ips()[0]


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
            if proc.info["pid"] != me and (any(Path(arg).name == "lan_moba.py" for arg in cmdline) or "--lan-moba" in cmdline):
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

    def host_lobby(self, name, slot=1, display_ip=None):
        self.host = True
        slot = valid_slot(slot)
        self.app.player_id = slot
        self.players = [{"id": slot, "name": name, "ready": True, "host": True}]
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("0.0.0.0", LOBBY_PORT))
        self.server.listen()
        threading.Thread(target=self.accept_loop, daemon=True).start()
        self.app.post(("state", self.players, f"已开房：{display_ip or lan_ip()}:{LOBBY_PORT}"))

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
        msg = {"cmd": "start", "server_ip": server_ip, "players": len(start_players), "slots": slots, "map": self.app.map_id(), "map_options": self.app.selected_map_options()}
        for p in start_players:
            if p["id"] in self.clients:
                line(self.clients[p["id"]][0], msg)
        self.app.start_game(server_ip, len(start_players), self.app.player_id, slots, ip_slots, msg["map"], msg["map_options"])


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("LAN MOBA 启动器")
        self.events = queue.Queue()
        self.lobby = Lobby(self)
        self.players = []
        self.player_id = 1
        self.procs = []
        self.settings = self.load_settings()
        self.maps = []
        self.map_by_label = {}
        self.maps_game_dir = ""
        self.build()
        self.root.after(100, self.pump)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build(self):
        tk.Label(self.root, text="游戏目录").grid(row=0, column=0, sticky="w")
        self.game_dir = tk.Entry(self.root)
        self.game_dir.insert(0, self.settings.get("game_dir", GAME_DIR))
        self.game_dir.grid(row=0, column=1, sticky="ew")
        tk.Button(self.root, text="浏览", command=self.browse_game).grid(row=0, column=2, sticky="ew")
        tk.Label(self.root, text="地图").grid(row=1, column=0, sticky="w")
        self.map_var = tk.StringVar()
        self.map_combo = ttk.Combobox(self.root, textvariable=self.map_var, state="readonly")
        self.map_combo.grid(row=1, column=1, columnspan=2, sticky="ew")
        self.map_combo.bind("<<ComboboxSelected>>", lambda _e: self.select_map())
        self.map_desc = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self.map_desc, wraplength=420, justify="left").grid(row=2, column=0, columnspan=3, sticky="w")
        self.option_controls = []
        self.option_vars = {}
        for i in range(10):
            var = tk.StringVar()
            label = tk.Label(self.root, text="")
            combo = ttk.Combobox(self.root, textvariable=var, state="disabled")
            label.grid(row=3 + i, column=0, sticky="e")
            combo.grid(row=3 + i, column=1, columnspan=2, sticky="ew")
            label.grid_remove()
            combo.grid_remove()
            combo.bind("<<ComboboxSelected>>", lambda _e: self.save_settings())
            self.option_controls.append((label, combo, var))
        tk.Label(self.root, text="昵称").grid(row=13, column=0, sticky="w")
        self.name = tk.Entry(self.root)
        self.name.insert(0, "player1")
        self.name.grid(row=13, column=1, columnspan=2, sticky="ew")
        tk.Label(self.root, text="房主IP").grid(row=14, column=0, sticky="w")
        ips = local_ips()
        saved_host_ip = self.settings.get("host_ip", "")
        if saved_host_ip and saved_host_ip not in ips:
            ips.append(saved_host_ip)
        self.host_ip = ttk.Combobox(self.root, values=ips)
        self.host_ip.insert(0, saved_host_ip or lan_ip())
        self.host_ip.grid(row=14, column=1, columnspan=2, sticky="ew")
        tk.Label(self.root, text="Slot").grid(row=15, column=0, sticky="w")
        self.slot = tk.Spinbox(self.root, values=MAP_SLOTS, width=6)
        self.slot.delete(0, tk.END)
        self.slot.insert(0, "1")
        self.slot.grid(row=15, column=1, sticky="w")
        self.host_btn = tk.Button(self.root, text="开房", command=self.host)
        self.host_btn.grid(row=16, column=0, sticky="ew")
        self.join_btn = tk.Button(self.root, text="加入", command=self.join)
        self.join_btn.grid(row=16, column=1, columnspan=2, sticky="ew")
        self.ready_var = tk.BooleanVar()
        self.ready_btn = tk.Checkbutton(self.root, text="准备", variable=self.ready_var, command=self.ready)
        self.ready_btn.grid(row=17, column=0, sticky="ew")
        self.start_btn = tk.Button(self.root, text="开始", command=self.start, state="disabled")
        self.start_btn.grid(row=17, column=1, columnspan=2, sticky="ew")
        self.listbox = tk.Listbox(self.root, width=42, height=8)
        self.listbox.grid(row=18, column=0, columnspan=3, sticky="nsew")
        self.status = tk.StringVar(value="未连接")
        tk.Label(self.root, textvariable=self.status).grid(row=19, column=0, columnspan=3, sticky="w")
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(18, weight=1)
        self.refresh_maps(Path(self.game_path()), self.settings.get("map", DEFAULT_MAP))

    def load_settings(self):
        try:
            return json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save_settings(self):
        saved_options = dict(self.settings.get("map_options") or {})
        if hasattr(self, "option_vars"):
            saved_options[self.map_id()] = self.selected_map_option_values()
        try:
            SETTINGS.write_text(
                json.dumps(
                    {
                        "game_dir": self.game_path(),
                        "map": self.map_id(),
                        "map_options": saved_options,
                        "host_ip": self.host_address() if hasattr(self, "host_ip") else self.settings.get("host_ip", ""),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.settings["map_options"] = saved_options
        except OSError:
            pass

    def browse_game(self):
        path = filedialog.askdirectory(title="选择 gametest 游戏目录")
        if path:
            self.game_dir.delete(0, tk.END)
            self.game_dir.insert(0, path)
            self.refresh_maps(Path(path))
            self.save_settings()

    def game_path(self):
        return self.game_dir.get().strip() or GAME_DIR

    def check_game_path(self):
        game_dir = Path(self.game_path())
        if not (game_dir / "core" / "game.exe").exists():
            messagebox.showerror("游戏路径错误", "请选择包含 core\\game.exe 的 gametest 目录")
            return None
        self.refresh_maps(game_dir, self.map_id())
        self.save_settings()
        return game_dir

    def refresh_maps(self, game_dir, wanted=None):
        key = cache_key(game_dir)
        if key != self.maps_game_dir or not self.maps:
            try:
                self.maps = cached_maps(game_dir)
                if not self.maps:
                    self.maps = [normalize_map_info(load_map_info(DEFAULT_MAP, game_dir))]
            except OSError:
                self.maps = [{"id": DEFAULT_MAP, "title": DEFAULT_MAP, "desc": "", "options": [], "slot_sides": MAP_SLOT_SIDES}]
            self.maps_game_dir = key
        self.map_by_label = {}
        labels = []
        for info in self.maps:
            label = f"{info['id']}  {info['title']}" if info["title"] != info["id"] else info["id"]
            self.map_by_label[label] = info
            labels.append(label)
        self.map_combo.config(values=labels)
        wanted = wanted or self.map_id()
        label = next((x for x in labels if self.map_by_label[x]["id"] == wanted), labels[0])
        self.map_var.set(label)
        self.select_map()

    def select_map(self):
        info = self.current_map_info()
        self.refresh_map_info(info)
        self.option_vars = {}
        saved = (self.settings.get("map_options") or {}).get(info["id"], {})
        legacy_difficulty = self.settings.get("difficulty", "")
        for idx, (label, combo, var) in enumerate(self.option_controls):
            if idx >= len(info["options"]):
                label.grid_remove()
                combo.grid_remove()
                continue
            opt = info["options"][idx]
            choices = opt["choices"] or [""]
            try:
                value = int(saved.get(str(opt["id"]), opt["default"]))
            except (TypeError, ValueError):
                value = opt["default"]
            if opt["name"] == "难度" and legacy_difficulty in choices:
                value = choices.index(legacy_difficulty)
            if not 0 <= value < len(choices):
                value = opt["default"] if 0 <= opt["default"] < len(choices) else 0
            label.config(text=opt["name"] or "----")
            combo.config(state="readonly", values=choices)
            var.set(choices[value])
            self.option_vars[opt["id"]] = (opt, var)
            label.grid()
            combo.grid()
        self.map_desc.set(info.get("desc") or "")
        self.save_settings()

    def current_map_info(self):
        return self.map_by_label.get(self.map_var.get()) or (self.maps[0] if self.maps else load_map_info(DEFAULT_MAP, self.game_path()))

    def map_id(self):
        return self.current_map_info()["id"] if hasattr(self, "map_var") else self.settings.get("map", DEFAULT_MAP)

    def selected_map_options(self):
        pairs = []
        for opt in self.current_map_info()["options"]:
            value = opt["default"]
            item = self.option_vars.get(opt["id"]) if hasattr(self, "option_vars") else None
            if item:
                try:
                    value = opt["choices"].index(item[1].get())
                except ValueError:
                    value = opt["default"]
            pairs.append([opt["id"] - 1, value])
        return pairs

    def selected_map_option_values(self):
        values = {}
        for opt in self.current_map_info()["options"]:
            value = opt["default"]
            item = self.option_vars.get(opt["id"]) if hasattr(self, "option_vars") else None
            if item:
                try:
                    value = opt["choices"].index(item[1].get())
                except ValueError:
                    value = opt["default"]
            values[str(opt["id"])] = value
        return values

    def refresh_map_info(self, info):
        global MAP_SLOT_SIDES, MAP_SLOTS, MAP_SLOT_SET
        current = self.slot.get()
        MAP_SLOT_SIDES = info["slot_sides"]
        MAP_SLOTS = tuple(MAP_SLOT_SIDES)
        MAP_SLOT_SET = set(MAP_SLOTS)
        self.slot.config(values=MAP_SLOTS)
        self.slot.delete(0, tk.END)
        self.slot.insert(0, str(valid_slot(current)))

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
                self.start_game(msg["server_ip"], msg["players"], self.player_id, msg.get("slots"), None, msg.get("map"), msg.get("map_options"))
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

    def host_address(self):
        return self.host_ip.get().strip() or lan_ip()

    def host(self):
        try:
            if not self.check_game_path():
                return
            self.lobby.host_lobby(self.name.get().strip() or "player1", self.slot_value(), self.host_address())
        except OSError as e:
            messagebox.showerror("开房失败", str(e))

    def join(self):
        try:
            if not self.check_game_path():
                return
            self.lobby.join_lobby(self.host_ip.get().strip(), self.name.get().strip() or "player", self.slot_value())
        except OSError as e:
            messagebox.showerror("加入失败", str(e))

    def ready(self):
        self.lobby.ready(self.ready_var.get())

    def start(self):
        self.lobby.start(self.host_address())

    def start_game(self, server_ip, players, pos, slots=None, ip_slots=None, map_name=None, map_options=None):
        game_dir = self.check_game_path()
        if not game_dir:
            return
        self.stop_procs()
        map_name = map_name or self.map_id()
        self.refresh_maps(game_dir, map_name)
        map_options = map_options if map_options is not None else self.selected_map_options()
        pos = valid_slot(pos)
        name = self.name.get().strip() or f"player{pos}"
        kill_old_lan_moba()
        pipe = f"{PIPE}_{os.getpid()}_{int(time.time() * 1000)}"
        slots = valid_slots(slots or MAP_SLOTS[:players])
        if pos not in slots:
            slots.insert(0, pos)
        self.write_config(pos, [pos], map_options)
        if getattr(sys, "frozen", False):
            base = [sys.executable, "--lan-moba"]
        else:
            base = [sys.executable, str(ROOT / "tools" / "lan_moba.py")]
        base += ["--pipe", pipe, "--server-ip", server_ip, "--port", str(GAME_PORT), "--map", map_name, "--name", name, "--pos", str(pos), "--user-id", str(pos), "--map-options", json.dumps(map_options)]
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
        self.procs.append(subprocess.Popen(base, cwd=str(APP_DIR), creationflags=CREATE_NO_WINDOW, stdout=out, stderr=err))
        time.sleep(0.8)
        exe = game_dir / "core" / "game.exe"
        self.procs.append(subprocess.Popen([str(exe), map_name, "/testgamebyeditor=", f"/pipe={pipe}", f"/mapfile={map_name}", f"mapname={map_name}"], cwd=str(game_dir)))
        self.status.set("游戏已启动")

    def write_config(self, pos, slots=None, map_options=None):
        pos = valid_slot(pos)
        slots = valid_slots(slots or [pos])
        game_dir = Path(self.game_path())
        config = game_dir / "config.lua"
        pairs = list(map_options or [])
        if not pairs:
            pairs = [[0, 0]]
            seen = {0}
            pairs += [[slot, 0] for slot in slots if slot not in seen]
        text_pairs = "".join(f"{{{int(key)} , {int(val)}}}," for key, val in pairs)
        config.write_bytes(
            f"tempConfigLuaMapOptionInfo = {{ {text_pairs}}}\n"
            f"SetCurrentControlID({pos})".encode("mbcs"),
        )

    def start_single_game(self, pos):
        game_dir = self.check_game_path()
        if not game_dir:
            return
        self.write_config(pos, [pos], self.selected_map_options())
        exe = game_dir / "core" / "game.exe"
        map_name = self.map_id()
        self.procs.append(subprocess.Popen([str(exe), map_name, "/testgamebyeditor="], cwd=str(game_dir)))
        self.status.set("单机模式已启动")

    def close(self):
        self.stop_procs()
        self.root.destroy()

    def stop_procs(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
        self.procs.clear()


def self_test():
    payload = {"cmd": "state", "players": [{"id": 1, "name": "p", "ready": True}]}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert json.loads(data.decode("utf-8")) == payload
    assert ",".join(map(str, [1, 3])) == "1,3"
    assert valid_slot(9) == 1
    assert free_slot(1, {1, 2}) == 3
    assert valid_slots([1, 9, 20, 20]) == [1, 20]
    assert MAP_SLOT_SIDES[1] == 1
    try:
        from tools import lan_moba
    except ModuleNotFoundError:
        import lan_moba

    dummy = type("A", (), {"session_id": 1, "map": DEFAULT_MAP, "session_type": 0, "slots": "1,2", "map_options": ""})()
    assert lan_moba.session_info(dummy)[45] == 3
    dummy.map_options = "[[1,4],[2,0]]"
    assert lan_moba.option_info_pairs(dummy, 1) == [(1, 4), (2, 0)]
    dummy.map_options = ""
    assert lan_moba.option_info_pairs(dummy, 3) == [(0, 0), (3, 0)]
    table = lan_moba.player_table([(1, "p1", 1, 1), (2, "p2", 2, 1)], 2)
    assert table[:8] == b"\x02\x00\x00\x00\x02\x00\x00\x00"
    assert table[8 + 0x6F + 0x69] == 2
    assert lan_moba.turn_block_payload(0, [1, 2])[4] == 1
    assert len(lan_moba.turn_block_payload(0, [1, 2])) == 27
    assert lan_moba.turn_block_payload(1, [1, 2])[4] == 1
    assert lan_moba.turn_block_payload(1, [1, 2], commands=b"x")[4] == 2
    info = load_map_info(DEFAULT_MAP)
    assert info["id"] == DEFAULT_MAP
    assert any(o["name"] == "难度" for o in info["options"])
    first_two = info["options"][:2]
    assert [[o["id"] - 1, o["default"]] for o in first_two] == [[0, 0], [1, 0]]
    cached = normalize_map_info(info)
    assert 1 in cached["slot_sides"]
    assert _usable_lan_ip("172.16.2.95")
    assert not _usable_lan_ip("172.18.0.1")
    sample_ipconfig = "Ethernet adapter vEthernet:\n   IPv4 Address. . . . . . . . . . . : 172.18.0.1\n\nWireless LAN adapter WLAN:\n   IPv4 Address. . . . . . . . . . . : 192.168.3.95\n   Default Gateway . . . . . . . . . : 192.168.3.1\n"
    assert _gateway_ips(sample_ipconfig) == ["192.168.3.95"]
    ips = []
    _add_ip(ips, "172.18.0.1")
    _add_ip(ips, "172.16.2.95")
    _add_ip(ips, "172.16.2.95")
    assert ips == ["172.16.2.95"]
    assert Path(GAME_DIR).exists()
    assert (Path(GAME_DIR) / "core" / "game.exe").exists()


if __name__ == "__main__":
    if "--lan-moba" in sys.argv:
        sys.argv.remove("--lan-moba")
        from tools import lan_moba

        lan_moba.main()
    elif "--self-test" in sys.argv:
        self_test()
    elif "--build-map-cache" in sys.argv:
        idx = sys.argv.index("--build-map-cache")
        game_dir = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else GAME_DIR
        maps = build_map_cache(game_dir)
        print(f"cached {len(maps)} maps -> {MAP_CACHE}")
    else:
        App().root.mainloop()
