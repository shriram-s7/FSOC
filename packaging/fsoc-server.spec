# PyInstaller spec for the FSOC-PAT backend. Build with packaging\build_exe.ps1.
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
PACKAGES = ['server', 'ui', 'comparison', 'config', 'control', 'detection',
            'disturbance', 'evaluation', 'input', 'simulation', 'tracking']

hidden = []
for pkg in PACKAGES:
    hidden += collect_submodules(pkg)
hidden += collect_submodules('uvicorn') + collect_submodules('websockets')
hidden += ['multipart', 'python_multipart', 'yaml', 'filterpy.kalman', 'scipy.linalg']

datas = [
    (os.path.join(ROOT, 'config', 'default.yaml'), 'config'),
    (os.path.join(ROOT, 'models'), 'models'),
    (os.path.join(ROOT, 'frontend', 'src'), os.path.join('frontend', 'src')),
    (os.path.join(ROOT, 'harness', 'scenarios.yaml'), 'harness'),
]

a = Analysis(
    [os.path.join(SPECPATH, 'launcher.py')],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hidden,
    excludes=['dearpygui', 'tkinter', 'IPython', 'jupyter', 'notebook', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='fsoc-server',
          console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='fsoc-server', upx=False)
