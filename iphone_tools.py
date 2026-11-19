#!/usr/bin/env python3
"""iPhone Tools - a 3uTools-style GTK4/libadwaita front-end for libimobiledevice."""

import glob
import math
import os
import plistlib
import re
import shutil
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gsk, Gtk, Pango  # noqa: E402

APP_ID = "local.iphonetools"
BACKUP_DIR = os.path.expanduser("~/iPhone Backups")

# Apple system colours (dark appearance)
GREEN, ORANGE, RED = "#30D158", "#FF9F0A", "#FF453A"
BLUE, PURPLE, GREY, YELLOW = "#0A84FF", "#BF5AF2", "#8E8E93", "#FFD60A"

MODELS = {
    "iPhone10,1": "iPhone 8", "iPhone10,4": "iPhone 8", "iPhone10,2": "iPhone 8 Plus", "iPhone10,5": "iPhone 8 Plus",
    "iPhone10,3": "iPhone X", "iPhone10,6": "iPhone X", "iPhone11,2": "iPhone XS", "iPhone11,4": "iPhone XS Max",
    "iPhone11,6": "iPhone XS Max", "iPhone11,8": "iPhone XR", "iPhone12,1": "iPhone 11", "iPhone12,3": "iPhone 11 Pro",
    "iPhone12,5": "iPhone 11 Pro Max", "iPhone12,8": "iPhone SE (2nd gen)", "iPhone13,1": "iPhone 12 mini",
    "iPhone13,2": "iPhone 12", "iPhone13,3": "iPhone 12 Pro", "iPhone13,4": "iPhone 12 Pro Max",
    "iPhone14,4": "iPhone 13 mini", "iPhone14,5": "iPhone 13", "iPhone14,2": "iPhone 13 Pro",
    "iPhone14,3": "iPhone 13 Pro Max", "iPhone14,6": "iPhone SE (3rd gen)", "iPhone14,7": "iPhone 14",
    "iPhone14,8": "iPhone 14 Plus", "iPhone15,2": "iPhone 14 Pro", "iPhone15,3": "iPhone 14 Pro Max",
    "iPhone15,4": "iPhone 15", "iPhone15,5": "iPhone 15 Plus", "iPhone16,1": "iPhone 15 Pro",
    "iPhone16,2": "iPhone 15 Pro Max", "iPhone17,3": "iPhone 16", "iPhone17,4": "iPhone 16 Plus",
    "iPhone17,1": "iPhone 16 Pro", "iPhone17,2": "iPhone 16 Pro Max", "iPhone17,5": "iPhone 16e",
    "iPhone18,3": "iPhone 17", "iPhone18,1": "iPhone 17 Pro", "iPhone18,2": "iPhone 17 Pro Max",
    "iPhone18,4": "iPhone Air",
}

CSS = f"""
.hero {{
  border-radius: 24px;
  padding: 22px 24px;
  color: white;
  background-image: linear-gradient(135deg, alpha({BLUE}, 0.85), alpha(#5E5CE6, 0.75) 55%, alpha({PURPLE}, 0.70));
  box-shadow: 0 10px 30px alpha(black, 0.30);
}}
.hero .name {{ font-size: 1.75em; font-weight: 800; }}
.hero .sub {{ opacity: 0.85; }}
.chip {{
  background: alpha(white, 0.20);
  border-radius: 999px;
  padding: 3px 11px;
  font-weight: 600;
  font-size: 0.85em;
}}
.float-icon {{ animation: float 2.8s ease-in-out infinite alternate; }}
@keyframes float {{
  from {{ -gtk-icon-transform: translate(0, 4px) rotate(-2deg); }}
  to   {{ -gtk-icon-transform: translate(0, -5px) rotate(2deg); }}
}}
.pulse-icon {{ animation: pulse 1.5s ease-in-out infinite alternate; }}
@keyframes pulse {{
  from {{ -gtk-icon-transform: scale(0.92); opacity: 0.45; }}
  to   {{ -gtk-icon-transform: scale(1.05); opacity: 1; }}
}}
.bolt {{ color: {YELLOW}; font-weight: 800; animation: blink 1.1s ease-in-out infinite alternate; }}
@keyframes blink {{ from {{ opacity: 0.30; }} to {{ opacity: 1; }} }}
.live-dot {{ color: {GREEN}; animation: blink 1.6s ease-in-out infinite alternate; }}
.card {{
  border-radius: 20px;
  padding: 18px;
  background: alpha(currentColor, 0.055);
}}
.section-title {{ font-weight: 800; font-size: 1.05em; }}
.gauge-sub {{ font-size: 0.85em; opacity: 0.70; }}
.tile {{
  border-radius: 18px;
  padding: 14px 6px 12px 6px;
  background: alpha(currentColor, 0.055);
  transition: background 180ms ease, box-shadow 220ms ease;
}}
.tile:hover {{ background: alpha(currentColor, 0.11); box-shadow: 0 8px 22px alpha(black, 0.28); }}
.tile image {{ transition: -gtk-icon-transform 260ms cubic-bezier(.2, .9, .3, 1.5); }}
.tile:hover image {{ -gtk-icon-transform: scale(1.18) translate(0, -2px); }}
.tile:active image {{ -gtk-icon-transform: scale(0.90); }}
.tile.danger label {{ color: {RED}; }}
.tile.busy {{ background: alpha({BLUE}, 0.20); }}
.dot {{ border-radius: 99px; min-width: 10px; min-height: 10px; }}
.dot-sys {{ background: {GREY}; }}
.dot-photo {{ background: {ORANGE}; }}
.dot-apps {{ background: {BLUE}; }}
.dot-free {{ background: alpha(currentColor, 0.18); }}
.legend-value {{ font-weight: 700; }}
.backup-card {{ border: 1px solid alpha({BLUE}, 0.45); background: alpha({BLUE}, 0.10); }}
.backup-card progressbar trough {{ min-height: 8px; border-radius: 99px; }}
.backup-card progressbar progress {{ min-height: 8px; border-radius: 99px; background: {BLUE}; }}
.empty-title {{ font-size: 1.6em; font-weight: 800; }}
.dropzone {{
  border: 2px dashed alpha(currentColor, 0.22);
  border-radius: 22px;
  padding: 26px 18px;
  transition: border-color 200ms ease, background 200ms ease;
}}
.dropzone.hover {{ border-color: {BLUE}; background: alpha({BLUE}, 0.12); }}
.dropzone image {{ transition: -gtk-icon-transform 320ms cubic-bezier(.2, .9, .3, 1.5); }}
.dropzone.hover image {{ -gtk-icon-transform: scale(1.22) rotate(-8deg); }}
.dropzone .big {{ font-size: 1.15em; font-weight: 800; }}
.hint-card {{ border-radius: 14px; padding: 12px 14px; background: alpha({GREEN}, 0.13); }}
.copy-card {{ border-radius: 18px; padding: 14px 16px; background: alpha({BLUE}, 0.12);
              border: 1px solid alpha({BLUE}, 0.40); }}
.copy-card progressbar trough {{ min-height: 8px; border-radius: 99px; }}
.copy-card progressbar progress {{ min-height: 8px; border-radius: 99px; background: {BLUE}; }}
.note-bounce {{ animation: float 0.9s ease-in-out infinite alternate; }}
.mirror-bg {{
  background-image: radial-gradient(circle at 50% 28%, alpha(#5E5CE6, 0.30), transparent 62%),
                    linear-gradient(#16161a, #0b0b0d);
}}
.phone-frame {{
  background: #050506;
  border-radius: 50px;
  padding: 11px;
  border: 1px solid alpha(white, 0.14);
  box-shadow: 0 24px 70px alpha(black, 0.65), inset 0 0 0 2px alpha(white, 0.05);
}}
.phone-frame.landscape {{ border-radius: 40px; }}
.screen {{ border-radius: 40px; background: black; }}
.phone-frame.landscape .screen {{ border-radius: 30px; }}
.live-pill {{
  background: alpha({RED}, 0.92); color: white; border-radius: 99px;
  padding: 2px 10px; font-weight: 800; font-size: 0.8em;
}}
.live-pill label {{ animation: blink 1.2s ease-in-out infinite alternate; }}
.fps {{ font-size: 0.8em; opacity: 0.6; font-feature-settings: "tnum"; }}
.step {{ border-radius: 14px; padding: 10px 14px; background: alpha(currentColor, 0.07); }}
.step-num {{
  background: {BLUE}; color: white; border-radius: 99px; min-width: 24px; min-height: 24px;
  font-weight: 800;
}}
.mirror-pill {{
  background: alpha(white, 0.22); color: white; border-radius: 99px; padding: 6px 14px; font-weight: 700;
  transition: background 180ms ease;
}}
.mirror-pill:hover {{ background: alpha(white, 0.34); }}
/* some themes (e.g. WhiteSur) restyle flat buttons: be more specific so the pill looks the same everywhere */
button.flat.mirror-pill {{ background: alpha(white, 0.22); border-radius: 99px; padding: 6px 14px; }}
button.flat.mirror-pill:hover {{ background: alpha(white, 0.34); }}
.mirror-pill label, .mirror-pill image {{ color: white; opacity: 1; }}
"""

