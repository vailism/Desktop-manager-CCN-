"""Server configuration loading for CLI, environment, and config.json."""

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from rdm_project.shared.constants import DEFAULT_HOST, DEFAULT_PASSWORD, DEFAULT_PORT


@dataclass
class ServerConfig:
    host: str
    port: int
    password: str


def _load_json(path: str) -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RDM Server")
    parser.add_argument("--config", default="", help="Optional config json path")
    parser.add_argument("--host", default=None, help="Override host")
    parser.add_argument("--port", type=int, default=None, help="Override port")
    parser.add_argument("--password", default=None, help="Override password")
    return parser.parse_args()


def resolve_server_config(args: argparse.Namespace, default_config_path: str) -> ServerConfig:
    raw = _load_json(getattr(args, "config", "") or default_config_path)

    host = (
        getattr(args, "host", None)
        or os.getenv("RDM_SERVER_HOST")
        or str(raw.get("host", DEFAULT_HOST))
    )
    port = int(
        getattr(args, "port", None)
        or os.getenv("RDM_SERVER_PORT")
        or int(raw.get("port", DEFAULT_PORT))
    )
    password = (
        getattr(args, "password", None)
        or os.getenv("RDM_SERVER_PASSWORD")
        or str(raw.get("password", DEFAULT_PASSWORD))
    )

    return ServerConfig(host=host, port=port, password=password)
