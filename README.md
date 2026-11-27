# StarForge Flasher

A RotorHazard plugin that flashes a bare **StarForge ESP32-C5** node over USB
from the timer's own web UI - no PC at the bench.

![RotorHazard](https://img.shields.io/badge/RotorHazard-plugin-blue)

## What it does

Adds a **StarForge flasher** panel to RotorHazard's settings page with:

- a **Firmware folder** setting - point it at an unpacked StarForge release
  (`bootloader.bin`, `partitions.bin`, `firmware.bin`);
- a **Flash the free board** button - writes the release to whichever ESP32-C5
  is plugged into the timer's machine and is not already a timing node;
- a status line that reports progress and the outcome in place.

Flashing uses `esptool` as a Python library inside the RotorHazard plugin
process, at the C5 addresses: bootloader `0x2000`, partitions `0x8000`, app
`0x10000`. When the automatic reset over native USB misses, the panel prints the
hold-BOOT / tap-RESET / release-BOOT sequence.

## Requirements

- RotorHazard 4.3 or later (RHAPI 1.7 or later). Panel markdown and buttons
  need a server that delivers them.
- `esptool` (>= 4.8.1) importable by the Python running RotorHazard:

      python3 -m pip install esptool

  The panel says so if it is missing.

## Install

Once listed in the community database: **Settings -> Plugins -> Browse
Community Plugins** in RotorHazard.

Manually: copy `custom_plugins/starforge_flasher/` into the server's
`plugins/` directory (next to `config.json`) and restart RotorHazard.

## Limits

- **A board the timer is reading cannot be flashed.** The server owns that
  serial port; this plugin only offers ports outside `GENERAL.SERIAL_PORTS`.
  Stop the timer, or plug in a spare board.
- USB only - the board has to be on the machine running RotorHazard. It resumes
  as a timing node once flashed.
- It writes the folder you point it at; it does not download releases. Use the
  StarForge flasher (`flash_tool/` in
  [starforge-legacy](https://github.com/RaceFPV/starforge-legacy)) if you want
  one-click firmware downloads on a PC.

## Development

    python3 tests/test_flasher_plugin.py

The tests stub the RHAPI surface and esptool, so they need no server and no
hardware: port selection, the refusals, the flash addresses and the failure
paths.

Layout follows the RotorHazard community plugin requirements: one plugin per
repository, code in `custom_plugins/<domain>/`, validated by
[RHFest](https://github.com/RotorHazard/rhfest-action).
