"""Offline pytest runner: deny business and paid endpoints, allow loopback test servers."""
from pathlib import Path
import os
import socket
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
_original = socket.socket.connect
# Existing regression policy: external services and the local business/model gateways
# are never reached. Ephemeral loopback fake servers remain usable.
BLOCKED = {4008, 4009, 4010, 8000, 8001, 8002, 8020, 8021, 8022, 8030, 8100, 8200, 9000}
def connect(self, address):
    if isinstance(address, tuple):
        host, port = address[:2]
        if host not in {'127.0.0.1', 'localhost', '::1', '0.0.0.0'} or port in BLOCKED:
            raise OSError(f'offline test guard blocked {host}:{port}')
    return _original(self, address)
socket.socket.connect = connect
import pytest
sys.exit(pytest.main(sys.argv[1:] or ['-q', 'tests']))
