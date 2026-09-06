# Plex MediaInfo Helper 部署说明

在 **Plex 所在机器（192.168.0.122）** 上运行的本地写库小服务。PlexToolbox 插件负责计算媒体流信息，通过 HTTP 发送到本服务，由本服务在 **数据库文件本地** 安全写入，避免跨网络写 SQLite 损库。

## 前置：找到 Plex 数据库路径

数据库文件名为 `com.plexapp.plugins.library.db`，通常在 Plex 配置目录下：

```
.../Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db
```

Docker 版 Plex 一般把配置目录挂在宿主机某处（如 `/path/to/plex/config`）。找到后，数据库就在该目录下的 `Library/Application Support/.../Databases/`。

## 方式 A：直接跑 Python + systemd（推荐，实际部署方式）

helper 纯 Python 标准库、零依赖，直接在能访问数据库文件的那层（LXC 或宿主）用 systemd 常驻即可，比 Docker 少一层文件系统开销。

下文用到两个占位符，请全程替换成你自己的值：

- `MySecretToken123`：helper 访问密码，自己随便设一串，稍后同样填进插件配置的「helper Token」
- `YourPlexTokenHere`：你的 Plex Token（用于繁忙检测，可留空跳过）

### 逐步部署（一条一条敲）

**第 1 步：SSH 登录 Plex 所在机器**

```bash
ssh root@192.168.0.122
```

**第 2 步：创建部署目录**

```bash
mkdir -p /opt/plex/helper
```

**第 3 步：把脚本传上去**（这条在 MoviePilot 那台机器上敲，不是在 Plex 机器上）

```bash
scp plex_mediainfo_helper.py root@192.168.0.122:/opt/plex/helper/
```

**第 4 步：创建 systemd 服务文件**（回到 Plex 机器上，用 nano 编辑器）

```bash
nano /etc/systemd/system/plex-mediainfo-helper.service
```

打开编辑器后，把下面内容整段粘贴进去（改好两个 token 和数据库路径），然后按 `Ctrl+O` 回车保存、`Ctrl+X` 退出：

```ini
[Unit]
Description=Plex MediaInfo Helper
After=network.target

[Service]
Type=simple
Environment=PTH_HOST=0.0.0.0
Environment=PTH_PORT=9001
Environment=PTH_TOKEN=MySecretToken123
Environment="PTH_DB_PATH=/opt/plex/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db"
Environment=PTH_PLEX_URL=http://127.0.0.1:32400
Environment=PTH_PLEX_TOKEN=YourPlexTokenHere
Environment=PTH_BACKUP_ON_WRITE=0
ExecStart=/usr/bin/python3 /opt/plex/helper/plex_mediainfo_helper.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> ⚠️ `PTH_DB_PATH` 那行因为路径带空格，整个 `KEY=value` 要用双引号包住（如上）。数据库路径改成你的实际路径。

**第 5 步：启动并设开机自启**（逐条敲）

```bash
systemctl daemon-reload
```

```bash
systemctl enable --now plex-mediainfo-helper
```

**第 6 步：验证**（逐条敲，都在 Plex 机器上）

```bash
systemctl status plex-mediainfo-helper --no-pager
```

```bash
curl http://127.0.0.1:9001/health
```

```bash
curl -H "X-PTH-Token: MySecretToken123" http://127.0.0.1:9001/dbinfo
```

看到 `status` 显示 `active (running)`、`/health` 返回 `{"ok": true...}`、`/dbinfo` 返回 `"success": true` 即部署完成。

### 日常更新 helper（改了脚本后）

只需两条。第一条在 MoviePilot 机器上敲：

```bash
scp plex_mediainfo_helper.py root@192.168.0.122:/opt/plex/helper/
```

第二条在 Plex 机器上敲：

```bash
systemctl restart plex-mediainfo-helper
```

### 常用运维命令

```bash
systemctl restart plex-mediainfo-helper     # 重启
systemctl stop plex-mediainfo-helper        # 停止
journalctl -u plex-mediainfo-helper -f      # 看实时日志
journalctl -u plex-mediainfo-helper -n 100  # 看最近 100 行日志
```

## 方式 B：Docker 运行（备选）

在 Plex 所在机器上，把 Plex 的 **配置目录** 挂进 helper 容器（只需能读写到数据库文件即可）。

### 1. 构建镜像

把 `helper/` 目录（含 `plex_mediainfo_helper.py` 和 `Dockerfile`）拷到目标机器，然后：

```bash
cd helper
docker build -t plex-mediainfo-helper:latest .
```

### 2. 运行容器

```bash
docker run -d --name plex-mediainfo-helper \
  --restart unless-stopped \
  -p 9001:9001 \
  -v "/path/to/plex/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases":"/db" \
  -e PTH_DB_PATH="/db/com.plexapp.plugins.library.db" \
  -e PTH_TOKEN="换成一个自定义密码" \
  -e PTH_PLEX_URL="http://192.168.0.122:32400" \
  -e PTH_PLEX_TOKEN="你的PlexToken" \
  plex-mediainfo-helper:latest
