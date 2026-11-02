import assert from 'node:assert/strict';
import { test } from 'node:test';
import { dirname, resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { homedir } from 'node:os';
import { mkdtempSync, symlinkSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import verifierReady from '../adapters/pi_before_settle.ts';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const A = 'a'.repeat(64), B = 'b'.repeat(64);
const state = (status = 'no_report', extra = {}) => ({ code: A, max_blocks: 6, status,
  gate: status === 'pass' ? 'PASS' : status === 'pass_with_exception' ? 'PASS_WITH_EXCEPTION' :
    status === 'needs_human' ? 'NEEDS_HUMAN' : 'FAIL',
  release_allowed: ['pass', 'pass_with_exception'].includes(status), report: '/tmp/gate-report',
  failures: [], ...extra });
const boundary = (extra = {}) => ({ type: 'agent_before_settle', outcome: 'completed', entries: [],
  continue: false, context: { canContinue: true }, ...extra });

async function fixture(initial = state(), saved = []) {
  const handlers = new Map();
  const entries = [...saved];
  const calls = [];
  let value = initial, id = 'session-one';
  const pi = { on: (name, handler) => handlers.set(name, handler),
    appendEntry: (customType, data) => entries.push({ type: 'custom', customType, data: structuredClone(data) }),
    exec: async (command, args, options) => {
      calls.push({ command, args, options });
      if (value instanceof Error) throw value;
      return value?.raw ?? { stdout: JSON.stringify(value), stderr: '', killed: false,
        code: value.release_allowed ? 0 : 1 };
    } };
  const ctx = { cwd: ROOT, sessionManager: { getSessionId: () => id, getEntries: () => entries } };
  const fire = async (name, event = {}) => handlers.get(name)({ type: name, ...event }, ctx);
  verifierReady(pi);
  await fire('session_start', { reason: 'startup' });
  return { fire, entries, calls, set: next => { value = next; }, newSession: next => { id = next; },
    setCwd: cwd => { ctx.cwd = cwd; },
    edit: (path = 'impl/example.py', extra = {}) => fire('tool_result', { toolName: 'edit',
      input: { path }, isError: false, ...extra }),
    settle: extra => fire('agent_before_settle', boundary(extra)) };
}

for (const status of ['no_report', 'stale', 'running', 'review_invalid', 'coverage_incomplete',
  'hard_fail', 'inconsistent', 'unanswered', 'needs_human']) {
  test(`blocks ${status} using only the read-only bridge`, async () => {
    const f = await fixture(state(status, { failures: ['call-X conflict'],
      response: { unanswered: ['case-A::F-01'], refuted_pending: ['case-A::F-02'] } }));
    await f.edit();
    const result = await f.settle();
    assert.equal(result.continue, true);
    assert.match(result.entries.at(-1).content, new RegExp(status));
    assert.match(result.entries.at(-1).content, /call-X conflict/);
    if (status === 'needs_human') assert.match(result.entries.at(-1).content, /等待人工裁决：case-A::F-02/);
    if (status === 'unanswered') assert.match(result.entries.at(-1).content, /case-A::F-01/);
    if (status === 'running') assert.match(result.entries.at(-1).content, /300 秒/);
    assert.ok(f.calls.every(c => c.command === 'bash' && c.args.length === 2 && c.args[1] === '--hook-status'));
  });
}

for (const status of ['pass', 'pass_with_exception']) {
  test(`allows backend ${status} after a code edit`, async () => {
    const f = await fixture(state(status));
    await f.edit();
    assert.equal(await f.settle(), undefined);
  });
}

test('documentation, excluded files and reads do not activate the gate', async () => {
  const f = await fixture();
  for (const path of ['spec/example.md', 'impl/__pycache__/module.py', 'impl/module.pyc',
    'impl-other/file.py', '../outside/impl/file.py', 'projects/other/file.py']) await f.edit(path);
  await f.fire('tool_result', { toolName: 'read', input: { path: 'impl/example.py' }, isError: false });
  assert.equal(await f.settle(), undefined);
});

test('detects content changes made through bash/custom tools, including failed commands', async () => {
  for (const name of ['bash', 'custom-mutation']) {
    const f = await fixture();
    f.set(state('no_report', { code: B }));
    await f.fire('tool_result', { toolName: name, input: {}, isError: true });
    assert.equal((await f.settle()).continue, true);
  }
});

test('an edit remains in scope after reverting content; failed untouched edits do not activate', async () => {
  const f = await fixture();
  await f.edit('impl/example.py', { isError: true });
  assert.equal(await f.settle(), undefined);
  await f.edit('projects/llm_probe/example.py');
  assert.equal((await f.settle()).continue, true);
});

test('pi @, tilde and file URL path forms activate even when content digest stays unchanged', async () => {
  for (const path of ['@impl/example.py', pathToFileURL(resolve(ROOT, 'impl/example.py')).href,
    '~/' + resolve(ROOT, 'impl/example.py').slice(homedir().length + 1)]) {
    const f = await fixture();
    await f.edit(path);
    assert.equal((await f.settle()).continue, true, path);
  }
});

test('a symlink spelling of the repository cwd still activates a same-content scoped write', async () => {
  const directory = mkdtempSync(resolve(tmpdir(), 'verifier-ready-cwd-'));
  try {
    const alias = resolve(directory, 'repo-alias');
    symlinkSync(ROOT, alias, 'dir');
    const f = await fixture();
    f.setCwd(alias);
    await f.edit('@impl/example.py');
    assert.equal((await f.settle()).continue, true);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('six blocks then a visible limit notice, with no forced continuation', async () => {
  const f = await fixture();
  await f.edit();
  for (let i = 0; i < 6; i++) assert.equal((await f.settle()).continue, true);
  const result = await f.settle();
  assert.equal(result.continue, false);
  assert.match(result.entries.at(-1).content, /门未通过，已达拦截上限（6 次）/);
  assert.equal(result.entries.at(-1).details.blocks, 6);
});

test('another extension continuation and entries survive the cap', async () => {
  const f = await fixture(state('no_report', { max_blocks: 1 }));
  await f.edit();
  const first = { type: 'custom', customType: 'other-extension', data: {} };
  assert.deepEqual((await f.settle({ entries: [first] })).entries[0], first);
  const capped = await f.settle({ entries: [first], continue: true });
  assert.equal(capped.continue, true);
  assert.deepEqual(capped.entries[0], first);
});

test('reload/resume retain session count; a new session starts fresh', async () => {
  const f = await fixture(state('no_report', { max_blocks: 1 }));
  await f.edit(); await f.settle();
  const resumed = await fixture(state('no_report', { max_blocks: 1 }), f.entries);
  assert.equal((await resumed.settle()).continue, false);
  resumed.newSession('session-two');
  await resumed.fire('session_start', { reason: 'new' });
  assert.equal(await resumed.settle(), undefined);
  await resumed.edit();
  assert.equal((await resumed.settle()).continue, true);
});

test('human wait also obeys the cap, avoiding an endless needs_human loop', async () => {
  const f = await fixture(state('needs_human', { max_blocks: 1 }));
  await f.edit();
  assert.equal((await f.settle()).continue, true);
  const capped = await f.settle();
  assert.equal(capped.continue, false);
  assert.match(capped.entries.at(-1).content, /等待人工裁决/);
});

test('never restarts an aborted/error run', async () => {
  const f = await fixture();
  await f.edit();
  for (const extra of [{ outcome: 'aborted' }, { outcome: 'error' }]) {
    const calls = f.calls.length;
    assert.equal(await f.settle(extra), undefined);
    assert.equal(f.calls.length, calls);
  }
});

test('malformed status, invalid exit and bridge failures cannot turn into a pass', async () => {
  for (const bad of [new Error('status timed out'), state('pass', { release_allowed: false }),
    state('pass', { code: 'bogus' }), state('pass', { failures: {} }),
    { raw: { code: 0, stdout: 'not JSON', stderr: '', killed: false } },
    { raw: { code: 2, stdout: '', stderr: 'broken report', killed: false } },
    { raw: { code: 0, stdout: '', stderr: '', killed: true } }]) {
    const f = await fixture();
    await f.edit(); f.set(bad);
    const result = await f.settle();
    assert.equal(result.continue, true);
    assert.match(result.entries.at(-1).content, /状态读取失败/);
  }
});

test('pi installed loader, runner and projection accept continuation after a final assistant message', async () => {
  assert.ok(process.env.PI_GATE_TEST_PACKAGE, 'pytest wrapper supplies the installed pi package path');
  const pkg = process.env.PI_GATE_TEST_PACKAGE;
  const { loadExtensions, loadExtensionFromFactory } = await import(pathToFileURL(resolve(pkg, 'dist/core/extensions/loader.js')));
  const { ExtensionRunner } = await import(pathToFileURL(resolve(pkg, 'dist/core/extensions/runner.js')));
  const { SessionManager } = await import(pathToFileURL(resolve(pkg, 'dist/core/session-manager.js')));
  const { AgentSession } = await import(pathToFileURL(resolve(pkg, 'dist/core/agent-session.js')));
  const { createEventBus } = await import(pathToFileURL(resolve(pkg, 'dist/core/event-bus.js')));
  const loaded = await loadExtensions([resolve(ROOT, 'hooks/verifier-ready/adapters/pi_before_settle.ts')], ROOT);
  assert.deepEqual(loaded.errors, []);
  assert.equal(loaded.extensions.length, 1);
  const manager = SessionManager.inMemory(ROOT);
  loaded.runtime.appendEntry = (kind, data) => manager.appendCustomEntry(kind, data);
  const actualRunner = new ExtensionRunner(loaded.extensions, loaded.runtime, ROOT, manager, {});
  const actualErrors = [];
  actualRunner.onError(error => actualErrors.push(error));
  await actualRunner.emit({ type: 'session_start', reason: 'startup' });
  assert.deepEqual(actualErrors, []);
  assert.match(manager.getEntries().at(-1).data.last_code, /^[a-f0-9]{64}$/);
  // Keep the real runtime and projection, isolate the gate command's status input.
  const extension = await loadExtensionFromFactory(pi => verifierReady({ ...pi,
    exec: async (command, args) => {
      assert.equal(command, 'bash'); assert.equal(args[1], '--hook-status');
      return { code: 1, killed: false, stderr: '', stdout: JSON.stringify(state('inconsistent')) };
    } }), ROOT, createEventBus(), loaded.runtime);
  manager.appendMessage({ role: 'user', content: 'implement the change', timestamp: Date.now() });
  manager.appendMessage({ role: 'assistant', content: [{ type: 'text', text: 'done' }], api: 'openai-completions',
    provider: 'fixture', model: 'fixture', stopReason: 'stop', timestamp: Date.now(),
    usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } });
  const session = Object.assign(Object.create(AgentSession.prototype), { sessionManager: manager, _cwd: ROOT,
    agent: { peekQueuedMessages: () => [], hasQueuedMessages: () => false, state: { messages: [] } },
    _pendingCustomMessages: [], _entryIdsByMessage: new Map(), _eventListeners: [], _lastActivityOutcome: 'completed' });
  assert.equal(session._buildBoundaryContext([], 'agent_before_settle').canContinue, false);
  const runner = new ExtensionRunner([extension], loaded.runtime, ROOT, manager, {});
  const errors = [];
  runner.onError(error => errors.push(error));
  await runner.emit({ type: 'session_start', reason: 'startup' });
  await runner.emitToolResult({ type: 'tool_result', toolName: 'edit', toolCallId: 'test-edit',
    input: { path: 'impl/synthetic.py' }, content: [], isError: false, details: undefined });
  const result = await runner.emitBoundary({ type: 'agent_before_settle', outcome: 'completed' },
    entries => session._buildBoundaryContext(entries, 'agent_before_settle'));
  assert.deepEqual(errors, []);
  assert.equal(result.valid, true);
  assert.equal(result.continue, true);
  assert.equal(result.entries.at(-1).type, 'custom_message');
  assert.equal(result.entries.at(-1).customType, 'verifier-ready-gate');
  assert.equal(result.context.canContinue, true);
  assert.equal(result.context.llmMessages.at(-1).role, 'user');
  session._extensionRunner = runner;
  assert.equal(await session._runBeforeSettleBoundary(), true);
  assert.equal(manager.getEntries().at(-1).type, 'custom_message');
  assert.equal(session._buildBoundaryContext([], 'agent_before_settle').canContinue, true);
  loaded.runtime.appendEntry = () => { throw new Error('ENOSPC: synthetic session append failure'); };
  const failedPersistence = await runner.emitBoundary({ type: 'agent_before_settle', outcome: 'completed' },
    entries => session._buildBoundaryContext(entries, 'agent_before_settle'));
  assert.deepEqual(errors, []);
  assert.equal(failedPersistence.continue, true);
  assert.match(failedPersistence.entries.at(-1).content, /会话状态保存失败.*ENOSPC/);
});
