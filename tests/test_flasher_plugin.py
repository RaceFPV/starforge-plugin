"""Tests for the RotorHazard node flasher plugin (no hardware, no server).

The RHAPI surface is stubbed and esptool is replaced, so these check the
decisions that matter: which ports are candidates, which chip and offsets a
board preset resolves to, and what the user is told when something is missing.
"""
import importlib.util
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, '..', 'custom_plugins',
                                      'node_flasher', '__init__.py'))

failures = []


def check(name, condition, detail=''):
    if condition:
        print('  ok   %s' % name)
    else:
        failures.append('%s %s' % (name, detail))
        print('  FAIL %s %s' % (name, detail))


class FakeUI:
    def __init__(self):
        self.calls = []

    def register_panel(self, *a, **k):
        self.calls.append(('panel', a, k))

    def register_markdown(self, *a, **k):
        self.calls.append(('markdown', a, k))

    def register_quickbutton(self, *a, **k):
        self.calls.append(('button', a, k))

    def update_markdown(self, *a, **k):
        self.calls.append(('update_markdown', a, k))

    def message_notify(self, *a, **k):
        self.calls.append(('notify', a, k))


class FakeFields:
    def __init__(self):
        self.options = []

    def register_option(self, field, panel=None):
        self.options.append((field, panel))


class FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, section, key, default=None):
        return self.values.get((section, key), default)


class FakeRH:
    def __init__(self, values=None):
        self.config = FakeConfig(values)
        self.ui = FakeUI()
        self.fields = FakeFields()


