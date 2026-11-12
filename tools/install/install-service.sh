#!/usr/bin/env bash
# ssot-kit · 可选：把嵌入服务装成常驻（macOS=launchd / Linux=systemd --user）
# 用法: bash scripts/install-service.sh [--dry] [--root DIR] [--llama PATH] [--port N]
# 行为: 生成单元文件并加载；--dry 只打印不落盘。幂等（先卸载同名单元再装）。
set -euo pipefail

ROOT="${SSOT_ROOT:-$HOME/ssot}"
PORT="${EMBED_PORT:-8399}"
LLAMA="${LLAMA_SERVER:-}"
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry)   DRY=1; shift ;;
    --root)  ROOT="$2"; shift 2 ;;
    --llama) LLAMA="$2"; shift 2 ;;
    --port)  PORT="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

KIT="$(cd "$(dirname "$0")/.." && pwd)"
SERVE="$ROOT/tools/serve_embed.sh"
MODEL="$ROOT/models/embeddinggemma-2-BF16.gguf"
LOG="/tmp/ssot-embed.log"
LABEL="com.ssot.embed"

[ -f "$SERVE" ] || { echo "❌ 缺 ${SERVE}（先跑 scripts/setup.sh）"; exit 1; }
if [ -z "$LLAMA" ]; then
  LLAMA="$(command -v llama-server || true)"
fi
if [ -z "$LLAMA" ]; then
  echo "⚠️ PATH 中未找到 llama-server；服务将按 PATH 查找。建议用 --llama /path/to/llama-server"
  LLAMA="llama-server"
fi
[ -f "$MODEL" ] || echo "⚠️ 缺模型 ${MODEL}（服务起不来；先按 docs/SEMANTIC.md 拉模型）"

xml_escape() {
  printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

health_check() {
  for _ in $(seq 1 15); do
    if curl -sf -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
      echo "✅ 健康检查通过：http://127.0.0.1:$PORT/health"
      return 0
    fi
    sleep 1
  done
  echo "❌ 服务未在 15s 内就绪；查看 $LOG"
  tail -20 "$LOG" 2>/dev/null || true
  return 1
}

case "$(uname -s)" in
  Darwin)
    PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
    unit="<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$(xml_escape "$SERVE")</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>SSOT_ROOT</key><string>$(xml_escape "$ROOT")</string>
    <key>EMBED_PORT</key><string>$PORT</string>
    <key>EMBED_MODEL</key><string>$(xml_escape "$MODEL")</string>
    <key>LLAMA_SERVER</key><string>$(xml_escape "$LLAMA")</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>"
    if [ "$DRY" = "1" ]; then
      echo "── （dry）$PLIST"
      printf '%s\n' "$unit"
      exit 0
    fi
    mkdir -p "$(dirname "$PLIST")"
    printf '%s\n' "$unit" > "$PLIST"
    plutil -lint "$PLIST"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    launchctl kickstart -k "gui/$(id -u)/$LABEL"
    echo "✅ 已加载 launchd：$PLIST"
    health_check
    ;;
  Linux)
    UNIT_DIR="$HOME/.config/systemd/user"
    UNIT="$UNIT_DIR/ssot-embed.service"
    unit="[Unit]
Description=ssot embedding service (llama.cpp)
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash $(printf '%q' "$SERVE")
Environment=SSOT_ROOT=$(printf '%q' "$ROOT")
Environment=EMBED_PORT=$PORT
Environment=EMBED_MODEL=$(printf '%q' "$MODEL")
Environment=LLAMA_SERVER=$(printf '%q' "$LLAMA")
Restart=always
RestartSec=3
StandardOutput=append:$LOG
StandardError=append:$LOG

[Install]
WantedBy=default.target"
    if [ "$DRY" = "1" ]; then
      echo "── （dry）$UNIT"
      printf '%s\n' "$unit"
      exit 0
    fi
    mkdir -p "$UNIT_DIR"
    printf '%s\n' "$unit" > "$UNIT"
    systemctl --user daemon-reload
    systemctl --user enable --now ssot-embed.service
    echo "✅ 已加载 systemd --user：$UNIT"
    health_check
    ;;
  *)
    echo "❌ 仅支持 macOS / Linux"; exit 1 ;;
esac
