# 09 · 公网隧道运维手册（G2 过渡期 · 2026-11-01 实调固化）

> 本文固化 invest 公网直连链路（微信小程序体验版 → 家里 Mac）**实调攻克的全部障碍
> 与运维命令**。正式形态（备案域名 + HTTPS + Caddy）上线后本文降级为历史参考。
> 架构背景见 [07-architecture.md](07-architecture.md)；里程碑见 [prd/roadmap.md](../prd/roadmap.md) G2。

## 0. 链路终态（一图）

```
微信小程序(体验版+调试模式)
   │  http://47.92.235.34:8080（IP 直连，未备案域名的过渡形态）
   ▼
ECS frps 0.64.0（vhostHTTPPort=8080，按 Host 路由）
   ▼  frp 隧道（auth.token 认证）
Mac invest-frpc 容器（docker_default 网络，0.64.0 同版）
   ▼  容器对容器直连（localIP=star-invest-lan）
star-invest-lan :8792 容器（INVEST_AUTH_MODE=token 固定令牌）
   ▼
MySQL（star-mysql 容器，invest_dev 库）

备用链路：star 网关容器 → star-invest-star :8790 容器（star JWT 纵深防御）
```

## 1. 五层障碍与根因（排查时对号入座）

### 障碍一：凭据断层——"文档有架构、机器无凭据"

**现象**：仓库内 frps.toml/frpc.toml 全是占位符；SSH 无免密；aliyun CLI 未装。

**根因**：真实 token/密钥按约定不入库（正确），但换机后唯一载体是
`~/Desktop/换机迁移包/`（frpc.toml 含真实 token + hostHeaderRewrite 关键配置）。

**经验**：
- 排查公网链路故障先做**凭据考古**（迁移包/桌面 txt/zcode-memories），比要凭据快；
- ECS 登录密码变更后 SSH 用 expect 脚本注入（`/tmp/ecs-*.exp` 模式，密码勿落仓库）；
- **排除法验证凭据**：迁移包原版 toml 直接跑（硬编码 token）→ login success
  即证明 token 正确、问题在配置链——比读配置快十倍。

### 障碍二：ECS frps 配置格式大杂烩（INI 段被 TOML 解析静默忽略）

**现象**：frps 二进制 0.64.0（新版），但配置文件是 INI 老格式（`[common]`/`bind_port`）；
服务"正常跑着"，vhost 404、token 校验行为全部反直觉。

**根因**：frps ≥0.52 只认规范 TOML；INI 段键值对被**静默丢弃**，实际生效的全是默认值
（bind 7000 恰好同值 → 蒙混过关）。

**经验**：
- frp 升级二进制必须同步迁移配置格式（官方有 INI→TOML 迁移工具）；
- 验证配置是否真生效：`frps verify -c frps.toml`（只查语法）不够，要对照
  `ss -tlnp` 端口与 dashboard 实际值；
- 已重写为规范 TOML（保留原 token/dashboard 凭据，备份 frps.toml.bak-*）。

### 障碍三：frp 跨版本不兼容（控制面通、数据面 EOF）

**现象**：0.71.1 frpc 登录 frps 0.64.0 成功、proxy 注册成功，但 HTTP 转发
全部 `EOF`；换成 0.64.0 同版 frpc 立即通。

**根因**：frp 官方不保证跨版本兼容；work 连接协议随版本演进。

**经验**：
- **frpc 与 frps 必须严格同版**（镜像 tag 固定，禁止 latest）；
- 跨版本症状特征：`login success` + `start proxy success` + 转发层 EOF——
  别怀疑路由，先查版本；
- 国内拉镜像：`docker.m.daocloud.io`（Docker Hub 直连层下载被断）；
  GitHub release 大文件同理（ghfast/ghproxy 镜像，校验 gzip 完整性再解压）。

### 障碍四：Docker Desktop `--network host` 的回环陷阱（macOS 特有）

**现象**：frpc 容器 `--network host` + `localIP = 127.0.0.1:8792` → 转发
`connection refused`；同一配置 8080 却通。

**根因**：macOS 的 Docker `--network host` 是 **Linux VM 的 host**，不是 Mac 宿主——
`127.0.0.1` 指向 VM 回环；8080 之所以"通"是因为那本来就是 Docker 端口映射
（VM 内可见）。

**经验**（三层演进，终态最稳）：
1. `127.0.0.1` → 拒绝（VM 回环）
2. `host.docker.internal` + `--add-host=host.docker.internal:host-gateway` → 可通
   （桥接宿主），仍是间接层
3. **终态：frpc 与 invest 同入 docker_default 网络，`localIP=容器名` 容器对容器
   直连**——零间接、与 star 家族基建同形态
- 教训：macOS 上容器要访问宿主进程，先问"这个 host 到底是谁的 host"。

### 障碍五：常驻进程的三重围剿（nohup 时活时死 / launchd 被 TCC 拦 / 跨会话不稳）

