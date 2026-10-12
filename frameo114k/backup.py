# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
"""Firmware backup: on-device U-Boot command, host-side collection and extraction."""
import hashlib
import json
import re
import shutil
import struct
import zlib
from pathlib import Path

from .markers import BACKUP, parse_fields

DIRECTORY = 'frameo-backup-v1'
CHUNK_BLOCKS = 0x4000
BOOT_AREA_BLOCKS = 0x2000
# Physical start of UDISK (/data). Everything before it is firmware.
FIRMWARE_BLOCKS = 0x412000
VENDOR_TABLE_SECTOR = 0xa000
VENDOR_SHIFT = 40960
INSTALL_BOOT_SECTOR = 0x2a000
INSTALL_BOOT_BLOCKS = 0x8000
CORE_NAMES = ('bootloader', 'env', 'boot', 'system', 'misc', 'recovery')


def staged_save(address, name, size, label):
    return (f'setenv backup_stage {label}-write && save mmc 0:1 {address} {name} {size} && '
            f'setenv backup_stage {label}-readback && load mmc 0:1 0x43000000 {name} {size} && '
            f'setenv backup_stage {label}-size && itest ${{filesize}} == {size} && '
            f'setenv backup_stage {label}-compare && cmp.b {address} 0x43000000 {size}')


