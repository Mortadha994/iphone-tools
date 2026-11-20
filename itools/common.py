"""Helpers shared by every iPhone Tools window."""

import os
import shutil
import threading
import time
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # folder holding iphone_tools.py

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
        local = os.path.join(APP_DIR, "data", "iphone-tools.svg")
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


def run(args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr.decode(errors="replace")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, b"", str(e)


def gb(n):
    return f"{int(n) / 1e9:.1f} GB"


def stagger_reveal(revealers, step_ms=110):
    for i, r in enumerate(revealers):
        r.set_reveal_child(False)
        GLib.timeout_add(60 + i * step_ms, lambda rv=r: (rv.set_reveal_child(True), False)[1])


def revealer(child):
    r = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=420)
    r.set_child(child)
    return r


class MediaMount:
    """`with MediaMount(udid) as path:` mounts the iPhone's media area (DCIM, …) with ifuse."""

    def __init__(self, udid, name="media"):
        self.udid, self.path = udid, os.path.expanduser(f"~/.cache/iphone-tools/{name}")

    def __enter__(self):
        os.makedirs(self.path, exist_ok=True)
        subprocess.run(["fusermount", "-uz", self.path], capture_output=True)  # clear a stale mount
        rc, _, err = run(["ifuse", "-u", self.udid, self.path], timeout=30)
        if rc != 0:
            raise RuntimeError(err.strip() or "Could not open the iPhone. Unlock it and try again.")
        return self.path

    def __exit__(self, *exc):
        for _ in range(5):
            if subprocess.run(["fusermount", "-u", self.path], capture_output=True).returncode == 0:
                break
            time.sleep(0.4)
        else:
            subprocess.run(["fusermount", "-uz", self.path], capture_output=True)
        return False


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1000


def window_shell(win, title, subtitle, width=560, height=760):
    """Standard layout for a tool window: header bar with spinner, scrolling clamped column, toasts.
    Sets win.toasts, win.spinner, win.header, win.col, win.scroller; returns the column box."""
    win.set_default_size(width, height)
    win.set_title(title)
    win.toasts = Adw.ToastOverlay()
    view = Adw.ToolbarView()
    win.header = Adw.HeaderBar()
    win.wtitle = Adw.WindowTitle(title=title, subtitle=subtitle)
    win.header.set_title_widget(win.wtitle)
    win.spinner = Gtk.Spinner()
    win.header.pack_start(win.spinner)
    view.add_top_bar(win.header)
    clamp = Adw.Clamp(maximum_size=width + 40)
    win.col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                      margin_top=14, margin_bottom=24, margin_start=16, margin_end=16)
    clamp.set_child(win.col)
    win.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    win.scroller.set_child(clamp)
    view.set_content(win.scroller)
    win.toasts.set_child(view)
    win.set_content(win.toasts)
    return win.col


def toast(win, msg, timeout=4):
    win.toasts.add_toast(Adw.Toast(title=msg, timeout=timeout))


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)


def in_thread(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def ui(fn, *args):
    """Run fn(*args) on the GTK main loop (from a worker thread)."""
    GLib.idle_add(lambda: (fn(*args), False)[1])


def progress_card(icon, on_cancel, label="Cancel"):
    """A card with icon, title, detail line, progress bar and a cancel button, inside a hidden revealer.
    -> (revealer, title_label, line_label, progressbar)"""
    cc = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["copy-card"])
    top = Gtk.Box(spacing=10)
    top.append(Gtk.Image(gicon=themed(icon), pixel_size=30, css_classes=["note-bounce"]))
    t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
    title = Gtk.Label(xalign=0, css_classes=["section-title"])
    line = Gtk.Label(xalign=0, css_classes=["caption", "dim-label"], ellipsize=3)  # 3 = Pango.EllipsizeMode.END
    t.append(title)
    t.append(line)
    top.append(t)
    stop = Gtk.Button(label=label, valign=Gtk.Align.CENTER, css_classes=["pill"])
    stop.connect("clicked", lambda *_: on_cancel())
    top.append(stop)
    cc.append(top)
    bar = Gtk.ProgressBar()
    cc.append(bar)
    rev = revealer(cc)
    rev.set_visible(False)
    return rev, title, line, bar


def show_card(rev, shown):
    if shown:
        rev.set_visible(True)
        rev.set_reveal_child(True)
    else:
        rev.set_reveal_child(False)
        GLib.timeout_add(450, lambda: (rev.set_visible(False), False)[1])


def pmd3():
    """Path of the pymobiledevice3 command, or None if it isn't installed."""
    p = shutil.which("pymobiledevice3") or os.path.expanduser("~/.local/bin/pymobiledevice3")
    return p if os.path.exists(p) else None
