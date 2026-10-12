# Troubleshooting

## The screen stays dark

That is expected for every stage. The stage images do not enable the display. Wait the stated
time, unplug the frame, and read the result on the Mac.

## `sd result` says `not-observed`

The frame did not run the stage. Check that:

- The frame was unplugged before you inserted the card. The boot ROM reads the card only at power on.
- The card is fully inserted.
- You used the frame's own power adapter.

If it still fails, try another card. Some cards do not work with the A33 boot ROM.

## USB does not work

On the tested unit, USB never enumerated in normal mode or FEL mode. These tools do not need USB.
Use the SD card path and Wi-Fi ADB.

## The backup failed

Read `backup_stage` in the result:

- `data-write`, `digest-write` or `...-readback`: the SD card filesystem write failed. This
  happened during large backups on the tested card. Run `sd write backup` again and boot again.
  The backup re-reads each chunk already on the card, compares it with the eMMC, and continues
  from the first missing chunk. A different card can help.
- `internal-select` or `internal-read`: the eMMC read failed. Do not continue to the install.
- `device-refused`: the internal storage geometry does not match a Frameo 114K.
- `metadata-mismatch`: the card holds a backup from another frame. Use an empty card.

## macOS `._` files on the card

macOS writes AppleDouble metadata files such as `._patched.img` next to files it copies. The
install staging accepts them only if they match an expected image name and have the AppleDouble
header. Any other unexpected file in `/frameo-boot-v1` stops the staging.

## The install reported `running`

The installer started but did not finish. This could be a power cut during the write. Do not boot
Android first. Run `install-verify` to see what the boot partition holds. Then run
`install-rollback` if it is not one of the two expected images. Rollback refuses any content that
is not a mix of the original and patched images.

## `recovery-failed`

The installer could not put the original boot image back. Android will probably not boot. The SD
boot path still works, because it does not depend on the eMMC. Keep your `work/` directory and
open an issue with the result JSON.

## `adb connect` is refused or asks for authorization

- Only the key you patched in is accepted, from `~/.android/adbkey` on the Mac that ran `patch`.
- The frame must be on Wi-Fi. Set up Wi-Fi in Frameo before you install, or in Android Settings after.
- After a reboot, macOS adb sometimes needs `adb kill-server` before it connects again.

## Linux

The SD card commands use macOS `diskutil`. Contributions for Linux (`lsblk`, `udisksctl`) are
welcome. `build`, `patch` and the tests work on Linux.
