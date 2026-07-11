# LAN联机改动记录

## 当前目标

- 做真实局域网联机，不做 UI 伪显示。
- 进入游戏后必须有真实玩家身份，例如玩家1/玩家2；身份应自然触发脚本侧逻辑和物资。

## 当前已知稳定状态

- `tools/launcher.py` 通过 GUI 开房/加入。
- 游戏启动参数保留真实 pipe/TCP：
  - `7F_1000026`
  - `/testgamebyeditor=`
  - `/pipe=<动态pipe>`
  - `/mapfile=7F_1000026`
  - `mapname=7F_1000026`
- `tools/lan_moba.py` 的 pipe 启动包 `A002` 使用稳定的 `0x386` 结构，长度 74 字节。
- `0x0138` turn block 已恢复到之前不闪退的稳定结构：
  - `turn:uint32`
  - `slot_count:uint8`
  - `reserved:uint32`
  - 每个 slot: `<IBI>`
  - 后接客户端命令。

## 已验证能收到的网络信息

- `0x012D` login reply
- `0x013A` join game success
- `0x0133` control info
- `0x0130` player table
- `0x0150` add player
- `0x0141` session info
- `0x0142` option info
- 客户端命令 `0x025A` 能收到并可回灌进 turn block。

## 失败尝试

- 把 `0x0138` 开局包改成 `turn=0, kind=1`：
  - 结果：没有玩家身份。
  - 副作用：点击选择角色后闪退。
  - 已回滚。
- 把 pipe `A002` 改成 `0x387` 新结构：
  - 结果：启动信息串位，`HostSrvIP/Port/MapName/UserName` 都被读错。
  - 副作用：游戏启动后地图名变成乱码并退出。
  - 已回滚。
- 给 `0x0141` session info 的 `+8` 写入玩家名：
  - 结果：没有解决玩家身份。
  - 已回滚；疑似会让脚本侧 `GetSessionInfo` 的会话头字段读歪。

## 2026-07-11 本次改动

- 将 `tools/lan_moba.py` 的 `0x0141` session info 调整为“早期标志位 + 触发位”：
  - `+0x00`: `session_id`
  - `+0x04..+0x07`: `01 01 01 01`
  - `+0x2C`: `session_type=255`
  - `+0x2F..+0x37`: `1,1,1`
- 目的：
  - 修正日志里 `session_id=1;player_num=2;map_name=;max_player=0;game_type=255` 这种会话头异常。
  - 先恢复早期曾更接近可用状态的会话结构，再验证是否能让脚本层生成真实玩家身份。
- 待验证：
  - `cmd_1.log` 顶部的 `GetSessionInfo` 输出是否正常。
  - 进入游戏后是否自然显示/拥有 `玩家1` 身份。
  - 物资初始化是否恢复。

## 2026-07-11 继续排查：0x0138 turn 包

- 新发现：
  - 客户端 `0x0138` 处理逻辑把 payload `+4` 当作 `kind`。
  - `kind=1/3` 走会话加入/`AddSessionJoinInfo` 路径。
  - `kind=2/3` 走命令执行路径。
  - 之前 `turn_block_payload()` 把 `+4` 当作 `slot_count`，单人时一直等于 `1`，等于每帧都发 `kind=1`。
- 本次修改：
  - 开局/补发：`turn_packet(0, 3)`
  - 后续帧：`turn_packet(turn, 2, commands)`
- 目的：
  - 开局只触发一次会话玩家加入。
  - 后续帧正常执行客户端命令。
  - 避免把玩家槽位数量误塞进 `kind` 字段。
- 结果：
  - 没有出现玩家身份。
  - 点击选择角色后闪退。
  - 已回滚到原稳定 `turn_block_payload()` 格式。
  - 结论：不能直接改成 `turn_packet(0,3)` / `turn_packet(turn,2)`；该路径会让角色选择命令触发崩溃。

## 当前关键判断

- `0x0130/0x0150` 只能让 net_state 显示普通玩家网络表，不等于脚本层玩家身份。
- 用户观察到：没有玩家身份时物资不触发，所以问题不是显示刷新，而是进入游戏时没有携带脚本层主玩家身份。
- 早期曾出现玩家1身份，说明解法可能在启动配置/启动参数/简单玩家位置传入，而不是复杂新协议。

