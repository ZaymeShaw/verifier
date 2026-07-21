from __future__ import annotations

from typing import Any


__all__ = ["app", "create_app"]


def __getattr__(name: str) -> Any:
    """Keep package import side-effect free so startup CLI overrides resolve first."""
    if name not in __all__:
        raise AttributeError(name)
    from .app import app, create_app

    return app if name == "app" else create_app
