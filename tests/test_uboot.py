# SPDX-License-Identifier: GPL-2.0-or-later
import tempfile
import unittest
from pathlib import Path

from frameo114k import uboot

DEVICE = {'userblocks': 0x1d1f000, 'bootblocks': 0x2000,
          'cid0': 0x01020304, 'cid1': 0x05060708, 'cid2': 0x090a0b0c, 'cid3': 0x0d0e0f10}


def fake_tree(root):
    for name in ('configs', 'dts/upstream/src/arm/allwinner', 'drivers/mmc', 'cmd'):
        (root / name).mkdir(parents=True)
    (root / 'drivers/mmc/Kconfig').write_text('menu "MMC"\n')
    (root / 'drivers/mmc/sunxi_mmc.c').write_text(
        '#include "sunxi_mmc.h"\nstatic int f(void)\n{\n\tunsigned int bytecnt = 0;\n\treturn 0;\n}\n')
    (root / 'cmd/Makefile').write_text('obj-y += help.o\n')
    (root / 'cmd/Kconfig').write_text('menu "Commands"\n')


class UbootTests(unittest.TestCase):
    def test_device_header_uses_inputs(self):
        header = uboot.device_header(DEVICE, '00' * 32, 'ff' * 32)
        self.assertIn('{0x01020304, 0x05060708, 0x090a0b0c, 0x0d0e0f10}', header)
        self.assertIn('15634268160ULL', header)
        self.assertIn('device_sector_count[4] = {0x00,0xf0,0xd1,0x01}', header)

    def test_prepare_all_stages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_tree(root)
            for stage in uboot.STAGES:
                header = uboot.device_header(DEVICE, '00' * 32, 'ff' * 32) if stage == 'install' else None
                self.assertEqual(uboot.prepare(root, stage, header), f'frameo_{stage}_defconfig')
            driver = (root / 'drivers/mmc/sunxi_mmc.c').read_text()
            self.assertEqual(driver.count('frameo_command_allowed'), 1)
            self.assertIn('CONFIG_CMD_FRAMEOBOOT=y', (root / 'configs/frameo_install_defconfig').read_text())
            self.assertIn('CONFIG_FRAMEO_BACKUP=y', (root / 'configs/frameo_backup_defconfig').read_text())
            self.assertEqual((root / 'cmd/Makefile').read_text().count('frameoboot.o'), 1)
            self.assertTrue((root / 'cmd/boot_install_device.h').exists())

    def test_install_needs_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            fake_tree(Path(temporary))
            with self.assertRaises(ValueError):
                uboot.prepare(temporary, 'install')


if __name__ == '__main__':
    unittest.main()
