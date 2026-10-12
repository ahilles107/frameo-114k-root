# SPDX-License-Identifier: GPL-2.0-or-later
import os
import tempfile
import unittest

from frameo114k.layout import (BOOT_OFFSET, PREFIX_SIZE, REGION_END, RESULT_OFFSET, SAMPLE_OFFSETS,
                               apply_region, compose, recognize, validate_spl)
from tests.helpers import fake_prefix, fake_spl


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.original = os.urandom(PREFIX_SIZE)
        self.probe, self.backup = fake_spl(fill=1), fake_spl(size=131072, fill=2)
        self.images = {'probe': self.probe, 'backup': self.backup}

    def test_spl_checks(self):
        validate_spl(self.probe)
        broken = bytearray(self.probe)
        broken[100] ^= 1
        with self.assertRaises(ValueError):
            validate_spl(bytes(broken))
        with self.assertRaises(ValueError):
            validate_spl(fake_spl(size=1048576))

    def test_compose_keeps_bytes_outside_region(self):
        prefix = compose(self.original, self.probe, b'M' * 512)
        self.assertEqual(prefix[:BOOT_OFFSET], self.original[:BOOT_OFFSET])
        self.assertEqual(prefix[REGION_END:], self.original[REGION_END:])
        self.assertEqual(prefix[RESULT_OFFSET:REGION_END], b'M' * 512)
        self.assertEqual(prefix[SAMPLE_OFFSETS[0]:SAMPLE_OFFSETS[0] + 4], bytes(4))

    def test_recognize(self):
        self.assertEqual(recognize(self.original, self.original, self.images), 'original')
        running = bytearray(compose(self.original, self.backup, bytes(512)))
        running[RESULT_OFFSET:RESULT_OFFSET + 4] = b'RUN!'
        running[SAMPLE_OFFSETS[1]] = 7
        self.assertEqual(recognize(bytes(running), self.original, self.images), 'backup')
        running[BOOT_OFFSET + 200000] ^= 1
        self.assertIsNone(recognize(bytes(running), self.original, self.images))

    def test_apply_region_writes_and_verifies(self):
        desired = compose(self.original, self.probe, bytes(512))
        with tempfile.TemporaryFile() as file:
            file.write(self.original)
            file.flush()
            apply_region(file.fileno(), self.original, desired)
            self.assertEqual(os.pread(file.fileno(), PREFIX_SIZE, 0), desired)
            with self.assertRaises(ValueError):
                apply_region(file.fileno(), self.original, desired)

    def test_apply_region_refuses_outside_changes(self):
        desired = bytearray(fake_prefix())
        desired[0] = 1
        with tempfile.TemporaryFile() as file:
            file.write(fake_prefix())
            file.flush()
            with self.assertRaises(ValueError):
                apply_region(file.fileno(), fake_prefix(), bytes(desired))


if __name__ == '__main__':
    unittest.main()
