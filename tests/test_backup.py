# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
import hashlib
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from frameo114k import backup

DEVICE = b'userblocks=1d1f000\nbootblocks=2000\ncid0=11223344\ncid1=55667788\ncid2=99aabbcc\ncid3=ddeeff00\n'
VENDOR = {'bootloader': (32768, 65536), 'env': (98304, 32768), 'boot': (131072, 32768),
          'system': (163840, 2097152), 'misc': (2260992, 32768), 'recovery': (2293760, 65536),
          'UDISK': (4227072, 0)}


def vendor_tables(partitions=VENDOR):
    raw = bytearray()
    for copy in range(4):
        table = bytearray(16384)
        struct.pack_into('<II8sIII', table, 0, 0, 0x200, b'softw411', 4, copy, len(partitions))
        for number, (name, (sector, count)) in enumerate(partitions.items()):
            struct.pack_into('<IIII16s16s', table, 32 + number * 128, 0, sector, 0, count, b'', name.encode())
        struct.pack_into('<I', table, 0, zlib.crc32(table[4:]))
        raw += table
    return bytes(raw)


def write_chunk(folder, part, offset, data):
    (folder / f'p{part}-{offset:x}.bin').write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    (folder / f'p{part}-{offset:x}.bin.txt').write_bytes(
        f'part={part:x}\noff={offset:x}\nbytes={len(data):x}\ndigest={digest}\n'.encode().ljust(512, b'\0'))


class BackupTests(unittest.TestCase):
    def test_command_is_generic_and_fits(self):
        command = backup.backup_command()
        self.assertLess(len(command), 16384)
        self.assertIn('itest ${userblocks} -gt 0x412000', command)
        self.assertNotIn('itest ${cid0} ==', command)
        self.assertIn('for backup_area in 1 2 0;', command)

    def test_device_geometry(self):
        device = backup.parse_device(DEVICE.ljust(512, b'\0'))
        self.assertEqual(device['cid'], '112233445566778899aabbccddeeff00')
        with self.assertRaises(ValueError):
            backup.parse_device(DEVICE.replace(b'bootblocks=2000', b'bootblocks=1000').ljust(512, b'\0'))

    def test_vendor_table_and_physical_layout(self):
        self.assertEqual(backup.vendor_partitions(vendor_tables())['boot'], (131072, 32768))
        broken = bytearray(vendor_tables())
        broken[40000] ^= 1
        with self.assertRaises(ValueError):
            backup.vendor_partitions(bytes(broken))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            mbr = bytearray(backup.CHUNK_BLOCKS * 512)
            struct.pack_into('<I', mbr, 454, VENDOR['UDISK'][0] + backup.VENDOR_SHIFT)
            struct.pack_into('<I', mbr, 470, VENDOR['bootloader'][0] + backup.VENDOR_SHIFT)
            mbr[510:512] = b'\x55\xaa'
            (folder / 'p0-0.bin').write_bytes(mbr)
            chunk = bytearray(backup.CHUNK_BLOCKS * 512)
            chunk[0x2000 * 512:0x2000 * 512 + 65536] = vendor_tables()
            (folder / 'p0-8000.bin').write_bytes(chunk)
            layout = backup.physical_layout(folder)
            self.assertEqual(layout['boot'], (backup.INSTALL_BOOT_SECTOR, backup.INSTALL_BOOT_BLOCKS))
            moved = dict(VENDOR, boot=(131073, 32768))
            chunk[0x2000 * 512:0x2000 * 512 + 65536] = vendor_tables(moved)
            (folder / 'p0-8000.bin').write_bytes(chunk)
            with self.assertRaises(ValueError):
                backup.physical_layout(folder)

    def test_collect_verifies_every_chunk(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            source, target = Path(source_dir), Path(target_dir) / 'backup'
            (source / 'device.txt').write_bytes(DEVICE.ljust(512, b'\0'))
            device = backup.parse_device(DEVICE.ljust(512, b'\0'))
            for part, offset, size in backup.chunk_plan(device, backup.CHUNK_BLOCKS):
                write_chunk(source, part, offset, bytes([part + 1]) * size)
            backup.collect(source, target, backup.CHUNK_BLOCKS)
            self.assertEqual((target / 'p0-0.bin').read_bytes()[:1], b'\x01')
            (source / 'p1-0.bin').write_bytes(b'x' * 4194304)
            with self.assertRaises(ValueError):
                backup.collect(source, Path(target_dir) / 'again', backup.CHUNK_BLOCKS)


if __name__ == '__main__':
    unittest.main()
