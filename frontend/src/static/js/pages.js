/* FSOC-PAT — page navigation and mission builder state. */

class PageManager {
  constructor() {
    this.currentPage = 'splash';
    this.missionConfig = {
      motion: 'Straight',
      speed: 'Normal',
      position: 'Near Camera View',
      atmosphere: 'clear',
      disturbances: [],
      disturbanceIntensity: 0.3,
      tracking: 'Hybrid'
    };
  }

  showPage(pageId) {
    if(typeof CameraLabUI!=='undefined' && CameraLabUI.active && pageId!=='cameralab') { CameraLabUI.exit(); return; }
    if (typeof app !== 'undefined') {
      if (pageId !== 'control' && app.recorder) app.recorder.stop();
      if (pageId !== 'cameralab' && app.labCamera) { app.labCamera.stop(); app.labCamera = null; }
      if (pageId !== 'control' && app.camera) { app.camera.stop(); app.camera = null; }
    }
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const target = document.getElementById(`page-${pageId}`);
    if (target) target.classList.add('active');
    this.currentPage = pageId;
    if(pageId === 'splash' && window.refreshHome) window.refreshHome();

    const homeBtn = document.getElementById('nav-home-btn');
    if (homeBtn) homeBtn.style.display = ['splash', 'control'].includes(pageId) ? 'none' : 'block';
  }

  setMotion(motion) { this.missionConfig.motion = motion; }
  setSpeed(speed) { this.missionConfig.speed = speed; }
  setPosition(position) { this.missionConfig.position = position; }
  setAtmosphere(atm) { this.missionConfig.atmosphere = atm; }
  setTracking(mode) { this.missionConfig.tracking = mode; }
  setDisturbanceIntensity(v) { this.missionConfig.disturbanceIntensity = v; }

  toggleDisturbance(type) {
    const idx = this.missionConfig.disturbances.indexOf(type);
    if (idx >= 0) this.missionConfig.disturbances.splice(idx, 1);
    else this.missionConfig.disturbances.push(type);
  }

  speedToPxS(speed) {
    return { Slow: 15, Normal: 30, Fast: 55 }[speed] || 30;
  }

  buildMissionSummary() {
    const c = this.missionConfig;
    const dist = c.disturbances.length ? c.disturbances.join(', ') : 'none';
    return `${c.motion} motion · ${c.speed} speed · ${c.atmosphere} atmosphere · ${dist} disturbances · ${c.tracking} tracking`;
  }

  atmosphereLabel(mode) {
    return { clear: 'Clear', haze: 'Haze', fog: 'Fog', rain: 'Rain', low_light: 'Low Light' }[mode] || mode;
  }
}
