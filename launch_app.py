import os
import runpy
import sys
import traceback
from datetime import datetime


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "run.log")


def log(message):
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")


def log_exception(exc_type, exc_value, exc_traceback):
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Unhandled exception during app startup\n")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=handle)


sys.excepthook = log_exception


if __name__ == "__main__":
    log(f"launch_app.py started with interpreter: {sys.executable}")
    try:
        runpy.run_path(os.path.join(BASE_DIR, "main.py"), run_name="__main__")
    except SystemExit as exc:
        log(f"Application exited with SystemExit({exc.code!r})")
        raise
    except Exception:
        log("Application startup failed.")
        raise
    else:
        log("Application exited normally.")