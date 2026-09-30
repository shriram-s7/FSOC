"""Display contract: emphasis does not change measured rankings or values."""
import math

MODES = (
    dict(key='cv', label='CV', description='Classical candidates + calibrated feature score', color='#f4ad42', print_color='#986000'),
    dict(key='ai', label='AI', description='Whole-frame CNN scan + peak refinement', color='#ba8bff', print_color='#7744b6'),
    dict(key='hybrid', label='Hybrid', description='Classical candidates + CNN classification', color='#21dbc6', print_color='#007d71'),
)
METRICS = (
    ('rmse_px', 'Pointing RMSE', 'px', 'lower'),
    ('correct_lock_pct', 'Correct lock / all frames', '%', 'higher'),
    ('target_loss_pct', 'Target loss', '%', 'lower'),
    ('processing_fps', 'Pipeline-only rate', 'FPS', 'higher'),
)

def presentation(modes):
    rows = []
    for key, label, unit, direction in METRICS:
        values = {m['key']: modes.get(m['key'], {}).get('summary', {}).get(key) for m in MODES}
        valid = {k: round(v, 3) for k, v in values.items()
                 if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
        best = (min if direction == 'lower' else max)(valid.values()) if valid else None
        leaders = [k for k, v in valid.items() if v == best]
        rows.append(dict(key=key, label=label, unit=unit, direction=direction, values=values,
                         leaders=leaders, complete=len(valid) == 3))
    return dict(version='1-measured-beta', modes=list(MODES), metrics=rows,
                note='Beta comparison. Hybrid is the featured architecture; emphasis is not a performance ranking. '
                     'Leaders use measured values rounded to 0.001; ties are retained. Lower error/loss and higher lock/rate are better. '
                     'Pipeline rate is not end-to-end realtime FPS. Compare error sample coverage before claiming superiority.')
