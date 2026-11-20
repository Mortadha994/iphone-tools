"""Videos to iPhone: convert any video to an iPhone-friendly MP4 (H.264 + AAC) and send it to a video app
such as VLC. Files the iPhone can already play are sent as they are."""

import os
import shutil
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
gi.require_version("GstPbutils", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gst, GstPbutils, Gtk  # noqa: E402

from itools.common import AppDocs, human_size, in_thread, share_apps, themed, toast, ui, window_shell  # noqa: E402

VIDEO_EXT = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".m2ts",
             ".3gp", ".ogv", ".mts"}
WORK_DIR = os.path.expanduser("~/.cache/iphone-tools/video-out")
# Apps that accept videos from a computer, best first: (bundle id, how to find the videos on the phone)
VIDEO_APPS = {
    "org.videolan.vlc-ios": "Open VLC → Videos.",
    "com.firecore.infuse": "Open Infuse → Files → Other Locations → Infuse files.",
    "it.ideasolutions.amerigo-free": "Open Amerigo → Local files.",
    "com.readdle.ReaddleDocsIPad": "Open Documents → My Files.",
}


def init_gst():
    if not Gst.is_initialized():
        Gst.init(None)


def plays_on_iphone(path):
    """True if the file is already MP4/MOV with H.264/HEVC video and AAC (or no) audio, so no conversion needed."""
    init_gst()
    try:
        info = GstPbutils.Discoverer.new(15 * Gst.SECOND).discover_uri(Gst.filename_to_uri(path))
    except GLib.Error:
        return False, 0
    dur = info.get_duration() / Gst.SECOND if info.get_duration() else 0
    top = info.get_stream_info()
    caps = top.get_caps().to_string() if top and top.get_caps() else ""
    if not caps.startswith("video/quicktime"):
        return False, dur
    vids = info.get_video_streams()
    if not vids:
        return False, dur
    for v in vids:
        if not v.get_caps().to_string().startswith(("video/x-h264", "video/x-h265")):
            return False, dur
    for a in info.get_audio_streams():
        c = a.get_caps().to_string()
        if not (c.startswith("audio/mpeg") and "mpegversion=(int)4" in c):
            return False, dur
    return True, dur


def aac_encoder():
    for name in ("avenc_aac", "voaacenc", "fdkaacenc", "faac"):
        if Gst.ElementFactory.find(name):
            return name
    return None


