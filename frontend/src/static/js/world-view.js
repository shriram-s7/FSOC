/* FSOC-PAT — top-down world view canvas with an auto-zooming viewport
   that follows the beacon/camera instead of showing the full 2000x2000
   world (where the active region near (1000,1000) is a tiny corner).

   Coordinate space: cam_x/cam_y and target_wx/target_wy from /api/state
   (and the /ws/state stream) are WORLD-space coordinates in the 0-2000
   range, confirmed via temporary debug logging in server/app.py's
   serialize_state() (see task history) — no conversion needed. */

class WorldView {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');

    // Dynamic viewport bounds (world coordinates).
    // Start with a 1000x1000 world-unit view centered on (1000,1000) so
    // the 640x480-world-unit camera rectangle reads as roughly 64% of
    // the view width — a proportional box, not something that fills
    // (or dwarfs) the whole canvas.
    this.viewMinX = 500;
    this.viewMinY = 500;
    this.viewMaxX = 1500;
    this.viewMaxY = 1500;

    this.PADDING = 400; // world units of padding around active objects
    this.SMOOTH = 0.05; // viewport smoothing (lower = smoother but slower)

    // Target viewport (smooth interpolation toward this)
    this.targetMinX = 500;
    this.targetMinY = 500;
    this.targetMaxX = 1500;
    this.targetMaxY = 1500;

    this.beaconTrail = [];
    this.MAX_TRAIL = 300;

    this._lastArrowAngle = null;

