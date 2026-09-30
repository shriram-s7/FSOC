"""Configured application checks; no claim of independent PS certification."""
import math

def evaluate(summary, realtime=True):
    definitions = [
        ('acquisition_time_s', 'Acquisition time', 2.0, 's', '<=', False),
        ('mean_track_error_px', 'Centroid error vs GT' if summary.get('mode') == 'video' else 'Mean pointing error', 10.0, 'px', '<=', True),
        ('target_loss_pct', 'Target loss', 5.0, '%', '<', True),
        ('reacq_time_s', 'Re-acquisition time', 1.0, 's', '<=', True),
        ('mean_fps', 'End-to-end processing rate', 20.0, 'FPS', '>=', False),
    ]
    rows = []
    for key, label, limit, unit, op, needs_gt in definitions:
        value = summary.get(key)
        reason = ''
        if summary.get('total_frames') == 0:
            status, reason = 'NOT_TESTED', 'No frames recorded'
        elif needs_gt and not summary.get('scored_with_gt'):
            status, reason = 'NOT_SCORED', 'Ground truth unavailable'
        elif key == 'mean_fps' and not realtime:
            status, reason = 'NOT_TESTED', 'Unpaced generation; playback FPS is not processing FPS'
        elif key == 'reacq_time_s' and summary.get('reacq_unrecovered', 0):
            status, reason = 'FAIL', 'At least one loss was not recovered'
        elif value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
            status = 'NOT_TESTED'
            reason = 'No recovery event observed' if key == 'reacq_time_s' else 'No valid measurement'
        else:
            status = 'PASS' if (value < limit if op == '<' else value <= limit if op == '<=' else value >= limit) else 'FAIL'
        rows.append(dict(key=key, label=label, value=value, limit=limit, unit=unit, operator=op, status=status, reason=reason))
    statuses = [r['status'] for r in rows]
    overall = ('NOT_SCORED' if summary.get('not_scored') else 'FAIL' if 'FAIL' in statuses
               else 'INCOMPLETE' if any(s != 'PASS' for s in statuses) else 'PASS')
    return dict(overall=overall, provenance='Reference: supplied 26169.pdf, Performance Specifications. Tracking-error aggregation uses the application mean; the statement does not specify an aggregation rule.',
                policy='Every check must be measured and pass for overall PASS. Untested recovery remains incomplete.', rows=rows)
