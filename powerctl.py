"""Perfiles públicos del gestor de energía de Ubuntu."""
import os
import re
import shutil
import subprocess

PRESETS = {'Máximo rendimiento': 'performance', 'Desarrollo': 'balanced',
           'Oficina': 'power-saver'}


class PowerError(Exception):
    pass


def run(*args):
    executable = shutil.which('powerprofilesctl')
    if not executable:
        raise PowerError('Falta powerprofilesctl. Instala power-profiles-daemon para usar estos modos.')
    try:
        result = subprocess.run([executable, *args], capture_output=True, text=True,
                                timeout=15, env={**os.environ, 'LC_ALL': 'C', 'TERM': 'dumb'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PowerError(f'No se pudo consultar el gestor de energía: {exc}') from exc
    if result.returncode:
        raise PowerError(result.stderr.strip() or 'El gestor de energía rechazó la operación.')
    return result.stdout.strip()


def status():
    listing = run('list')
    available = re.findall(r'^\s*\*?\s*(performance|balanced|power-saver):\s*$', listing, re.M)
    if not available:
        raise PowerError('El gestor de energía no publicó perfiles reconocidos.')
    return {'available': available, 'current': run('get')}


def set_preset(label):
    if label not in PRESETS:
        raise PowerError('Modo no admitido.')
    target = PRESETS[label]
    if target not in status()['available']:
        raise PowerError(f'{label} no está disponible en este equipo.')
    run('set', target)
    observed = run('get')
    if observed != target:
        raise PowerError(f'El cambio no se confirmó: solicitado {target}, leído {observed}.')
    return f'Modo confirmado: {label} ({target}).'
