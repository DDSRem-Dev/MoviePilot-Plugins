#!/usr/bin/env bash
set -euo pipefail

target_branch=${1:?请指定推送目标分支}
git check-ref-format "refs/heads/$target_branch"
max_attempts=5

for ((attempt = 1; attempt <= max_attempts; attempt++)); do
  git fetch origin "refs/heads/$target_branch"
  if ! git rebase FETCH_HEAD; then
    echo "::error::同步远端时发生冲突，停止推送以保留远端修改"
    git rebase --abort
    exit 1
  fi

  if git push origin "HEAD:refs/heads/$target_branch"; then
    echo "新的 wheel 文件已成功提交并推送"
    exit 0
  fi

  if ((attempt < max_attempts)); then
    echo "推送失败，将同步远端后重试（${attempt}/${max_attempts}）"
    sleep "$((attempt * 2))"
  fi
done

echo "::error::推送失败，已达到 $max_attempts 次尝试上限"
exit 1
