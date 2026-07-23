from __future__ import annotations

import fcntl
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin

from .config_schema import ConfigError
from .path_contract import PathContractError
from .schema import ProjectSpec


_PROCESS_ENV_PASSTHROUGH = {
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "SHELL",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "VIRTUAL_ENV",
}


def ensure_project_service(spec: ProjectSpec) -> None:
    """Start a configured local service once, using health as the success signal."""
    if not spec.local_deployment_enabled:
        return
    spec.require("project.resources.source.repository")
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
    try:
        script, project_root = _local_service_paths(spec)
    except (PathContractError, RuntimeError, FileNotFoundError, TypeError, AttributeError) as exc:
        raise ConfigError(f"local deployment requires executable start script: {exc}") from exc
    environment = _service_environment(spec)
    log_path = Path(tempfile.gettempdir()) / "verifier-service-locks" / f"{spec.project_id}.log"
    try:
        process = subprocess.Popen(
            [str(script)],
            cwd=project_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise ConfigError(f"failed to start local service for {spec.project_id}: {type(exc).__name__}") from exc
    if process.stdout is not None:
        threading.Thread(
            target=_write_redacted_log,
            args=(process.stdout, log_path, _registered_secret_values(spec)),
            daemon=True,
            name=f"{spec.project_id}-service-log",
        ).start()

    timeout = float(health["startup_timeout_seconds"])
    interval = float(health["interval_seconds"])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _healthy(service, health):
            return
        return_code = process.poll()
        if return_code not in (None, 0):
            raise ConfigError(
                f"local service start failed for {spec.project_id}: exit={return_code}; log={log_path}"
            )
        time.sleep(interval)
    raise ConfigError(f"local service health timeout for {spec.project_id}: log={log_path}")


def _local_service_paths(spec: ProjectSpec) -> tuple[Path, Path]:
    script_accessor = getattr(spec, "local_start_script_path", None)
    root_accessor = getattr(spec, "project_package_path", None)
    if not callable(script_accessor) or not callable(root_accessor):
        raise ConfigError("local deployment requires resolver-backed ProjectSpec path accessors")
    return script_accessor(), root_accessor()


def _service_environment(spec: ProjectSpec) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in _PROCESS_ENV_PASSTHROUGH or name.startswith("LC_")
    }
    _inject_registered_values(spec, environment)
    return environment


def _registered_secret_values(spec: ProjectSpec) -> tuple[str, ...]:
    if spec.environment is None:
        return ()
    canonical = {"project": spec.project, "runtime": spec.runtime, "verifier": spec.verifier}
    return tuple(
        str(value)
        for variable in spec.environment.variables.values()
        if variable.secret
        for value in [_read_binding(canonical, variable.bind)]
        if value not in (None, "")
    )


def _write_redacted_log(stream: Any, log_path: Path, secrets: tuple[str, ...]) -> None:
    with log_path.open("a", encoding="utf-8") as log_file:
        for line in stream:
            redacted = line
            for secret in secrets:
                redacted = redacted.replace(secret, "***")
            log_file.write(redacted)
            log_file.flush()


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