```

> 把 `/path/to/plex/config` 换成 Plex 实际的配置目录。
> `PTH_TOKEN` 自定义一个密码，稍后填进插件。
> `PTH_PLEX_TOKEN` 用于「Plex 繁忙时拒绝写入」的检测，可留空则跳过检测。

### 方式 B2：docker compose

`helper/` 目录内已提供 `docker-compose.yml`。改好里面的挂载路径与 token 后：

```bash
cd helper
docker compose up -d
```

需要修改的地方：`volumes` 左侧换成 Plex 实际的 `Databases` 目录，`PTH_TOKEN` 自定义密码，`PTH_PLEX_TOKEN` 填你的 Plex token（留空则跳过繁忙检测）。

## 无 Emby 时使用 ffprobe

PlexToolbox V3 可以不依赖 Emby：MoviePilot 会读取 Plex 条目对应的 `.strm` 首行，
直接用 ffprobe 探测其中的 P115 302 地址，再把媒体流信息发送给本 helper 写入 Plex。
该流程只读取 STRM，不会改写 STRM 内容；helper 仍必须部署在 Plex 数据库所在机器。

在 PlexToolbox 的「媒体信息补全」中：

1. 开启「启用 ffprobe」，Emby 可留空或关闭。
2. 将「Plex 路径 → MoviePilot 容器路径映射」设为实际映射，例如
   `/Volumes/data=/media`。
3. 确认 MP 容器能访问映射后的 `.strm` 文件，并用「检查 helper」确认写库服务可达。

路径左侧是 Plex API 返回的路径，右侧是 MoviePilot 容器内的路径；多条映射每行一条。

### 3. 验证

```bash
# 健康检查（无需 token）
curl http://192.168.0.122:9001/health

# 确认找到数据库（需 token）
curl -H "X-PTH-Token: 换成一个自定义密码" http://192.168.0.122:9001/dbinfo
```

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `PTH_HOST` | `0.0.0.0` | 监听地址 |
| `PTH_PORT` | `9001` | 监听端口 |
| `PTH_TOKEN` | 空 | 访问令牌，插件请求需带 `X-PTH-Token`；留空不校验 |
| `PTH_DB_PATH` | 空 | 数据库路径；留空则自动探测 |
| `PTH_BACKUP_KEEP` | `10` | 数据库备份保留份数 |
| `PTH_PLEX_URL` | `http://127.0.0.1:32400` | 本地 Plex 地址（繁忙检测用） |
| `PTH_PLEX_TOKEN` | 空 | Plex token（繁忙检测用）；留空跳过检测 |
| `PTH_REFUSE_WHEN_PLAYING` | `1` | 有播放会话时拒绝写入 |
| `PTH_BACKUP_ON_WRITE` | `0` | 每次写入前是否备份数据库；大库全量备份耗时高，默认关闭，需要兜底时置 `1` |

## 安全说明

- 写入前可选备份数据库到同目录 `pth_backups/`（`PTH_BACKUP_ON_WRITE=1` 开启，保留最近 N 份；默认关闭以提升写入速度）。
- 写入前检测 Plex 是否在播放/扫描，繁忙则拒绝（可用 `force` 覆盖）。
- 只写 Plex 数据库中 **实际存在的列**，不改表结构。
- 写 Plex 库属于非官方操作，Plex 大版本升级可能改表结构；升级后先用 `/dbinfo` 验证。

## 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（无需 token） |
| GET | `/dbinfo` | 返回数据库路径与候选 |
| GET | `/busy` | 返回 Plex 是否繁忙 |
| POST | `/write` | 写入单个 part 的媒体信息 |
| POST | `/write_batch` | 批量写入 |
