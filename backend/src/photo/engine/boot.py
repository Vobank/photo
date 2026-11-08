"""Engine entry point, executed by the *engine* interpreter (not the app's).

    python boot.py --parent-pid 1234 --comfy-dir /path/to/comfyui -- <comfyui args>

Starts a watchdog that exits the engine as soon as the app server process is gone,
so a crashed or force-killed app never leaves an orphan holding the GPU. Must stay
standalone: only the stdlib and psutil (a ComfyUI dependency) are available here.
"""

import argparse
import os
import runpy
import sys
import threading
import time


def _watch_parent(pid: int) -> None:
    import psutil

    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        os._exit(3)
    while True:
        if not parent.is_running() or parent.status() == psutil.STATUS_ZOMBIE:
            os._exit(3)
        time.sleep(1.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent-pid", type=int, required=True)
    ap.add_argument("--comfy-dir", required=True)
    ap.add_argument("rest", nargs=argparse.REMAINDER)
    ns = ap.parse_args()

    threading.Thread(target=_watch_parent, args=(ns.parent_pid,), daemon=True).start()

    comfy_dir = os.path.abspath(ns.comfy_dir)
    rest = ns.rest[1:] if ns.rest[:1] == ["--"] else ns.rest
    os.chdir(comfy_dir)
    sys.path.insert(0, comfy_dir)
    sys.argv = [os.path.join(comfy_dir, "main.py"), *rest]
    runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main()
