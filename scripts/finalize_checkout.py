"""Archive stale files when applying the public-data overlay to an older repo.

This script only moves selected legacy source/docs. It NEVER operates in data/
or models/, and does not delete existing files or overwrite archive collisions.
Run after extracting the overlay into the repository.
"""
from __future__ import annotations
from pathlib import Path
from shutil import move

ROOT = Path(__file__).resolve().parents[1]

LEGACY_FILES = (
    'inversion/train.py', 'inversion/hrrr_train.py',
    'inversion/models.py', 'inversion/predict.py',
    'inversion/features.py', 'inversion/weather.py',
    'scripts/data_status.py', 'scripts/archive_legacy_ml.py',
    'dl_inversion.py', 'xgb_inversion.py',
)
RELEASE_DOCS = (
    'FOOTHILLS_TRANSECT.md', 'HRRR_FIX_NOTES.md',
    'LEGACY_HISTORY_FIX.md', 'ONE_BUTTON_REFRESH.md',
    'QUICKLOOK.md', 'SCENIC_UPDATE_NOTES.md',
    'SCENIC_V2_AND_T0_NOTES.md', 'WEATHER_EXPLORER_NOTES.md',
)


def run(root=ROOT):
    root = Path(root)
    moved = []
    for relative in (*LEGACY_FILES, *RELEASE_DOCS):
        src = root / relative
        if not src.is_file() or src.is_symlink():
            continue
        folder = (root / 'archive' /
                  ('release-notes' if relative in RELEASE_DOCS else 'machine-learning/legacy-checkout'))
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / src.name
        if target.exists():
            # Preserve BOTH revisions. Never clobber an existing archive file.
            # Move even an identical copy: the active checkout should not
            # retain retired top-level docs or training entry points.
            # Use a unique archive name and never overwrite the old archive.
            counter = 1
            while (folder / f'{src.stem}.pre-cleanup-{counter}{src.suffix}').exists():
                counter += 1
            target = folder / f'{src.stem}.pre-cleanup-{counter}{src.suffix}'
        move(str(src), str(target))
        moved.append(f'{relative} -> {target.relative_to(root)}')
    print(f'Archived {len(moved)} inactive sources / old release notes.')
    for item in moved:
        print('  ' + item)
    print('data/ and models/ are never touched.')
    return moved


if __name__ == '__main__':
    run()
