"""Messages & contacts export: turn the SMS/iMessage, WhatsApp and Contacts databases inside a backup into
readable files (a web page per chat, plain text, vCard and CSV)."""

import csv
import datetime
import html
import os
import re
import shutil
import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from itools.backups import backups  # noqa: E402
from itools.common import human_size, in_thread, open_folder, progress_card, show_card, toast, ui, window_shell  # noqa: E402,E501

EXPORT_DIR = os.path.expanduser("~/iPhone Exports")
APPLE_EPOCH = datetime.datetime(2001, 1, 1)
REACTIONS = {2000: "❤️", 2001: "👍", 2002: "👎", 2003: "😂", 2004: "‼️", 2005: "❓", 2006: "reacted"}

CSS = """
body{font:15px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#f2f2f7;color:#1c1c1e}
header{position:sticky;top:0;background:#fffc;backdrop-filter:blur(12px);padding:14px 20px;
  border-bottom:1px solid #d1d1d6;z-index:1}
header h1{font-size:18px;margin:0}header p{margin:2px 0 0;color:#8e8e93;font-size:13px}
main{max-width:760px;margin:0 auto;padding:12px 16px 40px}
.day{text-align:center;color:#8e8e93;font-size:12px;margin:18px 0 8px}
.m{display:flex;margin:3px 0}.m.me{justify-content:flex-end}.m>div{max-width:75%}
.b{padding:8px 12px;border-radius:18px;background:#e5e5ea;white-space:pre-wrap;overflow-wrap:anywhere}
.b a{color:inherit}
.me .b{background:#0a84ff;color:#fff}.me.sms .b{background:#30d158}
.who{font-size:12px;color:#8e8e93;margin:0 0 2px 4px}.t{font-size:11px;opacity:.6;margin-top:2px;text-align:right}
.b img,.b video{max-width:100%;border-radius:12px;display:block;margin-top:4px}
.note{text-align:center;color:#8e8e93;font-size:12px;margin:6px 0}
ul.chats{list-style:none;padding:0}ul.chats li{background:#fff;margin:6px 0;border-radius:12px}
ul.chats a{display:flex;justify-content:space-between;padding:12px 16px;color:inherit;text-decoration:none}
ul.chats span{color:#8e8e93}
@media(prefers-color-scheme:dark){body{background:#000;color:#f2f2f7}header{background:#1c1c1ecc;border-color:#38383a}
  .b{background:#2c2c2e}ul.chats li{background:#1c1c1e}}
"""


def apple_time(v):
    """Apple's Core Data time (seconds or nanoseconds since 2001-01-01) -> local datetime, or None."""
    if not v:
        return None
    v = float(v)
    if v > 1e11:
        v /= 1e9
    try:
        utc = APPLE_EPOCH + datetime.timedelta(seconds=v)
        return utc.replace(tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
    except OverflowError:
        return None


def attributed_text(blob):
    """Text out of iMessage's attributedBody (an NSAttributedString 'typedstream')."""
    if not blob:
        return None
    i = blob.find(b"NSString")
    if i < 0:
        return None
    p = i + len("NSString") + 5
    if p >= len(blob):
        return None
    n = blob[p]
    if n == 0x81:
        n, start = int.from_bytes(blob[p + 1:p + 3], "little"), p + 3
    elif n == 0x82:
        n, start = int.from_bytes(blob[p + 1:p + 4], "little"), p + 4
    else:
        start = p + 1
    return blob[start:start + n].decode("utf-8", "replace") or None


def digits(s):
    return re.sub(r"\D", "", s or "")


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", s).strip(" .")
    return (s or "chat")[:80]


class BackupFiles:
    """Find files inside a backup by domain + path."""

    def __init__(self, path):
        self.path = path
        self.db = sqlite3.connect(f"file:{os.path.join(path, 'Manifest.db')}?mode=ro", uri=True)

    def find(self, domain, rel):
        r = self.db.execute("select fileID from Files where domain=? and relativePath=?", (domain, rel)).fetchone()
        if not r:
            return None
        p = os.path.join(self.path, r[0][:2], r[0])
        return p if os.path.exists(p) else None

    def find_like(self, domain_like, rel):
        r = self.db.execute("select domain from Files where domain like ? and relativePath=?",
                            (domain_like, rel)).fetchone()
        return (r[0], self.find(r[0], rel)) if r else (None, None)


def open_ro(p):
    return sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)


