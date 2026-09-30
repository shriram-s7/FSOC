"""
Beacon CNN Classifier — Inference Module
=========================================
Loads the trained BeaconCNN model and classifies detector candidates.

Usage:
    from detection.classifier import BeaconClassifier
    clf = BeaconClassifier()
    candidates = clf.classify(candidates)   # fills confidence + is_beacon

The classifier assigns each Candidate:
    candidate.confidence  = P(beacon), float [0, 1]
    candidate.is_beacon   = True if confidence > threshold

Threshold is set conservatively (0.60) for single-frame decisions.
Temporal fusion (Stage 5) does the real lock/unlock decision.
"""

import torch
import numpy as np
import os
from typing import List

MODEL_PATH = os.path.join('models', 'beacon_classifier.pt')


class BeaconCNN(torch.nn.Module):
    """Must match architecture in train_classifier.py exactly."""
    def __init__(self):
        super().__init__()
        self.features = torch.nn.Sequential(
            torch.nn.Conv2d(1, 8, kernel_size=3, padding=1),
            torch.nn.BatchNorm2d(8),
            torch.nn.ReLU(inplace=True),
            torch.nn.MaxPool2d(2),
            torch.nn.Conv2d(8, 16, kernel_size=3, padding=1),
            torch.nn.BatchNorm2d(16),
            torch.nn.ReLU(inplace=True),
            torch.nn.MaxPool2d(2),
            torch.nn.Conv2d(16, 32, kernel_size=3, padding=1),
            torch.nn.BatchNorm2d(32),
            torch.nn.ReLU(inplace=True),
            torch.nn.MaxPool2d(2),
        )
        self.classifier = torch.nn.Sequential(
            torch.nn.Flatten(),
            torch.nn.Linear(32 * 4 * 4, 64),
            torch.nn.ReLU(inplace=True),
            torch.nn.Dropout(0.4),
            torch.nn.Linear(64, 2),
        )

    def forward(self, x):
        return self.classifier(self.features(x))


class BeaconClassifier:
    """
    Loads trained BeaconCNN and classifies Candidate patches.
    Single-frame confidence scores (0-1).
    Temporal fusion in Stage 5 buffers these for stable decisions.
    """

    SINGLE_FRAME_THRESHOLD = 0.60

    def __init__(self, model_path=None):
        # Model file comes from config (classifier.model_path) so switching
        # between models is a one-line config change; falls back to v1.
        if model_path is None:
            from config.loader import cfg
            model_path = (cfg.get('classifier') or {}).get('model_path', MODEL_PATH)
        self.device = torch.device('cpu')   # always CPU for speed
        self.model  = BeaconCNN().to(self.device)

        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Model not found at {model_path}. "
                f"Run detection/train_classifier.py first."
            )

        checkpoint = torch.load(model_path, map_location=self.device)
        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.model.eval()

        val_acc = checkpoint.get('val_acc', 0)
        print(f"[Classifier] Loaded model (val_acc={val_acc*100:.1f}%)")

        # Warmup inference
        dummy = torch.zeros(1, 1, 32, 32)
        with torch.no_grad():
            self.model(dummy)

    def classify(self, candidates) -> list:
        """
        Classify all candidates in a single batched forward pass.
        Fills candidate.confidence and candidate.is_beacon in-place.

        Args:
            candidates: List[Candidate] from BeaconDetector.detect()

        Returns:
            Same list, sorted by confidence descending.
        """
        if not candidates:
            return candidates

        # Stack patches into batch tensor
        patches = np.stack([c.patch for c in candidates])  # (N, 32, 32)
        tensor  = torch.from_numpy(patches).unsqueeze(1)   # (N, 1, 32, 32)

        with torch.no_grad():
            logits = self.model(tensor)                     # (N, 2)
            probs  = torch.softmax(logits, dim=1)           # (N, 2)
            beacon_probs = probs[:, 1].numpy()              # P(beacon) for each

        for i, c in enumerate(candidates):
            c.confidence = float(beacon_probs[i])
            c.is_beacon  = c.confidence >= self.SINGLE_FRAME_THRESHOLD

        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    def top_beacon(self, candidates):
        """
        Returns the single most-likely beacon candidate, or None.
        Requires candidate to pass single-frame threshold.
        """
        classified = self.classify(candidates)
        for c in classified:
            if c.is_beacon:
                return c
        return None
