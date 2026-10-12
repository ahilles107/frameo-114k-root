# SPDX-License-Identifier: GPL-2.0-or-later
"""SD card access on macOS through diskutil and the raw /dev/rdiskN device."""
import os
import plistlib
import re
import stat
import subprocess
import sys
from pathlib import Path

from .layout import PREFIX_SIZE

DISKUTIL = '/usr/sbin/diskutil'


def require_macos():
    if sys.platform != 'darwin':
        raise SystemExit('SD card commands currently support macOS only. See docs/troubleshooting.md.')


def disk_name(disk):
    match = re.fullmatch(r'(?:/dev/)?(disk\d+)', disk)
    if not match:
        raise ValueError('Pass the whole SD card device, for example --disk /dev/disk4.')
    return match.group(1)


def info(device):
    result = subprocess.run([DISKUTIL, 'info', '-plist', device], check=True, capture_output=True)
    return plistlib.loads(result.stdout)


def identity(disk):
    """Describe the card and refuse anything that does not look like a spare SD card."""
    name = disk_name(disk)
    whole, partition = info(name), info(name + 's1')
    if whole.get('WholeDisk') is not True or name == 'disk0':
        raise ValueError('Not a whole disk.')
    if not (whole.get('RemovableMedia') or whole.get('Removable') or whole.get('Ejectable')):
        raise ValueError('The disk is not removable media. Refusing.')
    if whole.get('Content') != 'FDisk_partition_scheme':
        raise ValueError('The card must use an MBR partition table. See README, Prepare the SD card.')
    if whole.get('DeviceBlockSize') != 512:
        raise ValueError('Unexpected block size.')
    offset = partition.get('PartitionMapPartitionOffset', 0)
    if offset < PREFIX_SIZE:
        raise ValueError('The first partition must start at 4 MiB or later. Reformat with SD Card Formatter.')
    return {'disk': name, 'size': whole.get('Size') or whole.get('TotalSize'),
            'media_name': whole.get('MediaName'), 'volume_uuid': partition.get('VolumeUUID'),
            'partition_offset': offset}


def same_card(disk, recorded):
    current = identity(disk)
    if current != recorded:
        raise ValueError('This is not the card recorded by "sd init". Stop.')
    return current


def unmount(disk):
    subprocess.run([DISKUTIL, 'unmountDisk', disk_name(disk)], check=True, capture_output=True)


def eject(disk):
    subprocess.run([DISKUTIL, 'eject', disk_name(disk)], check=True)


def mount(disk, readonly):
    partition = disk_name(disk) + 's1'
    arguments = [DISKUTIL, 'mount'] + (['readOnly'] if readonly else []) + [partition]
    subprocess.run(arguments, check=True, capture_output=True)
    details = info(partition)
    if details.get('FilesystemType') != 'exfat' or not details.get('MountPoint'):
        raise ValueError('The first partition must be ExFAT.')
    if readonly and details.get('WritableVolume') is not False:
        raise ValueError('Expected a read-only mount.')
    return Path(details['MountPoint'])


def open_raw(disk, writable):
    if os.geteuid() != 0:
        raise SystemExit('Raw SD access needs root. Run this command with sudo.')
    fd = os.open('/dev/r' + disk_name(disk), os.O_RDWR if writable else os.O_RDONLY)
    if not stat.S_ISCHR(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError('Expected a raw character device.')
    return fd


def read_prefix(disk):
    fd = open_raw(disk, False)
    try:
        data = os.pread(fd, PREFIX_SIZE, 0)
    finally:
        os.close(fd)
    if len(data) != PREFIX_SIZE:
        raise ValueError('Short read from the SD card.')
    return data
