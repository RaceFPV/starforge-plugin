# Node Flasher

A RotorHazard plugin that writes ESP32 firmware to a **node board over USB**,
from the timer's own web UI - no PC at the bench.

It is deliberately **not tied to one vendor**. A board preset says which chip it
is and where a release's parts go; the custom mode writes any single firmware
image at any offset, so a board from another project works without a plugin per
vendor.

## Board presets

| preset | chip | writes |
|---|---|---|
| StarForge C5 (DevKitC / C5-Zero / XIAO) | ESP32-C5 | bootloader `0x2000`, partitions `0x8000`, app `0x10000` |
| StarForge C3 | ESP32-C3 | `0x0`, `0x8000`, `0x10000` |
| StarForge S3 | ESP32-S3 | `0x0`, `0x8000`, `0x10000` |
| Generic ESP32-C6 (parts) | ESP32-C6 | `0x0`, `0x8000`, `0x10000` |
| Merged image at 0x0 | auto | one image (ESP-IDF `merge_bin`, FPVGate, most C3/C6/S3) |
| Merged image at 0x1000 | auto | one image (ESP32 / ESP32-S2) |
| Merged image at 0x2000 | auto | one image (ESP32-C5) |
| Custom | you pick | one image at the offset you type |

FPVGate publishes its firmware as a merged image through its own browser
flasher; this plugin can write the same file if you have it locally - it does
not replace that project's flasher, and needs nothing from it.

## How it works

- Panel: **Settings → Node flasher**, with a board preset, firmware folder, image
  file, chip and offset, one button and a status line.
- Only ports **outside `GENERAL.SERIAL_PORTS`** are offered, so the board the
  timer is reading is never a candidate.
- Uses `esptool` as a library inside the RotorHazard process, with
  `--before default_reset --after watchdog-reset`; when the automatic reset misses
  it prints the hold-BOOT / tap-RESET / release-BOOT sequence.

## Requirements

- RotorHazard 4.3+ / RHAPI 1.7+ (panel markdown and buttons need a server that
  delivers them).
- `esptool` >= 4.8.1 importable by the Python running RotorHazard:

      python3 -m pip install esptool

## Install

Community database (once listed): **Settings → Plugins → Browse Community
Plugins**.

Manually: copy `custom_plugins/node_flasher/` into the server's `plugins/`
directory and restart RotorHazard.

## Limitations

- A board the timer is reading cannot be flashed - stop the timer or use a spare
  port.
- USB only: the board must be on the machine running RotorHazard.
- It writes what you point it at; it does not download firmware or know a
  project's release layout beyond the presets above. Add a preset when a board's
  offsets are known and stable.

## Development

    python3 tests/test_flasher_plugin.py

Stubs the RHAPI surface and esptool: port selection, preset resolution, custom
offset parsing, refusals and failure paths.

Layout follows the RotorHazard community plugin requirements: one plugin per
repository, `custom_plugins/<domain>/`, RHFest validated.
