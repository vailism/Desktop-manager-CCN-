import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from rdm_project.server.config import parse_args, resolve_server_config
from rdm_project.server.ui.server_ui import main as run_server_ui


def main() -> None:
    args = parse_args()
    cfg = resolve_server_config(args, os.path.join(BASE_DIR, "config.json"))

    argv = [sys.argv[0]]
    argv += ["--host", cfg.host]
    argv += ["--port", str(cfg.port)]
    argv += ["--password", cfg.password]

    old_argv = sys.argv
    try:
        sys.argv = argv
        run_server_ui()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    main()