# ---------------------------------------------------------------- contacts
def read_contacts(bf):
    p = bf.find("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb")
    if not p:
        return []
    db = open_ro(p)
    people = {}
    for rid, first, last, org, nick, bday, note in db.execute(
            "select ROWID, First, Last, Organization, Nickname, Birthday, Note from ABPerson"):
        name = " ".join(x for x in (first, last) if x) or org or nick or ""
        people[rid] = {"name": name, "first": first or "", "last": last or "", "org": org or "", "phones": [],
                       "emails": [], "birthday": bday, "note": note or ""}
    for rid, prop, value in db.execute("select record_id, property, value from ABMultiValue where value is not null"):
        if rid in people:
            if prop == 3:
                people[rid]["phones"].append(str(value))
            elif prop == 4:
                people[rid]["emails"].append(str(value))
    return [p for p in people.values() if p["name"] or p["phones"] or p["emails"]]


def contact_lookup(contacts):
    """handle (phone/email) -> contact name. Phones match on their last 8 digits (ignores +216, 00216 …)."""
    by_tail, by_mail = {}, {}
    for c in contacts:
        for ph in c["phones"]:
            d = digits(ph)
            if len(d) >= 6:
                by_tail.setdefault(d[-8:], c["name"])
        for m in c["emails"]:
            by_mail[m.lower()] = c["name"]

    def name(handle):
        if not handle:
            return None
        if "@" in handle:
            return by_mail.get(handle.lower())
        d = digits(handle)
        return by_tail.get(d[-8:]) if len(d) >= 6 else None
    return name


def write_contacts(contacts, out):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "Contacts.vcf"), "w", newline="") as f:
        for c in contacts:
            f.write("BEGIN:VCARD\r\nVERSION:3.0\r\n")
            f.write(f"N:{c['last']};{c['first']};;;\r\nFN:{c['name'] or (c['phones'] or c['emails'])[0]}\r\n")
            if c["org"]:
                f.write(f"ORG:{c['org']}\r\n")
            for ph in c["phones"]:
                f.write(f"TEL;TYPE=CELL:{ph}\r\n")
            for m in c["emails"]:
                f.write(f"EMAIL:{m}\r\n")
            if c["note"]:
                f.write("NOTE:" + c["note"].replace("\n", "\\n") + "\r\n")
            f.write("END:VCARD\r\n")
    with open(os.path.join(out, "Contacts.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Name", "Phones", "Emails", "Organization", "Note"])
        for c in sorted(contacts, key=lambda c: c["name"].lower()):
            w.writerow([c["name"], " | ".join(c["phones"]), " | ".join(c["emails"]), c["org"], c["note"]])
    return len(contacts)


# ---------------------------------------------------------------- chat rendering
def render_chat(title, subtitle, msgs, path_html, path_txt):
    """msgs: [(datetime, is_me, sender or None, text, service, media_rel or None)]"""
    out, txt, day = [], [], None
    for when, me, sender, text, service, media in msgs:
        d = when.date() if when else None
        if d != day:
            day = d
            label = when.strftime("%A %-d %B %Y") if when else "Unknown date"
            out.append(f'<div class="day">{label}</div>')
            txt.append(f"\n—— {label} ——")
        cls = "m me" if me else "m"
        if service == "SMS":
            cls += " sms"
        body = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', html.escape(text or ""))
        if media:
            ext = os.path.splitext(media)[1].lower()
            src = html.escape(media)
            if ext in (".jpg", ".jpeg", ".png", ".heic", ".gif", ".webp"):
                body += f'<a href="{src}"><img src="{src}" loading="lazy"></a>'
            elif ext in (".mp4", ".mov", ".m4v"):
                body += f'<video src="{src}" controls preload="none"></video>'
            else:
                body += f'<br><a href="{src}">📎 {html.escape(os.path.basename(media))}</a>'
        who = f'<div class="who">{html.escape(sender)}</div>' if sender and not me else ""
        t = when.strftime("%H:%M") if when else ""
        out.append(f'<div class="{cls}"><div>{who}<div class="b">{body}<div class="t">{t}</div></div></div></div>')
        name = "Me" if me else (sender or title)
        txt.append(f"[{t}] {name}: {text or ''}{'  [' + os.path.basename(media) + ']' if media else ''}")
    with open(path_html, "w") as f:
        f.write(f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                f'<title>{html.escape(title)}</title><style>{CSS}</style>'
                f'<header><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></header><main>'
                + "\n".join(out) + "</main>")
    with open(path_txt, "w") as f:
        f.write(f"{title}\n{subtitle}\n" + "\n".join(txt) + "\n")


