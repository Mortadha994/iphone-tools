"""App manager: every app you installed, biggest first, with uninstall."""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from itools.common import helper, human_size, in_thread, toast, ui, window_shell  # noqa: E402

ICON_CACHE = os.path.expanduser("~/.cache/iphone-tools/app-icons")


def app_name(a):
    return a.get("CFBundleDisplayName") or a.get("CFBundleName") or a["CFBundleIdentifier"]


def total(a):
    return (a.get("StaticDiskUsage") or 0) + (a.get("DynamicDiskUsage") or 0)


class AppsWindow(Adw.Window):
    def __init__(self, parent, udid):
        super().__init__(transient_for=parent)
        self.udid = udid
        self.apps, self.rows, self.sizes_known = {}, {}, False
        col = window_shell(self, "Apps", "Loading…", width=600, height=800)

        bar = Gtk.Box(spacing=10)
        self.search = Gtk.SearchEntry(placeholder_text="Search apps", hexpand=True)
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        bar.append(self.search)
        self.sort = Gtk.DropDown(model=Gtk.StringList.new(["Biggest first", "Name"]), valign=Gtk.Align.CENTER)
        self.sort.connect("notify::selected", lambda *_: self.listbox.invalidate_sort())
        bar.append(self.sort)
        col.append(bar)

        self.sizes_lbl = Gtk.Label(xalign=0, css_classes=["caption", "dim-label"],
                                   label="Adding up app sizes on the iPhone… (can take a minute or two)")
        self.sizes_box = Gtk.Box(spacing=8)
        self.sizes_spin = Gtk.Spinner(spinning=True)
        self.sizes_box.append(self.sizes_spin)
        self.sizes_box.append(self.sizes_lbl)
        col.append(self.sizes_box)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.listbox.set_filter_func(self._filter)
        self.listbox.set_sort_func(self._sort)
        self.listbox.set_placeholder(Gtk.Label(label="Loading apps…", margin_top=30, margin_bottom=30,
                                               css_classes=["dim-label"]))
        col.append(self.listbox)
        col.append(Gtk.Label(wrap=True, xalign=0, css_classes=["caption", "dim-label"], label=(
            "“App” is the app itself; “data” is what it stores (cache, downloads, accounts). Deleting an app "
            "here removes it and its data from the iPhone, like holding its icon and choosing Delete App.")))

        self.spinner.start()
        in_thread(self._load)

    # --- loading
    def _load(self):
        try:
            apps = helper(self.udid, "apps")
        except RuntimeError as e:
            ui(self._failed, str(e))
            return
        ui(self._show_apps, apps)
        missing = [a["CFBundleIdentifier"] for a in apps
                   if not os.path.exists(os.path.join(ICON_CACHE, a["CFBundleIdentifier"] + ".png"))]
        if missing:
            try:
                helper(self.udid, "icons", ICON_CACHE, *missing,
                       on_line=lambda o: "error" not in o and ui(self._set_icon, o["bundle"]))
            except RuntimeError:
                pass  # icons are nice-to-have
        try:
            sized = helper(self.udid, "apps", "--sizes")
        except RuntimeError as e:
            ui(self._sizes_failed, str(e))
            return
        ui(self._show_sizes, sized)

    def _failed(self, err):
        self.spinner.stop()
        self.wtitle.set_subtitle("Couldn’t read the apps")
        self.sizes_box.set_visible(False)
        self.listbox.set_placeholder(Gtk.Label(label=err, wrap=True, margin_top=30, margin_bottom=30,
                                               margin_start=20, margin_end=20, css_classes=["dim-label"]))

    def _show_apps(self, apps):
        self.spinner.stop()
        for a in apps:
            if a.get("IsAppClip"):
                continue
            b = a["CFBundleIdentifier"]
            self.apps[b] = a
            row = Adw.ActionRow(title=app_name(a), use_markup=False,
                                subtitle=f"Version {a.get('CFBundleShortVersionString') or '?'}")
            row.bundle = b
            icon = Gtk.Image(pixel_size=44, css_classes=["app-icon"])
            row.icon = icon
            row.add_prefix(icon)
            self._set_icon(b, row)
            row.size_lbl = Gtk.Label(css_classes=["legend-value"], valign=Gtk.Align.CENTER)
            row.add_suffix(row.size_lbl)
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                            css_classes=["flat", "circular"], tooltip_text=f"Delete {app_name(a)} from the iPhone")
            rm.connect("clicked", lambda _b, bid=b: self._confirm(bid))
            row.add_suffix(rm)
            self.rows[b] = row
            self.listbox.append(row)
        self._update_title()

    def _set_icon(self, bundle, row=None):
        row = row or self.rows.get(bundle)
        path = os.path.join(ICON_CACHE, bundle + ".png")
        if row is None:
            return
        if os.path.exists(path):
            row.icon.set_from_gicon(Gio.FileIcon.new(Gio.File.new_for_path(path)))
        else:
            row.icon.set_from_icon_name("application-x-executable")

    def _show_sizes(self, sized):
        self.sizes_known = True
        self.sizes_box.set_visible(False)
        for a in sized:
            b = a["CFBundleIdentifier"]
            if b in self.apps:
                self.apps[b].update(a)
                row = self.rows[b]
                row.size_lbl.set_label(human_size(total(a)))
                row.set_subtitle(f"Version {a.get('CFBundleShortVersionString') or '?'} · "
                                 f"app {human_size(a.get('StaticDiskUsage') or 0)} · "
                                 f"data {human_size(a.get('DynamicDiskUsage') or 0)}")
        self.listbox.invalidate_sort()
        self._update_title()

    def _sizes_failed(self, err):
        self.sizes_spin.set_spinning(False)
        self.sizes_lbl.set_label(f"Couldn’t get app sizes: {err[:80]}")

    def _update_title(self):
        n = len(self.apps)
        sub = f"{n} app{'s' * (n != 1)}"
        if self.sizes_known:
            sub += f" · {human_size(sum(total(a) for a in self.apps.values()))}"
        self.wtitle.set_subtitle(sub)

    # --- list helpers
    def _filter(self, row):
        q = self.search.get_text().strip().lower()
        a = self.apps.get(getattr(row, "bundle", None))
        return not q or (a is not None and (q in app_name(a).lower() or q in a["CFBundleIdentifier"].lower()))

    def _sort(self, r1, r2):
        a1, a2 = self.apps[r1.bundle], self.apps[r2.bundle]
        if self.sort.get_selected() == 0 and self.sizes_known:
            d = total(a2) - total(a1)
            if d:
                return 1 if d > 0 else -1
        n1, n2 = app_name(a1).lower(), app_name(a2).lower()
        return (n1 > n2) - (n1 < n2)

    # --- uninstall
    def _confirm(self, bundle):
        a = self.apps[bundle]
        size = f" and frees {human_size(total(a))}" if self.sizes_known else ""
        d = Adw.MessageDialog(transient_for=self, heading=f"Delete “{app_name(a)}”?",
                              body=f"The app and all its data are removed from the iPhone{size}. You can "
                                   "reinstall it from the App Store, but data that isn’t in iCloud is lost.")
        d.add_response("cancel", "Cancel")
        d.add_response("delete", "Delete app")
        d.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _d, r: r == "delete" and self._uninstall(bundle))
        d.present()

    def _uninstall(self, bundle):
        row = self.rows[bundle]
        row.set_sensitive(False)
        row.size_lbl.set_label("Deleting…")
        self.spinner.start()

        def work():
            try:
                helper(self.udid, "uninstall", bundle)
                # iOS answers "done" even when it didn't remove anything, so check the app is really gone
                still = any(a["CFBundleIdentifier"] == bundle for a in helper(self.udid, "apps"))
                ui(self._uninstalled, bundle, "the iPhone kept it (is it restricted by Screen Time?)" if still else None)
            except RuntimeError as e:
                ui(self._uninstalled, bundle, str(e))
        in_thread(work)

    def _uninstalled(self, bundle, err):
        self.spinner.stop()
        row = self.rows[bundle]
        name = app_name(self.apps[bundle])
        if err:
            row.set_sensitive(True)
            row.size_lbl.set_label(human_size(total(self.apps[bundle])) if self.sizes_known else "")
            toast(self, f"Couldn’t delete {name}: {err[:80]}")
            return
        self.listbox.remove(row)
        del self.rows[bundle], self.apps[bundle]
        self._update_title()
        toast(self, f"✔ {name} deleted")

