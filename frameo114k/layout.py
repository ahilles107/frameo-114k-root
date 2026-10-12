# SPDX-License-Identifier: GPL-2.0-or-later
"""SD card prefix layout shared by every stage.

The Allwinner boot ROM loads the SPL from byte 8192 of the SD card. Each
stage image reports back through one 512-byte result sector at 3 MiB. The
probe also stores two 512 KiB internal-storage samples at 1 MiB and 2 MiB.
All of this sits before the first partition, which must start at 4 MiB or
later.
"""
import os
import struct

PREFIX_SIZE = 4194304
BOOT_OFFSET = 8192
BOOT_LIMIT = 1048576
SAMPLE_OFFSETS = (1048576, 2097152)
SAMPLE_SIZE = 524288
RESULT_OFFSET = 3145728
REGION_END = RESULT_OFFSET + 512


def validate_spl(image):
    if len(image) < 8192 or image[4:12] != b'eGON.BT0':
        raise ValueError('Missing Allwinner SPL header.')
    checksum, length = struct.unpack_from('<II', image, 12)
    if length < 32 or length > len(image) or length % 4:
        raise ValueError('Invalid SPL length.')
    calculated = (sum(struct.unpack(f'<{length // 4}I', image[:length]))
                  - checksum + 0x5F0A6C39) & 0xFFFFFFFF
    if calculated != checksum:
        raise ValueError('SPL checksum failed.')
    if BOOT_OFFSET + len(image) > BOOT_LIMIT:
        raise ValueError('Image does not fit below the 1 MiB sample area.')


def compose(original, image, marker):
    """Return the prefix with a stage image, empty sample slots and a marker."""
    validate_spl(image)
    if len(original) != PREFIX_SIZE or len(marker) != 512:
        raise ValueError('Unexpected prefix or marker length.')
    result = bytearray(original)
    result[BOOT_OFFSET:BOOT_OFFSET + len(image)] = image
    for offset in SAMPLE_OFFSETS:
        result[offset:offset + SAMPLE_SIZE] = bytes(SAMPLE_SIZE)
    result[RESULT_OFFSET:REGION_END] = marker
    return bytes(result)


def mask_results(prefix):
    """Blank the areas a running stage may change: samples and the result sector."""
    data = bytearray(prefix)
    for offset in SAMPLE_OFFSETS:
        data[offset:offset + SAMPLE_SIZE] = bytes(SAMPLE_SIZE)
    data[RESULT_OFFSET:REGION_END] = bytes(512)
    return bytes(data)


def recognize(current, original, images):
    """Name the stage image on the card, 'original', or None if unknown."""
    if len(current) != PREFIX_SIZE:
        raise ValueError('Invalid prefix length.')
    if current[BOOT_OFFSET:REGION_END] == original[BOOT_OFFSET:REGION_END]:
        return 'original'
    masked = mask_results(current)
    for name, image in images.items():
        if masked == mask_results(compose(original, image, bytes(512))):
            return name
    return None


def apply_region(fd, current, desired):
    """Write bytes BOOT_OFFSET..REGION_END, verify, and roll back on failure."""
    if len(current) != PREFIX_SIZE or len(desired) != PREFIX_SIZE:
        raise ValueError('Invalid prefix length.')
    if current[:BOOT_OFFSET] != desired[:BOOT_OFFSET] or current[REGION_END:] != desired[REGION_END:]:
        raise ValueError('Refusing to change bytes outside the stage region.')
    if os.pread(fd, PREFIX_SIZE, 0) != current:
        raise ValueError('Card contents changed. No write performed.')
    size = REGION_END - BOOT_OFFSET
    try:
        if os.pwrite(fd, desired[BOOT_OFFSET:REGION_END], BOOT_OFFSET) != size:
            raise OSError('Short write.')
        os.fsync(fd)
        if os.pread(fd, PREFIX_SIZE, 0) != desired:
            raise OSError('Readback differs from the expected prefix.')
    except Exception as failure:
        if os.pwrite(fd, current[BOOT_OFFSET:REGION_END], BOOT_OFFSET) != size:
            raise RuntimeError('Rollback failed. Keep the saved prefix and stop.') from failure
        os.fsync(fd)
        if os.pread(fd, PREFIX_SIZE, 0) != current:
            raise RuntimeError('Rollback verification failed. Stop.') from failure
        raise RuntimeError('Write failed; previous bytes restored and verified.') from failure
