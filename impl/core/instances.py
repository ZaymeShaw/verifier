"""Persistent port bindings and exclusive ownership of verifier runtime data."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import socket
import uuid

ROOT = Path(__file__).resolve().parents[2]
INSTANCE_ENV = 'VERIFIER_INSTANCE_ID'


def instance_root(instance_id, repository_root=None):
    if not re.fullmatch(r'inst-[a-f0-9]{16}', instance_id):
        raise ValueError('Invalid verifier instance ID')
    return Path(repository_root or ROOT) / '.runtime/instances' / instance_id


def data_root(repository_root=None, environ=None):
    root = Path(repository_root or ROOT)
    env = os.environ if environ is None else environ
    identity = env.get(INSTANCE_ENV)
    return instance_root(identity, root) / 'data' if identity else root / 'impl/data'


def tracing_root():
    identity = os.environ.get(INSTANCE_ENV)
    if not identity:
        raise ValueError('Tracing operation requires a resolved verifier instance')
    return instance_root(identity) / 'tracing'


def _atomic_json(path, value):
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with tmp.open('x') as f:
        json.dump(value, f, indent=2); f.write('\n')
    tmp.replace(path)


def _port_available(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def resolve_instance(port, *, repository_root=None, relay_start=None):
    root = Path(repository_root or ROOT)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid server port')
    if relay_start is None:
        cfg = root / 'tracing/config.yaml'
        if cfg.is_file():
            import yaml
            relay_start = yaml.safe_load(cfg.read_text())['relay_port_start']
        else:
            relay_start = 4005
    if type(relay_start) is not int or not 1024 <= relay_start <= 65533:
        raise ValueError('Invalid relay_port_start')
    runtime = root / '.runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    registry = runtime / 'instances.json'
    with (runtime / 'instances.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        bindings = json.loads(registry.read_text()) if registry.exists() else {'ports': {}, 'instances': {}}
        key = str(port)
        if key not in bindings['ports']:
            identity = 'inst-' + uuid.uuid4().hex[:16]
            reserved = {p for i in bindings['instances'].values() for p in i['relay_ports']}
            if port in reserved:
                raise ValueError(f'Server port {port} is reserved by an instance relay')
            reserved.update(int(p) for p in bindings['ports'])
            reserved.add(port)
            ports = []
            for candidate in range(relay_start, 65536):
                if candidate not in reserved and _port_available(candidate):
                    ports.append(candidate)
                    if len(ports) == 3:
                        break
            if len(ports) != 3:
                raise ValueError('No three available relay ports')
            bindings['ports'][key] = identity
            bindings['instances'][identity] = {'relay_ports': ports}
            _seed(root, identity)
            _atomic_json(registry, bindings)
        identity = bindings['ports'][key]
        instance_root(identity, root)  # validate before use
        return {'id': identity, 'port': port, **bindings['instances'][identity]}


def _seed(root, identity):
    """新实例的出厂数据：仓库 impl/data/ 下各项目目录（场景、登记、轴定义与代码、资料）拷一份，之后各自维护。
    运行期产物（context_store、sqlite、case_pools 等不在项目目录里的）不拷。"""
    source = root / 'impl/data'
    projects = {p.name for p in (root / 'impl/projects').iterdir() if p.is_dir()} if (root / 'impl/projects').is_dir() else set()
    target = instance_root(identity, root) / 'data'
    for item in sorted(source.iterdir()) if source.is_dir() else ():
        if item.is_dir() and item.name in projects:
            shutil.copytree(item, target / item.name,
                            ignore=shutil.ignore_patterns('__pycache__', '.DS_Store', '*.bak*', '*.tmp'))


@contextmanager
def instance_lock(instance, *, repository_root=None):
    path = instance_root(instance['id'], repository_root)
    path.mkdir(parents=True, exist_ok=True)
    with (path / 'server.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.seek(0)
            raise ValueError(f"Instance {instance['id']} is already owned by {lock.read().strip() or 'another server'}")
        lock.seek(0); lock.truncate()
        json.dump({'pid': os.getpid(), 'port': instance['port']}, lock); lock.flush()
        try:
            yield path
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def activate(instance):
    identity = instance['id']
    os.environ[INSTANCE_ENV] = identity
    os.environ['VERIFIER_PORT'] = str(instance['port'])
    prefix = f'verifier://.runtime/instances/{identity}/data'
    os.environ['CONTEXT_DATA_ROOT'] = prefix + '/context_runtime'
    os.environ['CONTEXT_STORE_ROOT'] = prefix + '/context_store'


def rebind_port(old_port, new_port):
    """Move an idle instance's binding; never allow two active owners."""
    runtime = ROOT / '.runtime'
    registry = runtime / 'instances.json'
    if not 1 <= new_port <= 65535:
        raise ValueError('Invalid server port')
    with (runtime / 'instances.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        bindings = json.loads(registry.read_text())
        if str(new_port) in bindings['ports']:
            raise ValueError('Destination port already has a binding')
        if any(new_port in item['relay_ports'] for item in bindings['instances'].values()):
            raise ValueError('Destination port is reserved by a relay')
        identity = bindings['ports'][str(old_port)]
        with instance_lock({'id': identity, 'port': old_port}):
            del bindings['ports'][str(old_port)]
            bindings['ports'][str(new_port)] = identity
            _atomic_json(registry, bindings)
        return identity
