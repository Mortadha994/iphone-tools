#!/bin/bash
# Installs iPhone Tools for the current user (no root needed for the app itself).
set -e
cd "$(dirname "$0")"

missing=()
for c in ideviceinfo idevice_id idevicediagnostics idevicebackup2 idevicename; do
  command -v "$c" >/dev/null || missing+=("$c")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "Missing libimobiledevice tools: ${missing[*]}"
  echo "Install them with:  sudo apt install libimobiledevice-utils usbmuxd ifuse"
  exit 1
fi

APP_DIR="$HOME/.local/share/iphone-tools"
mkdir -p "$APP_DIR" "$HOME/.local/share/applications"
install -m 755 iphone_tools.py "$APP_DIR/iphone_tools.py"

cat > "$HOME/.local/share/applications/iphone-tools.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=iPhone Tools
Comment=iPhone info, battery health, backup and files (3uTools-style)
Exec=python3 $APP_DIR/iphone_tools.py
Icon=phone-apple-iphone
Terminal=false
Categories=Utility;
Keywords=iphone;ios;3utools;battery;backup;apple;
StartupWMClass=local.iphonetools
EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "Installed. Open “iPhone Tools” from your apps menu."