## 2026-07-11 继续排查：主玩家身份字段

- 新发现：
  - `AddSessionJoinInfo` 使用控制对象 `+0x42/+0x46/+0x4A` 生成 session join record。
  - 这些字段来自 `B3D6/B3D8` 缓存，而不是 `0x0130/0x0150` 普通玩家表。
  - 客户端协议分支：
    - `0x006B`: 设置 `B3D6`，payload 为 `status:uint8 + pos:uint16`
    - `0x006C`: 设置 `B3D8`，payload 为 `user_id:uint32`
- 本次修改：
  - 登录成功包序列中补发 `0x006B(pos)` 和 `0x006C(user_id)`。
  - 心跳 `0x025D` 的 `0x006B` 回包改成当前连接对应的 `client.global_id`，避免多人都被回成 1。
- 目的：
  - 在开局 `0x0138 kind=1` 触发 `AddSessionJoinInfo` 前，先让客户端缓存真实主玩家位置/用户信息。

## 2026-07-11 试错回滚：0x006B 玩家位置包体

- 曾误判 `0x006B` 只读一个 `WORD`，把 `<BH>` 改成 `<H>`。
- 用户反馈仍无身份，且一直弹登录失败窗口。
- 已回滚：`0x006B` 保持 `status:uint8 + pos:uint16`，也就是 `<BH>`。

## 2026-07-11 修正：启动器自动发送 SCRP 会话脚本块

- 新判断：
  - `SetSessionInfo(0x0141)` 只存平台会话指针。
  - 脚本层 `玩家1/PlayerType1/UserName1` 这类身份变量来自录像里的 `SCRP` 块。
  - `replay\AutoSave\7frtest.7fr` 的 SCRP 已包含 `UserName1="玩家1"`、`PlayerType1=1`。
- 本次修改：
  - `launcher.py` 启动 `lan_moba.py` 时，如果 `replay\AutoSave\7frtest.7fr` 存在，自动加：
    - `--script-replay <7frtest.7fr>`
    - `--script-mode loaded`
- 目的：
  - 在客户端资源加载完成、开局前发送官方格式的会话脚本块，补上脚本层真实玩家身份变量。
- 后续结论：
  - 错路，已移除启动器自动 SCRP。
  - 反查协议跳表后确认 `0x012F` 调的是 `GameMsgDoCmd`，不是 `DoString`；把 SCRP 当命令流发送会卡在加载成功。

## 2026-07-11 调整：SCRP 延后到第一帧开局包后

- 用户反馈：
  - 不再弹登录失败。
  - 但卡在加载成功，进不去游戏。
- 日志现象：
  - 代理已收到 `0x025f`，发了 SCRP，也持续发送 turn。
  - 游戏日志不再出现 `GameEventCloseWindow/appExit`。
- 本次修改：
  - `script-mode loaded` 不再在 `0x025f` 处理中立刻发 `0x012F/SCRP`。
  - 改为第一帧 `0x0138` 开局包发给客户端后，再补发一次 `0x012F/SCRP`。
- 目的：
  - 先让客户端原本的加载完成/关加载窗口流程跑完，再补脚本层身份块。
- 后续结论：
  - 仍卡在加载成功，已删除自动 SCRP 发送逻辑。
  - `0x012F` 确认不是 SCRP 通道。

## 2026-07-11 修正：session_type 默认改为 0

- 根因线索：
  - 当前 `0x0138` 稳定 turn block 的 payload `+4` 是 slot_count=1，客户端会按 `kind=1` 进入会话加入路径。
  - 该路径调用 `004156A0`。
  - `004156A0` 读取 `GetSessionInfo()+0x2C`，当值为 `0xFF` 或 `0xFE` 时返回 false。
  - 旧默认 `session_type=255` 正好会短路 `AddSessionJoinInfo`，导致脚本层没有真实玩家身份。
- 本次修改：
  - `lan_moba.py --session-type` 默认值从 `255` 改为 `0`。
- 目的：
  - 让 `0x0138 kind=1` 的真实 `AddSessionJoinInfo` 路径能执行。

## 2026-07-11 修正：双阶段 session_type

