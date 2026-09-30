"""
Synthetic Training Data Generator for Beacon CNN Classifier
============================================================
Generates two classes of 32x32 grayscale patches:
  Class 0: DISTRACTOR — objects that look similar to beacon but aren't it
  Class 1: TRUE BEACON — the actual FSOC optical beacon

Why synthetic data works here:
  We control the simulator exactly, so we know precisely what the beacon
  looks like vs distractors. We generate patches that match the exact
  visual characteristics of our simulation under all disturbance conditions.

Output:
  data/training/beacon_patches.npy      shape: (N, 32, 32) float32 [0,1]
  data/training/beacon_labels.npy       shape: (N,) int64 {0=distractor, 1=beacon}
  data/training/val_patches.npy         validation set
  data/training/val_labels.npy
  data/training/test_patches.npy        test set
  data/training/test_labels.npy

Generates 12,000 total samples: 6000 beacon, 6000 distractor
Split: 70% train, 15% val, 15% test
"""

import numpy as np
import os
import cv2

OUTPUT_DIR = os.path.join('data', 'training')
os.makedirs(OUTPUT_DIR, exist_ok=True)

PATCH_SIZE = 32
HALF = PATCH_SIZE // 2
N_PER_CLASS = 6000
TOTAL = N_PER_CLASS * 2

# Reproducibility
np.random.seed(42)

# Real distractor spawn ranges — mirrors simulation/distractors.py Distractors._spawn()
# exactly, since both beacon and distractors are rendered by the identical
# world.py World._draw_gaussian_blob() ring function; only these parameter
# ranges (and the beacon-only white core, see render_ring_blob) differ.
DISTRACTOR_RADIUS_RANGE     = (3, 7)
DISTRACTOR_BRIGHTNESS_RANGE = (140, 200)
DISTRACTOR_COLOR_R_RANGE    = (180, 255)
DISTRACTOR_COLOR_G_RANGE    = (160, 220)
DISTRACTOR_COLOR_B_RANGE    = (50, 150)

# Real beacon params — mirrors config/default.yaml target: section
BEACON_RADIUS    = 6
BEACON_COLOR     = (255, 220, 100)


def luminance(color):
    """RGB -> grayscale value using the same BT.601 weights cv2.cvtColor
    (COLOR_RGB2GRAY) uses when the detector converts frames to grayscale."""
    r, g, b = color
    return 0.299 * r + 0.587 * g + 0.114 * b


def render_ring_blob(patch, cx, cy, radius, gray_peak):
    """
    Reproduce world.py's World._draw_gaussian_blob() exactly, but directly
    in grayscale space (verified against real detector-extracted patches):
    that function fills concentric integer-radius circles from r=radius
    down to r=1, so a pixel at distance d from center ends up with the
    value drawn by the SMALLEST integer circle that still contains it,
    i.e. r_eff = ceil(d) clamped to [1, radius]. Each ring's value is
    gray_peak * sqrt(r/radius) (from world.py's `frac = (r/radius)**0.5`).
    This produces the exact hard-edged "bullseye" bands the renderer
    actually draws — NOT a smooth Gaussian falloff.
    """
    radius = max(radius, 1.0)
    Y, X = np.ogrid[:PATCH_SIZE, :PATCH_SIZE]
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    r_eff = np.clip(np.ceil(dist), 1, radius)
    val = gray_peak * np.sqrt(r_eff / radius)
    mask = dist <= radius
    patch[mask] = np.maximum(patch[mask], val[mask])
    return patch


def make_blank_patch():
    """Black patch with slight background noise."""
    bg = np.random.uniform(0, 8, (PATCH_SIZE, PATCH_SIZE)).astype(np.float32)
    return bg


def add_stars_background(patch, n_stars=None):
    """Add faint star-like point sources to background."""
    if n_stars is None:
        n_stars = np.random.randint(0, 4)
    for _ in range(n_stars):
        sx = np.random.randint(0, PATCH_SIZE)
        sy = np.random.randint(0, PATCH_SIZE)
        brightness = np.random.uniform(15, 60)
        patch[sy, sx] = min(255, patch[sy, sx] + brightness)
        # Sometimes a 1px halo
        if np.random.random() < 0.3:
            for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
                nx, ny = sx+dx, sy+dy
                if 0 <= nx < PATCH_SIZE and 0 <= ny < PATCH_SIZE:
                    patch[ny, nx] = min(255, patch[ny, nx] + brightness * 0.2)
    return patch