# Apps that read songs from their "iTunes File Sharing" folder, with how to see them on the phone.
KNOWN_MUSIC_APPS = {
    "com.spotify.client": ("spotify",
                           "On the iPhone open Spotify → Settings, search “Local files” and turn on "
                           "“Show audio files from this device”. Songs appear in Your Library → Local Files."),
    "org.videolan.vlc-ios": ("vlc", "Songs appear in VLC’s Audio tab."),
}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".aif", ".aiff", ".alac", ".ogg", ".opus", ".mp4"}
MOUNT_DIR = os.path.expanduser("~/.cache/iphone-tools/mnt")
MIRROR_NAME = "iPhone Tools"              # name shown in the iPhone's Screen Mirroring list
MIRROR_PORT = 47800                       # local-only (127.0.0.1) handoff from uxplay to this app
SHOTS_DIR = os.path.expanduser("~/Pictures/iPhone Screenshots")
MIRROR_LOG = os.path.expanduser("~/.cache/iphone-tools/uxplay.log")


def rgba(colour, alpha=1.0):
    """'#RRGGBB' or a Gdk.RGBA -> Gdk.RGBA with the given alpha."""
    c = Gdk.RGBA()
    if isinstance(colour, Gdk.RGBA):
        c.red, c.green, c.blue = colour.red, colour.green, colour.blue
    else:
        c.parse(colour)
    c.alpha = alpha
    return c


# Icons that only some themes have (e.g. WhiteSur) get fallbacks; "iphone-tools" ships with the app.
ICON_FALLBACKS = {
    "phone-apple-iphone": ["phone-apple-iphone", "iphone-tools"],
    "org.gnome.Music": ["org.gnome.Music", "multimedia-audio-player", "audio-x-generic"],
    "deja-dup": ["deja-dup", "org.gnome.DejaDup", "document-save"],
    "spotify": ["spotify", "spotify-client", "org.gnome.Music", "audio-x-generic"],
    "vlc": ["vlc", "org.videolan.VLC", "multimedia-video-player", "audio-x-generic"],
}


def themed(name):
    """A GIcon that tries `name` first, then sensible fallbacks, so the app looks right on any icon theme."""
    names = ICON_FALLBACKS.get(name, [name])
    if name == "phone-apple-iphone":
        # Pick explicitly, because GTK searches the whole system theme for every fallback name before
        # hicolor: a full-colour theme iPhone (e.g. WhiteSur) > our own icon (installed, or the SVG next to
        # this file when running from a fresh clone). Stock Adwaita only has a flat -symbolic outline.
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        if _full_colour(theme, "phone-apple-iphone"):
            return Gio.ThemedIcon.new("phone-apple-iphone")
        if theme.has_icon("iphone-tools"):
            return Gio.ThemedIcon.new("iphone-tools")
        local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "iphone-tools.svg")
        if os.path.exists(local):
            return Gio.FileIcon.new(Gio.File.new_for_path(local))
    return Gio.ThemedIcon.new_from_names(names)


def _full_colour(theme, name):
    """True if the theme has a real colour icon for `name` (not just a monochrome -symbolic variant)."""
    if not theme.has_icon(name):
        return False
    paintable = theme.lookup_icon(name, None, 128, 1, Gtk.TextDirection.LTR, 0)
    f = paintable.get_file()
    where = (f.get_path() or f.get_uri() or "") if f else ""
    return bool(where) and "-symbolic" not in where


def pt(x, y):
    return Graphene.Point().init(x, y)


def arc_path(cx, cy, r, frac):
    """Clockwise arc from 12 o'clock covering `frac` of a circle (SVG arcs, so no cairo needed)."""
    b = Gsk.PathBuilder.new()
    frac = min(frac, 0.9999)
    b.move_to(cx, cy - r)
    if frac > 0.5:  # an SVG arc can't do >= 180 deg reliably in one go: go via 6 o'clock
        b.svg_arc_to(r, r, 0, False, True, cx, cy + r)
    a = -math.pi / 2 + 2 * math.pi * frac
    b.svg_arc_to(r, r, 0, False, True, cx + r * math.cos(a), cy + r * math.sin(a))
    return b.to_path()


def circle_path(cx, cy, r):
    b = Gsk.PathBuilder.new()
    b.add_circle(pt(cx, cy), r)
    return b.to_path()


def round_stroke(width):
    s = Gsk.Stroke.new(width)
    s.set_line_cap(Gsk.LineCap.ROUND)
    return s


def run(args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr.decode(errors="replace")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, b"", str(e)


def iphone_on_usb():
    """True if an Apple iPhone/iPad is physically plugged in (read from sysfs, no usbmuxd needed)."""
    for vendor in glob.glob("/sys/bus/usb/devices/*/idVendor"):
        try:
            if open(vendor).read().strip() != "05ac":
                continue
            product = open(os.path.join(os.path.dirname(vendor), "product")).read()
            if "iPhone" in product or "iPad" in product:
                return True
        except OSError:
            pass
    return False


def find_device():
    """-> (udid or None, problem) where problem is None, "service" (usbmuxd not answering)
    or "pairing" (phone plugged in but not listed: locked, not trusted, or lockdown error)."""
    rc, out, _ = run(["idevice_id", "-l"], timeout=5)
    ids = out.decode().split() if rc == 0 else []
    if ids:
        return ids[0], None
    if not iphone_on_usb():
        return None, None
    return None, ("service" if rc != 0 else "pairing")


def parse_info(raw):
    """Top-level 'Key: value' lines of ideviceinfo output."""
    out = {}
    for line in raw.decode(errors="replace").splitlines():
        if line[:1].isspace() or ": " not in line:
            continue
        k, v = line.split(": ", 1)
        out[k.strip()] = v.strip()
    return out


def gb(n):
    return f"{int(n) / 1e9:.1f} GB"


def read_device(udid):
    """Collect everything shown in the window. Runs in a worker thread."""
    d = {"udid": udid}
    rc, out, err = run(["ideviceinfo", "-u", udid])
    if rc != 0:
        d["error"] = err.strip() or "Could not read the iPhone. Unlock it and tap Trust."
        return d
    d["info"] = parse_info(out)
    d["battery"] = parse_info(run(["ideviceinfo", "-u", udid, "-q", "com.apple.mobile.battery"])[1])
    # Ask for each storage value on its own: fetching the whole disk_usage domain can hang for 20 s+
    # on iOS 26 (one of its internal keys is slow), while single keys answer in ~0.2-1 s.
    d["disk"] = {}
    for domain, key in [("com.apple.disk_usage", "TotalDiskCapacity"), ("com.apple.disk_usage", "TotalDataCapacity"),
                        ("com.apple.disk_usage", "TotalDataAvailable"), ("com.apple.disk_usage", "TotalSystemCapacity"),
                        ("com.apple.disk_usage.factory", "PhotoUsage")]:
        rc, out, _ = run(["ideviceinfo", "-u", udid, "-q", domain, "-k", key], timeout=6)
        value = out.decode(errors="replace").strip()
        if rc == 0 and value.isdigit():
            d["disk"][key] = value
    rc, out, _ = run(["idevicediagnostics", "-u", udid, "ioregentry", "AppleSmartBattery"])
    try:
        p = plistlib.loads(out) if rc == 0 and out else {}
        d["smart"] = p.get("IORegistry", p)
    except Exception:
        d["smart"] = {}
    return d


# ---------------------------------------------------------------- widgets
class Gauge(Gtk.Widget):
    """Animated ring gauge with a counting number in the middle (drawn with GSK paths)."""

    def __init__(self, caption, size=124):
        super().__init__(halign=Gtk.Align.CENTER)
        self.set_size_request(size, size)
        self.caption = caption
        self.color = BLUE
        self.frac = self.start_frac = self.end_frac = 0.0
        self.value = self.start_value = self.end_value = 0.0
        self.unit = "%"
        self.anim = None

    def animate_to(self, frac, color, value=None, unit="%"):
        frac = max(0.0, min(1.0, frac))
        self.color, self.unit = color, unit
        self.start_frac, self.end_frac = self.frac, frac
        self.start_value, self.end_value = self.value, (frac * 100 if value is None else value)
        if self.anim:
            self.anim.pause()
        target = Adw.CallbackAnimationTarget.new(self._tick)
        self.anim = Adw.TimedAnimation.new(self, 0.0, 1.0, 1300, target)
        self.anim.set_easing(Adw.Easing.EASE_OUT_EXPO)
        self.anim.play()

    def _tick(self, t):
        self.frac = self.start_frac + (self.end_frac - self.start_frac) * t
        self.value = self.start_value + (self.end_value - self.start_value) * t
        self.queue_draw()

    def _text(self, snap, text, px, weight, colour, cx, y):
        layout = self.create_pango_layout(text)
        fd = self.get_pango_context().get_font_description().copy()
        fd.set_absolute_size(px * Pango.SCALE)
        fd.set_weight(weight)
        layout.set_font_description(fd)
        tw, th = layout.get_pixel_size()
        snap.save()
        snap.translate(pt(cx - tw / 2, y))
        snap.append_layout(layout, colour)
        snap.restore()
        return th

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        fg = self.get_color()
        lw = 11
        r = min(w, h) / 2 - lw / 2 - 5
        cx, cy = w / 2, h / 2
        snap.append_stroke(circle_path(cx, cy, r), round_stroke(lw), rgba(fg, 0.10))  # track
        if self.frac > 0.003:
            arc = arc_path(cx, cy, r, self.frac)
            snap.append_stroke(arc, round_stroke(lw + 8), rgba(self.color, 0.20))  # soft glow
            snap.append_stroke(arc, round_stroke(lw), rgba(self.color))
            a = -math.pi / 2 + 2 * math.pi * min(self.frac, 0.9999)
            snap.append_fill(circle_path(cx + r * math.cos(a), cy + r * math.sin(a), 2.5),
                             Gsk.FillRule.WINDING, rgba("#FFFFFF", 0.9))  # bright tip
        self._text(snap, f"{self.value:.0f}{self.unit}", 26, Pango.Weight.HEAVY, rgba(fg), cx, cy - 24)
        self._text(snap, self.caption.upper(), 10.5, Pango.Weight.BOLD, rgba(fg, 0.55), cx, cy + 9)


class StorageBar(Gtk.Widget):
    """iPhone-Settings-style segmented bar that grows from the left."""

    def __init__(self):
        super().__init__(hexpand=True)
        self.set_size_request(-1, 18)
        self.segments = []  # [(fraction, colour)]
        self.t = 0.0
        self.anim = None

    def animate(self, segments):
        self.segments = segments
        if self.anim:
            self.anim.pause()
        self.anim = Adw.TimedAnimation.new(self, 0.0, 1.0, 1400,
                                           Adw.CallbackAnimationTarget.new(self._tick))
        self.anim.set_easing(Adw.Easing.EASE_OUT_EXPO)
        self.anim.play()

    def _tick(self, t):
        self.t = t
        self.queue_draw()

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        fg = self.get_color()
        clip = Gsk.RoundedRect()
        clip.init_from_rect(Graphene.Rect().init(0, 0, w, h), h / 2)
        snap.push_rounded_clip(clip)
        snap.append_color(rgba(fg, 0.12), Graphene.Rect().init(0, 0, w, h))
        x = 0.0
        for frac, colour in self.segments:
            seg = w * frac * self.t
            if seg > 2:
                snap.append_color(rgba(colour), Graphene.Rect().init(x, 0, seg - 2, h))  # 2 px gap
            x += seg
        snap.pop()


def stagger_reveal(revealers, step_ms=110):
    for i, r in enumerate(revealers):
        r.set_reveal_child(False)
        GLib.timeout_add(60 + i * step_ms, lambda rv=r: (rv.set_reveal_child(True), False)[1])


def revealer(child):
    r = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=420)
    r.set_child(child)
    return r


