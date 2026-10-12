# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
import base64
import gzip
import hashlib
import struct
import unittest

from frameo114k import bootimg

ADBD = bytes(0xf9a) + bytes.fromhex('00271720') + b'\x01' * 64


def cpio(entries):
    fields = [1, 0o100644, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0]
    packed = [(name, [index + 1] + fields[1:], data) for index, (name, data) in enumerate(entries)]
    packed.append(('TRAILER!!!', [0] * 13, b''))
    raw = bootimg.pack_cpio(packed)
    return raw + bytes(-len(raw) % 512)


def boot_image():
    kernel = b'K' * 4096
    ramdisk = gzip.compress(cpio([('default.prop', b'ro.secure=1\n'), ('init.rc', b'on init\n'),
                                  ('sbin/adbd', ADBD)]), mtime=0)
    image = bytearray(16777216)
    image[:8] = b'ANDROID!'
    struct.pack_into('<I', image, 8, len(kernel))
    struct.pack_into('<I', image, 16, len(ramdisk))
    struct.pack_into('<I', image, 36, 2048)
    image[2048:2048 + len(kernel)] = kernel
    start = 2048 + 4096
    image[start:start + len(ramdisk)] = ramdisk
    image[576:608] = bootimg.image_id(bytes(image), ramdisk)
    return bytes(image)


def adb_key():
    raw = struct.pack('<I', 64) + bytes(516) + struct.pack('<I', 65537)
    return base64.b64encode(raw).decode() + ' owner@host\n'


class BootImageTests(unittest.TestCase):
    def setUp(self):
        self.image = boot_image()
        self.known = {hashlib.sha256(self.image).hexdigest(): {
            'firmware': 'test', 'adbd_sha256': hashlib.sha256(ADBD).hexdigest(),
            'adbd_offset': 0xf9a, 'adbd_before': '00271720', 'adbd_after': '002735e0'}}

    def test_patch_changes_only_expected_members(self):
        patched, report = bootimg.build_candidate(self.image, adb_key(), self.known)
        self.assertEqual(len(patched), len(self.image))
        self.assertEqual(report['changed_existing_files'], ['default.prop', 'init.rc', 'sbin/adbd'])
        self.assertTrue(report['kernel_unchanged'])
        _, start, size, _ = bootimg.image_parts(patched)
        entries = {name: data for name, _, data in bootimg.parse_cpio(gzip.decompress(patched[start:start + size]))[0]}
        self.assertIn(b'service.adb.tcp.port=5555', entries['default.prop'])
        self.assertEqual(entries['sbin/adbd'][0xf9c:0xf9e], bytes.fromhex('35e0'))
        self.assertEqual(entries['adb_keys'], adb_key().strip().encode() + b'\n')

    def test_unknown_firmware_refused(self):
        with self.assertRaisesRegex(ValueError, 'Unknown boot image'):
            bootimg.build_candidate(self.image[:-1] + b'x', adb_key(), self.known)

    def test_bad_key_refused(self):
        with self.assertRaises(ValueError):
            bootimg.build_candidate(self.image, 'AAAA\nBBBB', self.known)

    def test_shipped_profile_is_pinned(self):
        self.assertEqual(len(bootimg.KNOWN_FIRMWARE), 1)
        profile = next(iter(bootimg.KNOWN_FIRMWARE.values()))
        self.assertEqual(profile['adbd_after'][:4], profile['adbd_before'][:4])


if __name__ == '__main__':
    unittest.main()