def backup_command():
    """U-Boot hush script that copies both eMMC boot areas and the firmware region to SD.

    Chunks already on the card are re-read from eMMC and compared, so re-running
    the same image resumes after an interrupted backup.
    """
    words = struct.unpack('<4I', BACKUP)
    challenge = ' && '.join(f'itest.l *0x{0x41000000 + i * 4:x} == 0x{word:x}'
                            for i, word in enumerate(words))
    register_reads = ' && '.join(
        [f'mmc reg read extcsd {212 + i} cap{i}' for i in range(4)] +
        ['mmc reg read extcsd 226 bootmult'] +
        [f'mmc reg read cid {i} cid{i}' for i in range(4)])
    capacity = (
        "setexpr userblocks ${cap3} '*' 0x1000000; "
        "setexpr value ${cap2} '*' 0x10000; setexpr userblocks ${userblocks} + ${value}; "
        "setexpr value ${cap1} '*' 0x100; setexpr userblocks ${userblocks} + ${value}; "
        "setexpr userblocks ${userblocks} + ${cap0}; "
        "setexpr bootblocks ${bootmult} '*' 0x100; ")
    device_condition = (f'itest ${{bootblocks}} == 0x{BOOT_AREA_BLOCKS:x} && '
                        f'itest ${{userblocks}} -gt 0x{FIRMWARE_BLOCKS:x}')
    progress = ('env export -t -s 0x1e0 0x41000020 backup_state part off total '
                'userblocks bootblocks cid0 cid1 cid2 cid3 backup_fs backup_stage && '
                'mmc dev 0 0 && mmc write 0x41000000 0x1800 1')
    chunk_save = staged_save('0x42000000', '${filename}', '${bytes}', 'data')
    digest_save = staged_save('0x41002000', '${filename}.txt', '0x200', 'digest')
    copy_loop = (
        'setenv good 1; '
        'for backup_area in 1 2 0; do setenv part ${backup_area}; '
        'if itest ${part} == 0; then setenv total ${userblocks}; '
        'else setenv total ${bootblocks}; fi; '
        f'if itest ${{part}} == 0; then setenv total {FIRMWARE_BLOCKS:x}; fi; '
        'setenv off 0; '
        'while itest ${off} -lt ${total} && itest ${good} == 1; do '
        'setexpr count ${total} - ${off}; '
        'if itest ${count} -gt 0x4000; then setenv count 4000; fi; '
        "setexpr bytes ${count} '*' 0x200; "
        f'setenv filename /{DIRECTORY}/p${{part}}-${{off}}.bin; '
        'setenv good 0; '
        'if setenv backup_stage internal-select && mmc dev 1 ${part} && '
        'setenv backup_stage internal-read && mmc read 0x42000000 ${off} ${count}; then '
        'if load mmc 0:1 0x43000000 ${filename} ${bytes} && '
        'itest ${filesize} == ${bytes} && cmp.b 0x42000000 0x43000000 ${bytes}; '
        f'then setenv good 1; else if {chunk_save}; then setenv good 1; fi; fi; '
        'if itest ${good} == 1; then setenv good 0; '
        'if setenv backup_stage hash && hash sha256 0x42000000 ${bytes} digest && '
        'setenv backup_stage digest-export && '
        'env export -t -s 0x200 0x41002000 part off bytes digest && '
        f'{digest_save}; then setenv good 1; fi; fi; fi; '
        'if itest ${good} == 1; then setexpr off ${off} + ${count}; setenv backup_stage progress; '
        f'if {progress}; then true; else setenv good 0; fi; fi; '
        'done; if itest ${good} == 0; then break; fi; done; '
        'if itest ${good} == 1; then setenv backup_state firmware-complete; '
        'mw.l 0x41000000 0x454e4f44 1; '
        'else setenv backup_state copy-failed; mw.l 0x41000000 0x4c494146 1; fi; ')
    metadata = f'/{DIRECTORY}/device.txt'
    device_read = (
        'setenv backup_state metadata-read-failed && '
        f'load mmc 0:1 0x43000000 {metadata} 0x200 && '
        'setenv backup_state metadata-size-failed && itest ${filesize} == 0x200 && '
        'setenv backup_state metadata-mismatch && cmp.b 0x41001000 0x43000000 0x200')
    device_save = ('setenv backup_state metadata-write-failed && '
                   f'save mmc 0:1 0x41001000 {metadata} 0x200 && ' + device_read)
    return (
        'if mmc dev 0 0 && mmc read 0x41000000 0x1800 1; then '
        f'if {challenge}; then mw.l 0x41000000 0x214e5552 1; '
        'if mmc write 0x41000000 0x1800 1; then '
        'setenv backup_state init-failed; '
        f'if mmc dev 1 0 && {register_reads}; then {capacity}'
        'setenv backup_state device-refused; '
        f'if {device_condition}; then '
        'setenv backup_state filesystem-failed; setenv metaok 0; setenv backup_fs unknown; '
        'if fstype mmc 0:1 backup_fs && test ${backup_fs} = exfat; then '
        'setenv backup_state metadata-export-failed; '
        'if env export -t -s 0x200 0x41001000 userblocks bootblocks cid0 cid1 cid2 cid3; then '
        f'if size mmc 0:1 {metadata}; then '
        f'if {device_read}; then setenv metaok 1; fi; '
        f'else if {device_save}; then setenv metaok 1; fi; fi; fi; fi; '
        'if itest ${metaok} == 1; then setenv backup_state copying; '
        + copy_loop + 'fi; fi; fi; '
        'if itest.l *0x41000000 != 0x454e4f44; then mw.l 0x41000000 0x4c494146 1; fi; '
        + progress + '; fi; fi; fi')


def hex_value(text):
    if not re.fullmatch('[0-9a-fA-F]{1,8}', text):
        raise ValueError('Invalid hexadecimal value.')
    return int(text, 16)


def parse_device(data):
    fields = parse_fields(data)
    if set(fields) != {'userblocks', 'bootblocks', 'cid0', 'cid1', 'cid2', 'cid3'}:
        raise ValueError('Missing or unexpected device fields.')
    device = {key: hex_value(value) for key, value in fields.items()}
    if device['bootblocks'] != BOOT_AREA_BLOCKS or device['userblocks'] <= FIRMWARE_BLOCKS:
        raise ValueError('Internal storage geometry does not match a Frameo 114K.')
    device['cid'] = ''.join(f'{device[f"cid{i}"]:08x}' for i in range(4))
    return device


