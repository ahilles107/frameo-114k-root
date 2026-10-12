# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Pawel Mikolajczuk
"""Compile and run the C guard, transaction and installer tests on the host."""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from frameo114k.uboot import device_header

ROOT = Path(__file__).resolve().parent.parent
DEVICE = {'userblocks': 0x1d1f000, 'bootblocks': 0x2000,
          'cid0': 0x11223344, 'cid1': 0x55667788, 'cid2': 0x99aabbcc, 'cid3': 0xddeeff00}

STUBS = r'''
#ifndef FRAMEO_HOST_STUB_H
#define FRAMEO_HOST_STUB_H
#include <stdio.h>
#include <string.h>
#include <stdint.h>
typedef unsigned long ulong;
typedef long long loff_t;
struct cmd_tbl { int unused; };
struct blk_desc { unsigned hwpart, blksz; };
struct mmc {
    unsigned cid[4], high_capacity, read_bl_len, write_bl_len;
    unsigned long long capacity_user, capacity_boot;
    int is_sd;
    struct blk_desc block;
};
#define IS_SD(m) ((m)->is_sd)
#define FS_TYPE_EXFAT 1
#define CMD_RET_FAILURE 1
#define CMD_RET_SUCCESS 0
#define U_BOOT_CMD(...)
struct mmc *find_mmc_device(int);
int mmc_init(struct mmc *);
struct blk_desc *mmc_get_blk_desc(struct mmc *);
int mmc_send_ext_csd(struct mmc *, unsigned char *);
ulong blk_dread(struct blk_desc *, ulong, ulong, void *);
ulong blk_dwrite(struct blk_desc *, ulong, ulong, const void *);
int fs_set_blk_dev(const char *, const char *, int);
int fs_size(const char *, loff_t *);
int fs_read(const char *, ulong, loff_t, loff_t, loff_t *);
void sha256_csum_wd(const unsigned char *, unsigned, unsigned char *, unsigned);
static unsigned char original_mem[16777216], patched_mem[16777216], scratch_mem[16777216];
static unsigned char marker_mem[512], check_mem[512], ext_mem[512];
#endif
'''

HARNESS = r'''
#include <assert.h>
#ifdef __APPLE__
#include <CommonCrypto/CommonDigest.h>
#define SHA256_FN CC_SHA256
#else
#include <openssl/sha.h>
#define SHA256_FN SHA256
#endif
static struct mmc cards[2];
static unsigned char disk[BOOT_BYTES], media_marker[512];
static int writes, wrong_file, write_fail, sd_fail, wrong_size, read_fail, init_fail;
static unsigned char cache_control;
struct mmc *find_mmc_device(int n) { return &cards[n]; }
int mmc_init(struct mmc *m) { return m == &cards[1] && init_fail; }
struct blk_desc *mmc_get_blk_desc(struct mmc *m) { return &m->block; }
int mmc_send_ext_csd(struct mmc *m, unsigned char *out) {
    (void)m; memset(out, 0, 512); out[33] = cache_control;
    memcpy(out + 212, device_sector_count, 4); out[226] = 32; return 0;
}
ulong blk_dread(struct blk_desc *d, ulong sector, ulong blocks, void *out) {
    if (d == &cards[0].block) {
        assert(sector == RESULT_SECTOR && blocks == 1);
        memcpy(out, media_marker, 512); return 1;
    }
    assert(sector == BOOT_SECTOR && blocks == BOOT_BLOCKS);
    if (read_fail) { return 0; }
    memcpy(out, disk, BOOT_BYTES); return blocks;
}
ulong blk_dwrite(struct blk_desc *d, ulong sector, ulong blocks, const void *in) {
    if (d == &cards[0].block) {
        assert(!frameo_boot_unlocked && sector == RESULT_SECTOR && blocks == 1);
        if (sd_fail) { return 0; }
        memcpy(media_marker, in, 512); return 1;
    }
    assert(frameo_boot_unlocked && sector == BOOT_SECTOR && blocks == BOOT_BLOCKS);
    assert(!memcmp(media_marker + 32, "running", 8));
    writes++; memcpy(disk, in, write_fail == writes ? 512 : BOOT_BYTES);
    return write_fail == writes ? 0 : blocks;
}
int fs_set_blk_dev(const char *interface, const char *device, int type) {
    assert(!strcmp(interface, "mmc") && !strcmp(device, "0:1") && type == FS_TYPE_EXFAT); return 0;
}
int fs_size(const char *name, loff_t *size) { (void)name; *size = BOOT_BYTES - wrong_size; return 0; }
int fs_read(const char *name, ulong address, loff_t offset, loff_t size, loff_t *actual) {
    const char *path = strstr(name, "original") ? ORIGINAL_PATH : PATCHED_PATH;
    FILE *input = fopen(path, "rb"); assert(input && !offset && size == BOOT_BYTES);
    *actual = fread((void *)address, 1, size, input); fclose(input);
    if (wrong_file) { ((unsigned char *)address)[100] ^= 1; } return 0;
}
void sha256_csum_wd(const unsigned char *in, unsigned len, unsigned char *out, unsigned chunk) {
    assert(chunk > 0); SHA256_FN(in, len, out);
}
static void reset(char mode) {
    FILE *file = fopen(ORIGINAL_PATH, "rb"); assert(file);
    assert(fread(disk, 1, BOOT_BYTES, file) == BOOT_BYTES); fclose(file);
    memset(cards, 0, sizeof(cards));
    cards[0].is_sd = 1; cards[0].block.blksz = 512;
    cards[1].high_capacity = 1; cards[1].read_bl_len = cards[1].write_bl_len = 512;
    cards[1].capacity_user = device_user_bytes; cards[1].capacity_boot = 4194304;
    memcpy(cards[1].cid, device_cid, sizeof(device_cid));
    memset(media_marker, 0, 512); memcpy(media_marker, challenge, 16);
    media_marker[16] = mode; memcpy(media_marker + 32, "pending", 8);
    writes = wrong_file = write_fail = sd_fail = wrong_size = read_fail = init_fail = cache_control = 0;
}
static void run(const char *expected, int expected_writes) {
    do_frameoboot(0, 0, 1, 0);
    assert(!strcmp((char *)media_marker + 32, expected));
    assert(writes == expected_writes && !frameo_boot_unlocked);
}
int main(void) {
    FILE *file;
    reset('V'); run("verified-original", 0);
    reset('A'); wrong_file = 1; run("image-refused", 0);
    reset('A'); wrong_size = 1; run("image-refused", 0);
    reset('A'); cards[1].cid[0] ^= 1; run("device-refused", 0);
    reset('A'); cards[1].capacity_user--; run("device-refused", 0);
    reset('A'); cards[1].block.hwpart = 1; run("device-refused", 0);
    reset('A'); cache_control = 1; run("device-refused", 0);
    reset('A'); init_fail = 1; run("device-refused", 0);
    reset('A'); sd_fail = 1; run("pending", 0);
    reset('A'); media_marker[511] = 1; run("pending", 0);
    reset('A'); read_fail = 1; run("read-failed", 0);
    reset('A'); disk[0] ^= 1; run("current-refused", 0);
    reset('A'); run("applied-verified", 1);
    run("applied-verified", 1);
    media_marker[16] = 'R'; memset(media_marker + 32, 0, 480); memcpy(media_marker + 32, "pending", 8);
    writes = 0; run("restored-verified", 1);
    reset('A'); write_fail = 1; run("failure-original-restored", 2);
    reset('V'); file = fopen(PATCHED_PATH, "rb"); assert(file);
    assert(fread(disk, 1, BOOT_BYTES, file) == BOOT_BYTES); fclose(file); run("verified-patched", 0);
    return 0;
}
'''


