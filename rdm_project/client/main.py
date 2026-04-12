import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from rdm_project.client.core.client import RemoteManagerClient
from rdm_project.client.config import ClientConfig, parse_args, resolve_client_config
from rdm_project.client.ui.client_ui import run_dashboard


def main() -> None:
    args = parse_args(default_config_path=os.path.join(BASE_DIR, "config.json"))

    cfg: ClientConfig = resolve_client_config(args, os.path.join(BASE_DIR, "config.json"))

    client = RemoteManagerClient(
        cfg.server_ip,
        cfg.port,
        cfg.password,
        cfg.client_name,
        cfg.fps,
        cfg.jpeg_quality,
        cfg.scale,
    )

    if cfg.ui:
        run_dashboard(client, auto_connect=cfg.auto_connect)
    else:
        if cfg.auto_connect:
            client.connect(interactive=True)


if __name__ == "__main__":
    main()