- 新静态结论：
  - `0x006B` 第一字节不能改成 `1`；反汇编分支显示非 0 会走登录失败弹窗，当前 `status=0 + pos:uint16` 是正确格式。
  - `00434E1C` 对应导入 `AddSessionJoinInfo`。
  - `0x0138 kind=1` 前的 `004156A0` 要求 `session_type` 不是 `0xFF/0xFE`，但 `00415E50` 内部真正调用 `AddSessionJoinInfo` 的分支又只在 `0xFF/0xFE` 下执行。
  - 客户端发送加载完成 `0x025F` 的路径 `00421C20` 在 `session_type=0xFF/0xFE` 时会调用 `00415E50(1)`。
- 本次修改：
  - 登录阶段首个 `0x0141` 仍发 `session_type=0xFF`，让客户端在加载完成时能走真实 `AddSessionJoinInfo`。
  - 服务端收到客户端 `0x025F` 后，先补发一次 `0x0141 session_type=0`，再发 `0x0146` 并开局，保留当前不卡加载/能进游戏的状态。
  - `0x0138` 稳定 turn block 不动，SCRP 不恢复。
- 待验证：
  - `launcher_lan_moba.log` 应出现 `session0141 initial ... ff ...` 和 `session0141 ready ... 00 ...`。
  - `net_state.log` 应先加载成功并进入游戏，不弹登录失败。
  - 进入游戏后观察是否出现真实 `玩家1/玩家2` 身份和物资逻辑。
- 后续结论：
  - 失败，用户反馈仍无身份。
  - 日志显示脚本首次 `GetSessionInfo` 仍读到 `game_type=255`，说明 ready 阶段补发太晚，不能作为身份初始化依据。

## 2026-07-11 修正：补全 0x0141 会话字段

- 新证据：
  - `gpi.o` 中 `RefreshPlayerInfo` 读取 `SESSIONINFO.map_name/max_player/game_type` 后初始化 `CONTROL_PLAYER`。
  - 最新 `cmd_1.log` 一直是 `map_name=;max_player=0`，说明 `0x0141` 的 session 结构仍缺字段。
  - `gpigame.dll` 的 `GetSessionInfo` 全局结构基址为 `1036E374`，`+8` 是宽字符字符串，`+0x28` 被作为数值字段读出，`+0x2C` 是当前已确认的 `game_type/session_type`。
- 本次修改：
  - 撤掉双阶段 `0xFF -> 0`。
  - 登录阶段 `0x0141` 直接发 `session_type=0`。
  - `0x0141 +8` 写入 UTF-16LE 地图名 `7F_1000026`。
  - `0x0141 +0x28` 写入当前房间 slot 数作为 `max_player`。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地结构检查输出：`7F_1000026 1 0`。
- 待验证：
  - 重新开房后 `cmd_1.log` 顶部应不再是 `map_name=;max_player=0`。
  - 若 `map_name/max_player` 正常但仍无身份，再查 `GetSessionPlayerInfo` 返回的玩家表字段。
- 后续结论：
  - 失败，用户反馈仍无身份。
  - 最新日志确认 `0x0141 +8` 写 UTF-16 地图名、`+0x28` 写 dword 后，脚本仍显示 `map_name=;max_player=0`。
  - 说明该 offset/编码判断错误。

## 2026-07-11 按官方启动器和 gpigame 绑定校正 0x0141

- 官方启动器静态结论：
  - 官方启动器只写 `config.lua` 并启动 `.\core\game.exe <map> /testgamebyeditor=`。
  - 官方 `config.lua` 拼接顺序是 `tempConfigLuaMapOptionInfo = { ... }`，再 `SetCurrentControlID(n)`；当前 launcher 与它基本一致。
  - 官方启动器没有 `/pipe` 联机路径，不能提供 `0x0141/0x0130` 网络包体参考。
- `gpigame.dll` 实锤布局：
  - `GetSessionInfo` 返回全局结构基址 `1036E374`。
  - Lua 绑定里：
    - `session_id` 读 `+0x00`。
    - `session_name` 读 `+0x08` 的 ANSI/C 字符串。
    - `game_type` 读 `+0x2C` 的 byte。
    - `max_player` 读 `+0x2D` 的 byte。
  - 因此之前把 `+8` 当 UTF-16、把 `+0x28` 当 `max_player` 是错的。
