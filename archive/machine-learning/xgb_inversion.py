"""Compatibility entry point; implementation lives in inversion.models/train."""
from inversion.models import train_xgb
from inversion.train import main

if __name__ == '__main__':
    main()
