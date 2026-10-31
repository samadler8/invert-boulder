"""Compatibility entry point; implementation lives in inversion.models/train."""
from inversion.models import ProfileCNN, train_cnn
from inversion.train import main

if __name__ == '__main__':
    main()