# ---------------------------------------------------------------- music (app file sharing)
def list_share_apps(udid):
    """Apps on the phone that accept files from a computer: [(bundle_id, name)]."""
    rc, out, _ = run(["ifuse", "-u", udid, "--list-apps"], timeout=30)
    apps = []
    for line in out.decode(errors="replace").splitlines():
        m = re.match(r'\s*([^,]+),\s*"[^"]*",\s*"(.*)"\s*$', line)
        if m and m.group(1) != "CFBundleIdentifier":
            apps.append((m.group(1).strip(), m.group(2)))
    # known music players first, Spotify at the top
    apps.sort(key=lambda a: (a[0] not in KNOWN_MUSIC_APPS, a[0] != "com.spotify.client", a[1].lower()))
    return apps


class AppDocs:
    """`with AppDocs(udid, app_id) as path:` mounts an app's Documents folder via ifuse."""

    def __init__(self, udid, app_id):
        self.udid, self.app_id, self.path = udid, app_id, MOUNT_DIR

    def __enter__(self):
        os.makedirs(self.path, exist_ok=True)
        subprocess.run(["fusermount", "-uz", self.path], capture_output=True)  # clear a stale mount
        rc, _, err = run(["ifuse", "-u", self.udid, "--documents", self.app_id, self.path], timeout=30)
        if rc != 0:
            raise RuntimeError(err.strip() or "Could not open the app folder on the iPhone")
        return self.path

    def __exit__(self, *exc):
        for _ in range(5):
            if subprocess.run(["fusermount", "-u", self.path], capture_output=True).returncode == 0:
                break
            time.sleep(0.4)
        else:
            subprocess.run(["fusermount", "-uz", self.path], capture_output=True)
        return False


def collect_audio(paths):
    """Expand files/folders into a sorted list of audio files."""
    found = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                found += [os.path.join(root, f) for f in files if os.path.splitext(f)[1].lower() in AUDIO_EXT]
        elif os.path.splitext(p)[1].lower() in AUDIO_EXT:
            found.append(p)
    return sorted(dict.fromkeys(found), key=lambda f: os.path.basename(f).lower())


