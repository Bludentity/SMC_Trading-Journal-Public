"""Helper to build a single-file Windows exe using PyInstaller.

Usage:
    python build_desktop.py --icon icon.ico --name SMC_Journal

This script constructs the PyInstaller command to include templates and static folders
and ensures a local .env next to the executable will be considered at runtime.
"""
import argparse
import subprocess
import shlex
import sys
import os

def build(icon=None, name="SMC_Journal"):
    here = os.path.abspath(os.path.dirname(__file__))
    templates = os.path.join(here, 'templates')
    static = os.path.join(here, 'static')
    datas = []
    if os.path.exists(templates):
        datas.append(f"{templates};templates")
    if os.path.exists(static):
        datas.append(f"{static};static")
    datas_arg = ' '.join([f'--add-data "{d}"' for d in datas])
    icon_arg = f'--icon "{icon}"' if icon else ''
    cmd = f'pyinstaller --onefile --noconsole {datas_arg} {icon_arg} --name "{name}" launcher.py'
    print('Running:', cmd)
    subprocess.check_call(cmd, shell=True)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--icon', help='path to icon.ico', default='icon.ico')
    p.add_argument('--name', help='exe name', default='SMC_Journal')
    args = p.parse_args()
    build(icon=args.icon, name=args.name)
