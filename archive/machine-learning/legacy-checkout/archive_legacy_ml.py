"""Move old ML modules out of an existing checkout without deleting user data."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
dest = root / 'archive' / 'machine-learning' / 'legacy-checkout'
for rel in ('inversion/hrrr_train.py','inversion/models.py','inversion/predict.py','inversion/train.py',
            'xgb_inversion.py','dl_inversion.py','tests/test_history.py'):
    source = root / rel
    if source.exists():
        dest.mkdir(parents=True,exist_ok=True)
        target = dest/source.name
        if target.exists():
            target = dest/(source.name+'.legacy')
        shutil.move(str(source),str(target))
        print('Archived',rel)
print('User data and saved model weights remain untouched.')
