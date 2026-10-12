# Adding another firmware version

`frameo114k/bootimg.py` patches only boot images listed in `KNOWN_FIRMWARE`. A different firmware
has a different boot image hash. Its adbd binary is probably different too, so the two-byte
patch may sit at another offset.

To add one:

1. Run the probe and backup, then `collect`. The tools check the partition layout. If
   `collect` reports a different layout, stop: the installer's fixed boot sector (0x2a000) does
   not apply.
2. Unpack `work/firmware/boot.img`, for example with `abootimg -x` and `cpio -id` on the
   ramdisk. Note the SHA-256 of the 16 MiB image and of `sbin/adbd`.
3. Disassemble `sbin/adbd` as Thumb code. Find the privilege drop in `adb_main`: a loop that
   removes capabilities with `prctl(PR_CAPBSET_DROP, ...)`, then `setgroups`, `setgid(2000)` and
   `setuid(2000)`. Find the first instruction of that sequence and the first instruction after
   it.
4. Encode a Thumb `b` (branch) from the first to the second address.
5. Add an entry with `adbd_offset`, the original bytes (`adbd_before`) and the patched bytes
   (`adbd_after`). Add tests, and open a pull request with the firmware string from Settings.

Do not install a patch you have not checked this way. A wrong branch can stop adbd from starting,
and then you have no ADB access. You can still roll back from the SD card.