def write_index(folder, title, chats):
    """chats: [(file name, chat title, count, last datetime)]"""
    items = "".join(f'<li><a href="{html.escape(fn)}"><b>{html.escape(t)}</b><span>{n} · '
                    f'{d.strftime("%-d %b %Y") if d else ""}</span></a></li>'
                    for fn, t, n, d in sorted(chats, key=lambda c: c[3] or datetime.datetime.min, reverse=True))
    with open(os.path.join(folder, "index.html"), "w") as f:
        f.write(f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
                f'<title>{html.escape(title)}</title><style>{CSS}</style><header><h1>{html.escape(title)}</h1>'
                f'<p>{len(chats)} chats</p></header><main><ul class="chats">{items}</ul></main>')


def unique(path):
    base, ext = os.path.splitext(path)
    i, p = 2, path
    while os.path.exists(p):
        p, i = f"{base} ({i}){ext}", i + 1
    return p


# ---------------------------------------------------------------- SMS / iMessage
def export_messages(bf, name_of, out, progress=None, cancel=lambda: False):
    p = bf.find("HomeDomain", "Library/SMS/sms.db")
    if not p:
        return 0, 0
    db = open_ro(p)
    handles = dict(db.execute("select ROWID, id from handle"))
    os.makedirs(out, exist_ok=True)
    media_dir = os.path.join(out, "attachments")
    chats = db.execute("select ROWID, chat_identifier, display_name, service_name from chat").fetchall()
    index, total = [], 0
    for k, (cid, ident, display, service) in enumerate(chats):
        if cancel():
            break
        members = [h for (h,) in db.execute(
            "select h.id from chat_handle_join j join handle h on h.ROWID=j.handle_id where j.chat_id=?", (cid,))]
        names = [name_of(m) or m for m in members] or [name_of(ident) or ident]
        title = display or ", ".join(names[:4]) + (f" +{len(names) - 4}" if len(names) > 4 else "")
        rows = db.execute(
            "select m.ROWID, m.date, m.is_from_me, m.handle_id, m.text, m.attributedBody, m.service, "
            "m.associated_message_type, m.item_type, m.cache_has_attachments "
            "from chat_message_join j join message m on m.ROWID=j.message_id where j.chat_id=? order by m.date",
            (cid,)).fetchall()
        msgs = []
        for mid, date, me, hid, text, body, svc, assoc, item, has_att in rows:
            if item:  # group renamed, member added … not a message
                continue
            text = text if text is not None else attributed_text(body)
            if text:
                text = text.replace("￼", "").strip()  # attachment placeholder character
            if assoc and assoc in REACTIONS:
                continue  # tapbacks: skip (they'd look like duplicate messages)
            sender = None if me else (name_of(handles.get(hid)) or handles.get(hid))
            media = None
            if has_att:
                for fn, tname in db.execute(
                        "select a.filename, a.transfer_name from message_attachment_join j join attachment a "
                        "on a.ROWID=j.attachment_id where j.message_id=?", (mid,)):
                    if not fn:
                        continue
                    rel = fn.replace("~/", "", 1) if fn.startswith("~/") else fn.split("/mobile/", 1)[-1]
                    src = bf.find("MediaDomain", rel) or bf.find("HomeDomain", rel)
                    if src:
                        os.makedirs(media_dir, exist_ok=True)
                        dst = unique(os.path.join(media_dir, safe_name(tname or os.path.basename(rel))))
                        shutil.copyfile(src, dst)
                        media = os.path.relpath(dst, out)
            if not text and not media:
                continue
            msgs.append((apple_time(date), bool(me), sender, text, svc, media))
        if not msgs:
            continue
        fn = safe_name(title)
        html_path = unique(os.path.join(out, fn + ".html"))
        render_chat(title, f"{len(msgs)} messages · {service or 'SMS'}", msgs, html_path,
                    os.path.splitext(html_path)[0] + ".txt")
        index.append((os.path.basename(html_path), title, len(msgs), msgs[-1][0]))
        total += len(msgs)
        if progress:
            progress((k + 1) / len(chats), title)
    write_index(out, "Messages", index)
    return len(index), total


