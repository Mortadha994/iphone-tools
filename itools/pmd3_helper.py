"""Runs inside pymobiledevice3's own Python (its pipx venv) and prints JSON lines for the GTK app.

    python pmd3_helper.py <udid> apps [--sizes]          -> one JSON object per user app
    python pmd3_helper.py <udid> icons <out_dir> <bundle>... -> saves <out_dir>/<bundle>.png, prints each bundle
    python pmd3_helper.py <udid> uninstall <bundle>      -> progress lines, then {"done": true}

Keeping one device connection for a whole batch is much faster than one CLI call per app.
"""

import asyncio
import json
import os
import sys

from pymobiledevice3.lockdown import create_using_usbmux

APP_ATTRS = ["CFBundleIdentifier", "CFBundleDisplayName", "CFBundleName", "CFBundleShortVersionString",
             "StaticDiskUsage", "DynamicDiskUsage", "ApplicationType", "SignerIdentity", "IsAppClip"]


def emit(obj):
    print(json.dumps(obj), flush=True)


async def apps(ld, sizes):
    """Sizes make the phone add up every app's files, which takes ~40 s, so the GTK app asks twice."""
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    attrs = APP_ATTRS if sizes else [a for a in APP_ATTRS if "DiskUsage" not in a]
    async with InstallationProxyService(lockdown=ld) as ip:
        res = await ip.browse(options={"ApplicationType": "User", "ReturnAttributes": attrs}, attributes=attrs)
    for a in res:
        emit({k: a.get(k) for k in APP_ATTRS})


async def icons(ld, out_dir, bundles):
    from pymobiledevice3.services.springboard import SpringBoardServicesService
    os.makedirs(out_dir, exist_ok=True)
    async with SpringBoardServicesService(lockdown=ld) as sb:
        for b in bundles:
            try:
                data = await sb.get_icon_pngdata(b)
            except Exception as e:  # noqa: BLE001 - keep going with the other icons
                emit({"bundle": b, "error": str(e)})
                continue
            path = os.path.join(out_dir, b + ".png")
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
            emit({"bundle": b})


async def uninstall(ld, bundle):
    from pymobiledevice3.services.installation_proxy import InstallationProxyService

    def handler(progress, *_):
        emit({"progress": progress})
    async with InstallationProxyService(lockdown=ld) as ip:
        await ip.uninstall(bundle, handler=handler)
    emit({"done": True})


async def main():
    udid, cmd, args = sys.argv[1], sys.argv[2], sys.argv[3:]
    ld = await create_using_usbmux(serial=udid, autopair=False)
    try:
        if cmd == "apps":
            await apps(ld, sizes="--sizes" in args)
        elif cmd == "icons":
            await icons(ld, args[0], args[1:])
        elif cmd == "uninstall":
            await uninstall(ld, args[0])
        else:
            raise SystemExit(f"unknown command {cmd}")
    finally:
        close = getattr(ld, "close", None)
        if close:
            r = close()
            if asyncio.iscoroutine(r):
                await r


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:  # noqa: BLE001 - report to the GTK app
        emit({"error": f"{type(e).__name__}: {e}"})
        sys.exit(1)
