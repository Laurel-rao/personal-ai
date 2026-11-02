#!/bin/bash
# ToDesk 彻底卸载（以 root 运行）
# 1. 停止并注销 launchd 服务  2. 杀进程  3. 删应用/helper/驱动/偏好
# 4. 转储目录改名后交给后台慢慢删（约 295GB、6.5 万+子目录）
set -x
exec >/tmp/todesk-uninstall.log 2>&1

D="/Library/Application Support/ToDesk"
CONSOLE_UID=$(stat -f %u /dev/console 2>/dev/null || echo 501)

# --- 1. 卸载 launchd 服务（先停，防止进程被拉起）---
for f in /Library/LaunchDaemons/com.youqu.todesk*.plist; do
  [ -f "$f" ] && launchctl bootout system "$f" 2>/dev/null
done
for f in /Library/LaunchAgents/com.youqu.todesk*.plist; do
  [ -f "$f" ] && launchctl bootout "gui/$CONSOLE_UID" "$f" 2>/dev/null
done
launchctl bootout "user/$CONSOLE_UID/com.youqu.todesk.startup" 2>/dev/null
launchctl bootout "user/$CONSOLE_UID/com.youqu.todesk.session" 2>/dev/null

# --- 2. 杀所有 ToDesk 进程 ---
pkill -9 -f 'ToDesk.app' 2>/dev/null
pkill -9 -f 'ToDeskOutputDriver' 2>/dev/null
sleep 1

# --- 3. 删除应用本体、helper、音频驱动、偏好、启动项 ---
rm -rf /Applications/ToDesk.app
rm -f /Library/PrivilegedHelperTools/com.youqu.todesk.UninstallerHelper
rm -rf '/Library/Audio/Plug-Ins/HAL/ToDeskOutputDriver.driver'
rm -f /Library/Preferences/com.youqu.todesk*.plist /Library/Preferences/com.todesk*.plist 2>/dev/null
rm -f /Library/LaunchDaemons/com.youqu.todesk*.plist /Library/LaunchAgents/com.youqu.todesk*.plist

# --- 4. 清空 ToDesk 数据目录：移除卸载器，把在写的转储目录改名，后台慢删 ---
if [ -d "$D" ]; then
  rm -rf "$D/ToDeskUninstaller.app"
  # 若服务又生成新的 dumps，先改名挪开
  if [ -d "$D/dumps" ]; then mv "$D/dumps" "$D/dumps_$(date +%s)" 2>/dev/null; fi
  # 后台删所有转储目录（超大目录，无超时）
  nohup bash -c '
    for d in "/Library/Application Support/ToDesk"/dumps*; do
      [ -e "$d" ] && rm -rf "$d"
    done
    rmdir "/Library/Application Support/ToDesk" 2>/dev/null
    echo "delete-done $(date) $(df -h / | awk "NR==2{print \$4}")"
  ' >>/tmp/todesk-delete.log 2>&1 &
  echo "background-delete-pid=$!"
fi

echo "uninstall-done $(date)"
