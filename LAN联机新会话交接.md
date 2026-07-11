# LAN 联机新会话交接

更新时间：2026-07-11 16:10 左右

## 一句话目标

继续实现 `E:\Desktop\Game\原创单机v1.1\原创v1.1` 的真实局域网联机。当前游戏能通过 `launcher.py` GUI 开房进入、能操作、脚本/计时器在跑、点击角色不闪退，但仍没有脚本层真实玩家身份：进游戏界面不显示 `玩家1/玩家2`，物资/选择角色逻辑仍不像真实玩家槽位。

## 当前用户最新反馈

- 最新代码下：不闪退。
- 仍然没有出现 `玩家1` 身份。
- 用户要开新会话窗口，所以本文件是新的最小上下文。

## 工作目录和关键文件

- 工作目录：`E:\Documents\逆向`
- 游戏目录：`E:\Desktop\Game\原创单机v1.1\原创v1.1\gametest`
- GUI 启动器：`E:\Documents\逆向\tools\launcher.py`
- LAN 服务端/pipe 代理：`E:\Documents\逆向\tools\lan_moba.py`
- 详细流水记录：`E:\Documents\逆向\LAN联机改动记录.md`
- 参考官方单机启动器：`E:\Desktop\Game\原创单机v1.1\原创v1.1\启动器.exe`
- 最新运行日志：
  - `E:\Documents\逆向\launcher_lan_moba.log`
  - `E:\Documents\逆向\launcher_lan_moba.err`
  - 游戏日志目录通常是 `E:\Desktop\Game\原创单机v1.1\原创v1.1\gametest\log*-YYYY.MM.DD-*`
- 反汇编/静态资料：
  - `E:\Documents\逆向\game_disasm.txt`
  - `E:\Documents\逆向\game_imports.txt`
  - `E:\Documents\逆向\gpigame_disasm.txt`
  - `E:\Documents\逆向\gpigame_imports.txt`
  - `E:\Documents\逆向\official_launcher_disasm.txt`

## 当前代码状态

### `launcher.py`

- GUI 大厅可开房/加入/准备/开始。
- 开房启动游戏时调用：
  - `lan_moba.py --pipe <动态pipe> --server-ip <房主IP> --port 7000 --map 7F_1000026 --name <昵称> --pos <slot> --user-id <slot>`
  - 房主还传：`--players`、`--slots`、`--ip-slots`、`--slot-sides`
- 启动 game.exe 参数：
  - `game.exe 7F_1000026 /testgamebyeditor= /pipe=<pipe> /mapfile=7F_1000026 mapname=7F_1000026`
- 启动前写 `gametest\config.lua`：
  - `tempConfigLuaMapOptionInfo = { {0 , 0},{slot , 0},...}`
  - `SetCurrentControlID(pos)`
- 不要硬写 14 个地图栏位；当前从 `.map` 读取真实栏位。

### `lan_moba.py`

稳定但未解决身份的核心状态：

- Pipe `A002` 使用稳定 `0x386` 结构，长度 74 字节。不要再切回旧试验的 `0x387`。
- 登录阶段发送：
  - `0x012D` login
  - `0x013A` join success
  - `0x006B` 主玩家位置：payload `status:uint8 + pos:uint16`
  - `0x006C` 主玩家 user id：payload `user_id:uint32`
  - `0x0133` control info：`<IBBIH>`，总长 12 字节
  - `0x0130` player table
  - `0x0150` add player
  - `0x0141` session info
  - `0x0142` options
- `0x0141` 当前结构：
  - 60 字节
  - `+0x00`: `session_id`
  - `+0x04..+0x07`: `01 01 01 01`
  - `+0x2C`: `session_type=255`
  - `+0x2F..+0x37`: `1,1,1`
  - 仍打印 `session0141 ...` 诊断行
- `0x0138` 当前已经回滚为不闪退格式：
  - `turn:uint32`
  - `slot_count:uint8`
  - `reserved:uint32`
  - 每个 slot：`<IBI>`
  - 后接命令
- 客户端命令：
  - `0x025A` 会被收到，并把 `payload[4:4+n]` 回灌到 turn block。
  - 点击角色时能收到多条 `0x025A`，当前不闪退，但仍无玩家身份。

## 最新运行证据

最近一次 `launcher_lan_moba.log` 显示：

```text
pipe send A002 74 bytes
tcp recv 0x0259 len=196
login reply global_id=1 players=[(1, 'player1', 1)]
session0141 01 00 00 00 01 01 01 01 ... ff ... 01 00 00 00 ...
tcp recv 0x026f len=273
tcp unknown 0x026f payload=ac 12 00 01 00 ...
...
client loaded global_id=1
game start players=1
send turn ...
queue cmd25a ... bytes=16 head=01 00 04 03 01 ...
```

最新游戏 `cmd_1.log` 顶部仍曾出现类似：

```text
0, RefreshPlayerInfo
0, GetLiveType
0, session_id=1;player_num=2;map_name=;max_player=0;game_type=255;live_type=0;PlatGameType=0
```

这说明脚本/计时已启动，但脚本层会话/玩家身份仍不完整。

## 已失败或不要重复的尝试

- 不要切 `A002` 到 `0x387`：
  - 会导致启动字段串位：`HostSrvIP/Port/MapName/UserName/Pos` 全错。