    // Camera position history (world coords + timestamp) used to derive
    // the CAM arrow's direction from the camera's actual motion, rather
    // than the camera->beacon vector (which is only 1-2px long and noisy
    // once LOCKED, making the old arrow's angle spin randomly).
    this.camHistory = [];
    this.CAM_HISTORY_LEN = 10;
    this.CAM_STILL_SPEED = 5; // world px/s below this: camera holding still
  }

  // Convert world coordinates to canvas pixel coordinates
  toCanvas(wx, wy) {
    const viewW = this.viewMaxX - this.viewMinX;
    const viewH = this.viewMaxY - this.viewMinY;
    const scaleX = this.canvas.width / viewW;
    const scaleY = this.canvas.height / viewH;
    const scale = Math.min(scaleX, scaleY);

    const offsetX = (this.canvas.width - viewW * scale) / 2;
    const offsetY = (this.canvas.height - viewH * scale) / 2;

    return {
      x: offsetX + (wx - this.viewMinX) * scale,
      y: offsetY + (wy - this.viewMinY) * scale,
      scale: scale
    };
  }

  updateViewport(state) {
    const bx = state.target_wx;
    const by = state.target_wy;
    const cx = state.cam_x;
    const cy = state.cam_y;

    if (bx == null || cy == null) return;

    // Compute bounding box of beacon + camera with padding
    const allX = [bx, cx];
    const allY = [by, cy];

    let minX = Math.min(...allX) - this.PADDING;
    let minY = Math.min(...allY) - this.PADDING;
    let maxX = Math.max(...allX) + this.PADDING;
    let maxY = Math.max(...allY) + this.PADDING;

    // Pull the world edge (0..2000) into view whenever the beacon or the
    // camera box is within PADDING of it, so an edge bounce / the camera
    // box going past the world boundary is actually visible.
    if (bx <= this.PADDING || cx <= this.PADDING) minX = Math.min(minX, -20);
    if (by <= this.PADDING || cy <= this.PADDING) minY = Math.min(minY, -20);
    if (bx >= 2000 - this.PADDING || cx >= 2000 - this.PADDING) maxX = Math.max(maxX, 2020);
    if (by >= 2000 - this.PADDING || cy >= 2000 - this.PADDING) maxY = Math.max(maxY, 2020);

    // Ensure minimum view size (800x800 world units, i.e. half-size 400 —
    // matches PADDING so the camera rectangle never looks like an
    // oversized frame filling the whole canvas)
    const midX = (minX + maxX) / 2;
    const midY = (minY + maxY) / 2;
    const halfW = Math.max((maxX - minX) / 2, 400);
    const halfH = Math.max((maxY - minY) / 2, 400);

    this.targetMinX = midX - halfW;
    this.targetMinY = midY - halfH;
    this.targetMaxX = midX + halfW;
    this.targetMaxY = midY + halfH;

    // Smooth interpolation toward target viewport
    this.viewMinX += (this.targetMinX - this.viewMinX) * this.SMOOTH;
    this.viewMinY += (this.targetMinY - this.viewMinY) * this.SMOOTH;
    this.viewMaxX += (this.targetMaxX - this.viewMaxX) * this.SMOOTH;
    this.viewMaxY += (this.targetMaxY - this.viewMaxY) * this.SMOOTH;
  }

  draw(state) {
    if ([state.target_wx,state.target_wy,state.cam_x,state.cam_y].some(v => v == null)) return;
    const ctx = this.ctx;

    // Keep the backing bitmap matched to the rendered size so the view stays
    // crisp whether it's the small docked panel or the full toggled-to view.
    const displayW = this.canvas.clientWidth;
    const displayH = this.canvas.clientHeight;
    if (displayW > 0 && displayH > 0 &&
        (this.canvas.width !== displayW || this.canvas.height !== displayH)) {
      this.canvas.width = displayW;
      this.canvas.height = displayH;
    }

    const W = this.canvas.width;
    const H = this.canvas.height;

    // Update auto-zoom viewport
    this.updateViewport(state);

    // Background
    ctx.fillStyle = '#040810';
    ctx.fillRect(0, 0, W, H);

    // Grid lines (in world space, every 100 units)
    ctx.strokeStyle = 'rgba(30,58,95,0.35)';
    ctx.lineWidth = 0.5;
    const gridStep = 100; // world units
    const startX = Math.floor(this.viewMinX / gridStep) * gridStep;
    const startY = Math.floor(this.viewMinY / gridStep) * gridStep;

    for (let wx = startX; wx <= this.viewMaxX; wx += gridStep) {
      const p1 = this.toCanvas(wx, this.viewMinY);
      const p2 = this.toCanvas(wx, this.viewMaxY);
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.stroke();
    }
    for (let wy = startY; wy <= this.viewMaxY; wy += gridStep) {
      const p1 = this.toCanvas(this.viewMinX, wy);
      const p2 = this.toCanvas(this.viewMaxX, wy);
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.stroke();
    }

    // World boundary rectangle (2000x2000) — always drawn as a clear
    // solid line (not faint dashes) so the beacon bouncing off it, and
    // the camera box going past it, are both plainly visible.
    const worldTL = this.toCanvas(0, 0);
    const worldBR = this.toCanvas(2000, 2000);
    ctx.strokeStyle = 'rgba(120,170,220,0.85)';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(worldTL.x, worldTL.y,
                    worldBR.x - worldTL.x, worldBR.y - worldTL.y);

    ctx.fillStyle = 'rgba(160,200,240,0.9)';
    ctx.font = '9px monospace';
    ctx.fillText('(0,0)', worldTL.x + 2, worldTL.y + 10);
    ctx.fillText('(2000,2000)', worldBR.x - 66, worldBR.y - 4);
    ctx.fillText('world edge', worldTL.x + 2, worldTL.y - 3);

    const bx = state.target_wx ?? 1000;
    const by = state.target_wy ?? 1000;
    const cx = state.cam_x ?? 1000;
    const cy = state.cam_y ?? 1000;

    // Update beacon trail
    this.beaconTrail.push({ x: bx, y: by });
    if (this.beaconTrail.length > this.MAX_TRAIL) {
      this.beaconTrail.shift();
    }

    // Draw beacon trail
    if (this.beaconTrail.length > 1) {
      ctx.strokeStyle = 'rgba(255,68,68,0.25)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      const first = this.toCanvas(this.beaconTrail[0].x, this.beaconTrail[0].y);
      ctx.moveTo(first.x, first.y);
      for (let i = 1; i < this.beaconTrail.length; i++) {
        const p = this.toCanvas(this.beaconTrail[i].x, this.beaconTrail[i].y);
        ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Draw camera viewport rectangle (640x480 in world space)
    // Camera viewport in world: cx±320, cy±240 (half of 640x480)
    const halfW=(state.camera_config?.width||640)/2,halfH=(state.camera_config?.height||480)/2;
    const camLeft = cx - halfW;
    const camTop = cy - halfH;
    const camRight = cx + halfW;
    const camBottom = cy + halfH;

    const tl2 = this.toCanvas(camLeft, camTop);
    const br2 = this.toCanvas(camRight, camBottom);

    ctx.fillStyle = 'rgba(0,212,255,0.04)';
    ctx.fillRect(tl2.x, tl2.y, br2.x - tl2.x, br2.y - tl2.y);
    ctx.strokeStyle = '#00d4ff';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(tl2.x, tl2.y, br2.x - tl2.x, br2.y - tl2.y);

    // "CAM FOV" label at the top-left corner of the camera rectangle
    ctx.fillStyle = '#00d4ff';
    ctx.font = '9px monospace';
    ctx.fillText('CAM FOV', tl2.x + 3, tl2.y + 10);

    const cp = this.toCanvas(cx, cy);
    const trackState = state.track_state || 'SEARCHING';

    // When LOCKED, show where in the world the tracker thinks the beacon
    // is: convert the tracked camera-frame pixel back to world space and
    // draw a small dot there.
    if (trackState === 'LOCKED' &&
        state.tracker_x != null && state.tracker_y != null) {
      const trackedWorldX = cx + (state.tracker_x - 320);
      const trackedWorldY = cy + (state.tracker_y - 240);
      const tp = this.toCanvas(trackedWorldX, trackedWorldY);
      ctx.fillStyle = '#00d4ff';
      ctx.beginPath();
      ctx.arc(tp.x, tp.y, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    // Draw beacon with glow
    const bp = this.toCanvas(bx, by);
    ctx.shadowBlur = 16;
    ctx.shadowColor = '#ff4444';
    ctx.fillStyle = '#ff4444';
    ctx.beginPath();
    ctx.arc(bp.x, bp.y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    // Beacon label
    ctx.fillStyle = 'rgba(255,68,68,0.8)';
    ctx.font = '9px monospace';
    ctx.fillText('BEACON', bp.x + 7, bp.y - 7);

    // Unmistakable in/out-of-frame indicator — checked against the CAM FOV
    // rectangle's actual world bounds, independent of track state, so it
    // still fires during COASTING/SEARCHING/LOST (e.g. right after a
    // tracker reset), not only while LOCKED.
    const beaconInFrame = (bx >= camLeft && bx <= camRight &&
                            by >= camTop && by <= camBottom);
    if (beaconInFrame) {
      ctx.strokeStyle = 'rgba(0,255,136,0.6)';
      ctx.lineWidth = 1;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(cp.x, cp.y);
      ctx.lineTo(bp.x, bp.y);
      ctx.stroke();
    } else {
      ctx.strokeStyle = 'rgba(255,136,0,0.85)';
      ctx.lineWidth = 3;
      ctx.setLineDash([6, 5]);
      ctx.beginPath();
      ctx.moveTo(cp.x, cp.y);
      ctx.lineTo(bp.x, bp.y);
      ctx.stroke();
      ctx.setLineDash([]);

      const midX = (cp.x + bp.x) / 2;
      const midY = (cp.y + bp.y) / 2;
      ctx.fillStyle = 'rgba(255,136,0,0.95)';
      ctx.font = 'bold 10px monospace';
      ctx.fillText('BEACON OUT OF FRAME', midX - 62, midY - 6);
    }

    // Camera glyph — shows the direction the CAMERA IS ACTUALLY MOVING,
    // derived from its own recent position history rather than the
    // camera->beacon vector: once LOCKED that vector is only 1-2px of
    // detection noise and its angle spins randomly, which isn't a
    // meaningful "aim" direction. Track the last CAM_HISTORY_LEN
    // (cam_x, cam_y, timestamp) samples and use the average velocity
    // between the oldest and newest to get a stable heading. Below
    // CAM_STILL_SPEED (world px/s) the camera reads as holding still,
    // so draw a dot instead of a spinning/noisy arrow.
    this.camHistory.push({ x: cx, y: cy, t: performance.now() });
    if (this.camHistory.length > this.CAM_HISTORY_LEN) {
      this.camHistory.shift();
    }

    let camSpeed = 0, dirX = 0, dirY = 1;
    if (this.camHistory.length >= 2) {
      const oldest = this.camHistory[0];
      const newest = this.camHistory[this.camHistory.length - 1];
      const dtSec = (newest.t - oldest.t) / 1000;
      if (dtSec > 1e-3) {
        const vx = (newest.x - oldest.x) / dtSec;
        const vy = (newest.y - oldest.y) / dtSec;
        camSpeed = Math.hypot(vx, vy);
        if (camSpeed > 1e-3) { dirX = vx; dirY = vy; }
      }
    }

    if (camSpeed < this.CAM_STILL_SPEED) {
      // Camera holding still — solid dot instead of a direction arrow.
      ctx.fillStyle = '#00d4ff';
      ctx.beginPath();
      ctx.arc(cp.x, cp.y, 4, 0, Math.PI * 2);
      ctx.fill();
    } else {
      this._lastArrowAngle = Math.atan2(dirY, dirX);
      const angle = this._lastArrowAngle;

      const ux = Math.cos(angle), uy = Math.sin(angle);
      const tailX = cp.x - 5 * ux, tailY = cp.y - 5 * uy;
      const tipX  = cp.x + 9 * ux, tipY  = cp.y + 9 * uy;
      const wingBackX = tipX - 5 * ux, wingBackY = tipY - 5 * uy;
      const perpX = -uy, perpY = ux;

      ctx.strokeStyle = '#00d4ff';
      ctx.fillStyle = '#00d4ff';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(tailX, tailY);
      ctx.lineTo(tipX, tipY);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(tipX, tipY);
      ctx.lineTo(wingBackX + 3 * perpX, wingBackY + 3 * perpY);
      ctx.lineTo(wingBackX - 3 * perpX, wingBackY - 3 * perpY);
      ctx.closePath();
      ctx.fill();
    }

    ctx.fillStyle = 'rgba(0,212,255,0.85)';
    ctx.font = '9px monospace';
    ctx.fillText('CAM (camera moving)', cp.x + 10, cp.y + 14);

    // Scale indicator bottom-right
    // Show what 100 world units = X canvas pixels
    const p1 = this.toCanvas(0, 0);
    const p2 = this.toCanvas(100, 0);
    const scaleBarPx = Math.abs(p2.x - p1.x);

    ctx.fillStyle = '#b2c9dc';
    ctx.font = '9px monospace';
    ctx.fillText(`100u = ${scaleBarPx.toFixed(0)}px`, W - 100, H - 8);

    // Current coordinates
    ctx.fillStyle = '#b2c9dc';
    ctx.fillText(`B:(${Math.round(bx)},${Math.round(by)})`, 6, H - 16);
    ctx.fillText(`C:(${Math.round(cx)},${Math.round(cy)})`, 6, H - 6);
  }

  reset() {
    this.viewMinX = 500;
    this.viewMinY = 500;
    this.viewMaxX = 1500;
    this.viewMaxY = 1500;
    this.targetMinX = 500;
    this.targetMinY = 500;
    this.targetMaxX = 1500;
    this.targetMaxY = 1500;
    this.beaconTrail = [];
    this._lastArrowAngle = null;
    this.camHistory = [];
  }

  drawMinimap(canvas, state) {
    if (!canvas || !state) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;

    ctx.fillStyle = '#060d18';
    ctx.fillRect(0, 0, W, H);

    // Grid
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.08)';
    ctx.lineWidth = 1;
    for (let x = 0; x < W; x += 25) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let y = 0; y < H; y += 25) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }

    const bx = state.target_wx != null ? state.target_wx : 1000;
    const by = state.target_wy != null ? state.target_wy : 1000;
    const cx = state.cam_x != null ? state.cam_x : 1000;
    const cy = state.cam_y != null ? state.cam_y : 1000;

    // View bounds centered at camera
    const viewW = 1200;
    const viewH = 900;
    const minX = cx - viewW / 2;
    const minY = cy - viewH / 2;
    const toMini = (wx, wy) => ({
      x: ((wx - minX) / viewW) * W,
      y: ((wy - minY) / viewH) * H
    });

    // World border indication
    const wtl = toMini(0, 0);
    const wbr = toMini(2000, 2000);
    ctx.strokeStyle = 'rgba(120, 170, 220, 0.3)';
    ctx.lineWidth = 1;
    ctx.strokeRect(wtl.x, wtl.y, wbr.x - wtl.x, wbr.y - wtl.y);

    // Camera FOV box (640x480 in world space)
    const halfW=(state.camera_config?.width||640)/2,halfH=(state.camera_config?.height||480)/2;
    const tl = toMini(cx - halfW, cy - halfH);
    const br = toMini(cx + halfW, cy + halfH);
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.75)';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(tl.x, tl.y, br.x - tl.x, br.y - tl.y);
    ctx.fillStyle = 'rgba(0, 240, 255, 0.08)';
    ctx.fillRect(tl.x, tl.y, br.x - tl.x, br.y - tl.y);

    // Beacon trajectory
    if (this.beaconTrail && this.beaconTrail.length > 2) {
      ctx.strokeStyle = 'rgba(239, 68, 68, 0.35)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([2, 2]);
      ctx.beginPath();
      const first = toMini(this.beaconTrail[0].x, this.beaconTrail[0].y);
      ctx.moveTo(first.x, first.y);
      const step = Math.max(1, Math.floor(this.beaconTrail.length / 40));
      for (let i = 1; i < this.beaconTrail.length; i += step) {
        const pt = toMini(this.beaconTrail[i].x, this.beaconTrail[i].y);
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Target beacon dot with glow
    const bp = toMini(bx, by);
    ctx.shadowBlur = 8;
    ctx.shadowColor = '#ef4444';
    ctx.fillStyle = '#ef4444';
    ctx.beginPath();
    ctx.arc(bp.x, bp.y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    // Connecting line from camera center to beacon
    const cp = toMini(cx, cy);
    const inFov = (bx >= cx - 320 && bx <= cx + 320 && by >= cy - 240 && by <= cy + 240);
    ctx.strokeStyle = inFov ? 'rgba(0, 230, 153, 0.5)' : 'rgba(245, 158, 11, 0.7)';
    ctx.setLineDash(inFov ? [] : [3, 2]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cp.x, cp.y);
    ctx.lineTo(bp.x, bp.y);
    ctx.stroke();
    ctx.setLineDash([]);

    // Camera center dot
    ctx.fillStyle = '#00f0ff';
    ctx.beginPath();
    ctx.arc(cp.x, cp.y, 2.5, 0, Math.PI * 2);
    ctx.fill();

    // Top-left label
    ctx.fillStyle = 'rgba(148, 163, 184, 0.85)';
    ctx.font = '9px monospace';
    ctx.fillText('MINIMAP', 6, 12);
  }
}
