# Hardware notes

Observed on one Frameo 114K over root ADB.

| Item | Value |
| --- | --- |
| SoC | Allwinner A33, 4x Cortex-A7, up to 1.344 GHz, ARMv7 32-bit only (`armeabi-v7a`) |
| GPU | Mali-400 MP2 (vendor `mali` module) |
| RAM | 1 GB, plus 320 MB zram |
| eMMC | 32 GB class, 4 MiB boot areas. Other units may use other sizes |
| Display | 1280 x 800, 160 dpi, `ro.sf.rotation=90` |
| Touch | Silead GSL1680 family, vendor module `gslX680new` |
| Accelerometer | `mir3da` |
| Wi-Fi and Bluetooth | XRadio XR819, vendor modules `xradio_wlan`, `xradio_core`, `xradio_mac` |
| Kernel | 3.4.39, Allwinner BSP |
| Android | 6.0.1, API 23, security patch 2016-07-05, `test-keys`, SELinux reported `Permissive` |
| USB | Did not enumerate on the tested unit, in normal or FEL mode |

## Partitions

From the vendor `softw411` table at eMMC sector 0xa000. Physical sector = vendor sector + 40960.

| Name | Physical sector | Size |
| --- | --- | --- |
| bootloader | 73728 | 32 MiB |
| env | 139264 | 16 MiB |
| boot | 172032 | 16 MiB |
| system | 204800 | 1 GiB |
| misc | 2301952 | 16 MiB |
| recovery | 2334720 | 32 MiB |
| cache | 2400256 | 768 MiB |
| metadata, private, frp, empty, alog, media_data | after cache | small |
| UDISK (`/data`) | 4268032 (0x412000) | rest of the eMMC |

The firmware backup covers everything before UDISK, plus both eMMC boot areas.

## Software on the stock firmware

- `net.frameo.frame`: the Frameo app. A privileged system app that is the home screen.
- `com.adups.fota`: the vendor's over-the-air updater.
- Allwinner test apps: `com.along.factorytest`, `com.softwinner.dragonaging`,
  `com.softwinner.dragonfire`, `com.softwinner.dragonphone`, `com.android.agingtest`.
- SystemUI is disabled. `config_showNavigationBar` is false and `status_bar_height` is 0dp.
- The AOSP Launcher2, Settings and Browser are present. System WebView is 106.0.5249.126.

## Newer Android

No newer Android build is known for this board. LineageOS and GloDroid do not support the A33.
Mainline Linux supports the A33 display and the GSL1680 touch controller. The XR819 Wi-Fi chip
only has an out-of-tree driver, and the Mali-400 only has the GLES 2 `lima` driver. A newer
Android would be a porting project.
