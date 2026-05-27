#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

echo "==> HDHive Auth Broker 一键部署"
require_docker
ensure_env_file
load_broker_port
compose_build_up
wait_for_health "${BROKER_HOST_PORT}"
print_post_deploy_hints "${BROKER_HOST_PORT}"
