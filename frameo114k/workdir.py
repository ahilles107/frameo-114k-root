# SPDX-License-Identifier: GPL-2.0-or-later
"""Work directory: owner backups, built images, results. Files stay owned by the invoking user under sudo."""
import hashlib
import json
import os
from pathlib import Path


def resolve(path=None):
    return Path(path or os.environ.get('FRAMEO_WORKDIR') or 'work').expanduser().resolve()


def _owner(fd):
    if os.geteuid() == 0 and 'SUDO_UID' in os.environ and 'SUDO_GID' in os.environ:
        os.fchown(fd, int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID']))


def make_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDONLY)
    try:
        _owner(fd)
    finally:
        os.close(fd)
    return path


def save(path, data):
    make_dir(path.parent)
    if isinstance(data, str):
        data = data.encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as file:
        _owner(file.fileno())
        file.write(data)
    return path


def save_json(path, value):
    return save(path, json.dumps(value, indent=2) + '\n')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verified(path, digest):
    data = Path(path).read_bytes()
    if sha256(data) != digest:
        raise ValueError(f'Checksum failed: {path}')
    return data
