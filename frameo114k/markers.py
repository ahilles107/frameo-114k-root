# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
"""Result-sector formats written by the probe, backup and install images."""
import re
import zlib

from .layout import RESULT_OFFSET, SAMPLE_OFFSETS, SAMPLE_SIZE

PROBE = b'FRAMEO114KPROBE1'
BACKUP = b'FRAMEO114KBKUP01'
INSTALL = b'FRAMEO114KBOOT01'
INSTALL_MODES = {'apply': 'A', 'rollback': 'R', 'verify': 'V'}
INSTALL_STATES = (
    'pending', 'running', 'image-refused', 'device-refused', 'current-refused',
    'read-failed', 'already-desired', 'applied-verified', 'restored-verified',
    'failure-original-restored', 'recovery-failed', 'verified-original', 'verified-patched')


def parse_fields(data):
    payload, separator, padding = bytes(data).partition(b'\0')
    if not separator or padding.strip(b'\0'):
        raise ValueError('Invalid terminated payload.')
    fields = {}
    for line in payload.decode('ascii').splitlines():
        key, separator, value = line.partition('=')
        if not separator or key in fields or not re.fullmatch('[a-z][a-z0-9_]*', key):
            raise ValueError('Invalid or duplicate field.')
        fields[key] = value
    return fields


def pending(stage, mode=None):
    if stage == 'probe':
        return PROBE.ljust(512, b'\0')
    if stage == 'backup':
        return BACKUP.ljust(512, b'\0')
    if stage == 'install':
        return install_marker(INSTALL_MODES[mode])
    raise ValueError(f'Unknown stage: {stage}')


def install_marker(mode, state='pending'):
    if mode not in INSTALL_MODES.values() or state not in INSTALL_STATES:
        raise ValueError('Unknown install mode or state.')
    return INSTALL + mode.encode() + bytes(15) + state.encode().ljust(480, b'\0')


def parse_install(marker):
    mode = chr(marker[16])
    state = bytes(marker[32:]).split(b'\0', 1)[0].decode('ascii', 'replace')
    if mode not in INSTALL_MODES.values() or state not in INSTALL_STATES or \
            bytes(marker) != install_marker(mode, state):
        raise ValueError('Invalid install marker.')
    return {'mode': mode, 'state': state}


def _status(marker, challenge):
    if marker[4:16] != challenge[4:] or marker[16:32] != bytes(16):
        raise ValueError('Unexpected result marker.')
    if marker[:4] == challenge[:4]:
        if marker[32:] != bytes(480):
            raise ValueError('Unexpected payload in a pending marker.')
        return 'not-observed'
    return {b'RUN!': 'started-not-completed', b'DONE': 'done', b'FAIL': 'failed'}.get(bytes(marker[:4]))


def parse_probe(prefix):
    marker = prefix[RESULT_OFFSET:RESULT_OFFSET + 512]
    status = _status(marker, PROBE)
    if status in ('not-observed', 'started-not-completed') and marker[32:] == bytes(480):
        return {'state': status}
    if status != 'done':
        raise ValueError('Unexpected probe marker state.')
    fields = parse_fields(marker[32:])
    if set(fields) - {'probe0', 'probe1', 'crc0', 'crc1'}:
        raise ValueError('Unexpected probe field.')
    samples = {}
    for number, offset in enumerate(SAMPLE_OFFSETS):
        status = fields.get(f'probe{number}')
        if status not in ('ok', 'read-failed', 'sd-write-failed'):
            raise ValueError('Missing or invalid probe status.')
        if status == 'ok':
            sample = bytes(prefix[offset:offset + SAMPLE_SIZE])
            crc = fields.get(f'crc{number}', '')
            if not re.fullmatch('[0-9a-fA-F]{8}', crc) or int(crc, 16) != zlib.crc32(sample):
                raise ValueError(f'Sample {number} checksum mismatch.')
            samples[number] = sample
    return {'state': 'completed', **fields, 'samples': samples}


def parse_backup(marker):
    status = _status(marker, BACKUP)
    if status == 'not-observed':
        return {'state': status}
    if status is None:
        raise ValueError('Unexpected backup marker state.')
    fields = parse_fields(marker[32:])
    if status == 'done' and fields.get('backup_state') == 'firmware-complete':
        return {'state': 'device-reported-complete', **fields}
    return {'state': 'failed' if status == 'done' else status, **fields}


def parse(stage, prefix):
    marker = bytes(prefix[RESULT_OFFSET:RESULT_OFFSET + 512])
    if stage == 'probe':
        return parse_probe(prefix)
    if stage == 'backup':
        return parse_backup(marker)
    if stage == 'install':
        return parse_install(marker)
    raise ValueError(f'Unknown stage: {stage}')
