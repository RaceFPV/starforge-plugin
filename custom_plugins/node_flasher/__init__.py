"""Node flasher: write ESP32 firmware to a node board over USB from RotorHazard.

Vendor-neutral on purpose. A board preset says which chip it is and where the
release's parts go; the custom mode writes any single image at any offset, so a
board from any project can be flashed without a plugin per vendor. This is not a
StarForge-only tool: StarForge presets are simply the ones we can guarantee.

A board the timer is reading cannot be flashed - the server owns that port, so
only ports outside GENERAL.SERIAL_PORTS are ever offered.
"""

import contextlib
import io
import json
import os
from glob import glob as _glob

PANEL = 'node_flasher'
PANEL_LABEL = 'Node flasher'
PROFILE_FIELD = 'profile'
FOLDER_FIELD = 'firmware_folder'
FILE_FIELD = 'image_file'
CHIP_FIELD = 'chip'
OFFSET_FIELD = 'offset'
DEFAULT_FOLDER = '~/node-firmware'

# (label, chip, bootloader offset) - parts come from the release folder as
# bootloader.bin / partitions.bin / firmware.bin.
PARTS_PROFILES = {
    'starforge_c5': ('StarForge C5 (DevKitC / C5-Zero / XIAO)', 'esp32c5', 0x2000),
    'starforge_c3': ('StarForge C3 (SuperMini and friends)', 'esp32c3', 0x0),
    'starforge_s3': ('StarForge S3', 'esp32s3', 0x0),
    'esp32_c6': ('Generic ESP32-C6 (parts)', 'esp32c6', 0x0),
}

# (label, chip, offset) - one already-merged image, the shape most projects
# publish for browser/one-shot flashing (FPVGate's included).
SINGLE_PROFILES = {
    'merged_0x0': ('Merged image at 0x0 (ESP-IDF merge_bin, FPVGate, most C3/C6/S3)',
                   'auto', 0x0),
    'merged_0x1000': ('Merged image at 0x1000 (ESP32 / ESP32-S2)', 'auto', 0x1000),
    'merged_0x2000': ('Merged image at 0x2000 (ESP32-C5)', 'auto', 0x2000),
}

CUSTOM_PROFILE = 'custom'

CHIPS = ('auto', 'esp32', 'esp32s2', 'esp32s3', 'esp32c3', 'esp32c5', 'esp32c6', 'esp32h2')

PART_NAMES = ('bootloader.bin', 'partitions.bin', 'firmware.bin')

INTRO = (
    'Flash a **node board** over USB, from this machine.\n\n'
    'Pick the board preset - StarForge boards are listed, and *custom* writes any '
    'single firmware image at an offset you choose, so other projects\' boards '
    'work too. Presets only differ in the chip and where the parts go, so a new '
    'board usually needs no plugin change at all.\n\n'
    'The board the timer is reading is never offered: stop the timer or plug in '
    'a spare port.'
)


def _hex(value, default=None):
    try:
        text = str(value).strip()
        if not text:
            return default
        return int(text, 16) if text.lower().startswith('0x') else int(text)
    except (TypeError, ValueError):
        return default


