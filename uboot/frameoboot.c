// SPDX-License-Identifier: GPL-2.0+
// Copyright (C) 2026 Pawel Mikolajczuk
/*
 * Boot-partition-only installer for the Frameo 114K. Loads the original and
 * patched boot images from the SD card, checks their hashes and the internal
 * eMMC identity, then applies, verifies or restores the boot partition.
 * Device identity and image hashes come from boot_install_device.h, which is
 * generated per unit by `frameo114k build install`.
 */
#include <command.h>
#include <blk.h>
#include <mmc.h>
#include <fs.h>
#include <u-boot/sha256.h>
#include <linux/string.h>
#include "boot_install_core.h"
#include "boot_install_device.h"

#define BOOT_BYTES 0x1000000
#define BOOT_BLOCKS 0x8000
#define BOOT_SECTOR 0x2a000
#define RESULT_SECTOR 0x1800

int frameo_boot_unlocked;
static unsigned char *const original = (void *)0x42000000;
static unsigned char *const patched = (void *)0x44000000;
static unsigned char *const scratch = (void *)0x46000000;
static unsigned char *const marker = (void *)0x41000000;
static unsigned char *const check = (void *)0x41001000;
static struct blk_desc *sd;
static const char challenge[16] = "FRAMEO114KBOOT01";

static int report(const char *state)
{
    memset(marker + 32, 0, 480);
    strncpy((char *)marker + 32, state, 479);
    if (blk_dwrite(sd, RESULT_SECTOR, 1, marker) != 1 ||
        blk_dread(sd, RESULT_SECTOR, 1, check) != 1 || memcmp(marker, check, 512)) {
        puts("Frameo boot result write failed\n");
        return 0;
    }
    printf("Frameo boot: %s\n", state);
    return 1;
}
static int load_image(const char *name, unsigned char *target, const unsigned char *hash)
{
    loff_t size, actual;
    unsigned char digest[32];
    if (fs_set_blk_dev("mmc", "0:1", FS_TYPE_EXFAT) ||
        fs_size(name, &size) || size != BOOT_BYTES ||
        fs_set_blk_dev("mmc", "0:1", FS_TYPE_EXFAT) ||
        fs_read(name, (ulong)target, 0, BOOT_BYTES, &actual) || actual != BOOT_BYTES) {
        return 0;
    }
    sha256_csum_wd(target, BOOT_BYTES, digest, 65536);
    return !memcmp(digest, hash, 32);
}
static int read_boot(void *context, unsigned char *target)
{
    return blk_dread(context, BOOT_SECTOR, BOOT_BLOCKS, target) == BOOT_BLOCKS;
}
static int write_boot(void *context, const unsigned char *source)
{
    ulong count;
    frameo_boot_unlocked = 1;
    count = blk_dwrite(context, BOOT_SECTOR, BOOT_BLOCKS, source);
    frameo_boot_unlocked = 0;
    return count == BOOT_BLOCKS;
}
static int device_matches(struct mmc *mmc)
{
    unsigned char *ext = (void *)0x41002000;
    if (IS_SD(mmc) || !mmc->high_capacity || memcmp(mmc->cid, device_cid, sizeof(device_cid)) ||
        mmc->read_bl_len != 512 || mmc->write_bl_len != 512 ||
        mmc->capacity_user != device_user_bytes || mmc->capacity_boot != 4194304 ||
        mmc_get_blk_desc(mmc)->hwpart != 0 || mmc_send_ext_csd(mmc, ext)) {
        return 0;
    }
    return ext[33] == 0 && (ext[179] & 7) == 0 && ext[226] == 32 &&
        !memcmp(ext + 212, device_sector_count, 4);
}
static int do_frameoboot(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
    struct mmc *card, *internal;
    struct boot_io io;
    enum boot_outcome outcome;
    const char *states[] = {"current-refused", "read-failed", "already-desired",
        "applied-verified", "restored-verified", "failure-original-restored", "recovery-failed"};
    unsigned mode;
    frameo_boot_unlocked = 0;
    card = find_mmc_device(0);
    if (!card || mmc_init(card)) { return CMD_RET_FAILURE; }
    sd = mmc_get_blk_desc(card);
    if (!IS_SD(card) || sd->blksz != 512 ||
        blk_dread(sd, RESULT_SECTOR, 1, marker) != 1 ||
        memcmp(marker, challenge, 16) || memcmp(marker + 32, "pending", 8)) {
        return CMD_RET_FAILURE;
    }
    mode = marker[16];
    if (mode != 'A' && mode != 'R' && mode != 'V') { return CMD_RET_FAILURE; }
    memset(check, 0, 512);
    memcpy(check, challenge, 16);
    check[16] = mode;
    memcpy(check + 32, "pending", 8);
    if (memcmp(marker, check, 512)) { return CMD_RET_FAILURE; }
    if (!report("running")) { return CMD_RET_FAILURE; }
    if (!load_image("/frameo-boot-v1/original.img", original, original_hash) ||
        !load_image("/frameo-boot-v1/patched.img", patched, patched_hash)) {
        report("image-refused"); return CMD_RET_FAILURE;
    }
    internal = find_mmc_device(1);
    if (!internal || mmc_init(internal) || !device_matches(internal)) {
        report("device-refused"); return CMD_RET_FAILURE;
    }
    io.context = mmc_get_blk_desc(internal);
    io.read = read_boot;
    io.write = write_boot;
    if (mode == 'V') {
        if (!read_boot(io.context, scratch)) {
            report("read-failed"); return CMD_RET_FAILURE;
        }
        report(!memcmp(scratch, original, BOOT_BYTES) ? "verified-original" :
               !memcmp(scratch, patched, BOOT_BYTES) ? "verified-patched" : "current-refused");
        return CMD_RET_SUCCESS;
    }
    outcome = boot_transaction(&io, original, patched, scratch, BOOT_BYTES, mode == 'R');
    report(states[outcome]);
    return outcome == BOOT_APPLIED || outcome == BOOT_RESTORED || outcome == BOOT_ALREADY ?
        CMD_RET_SUCCESS : CMD_RET_FAILURE;
}

U_BOOT_CMD(frameoboot, 1, 0, do_frameoboot,
           "verified Frameo boot-only install or restore", "");
