#!/bin/bash
# iPhone Tools installer (current user only, no root needed for the app itself).
#   ./install.sh             install or update
#   ./install.sh --uninstall remove the app (your backups and screenshots are kept)
set -e
cd "$(dirname "$0")"

APP_DIR="$HOME/.local/share/iphone-tools"
DESKTOP="$HOME/.local/share/applications/iphone-tools.desktop"
ICON="$HOME/.local/share/icons/hicolor/scalable/apps/iphone-tools.svg"

if [ "$1" = "--uninstall" ]; then
  rm -rf "$APP_DIR" "$DESKTOP" "$ICON"
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
  echo "iPhone Tools removed. (~/iPhone Backups and ~/Pictures/iPhone Screenshots were kept.)"
  exit 0
fi

need=()      # apt packages that are required
optional=()  # human-readable optional hints

have_py() { python3 -I -c "$1" >/dev/null 2>&1; }
have_gst() { gst-inspect-1.0 "$1" >/dev/null 2>&1; }

# --- Python + GTK4 / libadwaita / GStreamer bindings
have_py 'import gi' || need+=(python3-gi)
have_py 'import gi; gi.require_version("Gtk","4.0"); from gi.repository import Gtk; assert (Gtk.get_major_version(),Gtk.get_minor_version()) >= (4,14)' \
  || need+=(gir1.2-gtk-4.0)
have_py 'import gi; gi.require_version("Adw","1"); from gi.repository import Adw; assert (Adw.get_major_version(),Adw.get_minor_version()) >= (1,5)' \
  || need+=(gir1.2-adw-1)
have_py 'import gi; gi.require_version("Gst","1.0"); from gi.repository import Gst' || need+=(gir1.2-gstreamer-1.0)
for e in videoconvert appsink tcpclientsrc; do have_gst "$e" || { need+=(gstreamer1.0-plugins-base); break; }; done

# --- iPhone access (libimobiledevice)
for c in idevice_id ideviceinfo idevicediagnostics idevicename idevicebackup2; do
  command -v "$c" >/dev/null || { need+=(libimobiledevice-utils); break; }
done
[ -x /usr/sbin/usbmuxd ] || command -v usbmuxd >/dev/null || need+=(usbmuxd)
command -v ifuse >/dev/null || need+=(ifuse)
command -v fusermount >/dev/null || command -v fusermount3 >/dev/null || need+=(fuse3)

if [ ${#need[@]} -gt 0 ]; then
  pkgs=$(printf '%s\n' "${need[@]}" | sort -u | tr '\n' ' ')
  echo "Some required packages are missing. Install them with:"
  echo
  echo "    sudo apt install -y $pkgs"
  echo
  echo "then run ./install.sh again."
  exit 1
fi

# --- optional features
if ! command -v uxplay >/dev/null || ! have_gst gdppay || ! have_gst h264parse; then
  optional+=("Screen mirroring:  sudo apt install -y uxplay gstreamer1.0-plugins-bad")
fi
if ! command -v pymobiledevice3 >/dev/null && [ ! -x "$HOME/.local/bin/pymobiledevice3" ]; then
  optional+=("Backups on iOS 17+: sudo apt install -y pipx && pipx install pymobiledevice3")
fi

# --- install
mkdir -p "$APP_DIR" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
install -m 755 iphone_tools.py "$APP_DIR/iphone_tools.py"
install -m 644 data/iphone-tools.svg "$ICON"
gtk-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=iPhone Tools
Comment=iPhone info, battery health, music, backup, files and screen mirroring
Exec=python3 $APP_DIR/iphone_tools.py
Icon=iphone-tools
Terminal=false
Categories=Utility;
Keywords=iphone;ios;3utools;battery;backup;apple;mirror;airplay;music;
StartupWMClass=local.iphonetools
EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "✔ iPhone Tools installed. Open “iPhone Tools” from your apps menu."
if [ ${#optional[@]} -gt 0 ]; then
  echo
  echo "Optional extras (the app works without them):"
  printf '  • %s\n' "${optional[@]}"
fi
