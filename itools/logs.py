"""Crash reports (what crashed, when, why — in plain words) and the iPhone's live system log."""

import datetime
import json
import os
import re
import shutil
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from itools.common import in_thread, open_folder, run, toast, ui  # noqa: E402

CACHE = os.path.expanduser("~/.cache/iphone-tools/crash-reports")
SAVE_DIR = os.path.expanduser("~/iPhone Crash Reports")
MAX_LOG_LINES = 4000
DATE_RE = re.compile(r"-(\d{4}-\d{2}-\d{2}-\d{6})")

# file-name kinds -> (plain title, is it a problem the user may care about?)
KINDS = [
    (".diskwrites_resource", "wrote too much to storage", False),
    (".cpu_resource", "used too much CPU", False),
    (".wakeups_resource", "woke the phone too often", False),
    ("JetsamEvent", "Low memory: iOS closed apps", True),
    ("LowBatteryLog", "Battery ran very low", True),
    ("ExcUserFault_", "error report", False),
    ("OTAUpdate", "iOS update log", False),
    ("WiFiLQMMetrics", "Wi‑Fi diagnostics", False),
    ("stacks", "System snapshot", False),
]


def classify(name, head, body):
    """-> (title, detail, problem: bool, severity: 'crash'|'warn'|'info')"""
    app = head.get("app_name") or head.get("name") or re.split(r"[-.]", name, 1)[0]
    bug = str(head.get("bug_type", ""))
    if bug == "309":  # a real app crash
        exc = (body.get("exception") or {})
        why = " · ".join(x for x in (exc.get("type"), exc.get("signal")) if x)
        term = (body.get("termination") or {}).get("indicator")
        detail = why or term or "crashed"
        if term and why and term not in why:
            detail = f"{why} · {term}"
        return f"{app} crashed", detail, True, "crash"
    for marker, title, problem in KINDS:
        if marker in name:
            if marker.startswith("."):
                proc = name.split(marker)[0]
                return f"{proc} {title}", "The app was flagged, not closed", problem, "warn"
            if marker == "ExcUserFault_":
                return f"{name.split('_', 1)[1].split('-')[0]} {title}", "The app hit an error and recovered", \
                    problem, "warn"
            return title, "", problem, "warn" if problem else "info"
    if bug in ("298", "409"):
        return f"{app} froze", "The app stopped responding", True, "crash"
    return app, f"Report type {bug}" if bug else "", False, "info"


def parse(path):
    """Read an .ips file's JSON header (first line) and, if present, its JSON body."""
    head, body = {}, {}
    try:
        with open(path, errors="replace") as f:
            first = f.readline()
            rest = f.read(400_000)
        head = json.loads(first)
        if rest.lstrip().startswith("{"):
            try:
                body = json.loads(rest)
            except ValueError:
                pass
    except (OSError, ValueError):
        pass
    return head, body


def when(name, head):
    ts = head.get("timestamp", "")
    try:
        return datetime.datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        m = DATE_RE.search(name)
        if m:
            return datetime.datetime.strptime(m.group(1), "%Y-%m-%d-%H%M%S")
    return None


def load_reports(folder):
    out = []
    for n in os.listdir(folder):
        p = os.path.join(folder, n)
        if not os.path.isfile(p) or not n.endswith((".ips", ".crash", ".synced")):
            continue
        head, body = parse(p)
        title, detail, problem, sev = classify(n, head, body)
        out.append({"path": p, "name": n, "title": title, "detail": detail, "problem": problem, "sev": sev,
                    "when": when(n, head)})
    out.sort(key=lambda r: r["when"] or datetime.datetime.min, reverse=True)
    return out


