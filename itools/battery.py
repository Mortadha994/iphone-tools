"""Battery history: health and charge cycles are saved once a day whenever the iPhone is connected,
then shown as charts so you can see how fast the battery wears."""

import datetime
import json
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Graphene, Gsk, Gtk, Pango  # noqa: E402

from itools.common import BLUE, GREEN, ORANGE, RED, rgba, window_shell  # noqa: E402

HISTORY_DIR = os.environ.get("IPHONE_TOOLS_BATTERY_DIR") or os.path.expanduser("~/.local/share/iphone-tools/battery")


def history_path(udid):
    return os.path.join(HISTORY_DIR, f"{udid}.json")


def load(udid):
    try:
        with open(history_path(udid)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def record(udid, smart):
    """Save today's battery state (one entry per day; later readings the same day replace earlier ones)."""
    dc = smart.get("DesignCapacity")
    mc = smart.get("AppleRawMaxCapacity") or smart.get("NominalChargeCapacity")
    if not dc or not mc:
        return
    entry = {"date": datetime.date.today().isoformat(), "health": round(min(mc / dc * 100, 100), 1),
             "max_mah": mc, "design_mah": dc, "cycles": smart.get("CycleCount")}
    if smart.get("Temperature"):
        entry["temp_c"] = round(smart["Temperature"] / 100, 1)
    hist = [h for h in load(udid) if h.get("date") != entry["date"]]
    hist.append(entry)
    hist.sort(key=lambda h: h["date"])
    os.makedirs(HISTORY_DIR, exist_ok=True)
    tmp = history_path(udid) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(hist, f, indent=1)
    os.replace(tmp, history_path(udid))


def days(d):
    return datetime.date.fromisoformat(d).toordinal()


def trend(points):
    """Least-squares slope (per day) of [(day, value)], or None with < 2 distinct days."""
    if len({p[0] for p in points}) < 2:
        return None
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    den = sum((p[0] - mx) ** 2 for p in points)
    return sum((p[0] - mx) * (p[1] - my) for p in points) / den if den else None


def pt(x, y):
    return Graphene.Point().init(x, y)


class LineChart(Gtk.Widget):
    """A small line chart: dates along the bottom, values up the side, dots on each reading."""

    def __init__(self, points, colour, unit="", decimals=0, height=170, y_floor=None):
        super().__init__(hexpand=True)
        self.set_size_request(-1, height)
        self.points, self.colour, self.unit, self.decimals, self.y_floor = points, colour, unit, decimals, y_floor

    def _label(self, snap, text, x, y, colour, align=0.0, px=11):
        layout = self.create_pango_layout(text)
        fd = self.get_pango_context().get_font_description().copy()
        fd.set_absolute_size(px * Pango.SCALE)
        layout.set_font_description(fd)
        tw, th = layout.get_pixel_size()
        snap.save()
        snap.translate(pt(x - tw * align, y - th / 2))
        snap.append_layout(layout, colour)
        snap.restore()
        return tw

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        fg = self.get_color()
        if not self.points:
            return
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        lo, hi = min(ys), max(ys)
        if self.y_floor is not None:
            lo = min(lo, self.y_floor)
        if hi - lo < 1e-9:
            lo, hi = lo - 1, hi + 1
        pad = (hi - lo) * 0.12
        lo, hi = lo - pad, hi + pad
        x0, x1 = min(xs), max(xs)
        if x1 == x0:
            x0, x1 = x0 - 1, x1 + 1
        left, right, top, bottom = 46, w - 14, 10, h - 24

        def X(v):
            return left + (v - x0) / (x1 - x0) * (right - left)

        def Y(v):
            return bottom - (v - lo) / (hi - lo) * (bottom - top)

        # grid + value labels
        grid = Gsk.Stroke.new(1)
        for i in range(4):
            v = lo + (hi - lo) * i / 3
            b = Gsk.PathBuilder.new()
            b.move_to(left, Y(v))
            b.line_to(right, Y(v))
            snap.append_stroke(b.to_path(), grid, rgba(fg, 0.08))
            self._label(snap, f"{v:.{self.decimals}f}{self.unit}", left - 8, Y(v), rgba(fg, 0.5), align=1.0)
        # date labels: first and last (and the middle when there's room)
        marks = sorted({x0 if len(set(xs)) == 1 else min(xs), max(xs)} | ({(min(xs) + max(xs)) // 2}
                                                                       if len(set(xs)) > 2 else set()))
        for i, m in enumerate(marks):
            d = datetime.date.fromordinal(int(m))
            align = 0.0 if i == 0 and len(marks) > 1 else 1.0 if i == len(marks) - 1 and len(marks) > 1 else 0.5
            self._label(snap, d.strftime("%-d %b %Y"), X(m), h - 9, rgba(fg, 0.55), align=align)

        # area + line
        pts = sorted(self.points)
        if len(pts) > 1:
            area = Gsk.PathBuilder.new()
            area.move_to(X(pts[0][0]), bottom)
            for x, y in pts:
                area.line_to(X(x), Y(y))
            area.line_to(X(pts[-1][0]), bottom)
            area.close()
            snap.push_fill(area.to_path(), Gsk.FillRule.WINDING)
            snap.append_linear_gradient(Graphene.Rect().init(0, top, w, bottom - top), pt(0, top), pt(0, bottom),
                                        _stops(self.colour))
            snap.pop()
            line = Gsk.PathBuilder.new()
            line.move_to(X(pts[0][0]), Y(pts[0][1]))
            for x, y in pts[1:]:
                line.line_to(X(x), Y(y))
            s = Gsk.Stroke.new(2.5)
            s.set_line_join(Gsk.LineJoin.ROUND)
            s.set_line_cap(Gsk.LineCap.ROUND)
            snap.append_stroke(line.to_path(), s, rgba(self.colour))
        for x, y in pts:
            b = Gsk.PathBuilder.new()
            b.add_circle(pt(X(x), Y(y)), 3.5 if len(pts) < 40 else 2)
            snap.append_fill(b.to_path(), Gsk.FillRule.WINDING, rgba(self.colour))


def _stops(colour):
    a, b = Gsk.ColorStop(), Gsk.ColorStop()
    a.offset, a.color = 0.0, rgba(colour, 0.30)
    b.offset, b.color = 1.0, rgba(colour, 0.0)
    return [a, b]


def stat(title, value, sub, colour=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["card"], hexpand=True)
    box.append(Gtk.Label(label=title.upper(), xalign=0, css_classes=["caption", "dim-label"]))
    v = Gtk.Label(label=value, xalign=0, css_classes=["stat-value"])
    if colour:
        v.add_css_class({GREEN: "stat-green", ORANGE: "stat-orange", RED: "stat-red"}.get(colour, ""))
    box.append(v)
    box.append(Gtk.Label(label=sub, xalign=0, wrap=True, css_classes=["caption", "dim-label"]))
    return box


class BatteryHistoryWindow(Adw.Window):
    def __init__(self, parent, udid):
        super().__init__(transient_for=parent)
        self.udid = udid
        col = window_shell(self, "Battery history", "Saved each day the iPhone is connected", width=620, height=820)
        hist = load(udid)
        if not hist:
            col.append(Gtk.Label(label="No readings yet. They’re saved automatically each time the iPhone is "
                                       "connected.", wrap=True, margin_top=40, css_classes=["dim-label"]))
            return
        last, first = hist[-1], hist[0]
        span = days(last["date"]) - days(first["date"])
        h = last["health"]
        hc = GREEN if h >= 85 else ORANGE if h >= 80 else RED

        stats = Gtk.Box(spacing=10, homogeneous=True)
        stats.append(stat("Health", f"{h:.0f}%", f"{last['max_mah']} of {last['design_mah']} mAh", hc))
        stats.append(stat("Cycles", str(last.get("cycles", "—")), "full charges so far"))
        hpts = [(days(e["date"]), e["health"]) for e in hist]
        cpts = [(days(e["date"]), e["cycles"]) for e in hist if e.get("cycles") is not None]
        slope = trend(hpts) if span >= 14 else None
        if slope is not None and slope < 0:
            per_month = -slope * 30.4
            left = (h - 80) / -slope if h > 80 else 0
            when = (datetime.date.today() + datetime.timedelta(days=left)).strftime("%b %Y") if left else "now"
            stats.append(stat("Wear", f"−{per_month:.1f}%/mo", f"reaches 80% around {when}"))
        else:
            stats.append(stat("Wear", "—", "needs 2+ weeks of readings"))
        col.append(stats)

        for title, pts, colour, unit, dec, floor in (
                ("Battery health", hpts, hc, "%", 0, 80), ("Charge cycles", cpts, BLUE, "", 0, None)):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["card"])
            card.append(Gtk.Label(label=title, xalign=0, css_classes=["section-title"]))
            card.append(LineChart(pts, colour, unit=unit, decimals=dec, y_floor=floor))
            col.append(card)

        if len(hist) < 3:
            col.append(Gtk.Label(wrap=True, xalign=0, css_classes=["caption", "dim-label"], label=(
                f"Recording since {datetime.date.fromisoformat(first['date']).strftime('%-d %B %Y')}. A new point is "
                "added each day you plug in the iPhone, so the charts fill in over the coming weeks.")))

        g = Adw.PreferencesGroup(title="Readings")
        for e in reversed(hist[-60:]):
            d = datetime.date.fromisoformat(e["date"]).strftime("%a %-d %b %Y")
            r = Adw.ActionRow(title=d, use_markup=False)
            extra = f" · {e['temp_c']:.0f} °C" if e.get("temp_c") else ""
            r.add_suffix(Gtk.Label(label=f"{e['health']:.1f}% · {e.get('cycles', '—')} cycles{extra}",
                                   css_classes=["dim-label", "numeric"]))
            g.add(r)
        col.append(g)