class MusicWindow(Adw.Window):
    def __init__(self, parent, udid):
        super().__init__(transient_for=parent, modal=True, title="Add music", default_width=560, default_height=760)
        self.parent, self.udid = parent, udid
        self.apps, self.busy, self.cancel = [], False, False
        self.song_rows = []
        self.lock = threading.Lock()

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Add music", subtitle="From this PC to your iPhone"))
        self.spinner = Gtk.Spinner()
        header.pack_start(self.spinner)
        view.add_top_bar(header)

        clamp = Adw.Clamp(maximum_size=620)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                      margin_top=14, margin_bottom=24, margin_start=16, margin_end=16)
        clamp.set_child(col)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sc.set_child(clamp)
        view.set_content(sc)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        # target app
        tgt = Adw.PreferencesGroup(title="Send songs to")
        self.combo = Adw.ComboRow(title="Music app", model=Gtk.StringList.new(["Loading apps…"]), sensitive=False)
        self.app_icon = Gtk.Image(gicon=themed("org.gnome.Music"), pixel_size=32)
        self.combo.add_prefix(self.app_icon)
        self.combo.connect("notify::selected", lambda *_: self._target_changed())
        tgt.add(self.combo)
        col.append(tgt)
        self.hint = Gtk.Label(wrap=True, xalign=0, css_classes=["hint-card"])
        self.hint_rev = revealer(self.hint)
        col.append(self.hint_rev)

        # drop zone
        dz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["dropzone"])
        self.dz = dz
        self.dz_icon = Gtk.Image(gicon=themed("org.gnome.Music"), pixel_size=72, css_classes=["float-icon"])
        dz.append(self.dz_icon)
        dz.append(Gtk.Label(label="Drop songs or a folder here", css_classes=["big"]))
        dz.append(Gtk.Label(label="MP3 · M4A · AAC · WAV · FLAC …", css_classes=["caption", "dim-label"]))
        btns = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER, margin_top=6)
        self.pick_files = Gtk.Button(label="Choose songs…", css_classes=["pill", "suggested-action"])
        self.pick_files.connect("clicked", self._choose_files)
        self.pick_dir = Gtk.Button(label="Choose folder…", css_classes=["pill"])
        self.pick_dir.connect("clicked", self._choose_folder)
        btns.append(self.pick_files)
        btns.append(self.pick_dir)
        dz.append(btns)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("enter", lambda *_: (dz.add_css_class("hover"), Gdk.DragAction.COPY)[1])
        drop.connect("leave", lambda *_: dz.remove_css_class("hover"))
        drop.connect("drop", self._on_drop)
        dz.add_controller(drop)
        col.append(dz)

        # copy progress
        cc = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["copy-card"])
        top = Gtk.Box(spacing=10)
        top.append(Gtk.Image(icon_name="audio-x-generic", pixel_size=30, css_classes=["note-bounce"]))
        t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.cp_title = Gtk.Label(xalign=0, css_classes=["section-title"])
        self.cp_line = Gtk.Label(xalign=0, css_classes=["caption", "dim-label"], ellipsize=Pango.EllipsizeMode.MIDDLE)
        t.append(self.cp_title)
        t.append(self.cp_line)
        top.append(t)
        stop = Gtk.Button(label="Cancel", valign=Gtk.Align.CENTER, css_classes=["pill"])
        stop.connect("clicked", lambda *_: setattr(self, "cancel", True))
        top.append(stop)
        cc.append(top)
        self.cp_bar = Gtk.ProgressBar()
        cc.append(self.cp_bar)
        self.copy_rev = revealer(cc)
        self.copy_rev.set_visible(False)
        col.append(self.copy_rev)

        # songs already on the phone
        self.songs = Adw.PreferencesGroup(title="On your iPhone")
        self.count_lbl = Gtk.Label(css_classes=["dim-label"])
        self.songs.set_header_suffix(self.count_lbl)
        col.append(self.songs)

        self.connect("close-request", self._on_close)
        self._set_busy(True)
        threading.Thread(target=self._load_apps, daemon=True).start()

    # --- helpers
    def toast(self, msg):
        self.toasts.add_toast(Adw.Toast(title=msg, timeout=4))

    def _set_busy(self, busy):
        self.busy = busy
        (self.spinner.start if busy else self.spinner.stop)()
        for w in (self.pick_files, self.pick_dir):
            w.set_sensitive(not busy and bool(self.apps))
        self.combo.set_sensitive(not busy and bool(self.apps))

    def app_id(self):
        i = self.combo.get_selected()
        return self.apps[i][0] if 0 <= i < len(self.apps) else None

    def _on_close(self, *_):
        if self.busy:
            self.cancel = True
        return False

    # --- target apps
    def _load_apps(self):
        apps = list_share_apps(self.udid)
        GLib.idle_add(self._apps_loaded, apps)

    def _apps_loaded(self, apps):
        self.apps = apps
        if not apps:
            self.combo.set_model(Gtk.StringList.new(["No compatible app on the iPhone"]))
            self.hint.set_label("Install a music player that accepts files from a computer "
                                "(for example Spotify or VLC) from the App Store, then reopen this window.")
            self.hint_rev.set_reveal_child(True)
            self._set_busy(False)
            return False
        names = [n + ("  ♪" if a in KNOWN_MUSIC_APPS else "") for a, n in apps]
        self.combo.set_model(Gtk.StringList.new(names))
        self.combo.set_selected(0)
        self._set_busy(False)
        self._target_changed()
        return False

    def _target_changed(self):
        aid = self.app_id()
        if not aid:
            return
        icon, hint = KNOWN_MUSIC_APPS.get(
            aid, ("org.gnome.Music", "Songs go to this app’s folder (Files → On My iPhone). "
                                     "The app must be able to play files from there."))
        self.app_icon.set_from_gicon(themed(icon))
        self.hint_rev.set_reveal_child(False)
        self.hint.set_label("💡 " + hint)
        GLib.timeout_add(180, lambda: (self.hint_rev.set_reveal_child(True), False)[1])
        self.refresh_songs()

    # --- song list
    def refresh_songs(self):
        aid = self.app_id()
        if not aid or self.busy:
            return
        self._set_busy(True)
        threading.Thread(target=self._list_worker, args=(aid,), daemon=True).start()

    def _list_worker(self, aid):
        songs, err = [], None
        try:
            with self.lock, AppDocs(self.udid, aid) as mnt:
                for root, _d, files in os.walk(mnt):
                    for f in files:
                        if os.path.splitext(f)[1].lower() in AUDIO_EXT:
                            full = os.path.join(root, f)
                            songs.append((os.path.relpath(full, mnt), os.path.getsize(full)))
        except Exception as e:  # noqa: BLE001
            err = str(e)
        GLib.idle_add(self._show_songs, sorted(songs, key=lambda s: s[0].lower()), err)

    def _show_songs(self, songs, err):
        self._set_busy(False)
        for r in self.song_rows:
            self.songs.remove(r)
        self.song_rows = []
        if err:
            self.toast(f"Could not read the iPhone: {err[:80]}")
        total = sum(s for _, s in songs)
        self.count_lbl.set_label(f"{len(songs)} songs · {total / 1e6:.0f} MB" if songs else "")
        if not songs:
            r = Adw.ActionRow(title="No songs yet", subtitle="Drop some music above to get started")
            r.add_prefix(Gtk.Image(icon_name="audio-x-generic", pixel_size=28, opacity=0.5))
            self.songs.add(r)
            self.song_rows.append(r)
        for rel, size in songs:
            name = os.path.splitext(os.path.basename(rel))[0]
            r = Adw.ActionRow(title=GLib.markup_escape_text(name),
                              subtitle=f"{size / 1e6:.1f} MB · {os.path.splitext(rel)[1][1:].upper()}")
            r.add_prefix(Gtk.Image(icon_name="audio-x-generic", pixel_size=28))
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                            tooltip_text="Remove from iPhone", css_classes=["flat", "circular"])
            rm.connect("clicked", lambda _b, p=rel, n=name: self._confirm_delete(p, n))
            r.add_suffix(rm)
            self.songs.add(r)
            self.song_rows.append(r)
        return False

    def _confirm_delete(self, rel, name):
        d = Adw.MessageDialog(transient_for=self, heading="Remove song?",
                              body=f"“{name}” will be deleted from your iPhone. The copy on this PC is kept.")
        d.add_response("cancel", "Cancel")
        d.add_response("ok", "Remove")
        d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: self._delete(rel) if r == "ok" else None)
        d.present()

    def _delete(self, rel):
        aid = self.app_id()
        self._set_busy(True)

        def worker():
            err = None
            try:
                with self.lock, AppDocs(self.udid, aid) as mnt:
                    os.remove(os.path.join(mnt, rel))
            except Exception as e:  # noqa: BLE001
                err = str(e)
            GLib.idle_add(self._after_delete, err)
        threading.Thread(target=worker, daemon=True).start()

    def _after_delete(self, err):
        self._set_busy(False)
        self.toast("Song removed" if not err else f"Could not remove: {err[:80]}")
        self.refresh_songs()
        return False

    # --- choosing / dropping files
    def _audio_filter(self):
        f = Gtk.FileFilter()
        f.set_name("Music files")
        for e in sorted(AUDIO_EXT):
            f.add_suffix(e[1:])
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        return store, f

    def _start_folder(self):
        music = os.path.expanduser("~/Music")
        return Gio.File.new_for_path(music if os.path.isdir(music) else os.path.expanduser("~"))

    def _choose_files(self, *_):
        dlg = Gtk.FileDialog(title="Choose songs", modal=True)
        store, f = self._audio_filter()
        dlg.set_filters(store)
        dlg.set_default_filter(f)
        dlg.set_initial_folder(self._start_folder())

        def done(d, res):
            try:
                files = d.open_multiple_finish(res)
            except GLib.Error:
                return  # cancelled
            self.add_paths([files.get_item(i).get_path() for i in range(files.get_n_items())])
        dlg.open_multiple(self, None, done)

    def _choose_folder(self, *_):
        dlg = Gtk.FileDialog(title="Choose a music folder", modal=True)
        dlg.set_initial_folder(self._start_folder())

        def done(d, res):
            try:
                folder = d.select_folder_finish(res)
            except GLib.Error:
                return
            self.add_paths([folder.get_path()])
        dlg.select_folder(self, None, done)

    def _on_drop(self, _target, value, _x, _y):
        self.dz.remove_css_class("hover")
        self.add_paths([f.get_path() for f in value.get_files() if f.get_path()])
        return True

    # --- copying
    def add_paths(self, paths):
        if self.busy:
            self.toast("Please wait for the current task to finish")
            return
        files = collect_audio(paths)
        if not files:
            self.toast("No music files found there")
            return
        aid = self.app_id()
        self.cancel = False
        self._set_busy(True)
        self.cp_title.set_label(f"Sending {len(files)} song{'s' if len(files) > 1 else ''} to your iPhone…")
        self.cp_line.set_label("Connecting…")
        self.cp_bar.set_fraction(0)
        self.copy_rev.set_visible(True)
        self.copy_rev.set_reveal_child(True)
        threading.Thread(target=self._copy_worker, args=(aid, files), daemon=True).start()

    def _copy_worker(self, aid, files):
        total = sum(os.path.getsize(f) for f in files) or 1
        done_bytes, copied, skipped, err = 0, 0, 0, None
        try:
            with self.lock, AppDocs(self.udid, aid) as mnt:
                for n, src in enumerate(files, 1):
                    if self.cancel:
                        break
                    name = os.path.basename(src)
                    dst = os.path.join(mnt, name)
                    size = os.path.getsize(src)
                    GLib.idle_add(self._copy_progress, done_bytes / total, f"{n} of {len(files)} · {name}")
                    if os.path.exists(dst) and os.path.getsize(dst) == size:
                        skipped += 1
                        done_bytes += size
                        continue
                    part = dst + ".part"
                    with open(src, "rb") as fi, open(part, "wb") as fo:
                        while not self.cancel:
                            chunk = fi.read(1 << 20)
                            if not chunk:
                                break
                            fo.write(chunk)
                            done_bytes += len(chunk)
                            GLib.idle_add(self._copy_progress, done_bytes / total, None)
                    if self.cancel:
                        os.remove(part)
                        break
                    os.replace(part, dst)
                    copied += 1
        except Exception as e:  # noqa: BLE001
            err = str(e)
        GLib.idle_add(self._copy_done, copied, skipped, len(files), err)

    def _copy_progress(self, frac, line):
        self.cp_bar.set_fraction(min(frac, 1))
        if line:
            self.cp_line.set_label(line)
        return False

    def _copy_done(self, copied, skipped, total, err):
        self._set_busy(False)
        if err:
            self.cp_title.set_label("Copy stopped")
            self.cp_line.set_label(err[:120])
        elif self.cancel:
            self.cp_title.set_label(f"Cancelled · {copied} of {total} sent")
        else:
            self.cp_bar.set_fraction(1)
            extra = f" · {skipped} already there" if skipped else ""
            self.cp_title.set_label(f"Done ✔  {copied} song{'s' if copied != 1 else ''} sent{extra}")
            self.cp_line.set_label("Open the app on your iPhone to play them")
        self.toast(self.cp_title.get_label())

        def hide():
            self.copy_rev.set_reveal_child(False)
            GLib.timeout_add(500, lambda: (self.copy_rev.set_visible(False), False)[1])
            return False
        GLib.timeout_add_seconds(6, hide)
        self.refresh_songs()
        return False


