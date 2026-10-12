# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
"""Synthetic fixtures. No vendor firmware is stored in this repository."""
import struct

from frameo114k.layout import PREFIX_SIZE


def fake_spl(size=65536, fill=0x5a):
    image = bytearray([fill]) * size
    image[4:12] = b'eGON.BT0'
    struct.pack_into('<II', image, 12, 0x5F0A6C39, size)
    checksum = (sum(struct.unpack(f'<{size // 4}I', bytes(image))) - 0x5F0A6C39 + 0x5F0A6C39) & 0xFFFFFFFF
    struct.pack_into('<I', image, 12, checksum)
    return bytes(image)


def fake_prefix(fill=0x00):
    return bytes([fill]) * PREFIX_SIZE
