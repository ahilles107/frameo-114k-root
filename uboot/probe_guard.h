/* SPDX-License-Identifier: GPL-2.0+ */
/* Copyright (C) 2026 Pawel Mikolajczuk */
#ifndef FRAMEO_PROBE_GUARD_H
#define FRAMEO_PROBE_GUARD_H
static inline int frameo_command_allowed(unsigned controller, unsigned command,
                                        unsigned argument, int writes_data,
                                        unsigned partition_config)
{
    unsigned index, value;
    if (controller == 0) {
        return 1;
    }
    if (writes_data) {
        return 0;
    }
    switch (command) {
    case 0: case 1: case 2: case 3: case 7: case 8: case 9: case 10:
    case 12: case 13: case 16: case 17: case 18: case 41: case 55:
        return 1;
    case 6:
        if ((argument & 0xff0000ffu) != 0x03000000u) {
            return 0;
        }
        index = (argument >> 16) & 255;
        value = (argument >> 8) & 255;
        if (index == 179) {
#ifdef CONFIG_FRAMEO_BACKUP
            return (value & 0xf8) == (partition_config & 0xf8) && (value & 7) <= 2;
#else
            return value == (partition_config & 0xf8);
#endif
        }
        return (index == 175 && value <= 1) ||
               (index == 183 && value <= 2) || (index == 185 && value <= 1);
    default:
        return 0;
    }
}
#endif
