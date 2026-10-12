# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
import os
import unittest
import zlib

from frameo114k import markers
from frameo114k.layout import PREFIX_SIZE, RESULT_OFFSET, SAMPLE_OFFSETS, SAMPLE_SIZE


def with_marker(marker, prefix=None):
    data = bytearray(prefix or bytes(PREFIX_SIZE))
    data[RESULT_OFFSET:RESULT_OFFSET + 512] = marker
    return data


class MarkerTests(unittest.TestCase):
    def test_challenges_are_sixteen_bytes(self):
        for challenge in (markers.PROBE, markers.BACKUP, markers.INSTALL):
            self.assertEqual(len(challenge), 16)

    def test_install_roundtrip_and_tamper(self):
        marker = markers.install_marker('A', 'applied-verified')
        self.assertEqual(markers.parse_install(marker), {'mode': 'A', 'state': 'applied-verified'})
        with self.assertRaises(ValueError):
            markers.parse_install(marker[:-1] + b'x')
        self.assertEqual(markers.pending('install', 'rollback')[16:17], b'R')

    def test_probe_completed_with_valid_samples(self):
        prefix = bytearray(PREFIX_SIZE)
        sample = os.urandom(SAMPLE_SIZE)
        prefix[SAMPLE_OFFSETS[1]:SAMPLE_OFFSETS[1] + SAMPLE_SIZE] = sample
        payload = f'probe0=read-failed\nprobe1=ok\ncrc1={zlib.crc32(sample):08x}\n'.encode()
        marker = b'DONE' + markers.PROBE[4:] + bytes(16) + payload.ljust(480, b'\0')
        result = markers.parse('probe', with_marker(marker, bytes(prefix)))
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['samples'], {1: sample})
        prefix[SAMPLE_OFFSETS[1]] ^= 1
        with self.assertRaises(ValueError):
            markers.parse('probe', with_marker(marker, bytes(prefix)))

    def test_backup_states(self):
        self.assertEqual(markers.parse('backup', with_marker(markers.pending('backup')))['state'], 'not-observed')
        payload = b'backup_state=firmware-complete\npart=0\n'.ljust(480, b'\0')
        done = b'DONE' + markers.BACKUP[4:] + bytes(16) + payload
        self.assertEqual(markers.parse('backup', with_marker(done))['state'], 'device-reported-complete')
        failed = b'FAIL' + markers.BACKUP[4:] + bytes(16) + b'backup_stage=data-write\n'.ljust(480, b'\0')
        result = markers.parse('backup', with_marker(failed))
        self.assertEqual((result['state'], result['backup_stage']), ('failed', 'data-write'))
        with self.assertRaises(ValueError):
            markers.parse('backup', with_marker(markers.pending('probe')))


if __name__ == '__main__':
    unittest.main()
