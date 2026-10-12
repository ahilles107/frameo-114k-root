#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
# Turn a rooted Frameo 114K into a plain Android 6.0.1 tablet. Every step is reversible.
# Usage: scripts/tablet-setup.sh --serial 192.0.2.10:5555 --apks DIR [--download]
# See docs/android-tablet-setup.md.
set -eu

serial=
apks=
download=0
while [ $# -gt 0 ]; do
    case "$1" in
        --serial) serial=$2; shift 2 ;;
        --apks) apks=$2; shift 2 ;;
        --download) download=1; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
[ -n "$serial" ] && [ -n "$apks" ] || { echo "Usage: $0 --serial HOST:PORT --apks DIR [--download]" >&2; exit 2; }

# file|sha256|url. Hashes were checked against the F-Droid index and Mozilla's release signer.
APK_LIST='fr.neamar.kiss_224.apk|da6ab0b1219ad3b5ee573698523fb15d60a918083e0843f94a03c1b12e1098c9|https://f-droid.org/repo/fr.neamar.kiss_224.apk
fenix-143.0.4.multi.android-armeabi-v7a.apk|af560738627d4efc9ace75e708fc48aad6a24c78ef43a89daca27e16ff3829f8|https://archive.mozilla.org/pub/fenix/releases/143.0.4/android/fenix-143.0.4-android-armeabi-v7a/fenix-143.0.4.multi.android-armeabi-v7a.apk
org.fdroid.fdroid_1023052.apk|985f5181d48bb6bafd54083a048b391271e0ab28385881cc41294fb01a222762|https://f-droid.org/repo/org.fdroid.fdroid_1023052.apk
com.aurora.store_76.apk|fd9c75d90d0f4a7c132b9b4a5a2cf1992a45e03b8d8ff988b7dcfbc0db2c4d11|https://f-droid.org/repo/com.aurora.store_76.apk'
DISABLE='net.frameo.frame com.adups.fota com.along.factorytest com.softwinner.dragonaging com.softwinner.dragonfire com.softwinner.dragonphone com.android.agingtest'

run() { adb -s "$serial" shell "$@" | tr -d '\r'; }

[ "$(run id -u)" = 0 ] || { echo "Root ADB is required. Install the boot patch first." >&2; exit 1; }
[ "$(run getprop ro.build.version.sdk)" = 23 ] || { echo "Expected Android 6.0.1 (API 23)." >&2; exit 1; }

mkdir -p "$apks"
echo "$APK_LIST" | while IFS='|' read -r file sum url; do
    path="$apks/$file"
    if [ ! -f "$path" ] && [ "$download" = 1 ]; then
        curl -fL --proto '=https' -o "$path.partial" "$url" && mv "$path.partial" "$path"
    fi
    [ -f "$path" ] || { echo "Missing $path (use --download)." >&2; exit 1; }
    [ "$(shasum -a 256 "$path" | cut -d' ' -f1)" = "$sum" ] || { echo "Checksum mismatch: $path" >&2; exit 1; }
    echo "Installing $file"
    adb -s "$serial" install -r "$path" | tail -1
done

run pm enable com.android.systemui
if ! run grep -qx qemu.hw.mainkeys=0 /system/build.prop; then
    run 'mount -o remount,rw /system && { [ -f /system/build.prop.frameo-orig ] || cp -p /system/build.prop /system/build.prop.frameo-orig; } && echo qemu.hw.mainkeys=0 >> /system/build.prop && sync; mount -o remount,ro /system'
fi
run grep -qx qemu.hw.mainkeys=0 /system/build.prop || { echo "build.prop change failed." >&2; exit 1; }

for package in $DISABLE; do
    run am force-stop "$package"
    run pm disable "$package"
done
# Package Manager writes restrictions lazily; rebooting too early loses them.
for _ in $(seq 1 30); do
    missing=0
    for package in $DISABLE; do
        run grep -q "<pkg name=\"$package\"[^>]*enabled=\"2\"" /data/system/users/0/package-restrictions.xml || missing=1
    done
    [ "$missing" = 0 ] && break
    sleep 2
done
[ "$missing" = 0 ] || { echo "Disabled state not saved yet. Wait, then reboot manually." >&2; exit 1; }

cat <<EOF
Done. Reboot with: adb -s $serial reboot
To revert:
  adb -s $serial shell 'for p in $DISABLE; do pm enable \$p; done'
  adb -s $serial shell 'mount -o remount,rw /system && cp -p /system/build.prop.frameo-orig /system/build.prop && sync; mount -o remount,ro /system'
  adb -s $serial shell pm disable com.android.systemui
EOF
