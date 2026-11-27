# StarForge Flasher

Flash a node board from your RotorHazard timer — no laptop at the bench.

Plug an ESP32 board into the Pi, open Settings, press **Flash**. Done.

Made for StarForge boards, happy with others: pick a preset, or point it at any
firmware image and tell it where it goes.

## What you get

A **StarForge Flasher** panel in RotorHazard's Settings page with a board picker,
a folder for your firmware, one button, and a status line that says what is
happening.

## Boards

| Board | |
|---|---|
| StarForge C5 — DevKitC, C5-Zero, XIAO | ✔ |
| StarForge C3, StarForge S3 | ✔ |
| Generic ESP32-C6 (bootloader / partitions / app) | ✔ |
| Anything shipping a merged image — FPVGate and most ESP-IDF projects | ✔ "Merged image" preset |
| Something else | ✔ Custom: choose the chip and the offset |

If your board's offsets become well known, a preset for it is a few lines — pull
requests welcome.

## Install

**From the plugin list:** Settings → Plugins → Browse Community Plugins.

**By hand:** copy `custom_plugins/starforge_flasher/` into RotorHazard's
`plugins/` folder and restart.

One dependency — esptool 4.8.1 or later. RotorHazard installs it for you when the
plugin is installed; if your server does not install plugin dependencies (or you
copied the folder in by hand), install it once:

```bash
python3 -m pip install esptool
```

## Flashing a board

1. Unpack the firmware you want to flash, or grab a merged image.
2. Choose the board preset and point it at the folder or file.
3. Plug the board into the timer's USB port.
4. Press **Flash the free board**.

Not starting on its own? Hold BOOT, tap RESET, release BOOT, then press Flash
again. The panel tells you this too if a write fails.

## Good to know

- **A board the timer is reading can't be flashed.** Its port is skipped whether it
  is listed in `GENERAL.SERIAL_PORTS` or simply held open by another process, so
  stop the timer or use a spare port.
- USB only: the board has to be on the machine running RotorHazard.
- It writes the firmware you give it; it doesn't download releases by itself.

## Coming soon

- **FPVGate and other firmware, available to download** right from the panel.
- More board presets as projects publish their layouts.
- Version upgrades: pick the release you want instead of unpacking a zip.

## Development

```bash
python3 tests/test_flasher_plugin.py
```

The tests stub RotorHazard and esptool, so they need no server and no hardware:
board presets, merged images, custom offsets, the refusals and the failure paths.

Layout follows the RotorHazard community plugin rules — one plugin per
repository, `custom_plugins/<domain>/`, validated by
[RHFest](https://github.com/RotorHazard/rhfest-action).
