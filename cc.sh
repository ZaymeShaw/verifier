#!/usr/bin/env bash
export CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1
export CLAUDE_CODE_PROPAGATE_TRACEPARENT=1
export TRACEPARENT="00-$(openssl rand -hex 16)-$(openssl rand -hex 8)-01"

echo "$TRACEPARENT" >&2
claude -p "$1" --mcp-config mcp.json