# ---------------------------------------------------------------- screen mirroring (AirPlay via uxplay)
def wifi_name():
    rc, out, _ = run(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"], timeout=5)
    for line in out.decode(errors="replace").splitlines():
        if line.startswith("yes:"):
            return line[4:]
    return None


class MirrorWindow(Adw.Window):
    """Shows the iPhone screen live inside the app.

    uxplay (an AirPlay receiver) decodes the stream and, instead of opening its own window, hands the raw
    frames to us over a private 127.0.0.1 socket (gdppay ! tcpserversink). We read them with an appsink and
    paint them into a Gtk.Picture inside an iPhone-shaped frame."""

    def __init__(self, parent):
        super().__init__(transient_for=parent, title="Screen mirroring", default_width=500, default_height=920)
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        self.Gst = Gst
        Gst.init(None)
        self.proc = None
        self.client = None
        self.closing = False
        self.texture = None
        self.size = (0, 0)
        self.pending = None
        self.idle_queued = False
        self.frames = 0
        self.lock = threading.Lock()

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar(css_classes=["flat"])
        self.wtitle = Adw.WindowTitle(title="Screen mirroring", subtitle="Starting…")
        header.set_title_widget(self.wtitle)
        self.shot_btn = Gtk.Button(icon_name="camera-photo-symbolic", tooltip_text="Screenshot", sensitive=False)
        self.shot_btn.connect("clicked", self.screenshot)
        self.fs_btn = Gtk.Button(icon_name="view-fullscreen-symbolic", tooltip_text="Fullscreen")
        self.fs_btn.connect("clicked", self.toggle_fullscreen)
        header.pack_end(self.fs_btn)
        header.pack_end(self.shot_btn)
        self.live = Gtk.Box(css_classes=["live-pill"], visible=False, valign=Gtk.Align.CENTER)
        self.live.append(Gtk.Label(label="● LIVE"))
        header.pack_start(self.live)
        self.fps_lbl = Gtk.Label(css_classes=["fps"])
        header.pack_start(self.fps_lbl)
        view.add_top_bar(header)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=500,
                               css_classes=["mirror-bg"])
        self.stack.add_named(self.build_waiting(), "waiting")

        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.FILL, can_shrink=True, css_classes=["screen"])
        self.picture.set_overflow(Gtk.Overflow.HIDDEN)
        self.frame = Gtk.Box(css_classes=["phone-frame"])
        self.frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.frame.append(self.picture)
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        self.aspect = Gtk.AspectFrame(ratio=0.46, obey_child=False, xalign=0.5, yalign=0.5,
                                      margin_top=18, margin_bottom=22, margin_start=18, margin_end=18)
        self.aspect.set_child(self.frame)
        self.stack.add_named(self.aspect, "live")
        view.set_content(self.stack)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        self.connect("close-request", self._on_close)
        GLib.timeout_add_seconds(1, self._tick_fps)
        self.start_receiver()

    # --- layout
    def build_waiting(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, valign=Gtk.Align.CENTER,
                      halign=Gtk.Align.CENTER, margin_start=26, margin_end=26)
        box.append(Gtk.Image(gicon=themed("phone-apple-iphone"), pixel_size=120, css_classes=["pulse-icon"]))
        self.wait_title = Gtk.Label(label="Waiting for your iPhone", css_classes=["empty-title"])
        box.append(self.wait_title)
        ssid = wifi_name()
        steps = [
            f"Connect the iPhone to the same Wi‑Fi{f' — “{ssid}”' if ssid else ''}",
            "Swipe down from the top-right corner to open Control Center",
            f"Tap Screen Mirroring and choose “{MIRROR_NAME}”",
        ]
        self.steps_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=6)
        for i, text in enumerate(steps, 1):
            row = Gtk.Box(spacing=12, css_classes=["step"])
            row.append(Gtk.Label(label=str(i), css_classes=["step-num"], valign=Gtk.Align.CENTER))
            row.append(Gtk.Label(label=text, wrap=True, xalign=0, hexpand=True, max_width_chars=34))
            self.steps_box.append(row)
        box.append(self.steps_box)
        self.wait_err = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"],
                                  max_width_chars=44, visible=False, selectable=True)
        box.append(self.wait_err)
        return box

    def show_error(self, title, text):
        self.wait_title.set_label(title)
        self.wait_err.set_label(text)
        self.wait_err.set_visible(True)
        self.steps_box.set_visible(False)
        self.wtitle.set_subtitle("Not available")

    # --- uxplay receiver
    def start_receiver(self):
        if not shutil.which("uxplay"):
            self.show_error("Screen mirroring isn’t installed",
                            "Install it once in a terminal:\nsudo apt install uxplay gstreamer1.0-plugins-bad")
            return
        rc, out, _ = run(["pgrep", "-x", "uxplay"], timeout=5)
        if rc == 0:
            self.show_error("Another mirroring receiver is running",
                            "Close the other UxPlay window (or run “pkill uxplay”) and open this again.")
            return
        sink = f"gdppay ! tcpserversink host=127.0.0.1 port={MIRROR_PORT}"

        def die_with_app():  # Linux: SIGTERM uxplay automatically if this app exits or crashes
            import ctypes
            import signal
            ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
        try:
            self.proc = subprocess.Popen(
                # -avdec: decode on the CPU (a VA-API decoder outputs GPU memory, which can't go through
                #         the socket); -vsync no: don't hold frames for timestamp sync (they never left uxplay)
                ["uxplay", "-n", MIRROR_NAME, "-nh", "-p", "-reset", "0", "-avdec", "-vsync", "no", "-vs", sink],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0, preexec_fn=die_with_app)
        except OSError as e:
            self.show_error("Could not start mirroring", str(e))
            return
        self.wtitle.set_subtitle(f"Ready · choose “{MIRROR_NAME}” on your iPhone")
        threading.Thread(target=self._watch_receiver, daemon=True).start()
        GLib.timeout_add(1200, self._connect_client)

    def _watch_receiver(self):
        tail = []
        os.makedirs(os.path.dirname(MIRROR_LOG), exist_ok=True)
        with open(MIRROR_LOG, "w", encoding="utf-8") as log:  # kept for troubleshooting
            for raw in iter(self.proc.stdout.readline, b""):
                line = raw.decode(errors="replace").strip()
                if line:
                    log.write(time.strftime("%H:%M:%S ") + line + "\n")
                    log.flush()
                    tail = (tail + [line])[-8:]
        rc = self.proc.wait()
        if not self.closing:
            GLib.idle_add(self.show_error, "Mirroring stopped",
                          f"The receiver exited (code {rc}).\n" + "\n".join(tail[-4:]))

    # --- frame client
    def _connect_client(self):
        if self.closing or not self.proc or self.proc.poll() is not None:
            return False
        Gst = self.Gst
        self.client = Gst.parse_launch(
            f"tcpclientsrc host=127.0.0.1 port={MIRROR_PORT} ! gdpdepay ! videoconvert "
            "! video/x-raw,format=RGBA ! appsink name=out emit-signals=true max-buffers=1 drop=true sync=false")
        self.client.get_by_name("out").connect("new-sample", self._on_sample)
        bus = self.client.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_client_end)
        bus.connect("message::eos", self._on_client_end)
        self.client.set_state(Gst.State.PLAYING)
        return False

    def _on_client_end(self, _bus, _msg):
        # the receiver isn't streaming yet, or mirroring stopped: go back to waiting and retry
        if self.client:
            self.client.set_state(self.Gst.State.NULL)
            self.client = None
        if not self.closing:
            self._set_live(False)
            GLib.timeout_add(1000, self._connect_client)

    def _on_sample(self, sink):
        smp = sink.emit("pull-sample")
        st = smp.get_caps().get_structure(0)
        w, h = st.get_value("width"), st.get_value("height")
        buf = smp.get_buffer()
        ok, info = buf.map(self.Gst.MapFlags.READ)
        if ok:
            data = bytes(info.data)
            buf.unmap(info)
            with self.lock:
                self.pending = (w, h, data)
                if not self.idle_queued:
                    self.idle_queued = True
                    GLib.idle_add(self._paint)
        return self.Gst.FlowReturn.OK

    def _paint(self):
        with self.lock:
            frame, self.pending, self.idle_queued = self.pending, None, False
        if not frame or self.closing:
            return False
        w, h, data = frame
        stride = len(data) // h if h else w * 4
        self.texture = Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8A8, GLib.Bytes.new(data), stride)
        self.picture.set_paintable(self.texture)
        self.frames += 1
        if (w, h) != self.size:
            self.size = (w, h)
            self.aspect.set_ratio(w / h)
            (self.frame.add_css_class if w > h else self.frame.remove_css_class)("landscape")
        self._set_live(True)
        return False

    def _set_live(self, live):
        if live and self.stack.get_visible_child_name() != "live":
            self.stack.set_visible_child_name("live")
            self.wtitle.set_subtitle("Your iPhone screen, live")
        elif not live and self.stack.get_visible_child_name() != "waiting":
            self.stack.set_visible_child_name("waiting")
            self.wtitle.set_subtitle(f"Ready · choose “{MIRROR_NAME}” on your iPhone")
        self.live.set_visible(live)
        self.shot_btn.set_sensitive(live)
        if not live:
            self.fps_lbl.set_label("")

    def _tick_fps(self):
        if self.closing:
            return False
        if self.live.get_visible():
            self.fps_lbl.set_label(f"{self.frames} fps")
        self.frames = 0
        return True

    # --- actions
    def screenshot(self, *_):
        if not self.texture:
            return
        os.makedirs(SHOTS_DIR, exist_ok=True)
        path = os.path.join(SHOTS_DIR, time.strftime("iPhone %Y-%m-%d at %H.%M.%S.png"))
        self.texture.save_to_png(path)
        t = Adw.Toast(title="Screenshot saved", button_label="Open", timeout=5)
        t.connect("button-clicked", lambda *_: Gio.AppInfo.launch_default_for_uri(
            Gio.File.new_for_path(path).get_uri(), None))
        self.toasts.add_toast(t)

    def toggle_fullscreen(self, *_):
        if self.is_fullscreen():
            self.unfullscreen()
            self.fs_btn.set_icon_name("view-fullscreen-symbolic")
        else:
            self.fullscreen()
            self.fs_btn.set_icon_name("view-restore-symbolic")

    def _on_close(self, *_):
        self.closing = True
        if self.client:
            self.client.set_state(self.Gst.State.NULL)
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return False


