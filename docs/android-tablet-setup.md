# Turn the frame into a tablet

After rooting, the frame is a 1280 x 800 Android 6.0.1 tablet with 1 GB RAM. These steps add a
launcher, a navigation bar, a browser and app stores. Each step can be undone. They were done on
one unit and then checked after a reboot.

`scripts/tablet-setup.sh --serial <ip>:5555 --apks ./apks --download` does all of it. The steps
below describe what it does.

## Limits

- No Android newer than 6.0.1 exists for this board. See [hardware.md](hardware.md).
- Google Play is not an option. Google Play services needs Android 7.0 or later since July 2026
  ([Google Play Help](https://support.google.com/googleplay/answer/9037938)).
- System WebView 106.0.5249.126 is the last version for API 23. Apps that use WebView get that
  engine.
- Firefox 143.0.4 is the last Firefox for Android 5 to 7
  ([Mozilla](https://blog.mozilla.org/futurereleases/2025/09/15/raising-the-minimum-android-version-for-firefox/)).
  It gets no more security updates. Treat the frame as a home device, not a general browser for
  untrusted sites.
- Many current apps need Android 7 or later. Aurora Store shows only the apps that still support
  this version.

## Apps

| App | Version | Why | Source and check |
| --- | --- | --- | --- |
| KISS launcher | 3.26.0 | Maintained, minSdk 21, light | F-Droid; SHA-256 from the F-Droid index |
| Firefox | 143.0.4 armeabi-v7a | Current web engine on this device | archive.mozilla.org; signer SHA-256 `a78b62a5165b4494b2fead9e76a280d22d937fee6251aece599446b2ea319b04` |
| F-Droid | 1.23.2 | Last client for API 23 | F-Droid; signer SHA-256 `43238d512c1e5eb2d6569f4a3afbf5523418b82e0a3ed1552770abb9a9c9ccab` |
| Aurora Store | 4.8.4 | Anonymous Play Store client, minSdk 23 | F-Droid; SHA-256 from the F-Droid index |

The script pins the SHA-256 of each file. To check a newer download yourself:

```sh
apksigner verify --print-certs app.apk
```

Compare the result with the F-Droid index (`https://f-droid.org/repo/index-v1.json`) or with
Mozilla's signer above.

## Steps

1. Install the APKs: `adb -s <ip>:5555 install <file>.apk`. Firefox takes a few minutes, because
   Android 6 compiles it on install.
2. Enable SystemUI: `pm enable com.android.systemui`. The firmware disables it.
3. Show the navigation bar. The firmware sets `config_showNavigationBar` to false. Override it in
   `/system/build.prop` and keep a copy:

   ```sh
   mount -o remount,rw /system
   cp -p /system/build.prop /system/build.prop.frameo-orig
   echo qemu.hw.mainkeys=0 >> /system/build.prop
   sync; mount -o remount,ro /system
   ```

4. Disable Frameo and the vendor apps with `pm disable <package>`:
   - `net.frameo.frame`
   - `com.adups.fota`
   - `com.along.factorytest`
   - `com.softwinner.dragonaging`
   - `com.softwinner.dragonfire`
   - `com.softwinner.dragonphone`
   - `com.android.agingtest`

   KISS becomes the home screen. Nothing is deleted from `/system`.
5. Wait until `/data/system/users/0/package-restrictions.xml` shows `enabled="2"` for each
   disabled package. Package Manager writes the file late, and a reboot before that undoes step 4.
6. Reboot.

After the reboot you should see KISS with Back, Home and Recents at the bottom. Frameo should not
be running (`ps | grep frameo`).

## Known gaps

- The status bar is still 0 pixels tall (`status_bar_height` is 0dp in the firmware), so you
  cannot pull down notifications. Fixing it needs a resource overlay in `/system`.
- Firefox used about 185 MB (PSS) on a single web app page. With 1 GB of RAM, keep few apps open.

## Undo

```sh
adb shell 'for p in net.frameo.frame com.adups.fota com.along.factorytest com.softwinner.dragonaging com.softwinner.dragonfire com.softwinner.dragonphone com.android.agingtest; do pm enable $p; done'
adb shell 'mount -o remount,rw /system && cp -p /system/build.prop.frameo-orig /system/build.prop && sync; mount -o remount,ro /system'
adb shell pm disable com.android.systemui
adb uninstall fr.neamar.kiss   # and the other apps, if you want
```
