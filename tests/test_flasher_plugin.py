"""Unit tests for the StarForge RotorHazard flasher plugin.

No hardware and no server: the RHAPI surface is stubbed and esptool is replaced,
so these check the decisions the plugin makes (which port, which addresses,
what it says when something is missing).
"""
import importlib.util
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, '..', 'custom_plugins',
                                      'starforge_flasher', '__init__.py'))

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
    spec = importlib.util.spec_from_file_location('starforge_flasher', PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_rhui_stub():
    """The plugin imports UIField from RHUI, which the bridge provides."""
    stub = types.ModuleType('RHUI')

    class UIFieldType:
        TEXT = 'text'
        CHECKBOX = 'checkbox'

    class UIField:
        def __init__(self, name, label, **kwargs):
            self.name = name
            self.label = label
            self.kwargs = kwargs

    stub.UIField = UIField
    stub.UIFieldType = UIFieldType
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
check('firmware field registered', len(rh.fields.options) == 1)
button = next((c for c in rh.ui.calls if c[0] == 'button'), None)
check('button carries a callable',
      button is not None and callable(button[1][3]),
      repr(button))

print('port selection')
rh = FakeRH({('GENERAL', 'SERIAL_PORTS'): ['/dev/ttyACM0']})
flasher = plugin.initialize(rh)
flasher.initialize(None)
real = '/dev/ttyACM0'
flasher_free = flasher.free_ports()
check('configured port is not offered', real not in flasher_free, repr(flasher_free))

plugin._glob = lambda pattern: ['/dev/ttyACM0', '/dev/ttyACM1']
free = flasher.free_ports()
check('free port offered', free == ['/dev/ttyACM1'], repr(free))

# the same device listed twice must not look like two boards
plugin._glob = lambda pattern: ['/dev/ttyACM0', '/dev/ttyACM0']
plain = plugin.initialize(FakeRH({('GENERAL', 'SERIAL_PORTS'): []}))
plain.initialize(None)
check('duplicates collapse', plain.free_ports() == ['/dev/ttyACM0'], repr(plain.free_ports()))

print('refusals')
plugin._glob = lambda pattern: ['/dev/ttyACM0', '/dev/ttyACM1']
rh = FakeRH({('GENERAL', 'SERIAL_PORTS'): []})
flasher = plugin.initialize(rh)
flasher.initialize(None)
result = flasher.flash()
check('two free boards refused',
      'Several free ports' in result['status'], result['status'])

plugin._glob = lambda pattern: []
result = flasher.flash()
check('no board refused', 'No free board found' in result['status'], result['status'])

print('flashing')
with tempfile.TemporaryDirectory() as tmp:
    plugin._glob = lambda pattern: ['/dev/ttyACM1']
    rh = FakeRH({('GENERAL', 'SERIAL_PORTS'): [], ('starforge_flasher', 'firmware_dir'): tmp})
    flasher = plugin.initialize(rh)
    flasher.initialize(None)

    def must_not_run(_argv):
        raise AssertionError('esptool was called with parts missing')

    flasher._run_esptool = must_not_run
    result = flasher.flash()
    check('missing parts reported',
          'Missing bootloader.bin' in result['status'], result['status'])

    for name in ('bootloader.bin', 'partitions.bin', 'firmware.bin'):
        open(os.path.join(tmp, name), 'wb').write(b'x')

    captured = {}

    def fake_run(argv):
        captured['argv'] = argv
        return True, 'wrote 3 parts'

    flasher._run_esptool = fake_run
    result = flasher.flash()
    argv = captured.get('argv') or []
    check('flash succeeded', result['status'].startswith('Flashed'), result['status'])
    check('chip is esp32c5', argv[:2] == ['--chip', 'esp32c5'], repr(argv[:2]))
    check('port is the free one', '/dev/ttyACM1' in argv)
    joined = ' '.join(argv)
    check('bootloader at 0x2000', '0x2000' in joined and 'bootloader.bin' in joined)
    check('partitions at 0x8000', '0x8000' in joined and 'partitions.bin' in joined)
    check('app at 0x10000', '0x10000' in joined and 'firmware.bin' in joined)
    check('leaves download mode safely', 'watchdog-reset' in joined)

print('esptool failure paths')
# a fresh plugin: the one above has a stubbed _run_esptool on the instance
broken = plugin.initialize(FakeRH({('GENERAL', 'SERIAL_PORTS'): []}))
broken.initialize(None)
broken._esptool = lambda: (None, 'esptool is not installed for the plugin bridge python.')
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
print('PASS: starforge flasher plugin')
