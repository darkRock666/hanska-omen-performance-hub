#!/usr/bin/env python3
"""Control mínimo HP/OMEN mediante las interfaces públicas del kernel Linux."""
import argparse
import json
from pathlib import Path
import platform
import sys


class ControlError(Exception):
    pass


class Controller:
    def __init__(self, root=Path('/sys')):
        # Dependency injection for unit tests; the CLI always uses /sys.
        self.root = Path(root).resolve()

    def read(self, path):
        try:
            return path.read_text(encoding='utf-8').strip()
        except OSError as exc:
            raise ControlError(f'No se pudo leer {path}: {exc.strerror}') from exc

    def optional(self, path):
        try:
            return self.read(path)
        except ControlError:
            return None

    def safe(self, path):
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.root)
            return resolved
        except (ValueError, OSError) as exc:
            raise ControlError(f'Ruta sysfs inválida: {path}') from exc

    def fans(self):
        result = []
        for item in sorted((self.root / 'class/hwmon').glob('hwmon*')):
            if self.optional(item / 'name') != 'hp':
                continue
            node = self.safe(item)
            # The hp-wmi driver registers hwmon below its platform device.
            if 'hp-wmi' not in [p.name for p in node.parents]:
                continue
            result.append(node)
        return result

    def profiles(self):
        result = []
        for item in sorted((self.root / 'class/platform-profile').glob('*')):
            if self.optional(item / 'name') == 'hp-wmi':
                result.append(self.safe(item))
        if result:
            return [(p / 'profile', p / 'choices') for p in result]
        # The legacy interface is global; allow it only with hp-wmi present,
        # and only when no newer provider class exists (avoid mixed providers).
        providers = list((self.root / 'class/platform-profile').glob('*'))
        legacy = self.root / 'firmware/acpi/platform_profile'
        hp = self.root / 'devices/platform/hp-wmi'
        if not providers and hp.exists() and legacy.exists():
            return [(self.safe(legacy), self.safe(legacy.with_name('platform_profile_choices')))]
        return []

    def write(self, path, value):
        path = self.safe(path)
        try:
            # r+ deliberately avoids creating a missing pseudo-file.
            with path.open('r+', encoding='ascii') as stream:
                stream.write(value + '\n')
        except PermissionError as exc:
            raise ControlError('Permiso denegado: ejecuta este cambio con sudo.') from exc
        except OSError as exc:
            raise ControlError(f'El kernel rechazó el cambio: {exc.strerror}') from exc
        observed = self.read(path)
        if observed != value:
            raise ControlError(f'El cambio no se confirmó: pedido={value}, leído={observed}. '
                               'El firmware u otro servicio puede haberlo cambiado.')
        return observed

    def set_profile(self, value):
        providers = self.profiles()
        if len(providers) != 1:
            raise ControlError('Se necesita exactamente un proveedor de perfiles HP compatible.')
        target, choices_path = providers[0]
        choices = self.read(choices_path).split()
        if value not in choices:
            raise ControlError('Perfil no admitido. Opciones: ' + ', '.join(choices))
        return self.write(target, value)

    def set_fan(self, mode):
        if mode not in ('auto', 'max'):
            raise ControlError('Modo de ventilador no admitido.')
        candidates = [p for p in self.fans() if (p / 'pwm1_enable').exists()]
        if len(candidates) != 1:
            raise ControlError('No hay un único control hp-wmi pwm1_enable compatible.')
        self.write(candidates[0] / 'pwm1_enable', {'auto': '2', 'max': '0'}[mode])
        return mode

    def status(self):
        fan_data = []
        for node in self.fans():
            raw = self.optional(node / 'pwm1_enable')
            fan_data.append({'path': str(node), 'mode_raw': raw,
                             'mode': {'0': 'max', '1': 'manual', '2': 'auto'}.get(raw, 'unknown'),
                             'rpm': {p.stem: self.optional(p) for p in sorted(node.glob('fan[0-9]*_input'))}})
        profile_data = [{'path': str(p), 'current': self.optional(p),
                         'choices': (self.optional(c) or '').split()}
                        for p, c in self.profiles()]
        return {'kernel': platform.release(), 'hp_wmi_loaded': (self.root / 'module/hp_wmi').exists(),
                'hardware': {key: self.optional(self.root / 'class/dmi/id' / key)
                             for key in ('sys_vendor', 'product_name', 'board_name', 'bios_version')},
                'fans': fan_data, 'profiles': profile_data}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='Estado en JSON; solo lectura')
    commands.add_parser('diagnose', help='Diagnóstico en JSON; solo lectura')
    profiles = commands.add_parser('profile').add_subparsers(dest='action', required=True)
    profiles.add_parser('list')
    profiles.add_parser('set').add_argument('value')
    commands.add_parser('fan').add_argument('mode', choices=['auto', 'max'])
    args = parser.parse_args(argv)
    if sys.platform != 'linux':
        parser.exit(2, 'Esta herramienta requiere Linux y sysfs.\n')
    ctl = Controller()
    try:
        if args.command in ('status', 'diagnose'):
            data = ctl.status()
            if args.command == 'diagnose':
                data['notes'] = ['La presencia del atributo no garantiza soporte del firmware.',
                                 'Si faltan controles: revisar hp_wmi, versión del kernel y modelo/placa.',
                                 'Un gestor de energía puede cambiar el perfil después de esta lectura.']
            print(json.dumps(data, ensure_ascii=False, indent=2))
        elif args.command == 'fan':
            print('Ventiladores: ' + ctl.set_fan(args.mode))
        elif args.action == 'list':
            print(json.dumps(ctl.status()['profiles'], ensure_ascii=False, indent=2))
        else:
            print('Perfil: ' + ctl.set_profile(args.value))
        return 0
    except (ControlError, OSError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