def load_plugin():
    spec = importlib.util.spec_from_file_location('node_flasher', PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_rhui_stub():
    """The plugin imports UIField/UIFieldType from RHUI, which the bridge provides."""
    stub = types.ModuleType('RHUI')

    class UIFieldType:
        TEXT = 'text'
        SELECT = 'select'
        CHECKBOX = 'checkbox'

    class UIFieldSelectOption:
        def __init__(self, value, label):
            self.value = value
            self.label = label

    class UIField:
        def __init__(self, name, label, **kwargs):
            self.name = name
            self.label = label
            self.kwargs = kwargs

    stub.UIField = UIField
    stub.UIFieldType = UIFieldType
    stub.UIFieldSelectOption = UIFieldSelectOption
    sys.modules['RHUI'] = stub


install_rhui_stub()
plugin = load_plugin()

print('panel registration')
rh = FakeRH()
flasher = plugin.initialize(rh)
check('initialize returns the plugin', flasher is not None)
flasher.initialize(None)
kinds = [call[0] for call in rh.ui.calls]
check('panel registered', 'panel' in kinds)
check('markdown registered', kinds.count('markdown') >= 1)
check('quickbutton registered', 'button' in kinds)
check('five settings fields', len(rh.fields.options) == 5, len(rh.fields.options))
button = next((c for c in rh.ui.calls if c[0] == 'button'), None)
check('button carries a callable', button is not None and callable(button[1][3]))

print('board presets')
with tempfile.TemporaryDirectory() as tmp:
    for name in ('bootloader.bin', 'partitions.bin', 'firmware.bin'):
        open(os.path.join(tmp, name), 'wb').write(b'x')

    rh = FakeRH({('node_flasher', 'profile'): 'starforge_c5',
                 ('node_flasher', 'firmware_folder'): tmp})
    flasher = plugin.initialize(rh)
    flasher.initialize(None)
    chip, parts = flasher.plan()
    check('C5 preset uses esp32c5', chip == 'esp32c5', chip)
    check('C5 bootloader at 0x2000',
          [(o, os.path.basename(p)) for o, p in parts][0] == (0x2000, 'bootloader.bin'),
          parts)
    check('three parts at fixed addresses',
          [o for o, _p in parts] == [0x2000, 0x8000, 0x10000], parts)

    rh = FakeRH({('node_flasher', 'profile'): 'starforge_c3',
                 ('node_flasher', 'firmware_folder'): tmp})
    flasher3 = plugin.initialize(rh)
    flasher3.initialize(None)
    chip, parts = flasher3.plan()
    check('C3 preset uses esp32c3 at 0x0',
          chip == 'esp32c3' and parts[0][0] == 0x0, (chip, parts))

    rh = FakeRH({('node_flasher', 'profile'): 'starforge_c5',
                 ('node_flasher', 'firmware_folder'): tmp + '/absent'})
    broken = plugin.initialize(rh)
    broken.initialize(None)
    try:
        broken.plan()
        check('missing parts rejected', False)
    except ValueError as exc:
        check('missing parts rejected', 'bootloader.bin' in str(exc), str(exc))

print('single image and custom')
with tempfile.TemporaryDirectory() as tmp:
    image = os.path.join(tmp, 'firmware-merged.bin')
    open(image, 'wb').write(b'x')

    rh = FakeRH({('node_flasher', 'profile'): 'merged_0x0',
                 ('node_flasher', 'image_file'): image})
    merged = plugin.initialize(rh)
    merged.initialize(None)
    chip, parts = merged.plan()
    check('merged image at 0x0, chip auto',
          chip == 'auto' and parts == [(0x0, image)], (chip, parts))

    rh = FakeRH({('node_flasher', 'profile'): 'custom',
                 ('node_flasher', 'image_file'): image,
                 ('node_flasher', 'chip'): 'esp32c5',
                 ('node_flasher', 'offset'): '0x2000'})
    custom = plugin.initialize(rh)
    custom.initialize(None)
    chip, parts = custom.plan()
    check('custom chip and hex offset', chip == 'esp32c5' and parts[0][0] == 0x2000,
          (chip, parts))

    argv = custom.esptool_argv('/dev/ttyACM1')
    joined = ' '.join(argv)
    check('argv has chip, port and offset',
          ['--chip', 'esp32c5'] == argv[:2] and '/dev/ttyACM1' in joined
          and '0x2000' in joined, argv)
    check('argv leaves download mode safely', 'watchdog-reset' in joined)

    rh = FakeRH({('node_flasher', 'profile'): 'custom',
                 ('node_flasher', 'image_file'): image,
                 ('node_flasher', 'offset'): 'banana'})
    bad = plugin.initialize(rh)
    bad.initialize(None)
    try:
        bad.plan()
        check('bad offset rejected', False)
    except ValueError as exc:
        check('bad offset rejected', 'not a number' in str(exc), str(exc))

    rh = FakeRH({('node_flasher', 'profile'): 'no_such_board',
                 ('node_flasher', 'image_file'): image})
    unknown = plugin.initialize(rh)
    unknown.initialize(None)
    try:
        unknown.plan()
        check('unknown preset rejected', False)
    except ValueError as exc:
        check('unknown preset rejected', 'Unknown board preset' in str(exc), str(exc))

print('port selection')
plugin._glob = lambda pattern: ['/dev/ttyACM0', '/dev/ttyACM1']
rh = FakeRH({('GENERAL', 'SERIAL_PORTS'): ['/dev/ttyACM0']})
flasher = plugin.initialize(rh)
flasher.initialize(None)
check('port the timer uses is not offered',
      flasher.free_ports() == ['/dev/ttyACM1'], flasher.free_ports())

plugin._glob = lambda pattern: ['/dev/ttyACM0', '/dev/ttyACM0']
plain = plugin.initialize(FakeRH({('GENERAL', 'SERIAL_PORTS'): []}))
plain.initialize(None)
check('duplicates collapse', plain.free_ports() == ['/dev/ttyACM0'], plain.free_ports())

plugin._glob = lambda pattern: []
check('no free board refused',
      'No free board found' in plain.flash()['status'])

plugin._glob = lambda pattern: ['/dev/ttyACM0', '/dev/ttyACM1']
check('two free boards refused',
      'Several free ports' in plain.flash()['status'])

print('flashing')
with tempfile.TemporaryDirectory() as tmp:
    for name in ('bootloader.bin', 'partitions.bin', 'firmware.bin'):
        open(os.path.join(tmp, name), 'wb').write(b'x')
    plugin._glob = lambda pattern: ['/dev/ttyACM1']
    rh = FakeRH({('GENERAL', 'SERIAL_PORTS'): [],
                 ('node_flasher', 'profile'): 'starforge_c5',
                 ('node_flasher', 'firmware_folder'): tmp})
    flasher = plugin.initialize(rh)
    flasher.initialize(None)

    captured = {}

    def fake_run(argv):
        captured['argv'] = argv
        return True, 'wrote 3 parts'

    flasher._run_esptool = fake_run
    result = flasher.flash()
    argv = captured.get('argv') or []
    check('flash succeeded', result['status'].startswith('Flashed'), result['status'])
    joined = ' '.join(argv)
    check('wrote the preset addresses',
          '0x2000' in joined and '0x8000' in joined and '0x10000' in joined, joined)
    check('used the free port', '/dev/ttyACM1' in joined)

print('esptool failure paths')
broken = plugin.initialize(FakeRH())
broken.initialize(None)
broken._esptool = lambda: (None, 'esptool is not installed for the RotorHazard python.')
ok, output = broken._run_esptool(['--chip', 'esp32c5'])
check('missing esptool reported', not ok and 'esptool' in output, repr(output))


class Boom:
    def main(self, argv):
        raise SystemExit(2)


broken._esptool = lambda: (Boom(), None)
ok, output = broken._run_esptool(['--chip', 'esp32c5'])
check('non-zero exit reported', not ok, repr(output))

if failures:
    print('FAIL')
    for failure in failures:
        print('  -', failure)
    sys.exit(1)
print('PASS: node flasher plugin')
