# LAN 计时器脚本修复记录

更新时间：2026-07-11

## 结论

当前通过 `tools\launcher.py` GUI 开房启动后，游戏可以进入，脚本和计时器已经能运行。这个文档只记录“让脚本/计时器跑起来”的有效操作；`玩家1/玩家2` 身份、选角、多机同步是后续独立问题。

## 有效操作

1. 启动参数保留编辑器单机入口，同时接入 pipe：

```text
game.exe 7F_1000026 /testgamebyeditor= /pipe=<动态pipe> /mapfile=7F_1000026 mapname=7F_1000026
```

2. 启动前写入 `gametest\config.lua`，格式对齐官方单机启动器：

```lua
tempConfigLuaMapOptionInfo = { {0 , 0},{slot , 0},...}
SetCurrentControlID(pos)
```

3. pipe 启动包 `A002` 使用稳定的 `0x386` 结构，长度约 74 字节：

```text
0x386 + UTF-16LE map(32 bytes) + server_ip + port + pos + 0 + session_id + user_id + UTF-16LE name
```

不要改回 `0x387`，那会导致 `HostSrvIP/Port/MapName/UserName/Pos` 字段串位，游戏无法稳定进入。

4. TCP 登录阶段必须发基础会话/控制包：

```text
0x012D login
0x013A join success
0x0133 control info
0x0150 add player
0x0130 player table
0x0141 session info
0x0142 map options
```

其中 `0x0133` 提供帧率和控制回合参数；`0x0141` 当前按 gpigame 绑定校正为：

```text
+0x00 session_id
+0x08 ANSI session/map name
+0x2C session_type/game_type
+0x2D max_player
```

5. 客户端资源加载完成后，收到 `0x025F` 时服务端发送：

```text
0x0146
```

然后标记客户端 loaded。服务端 tick 线程在所有预期玩家 loaded 后发送第一帧：

```text
0x0138 turn=0, join/start block
```

之后持续发送 `0x0138` turn 帧。这个持续 turn 流是计时器/脚本真正开始跑的关键。

## 成功日志特征

`E:\Documents\逆向\launcher_lan_moba.log` 应出现类似：

```text
pipe send A002 74 bytes
tcp recv 0x0259 len=196
login reply global_id=1 ...
tcp recv 0x025f len=...
client loaded global_id=1
game start players=1
send turn 1 ...
send turn 2 ...
```

游戏侧 `cmd_1.log` 应能看到脚本函数继续执行，例如 `RefreshPlayerInfo`、`GetLiveType`、会话信息打印等。若没有 `game start players=...` 或没有后续 `send turn ...`，计时器/脚本通常不会启动。

## 已确认的错路

- 不要把 `0x012F` 当作 SCRP/脚本字符串通道；它会走 `GameMsgDoCmd`，曾导致卡在“加载成功”界面。
- 不要在加载完成前强塞 SCRP 块；曾导致能收到 loaded 但进不去游戏。
- 不要随意改 `0x0138` 无命令帧结构；旧稳定 join/start block 能触发进入和计时。
- 不要把“玩家身份没出现”误判为“脚本没跑”。当前脚本/计时器已跑，剩下是脚本层玩家槽位身份问题。

## 复查命令

```powershell
E:\anaconda3\python.exe -m py_compile E:\Documents\逆向\tools\lan_moba.py E:\Documents\逆向\tools\launcher.py 2>&1 | Select-Object -First 120 | Out-String -Width 220
E:\anaconda3\python.exe E:\Documents\逆向\tools\launcher.py --self-test 2>&1 | Select-Object -First 120 | Out-String -Width 220
Get-Content -LiteralPath 'E:\Documents\逆向\launcher_lan_moba.log' -Encoding UTF8 -Tail 260 2>&1 | Out-String -Width 260
```
