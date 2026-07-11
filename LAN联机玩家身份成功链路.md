# LAN 联机玩家身份成功链路

更新时间：2026-07-11

## 当前已成功现象

- 游戏能进入逻辑循环，脚本和计时器执行。
- `RefreshPlayerInfo` 能读取真实玩家身份。
- `net_state.log` 已确认玩家表正确：
  - `recv add player info(1): pos 1, name player1, side 1`
  - `recv player info(1): id 1, pos 1, name player1, side 1`
- 用户确认：已经能读取到玩家身份，并且能分配资源。

## 不要再改坏的稳定点

- 不要恢复 SCRP / `0x012F` 注入。`0x012F` 是 `GameMsgDoCmd`，不是 `DoString`。
- 不要把 pipe `A002` 从 `0x386` 改成 `0x387`。
- 不要把 `0x006B` 改成纯 WORD 或 status=1。正确格式是 `<BH status=0, pos>`。
- 不要把 `0x0141 +8` 改回 UTF-16；脚本绑定按 ANSI/C 字符串读。
- 不要把 `0x0130` 改成 12 字节头或三 DWORD 头；玩家 record 必须从 payload+8 开始。

## 成功字段

### A002 pipe

- 版本/结构：`0x386`
- 固定地图名：UTF-16LE，32 字节。
- 后接：`server_ip + port + pos + 0 + session_id + user_id + UTF-16LE name`

### 0x006B / 0x006C

- `0x006B`: `struct.pack("<BH", 0, global_id)`
- `0x006C`: `struct.pack("<I", global_id)`
- 必须使用当前连接的 `global_id`，不能固定用房主 `args.pos`。

### 0x0141 session info

- 长度：60 字节。
- `+0x00`: `session_id`
- `+0x04..+0x07`: `01 01 01 01`
- `+0x08`: ANSI/mbcs session/map name，32 字节。
- `+0x2C`: `session_type=0`
- `+0x2D`: `max_player=len(room_slots(args))`
- `+0x2F`: 三个 DWORD 标志，当前为 `1,1,1`。

### 0x0150 AddPlayer

每条玩家记录长度 `0x6F`：

- `+0x00`: `1`
- `+0x04`: `player_type=1`
- `+0x05`: `global_id:uint32`
- `+0x09`: UTF-16LE 玩家名，`0x60` 字节。
- `+0x69`: `pos`
- `+0x6A`: `side`

### 0x0130 SetPlayerInfo

正确 payload：

```text
0x00 uint32 local_id
+0x04 uint32 player_count
+0x08 player_info[0]
```

即 Python：

```python
struct.pack("<II", local_id, len(players)) + b"".join(player_info(...))
```

关键原因：

- `SetPlayerInfo` 读取前两个 DWORD。
- `recv player info` 后续按 `payload+8` 读取 `0x6F` 玩家记录。
- 如果使用三 DWORD 头，日志会变成 `id 16777216, pos 0, name , side 0`，并触发 `RefreshPlayerInfo pos=0` Lua 报错。

## 登录包顺序

当前成功顺序：

```text
0x012D login
0x013A join success
0x006B local pos
0x006C local user id
0x0133 control info
0x0150 add player(s)
0x0130 set player info
0x0141 session info
0x0142 options
```

`0x0150` 必须早于 `0x0130`，否则 `SetPlayerInfo` 查询本机玩家时表还是空。

## 当前未解决问题

- 玩家身份和资源已成功。
- 仍不能选取角色。
- 下一步只应查 `0x025A` / `0x0138` / `GameMsgDoCmd` 命令执行链路。
