#!/usr/bin/env bash
# Run three retrieval variants side by side against the same database.
set -euo pipefail

ENVF=/home/hermes/.search-env
if [ ! -f "$ENVF" ]; then
  docker inspect saimon-search --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -E '^(DATABASE_URL|DEEPSEEK_API_KEY|SAIMON_[A-Z_]+|EMBEDDING_)=' > "$ENVF"
  chmod 600 "$ENVF"
fi

IMG=$(docker inspect saimon-search --format '{{.Config.Image}}')
NET=$(docker inspect saimon-search --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}')

run() {
  local name="$1" port="$2"; shift 2
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" --network "$NET" --env-file "$ENVF" "$@" \
    -e PORT=8001 -p "127.0.0.1:${port}:8001" "$IMG" search-mcp >/dev/null
}

run saimon-var-a 8110 -e SAIMON_RERANK_MAX_CHUNKS_PER_DOC=0 -e SAIMON_RERANK_TITLE_WEIGHT=0
run saimon-var-b 8111 -e SAIMON_RERANK_MAX_CHUNKS_PER_DOC=3 -e SAIMON_RERANK_TITLE_WEIGHT=0
run saimon-var-c 8112 -e SAIMON_RERANK_MAX_CHUNKS_PER_DOC=8 -e SAIMON_RERANK_TITLE_WEIGHT=0.08
sleep 20
for p in 8110 8111 8112; do printf '%s ' "$p"; curl -s -m 5 "http://127.0.0.1:$p/health" | head -c 90; echo; done