- 本次修改：
  - `0x0141 +8` 改为 ANSI 地图/session 名字符串。
  - `0x0141 +0x2D` 写入当前 slot 数。
  - 保持 `0x0141 +0x2C = session_type=0`。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 结构检查确认 `+0x2C=0`、`+0x2D=1`。
- 待验证：
  - 重新开房后 `cmd_1.log` 至少应从 `max_player=0` 变为 `max_player=1`。
  - 如果仍无身份，再按 `GetSessionPlayerInfo/GetSessionPlayerInfoEx` 的玩家表布局查 `0x0130/0x0150`。

## 2026-07-11 修正：0x0130 玩家表头和发送顺序

- 新证据：
  - `0x0130` 处理器先读固定 12 字节并调用 `SetPlayerInfo`。
  - `SetPlayerInfo` 读取前两个 DWORD：第一个作为本机玩家 id 查询已存在的 `AddPlayer` 表，第二个用于玩家数量/日志。
  - 旧实现发的是 `<IHH> + player_info`，导致第二个 DWORD 变成 `0x006f0000`，且 `0x0130` 早于 `0x0150`，查询本机玩家时表还是空。
- 本次修改：
  - `player_table()` 改为只发 12 字节：`<III local_id, player_count, 0>`。
  - 登录包顺序改为先发所有 `0x0150 AddPlayer`，再发 `0x0130 SetPlayerInfo`。
  - `0x006B/0x006C/0x0130` 使用当前连接的 `global_id`，避免多人客户端都收到房主 slot。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地包体检查确认 `0x0130` payload 长度为 12 字节，例：`02 00 00 00 02 00 00 00 00 00 00 00`。
- 待验证：
  - 重新开房后 `net_state.log` 应出现合理的 `recv player info(1/2...)`，不能再被长度字段污染。
  - 进入游戏后观察真实玩家身份是否出现。
- 后续结论：
  - 有收获但不完整：用户反馈仍无玩家身份，且其他电脑阵营身份也没了。
  - 新日志显示 `0x0150` 仍正常：`recv add player info(1) pos 1, name player1, side 1`。
  - 但 `0x0130` 变成空刷新：`recv player info(1) id 0, pos 0, name , side 0`。
  - 说明纯 12 字节表头太短，会让游戏后续玩家刷新读到空记录。

## 2026-07-11 修正：0x0130 保留 12 字节头并补回玩家记录

- 本次修改：
  - `0x0130` payload 改为：`<III local_id, player_count, player_bytes> + player_info[]`。
  - 保留上一轮正确的 12 字节 DWORD 头，补回被误删的 `0x6F` 玩家记录列表。
  - `0x0150 AddPlayer` 仍先于 `0x0130 SetPlayerInfo` 发送。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地包体检查：两人时 `0x0130` 长度 `234 = 12 + 2*111`，头为 `local_id=2, player_count=2, player_bytes=222`，record 的 `type/id/pos/side` 均非零。
- 待验证：
  - 重新开房后 `net_state.log` 的 `recv player info(...)` 不应再出现 `id 0, pos 0, name , side 0`。
  - 若阵营恢复但仍无主玩家身份，继续查 `SetPlayerInfo` 如何把本机 id 写到脚本层控制玩家。
- 后续结论：
  - 仍失败，并且加载时报 Lua 错：`function.lua:3106 attempt to index field '?' (a nil value)`。
  - 弹窗堆栈显示 `RefreshPlayerInfo: index=1 limit=2 i=1 pos=0 playertype=1`，说明玩家类型已读到，但位置仍被读成 0。
  - 新 `net_state.log` 显示 `recv player info(1): id 16777216, pos 0, name , side 0`。
  - 这正好说明 player record 被从 `payload+12` 读偏了，实际 parser 仍按 `payload+8` 作为 record 起点。

## 2026-07-11 修正：0x0130 表头应为两个 DWORD

- 本次修改：
  - `0x0130` payload 改为：`<II local_id, player_count> + player_info[]`。
  - 保留 `SetPlayerInfo` 需要的两个 DWORD，同时让第一个 `0x6F` 玩家记录从 `payload+8` 开始。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地包体检查：两人时 `0x0130` 长度 `230 = 8 + 2*111`，从 `payload+8` 读取第一条 record 得到 `type=1, player_type=1, id=1, pos=1, side=1`。