def apply_noise(patch, noise_level):
    """Add Gaussian noise scaled by noise_level (0-1)."""
    if noise_level < 0.01:
        return patch
    sigma = noise_level * 40.0
    noise = np.random.normal(0, sigma, patch.shape).astype(np.float32)
    return np.clip(patch + noise, 0, 255)


def apply_blur(patch, blur_level):
    """Apply Gaussian blur scaled by blur_level (0-1)."""
    if blur_level < 0.01:
        return patch
    ksize = int(blur_level * 4) * 2 + 1  # must be odd, 1-9
    ksize = max(1, min(9, ksize))
    if ksize % 2 == 0:
        ksize += 1
    return cv2.GaussianBlur(patch, (ksize, ksize), 0)


def apply_translation(patch, max_offset):
    """Shift patch contents by random offset (vibration simulation)."""
    if max_offset < 1:
        return patch
    dx = np.random.randint(-max_offset, max_offset + 1)
    dy = np.random.randint(-max_offset, max_offset + 1)
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(patch, M, (PATCH_SIZE, PATCH_SIZE),
                          borderMode=cv2.BORDER_REFLECT)


def make_beacon_patch():
    """
    Generate a TRUE BEACON patch.
    Beacon characteristics:
      - Rendered by the SAME ring-blob function real distractors use, but:
          * fixed radius matching cfg.target.beacon_radius (config never
            varies it at runtime — only brightness varies, via scintillation)
          * yellow-white beacon color from cfg.target.beacon_color
          * a solid saturated WHITE core circle on top — real world.py only
            draws this extra core for the true beacon, never for distractors,
            so it is the strongest and most reliable discriminating feature
      - Intensity varies 0.15x-1.35x to mirror DisturbanceEngine's
        scintillation multiplier range, then clamped like world.py does
        (bi = max(30, min(255, int(bi*scint))))
      - Slight position jitter to mirror imperfect detector centroiding
    """
    patch = make_blank_patch()
    add_stars_background(patch, n_stars=np.random.randint(0, 3))

    # Center with slight random offset (detector centroid isn't pixel-perfect)
    cx = HALF + np.random.uniform(-2, 2)
    cy = HALF + np.random.uniform(-2, 2)

    radius = BEACON_RADIUS + np.random.uniform(-0.5, 0.5)

    # Scintillation-driven intensity, exactly mirroring world.py's clamp
    scint = np.random.uniform(0.15, 1.35)
    bi = int(max(30, min(255, 255 * scint)))
    gray_peak = luminance(BEACON_COLOR) * (bi / 255.0)

    patch = render_ring_blob(patch, cx, cy, radius, gray_peak)

    # Solid white core — ONLY the true beacon gets this (world.py draws it
    # unconditionally after the ring blob, regardless of scintillation)
    core_r = max(1, int(BEACON_RADIUS // 3))
    Y, X = np.ogrid[:PATCH_SIZE, :PATCH_SIZE]
    core_mask = (X - cx) ** 2 + (Y - cy) ** 2 <= core_r ** 2
    patch[core_mask] = 255.0

    # Apply disturbances at random levels
    noise_lvl = np.random.uniform(0, 0.6)
    blur_lvl  = np.random.uniform(0, 0.4)
    vib_offset = np.random.randint(0, 3)

    patch = apply_noise(patch, noise_lvl)
    patch = apply_blur(patch, blur_lvl)
    patch = apply_translation(patch, vib_offset)

    return np.clip(patch, 0, 255).astype(np.float32) / 255.0


def make_distractor_patch(distractor_type=None):
    """
    Generate a DISTRACTOR patch.
    Distractors are bright objects that LOOK like the beacon but aren't.
    Multiple sub-types make the classifier robust:
      Type 0: Dim beacon-like blob (similar shape, lower intensity)
      Type 1: Offset blob (blob not centered — distractor moving through)
      Type 2: Star cluster (multiple point sources)
      Type 3: Elongated blob (non-circular, different shape)
      Type 4: Bright noise peak (noise artifact that passes blob detection)
      Type 5: Double blob (two overlapping sources)
    """
    if distractor_type is None:
        distractor_type = np.random.randint(0, 6)

    patch = make_blank_patch()
    add_stars_background(patch, n_stars=np.random.randint(0, 5))

    if distractor_type == 0:
        # Real distractor blob — same ring-render function as the beacon,
        # same radius/color/brightness ranges as simulation/distractors.py,
        # but crucially NO white core (world.py never draws one for these).
        cx = HALF + np.random.uniform(-2, 2)
        cy = HALF + np.random.uniform(-2, 2)
        radius = np.random.uniform(*DISTRACTOR_RADIUS_RANGE)
        brightness = np.random.uniform(*DISTRACTOR_BRIGHTNESS_RANGE)
        color = (
            np.random.uniform(*DISTRACTOR_COLOR_R_RANGE),
            np.random.uniform(*DISTRACTOR_COLOR_G_RANGE),
            np.random.uniform(*DISTRACTOR_COLOR_B_RANGE),
        )
        gray_peak = luminance(color) * (brightness / 255.0)
        patch = render_ring_blob(patch, cx, cy, radius, gray_peak)

    elif distractor_type == 1:
        # Off-center distractor blob — near edge of patch, same ring-render
        cx = np.random.uniform(4, 12) if np.random.random() < 0.5 else \
             np.random.uniform(20, 28)
        cy = np.random.uniform(4, 28)
        radius = np.random.uniform(*DISTRACTOR_RADIUS_RANGE)
        brightness = np.random.uniform(*DISTRACTOR_BRIGHTNESS_RANGE)
        color = (
            np.random.uniform(*DISTRACTOR_COLOR_R_RANGE),
            np.random.uniform(*DISTRACTOR_COLOR_G_RANGE),
            np.random.uniform(*DISTRACTOR_COLOR_B_RANGE),
        )
        gray_peak = luminance(color) * (brightness / 255.0)
        patch = render_ring_blob(patch, cx, cy, radius, gray_peak)

    elif distractor_type == 2:
        # Star cluster — 2-4 point sources
        n = np.random.randint(2, 5)
        for _ in range(n):
            sx = np.random.randint(4, PATCH_SIZE-4)
            sy = np.random.randint(4, PATCH_SIZE-4)
            br = np.random.uniform(60, 180)
            Y, X = np.ogrid[:PATCH_SIZE, :PATCH_SIZE]
            blob = br * np.exp(-((X-sx)**2 + (Y-sy)**2) / (2*1.5**2))
            patch = np.clip(patch + blob, 0, 255)

    elif distractor_type == 3:
        # Elongated blob — clearly non-circular
        cx, cy = HALF, HALF
        peak = np.random.uniform(150, 220)
        sigma_x = np.random.uniform(5.0, 10.0)
        sigma_y = np.random.uniform(1.0, 2.5)
        # Random rotation
        angle = np.random.uniform(0, np.pi)
        Y, X = np.ogrid[:PATCH_SIZE, :PATCH_SIZE]
        Xr = (X-cx)*np.cos(angle) + (Y-cy)*np.sin(angle)
        Yr = -(X-cx)*np.sin(angle) + (Y-cy)*np.cos(angle)
        blob = peak * np.exp(-(Xr**2/(2*sigma_x**2) + Yr**2/(2*sigma_y**2)))
        patch = np.clip(patch + blob, 0, 255)

    elif distractor_type == 4:
        # Noise peak — random bright noise cluster
        cx = np.random.randint(8, PATCH_SIZE-8)
        cy = np.random.randint(8, PATCH_SIZE-8)
        for _ in range(np.random.randint(3, 8)):
            nx = cx + np.random.randint(-4, 5)
            ny = cy + np.random.randint(-4, 5)
            if 0 <= nx < PATCH_SIZE and 0 <= ny < PATCH_SIZE:
                patch[ny, nx] = min(255, patch[ny, nx] + np.random.uniform(80, 200))

    elif distractor_type == 5:
        # Double blob — two overlapping distractors, same ring-render
        for _ in range(2):
            cx = HALF + np.random.uniform(-6, 6)
            cy = HALF + np.random.uniform(-6, 6)
            radius = np.random.uniform(*DISTRACTOR_RADIUS_RANGE)
            brightness = np.random.uniform(*DISTRACTOR_BRIGHTNESS_RANGE)
            color = (
                np.random.uniform(*DISTRACTOR_COLOR_R_RANGE),
                np.random.uniform(*DISTRACTOR_COLOR_G_RANGE),
                np.random.uniform(*DISTRACTOR_COLOR_B_RANGE),
            )
            gray_peak = luminance(color) * (brightness / 255.0)
            patch = render_ring_blob(patch, cx, cy, radius, gray_peak)

    # Apply disturbances
    noise_lvl = np.random.uniform(0, 0.7)
    blur_lvl  = np.random.uniform(0, 0.5)
    vib_offset = np.random.randint(0, 4)

    patch = apply_noise(patch, noise_lvl)
    patch = apply_blur(patch, blur_lvl)
    patch = apply_translation(patch, vib_offset)

    return np.clip(patch, 0, 255).astype(np.float32) / 255.0


def generate_dataset():
    print(f"Generating {TOTAL} synthetic patches...")
    print(f"  {N_PER_CLASS} beacon patches (class 1)")
    print(f"  {N_PER_CLASS} distractor patches (class 0)")

    patches = np.zeros((TOTAL, PATCH_SIZE, PATCH_SIZE), dtype=np.float32)
    labels  = np.zeros(TOTAL, dtype=np.int64)

    # Generate beacon patches
    print("  Generating beacon patches...")
    for i in range(N_PER_CLASS):
        patches[i] = make_beacon_patch()
        labels[i]  = 1
        if (i+1) % 1000 == 0:
            print(f"    {i+1}/{N_PER_CLASS}")

    # Generate distractor patches
    print("  Generating distractor patches...")
    for i in range(N_PER_CLASS):
        idx = N_PER_CLASS + i
        dtype = i % 6   # cycle through all 6 distractor types
        patches[idx] = make_distractor_patch(dtype)
        labels[idx]  = 0
        if (i+1) % 1000 == 0:
            print(f"    {i+1}/{N_PER_CLASS}")

    # Shuffle
    perm = np.random.permutation(TOTAL)
    patches = patches[perm]
    labels  = labels[perm]

    # Split 70/15/15
    n_train = int(TOTAL * 0.70)
    n_val   = int(TOTAL * 0.15)

    train_p = patches[:n_train]
    train_l = labels[:n_train]
    val_p   = patches[n_train:n_train+n_val]
    val_l   = labels[n_train:n_train+n_val]
    test_p  = patches[n_train+n_val:]
    test_l  = labels[n_train+n_val:]

    # Save
    np.save(os.path.join(OUTPUT_DIR, 'beacon_patches.npy'), train_p)
    np.save(os.path.join(OUTPUT_DIR, 'beacon_labels.npy'),  train_l)
    np.save(os.path.join(OUTPUT_DIR, 'val_patches.npy'),    val_p)
    np.save(os.path.join(OUTPUT_DIR, 'val_labels.npy'),     val_l)
    np.save(os.path.join(OUTPUT_DIR, 'test_patches.npy'),   test_p)
    np.save(os.path.join(OUTPUT_DIR, 'test_labels.npy'),    test_l)

    print(f"\nDataset saved to {OUTPUT_DIR}/")
    print(f"  Train: {len(train_p)} samples")
    print(f"  Val:   {len(val_p)} samples")
    print(f"  Test:  {len(test_p)} samples")

    # Quick sanity check
    beacon_count = int(train_l.sum())
    distractor_count = len(train_l) - beacon_count
    print(f"  Train class balance: {beacon_count} beacon, "
          f"{distractor_count} distractor")


# ── v2: patches rendered through the simulator itself ───────────────────────
#
# The v1 patches above are synthetic ring blobs. v2 renders real scenes with
# the simulator's own World / DisturbanceEngine and takes the 32x32 patches
# exactly as BeaconDetector hands them to the CNN — for the (square) beacon
# (class 1) and for stars and round distractors (class 0) — under clean,
# noise (salt & pepper up to 10%, Gaussian sigma up to 20, Poisson), fog /
# haze / low light, and distractor conditions.
#
# Seeds: train 1000-1005, held-out test 2000-2001 — disjoint from every
# harness scenario seed (1-5, 42), so no test frame leaks into training.
#
#   python -m detection.generate_training_data --v2
#
# Output: data/training_v2/{train,val,test}_{patches,labels,cond}.npy

V2_DIR = os.path.join('data', 'training_v2')
V2_TRAIN_SEEDS = [1000, 1001, 1002, 1003, 1004, 1005]
V2_TEST_SEEDS = [2000, 2001]
V2_CONDITIONS = ['clean', 'saltpepper', 'gaussian', 'poisson',
                 'fog', 'haze', 'low_light', 'distractor']
# Condition groups used for per-condition accuracy.
V2_GROUP = {'clean': 'clean', 'saltpepper': 'noise', 'gaussian': 'noise',
            'poisson': 'noise', 'fog': 'fog', 'haze': 'fog',
            'low_light': 'fog', 'distractor': 'distractor'}


def _v2_worker(seed, n_frames, out_path):
    """Render n_frames scenes with seed; save candidate patches to out_path."""
    import math, random, types
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    import pygame
    from config.loader import cfg
    from simulation.world import World
    from disturbance.disturbance import DisturbanceEngine
    from detection.detector import BeaconDetector

    random.seed(seed)
    rng = np.random.RandomState(seed)
    np.random.seed(seed)          # DisturbanceEngine noise uses np.random
    pygame.init()
    world = World(cfg)
    detector = BeaconDetector(cfg)
    W, H = int(cfg.world.width), int(cfg.world.height)

    patches, labels, conds = [], [], []
    for k in range(n_frames):
        cond = V2_CONDITIONS[k % len(V2_CONDITIONS)]
        cam_x = rng.uniform(400, W - 400); cam_y = rng.uniform(300, H - 300)
        bsx = rng.uniform(40, 600); bsy = rng.uniform(40, 440)
        target = types.SimpleNamespace(
            wx=bsx + cam_x - 320, wy=bsy + cam_y - 240,
            size_px=int(cfg.target.size_px), color=tuple(cfg.target.color),
            brightness=int(cfg.target.brightness))
        # Round distractors (same ranges as simulation/distractors.py):
        # near the beacon for the distractor condition, sometimes elsewhere.
        n_d = rng.randint(1, 4) if cond == 'distractor' else int(rng.rand() < 0.3)
        dists = []
        for _ in range(n_d):
            if cond == 'distractor':
                ang = rng.uniform(0, 2 * math.pi); r = rng.uniform(15, 90)
                dsx, dsy = bsx + r * math.cos(ang), bsy + r * math.sin(ang)
            else:
                dsx, dsy = rng.uniform(20, 620), rng.uniform(20, 460)
            dists.append({'wx': dsx + cam_x - 320, 'wy': dsy + cam_y - 240,
                          'size': rng.randint(8, 13), 'brightness': rng.randint(220, 256),
                          'color': (rng.randint(235, 256), rng.randint(235, 256),
                                    rng.randint(215, 256)),
                          'shape': 'round'})

        surf, _ = world.render(cam_x, cam_y, [target], distractors=dists,
                               obstacles=[], scintillation=rng.uniform(0.6, 1.0))
        eng = DisturbanceEngine(cfg)
        lvl = rng.uniform(0.3, 1.0)
        kw = dict(noise=0.0, atmosphere='clear')
        if cond in ('saltpepper', 'gaussian', 'poisson'):
            kw.update(noise=lvl, noise_gaussian=cond == 'gaussian',
                      noise_saltpepper=cond == 'saltpepper',
                      noise_poisson=cond == 'poisson')
        elif cond in ('fog', 'haze', 'low_light'):
            kw.update(atmosphere=cond)
        eng.set_levels(**kw)
        surf = eng.apply(surf.copy(), 1 / 60)

        cands = detector.detect(surf)
        pos = [c for c in cands if math.hypot(c.x - bsx, c.y - bsy) < 5]
        if pos:
            patches.append(pos[0].patch); labels.append(1); conds.append(cond)
        neg = [c for c in cands if c not in pos]
        near_d = [c for c in neg if any(math.hypot(c.x - (d['wx'] - cam_x + 320),
                                                   c.y - (d['wy'] - cam_y + 240)) < 6
                                        for d in dists)]
        others = [c for c in neg if c not in near_d]
        rng.shuffle(others)
        for c in near_d + others[:max(0, 2 - len(near_d))]:
            patches.append(c.patch); labels.append(0)
            conds.append('distractor' if c in near_d else cond)
    np.savez(out_path, patches=np.array(patches, dtype=np.float32),
             labels=np.array(labels, dtype=np.int64), cond=np.array(conds))


def generate_dataset_v2(frames_per_seed=1600, test_frames_per_seed=800):
    import subprocess, sys
    os.makedirs(V2_DIR, exist_ok=True)
    jobs = [(s, frames_per_seed) for s in V2_TRAIN_SEEDS] + \
           [(s, test_frames_per_seed) for s in V2_TEST_SEEDS]
    procs = []
    for s, n in jobs:
        out = os.path.join(V2_DIR, f'part_{s}.npz')
        procs.append((s, out, subprocess.Popen(
            [sys.executable, '-m', 'detection.generate_training_data',
             '--v2-worker', str(s), str(n), out])))
    for s, out, p in procs:
        if p.wait() != 0:
            raise RuntimeError(f'v2 worker seed {s} failed')

    def load(seeds):
        parts = [np.load(os.path.join(V2_DIR, f'part_{s}.npz')) for s in seeds]
        return (np.concatenate([p['patches'] for p in parts]),
                np.concatenate([p['labels'] for p in parts]),
                np.concatenate([p['cond'] for p in parts]))

    tr_p, tr_l, tr_c = load(V2_TRAIN_SEEDS)
    te_p, te_l, te_c = load(V2_TEST_SEEDS)

    # Keep the v1 synthetic train/val data in the mix (condition 'v1').
    v1_p = np.concatenate([np.load(os.path.join(OUTPUT_DIR, 'beacon_patches.npy')),
                           np.load(os.path.join(OUTPUT_DIR, 'val_patches.npy'))])
    v1_l = np.concatenate([np.load(os.path.join(OUTPUT_DIR, 'beacon_labels.npy')),
                           np.load(os.path.join(OUTPUT_DIR, 'val_labels.npy'))])
    all_p = np.concatenate([tr_p, v1_p]); all_l = np.concatenate([tr_l, v1_l])
    all_c = np.concatenate([tr_c, np.array(['v1'] * len(v1_l))])

    rng = np.random.RandomState(7)
    perm = rng.permutation(len(all_l))
    n_val = int(0.15 * len(perm))
    val_i, trn_i = perm[:n_val], perm[n_val:]
    for name, idx_p, idx_l, idx_c in (
            ('train', all_p[trn_i], all_l[trn_i], all_c[trn_i]),
            ('val', all_p[val_i], all_l[val_i], all_c[val_i]),
            ('test', te_p, te_l, te_c)):
        np.save(os.path.join(V2_DIR, f'{name}_patches.npy'), idx_p)
        np.save(os.path.join(V2_DIR, f'{name}_labels.npy'), idx_l)
        np.save(os.path.join(V2_DIR, f'{name}_cond.npy'), idx_c)
        print(f'  {name}: {len(idx_l)} patches ({int(idx_l.sum())} beacon)')
    print(f'Dataset v2 saved to {V2_DIR}/')


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--v2-worker':
        _v2_worker(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
    elif len(sys.argv) > 1 and sys.argv[1] == '--v2':
        generate_dataset_v2()
        print("Done. Run: python -m detection.train_classifier --v2")
    else:
        generate_dataset()
        print("Done. Run train_classifier.py next.")
