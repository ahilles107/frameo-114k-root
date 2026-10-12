# SPDX-License-Identifier: GPL-2.0-or-later
"""Patch a stock Frameo 114K boot image for authenticated root ADB over Wi-Fi.

Changes only the ramdisk: TCP ADB on port 5555 in default.prop, adbd started from
init.rc, a two-byte branch in sbin/adbd that skips the privilege drop, and the
owner's public key in /adb_keys. Authentication, the kernel and SELinux policy
are unchanged. See docs/how-it-works.md.
"""
import base64
import gzip
import hashlib
import struct

# Stock boot images this patch has been checked against, keyed by SHA-256 of the
# complete 16 MiB boot partition. See docs/other-firmware.md to add one.
KNOWN_FIRMWARE = {
    '85fdb88071e045e053c44600bd922119945d3c222f0daa1c9f2f1c341d4ec023': {
        'firmware': '114119_HK9365_SWM0810_frameo_v1.29.13_20260114',
        'adbd_sha256': 'dc3f61adea1db9218f7023d22b94322016a2da5aa5840d5db122fa5ab6e6d330',
        'adbd_offset': 0xf9a,
        'adbd_before': '00271720',
        'adbd_after': '002735e0',
    },
}


def parse_cpio(raw):
    entries = []
    seen = set()
    position = 0
    while position + 110 <= len(raw):
        header = raw[position:position + 110]
        if header[:6] != b'070701':
            raise ValueError('Unsupported cpio header.')
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        size, name_size = fields[6], fields[11]
        name_bytes = raw[position + 110:position + 110 + name_size]
        if not name_bytes.endswith(b'\0') or name_size < 1:
            raise ValueError('Unterminated cpio name.')
        name = name_bytes[:-1].decode('ascii')
        position = (position + 110 + name_size + 3) & ~3
        if position + size > len(raw) or name in seen:
            raise ValueError('Truncated or duplicate cpio entry.')
        seen.add(name)
        entries.append((name, fields, raw[position:position + size]))
        position = (position + size + 3) & ~3
        if name == 'TRAILER!!!':
            if raw[position:].strip(b'\0'):
                raise ValueError('Unexpected cpio trailing payload.')
            return entries, raw[position:]
    raise ValueError('Missing cpio trailer.')


def pack_cpio(entries):
    output = bytearray()
    for name, original_fields, data in entries:
        fields = list(original_fields)
        encoded = name.encode('ascii') + b'\0'
        fields[6], fields[11] = len(data), len(encoded)
        output.extend(b'070701' + ''.join(f'{value:08x}' for value in fields).encode() + encoded)
        output.extend(bytes(-len(output) % 4))
        output.extend(data)
        output.extend(bytes(-len(output) % 4))
    return bytes(output)