class LogsWindow(Adw.Window):
    def __init__(self, parent, udid):
        super().__init__(transient_for=parent, title="Crash reports & logs", default_width=660, default_height=820)
        self.udid = udid
        self.reports = []
        self.log_proc = None
        self.pending, self.lock = [], threading.Lock()
        self.paused = False

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        self.spinner = Gtk.Spinner()
        header.pack_start(self.spinner)
        view.add_top_bar(header)
        self.stack.add_titled_with_icon(self._build_reports(), "reports", "Crash reports", "dialog-warning-symbolic")
        self.stack.add_titled_with_icon(self._build_live(), "live", "Live log", "utilities-terminal-symbolic")
        self.stack.connect("notify::visible-child-name", self._page_changed)
        view.set_content(self.stack)
        self.toasts.set_child(view)
        self.set_content(self.toasts)
        self.connect("close-request", self._on_close)
        self.refresh()
        if os.environ.get("IPHONE_TOOLS_LOGS_PAGE"):  # developer aid
            self.stack.set_visible_child_name(os.environ["IPHONE_TOOLS_LOGS_PAGE"])

    # ------------------------------------------------------------------ crash reports
    def _build_reports(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=10, margin_top=12, margin_start=16, margin_end=16, margin_bottom=6)
        self.summary = Gtk.Label(xalign=0, hexpand=True, wrap=True, css_classes=["section-title"],
                                 label="Copying reports from the iPhone…")
        bar.append(self.summary)
        self.only_problems = Gtk.CheckButton(label="Only crashes & important", active=True,
                                             valign=Gtk.Align.CENTER,
                                             tooltip_text="Untick to also see warnings and iOS’s own diagnostics")
        self.only_problems.connect("toggled", lambda *_: self.list.invalidate_filter())
        bar.append(self.only_problems)
        save = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Save all reports to a folder",
                          css_classes=["flat"], valign=Gtk.Align.CENTER)
        save.connect("clicked", self.save_all)
        bar.append(save)
        box.append(bar)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"],
                                margin_start=16, margin_end=16, margin_bottom=16, margin_top=6)
        self.list.set_filter_func(lambda r: not self.only_problems.get_active() or r.report["problem"])
        self.list.set_placeholder(Gtk.Label(label="Nothing here", margin_top=30, margin_bottom=30,
                                            css_classes=["dim-label"]))
        clamp = Adw.Clamp(maximum_size=700)
        clamp.set_child(self.list)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sc.set_child(clamp)
        box.append(sc)
        return box

    def refresh(self):
        self.spinner.start()
        in_thread(self._copy_worker)

    def _copy_worker(self):
        dest = os.path.join(CACHE, self.udid)
        os.makedirs(dest, exist_ok=True)
        # -k keeps the reports on the iPhone (so Settings → Privacy → Analytics still shows them)
        rc, _, err = run(["idevicecrashreport", "-u", self.udid, "-k", "-e", dest], timeout=180)
        reports = load_reports(dest)
        ui(self._show_reports, reports, None if rc == 0 else (err.strip() or "Couldn’t copy the reports"))

    def _show_reports(self, reports, err):
        self.spinner.stop()
        self.reports = reports
        while (r := self.list.get_row_at_index(0)) is not None:
            self.list.remove(r)
        for rep in reports:
            row = Adw.ActionRow(title=rep["title"], use_markup=False, activatable=True,
                                subtitle=" · ".join(x for x in (
                                    rep["when"].strftime("%-d %b %Y, %H:%M") if rep["when"] else "", rep["detail"])
                                    if x))
            row.report = rep
            dot = Gtk.Label(label="●", css_classes=[f"sev-{rep['sev']}"], valign=Gtk.Align.CENTER)
            row.add_prefix(dot)
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.connect("activated", lambda r: self.open_report(r.report))
            self.list.append(row)
        month_ago = datetime.datetime.now() - datetime.timedelta(days=30)
        crashes = [r for r in reports if r["sev"] == "crash" and r["when"] and r["when"] > month_ago]
        if err and not reports:
            self.summary.set_label(f"Couldn’t read crash reports: {err[:100]}")
        elif crashes:
            apps = {}
            for c in crashes:
                apps[c["title"]] = apps.get(c["title"], 0) + 1
            worst = max(apps, key=apps.get)
            self.summary.set_label(f"{len(crashes)} crash{'es' * (len(crashes) != 1)} in the last 30 days · "
                                   f"most: {worst.replace(' crashed', '')} ({apps[worst]}×)")
        else:
            self.summary.set_label("No app crashes in the last 30 days ✔")

    def open_report(self, rep):
        try:
            with open(rep["path"], errors="replace") as f:
                text = f.read(2_000_000)
        except OSError as e:
            toast(self, str(e))
            return
        win = Adw.Window(transient_for=self, modal=True, title=rep["title"], default_width=720, default_height=760)
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.set_title_widget(Adw.WindowTitle(title=rep["title"], subtitle=rep["name"]))
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy")
        copy.connect("clicked", lambda *_: (Gdk.Display.get_default().get_clipboard().set(text),
                                            toast(self, "Report copied")))
        hb.pack_end(copy)
        tv.add_top_bar(hb)
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            top_margin=10, bottom_margin=10, left_margin=12, right_margin=12)
        view.get_buffer().set_text(text)
        sc = Gtk.ScrolledWindow(vexpand=True)
        sc.set_child(view)
        tv.set_content(sc)
        win.set_content(tv)
        win.present()

    def save_all(self, *_):
        src = os.path.join(CACHE, self.udid)
        dest = os.path.join(SAVE_DIR, datetime.date.today().isoformat())
        try:
            shutil.copytree(src, dest, dirs_exist_ok=True)
        except OSError as e:
            toast(self, f"Couldn’t save: {e}")
            return
        open_folder(dest)
        toast(self, f"Saved to ~/{os.path.relpath(dest, os.path.expanduser('~'))}")

    # ------------------------------------------------------------------ live log
    def _build_live(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=8, margin_top=12, margin_start=16, margin_end=16, margin_bottom=8)
        self.filter = Gtk.SearchEntry(placeholder_text="Filter (app name or text)", hexpand=True)
        bar.append(self.filter)
        self.quiet = Gtk.CheckButton(label="Hide noisy system parts", active=True, valign=Gtk.Align.CENTER)
        self.quiet.connect("toggled", lambda *_: self._restart_log())
        bar.append(self.quiet)
        self.pause_btn = Gtk.Button(icon_name="media-playback-pause-symbolic", tooltip_text="Pause",
                                    valign=Gtk.Align.CENTER)
        self.pause_btn.connect("clicked", self.toggle_pause)
        bar.append(self.pause_btn)
        clear = Gtk.Button(icon_name="edit-clear-all-symbolic", tooltip_text="Clear", valign=Gtk.Align.CENTER)
        clear.connect("clicked", lambda *_: self.buf.set_text(""))
        bar.append(clear)
        save = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Save log to a file",
                          valign=Gtk.Align.CENTER)
        save.connect("clicked", self.save_log)
        bar.append(save)
        box.append(bar)
        self.view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=10, right_margin=10,
                                 top_margin=6, bottom_margin=6, css_classes=["log-view"])
        self.buf = self.view.get_buffer()
        self.tag_err = self.buf.create_tag("err", foreground="#FF6961")
        self.tag_warn = self.buf.create_tag("warn", foreground="#FFB340")
        self.tag_dim = self.buf.create_tag("dim", foreground="#8E8E93")
        self.log_sc = Gtk.ScrolledWindow(vexpand=True)
        self.log_sc.set_child(self.view)
        box.append(self.log_sc)
        self.status = Gtk.Label(xalign=0, margin_start=16, margin_bottom=8, margin_top=6,
                                css_classes=["caption", "dim-label"], ellipsize=Pango.EllipsizeMode.END)
        box.append(self.status)
        return box

    def _page_changed(self, *_):
        if self.stack.get_visible_child_name() == "live":
            if not self.log_proc:
                self._start_log()
        # keep streaming in the background when switching tabs; stops on close

    def _start_log(self):
        cmd = ["idevicesyslog", "-u", self.udid, "--no-colors", "-x"]
        if self.quiet.get_active():
            cmd.append("-q")
        try:
            self.log_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                             errors="replace", bufsize=1)
        except OSError as e:
            self.status.set_label(f"Couldn’t start the log: {e}")
            return
        self.status.set_label("Streaming… use the iPhone and watch what happens")
        in_thread(self._read_log, self.log_proc)
        GLib.timeout_add(250, self._flush)

    def _restart_log(self):
        if self.log_proc:
            self._stop_log()
            self._start_log()

    def _stop_log(self):
        p, self.log_proc = self.log_proc, None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(2)
            except subprocess.TimeoutExpired:
                p.kill()

    def _read_log(self, proc):
        entry = []
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line == "[connected]":
                continue
            # a new message starts with a date like "Nov 20 11:52:49"; continuation lines belong to it
            if re.match(r"^[A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d ", line) and entry:
                with self.lock:
                    self.pending.append("\n".join(entry))
                entry = []
            entry.append(line)
        if entry:
            with self.lock:
                self.pending.append("\n".join(entry))
        if proc is self.log_proc:
            ui(self.status.set_label, "The log stopped (iPhone disconnected?)")

    def _flush(self):
        if self.log_proc is None and not self.pending:
            return False
        if self.paused:
            return True
        with self.lock:
            msgs, self.pending = self.pending, []
        q = self.filter.get_text().strip().lower()
        if q:
            msgs = [m for m in msgs if q in m.lower()]
        if msgs:
            adj = self.log_sc.get_vadjustment()
            at_bottom = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 40
            end = self.buf.get_end_iter()
            for m in msgs[-1500:]:
                tag = self.tag_err if "<Error>" in m or "<Fault>" in m else \
                    self.tag_warn if "<Warning>" in m else None
                ts, rest = m[:15], m[15:]  # "Nov 20 11:52:49" then the message
                self.buf.insert_with_tags(end, ts, self.tag_dim)
                if tag:
                    self.buf.insert_with_tags(end, rest + "\n", tag)
                else:
                    self.buf.insert(end, rest + "\n")
            extra = self.buf.get_line_count() - MAX_LOG_LINES
            if extra > 0:
                self.buf.delete(self.buf.get_start_iter(), self.buf.get_iter_at_line(extra)[1])
            if at_bottom:
                GLib.idle_add(lambda: (adj.set_value(adj.get_upper()), False)[1])
        return True

    def toggle_pause(self, *_):
        self.paused = not self.paused
        self.pause_btn.set_icon_name("media-playback-start-symbolic" if self.paused else
                                     "media-playback-pause-symbolic")
        self.pause_btn.set_tooltip_text("Resume" if self.paused else "Pause")
        self.status.set_label("Paused — new messages are kept and shown when you resume" if self.paused else
                              "Streaming…")

    def save_log(self, *_):
        os.makedirs(SAVE_DIR, exist_ok=True)
        path = os.path.join(SAVE_DIR, time.strftime("live-log-%Y-%m-%d-%H%M%S.txt"))
        start, end = self.buf.get_bounds()
        with open(path, "w") as f:
            f.write(self.buf.get_text(start, end, False))
        toast(self, f"Saved {os.path.basename(path)} in ~/iPhone Crash Reports")
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(SAVE_DIR).get_uri(), None)

    def _on_close(self, *_):
        self._stop_log()
        return False
