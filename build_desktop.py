import argparse
import subprocess
import os


def build(icon=None, name="SMC_Journal"):
    here = os.path.abspath(os.path.dirname(__file__))
    datas = []
    for d in ('templates', 'static'):
        path = os.path.join(here, d)
        if os.path.exists(path):
            datas.append(f"{path};{d}")
    datas_arg = ' '.join([f'--add-data "{d}"' for d in datas])
    icon_arg = f'--icon "{icon}"' if icon and os.path.exists(icon) else ''
    cmd = f'pyinstaller --onefile --noconsole {datas_arg} {icon_arg} --name "{name}" launcher.py'
    subprocess.check_call(cmd, shell=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--icon', default='icon.ico')
    p.add_argument('--name', default='SMC_Journal')
    args = p.parse_args()
    build(icon=args.icon, name=args.name)