def image_parts(image):
    if len(image) != 16777216 or image[:8] != b'ANDROID!':
        raise ValueError('Unexpected boot partition.')
    kernel, ramdisk, second, page, dt = (struct.unpack_from('<I', image, off)[0] for off in (8, 16, 24, 36, 40))
    if page != 2048 or second != 0 or dt != 0 or min(kernel, ramdisk) <= 0:
        raise ValueError('Unexpected boot image sections.')
    start = page + ((kernel + page - 1) // page) * page
    end = start + ((ramdisk + page - 1) // page) * page
    if end > len(image):
        raise ValueError('Boot image exceeds partition.')
    return kernel, start, ramdisk, end


def image_id(image, compressed):
    kernel, _, _, _ = image_parts(image)
    digest = hashlib.sha1()
    digest.update(image[2048:2048 + kernel])
    digest.update(struct.pack('<I', kernel))
    digest.update(compressed)
    digest.update(struct.pack('<I', len(compressed)))
    digest.update(bytes(4))
    return digest.digest().ljust(32, b'\0')


def patch_adbd(data, profile):
    if hashlib.sha256(data).hexdigest() != profile['adbd_sha256']:
        raise ValueError('Unexpected stock adbd binary.')
    offset, before, after = profile['adbd_offset'], bytes.fromhex(profile['adbd_before']), bytes.fromhex(profile['adbd_after'])
    if data[offset:offset + len(before)] != before:
        raise ValueError('Unexpected privilege-drop instruction.')
    updated = bytearray(data)
    updated[offset:offset + len(after)] = after
    return bytes(updated)


def firmware_profile(original, known=KNOWN_FIRMWARE):
    digest = hashlib.sha256(original).hexdigest()
    if digest not in known:
        raise ValueError(f'Unknown boot image {digest}. Only verified stock firmware is supported; '
                         'see docs/other-firmware.md.')
    return known[digest]


def validate_public_key(text):
    line = text.strip()
    if '\n' in line or '\r' in line or not line:
        raise ValueError('Expected one public ADB key.')
    decoded = base64.b64decode(line.split()[0], validate=True)
    if len(decoded) != 524 or struct.unpack_from('<I', decoded)[0] != 64:
        raise ValueError('Expected an Android RSA-2048 public key.')
    if struct.unpack_from('<I', decoded, 520)[0] != 65537:
        raise ValueError('Unexpected ADB public exponent.')
    return line.encode() + b'\n'


def build_candidate(original, public_key, known=KNOWN_FIRMWARE):
    profile = firmware_profile(original, known)
    key = validate_public_key(public_key)
    _, start, size, end = image_parts(original)
    compressed = original[start:start + size]
    if image_id(original, compressed) != original[576:608]:
        raise ValueError('Original Android image ID does not match.')
    raw = gzip.decompress(compressed)
    entries, tail = parse_cpio(raw)
    if pack_cpio(entries) + tail != raw:
        raise ValueError('Cpio roundtrip differs from original bytes.')
    before = {name: (fields, data) for name, fields, data in entries}
    if 'adb_keys' in before:
        raise ValueError('Original already contains ADB keys.')
    properties = before['default.prop'][1]
    if b'ro.adb.secure=' in properties or b'service.adb.tcp.port=' in properties:
        raise ValueError('Original already specifies ADB authentication or TCP settings.')
    replacements = {
        'default.prop': properties.rstrip(b'\n') + b'\nro.adb.secure=1\nservice.adb.tcp.port=5555\n',
        'init.rc': before['init.rc'][1].rstrip(b'\n') +
                   b'\n\non boot\n    start adbd\n\non property:sys.boot_completed=1\n    start adbd\n',
        'sbin/adbd': patch_adbd(before['sbin/adbd'][1], profile),
    }
    changed = [(name, fields, replacements.get(name, data)) for name, fields, data in entries[:-1]]
    fields = list(before['default.prop'][0])
    fields[0] = max(entry[1][0] for entry in entries) + 1
    fields[1:5] = [0o100644, 0, 0, 1]
    fields[8:11] = [0, 0, 0]
    changed.append(('adb_keys', fields, key))
    changed.append(entries[-1])
    new_raw = pack_cpio(changed)
    new_raw += bytes(-len(new_raw) % 512)
    new_compressed = gzip.compress(new_raw, compresslevel=9, mtime=0)
    if len(new_compressed) > end - start:
        raise ValueError('Patched ramdisk does not fit the original allocation.')
    patched = bytearray(original)
    patched[start:end] = new_compressed.ljust(end - start, b'\0')
    struct.pack_into('<I', patched, 16, len(new_compressed))
    patched[576:608] = image_id(bytes(patched), new_compressed)
    decoded, _ = parse_cpio(gzip.decompress(new_compressed))
    after = {name: (fields, data) for name, fields, data in decoded}
    actual_changes = sorted(name for name, value in before.items() if after[name] != value)
    if actual_changes != sorted(replacements) or set(after) - set(before) != {'adb_keys'}:
        raise ValueError('Unexpected ramdisk changes.')
    report = {'firmware': profile['firmware'], 'original_sha256': hashlib.sha256(original).hexdigest(),
              'patched_sha256': hashlib.sha256(patched).hexdigest(), 'image_bytes': len(patched),
              'changed_existing_files': actual_changes, 'added_files': ['adb_keys'],
              'kernel_unchanged': patched[2048:start] == original[2048:start]}
    return bytes(patched), report
