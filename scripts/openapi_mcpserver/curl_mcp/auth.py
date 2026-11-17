"""Load project cURL requests or trusted functions that return an invocation token."""
import importlib
import importlib.util
import inspect
import sys
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import ModuleType

from .config import Settings
from .curl_auth import CurlToken, load_curl, validate_token


@dataclass
class ScriptAuth:
    function: Callable[[dict[str, str]], Awaitable[str]]
    env: dict[str, str]

    async def token(self, client=None) -> str:
        return validate_token(await self.function(env=dict(self.env)))


class AuthHandlers(dict[str, ScriptAuth | CurlToken]):
    """Isolated Python package for project scripts and their relative imports."""

    def __init__(self, project_dir):
        super().__init__()
        self.namespace = "_mcp_auth_" + uuid.uuid4().hex
        package = ModuleType(self.namespace)
        package.__path__ = [str(project_dir)]
        sys.modules[self.namespace] = package

    def close(self):
        self.clear()
        for name in list(sys.modules):
            if name == self.namespace or name.startswith(self.namespace + "."):
                del sys.modules[name]


def load_handlers(settings: Settings, env: dict[str, str]) -> AuthHandlers:
    handlers = AuthHandlers(settings._project_dir)
    for name, operation in settings.operations.items():
        auth = operation.auth
        if auth is None:
            continue
        try:
            if not isinstance(auth, str):
                handlers[name] = load_curl(settings._project_dir, auth.curl, auth.token_path, env)
                continue
            filename, function_name = auth.rsplit(":", 1)
            path = (settings._project_dir / filename).resolve()
            relative = path.relative_to(settings._project_dir).with_suffix("")
            if not all(part.isidentifier() for part in relative.parts) or not path.is_file():
                raise ValueError("Script must be a project-local Python module")
            module_name = handlers.namespace + "." + ".".join(relative.parts)
            if module_name not in sys.modules:
                importlib.import_module(module_name.rpartition(".")[0])
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    raise ValueError("Cannot load script")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            module = sys.modules[module_name]
            if getattr(module, "__file__", None) != str(path):
                raise ValueError("Conflicting module name")
            function = getattr(module, function_name)
            if not inspect.iscoroutinefunction(function):
                raise ValueError("Auth function must be async")
            inspect.signature(function).bind(env={})
        except Exception:
            handlers.close()
            # Arbitrary script exceptions may include credentials or HTTP request URLs.
            raise ValueError(f"Cannot load auth handler for {name}; check its file, syntax and environment variables") from None
        handlers[name] = ScriptAuth(function, dict(env))
    return handlers
