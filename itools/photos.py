"""Photo import: copy the iPhone's Camera Roll to the PC, one folder per month, skipping what's already there."""

import glob
import json
import os
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, GdkPixbuf, Gio, Gtk  # noqa: E402

from itools.common import (  # noqa: E402
    MediaMount, human_size, in_thread, open_folder, progress_card, show_card, themed, toast, ui, window_shell)

PHOTOS_DIR = os.path.expanduser("~/Pictures/iPhone")
MANIFEST = ".iphone-tools-imported.json"   # remembers what was imported, so moved/deleted photos aren't re-copied
PHOTO_EXT = {".heic", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".dng", ".tif", ".tiff"}
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".hevc"}
CHUNK = 1 << 20


def heic_supported():
    """True if libheif can decode HEVC (package libheif-plugin-libde265), so HEIC -> JPG works."""
    return bool(glob.glob("/usr/lib/*/libheif/plugins/*de265*") or glob.glob("/usr/lib/*/libheif/plugins/*ffmpeg*"))


def scan(root):
    """Camera Roll items on the phone: [(rel_path, size, mtime)] oldest first. .AAE edit sidecars are skipped."""
    items = []
    for d in sorted(glob.glob(os.path.join(root, "DCIM", "*"))):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            ext = os.path.splitext(n)[1].lower()
            if ext not in PHOTO_EXT and ext not in VIDEO_EXT:
                continue
            p = os.path.join(d, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            items.append((os.path.relpath(p, root), st.st_size, st.st_mtime))
    items.sort(key=lambda i: i[2])
    return items


def load_manifest(dest):
    try:
        with open(os.path.join(dest, MANIFEST)) as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_manifest(dest, done):
    tmp = os.path.join(dest, MANIFEST + ".tmp")
    with open(tmp, "w") as f:
        json.dump(sorted(done), f)
    os.replace(tmp, os.path.join(dest, MANIFEST))


def key(rel, size):
    # Folder + name + size: names repeat once IMG_9999 wraps, and an edited photo keeps its name but changes size.
    return f"{rel}:{size}"


def free_name(path):
    """path, or 'name (2).ext', 'name (3).ext', … if a different file already uses that name."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


class PhotoImportWindow(Adw.Window):
    def __init__(self, parent, udid):
        super().__init__(transient_for=parent)
        self.udid = udid
        self.items, self.new, self.busy, self.cancel = [], [], False, False
        self.dest = PHOTOS_DIR
        col = window_shell(self, "Import photos", "From your iPhone to this PC")

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["dropzone"])
        hero.append(Gtk.Image(gicon=themed("folder-pictures"), pixel_size=72, css_classes=["float-icon"]))
        self.count_lbl = Gtk.Label(label="Looking at your Camera Roll…", css_classes=["big"], wrap=True,
                                   justify=Gtk.Justification.CENTER)
        self.detail_lbl = Gtk.Label(css_classes=["caption", "dim-label"], wrap=True, justify=Gtk.Justification.CENTER)
        hero.append(self.count_lbl)
        hero.append(self.detail_lbl)
        btns = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER, margin_top=6)
        self.go_btn = Gtk.Button(label="Import", css_classes=["pill", "suggested-action"], sensitive=False)
        self.go_btn.connect("clicked", self.start)
        self.open_btn = Gtk.Button(label="Open folder", css_classes=["pill"])
        self.open_btn.connect("clicked", lambda *_: open_folder(self.dest))
        btns.append(self.go_btn)
        btns.append(self.open_btn)
        hero.append(btns)
        col.append(hero)

        self.prog_rev, self.p_title, self.p_line, self.p_bar = progress_card(
            "folder-pictures", lambda: setattr(self, "cancel", True))
        col.append(self.prog_rev)

        opts = Adw.PreferencesGroup(title="Options")
        self.dest_row = Adw.ActionRow(title="Save to", subtitle=self._pretty(self.dest), use_markup=False)
        pick = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                          tooltip_text="Choose another folder")
        pick.connect("clicked", self.choose_dest)
        self.dest_row.add_suffix(pick)
        opts.add(self.dest_row)
        self.videos_sw = Adw.SwitchRow(title="Include videos", active=True)
        self.videos_sw.connect("notify::active", lambda *_: self._recount())
        opts.add(self.videos_sw)
        ok = heic_supported()
        self.jpg_sw = Adw.SwitchRow(
            title="Convert HEIC photos to JPG", active=False, sensitive=ok,
            subtitle="JPG opens everywhere; HEIC keeps the best quality" if ok else
            "Needs the HEIC decoder: sudo apt install libheif-plugin-libde265")
        opts.add(self.jpg_sw)
        col.append(opts)
        col.append(Gtk.Label(wrap=True, xalign=0, css_classes=["caption", "dim-label"], label=(
            "Photos go into one folder per month (e.g. 2026-11). Photos you already imported are skipped, even if "
            "you moved or deleted them here since. Nothing is removed from the iPhone.")))

        self.spinner.start()
        in_thread(self._scan_worker)

    @staticmethod
    def _pretty(path):
        home = os.path.expanduser("~")
        return "~" + path[len(home):] if path.startswith(home) else path

    # --- scanning
    def _scan_worker(self):
        try:
            with MediaMount(self.udid) as root:
                items = scan(root)
            ui(self._scanned, items, None)
        except Exception as e:  # noqa: BLE001 - shown to the user
            ui(self._scanned, [], str(e))

    def _scanned(self, items, err):
        self.spinner.stop()
        if err:
            self.count_lbl.set_label("Couldn’t open the Camera Roll")
            self.detail_lbl.set_label(err)
            return
        self.items = items
        self._recount()

    def _recount(self):
        if self.busy:
            return
        done = load_manifest(self.dest)
        vids = self.videos_sw.get_active()
        wanted = [i for i in self.items if vids or os.path.splitext(i[0])[1].lower() not in VIDEO_EXT]
        self.new = [i for i in wanted if key(i[0], i[1]) not in done]
        photos = sum(1 for i in self.items if os.path.splitext(i[0])[1].lower() in PHOTO_EXT)
        videos = len(self.items) - photos
        if not self.items:
            self.count_lbl.set_label("No photos on this iPhone")
            self.detail_lbl.set_label("")
        elif self.new:
            self.count_lbl.set_label(f"{len(self.new)} new to import")
            self.detail_lbl.set_label(f"{human_size(sum(i[1] for i in self.new))} · on the iPhone: "
                                      f"{photos} photos, {videos} videos")
        else:
            self.count_lbl.set_label("Everything is already imported ✔")
            self.detail_lbl.set_label(f"On the iPhone: {photos} photos, {videos} videos")
        self.go_btn.set_sensitive(bool(self.new))

    def choose_dest(self, *_):
        d = Gtk.FileDialog(title="Save photos to")
        os.makedirs(self.dest, exist_ok=True)
        d.set_initial_folder(Gio.File.new_for_path(self.dest))

        def done(dlg, res):
            try:
                f = dlg.select_folder_finish(res)
            except Exception:  # noqa: BLE001 - cancelled
                return
            self.dest = f.get_path()
            self.dest_row.set_subtitle(self._pretty(self.dest))
            self._recount()
        d.select_folder(self, None, done)

    # --- import
    def start(self, *_):
        self.busy, self.cancel = True, False
        for w in (self.go_btn, self.videos_sw, self.jpg_sw, self.dest_row):
            w.set_sensitive(False)
        self.p_title.set_label("Importing…")
        self.p_line.set_label("")
        self.p_bar.set_fraction(0)
        show_card(self.prog_rev, True)
        self.spinner.start()
        in_thread(self._import_worker, list(self.new), self.dest, self.jpg_sw.get_active())

    def _import_worker(self, items, dest, to_jpg):
        total = sum(i[1] for i in items) or 1
        copied = done_bytes = 0
        err = None
        os.makedirs(dest, exist_ok=True)
        imported = load_manifest(dest)
        last_ui = 0
        try:
            with MediaMount(self.udid) as root:
                for n, (rel, size, mtime) in enumerate(items):
                    if self.cancel:
                        break
                    month = time.strftime("%Y-%m", time.localtime(mtime))
                    name = os.path.basename(rel)
                    out_dir = os.path.join(dest, month)
                    os.makedirs(out_dir, exist_ok=True)
                    src = os.path.join(root, rel)
                    heic = to_jpg and name.lower().endswith(".heic")
                    target = free_name(os.path.join(out_dir, os.path.splitext(name)[0] + ".jpg" if heic else name))
                    part = target + ".part"
                    if heic:
                        pb = GdkPixbuf.Pixbuf.new_from_file(src).apply_embedded_orientation()
                        pb.savev(part, "jpeg", ["quality"], ["92"])
                        done_bytes += size
                    else:
                        with open(src, "rb") as fi, open(part, "wb") as fo:
                            while chunk := fi.read(CHUNK):
                                if self.cancel:
                                    break
                                fo.write(chunk)
                                done_bytes += len(chunk)
                                if time.time() - last_ui > 0.2:
                                    last_ui = time.time()
                                    ui(self._progress, done_bytes / total, n, len(items), name)
                        if self.cancel:
                            os.unlink(part)
                            break
                    os.utime(part, (mtime, mtime))   # keep the date the photo was taken
                    os.replace(part, target)
                    imported.add(key(rel, size))
                    copied += 1
                    if copied % 25 == 0:
                        save_manifest(dest, imported)
                    ui(self._progress, done_bytes / total, n + 1, len(items), name)
        except Exception as e:  # noqa: BLE001 - shown to the user
            err = str(e)
        finally:
            if copied:
                save_manifest(dest, imported)
        ui(self._done, copied, len(items), err)

    def _progress(self, frac, n, total, name):
        self.p_bar.set_fraction(frac)
        self.p_title.set_label(f"Importing {n} of {total}…")
        self.p_line.set_label(name)

    def _done(self, copied, total, err):
        self.busy = False
        self.spinner.stop()
        show_card(self.prog_rev, False)
        for w in (self.videos_sw, self.dest_row):
            w.set_sensitive(True)
        self.jpg_sw.set_sensitive(heic_supported())
        if err:
            toast(self, f"Import stopped: {err[:90]}")
        elif self.cancel:
            toast(self, f"Stopped — {copied} of {total} imported")
        else:
            toast(self, f"✔ {copied} imported to {self._pretty(self.dest)}")
        self._recount()

