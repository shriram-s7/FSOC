"""Zero-leak proof: tracking / detection / control may use only the image
frames, their own state and the camera's own commanded motion.

1. Static check of the source (AST): no import of the simulator,
   disturbance engine, harness, scoring, UI or server packages, and no
   identifier, attribute, argument, keyword or string key naming ground
   truth, disturbance, atmosphere, noise settings, toggles or scenarios.
   Docstrings and comments are not inspected (they may explain what the
   code deliberately does NOT use).
2. Signature check of the public tracking API.
3. Behavioural check: S08 seed 1 (fog event) run twice - normally, and
   with the shared state's disturbance dict AND the disturbance engine's
   own fields overwritten with wrong values from just before the tracker
   runs until after the servo has moved (restored before the next render,
   so the rendered images are identical). The trace hashes must match.

Run:  venv\\Scripts\\python -m unittest tests.test_no_leak
(the behavioural test takes ~2-4 min; set FSOC_SKIP_SLOW=1 to skip it).
"""
import ast
import inspect
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKED_DIRS = ('tracking', 'detection', 'control')
EXEMPT = {'generate_training_data.py', 'train_classifier.py'}

FORBIDDEN_MODULES = ('disturbance', 'simulation', 'harness', 'evaluation',
                     'ui', 'server', 'input')
# Identifiers / attributes / argument names / string constants.
FORBIDDEN = re.compile(
    r'^(gt|ground_?truth|truth)(_|$)|_gt$|_gt_|'
    r'atmosphere|disturbance|low_light|toggle|scenario|'
    r'turbulence|scintillation|vibration|^jerk|platform_(enabled|speed|motion)|'
    r'applied_offset|^tgt_|^occluded$|'
    r'^noise$|^noise_(gaussian|saltpepper|poisson|types)$|shared_state',
    re.IGNORECASE)


def checked_files():
    for d in CHECKED_DIRS:
        for p in sorted((ROOT / d).glob('*.py')):
            if p.name not in EXEMPT:
                yield p


def violations(src, name='<src>'):
    """List of 'file:line: what' for every leak-shaped reference in src."""
    tree = ast.parse(src)
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, 'body', [])
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                doc_ids.add(id(body[0].value))
    out = []

    def bad(node, what):
        out.append(f'{name}:{getattr(node, "lineno", "?")}: {what}')

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split('.')[0] in FORBIDDEN_MODULES:
                    bad(node, f'import {a.name}')
        elif isinstance(node, ast.ImportFrom):
            if (node.module or '').split('.')[0] in FORBIDDEN_MODULES:
                bad(node, f'from {node.module} import ...')
        elif isinstance(node, ast.Name) and FORBIDDEN.search(node.id):
            bad(node, f'name {node.id}')
        elif isinstance(node, ast.Attribute) and FORBIDDEN.search(node.attr):
            bad(node, f'attribute .{node.attr}')
        elif isinstance(node, ast.arg) and FORBIDDEN.search(node.arg):
            bad(node, f'argument {node.arg}')
        elif isinstance(node, ast.keyword) and node.arg and FORBIDDEN.search(node.arg):
            bad(node, f'keyword {node.arg}=')
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in doc_ids and len(node.value) < 40 \
                and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', node.value) \
                and FORBIDDEN.search(node.value):
            bad(node, f'string key {node.value!r}')
    return out


class TestStaticNoLeak(unittest.TestCase):
    def test_source_has_no_leak(self):
        found = []
        for p in checked_files():
            found += violations(p.read_text(encoding='utf-8'),
                                str(p.relative_to(ROOT)))
        self.assertEqual(found, [], 'leak-shaped references:\n' + '\n'.join(found))

    def test_checker_catches_planted_violations(self):
        planted = [
            "def f(state):\n    return state['disturbances']['atmosphere']\n",
            "def f(sim):\n    return sim.gt_sx\n",
            "from disturbance.disturbance import DisturbanceEngine\n",
            "def process(self, c, atmosphere='clear'):\n    pass\n",
            "def f(t):\n    t.adapt(noise=0.5)\n",
        ]
        for src in planted:
            with self.subTest(src=src):
                self.assertTrue(violations(src))


