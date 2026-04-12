"""PyInstaller-friendly server launcher."""

import os
import sys


if getattr(sys, "frozen", False):
    base_dir = sys._MEIPASS
    os.chdir(base_dir)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from rdm_project.server.main import main as run_server


if __name__ == "__main__":
    run_server()
