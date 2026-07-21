from __future__ import annotations

import fcntl
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin

from .config_schema import ConfigError
from .schema import ProjectSpec


def ensure_project_service(spec: ProjectSpec) -> None:
    """Start a configured local service once, using health as the success signal."""
    if not spec.local_deployment_enabled:
        return
    primary = spec.service("primary")
    health = primary.get("healthcheck") or {}
    if _healthy(primary, health):
        return

    lock_root = Path(tempfile.gettempdir()) / "verifier-service-locks"
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = lock_root / f"{spec.project_id}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if _healthy(primary, health):
            return
        _start_and_wait(spec, primary, health)


def _start_and_wait(spec: ProjectSpec, service: Mapping[str, Any], health: Mapping[str, Any]) -> None:
    script = Path(spec.root) / "scripts" / "start.sh"
    if not script.is_file() or script.stat().st_mode & 0o111 == 0:
        raise ConfigError(f"local deployment requires executable start script: {script}")
    environment = dict(os.environ)
    _inject_registered_values(spec, environment)
    log_path = Path(tempfile.gettempdir()) / "verifier-service-locks" / f"{spec.project_id}.log"
    log_file = log_path.open("ab")
    try:
        process = subprocess.Popen(
            [str(script)],
            cwd=spec.root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        log_file.close()
        raise ConfigError(f"failed to start local service for {spec.project_id}: {type(exc).__name__}") from exc

    timeout = float(health["startup_timeout_seconds"])
    interval = float(health["interval_seconds"])
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if _healthy(service, health):
                return
            return_code = process.poll()
            if return_code not in (None, 0):
                raise ConfigError(
                    f"local service start failed for {spec.project_id}: exit={return_code}; log={log_path}"
                )
            time.sleep(interval)
    finally:
        log_file.close()
    raise ConfigError(f"local service health timeout for {spec.project_id}: log={log_path}")


def _healthy(service: Mapping[str, Any], health: Mapping[str, Any]) -> bool:
    if not health:
        return False
    url = urljoin(str(service["base_url"]).rstrip("/") + "/", str(health["endpoint"]).lstrip("/"))
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=float(health["request_timeout_seconds"])) as response:
            return 200 <= int(response.status) < 400
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _inject_registered_values(spec: ProjectSpec, environment: dict[str, str]) -> None:
    if spec.environment is None:
        return
    canonical = {
        "project": spec.project,
        "runtime": spec.runtime,
        "verifier": spec.verifier,
    }
    for variable in spec.environment.variables.values():
        value = _read_binding(canonical, variable.bind)
        if value not in (None, ""):
            environment[variable.name] = str(value)


def _read_binding(document: Mapping[str, Any], path: str) -> Any:
    value: Any = document
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value