- 待验证：
  - 重新开房后 `net_state.log` 的 `recv player info(1)` 应恢复为 `id 1, pos 1, name player1, side 1`。
  - 若 Lua `pos=0` 报错消失但玩家身份仍未出现，再继续查脚本层本机控制玩家赋值。
- 后续结论：
  - 成功：用户反馈已经能读取玩家身份并分配资源。
  - 新问题：不能选取角色。
  - 最新日志确认 `0x025A` 点击命令持续收到，但当前 `0x0138` 稳定包 `payload+4=1` 只走 join 路径，不会执行命令。

## 2026-07-11 修正：0x025A 命令长度前缀和 0x0138 命令帧

- 新证据：
  - `0x0138` handler 里 `kind=1/3` 走 join，`kind=2/3` 才会调用命令执行路径。
  - 命令执行路径把 `payload+5` 后的数据交给 `GameMsgDoCmd`。
  - `GameMsgDoCmd` 逐条读取 `uint16 length + command_body`。
  - 旧代码从 `0x025A payload[4:4+n]` 入队，剥掉了前面的 `uint16 length`；并且旧稳定 turn block 把命令放在 slot entry 后，kind 仍为 1。
- 本次修改：
  - `0x025A` 入队改为保留长度前缀：`payload[2:4+n]`。
  - `0x0269` 同理保留长度前缀：`payload[1:3+n]`。
  - `turn_block_payload()` 无命令时保持旧稳定 join block；有命令时发送 `turn:uint32 + kind=3:uint8 + commands`，让命令紧跟 `payload+5`。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地包体检查：命令帧开头为 `turn, kind=3, len=16, command...`。
- 待验证：
  - 重新进游戏点击角色，观察是否能选取角色。
  - 若仍不能选，优先看 `launcher_lan_moba.log` 是否出现 `send turn ... cmds=18`，以及游戏日志是否出现对应选择命令效果。
- 后续结论：
  - 用户反馈仍不能选取角色。
  - 新日志显示 `0x025A` 已收到并发出 `send turn ... cmds=18`。
  - 同时发现 `0x0269` 是大段脚本自定义数据上传，例如 `Type1 = 1 Player...`，不应进入命令回灌。

## 2026-07-11 修正：选角命令帧继续收窄

- 本次修改：
  - `0x0269` 不再 `queue_raw_commands`，只记录为 `client data`。
  - 有命令的 `0x0138` 帧从 `kind=3` 改成 `kind=2`，避免再次进入 join 分支；无命令帧仍保持旧稳定 join block。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地包体检查：命令帧开头为 `turn=166, kind=2, len=16, command...`。
- 待验证：
  - 重新进游戏点击角色，观察是否能选取。
  - 若仍失败，下一步只比较 `0x025A` 命令 body 是否还需要用 `GameMsgDoCmd` 直接通道处理，而不是 turn 队列。
- 后续结论：
  - 用户反馈仍不能选取。
  - 现象判断：点击角色等客户端事件不生效，但刷兵、计时器等时间驱动逻辑生效。
  - 静态确认：`0x012F` handler 会把剩余 payload 直接传给 `GameMsgDoCmd(ptr,len,2)`；而当前 `0x0138 kind=2` 路径只处理少数同步类命令，不适合普通点击命令。

## 2026-07-11 修正：0x025A 点击命令改走 0x012F 直接通道

- 本次修改：
  - `0x025A` 不再进入 `0x0138` pending 队列。
  - 从 `0x025A` 中取 raw command body：`payload[4:4+n]`。
  - 服务端广播 `tcp_pkt(0x012F, command_body)` 给已加载客户端。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地包体检查：示例点击命令生成 `0x012F len=20`，payload 为 `01 00 04 07 00 7a 08 01 ...`，不带 `uint16 length` 前缀。
- 待验证：
  - 重新进游戏点击角色，观察是否能选取。
  - 日志应出现 `send cmd25a direct ... bytes=16`。