class Flasher:
    def __init__(self, rhapi):
        self._rhapi = rhapi
        self._busy = False

    # ---------------------------------------------------------------- RHAPI
    def initialize(self, _args):
        rh = self._rhapi
        rh.ui.register_panel(PANEL, PANEL_LABEL, 'settings', order=2)
        rh.ui.register_markdown(PANEL, 'nf_intro', INTRO)

        from RHUI import UIField, UIFieldType
        try:
            from RHUI import UIFieldSelectOption
        except ImportError:  # older servers expose plain dicts
            UIFieldSelectOption = None

        def option(value, label):
            if UIFieldSelectOption is None:
                return {'value': value, 'label': label}
            return UIFieldSelectOption(value=value, label=label)

        profiles = [(CUSTOM_PROFILE, 'Custom: one image, chip and offset below')]
        profiles += [(key, value[0]) for key, value in PARTS_PROFILES.items()]
        profiles += [(key, value[0]) for key, value in SINGLE_PROFILES.items()]

        rh.fields.register_option(
            UIField(PROFILE_FIELD, 'Board', field_type=UIFieldType.SELECT,
                    value='starforge_c5',
                    options=[option(value, label) for value, label in profiles],
                    persistent_section=PANEL),
            PANEL)
        rh.fields.register_option(
            UIField(FOLDER_FIELD, 'Firmware folder',
                    field_type=UIFieldType.TEXT,
                    desc='Folder holding the release parts (presets) or the image',
                    value=DEFAULT_FOLDER, persistent_section=PANEL),
            PANEL)
        rh.fields.register_option(
            UIField(FILE_FIELD, 'Image file', field_type=UIFieldType.TEXT,
                    desc='Merged/custom images only; ignored by board presets',
                    value='', persistent_section=PANEL),
            PANEL)
        rh.fields.register_option(
            UIField(CHIP_FIELD, 'Chip (custom)', field_type=UIFieldType.SELECT,
                    value='auto', options=[option(c, c) for c in CHIPS],
                    persistent_section=PANEL),
            PANEL)
        rh.fields.register_option(
            UIField(OFFSET_FIELD, 'Offset (custom)', field_type=UIFieldType.TEXT,
                    value='0x0', desc='Hex, e.g. 0x0 or 0x2000',
                    persistent_section=PANEL),
            PANEL)

        rh.ui.register_markdown(PANEL, 'nf_state', 'Ready.')
        rh.ui.register_quickbutton(PANEL, 'nf_flash', 'Flash the free board', self.flash)

    # ------------------------------------------------------------ settings
    def _setting(self, key, default=''):
        try:
            value = self._rhapi.config.get(PANEL, key)
        except Exception:  # noqa: BLE001 - an unset field is normal
            value = None
        if value is None or value == '':
            return default
        return value

    def profile(self):
        return str(self._setting(PROFILE_FIELD, 'starforge_c5')).strip()

    def folder(self):
        return os.path.expanduser(str(self._setting(FOLDER_FIELD, DEFAULT_FOLDER)))

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
                    ports = text.split(',')
            else:
                ports = text.split(',')
        return [os.path.realpath(str(p)) for p in ports if str(p).strip()]

    def free_ports(self):
        used = set(self.configured_ports())
        found = {}
        for pattern in ('/dev/ttyACM*', '/dev/ttyUSB*'):
            for path in sorted(_glob(pattern)):
                real = os.path.realpath(path)
                if path in used or real in used:
                    continue
                found.setdefault(real, path)
        return sorted(found.values())

    # ---------------------------------------------------------------- plan
    def plan(self):
        """(chip, [(offset, path)]) for the selected board, or raise ValueError."""
        profile = self.profile()
        folder = self.folder()

        if profile in PARTS_PROFILES:
            _label, chip, boot_offset = PARTS_PROFILES[profile]
            offsets = (boot_offset, 0x8000, 0x10000)
            parts = [(offset, os.path.join(folder, name))
                     for offset, name in zip(offsets, PART_NAMES)]
            missing = [path for _offset, path in parts if not os.path.isfile(path)]
            if missing:
                raise ValueError('Missing %s. Point "Firmware folder" at an '
                                 'unpacked release.' % ', '.join(os.path.basename(p)
                                                                 for p in missing))
            return chip, parts

        image = str(self._setting(FILE_FIELD, '')).strip()
        if not image:
            raise ValueError('No image file set. Fill in "Image file" for this '
                             'board, or pick a preset that uses a release folder.')
        path = os.path.expanduser(image)
        if not os.path.isabs(path):
            path = os.path.join(folder, path)
        if not os.path.isfile(path):
            raise ValueError('Image not found: %s' % path)

        if profile == CUSTOM_PROFILE:
            chip = str(self._setting(CHIP_FIELD, 'auto')).strip() or 'auto'
            if chip not in CHIPS:
                raise ValueError('Unknown chip "%s". Use one of: %s'
                                 % (chip, ', '.join(CHIPS)))
            offset = _hex(self._setting(OFFSET_FIELD, '0x0'))
            if offset is None or offset < 0:
                raise ValueError('Offset "%s" is not a number (use 0x2000 etc).'
                                 % self._setting(OFFSET_FIELD, ''))
            return chip, [(offset, path)]

        if profile in SINGLE_PROFILES:
            _label, chip, offset = SINGLE_PROFILES[profile]
            return chip, [(offset, path)]

        raise ValueError('Unknown board preset "%s".' % profile)

    def esptool_argv(self, port):
        chip, parts = self.plan()
        argv = ['--chip', chip, '--port', port, '--baud', '460800',
                '--before', 'default_reset', '--after', 'watchdog-reset',
                'write_flash']
        for offset, path in parts:
            argv += ['0x%x' % offset, path]
        return argv

    # --------------------------------------------------------------- flashing
    def flash(self, _arg=None):
        if self._busy:
            return self._report('Already flashing - wait for the current write to finish.')
        ports = self.free_ports()
        if not ports:
            return self._report(
                'No free board found. Plug the board into this machine on a port '
                'the timer is not reading, then try again.')
        if len(ports) > 1:
            return self._report(
                'Several free ports (%s). Unplug the others so there is no doubt '
                'which board gets the firmware.' % ', '.join(ports))
        return self.flash_port(ports[0])

    def flash_port(self, port):
        try:
            argv = self.esptool_argv(port)
        except ValueError as exc:
            return self._report(str(exc))

        self._busy = True
        self._report('Flashing %s (%s) ...' % (port, self.profile()))
        try:
            ok, output = self._run_esptool(argv)
        finally:
            self._busy = False

        if not ok:
            return self._report(
                'Flash failed.\n\nIf the board did not reset into its bootloader, '
                'hold BOOT, tap RESET, release BOOT, then try again.\n\n%s'
                % output[-800:])
        return self._report('Flashed %s. Restart the timer - it should find the '
                            'board on its next scan.' % port)

    def _esptool(self):
        try:
            import esptool  # noqa: PLC0415 - optional, installed by the user
        except ImportError:
            return None, ('esptool is not installed for the RotorHazard python.\n'
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
            self._rhapi.ui.update_markdown({'panel': PANEL, 'name': 'nf_state',
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
