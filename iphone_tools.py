#!/usr/bin/env python3
"""iPhone Tools - a 3uTools-style GTK4/libadwaita front-end for libimobiledevice."""

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
"""


def rgba(colour, alpha=1.0):
    """'#RRGGBB' or a Gdk.RGBA -> Gdk.RGBA with the given alpha."""
    c = Gdk.RGBA()
    if isinstance(colour, Gdk.RGBA):
        c.red, c.green, c.blue = colour.red, colour.green, colour.blue
    else:
        c.parse(colour)
    c.alpha = alpha
    return c


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
    # the ".factory" domain has the same totals plus per-category usage (photos...)
    d["disk"] = parse_info(run(["ideviceinfo", "-u", udid, "-q", "com.apple.disk_usage.factory"])[1])
    if "TotalDiskCapacity" not in d["disk"]:
        d["disk"] = parse_info(run(["ideviceinfo", "-u", udid, "-q", "com.apple.disk_usage"])[1])
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
        box.append(Gtk.Image(icon_name="phone-apple-iphone", pixel_size=150, css_classes=["pulse-icon"]))
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
        return box

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
        hero.append(Gtk.Image(icon_name="phone-apple-iphone", pixel_size=104, css_classes=["float-icon"]))
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
        top.append(Gtk.Image(icon_name="deja-dup", pixel_size=32))
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
                           min_children_per_line=2, max_children_per_line=4, column_spacing=10, row_spacing=10)
        self.tiles = {}
        for key, title, icon, cb, danger in [
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
            b.append(Gtk.Image(icon_name=icon, pixel_size=40))
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
        rc, out, _ = run(["idevice_id", "-l"], timeout=5)
        ids = out.decode().split() if rc == 0 else []
        if (ids[0] if ids else None) != self.udid:
            GLib.idle_add(self.refresh)

    def refresh(self, *_):
        if self.busy:
            return False
        self.busy = True
        self.spinner.start()
        threading.Thread(target=self._refresh_worker, daemon=True).start()
        return False

    def _refresh_worker(self):
        rc, out, _ = run(["idevice_id", "-l"], timeout=5)
        ids = out.decode().split() if rc == 0 else []
        data = read_device(ids[0]) if ids else None
        GLib.idle_add(self._show, ids[0] if ids else None, data)

    def _show(self, udid, data):
        self.busy = False
        self.spinner.stop()
        was_shown = self.stack.get_visible_child_name() == "device" and self.udid == udid
        self.udid, self.data = udid, data
        if not data or "error" in data:
            if data:
                self.empty_title.set_label("Unlock your iPhone")
                self.empty_desc.set_label("Unlock the phone and tap “Trust”. It will appear here automatically.")
            else:
                self.empty_title.set_label("Connect your iPhone")
                self.empty_desc.set_label("Plug it in with a cable, unlock it and tap “Trust” on the phone.")
            self.wtitle.set_subtitle("No iPhone connected")
            self.stack.set_visible_child_name("empty")
            return False

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
        body = (f"A full backup of about {gb(used)} will be saved to “{BACKUP_DIR}”. "
                f"You have {gb(free)} free on this PC.\n\nKeep the iPhone plugged in and unlocked until it finishes.")
        self.confirm("Back up iPhone?", body, "Start backup", self._start_backup)

    def _start_backup(self):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        try:
            self.backup_proc = subprocess.Popen(
                ["idevicebackup2", "-u", self.udid, "backup", "--full", BACKUP_DIR],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
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
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        win = self.props.active_window or Window(self)
        win.present()
        shot = os.environ.get("IPHONE_TOOLS_SHOT")  # developer aid: save a PNG of the window
        if shot:
            GLib.timeout_add(int(os.environ.get("IPHONE_TOOLS_SHOT_MS", "4500")), self._shot, win, shot)

    def _shot(self, win, path):
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
