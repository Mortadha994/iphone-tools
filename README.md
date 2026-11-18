# iPhone Tools

A small **3uTools-style iPhone manager for Linux**, built with GTK4 + libadwaita on top of [libimobiledevice](https://libimobiledevice.org/).

![iPhone Tools screenshot](docs/screenshot.png)

## Features

- **Device overview** – name, model, iOS version and capacity, detected automatically when you plug the phone in
- **Battery** – charge level, **battery health %** (max vs design capacity in mAh), charge cycles and temperature
- **Storage** – used / free, calculated like *Settings → General → iPhone Storage*, with an iOS / Photos / Apps breakdown
- **Quick actions** – open photos and app files, full **backup** with progress, rename the iPhone, copy all info, restart or shut down the phone
- **Animations** – animated ring gauges and counters, growing storage bar, slide-in sections, hover effects

## Requirements

- Linux with GNOME (tested on Ubuntu 24.04, GNOME 46)
- Python 3 with PyGObject, GTK 4.14+ and libadwaita 1.5+ (preinstalled on Ubuntu 24.04)
- libimobiledevice tools:

```bash
sudo apt install libimobiledevice-utils usbmuxd ifuse
```

## Install

```bash
git clone https://github.com/Mortadha994/iphone-tools.git
cd iphone-tools
./install.sh
```

Then open **iPhone Tools** from the apps menu. Plug in your iPhone, unlock it and tap **Trust**.

## Notes

- Screenshots of the phone are not supported: iOS 17+ blocks the screenshot service for libimobiledevice 1.3.
- Backups are saved unencrypted to `~/iPhone Backups`.
