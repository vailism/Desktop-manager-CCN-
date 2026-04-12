"""PyInstaller-friendly client UI launcher."""

import os
import sys


if getattr(sys, "frozen", False):
    base_dir = sys._MEIPASS
    os.chdir(base_dir)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from rdm_project.client.config import ClientConfig, parse_args, resolve_client_config
from rdm_project.client.core.client import RemoteManagerClient
from rdm_project.client.ui.client_ui import run_dashboard


def main() -> None:
    config_path = os.path.join(base_dir, "rdm_project", "client", "config.json")
    args = parse_args(default_config_path=config_path)
    cfg: ClientConfig = resolve_client_config(args, config_path)

    client = RemoteManagerClient(
        cfg.server_ip,
        cfg.port,
        cfg.password,
        cfg.client_name,
        cfg.fps,
        cfg.jpeg_quality,
        cfg.scale,
    )

    run_dashboard(client, auto_connect=cfg.auto_connect)


if __name__ == "__main__":
    main()