- 不要直接把 turn 改成 `turn_packet(0,3)` / `turn_packet(turn,2,commands)`：
  - 曾导致点击角色闪退。
  - 已回滚。
- 不要用 UI 假显示 `玩家1`：
  - 用户明确拒绝伪联机，要求真实玩家身份自然触发脚本和物资。
- `0x0130/0x0150` 只会让 `net_state.log` 显示普通网络玩家表，不等于脚本层身份。
- 给 `0x0141 +8` 写玩家名没有解决，且疑似会话头字段读歪，已回滚。
- 单纯改 `SetCurrentControlID(pos)`/`config.lua` 仍不够；当前 launcher 已经写了。

## 关键反汇编结论

### `A002`

- 稳定结构是 `0x386`：
  - `map` 为 UTF-16LE，固定 32 字节
  - `ip + port + pos + 0 + session_id + user_id`
  - 后接 UTF-16LE 玩家名
- 当前 `net_state.log` 能正确显示：
  - `HostSrvIP`
  - `HostSrvPort`
  - `UserName`
  - `Pos`
  - `UserId`
  - `MapName`

### `0x0138`

- 反汇编显示 `payload +4` 会被当作 `kind`。
- `kind=1/3` 涉及 `AddSessionJoinInfo` 路径。
- `kind=2/3` 涉及命令执行路径。
- 但是直接改成干净 `turn_packet()` 会让点击角色闪退；说明当前游戏还依赖原来的 turn block 形状或后续命令封装，暂时不要再硬改。

### 玩家身份关键字段

重要链路：

- `AddSessionJoinInfo` 使用控制对象 `+0x42/+0x46/+0x4A` 生成 session join record。
- 这些字段来自 `B3D6/B3D8` 缓存，不是 `0x0130/0x0150` 普通玩家表。
- 客户端协议分支：
  - `0x006B` 设置 `B3D6`：payload 是 `status:uint8 + pos:uint16`
  - `0x006C` 设置 `B3D8`：payload 是 `user_id:uint32`
- 最新代码已经在登录包序列中补发 `0x006B/0x006C`，但用户反馈仍无 `玩家1`。
- 下一步不要假设它们生效，应该从游戏日志或更细日志确认客户端有没有实际进入这些分支，或是否发送时机不对。

### `0x026F`

- 客户端每次登录后都会发 `0x026F len=273`。
- 当前服务端只是打印 unknown。
- 旧 `tcp_probe.log` 中完整 `0x026F` payload 基本全 0，只有 IP 字段非零；最新 launcher 只打印前 32 字节。
- 它可能是客户端上传房间/平台资料，但目前没有证据证明回包能解决玩家身份。
- 若继续查，建议先把 `0x026F` 打印完整 payload，而不是只打印前 32 字节。

## 推荐下一步

最短路径：

1. 保持当前不闪退版本，不要再动 `0x0138`。
2. 扩大日志：
   - 完整打印 `0x026F` payload。
   - 在发送 `0x006B/0x006C` 时打印对应 bytes。
3. 重新跑一次 GUI 开房，检查：
   - `net_state.log` 是否仍正常。
   - `cmd_1.log` 顶部 session/player 信息是否有变化。
4. 如果 `0x006B/0x006C` 没效果，重点查发送时机：
   - 可能要在 `0x013A` 前发。
   - 或 `0x006B/0x006C` 不是 server-to-client，而是另一路状态更新。
5. 继续静态追踪 `00414310/00414320 -> B3D6/B3D8 -> 004156A0/004161B0 -> +42/+46/+4A -> AddSessionJoinInfo`，确认缺哪个字段。

## 常用验证命令

```powershell
E:\anaconda3\python.exe -m py_compile E:\Documents\逆向\tools\lan_moba.py E:\Documents\逆向\tools\launcher.py 2>&1 | Select-Object -First 120 | Out-String -Width 220
E:\anaconda3\python.exe E:\Documents\逆向\tools\launcher.py --self-test 2>&1 | Select-Object -First 120 | Out-String -Width 220
Get-Content -LiteralPath 'E:\Documents\逆向\launcher_lan_moba.log' -Encoding UTF8 -Tail 260 2>&1 | Out-String -Width 260
Get-ChildItem -LiteralPath 'E:\Desktop\Game\原创单机v1.1\原创v1.1\gametest' -Directory | Where-Object { $_.Name -like 'log*' } | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName,LastWriteTime | Out-String -Width 260
```

静态查询常用：

```powershell
rg -n "00414310|00414320|B3D6|B3D8|004156A0|004161B0|AddSessionJoinInfo|00434E1C" E:\Documents\逆向\game_disasm.txt E:\Documents\逆向\game_imports.txt
rg -n "1010F950|1000B8F0|1010F8A0|1010F8B0|SetSessionInfo|GetSessionInfo" E:\Documents\逆向\gpigame_disasm.txt
```

## 当前心理模型

游戏现在不是“没联网”，也不是“脚本没跑”。问题更窄：网络表存在，但脚本层 `CONTROL_PLAYER/CONTROL_PLAYER_temp` 没得到真实主玩家槽位。最可能缺的是平台/会话玩家身份链路中的某个小字段或发送时机，而不是需要重写整套联机协议。
