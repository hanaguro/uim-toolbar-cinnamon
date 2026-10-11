#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import shutil
import time

UUID = 'uim-toolbar@hanaguro-port'
p = argparse.ArgumentParser(description='Install or uninstall the per-user uim Cinnamon applet')
p.add_argument('action', choices=['install', 'uninstall'])
p.add_argument('--replace', action='store_true', help='backup an existing installation, then replace it')
a = p.parse_args()
if hasattr(os, 'geteuid') and os.geteuid() == 0:
    p.error('Run as the desktop user, not root/sudo.')
source = Path(__file__).resolve().parent / UUID
base = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'cinnamon/applets'
target = base / UUID
if target.is_symlink():
    p.error('Refusing a symlink destination: ' + str(target))
if a.action == 'install':
    if not source.is_dir():
        p.error('Applet source directory missing')
    base.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not a.replace:
            p.error('Already installed; use --replace to backup and replace it')
        backup_base = Path.home() / '.local/state/uim-toolbar-cinnamon/backups'
        backup_base.mkdir(parents=True, exist_ok=True)
        backup = backup_base / (str(time.time_ns()) + '-' + UUID)
        target.rename(backup)
        print('Backup:', backup)
        try:
            shutil.copytree(source, target)
            if (backup / 'options.json').is_file():
                shutil.copy2(backup / 'options.json', target / 'options.json')
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            backup.rename(target)
            raise
    else:
        shutil.copytree(source, target)
    print('Installed:', target)
    print('Enable "uim Toolbar" in Cinnamon panel applets.')
else:
    if not target.exists():
        p.error('Not installed')
    import json
    try:
        installed_uuid = json.loads((target / 'metadata.json').read_text())['uuid']
    except Exception:
        p.error('Refusing to remove an unrecognized directory')
    if installed_uuid != UUID:
        p.error('UUID does not match')
    print('Remove the applet from the panel before uninstalling.')
    if input('Delete ' + str(target) + '? Type yes: ') != 'yes':
        p.error('Cancelled')
    shutil.rmtree(target)
    print('Removed:', target)