**现象**：invest 用 nohup 跑宿主进程，公网链路"时好时坏"（8792 瞬时死亡）；
launchd KeepAlive 方案被 `Operation not permitted` 拒（Documents 路径保护，
`/bin/bash` 直调也被拦——TCC 按真实路径判定，wrapper 绕不开）。

**根因**：macOS 对 GUI 会话外的进程生命周期管理（TCC）与 invest 部署形态冲突。

**经验**：
- **容器是 macOS 上唯一可靠的常驻形态**（`--restart unless-stopped` 自愈，
  实测 restart 6 秒恢复、公网即通）；
- 容器化两个坑：
  - `pyobjc-framework-vision`（macOS Vision OCR）必须加 `sys_platform == 'darwin'`
    标记，否则 Linux 容器构建失败（找 `/usr/bin/sw_vers`）；运行期惰性导入天然降级；
  - 容器内默认 PyPI 被断——Dockerfile 固化 `UV_DEFAULT_INDEX=清华源`；
- invest 双容器（scripts/docker-serve.sh）：`star-invest-star:8790`（网关上游，
  star JWT）+ `star-invest-lan:8792`（隧道后端，固定令牌）。

## 2. 一次性部署与日常运维

```bash
# 全量拉起（顺序：invest 容器 → 隧道）
cd invest-platform
./scripts/docker-serve.sh   # 双容器（需 .env.dev：INVEST_JWT_SECRET/INVEST_LAN_TOKEN）
./scripts/frpc-up.sh        # 公网隧道（需 .env.dev：INVEST_FRP_TOKEN = ECS frps auth.token）

# 健康验证（三条全绿即链路健康）
curl http://127.0.0.1:8792/api/invest/ping                          # 本机容器
curl http://47.92.235.34:8080/api/invest/ping                        # 公网端到端
TOK=$(grep INVEST_LAN_TOKEN= .env.dev | cut -d= -f2 | tr -d "'")
curl -H "Authorization: Bearer $TOK" http://47.92.235.34:8080/api/invest/overview  # 带令牌真数据

# 故障排查顺序（对号入座第 1 节）
docker ps | grep invest          # 容器活着吗（自愈日志 docker logs <name>）
docker logs invest-frpc          # 隧道：login success? proxy success?
# ECS 侧：journalctl -u frps（SSH expect 模式或手动）
```

## 3. 密钥与凭据清单（全部走 .env.dev / 迁移包，不入库）

| 键 | 用途 | 来源 |
|---|---|---|
| INVEST_FRP_TOKEN | frpc↔frps 认证（= ECS frps.toml auth.token） | 换机迁移包/ECS |
| INVEST_LAN_TOKEN | :8792 固定令牌（= 小程序 VITE_INVEST_PUBLIC_TOKEN） | invest公开令牌.txt |
| INVEST_JWT_SECRET | star JWT 校验（<48 字节防 HS384 切换，见 G1 记录） | .env.dev |
| ECS root 密码 | SSH 运维（expect 注入） | 用户持有 |

## 3.5 日志巡检修复（2026-11-01 追加）

| 问题 | 修复 | 状态 |
|---|---|---|
| 网关 digest 盲区（Servlet Filter 在 WebFlux 不注册） | `GatewayDigestWebFilter`（WebFlux GlobalFilter，-200 先于 JWT）——rpc-server-digest.log 从 0 字节变为有真实 JSON 行 | ✅ 已部署验证 |
| traceId 入口不生成 | 网关入口 UUID 生成 + `X-Trace-Id` 头透传下游 | ✅ 已部署验证 |
| invest 无 trace 概念（跨语言断裂） | `TraceIdMiddleware`（读 X-Trace-Id → request.state → 响应头回传）——`curl -i` 即可拿到 traceId | ✅ 已部署验证 |
| MySQL slow_query_log OFF | `SET GLOBAL slow_query_log=ON, long_query_time=0.5` | ✅ 已生效 |
| family/reminder 503 | 网关有路由但服务未起（非本次 scope，巡检记录） | 📝 已记录 |

### 验证方法

```bash
# 网关 digest（JSON 行含 traceId/method/path/status/route）
docker exec star-platform-gateway cat logs/star-site-platform-gateway/rpc-server-digest.log | tail -3

# invest traceId 回传（curl -i 看 X-Trace-Id 响应头）
curl -i -H "X-Trace-Id: my-test-trace" -H "Authorization: Bearer <token>" http://<invest>/api/invest/ping | grep -i x-trace-id
```

## 4. 已知限制与后续

- **HTTP 明文 + IP 直连**：过渡形态。手机必须开"调试模式"（跳过域名校验）；
  正式形态（O1 前）= 备案域名 + HTTPS + Caddy（ECS 侧已有 Caddyfile 预置）。
- **Mac 睡眠即断链**：系统能源设置防睡眠（或 caffeinate）。
- **单点**：Mac/隧道/MySQL 全在家庭侧——家庭生产形态的既定取舍（数据主权留在家里）。