def file_digest(path):
    with Path(path).open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def verify_chunk(path, part, offset, size):
    fields = parse_fields(path.with_suffix('.bin.txt').read_bytes())
    if set(fields) != {'part', 'off', 'bytes', 'digest'}:
        raise ValueError(f'Invalid checksum metadata: {path.name}')
    if (hex_value(fields['part']), hex_value(fields['off']), hex_value(fields['bytes'])) != (part, offset, size):
        raise ValueError(f'Chunk coordinates do not match: {path.name}')
    digest = fields['digest']
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Invalid SHA-256.')
    if path.is_symlink() or path.stat().st_size != size or file_digest(path) != digest:
        raise ValueError(f'Chunk checksum or size mismatch: {path.name}')
    return digest


def chunk_plan(device, firmware_blocks=FIRMWARE_BLOCKS):
    for part in (1, 2, 0):
        total = firmware_blocks if part == 0 else device['bootblocks']
        for offset in range(0, total, CHUNK_BLOCKS):
            yield part, offset, min(CHUNK_BLOCKS, total - offset) * 512


def collect(source, target, firmware_blocks=FIRMWARE_BLOCKS):
    """Verify every chunk on the SD card and copy it into target."""
    metadata = (source / 'device.txt').read_bytes()
    device = parse_device(metadata)
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    needed = (firmware_blocks + 2 * device['bootblocks']) * 512
    if shutil.disk_usage(target).free < needed + 1073741824:
        raise ValueError('Not enough local space for the backup plus 1 GiB.')
    files = []
    for part, offset, size in chunk_plan(device, firmware_blocks):
        name = f'p{part}-{offset:x}.bin'
        digest = verify_chunk(source / name, part, offset, size)
        saved = target / name
        if not saved.exists() or saved.stat().st_size != size or file_digest(saved) != digest:
            temporary = target / (name + '.partial')
            with (source / name).open('rb') as reader, temporary.open('wb') as writer:
                shutil.copyfileobj(reader, writer, 1048576)
            temporary.chmod(0o600)
            if file_digest(temporary) != digest:
                raise ValueError(f'Copied file checksum failed: {name}')
            temporary.replace(saved)
        files.append({'file': name, 'part': part, 'sector': offset, 'bytes': size, 'sha256': digest})
        if len(files) % 64 == 0:
            print(f'Verified and copied {len(files)} chunks.', flush=True)
    (target / 'device.txt').write_bytes(metadata)
    manifest = {'device': device, 'verified_bytes': needed, 'files': files,
                'scope': 'eMMC boot areas 1 and 2 plus the user area before UDISK; UDISK and RPMB excluded'}
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return device


def read_physical(source, sector, count):
    """Read sectors of the eMMC user area from collected chunks."""
    output = bytearray()
    position, end = sector * 512, (sector + count) * 512
    while position < end:
        chunk = position // (CHUNK_BLOCKS * 512) * CHUNK_BLOCKS
        within = position - chunk * 512
        size = min(end - position, CHUNK_BLOCKS * 512 - within)
        with (source / f'p0-{chunk:x}.bin').open('rb') as reader:
            reader.seek(within)
            data = reader.read(size)
        if len(data) != size:
            raise ValueError('Truncated backup chunk.')
        output.extend(data)
        position += size
    return bytes(output)


def vendor_partitions(raw):
    """Parse the four Allwinner 'softw411' partition table copies; all must agree."""
    tables = []
    for copy in range(4):
        table = raw[copy * 16384:(copy + 1) * 16384]
        crc, version, magic, copies, index, count = struct.unpack_from('<II8sIII', table)
        if magic != b'softw411' or version != 0x200 or copies != 4 or index != copy or count > 120:
            raise ValueError('Unexpected Allwinner partition table header.')
        if crc != zlib.crc32(table[4:]):
            raise ValueError('Allwinner partition table checksum failed.')
        partitions = {}
        for number in range(count):
            entry = table[32 + number * 128:32 + (number + 1) * 128]
            high, low, size_high, size_low, _, name = struct.unpack_from('<IIII16s16s', entry)
            partitions[name.rstrip(b'\0').decode('ascii')] = ((high << 32) | low, (size_high << 32) | size_low)
        tables.append(partitions)
    if any(table != tables[0] for table in tables):
        raise ValueError('Partition table copies disagree.')
    return tables[0]


