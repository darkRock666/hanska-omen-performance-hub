import sys
from pathlib import Path
import unittest
from unittest.mock import patch, call

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import powerctl


class PowerTests(unittest.TestCase):
    def test_listing_with_active_marker_and_driver_details(self):
        listing = '  performance:\n    CpuDriver: amd_pstate\n* balanced:\n    PlatformDriver: placeholder\n  power-saver:\n'
        with patch.object(powerctl, 'run', side_effect=[listing, 'balanced']):
            self.assertEqual(powerctl.status(), {
                'available': ['performance', 'balanced', 'power-saver'], 'current': 'balanced'})

    def test_unavailable_performance_never_sets_profile(self):
        with patch.object(powerctl, 'status', return_value={'available': ['balanced']}), patch.object(powerctl, 'run') as run:
            with self.assertRaises(powerctl.PowerError):
                powerctl.set_preset('Máximo rendimiento')
            run.assert_not_called()

    def test_each_preset_is_confirmed_by_readback(self):
        for label, target in powerctl.PRESETS.items():
            with self.subTest(label=label), patch.object(powerctl, 'status', return_value={'available': [target]}), patch.object(powerctl, 'run', side_effect=['', target]) as run:
                self.assertIn('confirmado', powerctl.set_preset(label))
                self.assertEqual(run.call_args_list, [call('set', target), call('get')])

    def test_readback_mismatch_is_reported(self):
        with patch.object(powerctl, 'status', return_value={'available': ['performance']}), patch.object(powerctl, 'run', side_effect=['', 'balanced']):
            with self.assertRaisesRegex(powerctl.PowerError, 'no se confirmó'):
                powerctl.set_preset('Máximo rendimiento')

    def test_service_failure_is_reported(self):
        with patch.object(powerctl.shutil, 'which', return_value='/usr/bin/powerprofilesctl'), patch.object(powerctl.subprocess, 'run') as run:
            run.return_value.returncode = 1
            run.return_value.stderr = 'No se pudo conectar al servicio'
            with self.assertRaisesRegex(powerctl.PowerError, 'conectar'):
                powerctl.status()


if __name__ == '__main__':
    unittest.main()