class TestSignatures(unittest.TestCase):
    def test_public_tracking_api(self):
        from tracking.tracker import MasterTracker
        from tracking.temporal_fusion import TemporalFusionBuffer
        from tracking.stabiliser import ImageStabiliser
        from tracking.scene_estimator import SceneEstimator
        from control.camera_servo import CameraServo
        from detection.detector import BeaconDetector
        self.assertEqual(list(inspect.signature(MasterTracker.process).parameters),
                         ['self', 'candidates', 'camera', 'dt', 'gray', 'raw'])
        self.assertEqual(list(inspect.signature(MasterTracker.predict_only).parameters),
                         ['self', 'camera'])
        self.assertEqual(list(inspect.signature(SceneEstimator.update).parameters),
                         ['self', 'raw', 'cleaned', 'blobs', 'dt'])
        self.assertFalse(hasattr(TemporalFusionBuffer, 'adapt_to_conditions'))
        for fn in (MasterTracker.__init__, MasterTracker.process,
                   MasterTracker.predict_only, TemporalFusionBuffer.update,
                   TemporalFusionBuffer.apply_params, ImageStabiliser.update,
                   SceneEstimator.update, CameraServo.update, BeaconDetector.detect):
            for p in inspect.signature(fn).parameters:
                self.assertIsNone(FORBIDDEN.search(p), f'{fn.__qualname__}({p})')


WRONG = {'turbulence': 0.9, 'vibration': 0.9, 'noise': 1.0, 'scintillation': 0.9,
         'jerk': 0.1, 'atmosphere': 'dense_fog', 'noise_gaussian': True,
         'noise_saltpepper': True, 'noise_poisson': True, 'platform_enabled': True,
         'platform_speed': 50.0, 'low_light': True}
ENGINE_FIELDS = {'turbulence': 'turbulence', 'vibration': 'vibration', 'noise': 'noise',
                 'scintillation': 'scintillation', 'jerk': 'jerk_prob',
                 'atmosphere': 'atmosphere', 'noise_gaussian': 'noise_gaussian',
                 'noise_saltpepper': 'noise_saltpepper', 'noise_poisson': 'noise_poisson',
                 'platform_enabled': 'platform_enabled', 'platform_speed': 'platform_speed',
                 'low_light': 'low_light'}


def run_s08(corrupt, duration_s=26.0):
    """S08 seed 1 (fog 20-25 s) trace hash; corrupt=True overwrites every
    disturbance field the tracker/servo could possibly see."""
    from harness import runner
    from harness.scenarios import load_scenarios
    from tracking.tracker import MasterTracker
    from control.camera_servo import CameraServo
    saved = {}
    orig_process, orig_update = MasterTracker.process, CameraServo.update
    holder = {}

    def process(self, *a, **k):
        sim = holder.get('sim')
        if corrupt and sim is not None:
            saved['state'] = sim.state.get('disturbances')
            sim.state['disturbances'] = dict(WRONG)
            eng = sim.disturbance
            saved['engine'] = {f: getattr(eng, f) for f in ENGINE_FIELDS.values()}
            for k_, f in ENGINE_FIELDS.items():
                setattr(eng, f, WRONG[k_])
        return orig_process(self, *a, **k)

    def update(self, *a, **k):
        r = orig_update(self, *a, **k)
        sim = holder.get('sim')
        if corrupt and sim is not None and 'state' in saved:
            sim.state['disturbances'] = saved.pop('state')
            for f, v in saved.pop('engine').items():
                setattr(sim.disturbance, f, v)
        return r

    import ui.sim_thread as st
    orig_build = st.SimulationThread.build_pipeline

    def build(self, seed):
        holder['sim'] = self
        return orig_build(self, seed)

    MasterTracker.process, CameraServo.update = process, update
    st.SimulationThread.build_pipeline = build
    try:
        m = runner.run_one(load_scenarios()['S08'], 1, duration_s=duration_s)
    finally:
        MasterTracker.process, CameraServo.update = orig_process, orig_update
        st.SimulationThread.build_pipeline = orig_build
    return m['trace_hash']


@unittest.skipIf(os.environ.get('FSOC_SKIP_SLOW'), 'slow behavioural test skipped')
class TestBehaviouralNoLeak(unittest.TestCase):
    def test_s08_hash_ignores_disturbance_settings(self):
        self.assertEqual(run_s08(False), run_s08(True))


if __name__ == '__main__':
    unittest.main()
