# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare a pristine U-Boot v2026.07 tree for one SD-boot stage."""
import json
import shutil
import struct
from pathlib import Path

from .backup import backup_command
from .markers import PROBE

UBOOT_DIR = Path(__file__).resolve().parent.parent / 'uboot'
STAGES = ('probe', 'backup', 'install')

BASE_CONFIG = '''CONFIG_ARM=y
CONFIG_EXPERT=y
# CONFIG_ARMV7_NONSEC is not set
# CONFIG_ARMV7_VIRT is not set
# CONFIG_EFI_LOADER is not set
CONFIG_ARCH_SUNXI=y
CONFIG_DEFAULT_DEVICE_TREE="allwinner/sun8i-a33-frameo"
CONFIG_OF_UPSTREAM=y
CONFIG_SPL=y
CONFIG_MACH_SUN8I_A33=y
CONFIG_DRAM_CLK=456
CONFIG_DRAM_ZQ=15291
CONFIG_SUNXI_NO_PMIC=y
CONFIG_SYS_CLK_FREQ=408000000
CONFIG_CONS_INDEX=5
CONFIG_MMC_SUNXI_SLOT_EXTRA=-1
CONFIG_ENV_IS_NOWHERE=y
# CONFIG_ENV_IS_IN_FAT is not set
# CONFIG_ENV_IS_IN_MMC is not set
# CONFIG_ENV_IS_IN_SPI_FLASH is not set
# CONFIG_VIDEO_SUNXI is not set
# CONFIG_VIDEO is not set
# CONFIG_USB is not set
# CONFIG_NET is not set
# CONFIG_MTD is not set
# CONFIG_SPI is not set
# CONFIG_SCSI is not set
# CONFIG_SATA is not set
# CONFIG_BOOTSTD is not set
# CONFIG_DISTRO_DEFAULTS is not set
# CONFIG_USE_PREBOOT is not set
# CONFIG_CMD_SAVEENV is not set
# CONFIG_CMD_BOOTM is not set
# CONFIG_CMD_BOOTZ is not set
# CONFIG_CMD_BOOTEFI is not set
# CONFIG_CMD_SOURCE is not set
CONFIG_BOOTDELAY=-2
CONFIG_USE_BOOTCOMMAND=y
CONFIG_CMD_MMC=y
CONFIG_CMD_MEMORY=y
CONFIG_CMD_ITEST=y
CONFIG_HUSH_PARSER=y
CONFIG_FRAMEO_READ_ONLY=y
CONFIG_CMD_HASH=y
CONFIG_CMD_EXPORTENV=y
# CONFIG_USE_PRIVATE_LIBGCC is not set
'''

STAGE_CONFIG = {
    'probe': 'CONFIG_SYS_CBSIZE=4096\n',
    'backup': ('CONFIG_FRAMEO_BACKUP=y\nCONFIG_FS_EXFAT=y\nCONFIG_CMD_FS_GENERIC=y\n'
               'CONFIG_DOS_PARTITION=y\nCONFIG_SYS_64BIT_LBA=y\nCONFIG_CMD_MMC_REG=y\n'
               'CONFIG_SYS_CBSIZE=16384\n'),
    'install': ('CONFIG_SYS_CBSIZE=4096\nCONFIG_CMD_FRAMEOBOOT=y\nCONFIG_FS_EXFAT=y\n'
                'CONFIG_DOS_PARTITION=y\nCONFIG_SYS_64BIT_LBA=y\n'
                '# CONFIG_BLOCK_CACHE is not set\n# CONFIG_CMD_BLOCK_CACHE is not set\n'
                '# CONFIG_FRAMEO_BACKUP is not set\n'),
}

DEVICE_TREE = '''// SPDX-License-Identifier: GPL-2.0+
/dts-v1/;
#include "sun8i-a33.dtsi"
/ {
    model = "Frameo 114K SD stage";
    compatible = "allwinner,sun8i-a33";
    aliases {
        serial0 = &r_uart;
        mmc0 = &mmc0;
        mmc1 = &mmc2;
    };
    chosen {
        stdout-path = "serial0:115200n8";
    };
};
&mmc0 {
    bus-width = <4>;
    broken-cd;
    max-frequency = <25000000>;
    status = "okay";
};
&mmc1 { status = "disabled"; };
&mmc2 {
    pinctrl-names = "default";
    pinctrl-0 = <&mmc2_8bit_pins>;
    bus-width = <8>;
    non-removable;
    max-frequency = <25000000>;
    status = "okay";
};
&r_uart {
    pinctrl-names = "default";
    pinctrl-0 = <&r_uart_pins_a>;
    status = "okay";
};
'''

DRIVER_INCLUDE = '''#include "sunxi_mmc.h"
#include "probe_guard.h"
#if !defined(CONFIG_XPL_BUILD) && defined(CONFIG_CMD_FRAMEOBOOT)
#include "boot_install_core.h"
extern int frameo_boot_unlocked;
#endif'''

DRIVER_GUARD = '''\tunsigned int bytecnt = 0;

\tif (IS_ENABLED(CONFIG_FRAMEO_READ_ONLY) &&
\t    !frameo_command_allowed(priv->mmc_no, cmd->cmdidx, cmd->cmdarg,
\t                            data && (data->flags & MMC_DATA_WRITE),
\t                            mmc->part_config)
#if !defined(CONFIG_XPL_BUILD) && defined(CONFIG_CMD_FRAMEOBOOT)
\t    && !(data && (data->flags & MMC_DATA_WRITE) &&
\t         boot_write_allowed(frameo_boot_unlocked, priv->mmc_no,
\t             cmd->cmdidx, cmd->cmdarg, data->blocks, data->blocksize,
\t             mmc_get_blk_desc(mmc)->hwpart, mmc->high_capacity))
#endif
\t    ) {
\t\tprintf("Frameo rejected internal storage command %u\\n", cmd->cmdidx);
\t\treturn -EPERM;
\t}
'''


