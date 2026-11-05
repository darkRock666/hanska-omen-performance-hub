#!/usr/bin/env python3
"""Panel local HP OMEN/Victus. Lecturas sin privilegios; cambios vía PolicyKit."""
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from omenctl import Controller, ControlError
import powerctl

POWER_FAN_MODES = {'Máximo rendimiento': 'max', 'Desarrollo': 'max', 'Oficina': 'auto'}


class Panel:
    BG = '#090a0f'
    CARD = '#11131b'
    CARD_ALT = '#151722'
    RED = '#ff2348'
    RED_DARK = '#7e1428'
    TEXT = '#f3f4f8'
    MUTED = '#85899a'

    def __init__(self, root):
        self.root = root
        self.ctl = Controller()
        self.results = queue.Queue()
        self.busy = False
        self.power_reading = False
        self.power_available = []
        self.fan_controls_available = False
        self.fan_mode = 'unknown'
        self.fan_rpms = []
        self.fan_phase = 0.0
        root.title('HANSKA OMEN PERFORMANCE HUB')
        root.geometry('800x740')
        root.minsize(700, 680)
        root.configure(bg=self.BG)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', background=self.BG, foreground=self.TEXT, font=('DejaVu Sans', 10))
        style.configure('TFrame', background=self.BG)
        style.configure('Card.TFrame', background=self.CARD)
        style.configure('Inset.TFrame', background=self.CARD_ALT)
        style.configure('TLabel', background=self.BG, foreground=self.TEXT)
        style.configure('Card.TLabel', background=self.CARD, foreground=self.TEXT)
        style.configure('Inset.TLabel', background=self.CARD_ALT, foreground=self.TEXT)
        style.configure('Muted.Card.TLabel', background=self.CARD, foreground=self.MUTED)
        style.configure('Brand.TLabel', background=self.BG, foreground=self.RED, font=('DejaVu Sans', 10, 'bold'))
        style.configure('Title.TLabel', background=self.BG, foreground=self.TEXT, font=('DejaVu Sans', 25, 'bold'))
        style.configure('Section.TLabel', background=self.CARD, foreground=self.TEXT, font=('DejaVu Sans', 13, 'bold'))
        style.configure('Metric.TLabel', background=self.CARD_ALT, foreground=self.RED, font=('DejaVu Sans', 18, 'bold'))
        style.configure('Mode.TLabel', background=self.CARD, foreground=self.RED, font=('DejaVu Sans', 11, 'bold'))
        style.configure('Accent.TButton', background=self.RED, foreground='#ffffff', borderwidth=0,
                        padding=(14, 10), font=('DejaVu Sans', 9, 'bold'))
        style.map('Accent.TButton', background=[('active', '#ff4967'), ('disabled', '#4d2630')],
                  foreground=[('disabled', '#9c8288')])
        style.configure('Quiet.TButton', background=self.CARD_ALT, foreground=self.TEXT,
                        bordercolor=self.RED_DARK, borderwidth=1, padding=(14, 10))
        style.map('Quiet.TButton', background=[('active', '#25202a'), ('disabled', '#171820')],
                  foreground=[('disabled', '#6f7280')])

        outer = ttk.Frame(root, padding=(30, 25))
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='HANSKA  /  OMEN', style='Brand.TLabel').pack(anchor='w')
        ttk.Label(outer, text='PERFORMANCE HUB', style='Title.TLabel').pack(anchor='w', pady=(3, 0))
        self.hardware = ttk.Label(outer, text='DETECTANDO EQUIPO…', foreground=self.MUTED,
                                  font=('DejaVu Sans', 9, 'bold'))
        self.hardware.pack(anchor='w', pady=(4, 20))

        fan_card = ttk.Frame(outer, style='Card.TFrame', padding=20)
        fan_card.pack(fill='x', pady=(0, 14))
        fan_head = ttk.Frame(fan_card, style='Card.TFrame')
        fan_head.pack(fill='x')
        ttk.Label(fan_head, text='01  /  SISTEMA TÉRMICO', style='Section.TLabel').pack(side='left')
        self.mode = ttk.Label(fan_head, text='● EN ESPERA', style='Mode.TLabel')
        self.mode.pack(side='right')
        metric_row = ttk.Frame(fan_card, style='Card.TFrame')
        metric_row.pack(fill='x', pady=16)
        metric_text = ttk.Frame(metric_row, style='Card.TFrame')
        metric_text.pack(side='left', fill='both', expand=True, anchor='w')
        self.rpm = ttk.Label(metric_text, text='— RPM', style='Metric.TLabel')
        self.rpm.pack(anchor='w', pady=(14, 4))
        ttk.Label(metric_text, text='VELOCIDAD EN TIEMPO REAL', style='Muted.Card.TLabel',
                  font=('DejaVu Sans', 8, 'bold')).pack(anchor='w')
        self.fan_canvas = tk.Canvas(metric_row, width=128, height=124, bg=self.CARD,
                                    highlightthickness=0, bd=0)
        self.fan_canvas.pack(side='right', padx=(8, 12))
        fan_actions = ttk.Frame(fan_card, style='Card.TFrame')
        fan_actions.pack(fill='x')
        self.auto = ttk.Button(fan_actions, text='AUTO  /  FIRMWARE', style='Quiet.TButton',
                               command=lambda: self.change('auto'))
        self.auto.pack(side='left', padx=(0, 10))
        self.medium = ttk.Button(fan_actions, text='MEDIO  /  CURVA AUTO', style='Quiet.TButton',
                                 command=self.change_medium)
        self.medium.pack(side='left', padx=(0, 10))
        self.maximum = ttk.Button(fan_actions, text='ENCENDER  /  MÁXIMO', style='Accent.TButton',
                                  command=lambda: self.change('max'))
        self.maximum.pack(side='left')
        self.profiles = ttk.Label(fan_card, text='Perfil OMEN: leyendo controlador…', style='Muted.Card.TLabel')
        self.profiles.pack(anchor='w', pady=(13, 0))

        power_card = ttk.Frame(outer, style='Card.TFrame', padding=20)
        power_card.pack(fill='x')
        ttk.Label(power_card, text='02  /  PERFIL DE ENERGÍA', style='Section.TLabel').pack(anchor='w')
        self.power_state = ttk.Label(power_card, text='Consultando perfiles de Ubuntu…',
                                     style='Muted.Card.TLabel', wraplength=640)
        self.power_state.pack(anchor='w', pady=(7, 13))
        power_row = ttk.Frame(power_card, style='Card.TFrame')
        power_row.pack(fill='x')
        self.power_buttons = {}
        button_labels = {'Máximo rendimiento': 'PERFORMANCE + FAN MAX',
                         'Desarrollo': 'DESARROLLO + FAN MAX',
                         'Oficina': 'OFICINA + FAN AUTO'}
        for label in powerctl.PRESETS:
            button = ttk.Button(power_row, text=button_labels[label], style='Quiet.TButton', state='disabled',
                                command=lambda value=label: self.change_power(value))
            button.pack(side='left', padx=(0, 8))
            self.power_buttons[label] = button
        ttk.Label(power_card, text='MEDIO COMBINA ESTA ENERGÍA EQUILIBRADA CON AUTO DEL FIRMWARE.',
                  style='Muted.Card.TLabel', font=('DejaVu Sans', 8, 'bold')).pack(anchor='w', pady=(12, 0))
        status_bar = ttk.Frame(outer, style='Inset.TFrame', padding=(13, 10))
        status_bar.pack(fill='x', pady=(14, 8))
        self.feedback = ttk.Label(status_bar, text='● SISTEMA LISTO  ·  LECTURA TÉRMICA CADA 2 S',
                                  style='Inset.TLabel', wraplength=640)
        self.feedback.pack(anchor='w')
        ttk.Label(outer, text='Los cambios de ventilador permanecen activos hasta restaurar AUTO.',
                  foreground=self.MUTED, font=('DejaVu Sans', 8)).pack(anchor='w')
        self.refresh()
        self.poll()
        self.refresh_power()
        self.animate_fan()

    def power_button_states(self):
        for label, button in self.power_buttons.items():
            button.config(state='normal' if not self.busy and
                          self.fan_controls_available and
                          powerctl.PRESETS[label] in self.power_available else 'disabled')

    def set_fan_mode(self, mode):
        cli = Path(__file__).resolve().with_name('omenctl.py')
        command = [sys.executable, str(cli), 'fan', mode]
        if os.geteuid() != 0:
            pkexec = shutil.which('pkexec')
            if not pkexec:
                raise RuntimeError('No se encontró pkexec para cambiar los ventiladores.')
            command.insert(0, pkexec)
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f'No se pudo cambiar el ventilador: {exc}') from exc
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'El controlador rechazó el cambio del ventilador.')
        return result.stdout.strip()

    def refresh_power(self):
        if not self.busy and not self.power_reading:
            self.power_reading = True

            def worker():
                try:
                    self.results.put(('power_status', powerctl.status()))
                except powerctl.PowerError as exc:
                    self.results.put(('power_error', str(exc)))

            threading.Thread(target=worker, daemon=True).start()
        self.root.after(4000, self.refresh_power)

    def change_power(self, label):
        if self.busy:
            return
        self.busy = True
        self.power_button_states()
        for button in (self.auto, self.maximum):
            button.config(state='disabled')
        self.medium.config(state='disabled')
        fan_mode = POWER_FAN_MODES[label]
        self.feedback.config(text=f'● APLICANDO {label.upper()} + VENTILADOR {fan_mode.upper()}…')

        def worker():
            try:
                fan_result = self.set_fan_mode(fan_mode)
                message = powerctl.set_preset(label)
                message = f'{fan_result} · {message}'
            except RuntimeError as exc:
                message = str(exc)
            except powerctl.PowerError as exc:
                message = f'Ventilador en {fan_mode.upper()}; no se cambió el perfil de energía: {exc}'
            self.results.put(('action', message))

        threading.Thread(target=worker, daemon=True).start()

    def change_medium(self):
        """Use the safe firmware curve plus balanced system power as a medium preset."""
        if self.busy:
            return
        if 'balanced' not in self.power_available:
            self.feedback.config(text='● PERFIL MEDIO NO DISPONIBLE · Ubuntu no publicó balanced', foreground=self.RED)
            return
        self.busy = True
        self.power_button_states()
        for button in (self.auto, self.medium, self.maximum):
            button.config(state='disabled')
        self.feedback.config(text='● ACTIVANDO MEDIO  ·  AUTO DEL FIRMWARE + ENERGÍA EQUILIBRADA…')

        def worker():
            try:
                fan_result = self.set_fan_mode('auto')
            except RuntimeError as exc:
                self.results.put(('action', f'No se pudo activar la curva AUTO: {exc}'))
                return
            try:
                energy_result = powerctl.set_preset('Desarrollo')
                self.results.put(('action', f'Curva AUTO activada; {energy_result}'))
            except powerctl.PowerError as exc:
                self.results.put(('action', f'Ventiladores en AUTO; no se cambió energía equilibrada: {exc}'))

        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        try:
            data = self.ctl.status()
            hw = data['hardware']
            self.hardware.config(text=f"{hw.get('product_name') or 'HP'} · placa {hw.get('board_name') or '?'}")
            fans = data['fans']
            eligible = [f for f in fans if (Path(f['path']) / 'pwm1_enable').exists()]
            enabled = len(eligible) == 1 and not self.busy
            self.fan_controls_available = len(eligible) == 1
            self.power_button_states()
            for button in (self.auto, self.medium, self.maximum):
                button.config(state='normal' if enabled else 'disabled')
            self.medium.config(state='normal' if enabled and 'balanced' in self.power_available else 'disabled')
            labels = {'auto': 'Automático', 'max': 'Máximo', 'manual': 'Manual', 'unknown': 'Desconocido'}
            mode = labels.get(fans[0]['mode'], 'Desconocido').upper() if len(fans) == 1 else 'NO DISPONIBLE'
            self.fan_mode = fans[0]['mode'] if len(fans) == 1 else 'unknown'
            self.mode.config(text=f'● {mode}')
            values = [value for fan in fans for value in fan['rpm'].values()]
            self.fan_rpms = [int(value) for value in values if value is not None and value.isdigit()]
            readings = [f"FAN {i}   {value if value is not None else '—'} RPM" for f in fans for i, value in enumerate(f['rpm'].values(), 1)]
            self.rpm.config(text='     /     '.join(readings) or 'RPM NO DISPONIBLES')
            self.profiles.config(text='Perfil: ' + (', '.join(p['current'] or 'desconocido' for p in data['profiles']) or 'no disponible en este kernel'))
            present_values = [value for value in values if value is not None]
            if present_values and all(value == '0' for value in present_values):
                if self.fan_mode == 'max':
                    self.feedback.config(text='● MÁXIMO SOLICITADO · EL CONTROLADOR SIGUE INFORMANDO 0 RPM', foreground=self.RED)
                else:
                    self.feedback.config(text='● 0 RPM REPORTADAS EN AUTO · PRUEBA «ENCENDER / MÁXIMO» PARA VERIFICAR', foreground=self.RED)
            elif self.fan_rpms and any(rpm > 0 for rpm in self.fan_rpms):
                self.feedback.config(text='● VENTILADORES EN MOVIMIENTO · RPM RECIBIDAS DEL SENSOR', foreground='#51e6a6')
        except (ControlError, OSError) as exc:
            self.fan_controls_available = False
            self.power_button_states()
            self.feedback.config(text='● ERROR  ·  ' + str(exc))
            for button in (self.auto, self.medium, self.maximum):
                button.config(state='disabled')
        self.root.after(2000, self.refresh)

    def animate_fan(self):
        """Animate the rotor only when sensor RPMs confirm movement; pulse the halo otherwise."""
        canvas = self.fan_canvas
        canvas.delete('all')
        cx, cy = 64, 62
        moving = any(rpm > 0 for rpm in self.fan_rpms)
        self.fan_phase = (self.fan_phase + (max(3, min(28, sum(self.fan_rpms) / 90)) if moving else 1.1)) % 360
        pulse = (self.fan_phase % 40) / 40 if not moving else 0.5
        halo = '#ff2348' if moving else ('#7e1428' if pulse < 0.5 else '#b61d38')
        canvas.create_oval(10, 8, 118, 116, outline=halo, width=2)
        canvas.create_oval(18, 16, 110, 108, outline='#38202a', width=1)
        if moving:
            import math
            for i in range(5):
                angle = math.radians(self.fan_phase + i * 72)
                points = []
                for radius, offset in ((13, -0.38), (47, -0.12), (43, 0.3), (18, 0.16)):
                    a = angle + offset
                    points.extend((cx + math.cos(a) * radius, cy + math.sin(a) * radius))
                canvas.create_polygon(*points, fill='#ff2348', outline='#ff7188', width=1)
            canvas.create_oval(cx-9, cy-9, cx+9, cy+9, fill='#f4f4f8', outline=self.RED, width=3)
        else:
            for i in range(5):
                angle = (self.fan_phase + i * 72) * 3.14159265 / 180
                import math
                x1, y1 = cx + math.cos(angle) * 15, cy + math.sin(angle) * 15
                x2, y2 = cx + math.cos(angle) * 42, cy + math.sin(angle) * 42
                canvas.create_line(x1, y1, x2, y2, fill='#8f2238', width=7, capstyle='round')
            canvas.create_oval(cx-8, cy-8, cx+8, cy+8, fill='#ff2348', outline='#ff8094', width=2)
        canvas.create_text(cx, 121, text='LIVE / RPM' if moving else 'IDLE / AUTO',
                           fill=self.RED if moving else '#8b6972', font=('DejaVu Sans', 7, 'bold'))
        self.root.after(45, self.animate_fan)

    def change(self, mode):
        if self.busy:
            return
        cli = Path(__file__).resolve().with_name('omenctl.py')
        command = [sys.executable, str(cli), 'fan', mode]
        if os.geteuid() != 0:
            pkexec = shutil.which('pkexec')
            if not pkexec:
                messagebox.showerror('Autenticación', 'Falta pkexec. Puedes usar los comandos sudo descritos en LEEME.md.')
                return
            command.insert(0, pkexec)
        self.busy = True
        self.power_button_states()
        for button in (self.auto, self.medium, self.maximum):
            button.config(state='disabled')
        self.feedback.config(text='● AUTENTICANDO  ·  ESPERANDO CONFIRMACIÓN DEL KERNEL…')

        def worker():
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=120)
                message = (result.stdout if result.returncode == 0 else result.stderr).strip()
                self.results.put(('action', message or 'Cambio cancelado o rechazado.'))
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.results.put(('action', f'No se completó el cambio: {exc}'))

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            kind, value = self.results.get_nowait()
            if kind == 'action':
                self.busy = False
                self.feedback.config(text=value)
            elif kind == 'power_status':
                self.power_reading = False
                self.power_available = value['available']
                label = next((k for k, v in powerctl.PRESETS.items() if v == value['current']), value['current'])
                self.power_state.config(text=f"Activo: {label} ({value['current']})")
                self.medium.config(state='normal' if not self.busy and 'balanced' in self.power_available and
                                   self.fan_controls_available else 'disabled')
            else:
                self.power_reading = False
                self.power_available = []
                self.power_state.config(text='Energía no disponible: ' + value)
                self.medium.config(state='disabled')
            self.power_button_states()
        except queue.Empty:
            pass
        self.root.after(150, self.poll)


if __name__ == '__main__':
    root = tk.Tk()
    Panel(root)
    root.mainloop()