- 后续结论：
  - 用户反馈点击触发事件会卡死。
  - 最新日志显示第一次 `0x012F` 直发后客户端不再正常回包，说明普通点击命令不能直接回给客户端走 `0x012F`。
  - 已撤销 `0x012F` 直发，恢复 `0x025A` 进入 `0x0138 kind=2` 队列。

## 2026-07-11 修正：命令 turn 往后一拍

- 新证据：
  - 本地点击入队代码调用 `00425B30` 时使用 `当前游戏帧 / control_turn + 1`。
  - 命令队列处理 `00425770` 只在精确控制帧执行命令；如果命令目标帧已经过去，会丢弃该命令。
- 本次修改：
  - `0x025A` 不再直发 `0x012F`。
  - `0x025A` 继续保留长度前缀进入 pending：`payload[2:4+n]`。
  - 有 pending 命令时，`0x0138 kind=2` 的 turn 从 `self.turn` 改为 `self.turn + 1`。
  - 日志改为打印 `send turn <server_turn> target=<packet_turn> ...`，便于确认命令目标帧。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地包体检查：命令帧 `turn=91, kind=2, len=16, command...`。
- 待验证：
  - 重新进游戏点击角色，观察是否还卡死、是否能选取。
  - 日志应出现 `queue cmd25a ...` 后接 `send turn X target=X+1 ... cmds=18`。
- 后续结论：
  - 用户反馈不卡死了，但事件仍不生效。
  - 最新日志显示命令帧后会立刻出现重复 target，例如 `send turn 19 target=20 cmds=15` 后又 `send turn 20 target=20 cmds=0`。
  - 这可能让客户端同一控制帧收到两种不同 `0x0138`，命令帧被普通 join 帧覆盖/打乱。

## 2026-07-11 修正：避免命令 target turn 重复

- 本次修改：
  - tick 结束时不再固定 `self.turn += 1`。
  - 改为 `self.turn = packet_turn + 1`。
  - 如果命令帧发到 `target=X+1`，下一帧从 `X+2` 开始，避免再发一个相同 target 的无命令帧。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地模拟确认：命令 `target=20` 后下一帧为 `21`，不再重复 `20`。
- 待验证：
  - 重新进游戏点击角色，观察是否能触发选角。
  - 日志中不应再出现连续两条相同 target 的 `send turn`。

## 2026-07-11 修正：0x025A 点击命令需要包装成 0x012E

- 新证据：
  - 客户端构造 `0x025A` 的路径在 `00421630` 附近。
  - 发送 TCP `0x025A` 成功后，官方本地路径会继续调用 `00420A80(..., 0x012E)`。
  - `00420A80` 会把原 `0x025A` 包体包装为一条队列命令：
    - `uint16 body_len = raw_len + 6`
    - `uint16 cmd = 0x012E`
    - `uint8 flag`
    - `uint8 seq`
    - `uint16 raw_len`
    - `raw_data`
  - 之前只回灌 `uint16 raw_len + raw_data`，没有 `0x012E` 命令号和 `flag/seq/raw_len` 上下文，脚本计时器能跑但点击事件不会按官方链路分发。
- 本次修改：
  - `0x025A` 入队改为官方包装格式：
    - `struct.pack("<HHBBH", n + 6, 0x012E, flag, seq, n) + data`
  - 继续走 `0x0138 kind=2` turn 队列，不恢复 `0x012F` 直发。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地包体检查：示例点击命令变为 `16 00 2e 01 01 02 10 00 ...`。
- 待验证：
  - 重新进游戏点击角色，日志应出现 `queue cmd25a ... raw=16 bytes=24 head=16 00 2e 01 ...`。
  - 若仍失败，下一步只查 `0x012E` 对应的确认/序号处理，不再改玩家身份链路。

## 2026-07-11 修正：连续 turn 和 0x0263 购买命令

- 新现象：
  - 用户确认选取角色已生效。
  - 购买不生效。
  - 走路像瞬移，一闪一闪。
- 新证据：
  - `cmd_1.log` 已出现大量 `DoCmd "MV"`，说明移动命令已进入脚本层。
  - 旧逻辑在有命令时发送 `target=self.turn+1`，随后 `self.turn=target+1`，导致 turn 号跳着发，移动表现会闪烁/瞬移。
  - 购买附近出现未处理 `0x0263`，payload 包含玩家/英雄/物品类字段；客户端构造路径 `004223F0` 发送后会调用 `00420A80(..., 0x013C)`。
