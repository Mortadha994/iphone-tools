"""Backup browser: look inside an iPhone backup and copy any app's files (or photos, or anything) out of it."""

import os
import plistlib
import re
import shutil
import sqlite3
import tempfile

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from itools.common import BACKUP_DIR, human_size, in_thread, open_folder, toast, ui  # noqa: E402

ICON_CACHE = os.path.expanduser("~/.cache/iphone-tools/app-icons")
AREAS = {  # friendly names for system domains
    "CameraRollDomain": ("Photos & videos", "folder-pictures"),
    "HomeDomain": ("Messages, notes & settings", "user-home"),
    "MediaDomain": ("Media (recordings, attachments)", "folder-music"),
    "KeyboardDomain": ("Keyboard dictionary", "input-keyboard"),
    "WirelessDomain": ("Wi‑Fi & cellular", "network-wireless"),
    "HealthDomain": ("Health", "emblem-favorite"),
}


def backups():
    """[(path, device name, date, iOS)] of the backups in ~/iPhone Backups, newest first."""
    out = []
    try:
        names = os.listdir(BACKUP_DIR)
    except OSError:
        return out
    for n in names:
        p = os.path.join(BACKUP_DIR, n)
        if not os.path.exists(os.path.join(p, "Manifest.db")):
            continue
        try:
            info = plistlib.load(open(os.path.join(p, "Info.plist"), "rb"))
            status = plistlib.load(open(os.path.join(p, "Status.plist"), "rb"))
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
        out.append((p, info.get("Device Name", n), status.get("Date"), info.get("Product Version", "")))
    out.sort(key=lambda b: b[2] or 0, reverse=True)
    return out


class Node:
    __slots__ = ("name", "children", "size", "mtime", "file_id", "count")

    def __init__(self, name):
        self.name, self.children, self.size, self.mtime, self.file_id, self.count = name, None, 0, 0, None, 0

    @property
    def is_dir(self):
        return self.children is not None


class Backup:
    """Reads Manifest.db of an (unencrypted) backup and builds browsable 'places' (apps and areas)."""

    def __init__(self, path):
        self.path = path
        man = plistlib.load(open(os.path.join(path, "Manifest.plist"), "rb"))
        if man.get("IsEncrypted"):
            raise RuntimeError("This backup is encrypted. Turn off “Encrypt local backup” to browse it here.")
        self.info = plistlib.load(open(os.path.join(path, "Info.plist"), "rb"))
        db = sqlite3.connect(f"file:{os.path.join(path, 'Manifest.db')}?mode=ro", uri=True)
        self.domains = {}  # domain -> root Node
        for fid, domain, rel, flags, blob in db.execute("select fileID, domain, relativePath, flags, file from Files"):
            if flags not in (1, 2) or not rel:
                continue
            root = self.domains.setdefault(domain, Node(domain))
            if root.children is None:
                root.children = {}
            node = root
            parts = rel.split("/")
            for part in parts[:-1]:
                nxt = node.children.get(part)
                if nxt is None:
                    nxt = node.children[part] = Node(part)
                    nxt.children = {}
                elif nxt.children is None:
                    nxt.children = {}
                node = nxt
            leaf = node.children.get(parts[-1])
            if leaf is None:
                leaf = node.children[parts[-1]] = Node(parts[-1])
            if flags == 2:
                if leaf.children is None:
                    leaf.children = {}
            else:
                try:
                    o = plistlib.loads(blob)["$objects"][1]
                    leaf.size, leaf.mtime = o.get("Size", 0), o.get("LastModified", 0)
                except Exception:  # noqa: BLE001 - odd entry: show it without size
                    pass
                leaf.file_id = fid
        db.close()
        for root in self.domains.values():
            self._sum(root)

    def _sum(self, node):
        if node.children is None:
            node.count = 1
            return
        node.size = node.count = 0
        for c in node.children.values():
            self._sum(c)
            node.size += c.size
            node.count += c.count

    def app_names(self):
        names = {}
        for bundle, meta in (self.info.get("Applications") or {}).items():
            try:
                md = plistlib.loads(meta.get("iTunesMetadata", b""))
                names[bundle] = md.get("itemName") or md.get("bundleDisplayName") or bundle
            except Exception:  # noqa: BLE001
                names[bundle] = bundle
        return names

    def app_icon(self, bundle):
        data = ((self.info.get("Applications") or {}).get(bundle) or {}).get("PlaceholderIcon")
        cached = os.path.join(ICON_CACHE, bundle + ".png")  # saved by the Apps tool
        if not data and os.path.exists(cached):
            with open(cached, "rb") as f:
                data = f.read()
        if not data:
            return None
        try:
            return Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
        except GLib.Error:
            return None

    def places(self):
        """-> list of (key, title, icon_texture_or_name, [ (label, root Node) ]) sorted for display."""
        names = self.app_names()
        apps, used = {}, set()
        for d in self.domains:
            if d.startswith("AppDomain-"):
                b = d[len("AppDomain-"):]
                apps[b] = [("App data", self.domains[d])]
                used.add(d)
        for d in self.domains:
            if d.startswith("AppDomainPlugin-"):
                plug = d[len("AppDomainPlugin-"):]
                owner = max((b for b in apps if plug.startswith(b + ".")), key=len, default=None)
                if owner:
                    apps[owner].append((f"Extension: {plug[len(owner) + 1:]}", self.domains[d]))
                    used.add(d)
            elif d.startswith("AppDomainGroup-"):
                grp = d[len("AppDomainGroup-"):]
                bare = grp.split("group.", 1)[-1] if "group." in grp else grp
                owner = max((b for b in apps if bare.startswith(b) or b.startswith(bare)), key=len, default=None)
                if owner:
                    apps[owner].append((f"Shared: {grp}", self.domains[d]))
                    used.add(d)
        out = []
        for b, parts in apps.items():
            if b.startswith("com.apple.") and b not in names:
                continue  # Apple's own system bits go under "System"
            out.append(("app:" + b, names.get(b) or pretty_bundle(b), self.app_icon(b) or "application-x-executable",
                        parts))
        out.sort(key=lambda p: -sum(n.size for _, n in p[3]))
        areas = []
        for d, (title, icon) in AREAS.items():
            if d in self.domains:
                areas.append(("area:" + d, title, icon, [(title, self.domains[d])]))
                used.add(d)
        rest = [(d, n) for d, n in self.domains.items() if d not in used]
        system = ("area:system", "System & other apps", "preferences-system",
                  sorted(rest, key=lambda x: -x[1].size))
        return out, areas + ([system] if rest else [])

    def src(self, node):
        return os.path.join(self.path, node.file_id[:2], node.file_id)