def physical_layout(source):
    """Map vendor partitions to physical sectors and check the installer constants."""
    partitions = vendor_partitions(read_physical(source, VENDOR_TABLE_SECTOR, 128))
    mbr = read_physical(source, 0, 1)
    if mbr[510:512] != b'\x55\xaa':
        raise ValueError('Invalid physical MBR.')
    for name in (*CORE_NAMES, 'UDISK'):
        if name not in partitions:
            raise ValueError(f'Missing vendor partition: {name}')
    udisk, bootloader = struct.unpack_from('<I', mbr, 454)[0], struct.unpack_from('<I', mbr, 470)[0]
    if udisk - partitions['UDISK'][0] != VENDOR_SHIFT or bootloader != partitions['bootloader'][0] + VENDOR_SHIFT:
        raise ValueError('Physical MBR and vendor partition table disagree.')
    layout = {name: (sector + VENDOR_SHIFT, count) for name, (sector, count) in partitions.items()}
    if layout['boot'] != (INSTALL_BOOT_SECTOR, INSTALL_BOOT_BLOCKS) or layout['UDISK'][0] != FIRMWARE_BLOCKS:
        raise ValueError('Partition layout differs from the supported Frameo 114K layout.')
    return layout


def verify_partition_header(name, data):
    if name == 'system' and data[1080:1082] != b'\x53\xef':
        raise ValueError('System partition lacks an ext4 superblock.')
    if name in ('boot', 'recovery'):
        if data[:8] != b'ANDROID!':
            raise ValueError(f'Missing Android boot header in {name}.')
        page = struct.unpack_from('<I', data, 36)[0]
        sizes = [struct.unpack_from('<I', data, offset)[0] for offset in (8, 16, 24)]
        if page != 2048 or min(sizes[:2]) <= 0:
            raise ValueError('Unexpected Android image geometry.')
        if page + sum((size + page - 1) // page * page for size in sizes) > len(data):
            raise ValueError('Android image exceeds its partition.')


def extract_firmware(source, target, samples=()):
    """Extract core partition images and both eMMC boot areas from a collected backup."""
    device = parse_device((source / 'device.txt').read_bytes())
    for sector, sample in samples:
        if read_physical(source, sector, len(sample) // 512) != sample:
            raise ValueError(f'Backup differs from the probe sample at sector {sector:#x}.')
    layout = physical_layout(source)
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    for name in CORE_NAMES:
        sector, count = layout[name]
        data = read_physical(source, sector, count)
        verify_partition_header(name, data)
        results.append(_save(target / f'{name}.img', data, name, sector))
    for part in (1, 2):
        data = (source / f'p{part}-0.bin').read_bytes()
        results.append(_save(target / f'emmc-boot{part}.img', data, f'emmc-boot{part}', 0))
    manifest = {'device': device, 'complete_device_backup': False, 'partitions': results,
                'excluded': [name for name in layout if name not in CORE_NAMES] + ['RPMB']}
    (target / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (target / 'device.json').write_text(json.dumps(device, indent=2) + '\n')
    return manifest


def _save(path, data, name, sector):
    digest = hashlib.sha256(data).hexdigest()
    if path.exists() and file_digest(path) != digest:
        raise ValueError(f'Existing {path.name} differs; preserve it before extracting again.')
    path.write_bytes(data)
    path.chmod(0o600)
    return {'name': name, 'sector': sector, 'bytes': len(data), 'sha256': digest, 'file': path.name}
