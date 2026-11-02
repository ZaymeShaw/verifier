/** Independent pi adapter. Load explicitly; no project registration is installed. */
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";
import { existsSync, realpathSync } from "node:fs";
import type { ExtensionAPI, ExtensionContext, AgentBeforeSettleEvent } from "@earendil-works/pi-coding-agent";

const ROOT = realpathSync(resolve(dirname(fileURLToPath(import.meta.url)), "../../.."));
const RUNNER = resolve(ROOT, "hooks/verifier-ready/run.sh");
const STATE_TYPE = "verifier-ready-hook-state";
const DEFAULT_LIMIT = 6;
const STATES = new Set(["no_report", "stale", "running", "review_invalid", "coverage_incomplete",
  "hard_fail", "inconsistent", "unanswered", "needs_human", "pass", "pass_with_exception"]);

type GateState = {
  code: string | null; max_blocks: number; status: string; gate: string; release_allowed: boolean;
  report?: string | null; failures?: string[];
  response?: { unanswered?: string[]; refuted_pending?: string[] };
  review?: { shards?: Record<string, { valid: boolean }> };
};
type SessionState = { session_id: string; modified: boolean; blocks: number; last_code: string | null };

function storedState(value: unknown, id: string): SessionState | undefined {
  if (typeof value !== "object" || value === null) return;
  const state = value as Partial<SessionState>;
  if (state.session_id === id && typeof state.modified === "boolean" && Number.isInteger(state.blocks) &&
      state.blocks! >= 0 && (state.last_code === null || typeof state.last_code === "string" && /^[a-f0-9]{64}$/.test(state.last_code))) {
    return { ...state } as SessionState;
  }
}

function inScope(path: unknown, cwd: string): boolean {
  if (typeof path !== "string") return false;
  // Match pi write/edit normalization: Unicode spaces, @, ~ and file URLs.
  path = path.replace(/[\u00A0\u2000-\u200A\u202F\u205F\u3000]/g, " ").replace(/^@/, "");
  if (path === "~") path = homedir();
  else if (path.startsWith("~/")) path = resolve(homedir(), path.slice(2));
  if (path.startsWith("file://")) path = fileURLToPath(path);
  const absolute = resolve(realpathSync(cwd), path);
  const name = relative(ROOT, existsSync(absolute) ? realpathSync(absolute) : absolute);
  if (isAbsolute(name) || name === ".." || name.startsWith(`..${sep}`)) return false;
  const parts = name.split(sep);
  return !parts.includes("__pycache__") && !name.endsWith(".pyc") &&
    (parts[0] === "impl" || parts[0] === "projects" && parts[1] === "llm_probe");
}

function instruction(gate: GateState): string {
  const command = `bash '${RUNNER.replaceAll("'", "'\\''")}'`;
  const out = gate.report ? ` --out '${gate.report.replaceAll("'", "'\\''")}'` : "";
  let action: string;
  switch (gate.status) {
    case "no_report": case "stale":
      action = `后台运行 ${command} --all，至少每 300 秒查看一次进度；新运行使用新目录。`; break;
    case "running":
      action = "门正在运行，等待完成；至少每 300 秒查看一次 progress/status，不再启动重复运行。"; break;
    case "review_invalid": case "coverage_incomplete": {
      const invalid = Object.entries(gate.review?.shards ?? {}).filter(([, value]) => !value.valid).map(([key]) => key);
      action = `重跑 ${command} --review${out}；需要重审的分片：${invalid.join(", ") || "见报告覆盖记录"}。`; break;
    }
    case "needs_human":
      action = `等待人工裁决：${gate.response?.refuted_pending?.join(", ") || "见 response.json"}。不得自行执行 adjudicate 或豁免。`; break;
    case "unanswered":
      action = `在 response.json 回应：${gate.response?.unanswered?.join(", ") || "见报告"}。fixed 必须新运行闭环；refuted 附原文反证并等待人工裁决。`; break;
    case "hard_fail": case "inconsistent":
      action = "按报告修复后新运行验证；不接受 finding 时写 refuted 与 call_id/原文反证，等待人工裁决。"; break;
    default:
      action = "门状态读取失败，检查错误及独立命令 --hook-status；不得把错误当成通过。";
  }
  return `verifier 完工门未通过（${gate.status}）。${gate.report ? `报告：${gate.report}。` : ""}\n${action}` +
    (gate.failures?.length ? `\n失败项：\n${gate.failures.map(item => `- ${item}`).join("\n")}` : "");
}

