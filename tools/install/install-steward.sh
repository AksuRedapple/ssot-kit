#!/usr/bin/env bash
# ssot-kit · 安装 6h 值守（macOS=launchd / Linux=systemd --user）
# 用法: bash scripts/install-steward.sh [--dry] [--uninstall] [--root DIR]
set -euo pipefail

ROOT="${SSOT_ROOT:-$HOME/ssot}"
DRY=0
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry) DRY=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --root) ROOT="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done
KIT="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${ROOT/#\~/$HOME}"
LABEL="com.ssot.steward"
LOG="$ROOT/alerts/steward.log"

if [ "$UNINSTALL" = "0" ] && [ "$DRY" = "0" ]; then
  mkdir -p "$ROOT/tools" "$ROOT/alerts" "$ROOT/sessions/_pending"
  cp -f "$KIT/tools/steward.sh" "$ROOT/tools/steward.sh"
  chmod +x "$ROOT/tools/steward.sh"
  echo "── steward 已同步 → $ROOT/tools/steward.sh"
elif [ "$DRY" = "1" ]; then
  echo "── （dry）不复制 steward、不加载单元"
fi

xml_escape() {
  printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

case "$(uname -s)" in
  Darwin)
    PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
    unit="<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$(xml_escape "$ROOT/tools/steward.sh")</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>HOME</key><string>$(xml_escape "$HOME")</string>
    <key>SSOT_ROOT</key><string>$(xml_escape "$ROOT")</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>21600</integer>
  <key>StandardOutPath</key><string>$(xml_escape "$ROOT/alerts/steward.stdout.log")</string>
  <key>StandardErrorPath</key><string>$(xml_escape "$ROOT/alerts/steward.stderr.log")</string>
</dict></plist>"
    if [ "$DRY" = "1" ]; then
      echo "── （dry）$PLIST"
      printf '%s\n' "$unit"
      exit 0
    fi
    if [ "$UNINSTALL" = "1" ]; then
      launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
      rm -f "$PLIST"
      echo "✅ 已卸载 $LABEL"
      exit 0
    fi
    mkdir -p "$(dirname "$PLIST")"
    printf '%s\n' "$unit" > "$PLIST"
    plutil -lint "$PLIST"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    launchctl kickstart -k "gui/$(id -u)/$LABEL"
    echo "✅ 已加载 launchd（6h）：$PLIST"
    ;;
  Linux)
    UNIT_DIR="$HOME/.config/systemd/user"
    SERVICE="$UNIT_DIR/ssot-steward.service"
    TIMER="$UNIT_DIR/ssot-steward.timer"
    service="[Unit]
Description=ssot 6h steward
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/bash $(printf '%q' "$ROOT/tools/steward.sh")
Environment=HOME=$(printf '%q' "$HOME")
Environment=SSOT_ROOT=$(printf '%q' "$ROOT")
"
    timer="[Unit]
Description=ssot steward every 6h

[Timer]
OnBootSec=5min
OnUnitActiveSec=6h
Persistent=true

[Install]
WantedBy=timers.target
"
    if [ "$DRY" = "1" ]; then
      echo "── （dry）$SERVICE"; printf '%s\n' "$service"
      echo "── （dry）$TIMER"; printf '%s\n' "$timer"
      exit 0
    fi
    if [ "$UNINSTALL" = "1" ]; then
      systemctl --user disable --now ssot-steward.timer 2>/dev/null || true
      rm -f "$SERVICE" "$TIMER"
      systemctl --user daemon-reload
      echo "✅ 已卸载 ssot-steward.timer"
      exit 0
    fi
    mkdir -p "$UNIT_DIR"
    printf '%s\n' "$service" > "$SERVICE"
    printf '%s\n' "$timer" > "$TIMER"
    systemctl --user daemon-reload
    systemctl --user enable --now ssot-steward.timer
    echo "✅ 已启用 systemd timer（6h）：$TIMER"
    ;;
  *)
    echo "❌ 仅支持 macOS / Linux"; exit 1 ;;
esac
