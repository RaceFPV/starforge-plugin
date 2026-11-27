"""StarForge flasher: update a bare ESP32-C5 node from the RotorHazard UI.

Plug the board into the machine running RotorHazard, on a USB port the timer is
not using, then press the button in this panel. A board that the timer is
currently reading cannot be flashed - the server owns its port.
"""

import contextlib
import io
import json
import os
from glob import glob as _glob

PANEL = 'starforge_flasher'
PANEL_LABEL = 'StarForge flasher'
FIRMWARE_FIELD = 'firmware_dir'
DEFAULT_FIRMWARE = '~/starforge-firmware'

# C5 ROM bootloader sits at 0x2000, unlike the ESP32/S2 targets at 0x1000.
PARTS = (
    ('0x2000', 'bootloader.bin'),
    ('0x8000', 'partitions.bin'),
    ('0x10000', 'firmware.bin'),
)

INTRO = (
    'Flash a **bare** StarForge node without leaving RotorHazard.\n\n'
    'Plug the ESP32-C5 into this machine using its USB port, then press the '
    'button below. The board the timer is reading is not offered: stop the '
    'timer, or use a spare port.'
)


class Flasher:
    def __init__(self, rhapi):
        self._rhapi = rhapi
        self._busy = False

    # ---------------------------------------------------------------- RHAPI
    def initialize(self, _args):
        rh = self._rhapi
        rh.ui.register_panel(PANEL, PANEL_LABEL, 'settings', order=2)
        rh.ui.register_markdown(PANEL, 'sf_intro', INTRO)

        from RHUI import UIField, UIFieldType
        rh.fields.register_option(
            UIField(FIRMWARE_FIELD, 'Firmware folder',
                    field_type=UIFieldType.TEXT,
                    desc='Folder holding bootloader.bin, partitions.bin and firmware.bin',
                    value=DEFAULT_FIRMWARE,
                    persistent_section=PANEL),
            PANEL)

        rh.ui.register_markdown(PANEL, 'sf_state', 'Ready.')
        rh.ui.register_quickbutton(PANEL, 'sf_flash', 'Flash the free board', self.flash)

    # ------------------------------------------------------------ inspection
    def firmware_dir(self):
        value = None
        try:
            value = self._rhapi.config.get(PANEL, FIRMWARE_FIELD)
        except Exception:  # noqa: BLE001 - a missing setting is normal
            value = None
        return os.path.expanduser(str(value or DEFAULT_FIRMWARE))

    def configured_ports(self):
        """Ports the server is using - never candidates for flashing."""
        ports = []
        try:
            ports = self._rhapi.config.get('GENERAL', 'SERIAL_PORTS') or []
        except Exception:  # noqa: BLE001
            ports = []
        if isinstance(ports, str):
            text = ports.strip()
            if text.startswith('['):
                try:
                    ports = json.loads(text)
                except ValueError:
                    ports = [p for p in text.split(',')]
            else:
                ports = [p for p in text.split(',')]
        return [os.path.realpath(str(p)) for p in ports if str(p).strip()]

    def free_ports(self):
        """Serial ports present on this machine that the timer is not using."""
        used = set(self.configured_ports())
        found = {}
        for pattern in ('/dev/ttyACM*', '/dev/ttyUSB*'):
            for path in sorted(_glob(pattern)):
                real = os.path.realpath(path)
                if path in used or real in used:
                    continue
                found.setdefault(real, path)
        return sorted(found.values())

    # --------------------------------------------------------------- flashing
    def flash(self, _arg=None):
        if self._busy:
            return self._report('Already flashing - wait for the current write to finish.')
        ports = self.free_ports()
        if not ports:
            return self._report(
                'No free board found. Plug the ESP32-C5 into this machine on a '
                'port the timer is not reading, then try again.')
        if len(ports) > 1:
            return self._report(
                'Several free ports (%s). Unplug the others so there is no doubt '
                'which board gets the firmware.' % ', '.join(ports))
        return self.flash_port(ports[0])

    def flash_port(self, port):
        firmware = self.firmware_dir()
        missing = [name for _, name in PARTS
                   if not os.path.isfile(os.path.join(firmware, name))]
        if missing:
            return self._report('Missing %s in %s. Point "Firmware folder" at the '
                                'unpacked release.' % (', '.join(missing), firmware))

        argv = ['--chip', 'esp32c5', '--port', port, '--baud', '460800',
                '--before', 'default_reset', '--after', 'watchdog-reset',
                'write_flash']
        for address, name in PARTS:
            argv += [address, os.path.join(firmware, name)]

        self._busy = True
        self._report('Flashing %s ...' % port)
        try:
            ok, output = self._run_esptool(argv)
        finally:
            self._busy = False

        if not ok:
            return self._report(
                'Flash failed.\n\nHold BOOT, tap RESET, release BOOT, then try '
                'again.\n\n%s' % output[-800:])
        return self._report('Flashed %s. The timer should find its seats on the '
                            'next scan.' % port)

    def _esptool(self):
        try:
            import esptool  # noqa: PLC0415 - optional, installed by the user
        except ImportError:
            return None, ('esptool is not installed for the plugin bridge python.\n'
                          'Install it with: python3 -m pip install esptool')
        return esptool, None

    def _run_esptool(self, argv):
        module, problem = self._esptool()
        if problem:
            return False, problem
        buf = io.StringIO()
        code = 0
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                module.main(argv)
        except SystemExit as exc:
            code = exc.code or 0
        except Exception as exc:  # noqa: BLE001 - report anything esptool raises
            return False, '%s: %s' % (type(exc).__name__, exc)
        return code == 0, buf.getvalue()

    # ------------------------------------------------------------------ misc
    def _report(self, text):
        try:
            self._rhapi.ui.update_markdown({'panel': PANEL, 'name': 'sf_state',
                                            'desc': text})
        except Exception:  # noqa: BLE001 - the return value is the fallback
            pass
        try:
            first = text.splitlines()[0] if text else ''
            self._rhapi.ui.message_notify(first[:120])
        except Exception:  # noqa: BLE001
            pass
        return {'status': text}


def initialize(rhapi):
    return Flasher(rhapi)
