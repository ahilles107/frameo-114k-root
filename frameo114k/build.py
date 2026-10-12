# SPDX-License-Identifier: GPL-2.0-or-later
"""Build stage images with the pinned U-Boot release inside Docker."""
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

from . import uboot, workdir
from .bootimg import firmware_profile
from .layout import validate_spl

UBOOT_URL = 'https://github.com/u-boot/u-boot/archive/refs/tags/v2026.07.tar.gz'
UBOOT_SHA256 = '21463d6d4498768d01fa192f6027468c04480d0daa99cd546f9a75a4d9ec353c'
REPO = Path(__file__).resolve().parent.parent
IMAGE = 'frameo114k-builder'
TOOLCHAIN = 'arm-linux-gnueabi-'


def fetch(work):
    path = work / 'cache/u-boot-v2026.07.tar.gz'
    if not path.exists():
        workdir.make_dir(path.parent)
        temporary = path.with_suffix('.partial')
        with urllib.request.urlopen(UBOOT_URL) as response, temporary.open('wb') as output:
            shutil.copyfileobj(response, output)
        temporary.replace(path)
    workdir.verified(path, UBOOT_SHA256)
    return path


def install_inputs(work):
    """Device identity and boot hashes for the install image, from the owner's own files."""
    device = (work / 'firmware/device.json')
    if not device.exists():
        raise SystemExit('Missing firmware/device.json. Run the backup and "collect" first.')
    original = (work / 'firmware/boot.img').read_bytes()
    firmware_profile(original)
    patched = work / 'boot/boot-patched.img'
    if not patched.exists():
        raise SystemExit('Missing boot/boot-patched.img. Run "patch" first.')
    values = json.loads(device.read_text())
    return values, workdir.sha256(original), workdir.sha256(patched.read_bytes())


def build(work, stage):
    header, inputs = None, {}
    if stage == 'install':
        device, original, patched = install_inputs(work)
        header = uboot.device_header(device, original, patched)
        inputs = {'cid': device['cid'], 'original_sha256': original, 'patched_sha256': patched}
    tarball = fetch(work)
    tree = work / 'build' / stage
    if tree.exists():
        shutil.rmtree(tree)
    workdir.make_dir(tree)
    subprocess.run(['tar', '-xzf', str(tarball), '-C', str(tree)], check=True)
    defconfig = uboot.prepare(tree / 'u-boot-2026.07', stage, header)
    subprocess.run(['docker', 'build', '-q', '-t', IMAGE, str(REPO)], check=True)
    jobs = os.cpu_count() or 4
    script = (f'cd /work/u-boot-2026.07 && make O=/work/out CROSS_COMPILE={TOOLCHAIN} {defconfig} && '
              f'make O=/work/out CROSS_COMPILE={TOOLCHAIN} -j{jobs}')
    subprocess.run(['docker', 'run', '--rm', '-v', f'{tree}:/work', IMAGE, 'sh', '-c', script], check=True)
    image = (tree / 'out/u-boot-sunxi-with-spl.bin').read_bytes()
    validate_spl(image)
    workdir.save(work / f'images/{stage}.bin', image)
    workdir.save_json(work / f'images/{stage}.json', {
        'stage': stage, 'sha256': workdir.sha256(image), 'bytes': len(image),
        'uboot_sha256': UBOOT_SHA256, 'toolchain': TOOLCHAIN, **inputs})
    print(f'Built {stage}: {len(image)} bytes, sha256 {workdir.sha256(image)}')
