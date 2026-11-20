# iPhone Tools

A **3uTools-style iPhone manager for Linux**, built with GTK4 + libadwaita on top of
[libimobiledevice](https://libimobiledevice.org/), [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)
and [UxPlay](https://github.com/FDH2/UxPlay).

![iPhone Tools](docs/screenshot.png)

| Add music | Screen mirroring |
|---|---|
| ![Add music](docs/add-music.png) | ![Screen mirroring](docs/mirror.png) |

## Features

- **Device overview**: name, model, iOS version and capacity, detected automatically when you plug the phone in
- **Battery**: charge level, **battery health %** (max vs design capacity in mAh), charge cycles and temperature
- **Hardware check** (like 3uTools' verification report): the serial number each part reports (battery, screen, cameras, Face ID parts, light sensor) plus logic board serial, ECID, IMEI(s), Wi‑Fi/Bluetooth and modem info. A part with no serial is flagged, which usually means it was replaced. **Copy report** puts it all on the clipboard
- **Storage**: used / free, calculated like *Settings → General → iPhone Storage*, with an iOS / Photos / Apps breakdown
- **Add music**: drag & drop songs or a folder (MP3, M4A, AAC, WAV, FLAC…) into a music app on the iPhone (Spotify *Local Files*, VLC, …), and see or remove the songs already there
- **Screen mirroring**: the iPhone screen **live inside the app** (AirPlay over Wi‑Fi) in an iPhone-shaped frame, with sound, auto-rotation, fullscreen and **screenshots**
- **Backup**: full first backup, then **incremental** (only changes), with progress
- **Quick actions**: open photos and app files, rename the iPhone, copy all info, restart or shut down the phone

**Tools**

- **Import photos**: copies the Camera Roll to `~/Pictures/iPhone`, one folder per month, keeping the date each photo was taken. Photos already imported are skipped, even if you moved them since. Optional HEIC → JPG
- **Apps**: every app you installed with its icon, version, app size and data size, biggest first, with search and **uninstall**
- **Battery history**: health and charge cycles are saved each day the iPhone is connected, then charted, with wear per month and when health will reach 80 %
- **Crash reports & live log**: which apps crashed and why, in plain words, plus low-memory and low-battery events; the iPhone's live system log with filter, pause and save
- **Videos to iPhone**: drop any video (MKV, AVI, WEBM, MP4…); it's converted to an iPhone-friendly MP4 on this PC (if needed) and sent to VLC
- **Backup browser**: look inside a backup app by app and copy any app's files (or photos, or anything) out of it. Works without the iPhone connected
- **Export chats**: SMS/iMessage and WhatsApp chats from the latest backup become readable web pages and text files (with photos), and contacts become a vCard and a CSV
- **Connection repair**: detects when Linux's iPhone service (usbmuxd) got stuck and fixes it with one click
- **Animations**: ring gauges and counters, growing storage bar, slide-in sections, hover effects

## Quick start (Ubuntu 24.04 or newer)

```bash
# 1. dependencies (everything, including the optional extras)
sudo apt install -y python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0 \
    libimobiledevice-utils usbmuxd ifuse uxplay gstreamer1.0-plugins-bad pipx \
    gstreamer1.0-plugins-ugly gstreamer1.0-libav libheif-plugin-libde265
pipx install pymobiledevice3 && pipx ensurepath

# 2. the app
git clone https://github.com/Mortadha994/iphone-tools.git
cd iphone-tools
./install.sh
```

Open **iPhone Tools** from the apps menu, plug in your iPhone, unlock it and tap **Trust**.

`install.sh` checks every dependency first. If something required is missing, it prints the exact
`sudo apt install …` line to run. Optional extras are only suggested:

| Feature | Needs |
|---|---|
| The app (info, battery, storage, music, files, rename, restart) | `python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0 libimobiledevice-utils usbmuxd ifuse` |
| Screen mirroring | `uxplay gstreamer1.0-plugins-bad` |
| Backups on iOS 17 and newer, Apps tool | `pymobiledevice3` (via `pipx`) |
| HEIC photos → JPG when importing | `libheif-plugin-libde265` |
| Videos to iPhone (converting) | `gstreamer1.0-plugins-ugly gstreamer1.0-libav` (H.264 and AAC encoders) |

Requires GTK 4.14+ and libadwaita 1.5+ (Ubuntu 24.04 / GNOME 46 or newer).

## Update / uninstall

```bash
cd iphone-tools
git pull && ./install.sh     # update
./install.sh --uninstall     # remove (backups and screenshots are kept)
```

## Using it

- **Screen mirroring**: click **Mirror screen**. On the iPhone, open **Control Center → Screen Mirroring → “iPhone Tools”**. The iPhone and the PC must be on the same Wi‑Fi. If “iPhone Tools” isn't listed yet, wait 5–10 s.
- **Add music**: songs can't go into the built-in **Apple Music** app from Linux (that needs Apple's private ATC sync service). They go into a music app that accepts files, such as **Spotify**: on the iPhone, open *Spotify → Settings → Local files* and turn on **Show audio files from this device**. They then appear in *Your Library → Local Files*.
- **Hardware check**: shows what each part reports about itself. 3uTools also compares serials with Apple's factory records, which other apps can't access. For Apple's own verdict, open *Settings → General → About → Parts and Service History* on the iPhone.
- **Import photos**: nothing is deleted from the iPhone. To get JPG instead of HEIC, install `libheif-plugin-libde265` and turn on *Convert HEIC photos to JPG*.
- **Apps**: app sizes take the iPhone 1–2 minutes to add up, so they appear after the list. Deleting an app here is the same as *Delete App* on the iPhone.
- **Battery history** starts the first time you open the new version; a point is added each day you plug the iPhone in.
- **Videos to iPhone**: install **VLC** (free) from the App Store first. iOS doesn't let a computer add videos to the Photos app.
- **Export chats** reads your latest backup, so click **Back up** first to include recent messages. Call history isn't available: iOS only includes it in encrypted backups. Exports are saved in `~/iPhone Exports` and stay on your PC.
- **Backups** are saved **unencrypted** to `~/iPhone Backups`. Keep them private.

## Troubleshooting

| Problem | Fix |
|---|---|
| “Connection problem” / the phone isn't detected | Click **Repair connection** in the app (or run `sudo systemctl restart usbmuxd`), unlock the iPhone and replug it |
| “Unlock your iPhone” | Unlock it and tap **Trust**. Unlock the iPhone *before* plugging it in |
| Mirroring plays sound but no picture | Update the app (`git pull && ./install.sh`). Receiver messages are in `~/.cache/iphone-tools/uxplay.log` |
| “Another mirroring receiver is running” | Close the other UxPlay window or run `pkill uxplay` |
| Backup stays at 0 % | Install pymobiledevice3 (see above). libimobiledevice 1.3's backup hangs on iOS 26 |

## How it works

`iphone_tools.py` is the main window; each tool is a module in `itools/` (shared helpers in `itools/common.py`).
Device data comes from the `idevice*` command-line tools, part serial numbers from the IORegistry
(`idevicediagnostics ioregentry`), music, photos and files from `ifuse`, backups from `pymobiledevice3`.
`itools/pmd3_helper.py` runs inside pymobiledevice3's own Python and streams JSON, so a whole batch (all apps, all
icons) uses one device connection. Videos are converted in-process with GStreamer. The backup browser and the chat
export read the backup's `Manifest.db` and the SQLite databases inside it directly. Mirroring runs `uxplay` as an
AirPlay receiver that hands decoded frames to the app over a private `127.0.0.1` socket.