- 本次修改：
  - turn 帧恢复连续递增：有命令也发送当前 `self.turn`，随后只 `self.turn += 1`。
  - `0x0263` 入队为 `h2c_cmd(0x013C, payload)`，继续走 `0x0138 kind=2` 队列。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地包体检查：示例 `0x0263` 变为 `1e 00 3c 01 ...`。
- 待验证：
  - 重新进游戏走路，日志中命令帧应为连续 `send turn X target=X ...`，不再跳号。
  - 购买时应出现 `queue cmd263 ... head=1e 00 3c 01 ...`，并观察 `buyItemCmd.log` 是否开始有内容。

## 2026-07-11 回滚：0x0263 不能直接包装成 0x013C

- 新现象：
  - 用户反馈购买物品时游戏闪退。
  - 走路更流畅一些，但仍有明显延迟。
- 新证据：
  - 最新服务端日志显示购买时 `queue cmd263 ... head=1e 00 3c 01 ...` 后客户端断开。
  - 反汇编 `00420A80` 对 `0x013C` 有专门重组逻辑，不是简单 `h2c_cmd(0x013C, raw_payload)`。
- 本次修改：
  - 撤销 `0x0263 -> 0x013C` 直接回灌，先避免购买闪退。
  - 保留连续 turn。
  - 默认 `control_turn` 从 `4` 降到 `2`，降低输入最多等待时间：约 `133ms -> 66ms`。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
- 待验证：
  - 购买不应再因为 `queue cmd263` 闪退；日志里不应再出现 `queue cmd263`。
  - 移动日志应显示 `recv control info(... turn 2 ...)`，体感延迟应比 turn 4 更低。

## 2026-07-11 修正：角色数据上传后回灌 0x026B

- 新现象：
  - 用户反馈初始选角色等非角色购买已经生效，但给已选角色购买装备不生效。
  - 最新日志显示装备相关操作后出现一串 `0x0269` 分片，随后 `0x0265 len=4`，而 `buyItemCmd.log` 仍为空。
- 新证据：
  - `0x0269` 构造路径只是把大块角色/玩家数据分片上传，不走 `00420A80` 本地命令包装。
  - 官方 `00422C10` 会生成下发包 `0x026B`，包体为 `uint16 1 + uint32 当前玩家id + 数据块`。
  - 因此缺的不是 `0x0263 -> 0x013C`，而是服务端收到 `0x0269` 分片后，在 `0x0265` 提交时把合并后的数据以 `0x026B` 广播回客户端。
- 本次修改：
  - `Client` 增加 `client_data` 缓冲。
  - 收到 `0x0269` 时，`flag=1` 清空缓冲并追加本片数据，其余分片继续追加。
  - 收到 `0x0265` 时，广播 `tcp_pkt(0x026B, <HI 1, global_id> + client_data)`。
  - 默认 `control_turn` 从 `2` 降到 `1`，把输入等待进一步降到约 `33ms`。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
- 待验证：
  - 重新进游戏购买装备，日志应出现 `send client data global_id=... bytes=...`，且不再出现 `tcp unknown 0x0265`。
  - 观察 `buyItemCmd.log` 是否开始记录购买命令或装备状态是否实际刷新。
  - 移动体感应比 `control_turn=2` 更低延迟；若抖动变明显，再把默认值回调到 2。

## 2026-07-11 修正：0x0263 购买包按官方 0x013C 回调格式重组

- 新现象：
  - 用户反馈移动延迟已可接受，但装备购买仍不生效。
  - 最新日志确认购买时仍先出现 `tcp recv 0x0263 len=32`，随后才有 `0x0269/0x0265` 角色数据上传。
- 新证据：
  - `gpigame.dll` 的 `lua_BuyItem` 会走平台购买命令；购买结果最终由 `BuyItemCallBack` 处理。
  - `BuyItemCallBack` 对应 `GameMsgDoCmd` 的 `0x013C` 分支。
  - `game.exe` 的 `00420A80` 对 `0x013C` 有专门重组：不是直接把 `0x0263` payload 塞进 `0x013C`，而是生成 `0x3D` 回调记录，再追加 `count * 8` 字节明细。
