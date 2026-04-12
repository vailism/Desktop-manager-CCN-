"""Client configuration loading for CLI, environment, and config.json."""

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from rdm_project.shared.constants import (
    DEFAULT_CLIENT_NAME,
    DEFAULT_FPS,
    DEFAULT_JPEG_QUALITY,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_SCALE,
)


@dataclass
class ClientConfig:
    server_ip: str
    port: int
    password: str
    client_name: str
    auto_connect: bool
    fps: float
    jpeg_quality: int
    scale: float
    ui: bool


def _load_json(path: str) -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _env_bool(name: str, fallback: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return fallback
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_client_config(args: argparse.Namespace, default_config_path: str) -> ClientConfig:
    raw = _load_json(getattr(args, "config", "") or default_config_path)

    server_ip = (
        getattr(args, "server_ip", None)
        or os.getenv("RDM_SERVER_IP")
        or str(raw.get("server_ip", "127.0.0.1"))
    )
    port = int(
        getattr(args, "port", None)
        or os.getenv("RDM_SERVER_PORT")
        or int(raw.get("port", raw.get("server_port", DEFAULT_PORT)))
    )
    password = (
        getattr(args, "password", None)
        or os.getenv("RDM_PASSWORD")
        or str(raw.get("password", DEFAULT_PASSWORD))
    )
    client_name = (
        getattr(args, "client_name", None)
        or os.getenv("RDM_CLIENT_NAME")
        or str(raw.get("client_name", raw.get("name", DEFAULT_CLIENT_NAME)))
    )

    auto_connect = bool(raw.get("auto_connect", True))
    auto_connect = _env_bool("RDM_AUTO_CONNECT", auto_connect)
    if getattr(args, "auto_connect", None) is not None:
        auto_connect = bool(args.auto_connect)

    fps = float(getattr(args, "fps", None) or os.getenv("RDM_FPS") or float(raw.get("fps", DEFAULT_FPS)))
    jpeg_quality = int(
        getattr(args, "jpeg_quality", None)
        or os.getenv("RDM_JPEG_QUALITY")
        or int(raw.get("jpeg_quality", DEFAULT_JPEG_QUALITY))
    )
    scale = float(getattr(args, "scale", None) or os.getenv("RDM_SCALE") or float(raw.get("scale", DEFAULT_SCALE)))

    ui = bool(raw.get("ui", True))
    ui = _env_bool("RDM_UI", ui)
    if getattr(args, "ui", None) is not None:
        ui = bool(args.ui)

    return ClientConfig(
        server_ip=server_ip,
        port=port,
        password=password,
        client_name=client_name,
        auto_connect=auto_connect,
        fps=fps,
        jpeg_quality=jpeg_quality,
        scale=scale,
        ui=ui,
    )


def parse_args(default_config_path: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RDM Client")
    parser.add_argument("--config", default=default_config_path)
    parser.add_argument("--server-ip", dest="server_ip", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--client-name", dest="client_name", default=None)
    parser.add_argument("--auto-connect", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--fps", type=float, default=None)
    parser.add_argument("--jpeg-quality", type=int, default=None)
    parser.add_argument("--scale", type=float, default=None)
    parser.add_argument("--ui", action=argparse.BooleanOptionalAction, default=None)
    return parser.parse_args()


def save_client_config(path: str, cfg: ClientConfig) -> None:
    Path(path).write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
