const { app, BrowserWindow, dialog } = require('electron')
const path = require('path')
const fs = require('fs')
const net = require('net')
const http = require('http')
const { spawn, execFile } = require('child_process')

let mainWindow
let pythonProcess
let port = Number(process.env.FSOC_PORT) || 8765

// Packaged builds run the bundled fsoc-server.exe; development runs the venv.
function serverCommand() {
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, 'fsoc-server', 'fsoc-server.exe')
    return { file: exe, args: [], cwd: path.dirname(exe) }
  }
  const root = path.resolve(__dirname, '..')
  return { file: path.join(root, 'venv', 'Scripts', 'python.exe'), args: ['-m', 'server.app'], cwd: root }
}

function dataDir() {
  return process.env.FSOC_DATA_DIR || path.join(process.env.LOCALAPPDATA || app.getPath('userData'), 'FSOC-PAT')
}

// Prefer the usual port, but fall back to any free one so a stray server cannot hijack the UI.
function pickPort(preferred) {
  return new Promise(resolve => {
    const probe = net.createServer()
    probe.once('error', () => {
      const any = net.createServer()
      any.listen(0, '127.0.0.1', () => { const p = any.address().port; any.close(() => resolve(p)) })
    })
    probe.listen(preferred, '127.0.0.1', () => probe.close(() => resolve(preferred)))
  })
}

function startPythonServer() {
  const { file, args, cwd } = serverCommand()
  const env = { ...process.env, FSOC_PORT: String(port) }
  if (app.isPackaged) env.FSOC_DATA_DIR = dataDir()
  const logDir = app.isPackaged ? path.join(dataDir(), 'server-logs') : path.join(cwd, 'scratch', 'ui')
  fs.mkdirSync(logDir, { recursive: true })
  const out = fs.createWriteStream(path.join(logDir, 'server.out.log'))
  const err = fs.createWriteStream(path.join(logDir, 'server.err.log'))
  pythonProcess = spawn(file, args, { cwd, env, stdio: 'pipe', windowsHide: true })
  pythonProcess.stdout.pipe(out)
  pythonProcess.stderr.pipe(err)
  pythonProcess.on('exit', code => {
    pythonProcess = null
    if (mainWindow && !app.isQuitting) {
      dialog.showErrorBox('FSOC-PAT backend stopped',
        `The tracking backend exited (code ${code}). See logs in:\n${logDir}`)
      app.quit()
    }
  })
}

// Kill the whole tree so comparison worker processes do not outlive the app.
function stopPythonServer() {
  if (!pythonProcess) return
  execFile('taskkill', ['/pid', String(pythonProcess.pid), '/T', '/F'], () => {})
  pythonProcess = null
}

function waitForServer(callback, attempts = 0) {
  // First launch can be slow while antivirus scans the bundled runtime.
  if (attempts > 240) { callback(); return }
  http.get(`http://127.0.0.1:${port}/api/state`, res => { res.resume(); callback() })
    .on('error', () => setTimeout(() => waitForServer(callback, attempts + 1), 500))
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1200,
    minHeight: 800,
    frame: true,
    backgroundColor: '#080c14',
    title: 'FSOC-PAT | Autonomous Coarse Alignment',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    }
  })

  mainWindow.maximize()
  mainWindow.setMenuBarVisibility(false)
  mainWindow.loadURL('data:text/html,' + encodeURIComponent(
    '<body style="background:#080c14;color:#9fb3c8;font:16px sans-serif;display:flex;' +
    'align-items:center;justify-content:center;height:100vh;margin:0">Starting FSOC-PAT backend…</body>'))

  waitForServer(() => mainWindow && mainWindow.loadURL(`http://127.0.0.1:${port}`))

  mainWindow.on('closed', () => {
    stopPythonServer()
    mainWindow = null
  })
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus() }
  })

  app.whenReady().then(async () => {
    port = await pickPort(port)
    startPythonServer()
    createWindow()
  })
}

app.on('before-quit', () => { app.isQuitting = true; stopPythonServer() })

app.on('window-all-closed', () => {
  stopPythonServer()
  app.quit()
})
