import os
import sys
import traceback
from datetime import datetime

from streamlit.web import cli as stcli


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, 'web_run.log')
HOST = os.environ.get('HSS_TRUSS_HOST', '0.0.0.0')
PORT = os.environ.get('PORT', os.environ.get('HSS_TRUSS_PORT', '8501'))


def log(message):
    with open(LOG_FILE, 'a', encoding='utf-8') as handle:
        handle.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n')


def log_exception(exc_type, exc_value, exc_traceback):
    with open(LOG_FILE, 'a', encoding='utf-8') as handle:
        handle.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] Streamlit server failed\n')
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=handle)


sys.excepthook = log_exception


if __name__ == '__main__':
    os.chdir(BASE_DIR)
    log(f'launch_web_server.py started with interpreter: {sys.executable}')
    log(f'Streamlit binding to {HOST}:{PORT}')
    sys.argv = [
        'streamlit',
        'run',
        os.path.join(BASE_DIR, 'web_app.py'),
        f'--server.address={HOST}',
        f'--server.port={PORT}',
        '--server.headless=true',
        '--server.fileWatcherType=none',
        '--browser.gatherUsageStats=false',
    ]
    try:
        raise SystemExit(stcli.main())
    except SystemExit as exc:
        log(f'Streamlit server exited with code {exc.code!r}')
        raise
    except Exception:
        log('Streamlit server startup crashed.')
        raise