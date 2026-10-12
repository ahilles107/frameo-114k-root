# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
import tempfile
import unittest
from pathlib import Path

from frameo114k import sdcard, sdflow


class StagingTests(unittest.TestCase):
    def test_check_files_accepts_matching_apple_double_only(self):
        files = {'original.img': b'a', 'patched.img': b'b'}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name, data in files.items():
                (folder / name).write_bytes(data)
            (folder / '._patched.img').write_bytes(bytes.fromhex('0005160700020000') + b'meta')
            sdflow.check_files(folder, files, False)
            (folder / '._other.img').write_bytes(bytes.fromhex('0005160700020000'))
            with self.assertRaises(SystemExit):
                sdflow.check_files(folder, files, False)
            (folder / '._other.img').unlink()
            (folder / 'patched.img').write_bytes(b'changed')
            with self.assertRaises(SystemExit):
                sdflow.check_files(folder, files, False)

    def test_disk_names(self):
        self.assertEqual(sdcard.disk_name('/dev/disk4'), 'disk4')
        for bad in ('/dev/disk4s1', '/dev/rdisk4', 'sda'):
            with self.assertRaises(ValueError):
                sdcard.disk_name(bad)


if __name__ == '__main__':
    unittest.main()
