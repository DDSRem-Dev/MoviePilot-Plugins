#!/usr/bin/env bash
# shellcheck shell=bash
# 供 deploy.sh / update.sh 共用的辅助函数

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${SERVICE_ROOT}"

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "错误: 未找到 docker，请先安装 Docker" >&2
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "错误: 未找到 docker compose v2（docker compose）" >&2
    exit 1
  fi
}

load_broker_port() {
  BROKER_HOST_PORT=8080
  if [[ -f .env ]]; then
    # shellcheck disable=SC1091
    set -a
    source .env
    set +a
  fi
  BROKER_HOST_PORT="${BROKER_HOST_PORT:-8080}"
}

ensure_env_file() {
  if [[ -f .env ]]; then
    return 0
  fi
  if [[ ! -f .env.example ]]; then
    echo "错误: 缺少 .env.example" >&2
    exit 1
  fi
  cp .env.example .env
  echo "已从 .env.example 生成 .env，请编辑填写 HDHIVE_CLIENT_ID、HDHIVE_APP_SECRET、HDHIVE_REDIRECT_URI 后重新运行本脚本"
  exit 1
}

compose_build_up() {
  echo "==> docker compose build"
  docker compose build
  echo "==> docker compose up -d"
  docker compose up -d --remove-orphans
}

http_health_ok() {
  local port="$1"
  local url="http://127.0.0.1:${port}/health"
  if command -v curl >/dev/null 2>&1; then
    curl -sf "${url}" >/dev/null 2>&1
    return $?
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -qO- "${url}" >/dev/null 2>&1
    return $?
  fi
  echo "警告: 未找到 curl/wget，跳过宿主机健康检查" >&2
  return 0
}

wait_for_health() {
  local port="$1"
  local max_attempts=30
  local attempt=1
  echo "==> 等待 /health (127.0.0.1:${port}) ..."
  while [[ "${attempt}" -le "${max_attempts}" ]]; do
    if http_health_ok "${port}"; then
      echo "健康检查通过"
      return 0
    fi
    sleep 2
    attempt=$((attempt + 1))
  done
  echo "错误: 健康检查超时" >&2
  docker compose logs --tail=50
  return 1
}

print_post_deploy_hints() {
  local port="$1"
  echo ""
  echo "部署完成。后续请确认："
  echo "  1. 公网可访问本服务（或通过反代暴露 HTTPS）"
  echo "  2. curl http://127.0.0.1:${port}/health"
  echo "  3. HDHive 控制台登记本机公网出口 IP"
  echo "  4. 插件 constants.py 中 HDHIVE_OAUTH_BROKER_BASE 改为对外 URL"
}