def probe_command():
    """Copy internal sectors 0 and 0xa000 (vendor partition table) to SD slots at 1 and 2 MiB."""
    conditions = ' && '.join(f'itest.l *0x{0x41000000 + i * 4:x} == 0x{word:x}'
                             for i, word in enumerate(struct.unpack('<4I', PROBE)))
    samples = ''.join(
        f'setenv probe{number} read-failed; '
        f'if mmc dev 1 0 && mmc read 0x42000000 0x{source:x} 0x400; then '
        f'setenv probe{number} sd-write-failed; '
        f'if hash crc32 0x42000000 0x80000 crc{number} && mmc dev 0 0 && '
        f'mmc write 0x42000000 0x{target:x} 0x400 && '
        f'mmc read 0x43000000 0x{target:x} 0x400 && '
        f'cmp.b 0x42000000 0x43000000 0x80000; then '
        f'setenv probe{number} ok; fi; fi; '
        for number, source, target in ((0, 0, 0x800), (1, 0xa000, 0x1000)))
    return ('if mmc dev 0 0 && mmc read 0x41000000 0x1800 1; then '
            f'if {conditions}; then mw.l 0x41000000 0x214e5552 1; '
            'if mmc write 0x41000000 0x1800 1; then ' + samples +
            'if mmc dev 0 0; then '
            'if env export -t -s 0x1e0 0x41000020 probe0 probe1 crc0 crc1; then '
            'mw.l 0x41000000 0x454e4f44 1; mmc write 0x41000000 0x1800 1; '
            'fi; fi; fi; fi; fi')


def c_bytes(name, data):
    return f'static const unsigned char {name}[{len(data)}] = {{' + ','.join(f'0x{b:02x}' for b in data) + '};'


def device_header(device, original_sha256, patched_sha256):
    """Per-unit constants for frameoboot.c, taken from the owner's own backup."""
    blocks = device['userblocks']
    cid = ', '.join(f'0x{device[f"cid{i}"]:08x}' for i in range(4))
    return '\n'.join([
        '/* Generated by frameo114k build install. Do not edit. */',
        f'static const unsigned int device_cid[4] = {{{cid}}};',
        f'static const unsigned long long device_user_bytes = {blocks * 512}ULL;',
        c_bytes('device_sector_count', blocks.to_bytes(4, 'little')),
        c_bytes('original_hash', bytes.fromhex(original_sha256)),
        c_bytes('patched_hash', bytes.fromhex(patched_sha256)), ''])


def _append_once(path, marker, text):
    content = path.read_text()
    if marker not in content:
        path.write_text(content + text)


def _replace_once(path, old, new):
    content = path.read_text()
    if content.count(old) != 1:
        raise ValueError(f'Unexpected U-Boot source in {path.name}; expected v2026.07.')
    path.write_text(content.replace(old, new))


def prepare(source, stage, install_header=None):
    if stage not in STAGES:
        raise ValueError(f'Unknown stage: {stage}')
    source = Path(source)
    command = {'probe': probe_command, 'backup': backup_command,
               'install': lambda: 'frameoboot; while true; do sleep 1; done'}[stage]()
    config = BASE_CONFIG + STAGE_CONFIG[stage] + 'CONFIG_BOOTCOMMAND=' + json.dumps(command) + '\n'
    (source / f'configs/frameo_{stage}_defconfig').write_text(config)
    (source / 'dts/upstream/src/arm/allwinner/sun8i-a33-frameo.dts').write_text(DEVICE_TREE)
    shutil.copyfile(UBOOT_DIR / 'probe_guard.h', source / 'drivers/mmc/probe_guard.h')
    shutil.copyfile(UBOOT_DIR / 'boot_install_core.h', source / 'drivers/mmc/boot_install_core.h')
    _append_once(source / 'drivers/mmc/Kconfig', 'config FRAMEO_READ_ONLY',
                 '\nconfig FRAMEO_READ_ONLY\n\tbool "Frameo internal storage read guard"\n'
                 '\tdepends on MMC_SUNXI\n\tdefault n\n'
                 '\nconfig FRAMEO_BACKUP\n\tbool "Frameo read-only backup"\n'
                 '\tdepends on FRAMEO_READ_ONLY\n\tdefault n\n')
    driver = source / 'drivers/mmc/sunxi_mmc.c'
    if 'probe_guard.h' not in driver.read_text():
        _replace_once(driver, '#include "sunxi_mmc.h"', DRIVER_INCLUDE)
        _replace_once(driver, '\tunsigned int bytecnt = 0;\n', DRIVER_GUARD)
    if stage == 'install':
        if install_header is None:
            raise ValueError('The install stage needs a device header.')
        for name in ('frameoboot.c', 'boot_install_core.h'):
            shutil.copyfile(UBOOT_DIR / name, source / 'cmd' / name)
        (source / 'cmd/boot_install_device.h').write_text(install_header)
        _append_once(source / 'cmd/Makefile', 'frameoboot.o',
                     '\nobj-$(CONFIG_$(PHASE_)CMD_FRAMEOBOOT) += frameoboot.o\n')
        _append_once(source / 'cmd/Kconfig', 'config CMD_FRAMEOBOOT',
                     '\nconfig CMD_FRAMEOBOOT\n\tbool "Frameo verified boot installer"\n'
                     '\tdepends on FRAMEO_READ_ONLY\n')
    return f'frameo_{stage}_defconfig'
