// SPDX-License-Identifier: GPL-2.0+
#include <assert.h>
#include "probe_guard.h"

int main(void)
{
    unsigned cmd, index, value;
    for (cmd = 0; cmd < 64; cmd++) {
        assert(frameo_command_allowed(0, cmd, 0, 1, 0));
        assert(!frameo_command_allowed(2, cmd, 0, 1, 0));
    }
    assert(frameo_command_allowed(2, 17, 0, 0, 0));
    assert(frameo_command_allowed(2, 18, 40960, 0, 0));
    for (cmd = 24; cmd <= 38; cmd++) {
        assert(!frameo_command_allowed(2, cmd, 0, 0, 0));
    }
    assert(!frameo_command_allowed(2, 42, 0, 0, 0));
    assert(!frameo_command_allowed(2, 56, 0, 0, 0));
    for (index = 0; index < 256; index++) {
        for (value = 0; value < 256; value++) {
            unsigned arg = (3u << 24) | (index << 16) | (value << 8);
            int expected = (index == 175 && value <= 1) ||
                (index == 183 && value <= 2) || (index == 185 && value <= 1) ||
                (index == 179 && value == 0x48);
            assert(frameo_command_allowed(2, 6, arg, 0, 0x48) == expected);
            assert(!frameo_command_allowed(2, 6, arg & 0xffffff, 0, 0x48));
        }
    }
    assert(!frameo_command_allowed(2, 6, 0x03b30800, 0, 0x48));
    assert(!frameo_command_allowed(2, 6, 0x03b34900, 0, 0x48));
    return 0;
}
