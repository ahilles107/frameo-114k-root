# Contributing

Reports from other frames are the most useful contribution. Use the "Hardware report" issue
template, with the firmware string and the `sd result` output.

## Ground rules

- Never commit firmware, boot images, `adbd` binaries, disassembly dumps or backups. They belong
  to the vendor, and they hold data specific to one unit.
- Keep the safety model: identity checks, hash pinning, full readback, and the eMMC write gate
  limited to the boot partition. A change that widens what the stage images may write needs a
  clear reason and tests.
- Add support for a new firmware only after checking the adbd patch as described in
  [docs/other-firmware.md](docs/other-firmware.md).
- Say in your pull request what you ran on real hardware and what you only tested on the host.

## Tests

```sh
python3 -m unittest discover -s tests -t .
shellcheck frameo scripts/tablet-setup.sh
```

The native tests need a C compiler. On Linux they also need the OpenSSL headers (`libssl-dev`).

## License

By contributing, you agree that your contributions are licensed under GPL-2.0-or-later.
