import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('omenctl', Path(__file__).parents[1] / 'omenctl.py')
omenctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(omenctl)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ctl = omenctl.Controller(self.root)

    def file(self, path, value):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value, encoding='utf-8')
        return p

    def fan(self):
        base = 'devices/platform/hp-wmi/hwmon/hwmon7/'
        self.file(base + 'name', 'hp\n')
        return self.file(base + 'pwm1_enable', '2\n')

    def test_realistic_class_symlink_resolves_to_hp_platform_device(self):
        target = self.fan()
        cls = self.root / 'class/hwmon/hwmon7'
        cls.parent.mkdir(parents=True)
        try:
            cls.symlink_to(target.parent, target_is_directory=True)
        except OSError:
            self.skipTest('Windows no permite symlinks en esta sesión')
        self.assertEqual(self.ctl.fans(), [target.parent])
        self.ctl.set_fan('max')
        self.assertEqual(target.read_text(), '0\n')
        self.ctl.set_fan('auto')
        self.assertEqual(target.read_text(), '2\n')

    def test_fan_only_changes_validated_target(self):
        target = self.fan()
        with patch.object(self.ctl, 'fans', return_value=[target.parent]):
            self.assertEqual(self.ctl.set_fan('max'), 'max')
            self.assertEqual(target.read_text(), '0\n')
            with self.assertRaises(omenctl.ControlError):
                self.ctl.set_fan('manual')

    def test_unrelated_hp_named_device_is_ignored(self):
        self.file('class/hwmon/hwmon0/name', 'hp')
        self.file('class/hwmon/hwmon0/pwm1_enable', '2')
        self.assertEqual(self.ctl.fans(), [])
        with self.assertRaises(omenctl.ControlError):
            self.ctl.set_fan('max')

    def test_missing_fan_control_is_not_created(self):
        with self.assertRaises(omenctl.ControlError):
            self.ctl.set_fan('auto')
        self.assertEqual(list(self.root.rglob('*')), [])

    def test_profile_choices_are_enforced(self):
        base = 'class/platform-profile/platform-profile-0/'
        self.file(base + 'name', 'hp-wmi')
        self.file(base + 'choices', 'balanced performance')
        target = self.file(base + 'profile', 'balanced')
        with self.assertRaises(omenctl.ControlError):
            self.ctl.set_profile('../performance')
        self.assertEqual(target.read_text(), 'balanced')
        self.assertEqual(self.ctl.set_profile('performance'), 'performance')

    def test_legacy_discovery_and_mixed_provider_refusal(self):
        self.file('devices/platform/hp-wmi/present', '')
        self.file('firmware/acpi/platform_profile', 'balanced')
        self.file('firmware/acpi/platform_profile_choices', 'balanced performance')
        self.assertEqual(len(self.ctl.profiles()), 1)
        self.file('class/platform-profile/platform-profile-0/name', 'other-driver')
        self.assertEqual(self.ctl.profiles(), [])

    def test_ambiguous_providers_refused(self):
        for n in range(2):
            base = f'class/platform-profile/platform-profile-{n}/'
            self.file(base + 'name', 'hp-wmi')
            self.file(base + 'profile', 'balanced')
            self.file(base + 'choices', 'balanced performance')
        with self.assertRaises(omenctl.ControlError):
            self.ctl.set_profile('performance')

    def test_readback_mismatch_is_error(self):
        target = self.file('attribute', 'balanced')
        with patch.object(self.ctl, 'read', return_value='balanced'):
            with self.assertRaises(omenctl.ControlError):
                self.ctl.write(target, 'performance')

    def test_permission_error_has_actionable_message(self):
        target = self.file('attribute', '2')
        with patch.object(Path, 'open', side_effect=PermissionError()):
            with self.assertRaisesRegex(omenctl.ControlError, 'sudo'):
                self.ctl.write(target, '0')

    def test_ambiguous_fan_control_refused(self):
        first = self.fan().parent
        second = self.file('devices/platform/hp-wmi/hwmon/hwmon8/pwm1_enable', '2').parent
        with patch.object(self.ctl, 'fans', return_value=[first, second]):
            with self.assertRaises(omenctl.ControlError):
                self.ctl.set_fan('max')

    def test_outside_root_rejected(self):
        with self.assertRaises(omenctl.ControlError):
            self.ctl.safe(self.root.parent)

    def test_status_missing_interfaces_is_useful(self):
        status = self.ctl.status()
        self.assertEqual(status['fans'], [])
        self.assertEqual(status['profiles'], [])
        self.assertIsNone(status['hardware']['board_name'])


if __name__ == '__main__':
    unittest.main()
