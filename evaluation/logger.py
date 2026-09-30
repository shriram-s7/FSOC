"""
evaluation/logger.py — FSOC-PAT Simulator (SIH 2025, PS 26169, ISRO)

CSV export for a completed evaluation session. Writes a per-frame log
and a summary log, both derived from a MetricsAccumulator, into the
configured logs directory (see config/default.yaml: logging.output_dir).
"""
import os
import csv
import datetime

from evaluation.centroid_log import write_centroid_log


FRAME_FIELDS = [
    'frame', 'timestamp_s', 'state', 'track_error_px', 'fps',
    'confidence', 'gt_x', 'gt_y', 'tracker_x', 'tracker_y',
    'tracker_stab_x', 'tracker_stab_y', 'sim_time', 'occluded',
]


class SessionLogger:
    """Writes per-frame and summary CSV files for a session."""

    def __init__(self, output_dir: str = "logs"):
        """
        Args:
            output_dir: folder to write CSV files to (created if missing).
        """
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def export_csv(self, metrics) -> str:
        """Write the per-frame and summary CSV files for `metrics`
        (a MetricsAccumulator). Returns the path to the per-frame CSV,
        or None if writing failed."""
        frame_rows = metrics.get_frame_data()
        summary = metrics.compute_summary()
        session_id = summary['session_id']

        frames_path = os.path.join(self.output_dir, f"{session_id}_frames.csv")
        summary_path = os.path.join(self.output_dir, f"{session_id}_summary.csv")

        try:
            with open(frames_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=FRAME_FIELDS,
                                         restval='')
                writer.writeheader()
                for row in frame_rows:
                    clean = {k: ('' if v is None else v) for k, v in row.items()}
                    writer.writerow(clean)
        except IOError as e:
            print(f"[Logger] Error writing frames CSV: {e}")
            return None

        try:
            with open(summary_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['metric', 'value'])
                for key, value in summary.items():
                    writer.writerow([key, str(value).lower() if isinstance(value,bool) and not key.startswith('pass_') and key!='overall_pass' else self._format_value(value)])
        except IOError as e:
            print(f"[Logger] Error writing summary CSV: {e}")
            return None

        try:
            metrics.centroid_log_path = write_centroid_log(
                os.path.join(self.output_dir, session_id, 'centroid_log.csv'),
                metrics.get_centroid_rows())
            print(f"[Logger] Saved: {metrics.centroid_log_path}")
        except IOError as e:
            print(f"[Logger] Error writing centroid log: {e}")

        print(f"[Logger] Saved: {frames_path}")
        return frames_path

    def _format_value(self, value):
        """Format a summary value for the CSV: booleans as PASS/FAIL,
        floats rounded to 3 decimals, None as empty string."""
        if isinstance(value, bool):
            return 'PASS' if value else 'FAIL'
        if isinstance(value, float):
            return round(value, 3)
        if value is None:
            return ''
        return value
