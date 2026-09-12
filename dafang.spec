# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 dafang.py 打成单文件可执行程序。
   用法（在仓库根目录）：
       pip install pyinstaller
       pyinstaller dafang.spec
   产物在 dist/ 下：
       Windows → dist/大大方方Agent.exe
       macOS   → dist/大大方方Agent
       Linux   → dist/大大方方Agent
   注意：程序里已带 --desktop 逻辑，双击产物即打开应用窗口；
        数据仍写用户目录（Windows「文档\\大大方方Agent」/ macOS与Linux「~/.dafang」）。
"""
import sys

name = '大大方方Agent'
console = not sys.platform.startswith('win')   # Windows 下不弹黑框；其它平台留控制台方便看日志

a = Analysis(
    ['dafang.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'numpy', 'PIL', 'pandas', 'matplotlib'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=console,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
