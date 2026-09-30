"""
evaluation/report_generator.py — FSOC-PAT Simulator (SIH 2025, PS 26169, ISRO)

Generates a professional PDF performance-certification report from a
completed MetricsAccumulator, using reportlab only (no matplotlib).
Page 1 holds the pass/fail certification and metrics tables; page 2
holds the tracking-error time-series chart and a system-info footer.
"""
import math
import os
import sys
import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
)
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.widgets.markers import makeMarker


NAVY = colors.HexColor('#0a1628')
GREEN = colors.HexColor('#1a7a4a')
RED = colors.HexColor('#8b1a1a')
WHITE = colors.white

MAX_GRAPH_POINTS = 500


class ReportGenerator:
    """Builds a PDF performance report for a completed session."""

    def __init__(self, output_dir: str = "logs"):
        """
        Args:
            output_dir: folder to write the PDF to (created if missing).
        """
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self._styles = getSampleStyleSheet()

    def generate(self, metrics, csv_path: str = None) -> str:
        """Build and save the PDF report for `metrics` (a
        MetricsAccumulator). Returns the output path, or None on
        failure."""
        from evaluation.report_layout import generate_session_pdf
        return generate_session_pdf(metrics, self.output_dir)

    def _legacy_generate(self, metrics, csv_path=None):
        summary = metrics.compute_summary()
        frame_data = metrics.get_frame_data()
        session_id = summary['session_id']
        pdf_path = os.path.join(self.output_dir, f"{session_id}_report.pdf")

        try:
            doc = SimpleDocTemplate(
                pdf_path, pagesize=letter,
                topMargin=0.4 * inch, bottomMargin=0.5 * inch,
                leftMargin=0.5 * inch, rightMargin=0.5 * inch,
            )
            story = []
            story += self._build_header(summary)
            clog = getattr(metrics, 'centroid_log_path', None)
            if clog:
                ap = os.path.abspath(clog).replace(os.sep, '/')
                story.append(Spacer(1, 0.08 * inch))
                story.append(Paragraph(
                    f'Per-frame centroid log (sub-pixel estimate, native image '
                    f'coordinates{", with GT error" if summary.get("scored_with_gt") else ""}): '
                    f'<link href="file:///{ap}" color="blue"><u>{os.path.basename(os.path.dirname(clog))}/centroid_log.csv</u></link>',
                    self._styles['Normal']))
            story.append(Spacer(1, 0.25 * inch))
            story += self._build_certification_table(summary)
            story.append(Spacer(1, 0.3 * inch))
            story += self._build_metrics_table(summary)
            story.append(PageBreak())
            story += self._build_chart(frame_data, summary)
            story.append(Spacer(1, 0.3 * inch))
            story += self._build_footer()

            doc.build(story)
        except Exception as e:
            print(f"[Report] Error generating PDF: {e}")
            return None

        metrics.report_path = pdf_path
        print(f"[Report] Saved: {pdf_path}")
        return pdf_path

    def _build_header(self, summary: dict) -> list:
        """Build the title/subtitle/session-info header block."""
        title_style = ParagraphStyle(
            'ReportTitle', parent=self._styles['Title'],
            textColor=WHITE, backColor=NAVY, alignment=1,
            fontSize=18, leading=24, spaceAfter=0, spaceBefore=0,
        )
        subtitle_style = ParagraphStyle(
            'ReportSubtitle', parent=self._styles['Normal'],
            textColor=WHITE, backColor=NAVY, alignment=1,
            fontSize=10, leading=14,
        )
        info_style = ParagraphStyle(
            'ReportInfo', parent=self._styles['Normal'],
            textColor=WHITE, backColor=NAVY, alignment=1,
            fontSize=9, leading=12,
        )

        mode_label = 'Video' if summary['mode'] == 'video' else 'Simulation'
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        header_table = Table(
            [[Paragraph('FSOC-PAT Simulator — Performance Report', title_style)],
             [Paragraph('PS 26169 &middot; ISRO / Department of Space &middot; SIH 2025', subtitle_style)],
             [Paragraph(f"Session: {summary['session_id']} &nbsp;|&nbsp; "
                        f"Mode: {mode_label} &nbsp;|&nbsp; "
                        f"Tracking mode: {summary.get('detector_mode', 'Hybrid')} &nbsp;|&nbsp; "
                        f"Generated: {now_str}",
                        info_style)]],
            colWidths=[7.0 * inch],
        )
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), NAVY),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        return [header_table]

    def _build_certification_table(self, summary: dict) -> list:
        """Build the 5-row pass/fail certification table plus overall
        result row."""
        def fmt_pass(p):
            return None if p is None else ('PASS' if p else 'FAIL')

        acq = summary['acquisition_time_s']
        err = summary['mean_track_error_px']
        loss = summary['target_loss_pct']
        reacq = summary['reacq_time_s']
        fps = summary['mean_fps']

        not_scored = bool(summary.get('not_scored'))
        measured = []
        if acq is not None:
            measured.append(f'acquisition {acq:.2f} s')
        if fps is not None:
            measured.append(f'processing {fps:.1f} FPS')
        if summary.get('lock_rate_pct') is not None:
            measured.append(f"lock rate {float(summary['lock_rate_pct']):.1f}% (tracker estimate)")
        no_gt_err = 'Not measured (no ground truth)'
        rows = [
            ['Requirement', 'Required', 'Achieved', 'Result'],
            ['Acquisition Time', '≤ 2.0 s',
             f"{acq:.2f}s" if acq is not None else 'N/A',
             fmt_pass(summary['pass_acq_time'])],
            [('Centroid Error vs GT' if summary.get('mode') == 'video'
              else 'Tracking Error'), '≤ 10 px',
             f"{err:.2f} px" if err is not None
             else (no_gt_err if not_scored else 'N/A'),
             fmt_pass(summary['pass_track_error'])],
            ['Target Loss', '< 5%',
             f"{loss:.2f}%" if loss is not None
             else (no_gt_err if not_scored else 'N/A'),
             fmt_pass(summary['pass_target_loss'])],
            ['Re-acquisition Time', '≤ 1.0 s',
             f"{reacq:.2f}s" if reacq is not None
             else (no_gt_err if not_scored else 'N/A'),
             fmt_pass(summary['pass_reacq_time'])],
            ['Processing Speed', '≥ 20 FPS', f"{fps:.1f} FPS" if fps is not None else 'N/A',
             fmt_pass(summary['pass_fps'])],
            ['OVERALL RESULT', '', '',
             (Paragraph('NOT SCORED (no ground truth) — measured: '
                        + (', '.join(measured) or 'nothing'),
                        ParagraphStyle('NotScored', parent=self._styles['Normal'],
                                       textColor=WHITE, fontSize=7, leading=8,
                                       fontName='Helvetica-Bold'))
              if not_scored else
              'PASS' if summary['overall_pass'] else 'FAIL')],
        ]
        # A requirement with nothing measured is N/A (grey) — never PASS.
        for row in rows[1:-1]:
            if row[2] == 'N/A' or row[2] == no_gt_err or row[3] is None:
                row[3] = 'N/A'

        table = Table(rows, colWidths=[2.0 * inch, 1.5 * inch,
                                        1.8 * inch, 1.2 * inch])
        style = [
            ('BACKGROUND', (0, 0), (-1, 0), NAVY),
            ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('SPAN', (0, -1), (2, -1)),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ]
        for i, row in enumerate(rows[1:-1], start=1):
            result = row[3]
            bg = (GREEN if result == 'PASS' else
                  colors.grey if result == 'N/A' else RED)
            style.append(('BACKGROUND', (3, i), (3, i), bg))
            style.append(('TEXTCOLOR', (3, i), (3, i), WHITE))

        overall_bg = (colors.grey if not_scored else
                      GREEN if summary['overall_pass'] else RED)
        style.append(('BACKGROUND', (0, -1), (-1, -1), overall_bg))
        style.append(('TEXTCOLOR', (0, -1), (-1, -1), WHITE))

        table.setStyle(TableStyle(style))
        return [Paragraph('PS Requirement Certification', self._styles['Heading2']),
                table]

    def _build_metrics_table(self, summary: dict) -> list:
        """Build the general performance-metrics table."""
        centroid = summary['centroid_rmse_px']
        max_err = summary['max_track_error_px']
        rmse = summary['rmse_px']

        rows = [
            ['Metric', 'Value'],
            ['Total Frames', f"{summary['total_frames']}"],
            ['Session Duration', f"{summary['duration_sec']:.1f}s"],
            ['Mean FPS', f"{summary['mean_fps']:.1f}"],
            (['Correct lock (vs ground truth)',
              f"{summary['correct_lock_pct']:.1f}%"]
             if summary.get('scored_with_gt') and summary.get('correct_lock_pct') is not None
             else ["Lock rate (tracker's own state)",
                   f"{summary['lock_rate_pct']:.1f}%"]),
            ['Beacon out of camera view %',
             f"{summary['beacon_out_of_fov_pct']:.1f}%"
                if summary.get('beacon_out_of_fov_pct') is not None else 'N/A'],
        ]
        if summary.get('mode') != 'video':
            rows += [
                ['Mean Track Error', f"{summary['mean_track_error_px']:.2f} px"
                    if summary['mean_track_error_px'] is not None else 'N/A'],
                ['Max Track Error', f"{max_err:.1f} px" if max_err is not None else 'N/A'],
                ['Raw image error (includes camera jitter)',
                 f"{summary['raw_sensor_err_mean_px']:.2f} px"
                    if summary.get('raw_sensor_err_mean_px') is not None else 'N/A'],
                ['Pull-in Time (mean / max)',
                 f"{summary['pull_in_mean_s']:.2f} s / {summary['pull_in_max_s']:.2f} s"
                    if summary.get('pull_in_mean_s') is not None else 'N/A'],
                ['RMSE', f"{rmse:.2f} px" if rmse is not None else 'N/A'],
            ]
        if summary.get('mode') != 'video' or summary.get('scored_with_gt'):
            rows.append(['Centroid RMSE',
                         f"{centroid:.2f} px" if centroid is not None else 'N/A'])
        if summary.get('scored_with_gt'):
            def pct(k):
                v = summary.get(k)
                return f"{v:.1f}%" if v is not None else 'N/A'
            cm, cx = summary.get('centroid_err_mean_px'), summary.get('centroid_err_max_px')
            rows += [
                ['Centroid Error vs GT (mean / max)',
                 f"{cm:.2f} px / {cx:.1f} px" if cm is not None else 'N/A'],
                ['Correct Lock (of frames with beacon visible)',
                 pct('correct_lock_visible_pct')],
                ['Lock Retention (after first lock)', pct('lock_retention_pct')],
                ['Wrong-lock Events', f"{summary.get('wrong_lock_events', 0)}"],
            ]
        if summary.get('processing_fps') is not None:
            rows.append(['Processing FPS (pipeline only)',
                         f"{summary['processing_fps']:.1f}"])
        table = Table(rows, colWidths=[3.0 * inch, 2.0 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), NAVY),
            ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.whitesmoke]),
        ]))
        return [Paragraph('Performance Metrics', self._styles['Heading2']), table]

    def _build_chart(self, frame_data: list, summary: dict = None) -> list:
        """Build the tracking-error-vs-time line chart for LOCKED
        frames, subsampled to at most MAX_GRAPH_POINTS points. Video mode
        plots the centroid error vs ground truth instead (distance from the
        picture centre means nothing for a fixed camera), or nothing when
        no ground truth was loaded."""
        summary = summary or {}
        video = summary.get('mode') == 'video'
        elements = [Paragraph('Tracking Performance', self._styles['Heading2'])]
        if video and not summary.get('scored_with_gt'):
            elements.append(Paragraph(
                'No error chart — no ground truth loaded with this video.',
                self._styles['Normal']))
            return elements
        if video:
            points = [(row.get('sim_time') or row['timestamp_s'],
                       math.hypot(row['tracker_x'] - row['gt_x'],
                                  row['tracker_y'] - row['gt_y']))
                      for row in frame_data
                      if row['state'] == 'LOCKED' and None not in (
                          row['tracker_x'], row['tracker_y'],
                          row['gt_x'], row['gt_y'])]
        else:
            points = [(row['timestamp_s'], row['track_error_px'])
                      for row in frame_data
                      if row['state'] == 'LOCKED' and row['track_error_px'] is not None]

        if not points:
            elements.append(Paragraph('No LOCKED frames recorded — no chart available.',
                                       self._styles['Normal']))
            return elements

        if len(points) > MAX_GRAPH_POINTS:
            step = max(1, len(points) // MAX_GRAPH_POINTS)
            points = points[::step]

        drawing = Drawing(500, 250)
        chart = LinePlot()
        chart.x = 50
        chart.y = 30
        chart.height = 180
        chart.width = 420
        chart.data = [points]
        chart.lines[0].strokeColor = colors.HexColor('#1f6fd6')
        chart.lines[0].strokeWidth = 1.2

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x_min, x_max = min(xs), max(xs)
        y_max = max(10.0, max(ys)) * 1.1

        chart.xValueAxis.valueMin = x_min
        chart.xValueAxis.valueMax = x_max if x_max > x_min else x_min + 1
        chart.yValueAxis.valueMin = 0
        chart.yValueAxis.valueMax = y_max

        drawing.add(chart)

        # 10px spec-limit reference line, drawn in the chart's local
        # coordinate space (chart.x/y offset within the drawing).
        limit_frac = min(1.0, 10.0 / y_max)
        y_pixel = chart.y + limit_frac * chart.height
        drawing.add(Line(chart.x, y_pixel, chart.x + chart.width, y_pixel,
                          strokeColor=colors.red, strokeDashArray=[4, 3]))
        drawing.add(String(chart.x + chart.width - 90, y_pixel + 4,
                            '10px spec limit', fontSize=8, fillColor=colors.red))

        elements.append(drawing)
        elements.append(Paragraph(
            ('Centroid Error vs GT (px) vs Time — LOCKED frames only' if video
             else 'Tracking Error (px) vs Time — LOCKED frames only'),
            self._styles['Italic']))
        return elements

    def _build_footer(self) -> list:
        """Build the system-information footer (Python/torch/opencv
        versions and report generation timestamp)."""
        py_ver = sys.version.split()[0]
        try:
            import torch
            torch_ver = torch.__version__
        except Exception:
            torch_ver = 'N/A'
        try:
            import cv2
            cv2_ver = cv2.__version__
        except Exception:
            cv2_ver = 'N/A'

        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        footer_style = ParagraphStyle(
            'Footer', parent=self._styles['Normal'],
            textColor=colors.grey, fontSize=8,
        )
        text = (f"Python {py_ver} &nbsp;|&nbsp; torch {torch_ver} "
                f"&nbsp;|&nbsp; opencv-python {cv2_ver} "
                f"&nbsp;|&nbsp; Report generated {now_str}")
        return [Paragraph(text, footer_style)]