- 本次修改：
  - 新增 `buy_item_cmd(payload, global_id)`。
  - 收到 `0x0263` 后按官方布局生成 `h2c_cmd(0x013C, record_0x3D + detail_8n)` 并进入 turn 队列。
  - 对明细数量做长度上限裁剪，避免坏包再次导致购买闪退。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地样例 `0x0263` 生成命令头 `47 00 3c 01`，总长 `73 = 2 + 2 + 0x3D + 8`。
- 待验证：
  - 重新进游戏购买装备，日志应出现 `queue cmd263 ... head=47 00 3c 01 ...`。
  - 观察是否不闪退且 `buyItemCmd.log`/装备状态开始刷新。

## 2026-07-11 修正：补齐 0x013C 购买回调的第 4 个整数参数

- 新现象：
  - 用户反馈购买已有失败提示，说明 `0x0263 -> 0x013C -> BuyItemCallBack` 已经进入脚本/UI，不再是事件没生效。
- 新证据：
  - 原始 `0x0263` payload 至少有 5 个 dword：样例为 `(1, 278, 14, 1, 17)`。
  - `BuyItemCallBack` 读取 `0x3D` 记录里的 5 个整数参数：`[0] [4] [8] [0x0C] [0x10]`。
  - 旧重组只填了 `[0] [4] [8] [0x10]`，导致 `[0x0C]` 一直为 0，脚本拿到参数但判定失败。
- 本次修改：
  - `buy_item_cmd()` 将原始 payload 的第 5 个 dword (`payload[16:20]`) 填入 `record[0x0C:0x10]`。
  - `queue cmd263` 日志增加 `fields=(...)`，后续可直接核对购买包 5 个原始字段。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地样例生成回调前五个整数为 `(1, 1, 278, 17, 14)`，不再出现第四参数为 0。
- 待验证：
  - 重新进游戏购买装备，日志应出现 `queue cmd263 ... fields=(...) ... head=47 00 3c 01 ...`。
  - 观察购买失败提示是否消失，装备/资源是否刷新。

## 2026-07-11 修正：按官方栈布局恢复 0x013C 第 5 参数为 0

- 新现象：
  - 用户反馈仍提示购买失败。
  - 最新日志显示 `queue cmd263 ... fields=(1, 278, 14/15, 1, 17)`，`DoCmd[316]` 已进脚本命令层，但 `buyItemCmd.log` 仍为空。
- 新证据：
  - 复核 `game.exe 00420A80` 的 `0x013C` 分支后，官方记录布局是：
    - `record+0x00 = 当前玩家 id`
    - `record+0x04 = payload[0]`
    - `record+0x08 = payload[4]`
    - `record+0x0C = payload[8]`
    - `record+0x10 = 0`
    - `record+0x35 = count`
  - 旧修正把 `payload[16]` 塞进 `record+0x0C`，又把 `payload[8]` 塞进 `record+0x10`，导致 `BuyItemCallBack` 第 5 个整数不是官方的 0，可能被脚本当作失败码。
- 本次修改：
  - `buy_item_cmd()` 改回官方字段：`record[12:16] = payload[8:12]`，`record[16:20]` 保持 0。
  - `count` 改写到官方偏移 `record+0x35`。
- 已验证：
  - `py_compile` 通过。
  - `launcher.py --self-test` 通过。
  - 本地样例生成 `BuyItemCallBack` 前五个整数 `(1, 1, 278, 14, 0)`，`count_35=1`，明细 `(2205, 1)`。
- 待验证：
  - 重新进游戏购买装备，观察“购买失败”是否消失。
  - 若仍失败，下一步只查 `BuyItemCallBack` 第 4 参数和明细 `(item_id, count)` 的语义，不再动身份/移动链路。

## 下一步优先级

1. 让用户用 GUI 开房再跑一次，优先看 `cmd_1.log` 的 `map_name/max_player` 是否修正，以及身份是否出现。
2. 如果仍无身份，检查 `GetSessionPlayerInfo` 依赖的 `0x0130/0x0150` 玩家表字段。
3. 暂不再改 `0x0138` turn block，避免重新引入选择角色闪退。
