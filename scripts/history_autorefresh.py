"""Create a macOS LaunchAgent that archives issued HRRR forecasts every 6 hours.

This deliberately only writes the plist. The user must explicitly run the
printed launchctl bootstrap command to enable recurring network downloads.
"""
import argparse
import plistlib
import sys
from pathlib import Path

from inversion.config import ROOT, DATA_DIR

LABEL = 'org.invertboulder.hrrr-history'


def plist_definition(python_executable=sys.executable, root=ROOT, seconds=21600):
    return {
        'Label': LABEL,
        'ProgramArguments': [str(python_executable), '-m', 'inversion.hrrr', 'live',
                             '--lead-hours', '12,18,24,30,36,39',
                             '--morning-hours', '5,6,7,8,9'],
        'WorkingDirectory': str(root),
        'RunAtLoad': True,
        'StartInterval': seconds,
        'StandardOutPath': str(DATA_DIR / 'history_refresh.log'),
        'StandardErrorPath': str(DATA_DIR / 'history_refresh_errors.log'),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=Path.home() / 'Library' /
                    'LaunchAgents' / (LABEL + '.plist'))
    a = ap.parse_args()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with a.output.open('wb') as stream:
        plistlib.dump(plist_definition(), stream)
    print(f'Wrote {a.output}')
    print('To enable automatic refreshes while this Mac is awake, run:')
    print(f'  launchctl bootstrap "gui/$(id -u)" "{a.output}"')
    print('To disable later, run:')
    print(f'  launchctl bootout "gui/$(id -u)" "{a.output}"')
    print('Sleep/lid closure/network outages can prevent scheduled downloads.')


if __name__ == '__main__':
    main()
