# HDHive Auth Broker

集中 OAuth 中转服务：持有 HDHive 应用 Secret，为 MoviePilot `p115strmhelper` 插件提供 OAuth 与 Open API 代理。

## HDHive 控制台配置

| 项 | 建议值 |
|----|--------|
| 授权结果投递 | 页面消息（`postmessage`） |
| Redirect URI 白名单 | 留空（使用环境变量 `HDHIVE_REDIRECT_URI`） |
| 预期服务端出口 IP | 在控制台填写 **本服务部署机的公网出口 IP**（部署后自行查询并登记，勿写入公开仓库） |
| Scope | 至少 `query`、`unlock` |

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `HDHIVE_CLIENT_ID` | 是 | OpenAPI 应用 ID |
| `HDHIVE_APP_SECRET` | 是 | 应用 Secret（仅本服务） |
| `HDHIVE_REDIRECT_URI` | 是 | authorize 与 token 交换共用的 redirect_uri |
| `LISTEN_ADDR` | 否 | 默认 `:8080`（容器内监听，一般无需改） |
| `HDHIVE_BASE_URL` | 否 | 默认 `https://hdhive.com` |
| `OAUTH_STATE_TTL_MINUTES` | 否 | 默认 `10` |
| `BROKER_HOST_PORT` | 否 | Compose 宿主机映射端口，默认 `8080`（见 `.env.example`） |

## 路由

- `GET /oauth/hdhive/start?instance_key=&scope=`
- `POST /oauth/hdhive/exchange`
- `POST /oauth/hdhive/refresh`
- `POST /oauth/hdhive/revoke`
- `ANY /proxy/open/*path` — 转发至 HDHive Open API（附加 `X-API-Key`）；**本中转自研路由，非 HDHive 官方路径**
- `GET /health`

## 一键部署（Docker Compose）

前置：已安装 [Docker](https://docs.docker.com/get-docker/) 与 Compose v2（`docker compose`）。

```bash
cd services/hdhive-auth-broker
cp .env.example .env
# 编辑 .env：填写 HDHIVE_CLIENT_ID、HDHIVE_APP_SECRET、HDHIVE_REDIRECT_URI
./scripts/deploy.sh
```

`deploy.sh` 会：检查 Docker → 确认 `.env` 存在 → `docker compose build` → `docker compose up -d` → 等待 `/health` 就绪。

若首次未创建 `.env`，脚本会从 `.env.example` 复制并退出，提示编辑后重跑。

## 一键更新

在已部署的机器上，于本目录执行：

```bash
./scripts/update.sh
```

默认在 monorepo 根目录执行 `git pull --ff-only`，然后重建镜像并重启容器。

仅本地重建、不拉代码：

```bash
./scripts/update.sh --no-pull
```

## 部署后检查清单

1. 本机：`curl -sf http://127.0.0.1:${BROKER_HOST_PORT:-8080}/health`
2. 公网（或反代后的 HTTPS）可访问同一 broker 对外 URL
3. HDHive 控制台登记 **本机公网出口 IP**
4. 插件 [`plugins.v2/p115strmhelper/helper/hdhive/open/constants.py`](../../plugins.v2/p115strmhelper/helper/hdhive/open/constants.py) 中 `HDHIVE_OAUTH_BROKER_BASE` 改为对外 URL（与 `HDHIVE_REDIRECT_URI` 域名一致或同站点）

### 可选：Nginx 反代 TLS

Compose 仅暴露 HTTP 端口；生产建议在宿主机用 Nginx/Caddy 做 HTTPS 终结，例如：

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

`HDHIVE_REDIRECT_URI` 与插件 `HDHIVE_OAUTH_BROKER_BASE` 应使用 **https://** 对外地址。

## 本地开发运行

```bash
cd services/hdhive-auth-broker
export HDHIVE_CLIENT_ID=app_xxx
export HDHIVE_APP_SECRET=your-secret
export HDHIVE_REDIRECT_URI=https://your-broker.example/oauth/hdhive/callback
go run ./cmd/server
```

## 测试

```bash
go test ./...
```

## 手工 Docker（无 Compose）

```bash
docker build -t hdhive-auth-broker .
docker run -p 8080:8080 \
  -e HDHIVE_CLIENT_ID=app_xxx \
  -e HDHIVE_APP_SECRET=secret \
  -e HDHIVE_REDIRECT_URI=https://your-broker.example/oauth/hdhive/callback \
  hdhive-auth-broker
```

插件侧在 `helper/hdhive/open/constants.py` 配置 `HDHIVE_OAUTH_BROKER_BASE`（公开 URL）。