def extract(backup, label_nodes, dest, cancel=lambda: False, progress=None):
    """Copy nodes (and everything under them) to dest, keeping names, folders and dates. -> files copied."""
    total = sum(n.size for _, n in label_nodes) or 1
    done = copied = 0

    def walk(node, out):
        nonlocal done, copied
        if cancel():
            return
        if node.is_dir:
            os.makedirs(out, exist_ok=True)
            for c in node.children.values():
                walk(c, os.path.join(out, c.name))
            return
        src = backup.src(node)
        if not os.path.exists(src):
            return
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copyfile(src, out)
        if node.mtime:
            os.utime(out, (node.mtime, node.mtime))
        copied += 1
        done += node.size
        if progress:
            progress(done / total, node.name)

    for label, node in label_nodes:
        walk(node, os.path.join(dest, safe(label)) if len(label_nodes) > 1 or node.is_dir else
             os.path.join(dest, node.name))
    return copied


def pretty_bundle(bundle):
    """'com.riotgames.league.teamfighttactics' -> 'Teamfighttactics' (when the backup has no app name)."""
    last = bundle.rsplit(".", 1)[-1]
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", last).replace("_", " ").replace("-", " ")
    return words[:1].upper() + words[1:]


def safe(name):
    """A label usable as a folder name ("Extension: Widget" -> "Extension - Widget")."""
    return name.replace(": ", " - ").replace("/", "-").replace(":", "-").strip() or "_"


