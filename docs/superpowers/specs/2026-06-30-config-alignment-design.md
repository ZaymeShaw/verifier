# Config Alignment Design

Date: 2026-06-30

## Goal

Unify this project's runtime configuration so server startup, Python execution, LLM settings, and UAT/E2E ports are read from a single project-level configuration path with predictable overrides.

The first implementation will use the minimal方案 A:

- Add `impl/config.yaml` as the canonical non-secret runtime config file.
- Add `impl/core/config.py` as the only runtime config loading layer.
- Keep API keys and other secrets in environment variables.
- Preserve current behavior where possible, including existing DeepSeek env names and `env.md` fallback.

## Non-goals

This design intentionally does not include:

- Profile support such as `local` / `uat` / `ci` sections.
- Moving or redesigning `impl/projects/*/project.yaml`.
- Storing API keys or secrets in `impl/config.yaml`.
- Docker, CI, or deployment pipeline redesign.
- Full adapter/business-service configuration migration.
- Removing the existing `env.md` compatibility path.

## Configuration file

Create `impl/config.yaml`:

```yaml
python:
  executable: python

server:
  host: 127.0.0.1
  port: 8020

uat:
  host: 127.0.0.1
  port: 8021

llm:
  provider: deepseek
  model: deepseek-v4-pro
  base_url: https://api.deepseek.com/v1/chat/completions
  api_key_env:
    - DEEPSEEK_API_KEY
    - LLM_API_KEY
```

`impl/config.yaml` contains only non-sensitive defaults. It may name environment variables where secrets should be read from, but it must not contain actual secret values.

## Override order

Runtime values resolve in this order:

```text
CLI arguments > environment variables > impl/config.yaml > code defaults
```

Supported environment overrides for the first version:

```text
PYTHON_EXECUTABLE
VERIFIER_HOST
VERIFIER_PORT
VERIFIER_UAT_HOST
VERIFIER_UAT_PORT
LLM_PROVIDER
LLM_MODEL
LLM_BASE_URL
DEEPSEEK_BASE_URL
DEEPSEEK_API_KEY
LLM_API_KEY
```

LLM API key lookup uses `llm.api_key_env` order from `impl/config.yaml`, defaulting to:

```text
DEEPSEEK_API_KEY > LLM_API_KEY > env.md fallback
```

## New config module

Add `impl/core/config.py` with a small typed API:

```python
get_runtime_config()
get_python_config()
get_server_config()
get_uat_config()
get_llm_config()
```

The module is responsible for:

- Loading `impl/config.yaml`.
- Applying code defaults if the file or individual keys are missing.
- Applying supported environment variable overrides.
- Converting port strings to integers.
- Validating host/port shape.
- Resolving LLM API key from the configured env var order.
- Providing clear error messages for malformed YAML or invalid values.

The implementation should keep this layer lightweight. It does not need a heavy schema framework in the first version.

## Server startup

`impl/server.py` currently has hardcoded parser defaults:

```python
parser.add_argument("--port", type=int, default=8020)
parser.add_argument("--host", default="127.0.0.1")
```

Change this to read defaults from `get_server_config()`:

```text
impl/config.yaml
  -> env overrides VERIFIER_HOST / VERIFIER_PORT
  -> CLI overrides --host / --port
  -> uvicorn.run(...)
```

Expected behavior:

```bash
python -m impl.server
```

starts on `server.host` and `server.port` from config unless environment variables override them.

```bash
VERIFIER_PORT=8022 python -m impl.server
```

uses port `8022`.

```bash
python -m impl.server --port 8023
```

uses port `8023`, overriding env and config.

## Python startup

`start_server.sh` currently hardcodes a local Conda Python path. Replace it with a portable launcher:

```bash
#!/bin/bash
set -euo pipefail

PYTHON_BIN="${PYTHON_EXECUTABLE:-python}"
exec "$PYTHON_BIN" -m impl.server "$@"
```

This keeps shell startup simple and portable. The shell script does not parse YAML. If a user needs a custom interpreter locally, they set `PYTHON_EXECUTABLE`:

```bash
PYTHON_EXECUTABLE=/path/to/python ./start_server.sh
```

`python.executable` remains documented in `impl/config.yaml` for Python-side tooling and future launch helpers, but the first shell launcher uses the environment variable for portability.

## LLM configuration

`impl/core/llm_client.py` currently owns model/base URL defaults and reads env vars directly. Move runtime default resolution into `impl/core/config.py`.

`LlmClient()` should receive defaults equivalent to:

```text
model = get_llm_config().model
base_url = get_llm_config().base_url
api_key = get_llm_config().api_key
```

The following compatibility behavior stays intact:

- `DEEPSEEK_API_KEY` and `LLM_API_KEY` continue to work.
- `DEEPSEEK_BASE_URL` and `LLM_BASE_URL` continue to work.
- `env.md` fallback remains for local compatibility.
- The Agno/OpenAI compatibility bridge remains, but should be isolated behind a clear helper such as `ensure_openai_compat_api_key(api_key)`.

Missing key behavior should remain non-crashing and return a structured missing-key response. The message may be generalized to mention configured key env names.

## UAT and E2E ports

Separate runtime server port from UAT/E2E target port:

- `server.port`: default verifier UI/backend server port.
- `uat.port`: default UAT/E2E target port.

Existing tests or smoke checks that hardcode `8020` should instead build URLs from `get_uat_config()` and allow `VERIFIER_UAT_PORT` to override.

If an existing test assumes the server is already running, that assumption remains unchanged in the first version. Only the target URL construction changes.

## Documentation updates

Update `README.md` to show the standard startup path:

```bash
python -m impl.server
```

Document that defaults are in:

```text
impl/config.yaml
```

Document common overrides:

```bash
VERIFIER_PORT=8022 python -m impl.server
python -m impl.server --port 8023
export DEEPSEEK_API_KEY="..."
```

Remove or replace examples that imply a machine-specific Python path is the standard launch method.

## Error handling

The config layer should raise clear configuration errors for invalid local setup:

- Malformed YAML: include `impl/config.yaml` and the parser error.
- Missing PyYAML: explain that runtime config requires `pyyaml` in the project environment.
- Invalid port: identify the exact field and require `1..65535`.
- Invalid `api_key_env`: require a list of non-empty strings.

LLM missing-key behavior remains a runtime LLM response, not a process-level crash.

## Testing

Add or update tests for these behaviors:

1. Config loading
   - Defaults load from `impl/config.yaml`.
   - Missing config keys fall back to code defaults.
   - Env vars override YAML values.
   - Invalid port values fail clearly.
   - LLM key resolution follows `api_key_env` order.

2. Server startup
   - Default host/port come from config.
   - `VERIFIER_PORT` overrides config.
   - CLI `--port` overrides env/config.
   - `uvicorn.run` can be monkeypatched so the test does not start a real server.

3. LLM client
   - Default model/base URL come from config.
   - `DEEPSEEK_BASE_URL` / `LLM_BASE_URL` override config.
   - Missing key returns the existing structured error.
   - OpenAI compatibility env bridge still sets the request API key as expected.

4. UAT URL construction
   - URLs use `uat.host` / `uat.port`.
   - `VERIFIER_UAT_PORT` overrides config.

## Migration impact

Existing users can still run:

```bash
python -m impl.server --port 8020
```

Existing LLM env vars still work. The main visible change is that plain startup:

```bash
python -m impl.server
```

now gets its default host and port from `impl/config.yaml`, and `start_server.sh` no longer assumes a developer-specific Conda path.
