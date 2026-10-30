"""
================================================================================
APPROACH B: PYTORCH 1D-CNN / NEURAL NETWORK FOR ATMOSPHERIC VERTICAL PROFILES
================================================================================

[INSTRUCTIONS FOR NEXT LLM]:
1. Data Pipeline Integration:
   - Use `sounderpy` or `herbie-data` (Python packages) to fetch atmospheric soundings (KDNR Denver radiosondes or HRRR grid forecasts).
   - Standardize inputs to a fixed vertical grid (e.g., 50 vertical pressure levels from 1000 hPa to 500 hPa).
2. Tensor Shape Expected:
   - Input Tensor: `(Batch_Size, Num_Channels, Num_Vertical_Levels)`
   - `Num_Channels`: e.g., 4 channels [Temperature, Dewpoint, U-wind, V-wind]
   - `Num_Vertical_Levels`: e.g., 50 standardized pressure/height steps.
3. Multi-Task Learning Objective (Optional Extension):
   - Output 1: Binary Classification (Inversion Present / Not Present)
   - Output 2: Regression Output [Inversion Base Height (m), Inversion Top Height (m), Delta T (°C)]
"""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import numpy as np

# ==============================================================================
# 1. CUSTOM DATASET CLASS FOR VERTICAL ATMOSPHERIC PROFILES
# ==============================================================================

class AtmosphericSoundingDataset(Dataset):
    """
    Dataset wrapper for 1D vertical profile soundings.
    
    Attributes:
    -----------
    profiles: np.ndarray of shape (N, C, L)
              N = samples, C = variables (Temp, Dewpoint, U-wind, V-wind), L = vertical levels
    labels: np.ndarray of shape (N,)
            Binary indicator (1 = Inversion present in boundary layer, 0 = Normal lapse rate)
    """
    def __init__(self, profiles: np.ndarray, labels: np.ndarray):
        self.profiles = torch.tensor(profiles, dtype=torch.float32)
        self.labels = torch.tensor(labels, dtype=torch.float32).unsqueeze(1)

    def __len__(self):
        return len(self.profiles)

    def __getitem__(self, idx):
        return self.profiles[idx], self.labels[idx]


# ==============================================================================
# 2. 1D-CNN ARCHITECTURE FOR VERTICAL ATMOSPHERIC SOUNDINGS
# ==============================================================================

class InversionProfileCNN1D(nn.Module):
    """
    1D Convolutional Neural Network designed to extract feature patterns 
    (such as thermal inversions or lapse rate changes) along the vertical atmospheric column.
    """
    def __init__(self, in_channels: int = 4, num_levels: int = 50):
        super(InversionProfileCNN1D, self).__init__()
        
        # 1D Convolutions slide vertically from ground level up through atmosphere
        self.conv_block = nn.Sequential(
            nn.Conv1d(in_channels=in_channels, out_channels=16, kernel_size=3, padding=1),
            nn.BatchNorm1d(16),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2),  # Halves resolution (50 -> 25)

            nn.Conv1d(in_channels=16, out_channels=32, kernel_size=3, padding=1),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(8)       # Fixed output size regardless of input profile depth
        )

        # Dense Classifier Head
        self.classifier = nn.Sequential(
            nn.Linear(32 * 8, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, 1)  # Outputs raw logits for binary classification
        )

    def forward(self, x):
        # Input shape: (Batch, Channels, Levels)
        x = self.conv_block(x)
        x = x.view(x.size(0), -1)  # Flatten
        logits = self.classifier(x)
        return logits


# ==============================================================================
# 3. TRAINING & VALIDATION LOOP
# ==============================================================================

def train_dl_inversion_model(model, dataloader, epochs=10, lr=1e-3):
    criterion = nn.BCEWithLogitsLoss()  # Numerically stable for binary classification
    optimizer = optim.Adam(model.parameters(), lr=lr)

    model.train()
    for epoch in range(epochs):
        total_loss = 0.0
        for profiles, labels in dataloader:
            optimizer.zero_grad()
            outputs = model(profiles)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * profiles.size(0)

        epoch_loss = total_loss / len(dataloader.dataset)
        print(f"Epoch [{epoch+1}/{epochs}] - Loss: {epoch_loss:.4f}")

    return model


# ==============================================================================
# 4. PLACEHOLDER EXECUTION FOR VERIFICATION
# ==============================================================================

if __name__ == "__main__":
    # Parameters matching real soundings
    NUM_SAMPLES = 500
    CHANNELS = 4       # [Temp, Dewpoint, U_wind, V_wind]
    HEIGHT_LEVELS = 50 # 50 discrete pressure layers

    # Generate random test profiles (Shape: [500, 4, 50])
    dummy_profiles = np.random.randn(NUM_SAMPLES, CHANNELS, HEIGHT_LEVELS)
    dummy_labels = np.random.randint(0, 2, size=NUM_SAMPLES)

    # Initialize Dataset and DataLoader
    dataset = AtmosphericSoundingDataset(dummy_profiles, dummy_labels)
    loader = DataLoader(dataset, batch_size=32, shuffle=True)

    # Instantiate and test model forward pass
    model = InversionProfileCNN1D(in_channels=CHANNELS, num_levels=HEIGHT_LEVELS)
    print("Model Architecture Initialized:\n", model)
    
    # Train test loop
    print("\nRunning test training loop...")
    trained_model = train_dl_inversion_model(model, loader, epochs=3)