# ---------------------------------------------------------------- WhatsApp
def export_whatsapp(bf, name_of, out, progress=None, cancel=lambda: False):
    domain, p = bf.find_like("AppDomainGroup-group.net.whatsapp.WhatsApp%.shared", "ChatStorage.sqlite")
    if not p:
        return 0, 0
    db = open_ro(p)
    os.makedirs(out, exist_ok=True)
    media_dir = os.path.join(out, "media")
    members = {pk: (cname or (name_of(jid.split("@")[0]) if jid else None) or (jid or "").split("@")[0])
               for pk, cname, jid in db.execute("select Z_PK, ZCONTACTNAME, ZMEMBERJID from ZWAGROUPMEMBER")}
    sessions = db.execute("select Z_PK, ZPARTNERNAME, ZCONTACTJID, ZSESSIONTYPE from ZWACHATSESSION "
                          "where coalesce(ZREMOVED,0)=0").fetchall()
    index, total = [], 0
    for k, (sid, partner, jid, stype) in enumerate(sessions):
        if cancel():
            break
        if jid and jid.endswith("@status"):
            continue
        title = partner or name_of((jid or "").split("@")[0]) or (jid or "Chat").split("@")[0]
        rows = db.execute(
            "select m.ZMESSAGEDATE, m.ZISFROMME, m.ZGROUPMEMBER, m.ZTEXT, m.ZMESSAGETYPE, mi.ZMEDIALOCALPATH, "
            "mi.ZTITLE, mi.ZLATITUDE, mi.ZLONGITUDE from ZWAMESSAGE m left join ZWAMEDIAITEM mi on "
            "mi.Z_PK=m.ZMEDIAITEM where m.ZCHATSESSION=? order by m.ZMESSAGEDATE", (sid,)).fetchall()
        msgs = []
        for date, me, gm, text, mtype, mpath, mtitle, lat, lon in rows:
            if mtype in (6, 10):  # system / group event notices
                continue
            media = None
            if mpath:
                src = bf.find(domain, "Message/" + mpath) or bf.find(domain, mpath)
                if src:
                    os.makedirs(media_dir, exist_ok=True)
                    dst = unique(os.path.join(media_dir, safe_name(os.path.basename(mpath))))
                    shutil.copyfile(src, dst)
                    media = os.path.relpath(dst, out)
                elif not text and mtype in MEDIA_KINDS:
                    text = f"[{MEDIA_KINDS[mtype]} not in the backup]"
            if mtype == 5 and lat:
                text = (text or "") + f"📍 https://maps.google.com/?q={lat},{lon}"
            if not text and mtitle:
                text = mtitle
            if not text and not media:
                continue
            sender = None if me else (members.get(gm) if gm else title)
            msgs.append((apple_time(date), bool(me), sender if stype == 1 else None, text, "WhatsApp", media))
        if not msgs:
            continue
        html_path = unique(os.path.join(out, safe_name(title) + ".html"))
        render_chat(title, f"{len(msgs)} messages · WhatsApp{' group' if stype == 1 else ''}", msgs, html_path,
                    os.path.splitext(html_path)[0] + ".txt")
        index.append((os.path.basename(html_path), title, len(msgs), msgs[-1][0]))
        total += len(msgs)
        if progress:
            progress((k + 1) / len(sessions), title)
    write_index(out, "WhatsApp", index)
    return len(index), total


MEDIA_KINDS = {1: "Photo", 2: "Video", 3: "Voice message", 4: "Contact card", 8: "Document", 11: "GIF",
               15: "Sticker"}  # other types (calls, polls, events …) are skipped when they have no text


