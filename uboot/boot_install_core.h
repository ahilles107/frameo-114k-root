/* SPDX-License-Identifier: GPL-2.0+ */
/* Copyright (C) 2026 Pawel Mikolajczuk */
#ifndef FRAMEO_BOOT_INSTALL_CORE_H
#define FRAMEO_BOOT_INSTALL_CORE_H
#include <stddef.h>
#include <string.h>

enum boot_outcome {
    BOOT_REFUSED, BOOT_READ_FAILED, BOOT_ALREADY, BOOT_APPLIED,
    BOOT_RESTORED, BOOT_RECOVERED, BOOT_RECOVERY_FAILED
};
struct boot_io {
    void *context;
    int (*read)(void *, unsigned char *);
    int (*write)(void *, const unsigned char *);
};
static inline int boot_write_allowed(int unlocked, unsigned controller,
    unsigned command, unsigned sector, unsigned blocks, unsigned blocksize,
    unsigned hwpart, int high_capacity)
{
    return unlocked && controller == 2 && (command == 24 || command == 25) &&
        hwpart == 0 && high_capacity && blocksize == 512 && blocks &&
        sector >= 0x2a000 && sector < 0x32000 && blocks <= 0x32000 - sector &&
        (command != 24 || blocks == 1);
}
static inline enum boot_outcome boot_transaction(struct boot_io *io,
    const unsigned char *original, const unsigned char *patched,
    unsigned char *scratch, size_t size, int rollback)
{
    const unsigned char *desired = rollback ? original : patched;
    size_t i;
    if (!io->read(io->context, scratch)) { return BOOT_READ_FAILED; }
    if (!memcmp(scratch, desired, size)) { return BOOT_ALREADY; }
    if (rollback) {
        for (i = 0; i < size; i++) {
            if (scratch[i] != original[i] && scratch[i] != patched[i]) {
                return BOOT_REFUSED;
            }
        }
    } else if (memcmp(scratch, original, size)) {
        return BOOT_REFUSED;
    }
    if (io->write(io->context, desired) && io->read(io->context, scratch) &&
        !memcmp(scratch, desired, size)) {
        return rollback ? BOOT_RESTORED : BOOT_APPLIED;
    }
    if (io->write(io->context, original) && io->read(io->context, scratch) &&
        !memcmp(scratch, original, size)) {
        return BOOT_RECOVERED;
    }
    return BOOT_RECOVERY_FAILED;
}
#endif
