# Frameo 114K root

Root access for the Frameo 114K digital photo frame, without USB and without opening the case.

Everything runs from an SD card. The frame's Allwinner A33 boots the SD card before its internal
eMMC, so a small U-Boot image on the card can back up the firmware and then replace only the
16 MiB boot partition. The patched boot image gives you **authenticated root ADB over Wi-Fi**.
After that, [docs/android-tablet-setup.md](docs/android-tablet-setup.md) turns the frame into a
plain Android tablet with a launcher, a browser and an app store.

> **Warning.** This writes to the internal storage of your frame. It worked on one unit. It can
> leave a frame that does not boot. You need a spare SD card and some patience. You use it at
> your own risk.

## Supported device

| Item | Value |
| --- | --- |
| Product | Frameo 114K by Shenzhen Kejinming, FCC ID 2ATFT-102K |
| Board | Allwinner A33 (sun8i), marked M33-V4.0 |
| Android | 6.0.1, API 23, build `astar_xr819-user MOB30R` |
| Firmware | `114119_HK9365_SWM0810_frameo_v1.29.13_20260114` (Settings, About) |

The patch step refuses any other boot image. To add another firmware version, see
[docs/other-firmware.md](docs/other-firmware.md). Hardware details are in
[docs/hardware.md](docs/hardware.md).

## What changes

- Only the boot partition (eMMC sectors 172032 through 204799) is written.
- The boot ramdisk gets TCP ADB on port 5555, a started adbd, your ADB public key, and a two-byte
  adbd patch that keeps root. See [docs/how-it-works.md](docs/how-it-works.md).
- ADB authentication stays on. Only your key is accepted. The kernel, system partition and
  SELinux policy are not changed.
- The original boot image stays in your work directory and on the SD card for rollback.

## What was verified

| Step | Status |
| --- | --- |
| SD boot, read-only probe, firmware backup | Ran on hardware |
| Boot patch and install (`install-apply`) | Ran on hardware: `applied-verified`, then Android booted with root ADB |
| Install rollback (`install-rollback`) | **Not run on hardware.** Covered by host tests only |
| Power loss during install | **Not tested.** It can leave Android unable to boot |
| Backup scope | Firmware only. User data (`UDISK`) and RPMB are **not** backed up |

This repository is a cleaned-up version of the tools used on that unit. The device-side code is
the same apart from per-unit values, which now come from your own backup. The backup's model
check (`itest ... -gt`) and the cleaned-up host tools have not run on hardware yet. A regression
check reproduced the hardware-verified patched boot image byte for byte.

## Requirements

- macOS (the SD card commands use `diskutil`). Linux is not supported yet.
- Docker, Python 3.11 or later, `adb` (Android platform tools).
- A spare SD card of 8 GB or more and a card reader.
- The frame's own power adapter.

## Quick start

Run everything from the repository root. Files go into `./work`; use `--workdir` or
`FRAMEO_WORKDIR` to move it. Keep that directory: it holds your firmware backup.

### 1. Prepare the SD card

Format the card with the [SD Card Formatter](https://www.sdcard.org/downloads/formatter/) from the
SD Association, using ExFAT (cards over 32 GB format as ExFAT by default). The first partition
must start at 4 MiB or later, and the formatter does that. Find the device name:

```sh
diskutil list external
```

The examples below use `/dev/disk4`. Use your own. The tools refuse non-removable disks and
cards with the wrong layout, but check the name yourself anyway.

### 2. Build the images

```sh
./frameo build probe
./frameo build backup
```

The first build downloads U-Boot v2026.07 and checks its SHA-256.

### 3. Record the card

```sh
sudo ./frameo sd init --disk /dev/disk4
```

This saves the first 4 MiB of the card. Later commands check that the same card is inserted.

### 4. Probe (optional, recommended)

```sh
sudo ./frameo sd write probe --disk /dev/disk4
```

Unplug the frame. Insert the card. Plug the frame in and wait 60 seconds. The screen stays dark.
Unplug the frame, put the card back into the Mac, then:

```sh
sudo ./frameo sd result --disk /dev/disk4
```

You want `"state": "completed"`, both probes `ok`, and `"supported_layout": true`.

### 5. Back up the firmware

```sh
sudo ./frameo sd write backup --disk /dev/disk4
```

Boot the frame from the card as before and wait 30 minutes. The backup copies 2092 MiB at about
1.7 MiB/s. Then:

```sh
sudo ./frameo sd result --disk /dev/disk4
./frameo collect --disk /dev/disk4
```

If the result is not `device-reported-complete`, run `sd write backup` again and boot again. The
backup resumes: it compares chunks already on the card and copies the rest. `collect` runs
without sudo. It checks every chunk's SHA-256, copies the backup to `work/backup`, and extracts
`boot.img`, `system.img`, `recovery.img` and the other firmware partitions to `work/firmware`.

### 6. Patch the boot image

```sh
adb devices               # creates ~/.android/adbkey.pub on first use
./frameo patch            # or: ./frameo patch --adb-key path/to/adbkey.pub
./frameo build install
```

The install image contains your eMMC identity (CID) and both boot image hashes. It only works on
your frame.

### 7. Check, then install

First run the check. It reads the boot partition and writes nothing:

```sh
sudo ./frameo sd write install-verify --disk /dev/disk4
# boot the frame from the card, wait 5 minutes, unplug, card back
sudo ./frameo sd result --disk /dev/disk4    # expect "verified-original"
```

Then install:

```sh
sudo ./frameo sd write install-apply --disk /dev/disk4
# boot the frame from the card, wait 5 minutes, do not interrupt power
sudo ./frameo sd result --disk /dev/disk4    # expect "applied-verified"
sudo ./frameo sd restore --disk /dev/disk4   # return the card to its original state
```

If the write or readback fails, the installer tries to restore the original boot partition
itself and reports `failure-original-restored` or `recovery-failed`.

### 8. Connect

Remove the card and power the frame on. Find its IP address in your router, then:

```sh
adb connect 192.0.2.10:5555
adb -s 192.0.2.10:5555 shell id       # uid=0(root)
```

Next: [docs/android-tablet-setup.md](docs/android-tablet-setup.md).

## Rollback

```sh
sudo ./frameo sd write install-rollback --disk /dev/disk4
# boot the frame from the card, wait 5 minutes
sudo ./frameo sd result --disk /dev/disk4    # expect "restored-verified"
```

Rollback accepts the patched image, the original, or a mix of the two after an interrupted write.
It refuses anything else. Remember that rollback has not run on hardware.

## More

- [How it works](docs/how-it-works.md): SD layout, write guard, install transaction, adbd patch.
- [Troubleshooting](docs/troubleshooting.md).
- [Hardware notes](docs/hardware.md).
- Tests: `python3 -m unittest discover -s tests -t .` (needs a C compiler).

## Credits

- Wes Bos, [photo-frame-dashboard](https://github.com/wesbos/photo-frame-dashboard): the
  authenticated Wi-Fi ADB approach and A33 frame notes.
- divinehawk, [Pastigio frame ADB via FEL](https://divinehawk.github.io/2026/07/08/pastigio-frame-adb-fel-mode.html).
- [linux-sunxi](https://linux-sunxi.org/) and [U-Boot](https://docs.u-boot.org/en/latest/board/allwinner/sunxi.html).

## Contributing

Hardware reports and fixes are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Copyright (C) 2026 Pawel Mikolajczuk.

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 2 of the
License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY. See
[LICENSE](LICENSE).

The C sources are compiled into U-Boot, which is also GPL-2.0+. Frameo is a trademark of its
owner. This project is not affiliated with Frameo or the frame's manufacturer.
