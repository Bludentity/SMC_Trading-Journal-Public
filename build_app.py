"""Build helper: create a single-file Windows exe and optionally install it."""
import os
import shutil
import subprocess
import argparse


def clean(paths):
    for p in paths:
        if os.path.exists(p):
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)


def build(icon='icon.ico', name='SMC_Journal'):
    here = os.getcwd()
    datas = []
    for d in ('templates', 'static', 'uploads', 'exports'):
        path = os.path.join(here, d)
        if os.path.exists(path):
            datas.append(f"{path};{d}")
    datas_arg = ' '.join([f'--add-data "{d}"' for d in datas])
    icon_arg = f'--icon "{icon}"' if icon and os.path.exists(os.path.join(here, icon)) else ''
    cmd = f'pyinstaller --onefile --noconsole {datas_arg} {icon_arg} --name "{name}" launcher.py'
    subprocess.check_call(cmd, shell=True)
    try:
        dist_path = os.path.join(here, 'dist', f'{name}.exe')
        if os.path.exists(dist_path):
            desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
            dest_dir = os.path.join(desktop, name)
            os.makedirs(dest_dir, exist_ok=True)
            dest_exe = os.path.join(dest_dir, f'{name}.exe')
            shutil.copy2(dist_path, dest_exe)
            try:
                lnk = os.path.join(desktop, f'{name}.lnk')
                ps = ("$w=New-Object -ComObject WScript.Shell;" f"$s=$w.CreateShortcut('{lnk}'); $s.TargetPath='{dest_exe}'; $s.WorkingDirectory='{dest_dir}'; $s.Save()")
                subprocess.call(['powershell', '-NoProfile', '-Command', ps])
            except Exception:
                pass
    except Exception:
        pass


def build_with_install(icon='icon.ico', name='SMC_Journal', install_dir=None):
    build(icon=icon, name=name)
    if install_dir:
        here = os.getcwd()
        dist_path = os.path.join(here, 'dist', f'{name}.exe')
        if os.path.exists(dist_path):
            try:
                os.makedirs(install_dir, exist_ok=True)
                shutil.copy2(dist_path, os.path.join(install_dir, f'{name}.exe'))
            except Exception:
                pass


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--icon', default='icon.ico')
    p.add_argument('--name', default='SMC_Journal')
    p.add_argument('--install-dir', default=None, help='Optional directory to copy the built exe to (overrides Desktop default)')
    args = p.parse_args()
    clean(['build', 'dist', f'{args.name}.spec'])
    if args.install_dir:
        build_with_install(icon=args.icon, name=args.name, install_dir=args.install_dir)
    else:
        build(icon=args.icon, name=args.name)
