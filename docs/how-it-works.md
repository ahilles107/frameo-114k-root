# How it works

## Boot path

The Allwinner A33 boot ROM tries the SD card before the internal eMMC. It loads an SPL (secondary
program loader) from byte 8192 of the card. Each stage here is a U-Boot v2026.07 image built for
the A33 with the Q8 tablet memory settings, a 408 MHz CPU clock and no PMIC programming.

The device tree enables only:

- `mmc0`: the external SD slot, 4-bit, 25 MHz.
- `mmc2`: the internal eMMC, 8-bit, 25 MHz, as logical device 1.
- The R_UART serial console.

Display, USB, network and SPI are disabled. The screen stays dark while a stage runs. The image
runs one boot command and then stops. It never starts Android.

## SD card layout

| Bytes | Use |
| --- | --- |
| 0 to 511 | MBR of the card, never written |
| 8192 to below 1 MiB | Stage image (SPL and U-Boot) |
| 1 MiB, 512 KiB | Probe sample 0: eMMC sector 0 |
| 2 MiB, 512 KiB | Probe sample 1: eMMC sector 0xa000, the vendor partition table |
| 3 MiB, 512 bytes | Result sector: a 16-byte challenge, status, exported variables |
| 4 MiB or later | First partition (ExFAT). Backup chunks and install images live here |

The host tool saves the card's first 4 MiB on `sd init` and before every write. It only writes
bytes 8192 through 3 MiB + 511. It reads everything back and restores the previous bytes if the
readback differs. `sd restore` puts the original bytes back.

## Stages

| Stage | Reads | Writes to eMMC |
| --- | --- | --- |
| `probe` | eMMC sectors 0 and 0xa000 | Nothing |
| `backup` | eMMC boot areas 1 and 2, user area sectors 0 to 0x411fff | Nothing |
| `install` | Boot partition, both images from SD | Boot partition only |

Results:

- Probe: `completed`, with `probe0` and `probe1` set to `ok`, `read-failed` or `sd-write-failed`,
  and CRC32 values that the host checks.
- Backup: `device-reported-complete`, `failed` or `started-not-completed`, with `backup_state`
  and `backup_stage` naming the step that failed.
- Install: `verified-original`, `verified-patched`, `applied-verified`, `restored-verified`,
  `already-desired`, `image-refused`, `device-refused`, `current-refused`, `read-failed`,
  `failure-original-restored` or `recovery-failed`.

## The write guard

A patch to U-Boot's `sunxi_mmc.c` driver checks every command before it reaches the hardware
(`uboot/probe_guard.h`):

- The SD controller (controller 0) is not restricted.
- On the eMMC, every command that writes data is refused.
- Only read, status and selection commands are allowed. `SWITCH` may only select the user area
  or, in the backup image, the two boot areas. It cannot change boot configuration bits.

The install image adds one exception (`boot_write_allowed` in `uboot/boot_install_core.h`). The
exception allows `WRITE_BLOCK` and `WRITE_MULTIPLE_BLOCK` on controller 2, in the user area,
inside sectors 0x2a000 to 0x31fff only. It also needs a flag that the installer sets for the
duration of one boot write. Erase and permanent configuration commands stay blocked. The rule is
compiled into the driver, below the command interpreter.

## Install transaction

`uboot/frameoboot.c`:

1. Checks the 16-byte challenge, the mode (`A` apply, `R` rollback, `V` verify) and `pending`.
2. Writes `running` to the result sector.
3. Loads `/frameo-boot-v1/original.img` and `patched.img` from the SD card and checks both SHA-256
   values against the values compiled into the image.
4. Checks the eMMC identity: CID, user area size, sector count in EXT_CSD, 4 MiB boot areas,
   512-byte blocks, user area selected and write cache off. These values come from your backup.
5. Reads the 16 MiB boot partition.
   - Apply needs the original image exactly.
   - Rollback accepts the patched image, the original, or a byte-wise mix of the two.
6. Writes the target image, reads all 16 MiB back and compares.
7. If the write or the comparison fails, writes the original image, reads it back and reports
   `failure-original-restored` or `recovery-failed`.

The host tests compile this file against stubs and run every path, including failed writes and
readback errors (`tests/test_native.py`).

## The boot image patch

`frameo114k/bootimg.py` unpacks the gzip cpio ramdisk. It requires the archive to repack to the
exact original bytes before it changes anything. It changes:

- `default.prop`: adds `ro.adb.secure=1` and `service.adb.tcp.port=5555`.
- `init.rc`: starts adbd on boot and again at `sys.boot_completed=1`.
- `sbin/adbd`: two bytes, see below.
- `/adb_keys`: adds your RSA public key, mode 0644.

It then recalculates the Android image ID and checks that only these members changed.

Stock Android 6 adbd drops to the `shell` user. In a `user` build it is compiled without
`ALLOW_ADBD_ROOT`, so `should_drop_privileges` always returns true and properties cannot change
that. adbd then removes capabilities and calls `setgid(2000)` and `setuid(2000)`. See
[adb_main.cpp](https://android.googlesource.com/platform/system/core/+/refs/tags/android-6.0.1_r81/adb/adb_main.cpp)
and [Android.mk](https://android.googlesource.com/platform/system/core/+/refs/tags/android-6.0.1_r81/adb/Android.mk).

In the stock binary (SHA-256 `dc3f61ad...`), the Thumb instruction at file offset 0xf9c starts that
sequence. The patch replaces it, `1720` (`movs r0, #23`), with `35e0`, a branch over the
capability loop and both ID calls. The setup before the drop and all authentication code stay
the same. adbd keeps root and still requires a key from `/adb_keys`.

The adbd binary is not distributed here. The patch is applied to the binary inside your own boot
image, and only if its hash matches.
