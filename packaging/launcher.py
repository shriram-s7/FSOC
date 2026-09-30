"""Entry point for the frozen FSOC-PAT backend (fsoc-server.exe).

Usage:
  fsoc-server.exe                                  run the FastAPI server
  fsoc-server.exe --comparison-worker DIR MODE     run one comparison worker

Writable data (sessions, uploaded videos, logs) goes to FSOC_DATA_DIR,
defaulting to %LOCALAPPDATA%\\FSOC-PAT, because the install folder may be
read-only. Bundled read-only files (models, config, frontend) are resolved
relative to the bundle directory, which becomes the working directory.
"""
import multiprocessing
import os
import sys


def _prepare():
    bundle = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.chdir(bundle)
    data = os.environ.get('FSOC_DATA_DIR') or os.path.join(
        os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'FSOC-PAT')
    os.environ.setdefault('FSOC_LOGS_DIR', os.path.join(data, 'logs'))
    os.environ.setdefault('FSOC_VIDEOS_DIR', os.path.join(data, 'input_videos'))
    os.environ.setdefault('FSOC_UI_LOG_DIR', os.path.join(data, 'server-logs'))
    for key in ('FSOC_LOGS_DIR', 'FSOC_VIDEOS_DIR', 'FSOC_UI_LOG_DIR'):
        os.makedirs(os.environ[key], exist_ok=True)


def main():
    multiprocessing.freeze_support()
    _prepare()
    args = sys.argv[1:]
    if args[:1] == ['--comparison-worker']:
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
        from comparison.worker import run
        run(args[1], args[2])
        return
    import uvicorn
    import server.app as backend
    backend._uvicorn_server = uvicorn.Server(uvicorn.Config(
        backend.app, host='127.0.0.1', port=int(os.environ.get('FSOC_PORT', 8765)),
        log_level='warning'))
    backend._uvicorn_server.run()


if __name__ == '__main__':
    main()