export default function verifierReady(pi: ExtensionAPI) {
  let session: SessionState | undefined;
  let lastLimit = DEFAULT_LIMIT;
  let persistenceError: string | undefined;

  async function probe(): Promise<GateState> {
    try {
      const result = await pi.exec("bash", [RUNNER, "--hook-status"], { timeout: 30000 });
      if (result.killed || ![0, 1].includes(result.code)) throw new Error(`status exit ${result.code}: ${result.stderr}`);
      const value = JSON.parse(result.stdout);
      const expectedGate = value.status === "pass" ? "PASS" : value.status === "pass_with_exception" ? "PASS_WITH_EXCEPTION" :
        value.status === "needs_human" ? "NEEDS_HUMAN" : "FAIL";
      if (!/^[a-f0-9]{64}$/.test(value.code) || !Number.isInteger(value.max_blocks) || value.max_blocks < 1 ||
          !STATES.has(value.status) || typeof value.release_allowed !== "boolean" || value.gate !== expectedGate ||
          value.release_allowed !== ["pass", "pass_with_exception"].includes(value.status) ||
          value.report != null && typeof value.report !== "string" ||
          value.failures !== undefined && (!Array.isArray(value.failures) || value.failures.some((item: unknown) => typeof item !== "string")) ||
          [value.response?.unanswered, value.response?.refuted_pending].some(items => items !== undefined &&
            (!Array.isArray(items) || items.some((item: unknown) => typeof item !== "string"))) ||
          value.review?.shards !== undefined && (value.review.shards === null || typeof value.review.shards !== "object" ||
            Object.values(value.review.shards).some((item: unknown) => !item || typeof (item as { valid?: unknown }).valid !== "boolean"))) {
        throw new Error("invalid hook status contract");
      }
      lastLimit = value.max_blocks;
      return value;
    } catch (error) {
      return { code: null, max_blocks: lastLimit, status: "error", gate: "FAIL", release_allowed: false,
        failures: [error instanceof Error ? error.message : String(error)] };
    }
  }

  function persist() {
    try { pi.appendEntry(STATE_TYPE, { ...session }); }
    catch (error) { persistenceError = `会话状态保存失败：${error instanceof Error ? error.message : String(error)}`; }
  }

  function observe(gate: GateState) {
    if (!session) return;
    if (gate.code !== null) {
      if (session.last_code !== null && session.last_code !== gate.code) session.modified = true;
      session.last_code = gate.code;
    }
  }

  async function initialize(ctx: ExtensionContext, gate: GateState) {
    const id = ctx.sessionManager.getSessionId();
    if (session?.session_id === id) return;
    const previous = [...ctx.sessionManager.getEntries()].reverse().find(entry => entry.type === "custom" &&
      entry.customType === STATE_TYPE && storedState(entry.data, id));
    session = (previous?.type === "custom" ? storedState(previous.data, id) : undefined) ??
      { session_id: id, modified: false, blocks: 0, last_code: gate.code };
    observe(gate);
    persist();
  }

  pi.on("session_start", async (_event, ctx) => {
    session = undefined;
    persistenceError = undefined;
    await initialize(ctx, await probe());
  });

  // Comparing actual content catches bash/custom tool mutations without guessing command text.
  pi.on("tool_result", async (event, ctx) => {
    const gate = await probe();
    await initialize(ctx, gate);
    if ((event.toolName === "write" || event.toolName === "edit") && !event.isError && inScope(event.input.path, ctx.cwd)) {
      session!.modified = true;
    }
    observe(gate);
    // Unknown content after a non-read tool cannot establish an unchanged code scope.
    if (gate.code === null && !["read", "grep", "find", "ls"].includes(event.toolName)) session!.modified = true;
    persist();
  });

  pi.on("agent_before_settle", async (event: AgentBeforeSettleEvent, ctx) => {
    // The final assistant message normally cannot continue yet. Our custom_message
    // creates runnable context; pi validates eligibility after applying the drafts.
    if (event.outcome !== "completed") return;
    let gate = await probe();
    await initialize(ctx, gate);
    observe(gate);
    persist();
    if (persistenceError) gate = { ...gate, status: "error", gate: "FAIL", release_allowed: false,
      failures: [...(gate.failures ?? []), persistenceError] };
    if (!session!.modified || gate.release_allowed) return;
    const capped = session!.blocks >= gate.max_blocks;
    const content = capped ? `${instruction(gate)}\n门未通过，已达拦截上限（${gate.max_blocks} 次），本次不再要求继续。` : instruction(gate);
    if (!capped) { session!.blocks += 1; persist(); }
    return { entries: [...event.entries, { type: "custom_message" as const, customType: "verifier-ready-gate",
      content, display: true, details: { status: gate.status, blocks: session!.blocks, capped } }],
      continue: capped ? event.continue : true };
  });
}
