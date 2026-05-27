#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

NO_PULL=false
for arg in "$@"; do
  case "${arg}" in
    --no-pull)
      NO_PULL=true
      ;;
    -h | --help)
      echo "用法: $0 [--no-pull]"
      echo "  --no-pull  跳过 git pull，仅重建并重启容器"
      exit 0
      ;;
    *)
      echo "未知参数: ${arg}（可用 --no-pull）" >&2
      exit 1
      ;;
  esac
done

echo "==> HDHive Auth Broker 一键更新"
require_docker
ensure_env_file

if [[ "${NO_PULL}" == "false" ]]; then
  REPO_ROOT="$(git -C "${SERVICE_ROOT}" rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -n "${REPO_ROOT}" ]]; then
    echo "==> git pull (${REPO_ROOT})"
    git -C "${REPO_ROOT}" pull --ff-only
  else
    echo "警告: 不在 git 仓库内，跳过 git pull" >&2
  fi
else
  echo "==> 跳过 git pull"
fi

load_broker_port
compose_build_up
if ! wait_for_health "${BROKER_HOST_PORT}"; then
  exit 1
fi
echo "更新完成"
