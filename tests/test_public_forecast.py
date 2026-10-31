from pathlib import Path
from inversion.server import forecast, health
from inversion.history import capture_published_live

def test_no_ml_dependency_loaded():
    import sys
    assert 'inversion.predict' not in sys.modules
    assert 'inversion.models' not in sys.modules
    assert not health()['trained_models_available']

def test_archived_files_present():
    root = Path(__file__).resolve().parents[1]
    assert (root/'archive/machine-learning/hrrr_train.py').exists()
    assert not (root/'inversion/models.py').exists()