def compile_and_run(directory, source, extra=()):
    binary = directory / 'test'
    libraries = [] if sys.platform == 'darwin' else ['-lcrypto']
    subprocess.run(['cc', '-Wall', '-Werror', '-Wno-deprecated-declarations', '-I', str(directory),
                    *extra, str(source), '-o', str(binary), *libraries], check=True)
    subprocess.run([str(binary)], check=True, capture_output=True)


class NativeTests(unittest.TestCase):
    def test_boot_transaction_and_write_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            compile_and_run(Path(temporary), ROOT / 'tests/c/test_boot_install.c', ['-I', str(ROOT / 'uboot')])

    def test_read_only_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            compile_and_run(Path(temporary), ROOT / 'tests/c/test_probe_guard.c', ['-I', str(ROOT / 'uboot')])

    def test_installer_command_with_generated_device_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            original = os.urandom(16777216)
            patched = bytearray(original)
            patched[5000:5008] = b'PATCHED!'
            (target / 'original.img').write_bytes(original)
            (target / 'patched.img').write_bytes(bytes(patched))
            for name in ('command.h', 'blk.h', 'mmc.h', 'fs.h', 'u-boot/sha256.h', 'linux/string.h'):
                (target / name).parent.mkdir(parents=True, exist_ok=True)
                (target / name).write_text(STUBS)
            (target / 'boot_install_core.h').write_bytes((ROOT / 'uboot/boot_install_core.h').read_bytes())
            (target / 'boot_install_device.h').write_text(device_header(
                DEVICE, hashlib.sha256(original).hexdigest(), hashlib.sha256(bytes(patched)).hexdigest()))
            source = (ROOT / 'uboot/frameoboot.c').read_text()
            for address, name in [('42000000', 'original_mem'), ('44000000', 'patched_mem'),
                                  ('46000000', 'scratch_mem'), ('41000000', 'marker_mem'),
                                  ('41001000', 'check_mem'), ('41002000', 'ext_mem')]:
                source = source.replace('(void *)0x' + address, name)
            definitions = (f'#define ORIGINAL_PATH "{target / "original.img"}"\n'
                           f'#define PATCHED_PATH "{target / "patched.img"}"\n')
            (target / 'test.c').write_text(definitions + source + HARNESS)
            compile_and_run(target, target / 'test.c')


if __name__ == '__main__':
    unittest.main()