# ---------------------------------------------------------------- window
class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="iPhone Tools", default_width=620, default_height=860)
        self.udid = None
        self.data = None
        self.busy = False
        self.backup_proc = None
        self.backup_started = time.time()

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.wtitle = Adw.WindowTitle(title="iPhone Tools", subtitle="Looking for your iPhone…")
        header.set_title_widget(self.wtitle)
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh")
        self.refresh_btn.connect("clicked", lambda *_: self.refresh())
        header.pack_end(self.refresh_btn)
        mirror_btn = Gtk.Button(icon_name="video-display-symbolic", tooltip_text="Mirror the iPhone screen")
        mirror_btn.connect("clicked", self.open_mirror)
        header.pack_end(mirror_btn)
        self.spinner = Gtk.Spinner()
        header.pack_start(self.spinner)
        view.add_top_bar(header)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=450)
        self.stack.add_named(self.build_empty(), "empty")
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self.build_device_page())
        self.stack.add_named(scroller, "device")
        view.set_content(self.stack)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        self.refresh()
        GLib.timeout_add_seconds(3, self.poll)

    # ---------- layout ----------
    def build_empty(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, valign=Gtk.Align.CENTER,
                      halign=Gtk.Align.CENTER, margin_start=30, margin_end=30)
        box.append(Gtk.Image(gicon=themed("phone-apple-iphone"), pixel_size=150, css_classes=["pulse-icon"]))
        self.empty_title = Gtk.Label(label="Connect your iPhone", css_classes=["empty-title"])
        self.empty_desc = Gtk.Label(label="Plug it in with a cable, unlock it and tap “Trust” on the phone.",
                                    wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"],
                                    max_width_chars=42)
        box.append(self.empty_title)
        box.append(self.empty_desc)
        wait = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=8)
        sp = Gtk.Spinner(spinning=True)
        wait.append(sp)
        wait.append(Gtk.Label(label="Waiting for device", css_classes=["dim-label"]))
        box.append(wait)
        self.repair_btn = Gtk.Button(label="Repair connection", halign=Gtk.Align.CENTER, margin_top=6,
                                     css_classes=["pill", "suggested-action"])
        self.repair_btn.connect("clicked", self.repair)
        self.repair_rev = revealer(self.repair_btn)
        box.append(self.repair_rev)
        return box

    def repair(self, *_):
        """Restart usbmuxd (Linux's iPhone connection service) via the graphical password prompt."""
        self.repair_btn.set_sensitive(False)
        self.repair_btn.set_label("Repairing…")

        def worker():
            rc, _, err = run(["pkexec", "systemctl", "restart", "usbmuxd"], timeout=180)
            time.sleep(3)  # let the phone reconnect
            GLib.idle_add(self._repaired, rc, err)
        threading.Thread(target=worker, daemon=True).start()

    def _repaired(self, rc, err):
        self.repair_btn.set_sensitive(True)
        self.repair_btn.set_label("Repair connection")
        if rc == 0:
            self.toast("Connection service restarted ✔")
        elif rc in (126, 127):
            self.toast("Repair cancelled")
        else:
            self.toast(f"Repair failed: {err.strip()[:80] or rc}")
        self.conn = None
        self.refresh()
        return False

    def card(self, title=None, extra_css=()):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=["card", *extra_css])
        if title:
            box.append(Gtk.Label(label=title, xalign=0, css_classes=["section-title"]))
        return box

    def build_device_page(self):
        clamp = Adw.Clamp(maximum_size=660, tightening_threshold=500)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                      margin_top=16, margin_bottom=24, margin_start=16, margin_end=16)
        clamp.set_child(col)

        # hero
        hero = Gtk.Box(spacing=20, css_classes=["hero"])
        hero.append(Gtk.Image(gicon=themed("phone-apple-iphone"), pixel_size=104, css_classes=["float-icon"]))
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.CENTER, hexpand=True)
        self.name_lbl = Gtk.Label(xalign=0, css_classes=["name"], ellipsize=Pango.EllipsizeMode.END)
        chips = Gtk.Box(spacing=6)
        self.model_chip = Gtk.Label(css_classes=["chip"])
        self.ios_chip = Gtk.Label(css_classes=["chip"])
        self.cap_chip = Gtk.Label(css_classes=["chip"])
        for c in (self.model_chip, self.ios_chip, self.cap_chip):
            chips.append(c)
        status = Gtk.Box(spacing=6)
        status.append(Gtk.Label(label="●", css_classes=["live-dot"]))
        self.status_lbl = Gtk.Label(xalign=0, css_classes=["sub"])
        status.append(self.status_lbl)
        txt.append(self.name_lbl)
        txt.append(chips)
        txt.append(status)
        mirror = Gtk.Button(css_classes=["flat", "mirror-pill"], halign=Gtk.Align.START, margin_top=4)
        mb = Gtk.Box(spacing=7)
        mb.append(Gtk.Image(icon_name="video-display-symbolic"))
        mb.append(Gtk.Label(label="Mirror screen"))
        mirror.set_child(mb)
        mirror.connect("clicked", self.open_mirror)
        txt.append(mirror)
        hero.append(txt)

        # gauges
        gcard = self.card()
        grid = Gtk.Box(homogeneous=True, spacing=8)
        self.g_batt = Gauge("Battery")
        self.g_health = Gauge("Health")
        self.g_store = Gauge("Used")
        self.batt_sub = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER)
        self.bolt = Gtk.Label(label="⚡", css_classes=["bolt"], visible=False)
        self.batt_sub_lbl = Gtk.Label(css_classes=["gauge-sub"])
        self.batt_sub.append(self.bolt)
        self.batt_sub.append(self.batt_sub_lbl)
        self.health_sub = Gtk.Label(css_classes=["gauge-sub"])
        self.store_sub = Gtk.Label(css_classes=["gauge-sub"])
        for g, sub in ((self.g_batt, self.batt_sub), (self.g_health, self.health_sub), (self.g_store, self.store_sub)):
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            b.append(g)
            b.append(sub)
            grid.append(b)
        gcard.append(grid)

        # storage
        scard = self.card("Storage")
        self.sbar = StorageBar()
        scard.append(self.sbar)
        legend = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                             min_children_per_line=2, max_children_per_line=4, column_spacing=8, row_spacing=6)
        self.legend_vals = {}
        for key, label in (("sys", "iOS & system"), ("photo", "Photos"), ("apps", "Apps & data"), ("free", "Free")):
            item = Gtk.Box(spacing=7)
            item.append(Gtk.Box(css_classes=["dot", f"dot-{key}"], valign=Gtk.Align.CENTER))
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            v.append(Gtk.Label(label=label, xalign=0, css_classes=["caption", "dim-label"]))
            val = Gtk.Label(xalign=0, css_classes=["legend-value"])
            v.append(val)
            item.append(v)
            self.legend_vals[key] = val
            legend.append(item)
        scard.append(legend)

        # backup progress (hidden until a backup runs)
        bcard = self.card(extra_css=("backup-card",))
        top = Gtk.Box(spacing=10)
        top.append(Gtk.Image(gicon=themed("deja-dup"), pixel_size=32))
        bt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.bk_title = Gtk.Label(label="Backing up…", xalign=0, css_classes=["section-title"])
        self.bk_line = Gtk.Label(xalign=0, css_classes=["caption", "dim-label"], ellipsize=Pango.EllipsizeMode.END)
        bt.append(self.bk_title)
        bt.append(self.bk_line)
        top.append(bt)
        stop = Gtk.Button(label="Stop", valign=Gtk.Align.CENTER, css_classes=["pill", "destructive-action"])
        stop.connect("clicked", lambda *_: self.backup())
        top.append(stop)
        bcard.append(top)
        self.bk_bar = Gtk.ProgressBar()
        bcard.append(self.bk_bar)
        self.backup_rev = revealer(bcard)
        self.backup_rev.set_visible(False)  # no empty gap in the column while hidden

        # actions
        acard = self.card("Quick actions")
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           min_children_per_line=3, max_children_per_line=3, column_spacing=10, row_spacing=10)
        self.tiles = {}
        for key, title, icon, cb, danger in [
            ("music", "Add music", "org.gnome.Music", self.open_music, False),
            ("photos", "Photos", "folder-pictures", self.open_photos, False),
            ("files", "App files", "folder-documents", self.open_files, False),
            ("backup", "Back up", "deja-dup", self.backup, False),
            ("backups", "My backups", "drive-harddisk", self.open_backups, False),
            ("rename", "Rename", "accessories-text-editor", self.rename, False),
            ("copy", "Copy info", "edit-copy", self.copy_info, False),
            ("restart", "Restart", "system-reboot", lambda *_: self.power("restart"), True),
            ("shutdown", "Shut down", "system-shutdown", lambda *_: self.power("shutdown"), True),
        ]:
            btn = Gtk.Button(css_classes=["flat", "tile"] + (["danger"] if danger else []))
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            b.append(Gtk.Image(gicon=themed(icon), pixel_size=40))
            lbl = Gtk.Label(label=title, css_classes=["caption-heading"])
            b.append(lbl)
            btn.set_child(b)
            btn.connect("clicked", cb)
            self.tiles[key] = (btn, lbl)
            flow.append(btn)
        acard.append(flow)

        # details
        details = Adw.PreferencesGroup(title="Details")
        self.fields = {}
        for key, title in [
            ("ProductVersion", "iOS version"), ("BuildVersion", "Build"), ("SerialNumber", "Serial number"),
            ("ModelNumber", "Model number"), ("RegionInfo", "Region"), ("ProductType", "Hardware"),
            ("WiFiAddress", "Wi-Fi address"), ("ActivationState", "Activation"),
            ("PasswordProtected", "Passcode"), ("Temperature", "Battery temperature"),
            ("Cycles", "Charge cycles"), ("Capacity", "Battery capacity"), ("udid", "UDID"),
        ]:
            r = Adw.ActionRow(title=title)
            lbl = Gtk.Label(selectable=True, xalign=1, css_classes=["dim-label"], wrap=True)
            r.add_suffix(lbl)
            details.add(r)
            self.fields[key] = lbl

        self.sections = [revealer(w) for w in (hero, gcard, scard, acard, details)]
        col.append(self.sections[0])
        col.append(self.sections[1])
        col.append(self.backup_rev)
        for r in self.sections[2:]:
            col.append(r)
        return clamp

    # ---------- device detection ----------
    def poll(self):
        if not self.busy and self.backup_proc is None:
            threading.Thread(target=self._poll_worker, daemon=True).start()
        return True

    def _poll_worker(self):
        state = find_device()
        if state != getattr(self, "conn", None):
            GLib.idle_add(self.refresh)

    def refresh(self, *_):
        if self.busy:
            return False
        self.busy = True
        self.spinner.start()
        threading.Thread(target=self._refresh_worker, daemon=True).start()
        return False

    def _refresh_worker(self):
        udid, problem = find_device()
        data = read_device(udid) if udid else None
        GLib.idle_add(self._show, udid, data, problem)

    def _show(self, udid, data, problem=None):
        self.busy = False
        self.spinner.stop()
        self.conn = (udid, problem)
        was_shown = self.stack.get_visible_child_name() == "device" and self.udid == udid
        self.udid, self.data = udid, data
        if not data or "error" in data:
            if problem == "service":
                self.empty_title.set_label("Connection problem")
                self.empty_desc.set_label("Your iPhone is plugged in, but Linux’s iPhone service stopped "
                                          "responding. Click Repair — you’ll be asked for your password.")
            elif data or problem == "pairing":
                self.empty_title.set_label("Unlock your iPhone")
                self.empty_desc.set_label("Unlock the phone and tap “Trust”. It will appear here automatically. "
                                          "Still nothing after a few seconds? Click Repair.")
            else:
                self.empty_title.set_label("Connect your iPhone")
                self.empty_desc.set_label("Plug it in with a cable, unlock it and tap “Trust” on the phone.")
            self.repair_rev.set_reveal_child(problem is not None)
            self.wtitle.set_subtitle("Connection problem" if problem == "service" else "No iPhone connected")
            self.stack.set_visible_child_name("empty")
            return False
        self.repair_rev.set_reveal_child(False)

        i, b, dk, s = data["info"], data["battery"], data["disk"], data["smart"]
        ptype = i.get("ProductType", "")
        model = MODELS.get(ptype, ptype or "iPhone")
        self.wtitle.set_subtitle(f"{model} connected")
        self.name_lbl.set_label(i.get("DeviceName", "iPhone"))
        self.model_chip.set_label(model)
        self.ios_chip.set_label(f"iOS {i.get('ProductVersion', '?')}")

        def num(src, k):
            try:
                return int(src.get(k, 0) or 0)
            except (TypeError, ValueError):
                return 0

        # battery
        lvl = num(b, "BatteryCurrentCapacity")
        charging = b.get("BatteryIsCharging") == "true"
        self.g_batt.animate_to(lvl / 100, GREEN if lvl > 50 else ORANGE if lvl > 20 else RED)
        self.bolt.set_visible(charging)
        self.batt_sub_lbl.set_label("Charging" if charging else ("Plugged in" if b.get("ExternalConnected") == "true"
                                                                 else "On battery"))
        self.status_lbl.set_label("Connected via USB" + (" · charging" if charging else ""))

        dc = s.get("DesignCapacity")
        mc = s.get("AppleRawMaxCapacity") or s.get("NominalChargeCapacity")
        if dc and mc:
            h = min(mc / dc * 100, 100)
            self.g_health.animate_to(h / 100, GREEN if h >= 85 else ORANGE if h >= 80 else RED, value=h)
            self.health_sub.set_label("Excellent" if h >= 90 else "Good" if h >= 80 else "Service recommended")
            self.fields["Capacity"].set_label(f"{mc} / {dc} mAh")
        else:
            self.g_health.animate_to(0, GREY)
            self.health_sub.set_label("Not available")
            self.fields["Capacity"].set_label("—")
        self.fields["Cycles"].set_label(str(s.get("CycleCount", "—")))
        t = s.get("Temperature")
        self.fields["Temperature"].set_label(f"{t / 100:.1f} °C" if t else "—")

        # storage — same maths as iPhone Settings > General > iPhone Storage
        total = num(dk, "TotalDiskCapacity") or num(dk, "TotalDataCapacity")
        free = num(dk, "TotalDataAvailable")
        system = num(dk, "TotalSystemCapacity") or max(total - num(dk, "TotalDataCapacity"), 0)
        photos = num(dk, "PhotoUsage") or num(dk, "CameraUsage")
        data_used = max(num(dk, "TotalDataCapacity") - free, 0)
        apps = max(data_used - photos, 0)
        if total:
            used = total - free
            self.cap_chip.set_label(f"{round(total / 1e9)} GB")
            self.g_store.animate_to(used / total, BLUE if used / total < 0.8 else ORANGE if used / total < 0.92 else RED)
            self.store_sub.set_label(f"{gb(free)} free")
            self.sbar.animate([(system / total, GREY), (photos / total, ORANGE), (apps / total, BLUE)])
            self.legend_vals["sys"].set_label(gb(system))
            self.legend_vals["photo"].set_label(gb(photos) if photos else "—")
            self.legend_vals["apps"].set_label(gb(apps))
            self.legend_vals["free"].set_label(gb(free))

        for key, lbl in self.fields.items():
            if key in ("Temperature", "Cycles", "Capacity"):
                continue
            v = udid if key == "udid" else i.get(key, "—")
            if key == "PasswordProtected":
                v = "On" if v == "true" else "Off  ⚠ set one in Settings"
            if key == "ProductType":
                v = f"{v} ({MODELS.get(v, 'unknown')})"
            lbl.set_label(v)

        self.stack.set_visible_child_name("device")
        if not was_shown:
            stagger_reveal(self.sections)
            if os.environ.get("IPHONE_TOOLS_OPEN") == "music" and not getattr(self, "music_win", None):
                GLib.timeout_add(600, lambda: (self.open_music(), False)[1])  # developer aid
            if os.environ.get("IPHONE_TOOLS_OPEN") == "mirror" and not getattr(self, "mirror_win", None):
                GLib.timeout_add(600, lambda: (self.open_mirror(), False)[1])  # developer aid
        return False

    # ---------- actions ----------
    def toast(self, msg):
        self.toasts.add_toast(Adw.Toast(title=msg, timeout=4))

    def need_device(self):
        if not self.udid or not self.data or "error" in self.data:
            self.toast("Connect and unlock your iPhone first")
            return False
        return True

    def _open_gvfs(self, prefix, what):
        if not self.need_device():
            return
        base = f"/run/user/{os.getuid()}/gvfs"
        uid = self.udid.replace("-", "")
        uri = f"gphoto2://Apple_Inc._iPhone_{uid}/" if prefix == "gphoto2" else f"afc://{self.udid}:3/"

        def worker():
            run(["gio", "mount", uri], timeout=20)
            target = None
            if os.path.isdir(base):
                for n in os.listdir(base):
                    if n.startswith(prefix + ":") and uid[:12] in n.replace("-", ""):
                        target = os.path.join(base, n)
            GLib.idle_add(self._launch, target or uri, what)
        threading.Thread(target=worker, daemon=True).start()

    def _launch(self, target, what):
        try:
            f = Gio.File.new_for_path(target) if target.startswith("/") else Gio.File.new_for_uri(target)
            Gio.AppInfo.launch_default_for_uri(f.get_uri(), None)
            self.toast(f"Opening {what}…")
        except GLib.Error as e:
            self.toast(f"Could not open {what}: unlock the iPhone and try again ({e.message})")
        return False

    def open_mirror(self, *_):
        win = getattr(self, "mirror_win", None)
        if win and win.get_visible():
            win.present()
            return
        self.mirror_win = MirrorWindow(self)  # works over Wi-Fi, no USB needed
        self.mirror_win.present()

    def open_music(self, *_):
        if not self.need_device():
            return
        self.music_win = MusicWindow(self, self.udid)
        self.music_win.present()

    def open_photos(self, *_):
        self._open_gvfs("gphoto2", "photos")

    def open_files(self, *_):
        self._open_gvfs("afc", "app files")

    def open_backups(self, *_):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(BACKUP_DIR).get_uri(), None)

    def copy_info(self, *_):
        if not self.need_device():
            return
        lines = [f"{self.name_lbl.get_label()} — {self.model_chip.get_label()} · {self.ios_chip.get_label()}",
                 f"Battery: {self.g_batt.end_value:.0f}% · health {self.g_health.end_value:.0f}% "
                 f"({self.health_sub.get_label()})",
                 "Storage: " + ", ".join(f"{k} {v.get_label()}" for k, v in self.legend_vals.items())]
        lines += [f"{k}: {lbl.get_label()}" for k, lbl in self.fields.items()]
        Gdk.Display.get_default().get_clipboard().set("\n".join(lines))
        self.toast("Info copied to clipboard")

    def confirm(self, heading, body, label, cb, destructive=False):
        d = Adw.MessageDialog(transient_for=self, heading=heading, body=body)
        d.add_response("cancel", "Cancel")
        d.add_response("ok", label)
        d.set_response_appearance(
            "ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED)
        d.connect("response", lambda _d, r: cb() if r == "ok" else None)
        d.present()

    def power(self, mode):
        if not self.need_device():
            return
        word = "Restart" if mode == "restart" else "Shut down"

        def go():
            rc, _, err = run(["idevicediagnostics", "-u", self.udid, mode])
            self.toast(f"{word} sent to iPhone" if rc == 0 else f"{word} failed: {err.strip()[:80]}")
        self.confirm(f"{word} iPhone?", f"Your iPhone will {word.lower()} now.", word, go, destructive=True)

    def rename(self, *_):
        if not self.need_device():
            return
        d = Adw.MessageDialog(transient_for=self, heading="Rename iPhone")
        entry = Gtk.Entry(text=self.data["info"].get("DeviceName", ""), activates_default=True)
        d.set_extra_child(entry)
        d.add_response("cancel", "Cancel")
        d.add_response("ok", "Rename")
        d.set_default_response("ok")
        d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def resp(_d, r):
            name = entry.get_text().strip()
            if r == "ok" and name:
                rc, _, err = run(["idevicename", "-u", self.udid, name])
                self.toast("Renamed ✔" if rc == 0 else f"Rename failed: {err.strip()[:80]}")
                self.refresh()
        d.connect("response", resp)
        d.present()

    # ---------- backup ----------
    def backup(self, *_):
        if self.backup_proc is not None:
            self.confirm("Stop the backup?", "The backup in progress will be cancelled.", "Stop backup",
                         self._stop_backup, destructive=True)
            return
        if not self.need_device():
            return
        free = shutil.disk_usage(os.path.expanduser("~")).free
        dk = self.data["disk"]
        try:
            used = int(dk.get("TotalDataCapacity", 0)) - int(dk.get("TotalDataAvailable", 0))
        except ValueError:
            used = 0
        body = (f"A backup of about {gb(used)} will be saved to “{BACKUP_DIR}” (after the first one, only "
                f"changes are copied). You have {gb(free)} free on this PC.\n\n"
                "Keep the iPhone plugged in and unlocked until it finishes. If it asks for your passcode, enter it.")
        self.confirm("Back up iPhone?", body, "Start backup", self._start_backup)

    def _start_backup(self):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        # pymobiledevice3 works on iOS 17+ and is incremental after the first backup;
        # libimobiledevice 1.3's idevicebackup2 hangs at "Requesting backup" on iOS 26.
        pmd3 = shutil.which("pymobiledevice3") or os.path.expanduser("~/.local/bin/pymobiledevice3")
        if os.path.exists(pmd3):
            cmd = [pmd3, "backup2", "backup", BACKUP_DIR]
        else:
            cmd = ["idevicebackup2", "-u", self.udid, "backup", "--full", BACKUP_DIR]
        try:
            self.backup_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        except OSError as e:
            self.toast(f"Backup could not start: {e}")
            return
        self.backup_started = time.time()
        btn, lbl = self.tiles["backup"]
        btn.add_css_class("busy")
        lbl.set_label("Backing up…")
        self.bk_title.set_label("Backing up your iPhone…")
        self.bk_line.set_label("Starting…")
        self.bk_bar.set_fraction(0)
        self.backup_rev.set_visible(True)
        self.backup_rev.set_reveal_child(True)
        threading.Thread(target=self._backup_worker, args=(self.backup_proc,), daemon=True).start()

    def _backup_worker(self, proc):
        buf, last = b"", ""
        pct_re = re.compile(rb"(\d{1,3})%")
        while True:
            ch = proc.stdout.read(256)
            if not ch:
                break
            buf += ch
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                last = p.decode(errors="replace")
                m = pct_re.findall(p)
                GLib.idle_add(self._backup_progress, last, int(m[-1]) / 100 if m else None)
        rc = proc.wait()
        GLib.idle_add(self._backup_done, rc, last)

    def _backup_progress(self, line, frac):
        if frac is not None:
            self.bk_bar.set_fraction(min(frac, 1))
            self.bk_title.set_label(f"Backing up your iPhone… {frac * 100:.0f}%")
        else:
            self.bk_bar.pulse()
        self.bk_line.set_label(line[:100])
        return False

    def _stop_backup(self):
        if self.backup_proc:
            self.backup_proc.terminate()

    def _backup_done(self, rc, last):
        self.backup_proc = None
        btn, lbl = self.tiles["backup"]
        btn.remove_css_class("busy")
        lbl.set_label("Back up")
        mins = (time.time() - self.backup_started) / 60
        ok = rc == 0 and "Aborted" not in last
        self.bk_title.set_label("Backup finished ✔" if ok else "Backup stopped")
        self.bk_line.set_label(f"{time.strftime('%d %b %H:%M')} · {mins:.0f} min · {BACKUP_DIR}")
        if ok:
            self.bk_bar.set_fraction(1)
        def hide():
            self.backup_rev.set_reveal_child(False)
            GLib.timeout_add(500, lambda: (self.backup_rev.set_visible(False), False)[1])
            return False
        GLib.timeout_add_seconds(8, hide)
        self.toast("Backup finished ✔" if ok else f"Backup did not finish: {last[:80]}")
        return False


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        css = Gtk.CssProvider()
        css.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)  # our own classes win over theme gtk.css

    def do_shutdown(self):
        for w in self.get_windows():  # quitting the app also stops the mirroring receiver
            mw = getattr(w, "mirror_win", None)
            if mw:
                mw._on_close()
        Adw.Application.do_shutdown(self)

    def do_activate(self):
        win = self.props.active_window or Window(self)
        win.present()
        if os.environ.get("IPHONE_TOOLS_OPEN") == "mirror":  # developer aid
            GLib.timeout_add(800, lambda: (win.open_mirror(), False)[1])
        shot = os.environ.get("IPHONE_TOOLS_SHOT")  # developer aid: save a PNG of the window
        if shot:
            GLib.timeout_add(int(os.environ.get("IPHONE_TOOLS_SHOT_MS", "4500")), self._shot, win, shot)

    def _shot(self, win, path):
        win = getattr(win, "music_win", None) or getattr(win, "mirror_win", None) or win
        w, h = win.get_width(), win.get_height()
        paintable = Gtk.WidgetPaintable(widget=win)
        snap = Gtk.Snapshot()
        paintable.snapshot(snap, w, h)
        node = snap.to_node()
        if node:
            win.get_native().get_renderer().render_texture(node, None).save_to_png(path)
        self.quit()
        return False


if __name__ == "__main__":
    App().run(None)