class BackupsWindow(Adw.Window):
    def __init__(self, parent, udid=None):
        super().__init__(transient_for=parent, title="Backup browser", default_width=640, default_height=820)
        self.udid = udid
        self.backup = None
        self.cancel = False
        self.toasts = Adw.ToastOverlay()
        self.nav = Adw.NavigationView()
        self.toasts.set_child(self.nav)
        self.set_content(self.toasts)
        found = backups()
        if not found:
            self._message("No backups yet", "Click “Back up” in the main window first. Backups are saved in "
                                            "~/iPhone Backups.")
        elif len(found) == 1:
            self.open_backup(found[0])
        else:
            self._choose(found)

    # --- pages
    def _page(self, title, subtitle=""):
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_title_widget(Adw.WindowTitle(title=title, subtitle=subtitle))
        tv.add_top_bar(hb)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=12, margin_bottom=20,
                      margin_start=16, margin_end=16)
        clamp = Adw.Clamp(maximum_size=680)
        clamp.set_child(col)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sc.set_child(clamp)
        tv.set_content(sc)
        page = Adw.NavigationPage(title=title, child=tv)
        page.header, page.col = hb, col
        return page

    def _message(self, title, body):
        page = self._page("Backup browser")
        page.col.append(Adw.StatusPage(title=title, description=body, icon_name="drive-harddisk-symbolic"))
        self.nav.add(page)

    def _choose(self, found):
        page = self._page("Backup browser", "Choose a backup")
        g = Adw.PreferencesGroup()
        for b in found:
            r = Adw.ActionRow(title=b[1], use_markup=False, activatable=True,
                              subtitle=f"{b[2]:%-d %b %Y, %H:%M} · iOS {b[3]}" if b[2] else f"iOS {b[3]}")
            r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            r.connect("activated", lambda _r, bb=b: self.open_backup(bb))
            g.add(r)
        page.col.append(g)
        self.nav.add(page)

    def open_backup(self, b):
        page = self._page(b[1], "Reading the backup…")
        sp = Gtk.Spinner(spinning=True, width_request=32, height_request=32, margin_top=60)
        page.col.append(sp)
        self.nav.push(page) if self.nav.get_visible_page() else self.nav.add(page)

        def work():
            try:
                bk = Backup(b[0])
                ui(self._show_places, page, sp, bk, b, None)
            except Exception as e:  # noqa: BLE001 - shown to the user
                ui(self._show_places, page, sp, None, b, str(e))
        in_thread(work)

    def _show_places(self, page, sp, bk, b, err):
        page.col.remove(sp)
        if err:
            page.col.append(Adw.StatusPage(title="Couldn’t open this backup", description=err,
                                           icon_name="dialog-error-symbolic"))
            return
        self.backup = bk
        apps, areas = bk.places()
        total = sum(n.size for n in bk.domains.values())
        page.header.get_title_widget().set_subtitle(
            f"{b[2]:%-d %b %Y, %H:%M} · {human_size(total)}" if b[2] else human_size(total))
        search = Gtk.SearchEntry(placeholder_text="Search apps")
        page.col.append(search)
        g_apps = Adw.PreferencesGroup(title=f"Apps ({len(apps)})",
                                      description="Pick an app to see and copy out its files")
        rows = []
        for key, title, icon, parts in apps:
            r = self._place_row(title, icon, parts)
            rows.append((r, title.lower()))
            g_apps.add(r)
        search.connect("search-changed", lambda e: [r.set_visible(e.get_text().lower() in t) for r, t in rows])
        g_areas = Adw.PreferencesGroup(title="Everything else")
        for key, title, icon, parts in areas:
            g_areas.add(self._place_row(title, icon, parts))
        page.col.append(g_apps)
        page.col.append(g_areas)
        dev = os.environ.get("IPHONE_TOOLS_BACKUP_APP")  # developer aid
        if dev:
            hit = next((a for a in apps if dev.lower() in a[1].lower()), None)
            if hit:
                self.open_folder_page(hit[1], hit[3])
                if os.environ.get("IPHONE_TOOLS_BACKUP_DEEP"):
                    self.open_folder_page("App data", [("App data", hit[3][0][1])], f"{hit[1]} / App data")

    def _place_row(self, title, icon, parts):
        size = sum(n.size for _, n in parts)
        count = sum(n.count for _, n in parts)
        r = Adw.ActionRow(title=title, use_markup=False, activatable=True,
                          subtitle=f"{count:,} file{'s' * (count != 1)} · {human_size(size)}")
        img = Gtk.Image(pixel_size=36)
        if isinstance(icon, str):
            img.set_from_icon_name(icon)
        else:
            img.set_from_paintable(icon)
        r.add_prefix(img)
        r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        r.connect("activated", lambda *_: self.open_folder_page(title, parts))
        return r

    def open_folder_page(self, title, parts, path=""):
        """Show either several roots (an app's data + extensions + shared folders) or one folder's contents."""
        page = self._page(title, path or f"{human_size(sum(n.size for _, n in parts))}")
        ext = Gtk.Button(label="Copy out…", css_classes=["suggested-action"],
                         tooltip_text="Copy everything shown here to a folder on this PC")
        ext.connect("clicked", lambda *_: self.choose_and_extract(title, parts))
        page.header.pack_end(ext)
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        if len(parts) > 1:  # an app: its data, shared folders, extensions — biggest first, empty ones hidden
            entries = sorted(((label, node) for label, node in parts if node.count), key=lambda e: -e[1].size)
        else:
            node = parts[0][1]
            kids = sorted(node.children.values(), key=lambda n: (not n.is_dir, n.name.lower())) if node.is_dir \
                else [node]
            entries = [(n.name, n) for n in kids]
        if not entries:
            page.col.append(Gtk.Label(label="This folder is empty", css_classes=["dim-label"], margin_top=40))
        for label, n in entries:
            sub = (f"{n.count:,} file{'s' * (n.count != 1)} · " if n.is_dir else "") + human_size(n.size)
            r = Adw.ActionRow(title=label, subtitle=sub, use_markup=False, activatable=True)
            r.add_prefix(Gtk.Image(icon_name="folder" if n.is_dir else icon_for(label), pixel_size=28))
            if n.is_dir:
                r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                r.connect("activated", lambda _r, lb_=label, nn=n: self.open_folder_page(
                    lb_, [(lb_, nn)], f"{title} / {lb_}" if not path else f"{path} / {lb_}"))
            else:
                save = Gtk.Button(icon_name="document-save-symbolic", css_classes=["flat"], valign=Gtk.Align.CENTER,
                                  tooltip_text="Copy this file out")
                save.connect("clicked", lambda _b, lb_=label, nn=n: self.choose_and_extract(lb_, [(lb_, nn)]))
                r.add_suffix(save)
                r.connect("activated", lambda _r, nn=n: self.open_file(nn))
            lb.append(r)
        if entries:
            page.col.append(lb)
        self.nav.push(page)

    def open_file(self, node):
        src = self.backup.src(node)
        if not os.path.exists(src):
            toast(self, "This file isn’t in the backup")
            return
        d = tempfile.mkdtemp(prefix="iphone-tools-")
        out = os.path.join(d, node.name)
        shutil.copyfile(src, out)
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(out).get_uri(), None)

    def choose_and_extract(self, title, parts):
        dlg = Gtk.FileDialog(title=f"Copy “{title}” to…")
        dlg.set_initial_folder(Gio.File.new_for_path(os.path.expanduser("~")))

        def done(d, res):
            try:
                folder = d.select_folder_finish(res).get_path()
            except GLib.Error:
                return
            dest = os.path.join(folder, safe(title)) if len(parts) > 1 or parts[0][1].is_dir else folder
            self._extract(title, parts, dest)
        dlg.select_folder(self, None, done)

    def _extract(self, title, parts, dest):
        self.cancel = False
        dlg = Adw.MessageDialog(transient_for=self, heading=f"Copying “{title}”…", body="")
        bar = Gtk.ProgressBar(show_text=True)
        dlg.set_extra_child(bar)
        dlg.add_response("cancel", "Cancel")
        dlg.connect("response", lambda *_: setattr(self, "cancel", True))
        dlg.present()

        def prog(frac, name):
            ui(lambda: (bar.set_fraction(frac), bar.set_text(name)))

        def work():
            try:
                n = extract(self.backup, parts, dest, cancel=lambda: self.cancel, progress=prog)
                ui(self._extracted, dlg, dest, n, None)
            except OSError as e:
                ui(self._extracted, dlg, dest, 0, str(e))
        in_thread(work)

    def _extracted(self, dlg, dest, n, err):
        if self.cancel:
            toast(self, f"Stopped after {n} files")
            return
        dlg.close()
        if err:
            toast(self, f"Copy failed: {err[:90]}")
            return
        toast(self, f"✔ Copied {n:,} file{'s' * (n != 1)}")
        open_folder(dest if os.path.isdir(dest) else os.path.dirname(dest))


def icon_for(name):
    ext = os.path.splitext(name)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".heic", ".gif", ".webp"):
        return "image-x-generic"
    if ext in (".mov", ".mp4", ".m4v"):
        return "video-x-generic"
    if ext in (".mp3", ".m4a", ".aac", ".wav", ".caf", ".amr", ".opus"):
        return "audio-x-generic"
    if ext in (".sqlite", ".sqlitedb", ".db", ".storedata"):
        return "x-office-spreadsheet"
    if ext in (".plist", ".json", ".xml", ".txt", ".log"):
        return "text-x-generic"
    if ext == ".pdf":
        return "application-pdf"
    return "text-x-generic" if not ext else "application-octet-stream"
