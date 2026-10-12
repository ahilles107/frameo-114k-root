# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
"""Command-line entry point. Run through the ./frameo wrapper."""
import argparse
import json
from pathlib import Path

from . import backup, bootimg, build, sdcard, sdflow, workdir
from .backup import VENDOR_TABLE_SECTOR
from .uboot import STAGES


def collect(work, disk):
    sdcard.require_macos()
    sdflow.card_context(work, disk)
    sdcard.unmount(disk)
    source = sdcard.mount(disk, True) / backup.DIRECTORY
    device = backup.collect(source, workdir.make_dir(work / 'backup'))
    sdcard.unmount(disk)
    samples = [(sector, (work / f'probe/sample-{number}.bin').read_bytes())
               for number, sector in ((0, 0), (1, VENDOR_TABLE_SECTOR))
               if (work / f'probe/sample-{number}.bin').exists()]
    manifest = backup.extract_firmware(work / 'backup', work / 'firmware', samples)
    print(f'Backup verified for eMMC CID {device["cid"]}.')
    for item in manifest['partitions']:
        print(f'  {item["file"]}: {item["bytes"]} bytes, sha256 {item["sha256"]}')
    boot = workdir.sha256((work / 'firmware/boot.img').read_bytes())
    if boot not in bootimg.KNOWN_FIRMWARE:
        print(f'Warning: boot.img {boot} is not a supported firmware. See docs/other-firmware.md.')


def patch(work, key):
    original = (work / 'firmware/boot.img').read_bytes()
    image, report = bootimg.build_candidate(original, Path(key).expanduser().read_text())
    path = work / 'boot/boot-patched.img'
    if path.exists() and path.read_bytes() != image:
        raise SystemExit('An existing boot-patched.img differs. Move it away before patching again.')
    workdir.save(path, image)
    workdir.save_json(work / 'boot/report.json', report)
    print(json.dumps(report, indent=2))


def status(work):
    checks = [('sd/card.json', 'SD card recorded'), ('probe/sample-1.bin', 'probe samples'),
              ('firmware/device.json', 'firmware backup collected'), ('boot/boot-patched.img', 'boot image patched')]
    checks += [(f'images/{stage}.bin', f'{stage} image built') for stage in STAGES]
    print(f'Work directory: {work}')
    for name, label in checks:
        print(f'  [{"x" if (work / name).exists() else " "}] {label}')


def main():
    parser = argparse.ArgumentParser(prog='frameo', description='Frameo 114K root tooling')
    parser.add_argument('--workdir', help='work directory (default: $FRAMEO_WORKDIR or ./work)')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('build', help='build an SD stage image in Docker').add_argument('stage', choices=STAGES)
    sd = commands.add_parser('sd', help='SD card operations (need sudo)')
    sd.add_argument('action', choices=('init', 'write', 'result', 'restore'))
    sd.add_argument('target', nargs='?', choices=sdflow.TARGETS)
    sd.add_argument('--disk', required=True, help='whole SD card device, for example /dev/disk4')
    commands.add_parser('collect', help='verify and copy the backup from the SD card').add_argument('--disk', required=True)
    patch_parser = commands.add_parser('patch', help='patch the backed-up boot image')
    patch_parser.add_argument('--adb-key', default='~/.android/adbkey.pub')
    commands.add_parser('status', help='show progress')
    args = parser.parse_args()
    work = workdir.resolve(args.workdir)
    if args.command == 'build':
        build.build(work, args.stage)
    elif args.command == 'sd':
        sdcard.require_macos()
        if (args.action == 'write') != (args.target is not None):
            parser.error('"sd write" needs a target; other sd actions take none.')
        action = {'init': sdflow.init, 'result': sdflow.result, 'restore': sdflow.restore}.get(args.action)
        if action:
            action(work, args.disk)
        else:
            sdflow.write(work, args.disk, args.target)
    elif args.command == 'collect':
        collect(work, args.disk)
    elif args.command == 'patch':
        patch(work, args.adb_key)
    else:
        status(work)


if __name__ == '__main__':
    main()
