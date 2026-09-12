# -*- coding: utf-8 -*-
"""Desktop launcher for Windows (double-click .pyw = no console window).

Why this file exists: .bat files are read by cmd.exe in the local codepage,
so non-ASCII text inside a .bat breaks on Chinese/Japanese Windows.
Python reads this file as UTF-8, so it is a safe second way in.

If double-clicking does nothing, your Python may not be associated with .pyw -
just use start-desktop.bat instead.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, 'dafang.py')

if not os.path.isfile(APP):
    raise SystemExit('dafang.py not found next to launchers/: %s' % APP)

# Prefer the windowed interpreter so no black console box appears.
exe = sys.executable
if exe.lower().endswith('python.exe'):
    cand = os.path.join(os.path.dirname(exe), 'pythonw.exe')
    if os.path.isfile(cand):
        exe = cand

subprocess.Popen([exe, APP, '--desktop'], cwd=ROOT, close_fds=True)
