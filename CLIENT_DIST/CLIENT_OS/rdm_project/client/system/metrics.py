import psutil


def sample_metrics() -> dict:
    return {
        "cpu_pct": float(psutil.cpu_percent(interval=None)),
        "ram_pct": float(psutil.virtual_memory().percent),
    }