# ---------------------------------------------------------------- window
class ExportWindow(Adw.Window):
    def __init__(self, parent, udid=None):
        super().__init__(transient_for=parent)
        self.udid = udid
        self.cancel = False
        self.backup = None
        col = window_shell(self, "Export messages & contacts", "From your latest backup")
        found = backups()
        if not found:
            col.append(Adw.StatusPage(title="No backup yet", icon_name="drive-harddisk-symbolic",
                                      description="Messages and contacts are read from a backup. Click “Back up” in "
                                                  "the main window first, then come back here."))
            return
        self.backup = found[0]
        b = self.backup
        info = Adw.ActionRow(title=f"Backup of {b[1]}", use_markup=False,
                             subtitle=f"{b[2]:%-d %B %Y, %H:%M}" if b[2] else "")
        info.add_prefix(Gtk.Image(icon_name="drive-harddisk", pixel_size=32))
        g0 = Adw.PreferencesGroup(description="Make a new backup first to include your latest messages.")
        g0.add(info)
        col.append(g0)

        g = Adw.PreferencesGroup(title="What to export")
        self.sw_msgs = Adw.SwitchRow(title="Messages", subtitle="SMS and iMessage, with photos", active=True)
        self.sw_wa = Adw.SwitchRow(title="WhatsApp", subtitle="Chats, with the photos and videos in the backup",
                                   active=True)
        self.sw_contacts = Adw.SwitchRow(title="Contacts", subtitle="vCard (for any phone or Google Contacts) "
                                                                    "and a CSV spreadsheet", active=True)
        for w in (self.sw_msgs, self.sw_wa, self.sw_contacts):
            g.add(w)
        calls = Adw.ActionRow(title="Call history", subtitle="Only in encrypted backups — not available here",
                              sensitive=False)
        g.add(calls)
        col.append(g)

        self.go = Gtk.Button(label="Export", css_classes=["pill", "suggested-action"], halign=Gtk.Align.CENTER)
        self.go.connect("clicked", self.start)
        col.append(self.go)
        self.prog_rev, self.p_title, self.p_line, self.p_bar = progress_card(
            "mail-send", lambda: setattr(self, "cancel", True))
        col.append(self.prog_rev)
        self.result = Adw.PreferencesGroup(title="Exported")
        self.result.set_visible(False)
        col.append(self.result)
        col.append(Gtk.Label(wrap=True, xalign=0, css_classes=["caption", "dim-label"], label=(
            "Each chat becomes a web page (open it in any browser) and a plain-text file. The files are saved in "
            "~/iPhone Exports and stay on this PC — nothing is uploaded.")))

    def start(self, *_):
        self.cancel = False
        self.go.set_sensitive(False)
        for w in (self.sw_msgs, self.sw_wa, self.sw_contacts):
            w.set_sensitive(False)
        show_card(self.prog_rev, True)
        self.p_title.set_label("Exporting…")
        self.spinner.start()
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H.%M")
        out = os.path.join(EXPORT_DIR, f"{safe_name(self.backup[1])} {stamp}")
        in_thread(self._work, out, self.sw_msgs.get_active(), self.sw_wa.get_active(), self.sw_contacts.get_active())

    def _work(self, out, do_msgs, do_wa, do_contacts):
        res, err = [], None
        try:
            bf = BackupFiles(self.backup[0])
            contacts = read_contacts(bf)
            name_of = contact_lookup(contacts)
            os.makedirs(out, exist_ok=True)

            def prog(label):
                return lambda f, t: ui(self._progress, label, f, t)
            if do_contacts:
                n = write_contacts(contacts, out)
                res.append(("Contacts", f"{n} contacts", os.path.join(out, "Contacts.vcf")))
            if do_msgs and not self.cancel:
                c, m = export_messages(bf, name_of, os.path.join(out, "Messages"), prog("Messages"),
                                       lambda: self.cancel)
                res.append(("Messages", f"{c} chats · {m:,} messages", os.path.join(out, "Messages", "index.html")))
            if do_wa and not self.cancel:
                c, m = export_whatsapp(bf, name_of, os.path.join(out, "WhatsApp"), prog("WhatsApp"),
                                       lambda: self.cancel)
                if c:
                    res.append(("WhatsApp", f"{c} chats · {m:,} messages",
                                os.path.join(out, "WhatsApp", "index.html")))
                else:
                    res.append(("WhatsApp", "No WhatsApp chats in this backup", None))
        except Exception as e:  # noqa: BLE001 - shown to the user
            err = str(e)
        ui(self._done, out, res, err)

    def _progress(self, label, frac, title):
        self.p_title.set_label(f"Exporting {label}…")
        self.p_line.set_label(title)
        self.p_bar.set_fraction(frac)

    def _done(self, out, res, err):
        self.spinner.stop()
        show_card(self.prog_rev, False)
        self.go.set_sensitive(True)
        for w in (self.sw_msgs, self.sw_wa, self.sw_contacts):
            w.set_sensitive(True)
        if err:
            toast(self, f"Export failed: {err[:100]}")
            return
        self.result.set_visible(True)
        size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(out) for f in fs)
        self.result.set_description(f"~/{os.path.relpath(out, os.path.expanduser('~'))} · {human_size(size)}")
        for title, sub, target in res:
            r = Adw.ActionRow(title=title, subtitle=sub, use_markup=False, activatable=bool(target))
            if target:
                r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                r.connect("activated", lambda _r, t=target: open_file(t))
            self.result.add(r)
        open_folder(out)
        toast(self, "✔ Export finished" if not self.cancel else "Stopped — partial export saved")


def open_file(path):
    from gi.repository import Gio
    Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
