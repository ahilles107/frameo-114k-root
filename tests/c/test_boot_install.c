// SPDX-License-Identifier: GPL-2.0+
// Copyright (C) 2026 Pawel Mikolajczuk
#include <assert.h>
#include <string.h>
#include "boot_install_core.h"

static unsigned char disk[1024], original[1024], patched[1024], scratch[1024];
static int reads, writes, fail_write, corrupt_read, fail_read;
static int read_boot(void *context, unsigned char *out)
{
    (void)context;
    reads++;
    if (fail_read == reads) { return 0; }
    memcpy(out, disk, sizeof(disk));
    if (corrupt_read == reads) { out[0] ^= 0xff; }
    return 1;
}
static int write_boot(void *context, const unsigned char *in)
{
    (void)context;
    writes++;
    memcpy(disk, in, fail_write == writes || fail_write == -1 ? 512 : sizeof(disk));
    return fail_write != writes && fail_write != -1;
}
static enum boot_outcome run(int rollback)
{
    struct boot_io io = {0, read_boot, write_boot};
    return boot_transaction(&io, original, patched, scratch, sizeof(disk), rollback);
}
static void reset(void)
{
    reads = writes = fail_write = corrupt_read = fail_read = 0;
    memset(original, 0x11, sizeof(original));
    memset(patched, 0x22, sizeof(patched));
    memcpy(disk, original, sizeof(disk));
}
int main(void)
{
    unsigned command, part, sector, count;
    for (command = 0; command < 64; command++) {
        for (part = 0; part < 8; part++) {
            int expected = (command == 24 || command == 25) && part == 0;
            assert(boot_write_allowed(1, 2, command, 0x2a000, 1, 512, part, 1) == expected);
            assert(!boot_write_allowed(0, 2, command, 0x2a000, 1, 512, part, 1));
            assert(!boot_write_allowed(1, 1, command, 0x2a000, 1, 512, part, 1));
            assert(!boot_write_allowed(1, 2, command, 0x2a000, 1, 512, part, 0));
        }
    }
    for (sector = 0x29fff; sector <= 0x32001; sector++) {
        for (count = 0; count <= 3; count++) {
            int expected = count && sector >= 0x2a000 && sector < 0x32000 && count <= 0x32000 - sector;
            assert(boot_write_allowed(1, 2, 25, sector, count, 512, 0, 1) == expected);
        }
    }
    assert(!boot_write_allowed(1, 2, 25, 0xfffffff0, 32, 512, 0, 1));
    assert(!boot_write_allowed(1, 2, 25, 0x2a000, 1, 1024, 0, 1));
    reset(); assert(run(0) == BOOT_APPLIED && writes == 1);
    assert(!memcmp(disk, patched, sizeof(disk)));
    writes = 0; assert(run(0) == BOOT_ALREADY && writes == 0);
    assert(run(1) == BOOT_RESTORED && writes == 1);
    reset(); disk[99] = 0x44; assert(run(0) == BOOT_REFUSED && writes == 0);
    assert(run(1) == BOOT_REFUSED && writes == 0);
    reset(); fail_write = 1; assert(run(0) == BOOT_RECOVERED && writes == 2);
    assert(!memcmp(disk, original, sizeof(disk)));
    reset(); corrupt_read = 2; assert(run(0) == BOOT_RECOVERED && writes == 2);
    reset(); fail_read = 1; assert(run(0) == BOOT_READ_FAILED && writes == 0);
    reset(); fail_read = 2; assert(run(0) == BOOT_RECOVERED && writes == 2);
    reset(); fail_write = -1; assert(run(0) == BOOT_RECOVERY_FAILED && writes == 2);
    reset(); memcpy(disk, patched, 512); assert(run(0) == BOOT_REFUSED && writes == 0);
    assert(run(1) == BOOT_RESTORED && writes == 1);
    return 0;
}