def convert(src, dst, progress=None, cancel=lambda: False):
    """Transcode src to an H.264 (x264) + AAC MP4 at dst with GStreamer. Raises RuntimeError on failure.
    The encoders are chosen explicitly: letting GStreamer pick can select a GPU encoder that then fails."""
    init_gst()
    if not Gst.ElementFactory.find("x264enc"):
        raise RuntimeError("H.264 encoder missing: sudo apt install gstreamer1.0-plugins-ugly")
    aac = aac_encoder()
    pipe = Gst.Pipeline.new("convert")
    dec = Gst.ElementFactory.make("uridecodebin", None)
    dec.set_property("uri", Gst.filename_to_uri(src))
    mux = Gst.ElementFactory.make("mp4mux", None)
    mux.set_property("faststart", True)            # starts playing before it is fully loaded
    sink = Gst.ElementFactory.make("filesink", None)
    sink.set_property("location", dst)
    for e in (dec, mux, sink):
        pipe.add(e)
    mux.link(sink)
    linked = set()

    def branch(desc):
        bin_ = Gst.parse_bin_from_description(desc, True)
        pipe.add(bin_)
        bin_.sync_state_with_parent()
        return bin_

    def on_pad(_dec, pad):
        caps = pad.get_current_caps() or pad.query_caps(None)
        kind = caps.to_string().split("/", 1)[0] if caps else ""
        if kind in linked:
            return
        if kind == "video":
            b = branch("queue ! videoconvert ! video/x-raw,format=I420 ! "
                       "x264enc speed-preset=faster pass=quant quantizer=21 key-int-max=120 ! "
                       "video/x-h264,profile=high ! h264parse")
        elif kind == "audio" and aac:
            b = branch(f"queue ! audioconvert ! audioresample ! audio/x-raw,rate=48000 ! {aac} bitrate=160000 ! "
                       "aacparse")
        else:
            return
        linked.add(kind)
        pad.link(b.get_static_pad("sink"))
        b.get_static_pad("src").link(mux.request_pad_simple("video_%u" if kind == "video" else "audio_%u"))
    dec.connect("pad-added", on_pad)

    pipe.set_state(Gst.State.PLAYING)
    bus = pipe.get_bus()
    err = None
    try:
        while True:
            if cancel():
                err = "cancelled"
                break
            msg = bus.timed_pop_filtered(200 * Gst.MSECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
            if progress:
                ok_d, dur = pipe.query_duration(Gst.Format.TIME)
                ok_p, pos = pipe.query_position(Gst.Format.TIME)
                if ok_d and ok_p and dur > 0:
                    progress(min(pos / dur, 1.0))
            if msg is None:
                continue
            if msg.type == Gst.MessageType.ERROR:
                e, _dbg = msg.parse_error()
                err = e.message
            break
    finally:
        pipe.set_state(Gst.State.NULL)
    if err or "video" not in linked:
        if os.path.exists(dst):
            os.unlink(dst)
        raise RuntimeError(err or "No video track found in this file")


def collect(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for d, _, fs in os.walk(p):
                out += [os.path.join(d, f) for f in sorted(fs) if os.path.splitext(f)[1].lower() in VIDEO_EXT]
        elif os.path.splitext(p)[1].lower() in VIDEO_EXT:
            out.append(p)
    return out


class VideosWindow(Adw.Window):
    def __init__(self, parent, udid):
        super().__init__(transient_for=parent)
        self.udid = udid
        self.apps, self.items, self.busy, self.cancel = [], [], False, False
        self.lock = threading.Lock()
        col = window_shell(self, "Videos to iPhone", "Converted to play on the iPhone", width=580, height=780)

        tgt = Adw.PreferencesGroup(title="Send videos to")
        self.combo = Adw.ComboRow(title="Video app", model=Gtk.StringList.new(["Loading apps…"]), sensitive=False)
        self.combo.add_prefix(Gtk.Image(gicon=themed("vlc"), pixel_size=32))
        self.combo.connect("notify::selected", lambda *_: self._target_changed())
        tgt.add(self.combo)
        col.append(tgt)
        self.hint = Gtk.Label(wrap=True, xalign=0, css_classes=["hint-card"])
        col.append(self.hint)

        dz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["dropzone"])
        dz.append(Gtk.Image(gicon=themed("video-x-generic"), pixel_size=64, css_classes=["float-icon"]))
        dz.append(Gtk.Label(label="Drop videos or a folder here", css_classes=["big"]))
        dz.append(Gtk.Label(label="MP4 · MKV · AVI · MOV · WEBM …", css_classes=["caption", "dim-label"]))
        self.pick = Gtk.Button(label="Choose videos…", css_classes=["pill"], halign=Gtk.Align.CENTER)
        self.pick.connect("clicked", self._choose)
        dz.append(self.pick)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("enter", lambda *_: (dz.add_css_class("hover"), Gdk.DragAction.COPY)[1])
        drop.connect("leave", lambda *_: dz.remove_css_class("hover"))
        drop.connect("drop", lambda _t, v, *_: (dz.remove_css_class("hover"),
                                                self.add([f.get_path() for f in v.get_files() if f.get_path()]),
                                                True)[2])
        dz.add_controller(drop)
        col.append(dz)

        self.queue = Adw.PreferencesGroup(title="Queue")
        self.go = Gtk.Button(label="Send to iPhone", css_classes=["suggested-action", "pill"], sensitive=False)
        self.go.connect("clicked", self.start)
        self.queue.set_header_suffix(self.go)
        self.queue.set_visible(False)
        col.append(self.queue)
        col.append(Gtk.Label(wrap=True, xalign=0, css_classes=["caption", "dim-label"], label=(
            "Videos the iPhone can already play are sent unchanged; others are converted to MP4 (H.264 + AAC) on "
            "this PC first. iOS doesn’t let a computer add videos to the Photos app, so they go into a video app.")))

        self.spinner.start()
        in_thread(self._load_apps)

    # --- target app
    def _load_apps(self):
        apps = share_apps(self.udid)
        known = [a for a in apps if a[0] in VIDEO_APPS]
        known.sort(key=lambda a: list(VIDEO_APPS).index(a[0]))
        others = sorted((a for a in apps if a[0] not in VIDEO_APPS), key=lambda a: a[1].lower())
        ui(self._apps_loaded, known + others, bool(known))

    def _apps_loaded(self, apps, has_video_app):
        self.spinner.stop()
        self.apps = apps
        if not apps:
            self.combo.set_model(Gtk.StringList.new(["No app accepts files"]))
            self.hint.set_label("Install VLC from the App Store on the iPhone, then open this window again.")
            return
        self.combo.set_model(Gtk.StringList.new([a[1] for a in apps]))
        self.combo.set_sensitive(True)
        if not has_video_app:
            self.hint.set_label("Tip: install VLC (free) from the App Store — it plays almost any video. "
                                "Until then, pick another app that accepts files.")
        self._target_changed()
        self._update_go()

    def _target_changed(self):
        i = self.combo.get_selected()
        if 0 <= i < len(self.apps) and self.apps[i][0] in VIDEO_APPS:
            self.hint.set_label(f"After sending: {VIDEO_APPS[self.apps[i][0]]}")

    # --- queue
    def _choose(self, *_):
        d = Gtk.FileDialog(title="Choose videos")
        f = Gtk.FileFilter(name="Videos")
        f.add_mime_type("video/*")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        d.set_filters(store)
        d.set_initial_folder(Gio.File.new_for_path(os.path.expanduser("~/Videos")
                                                   if os.path.isdir(os.path.expanduser("~/Videos"))
                                                   else os.path.expanduser("~")))

        def done(dlg, res):
            try:
                files = dlg.open_multiple_finish(res)
            except GLib.Error:
                return
            self.add([files.get_item(i).get_path() for i in range(files.get_n_items())])
        d.open_multiple(self, None, done)

    def add(self, paths):
        new = [p for p in collect(paths) if p not in [it["path"] for it in self.items]]
        if not new:
            toast(self, "No videos found there")
            return
        for p in new:
            row = Adw.ActionRow(title=os.path.basename(p), use_markup=False, subtitle="Checking…")
            row.set_title_lines(1)
            st = Gtk.Label(css_classes=["dim-label", "numeric"], valign=Gtk.Align.CENTER)
            row.add_suffix(st)
            bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=90, visible=False)
            row.add_suffix(bar)
            rm = Gtk.Button(icon_name="list-remove-symbolic", css_classes=["flat", "circular"],
                            valign=Gtk.Align.CENTER, tooltip_text="Remove from the queue")
            item = {"path": p, "row": row, "status": st, "bar": bar, "rm": rm, "ready": None, "done": False}
            rm.connect("clicked", lambda _b, it=item: self._remove(it))
            row.add_suffix(rm)
            self.items.append(item)
            self.queue.add(row)
            in_thread(self._probe, item)
        self.queue.set_visible(True)
        self._update_go()

    def _probe(self, item):
        ok, dur = plays_on_iphone(item["path"])
        size = os.path.getsize(item["path"])
        mins = f"{int(dur // 60)}:{int(dur % 60):02d} · " if dur else ""
        ui(self._probed, item, ok, f"{mins}{human_size(size)} · " + ("plays as is" if ok else "will be converted"))

    def _probed(self, item, ok, sub):
        item["ready"] = ok
        item["row"].set_subtitle(sub)

    def _remove(self, item):
        if self.busy:
            return
        self.queue.remove(item["row"])
        self.items.remove(item)
        self.queue.set_visible(bool(self.items))
        self._update_go()

    def _update_go(self):
        todo = [i for i in self.items if not i["done"]]
        self.go.set_sensitive(bool(todo) and bool(self.apps) and not self.busy)
        self.go.set_label("Stop" if self.busy else f"Send {len(todo)} to iPhone" if todo else "Send to iPhone")

    # --- convert + send
    def start(self, *_):
        if self.busy:
            self.cancel = True
            return
        i = self.combo.get_selected()
        if not (0 <= i < len(self.apps)):
            return
        self.busy, self.cancel = True, False
        self.go.set_sensitive(True)
        self.go.set_label("Stop")
        self.go.remove_css_class("suggested-action")
        self.go.add_css_class("destructive-action")
        self.spinner.start()
        in_thread(self._worker, self.apps[i][0], [it for it in self.items if not it["done"]])

    def _worker(self, app_id, items):
        os.makedirs(WORK_DIR, exist_ok=True)
        sent = 0
        err = None
        for it in items:
            if self.cancel:
                break
            src = it["path"]
            try:
                if it["ready"] is None:
                    it["ready"] = plays_on_iphone(src)[0]
                if it["ready"]:
                    out, name = src, os.path.basename(src)
                else:
                    name = os.path.splitext(os.path.basename(src))[0] + ".mp4"
                    out = os.path.join(WORK_DIR, name)
                    ui(self._state, it, "Converting…", 0)
                    t0 = time.time()
                    convert(src, out, lambda f, i=it: ui(self._state, i, f"Converting {f * 100:.0f}%", f),
                            lambda: self.cancel)
                    it["took"] = time.time() - t0
                ui(self._state, it, "Sending…", None)
                with self.lock, AppDocs(self.udid, app_id, name="video-mnt") as mnt:
                    dst = os.path.join(mnt, name)
                    base, ext = os.path.splitext(dst)
                    k = 2
                    while os.path.exists(dst):
                        dst, k = f"{base} ({k}){ext}", k + 1
                    shutil.copyfile(out, dst + ".part")
                    os.replace(dst + ".part", dst)
                if out != src:
                    os.unlink(out)
                it["done"] = True
                sent += 1
                ui(self._state, it, "✔ On the iPhone", 1)
            except Exception as e:  # noqa: BLE001 - shown on the row
                if self.cancel:
                    ui(self._state, it, "Stopped", None)
                    break
                err = str(e)
                ui(self._state, it, "Failed", None)
                ui(self._row_error, it, err)
        ui(self._finished, sent, len(items), err)

    def _state(self, it, text, frac):
        it["status"].set_label(text)
        it["bar"].set_visible(frac is not None and frac < 1)
        if frac is not None:
            it["bar"].set_fraction(frac)
        it["rm"].set_visible(not self.busy)

    def _row_error(self, it, err):
        it["row"].set_subtitle(err[:120])
        it["row"].set_subtitle_lines(2)

    def _finished(self, sent, total, err):
        self.busy = False
        self.spinner.stop()
        self.go.remove_css_class("destructive-action")
        self.go.add_css_class("suggested-action")
        for it in self.items:
            it["rm"].set_visible(True)
        self._update_go()
        if self.cancel:
            toast(self, f"Stopped — {sent} of {total} sent")
        elif err:
            toast(self, f"{sent} of {total} sent; some failed")
        else:
            toast(self, f"✔ {sent} video{'s' * (sent != 1)} sent to the iPhone")

