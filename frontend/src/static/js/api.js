/* FSOC-PAT — all backend API calls live here. No fetch() anywhere else. */

const API = {
  BASE: location.protocol.startsWith('http') ? location.origin : 'http://127.0.0.1:8765',

  async request(path, options = {}) {
    const response = await fetch(this.BASE + path, options);
    if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.detail || `Request failed (${response.status})`); }
    return response.json();
  },
  post(path, data) { return this.request(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)}); },

  async getDiagnostics(route) {
    const response = await fetch(`${this.BASE}/api/${route}`);
    if (!response.ok) throw new Error('Diagnostics unavailable');
    return response.json();
  },

  async getState() {
    return fetch(`${this.BASE}/api/state`).then(r => r.json());
  },

  async command(cmd) {
    return this.post('/api/command',{cmd});
  },

  async setMotion(motion) {
    return fetch(`${this.BASE}/api/set_motion`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ motion })
    }).then(r => r.json());
  },

  async setAtmosphere(mode) {
    return fetch(`${this.BASE}/api/set_atmosphere`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode })
    }).then(r => r.json());
  },

  async setToggle(name, on) {
    return fetch(`${this.BASE}/api/set_toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, on })
    }).then(r => r.json());
  },

  async setDisturbance(type, value) {
    return fetch(`${this.BASE}/api/set_disturbance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, value })
    }).then(r => r.json());
  },

  async setDetector(mode) {
    return fetch(`${this.BASE}/api/set_detector`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode })
    }).then(r => r.json());
  },

  async setMode(mode) {
    return fetch(`${this.BASE}/api/set_mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode })
    }).then(r => r.json());
  },

  async setScenario(preset) {
    return fetch(`${this.BASE}/api/set_scenario`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset })
    }).then(r => r.json());
  },

  async getLogs() {
    return fetch(`${this.BASE}/api/logs`).then(r => r.json());
  },

  async getLogContent(filename) {
    return fetch(this.logFileURL(filename)).then(r => r.text());
  },

  async loadVideo(file, gtFile) {
    const formData = new FormData();
    formData.append('file', file);
    if (gtFile) formData.append('gt', gtFile);
    return fetch(`${this.BASE}/api/load_video`, {
      method: 'POST',
      body: formData
    }).then(r => r.json());
  },

  logFileURL(filename) {
    return `${this.BASE}/api/logs/${encodeURIComponent(filename)}`;
  },

  // Retain ownership of reconnects so an intentional close cannot leak streams.
  _connectWS(path, onMessage) {
    let socket, retry, closed = false;
    const connect = () => {
      if (closed) return;
      socket = new WebSocket(`${this.BASE.replace(/^http/, 'ws')}${path}`);
      socket.onmessage = e => { if (!closed) onMessage(JSON.parse(e.data)); };
      socket.onclose = () => { if (!closed) retry = setTimeout(connect, 1000); };
    };
    connect();
    return { close() { closed = true; clearTimeout(retry); if (socket) { socket.onclose = null; socket.close(); } } };
  },
  connectFrameWS(onFrame) {
    return this._connectWS('/ws/frame', data => { if (data.frame) onFrame(data.frame,data.telemetry); });
  },
  connectStateWS(onState) { return this._connectWS('/ws/state', onState); }
};
