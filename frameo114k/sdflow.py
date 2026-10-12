# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
"""SD card workflow: record the card, write a stage, read its result, restore."""
import json
import os
import time

from . import markers, sdcard, workdir
from .backup import DIRECTORY as BACKUP_DIRECTORY, vendor_partitions, VENDOR_SHIFT, INSTALL_BOOT_SECTOR
from .layout import BOOT_OFFSET, RESULT_OFFSET, apply_region, compose, recognize
from .uboot import STAGES

INSTALL_DIRECTORY = 'frameo-boot-v1'
CHALLENGES = (markers.PROBE, markers.BACKUP, markers.INSTALL)
TARGETS = ('probe', 'backup', 'install-verify', 'install-apply', 'install-rollback')


def load_images(work):
    images = {}
    for stage in STAGES:
        meta = work / f'images/{stage}.json'
        if meta.exists():
            images[stage] = workdir.verified(work / f'images/{stage}.bin', json.loads(meta.read_text())['sha256'])
    return images


def card_context(work, disk):
    path = work / 'sd/card.json'
    if not path.exists():
        raise SystemExit('No recorded SD card. Run "sd init --disk ..." first.')
    record = json.loads(path.read_text())
    sdcard.same_card(disk, record['identity'])
    return workdir.verified(work / 'sd/original-prefix.bin', record['original_sha256'])


def read_current(work, disk):
    sdcard.unmount(disk)
    current = sdcard.read_prefix(disk)
    workdir.save(work / f'sd/history/prefix-{time.time_ns()}.bin', current)
    return current


def init(work, disk):
    identity = sdcard.identity(disk)
    path = work / 'sd/card.json'
    if path.exists():
        if json.loads(path.read_text())['identity'] != identity:
            raise SystemExit('This work directory already records a different card. Use another --workdir.')
        print('Card already recorded.')
        return
    sdcard.unmount(disk)
    prefix = sdcard.read_prefix(disk)
    marker = prefix[RESULT_OFFSET:RESULT_OFFSET + 16]
    if any(marker[4:] == challenge[4:] for challenge in CHALLENGES):
        raise SystemExit('This card already holds a stage from another work directory. Restore it there first.')
    workdir.save(work / 'sd/original-prefix.bin', prefix)
    workdir.save_json(path, {'identity': identity, 'original_sha256': workdir.sha256(prefix)})
    print(f'Recorded {identity["disk"]} ({identity["size"]} bytes) and saved its first 4 MiB.')


def write(work, disk, target):
    stage, _, mode = target.partition('-')
    images = load_images(work)
    if stage not in images:
        raise SystemExit(f'Build the {stage} image first: ./frameo build {stage}')
    original = card_context(work, disk)
    current = read_current(work, disk)
    state = recognize(current, original, images)
    if state is None:
        raise SystemExit('The SD boot area holds unknown data. Stop and inspect the saved prefix.')
    if state != 'original':
        result = markers.parse(state, current)
        if state == 'install' and result['state'] == 'running' and target not in ('install-verify', 'install-rollback'):
            raise SystemExit('The last install did not report completion. Run install-verify or install-rollback.')
    if stage == 'backup':
        prepare_backup_folder(disk)
    if stage == 'install':
        stage_boot_images(work, disk)
        if sdcard.read_prefix(disk) != current:
            raise SystemExit('SD prefix changed while staging images. Stop.')
    desired = compose(original, images[stage], markers.pending(stage, mode or None))
    card_context(work, disk)
    fd = sdcard.open_raw(disk, True)
    try:
        apply_region(fd, current, desired)
    finally:
        os.close(fd)
    print(f'SD card prepared and verified for {target}. Ejecting.')
    sdcard.eject(disk)


def prepare_backup_folder(disk):
    volume = sdcard.mount(disk, False)
    (volume / BACKUP_DIRECTORY).mkdir(exist_ok=True)
    if os.statvfs(volume).f_bavail * os.statvfs(volume).f_frsize < 3 * 1024 ** 3:
        raise SystemExit('The SD card needs at least 3 GiB free for the firmware backup.')
    sdcard.unmount(disk)


def boot_image_files(work):
    meta = json.loads((work / 'images/install.json').read_text())
    return {'original.img': workdir.verified(work / 'firmware/boot.img', meta['original_sha256']),
            'patched.img': workdir.verified(work / 'boot/boot-patched.img', meta['patched_sha256'])}


def is_apple_double(path, files):
    if not path.name.startswith('._') or path.name[2:] not in files or path.is_symlink() or not path.is_file():
        return False
    with path.open('rb') as metadata:
        return metadata.read(8) == bytes.fromhex('0005160700020000')


def check_files(folder, files, allow_missing):
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise SystemExit(f'Unexpected /{INSTALL_DIRECTORY} on the SD card.')
    if not folder.exists():
        if allow_missing:
            return
        raise SystemExit(f'Missing /{INSTALL_DIRECTORY} on the SD card.')
    for path in folder.iterdir():
        if path.name not in files and not is_apple_double(path, files):
            raise SystemExit(f'Unexpected file /{INSTALL_DIRECTORY}/{path.name}. Remove it and retry.')
    for name, data in files.items():
        path = folder / name
        if not path.exists() and allow_missing:
            continue
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise SystemExit(f'/{INSTALL_DIRECTORY}/{name} differs from the expected image. Remove it and retry.')


def stage_boot_images(work, disk):
    files = boot_image_files(work)
    folder = sdcard.mount(disk, True) / INSTALL_DIRECTORY
    check_files(folder, files, True)
    sdcard.unmount(disk)
    folder = sdcard.mount(disk, False) / INSTALL_DIRECTORY
    folder.mkdir(exist_ok=True)
    for name, data in files.items():
        if not (folder / name).exists():
            with (folder / name).open('xb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
    sdcard.unmount(disk)
    check_files(sdcard.mount(disk, True) / INSTALL_DIRECTORY, files, False)
    sdcard.unmount(disk)


def result(work, disk):
    original = card_context(work, disk)
    current = read_current(work, disk)
    state = recognize(current, original, load_images(work))
    if state in (None, 'original'):
        raise SystemExit('No stage image on the card.' if state else 'Unknown SD boot area contents. Stop.')
    parsed = markers.parse(state, current)
    samples = parsed.pop('samples', {})
    for number, sample in samples.items():
        workdir.save(work / f'probe/sample-{number}.bin', sample)
    if 1 in samples:
        partitions = vendor_partitions(samples[1][:65536])
        parsed['boot_physical_sector'] = partitions['boot'][0] + VENDOR_SHIFT
        parsed['supported_layout'] = parsed['boot_physical_sector'] == INSTALL_BOOT_SECTOR
    parsed['stage'] = state
    workdir.save_json(work / f'results/{state}-{time.time_ns()}.json', parsed)
    print(json.dumps(parsed, indent=2))


def restore(work, disk):
    original = card_context(work, disk)
    current = read_current(work, disk)
    if recognize(current, original, load_images(work)) is None:
        raise SystemExit('Unknown SD boot area contents. Stop.')
    fd = sdcard.open_raw(disk, True)
    try:
        apply_region(fd, current, original)
    finally:
        os.close(fd)
    print(f'Restored the original bytes {BOOT_OFFSET} through {RESULT_OFFSET + 511}. Ejecting.')
    sdcard.eject(disk)
