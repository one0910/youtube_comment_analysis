#!/usr/bin/env bash
# 這支腳本在 EC2 上執行；GitHub Actions 會先請 EC2 更新程式碼，再呼叫它。
# 它只操作 TubeSense 的正式版 Compose，不會停止 Water Drop 專案。
set -euo pipefail

# 任一步驟出錯就停止；第一個參數必須是「剛通過 CI 的 commit 編號」。
expected_sha="${1:?expected commit SHA is required}"
if [[ ! "$expected_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid commit SHA" >&2
  exit 2
fi

cd /home/ubuntu/tubesense-ai
actual_sha="$(git rev-parse HEAD)"
# 如果 main 已經往前更新，就跳過這次舊部署，避免把新版蓋回舊版。
if [[ "$actual_sha" != "$expected_sha" ]]; then
  echo "Skipping superseded CI run: expected $expected_sha, current main is $actual_sha"
  exit 0
fi

# 正式環境的密碼與 API Key 留在 EC2，不放進 GitHub；缺檔就不部署。
if [[ ! -f .env.production || ! -f .env.postgres ]]; then
  echo "Missing .env.production or .env.postgres" >&2
  exit 1
fi
# 這台 EC2 的 80 Port 已由 Water Drop Gateway 使用，TubeSense 必須用 8090。
if ! grep -qx 'TUBESENSE_HTTP_PORT=8090' .env.production; then
  echo "Expected TUBESENSE_HTTP_PORT=8090 for the shared EC2 gateway" >&2
  exit 1
fi

# 把固定的 Compose 指令和參數存成 Bash 陣列；後面的 "${compose[@]}" 會逐項取出來執行。
# 這樣不用每次都重寫 docker compose --env-file ... -f ...。
compose=(docker compose --env-file .env.production -f compose.production.yaml)
# 先檢查 Compose 設定能否正確解析，還不會改動正在跑的容器。
"${compose[@]}" config --quiet

# 在 EC2 建置新版 image；GitHub 不負責建置或推送 image。
echo "Building TubeSense image for $actual_sha"
"${compose[@]}" build web worker

# 更新 TubeSense 的 web、worker、nginx；相依的資料庫與 Redis 由 Compose 處理。
# --remove-orphans 只針對 TubeSense 這個 Compose 專案，不會清掉 Water Drop 容器。
echo "Updating TubeSense services"
"${compose[@]}" up -d --no-build --remove-orphans web worker nginx

# 讓 Nginx 重新取得新版 web 容器的位址，避免它還連到舊容器。
"${compose[@]}" restart nginx

# 最多等約 5 分鐘：web、nginx 要通過健康檢查，worker 要保持執行。
for attempt in {1..60}; do
  web_id="$("${compose[@]}" ps -q web)"
  nginx_id="$("${compose[@]}" ps -q nginx)"
  worker_id="$("${compose[@]}" ps -q worker)"

  if [[ -n "$web_id" && -n "$nginx_id" && -n "$worker_id" ]] \
    && [[ "$(docker inspect --format '{{.State.Health.Status}}' "$web_id")" == healthy ]] \
    && [[ "$(docker inspect --format '{{.State.Health.Status}}' "$nginx_id")" == healthy ]] \
    && [[ "$(docker inspect --format '{{.State.Running}}' "$worker_id")" == true ]]; then
    echo "TubeSense services are healthy at $actual_sha"
    "${compose[@]}" ps
    exit 0
  fi
  sleep 5
done

# 等候逾時就把狀態和最近的日誌印出來，方便在 GitHub Actions 查原因。
echo "TubeSense services did not become healthy" >&2
"${compose[@]}" ps >&2
"${compose[@]}" logs --tail 50 web worker nginx >&2
exit 1
