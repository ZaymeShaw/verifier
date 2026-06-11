# 20260610 client_search 下游搜索边界审核报告

## 背景

`projects/client_search/judge_boundary-template.md` 更新后，client_search 的 judge 目标从单纯检查 parser 条件形态，明确扩展为判断 parser 是否能从依赖 ES/客户搜索能力中查到用户想要的客户。按 `check.md` 要求，本次不仅检查输出文档，也检查产生机制：adapter trace、downstream probe、judge boundary、attribute/check 协议是否一致。

## 机制调整

1. `impl/projects/client_search/project.yaml`
   - 新增项目级 `application.downstream_search` 配置：
     - `base_url: http://localhost:8081`
     - `endpoint: /api/v1/search/customer`
     - `method: POST`
     - `timeout: 3`
   - 下游端口和接口仅保留在 client_search 项目配置中，没有写入 generic core。

2. `impl/projects/client_search/adapter.py`
   - 在 `to_run_trace()` 中基于 parser 返回的 `conditions` / `query_logic` 构造下游搜索 payload。
   - 尝试调用 `POST http://localhost:8081/api/v1/search/customer`。
   - 将结果写入：
     - `RunTrace.project_fields.downstream_search`
     - `execution_trace` 的 `client_search.downstream_search` stage
   - 当 8081 不可用时，保留 `status=unavailable`、请求 payload 和错误信息。
   - 在 `normalize_judge_result()` 中补充：
     - `quality_flags += downstream_search_unavailable`
     - `boundary_decision.downstream_search_status`
     - `boundary_decision.result_set_verified=false`
     - downstream evidence
     - reasoning 中明确下游搜索状态不可用时，verdict 必须基于 parser 条件与 ES 查询语义等价性判断，不能声称已验证 ES 实际结果集。
   - 当下游搜索成功时，标记 `downstream_search_verified` 和 `result_set_verified=true`，供 judge 使用真实结果集证据。

3. `impl/projects/client_search/judge_boundary_protocals.md`
   - 明确 ES/下游客户搜索证据是核心依据。
   - `prompt.md` / `config.md` 是辅助参考。
   - 下游不可用时不能声称结果集已验证。
   - 下游不可用时仍必须依据 parser 条件、ES 查询语法、字段语义、操作符语义、枚举能力和业务意图判断搜索语义是否等价；不能退化成机械 prompt/config 字段形态比对或自动 `uncertain`。
   - 搜索语义或结果集等价时，可以接受条件中间形态差异。

4. `impl/projects/client_search/judge.md`
   - Judge 目标改为“能否在依赖 ES/客户搜索能力内检索到目标客户集合”。
   - 新增下游搜索状态判定步骤。
   - 区分 ES 查询语义等价判断与实际结果集验证；下游不可用时仍可基于语义证据给出 correct/incorrect，但必须标记结果集未验证。

5. `impl/projects/client_search/evaluation.md` / `checklist.md`
   - 补充 `project_fields.downstream_search`、`client_search.downstream_search` trace stage、`result_set_verified`、`requires_es_query_equivalence_judgment` 的检查要求。
   - 强调 generic core 不应硬编码 client_search 字段、端口或 case。

## 验证

### 静态验证

```bash
python -m compileall -q impl
python -m impl.cli projects
```

结果：通过，项目列表包含 `QA` 和 `client_search`。

### live run 验证

执行 client_search 单条 live run：

```python
from impl.core import pipeline
case = {'id':'boundary-probe-1','input': {'query': '45岁女性保费10万以上'}}
res = pipeline.run_chain('client_search', case, mock=False)
```

关键结果：

```json
{
  "downstream": {
    "status": "unavailable",
    "url": "http://localhost:8081/api/v1/search/customer",
    "payload": {
      "header": {"agent_id": "eval-user", "page": 1, "size": 20},
      "query_logic": "AND",
      "conditions": [
        {"field": "clientAge", "operator": "RANGE", "value": {"min": 45, "max": 45}},
        {"field": "clientSex", "operator": "MATCH", "value": "女"},
        {"field": "annPremSegNum", "operator": "GTE", "value": 100000}
      ]
    },
    "error": "Remote end closed connection without response"
  },
  "judge_verdict": "correct",
  "judge_flags": ["downstream_search_unavailable", "result_set_not_verified"],
  "boundary_decision": {
    "downstream_search_status": "unavailable",
    "result_set_verified": false,
    "requires_es_query_equivalence_judgment": true
  }
}
```

说明：parser 条件语义正确，但 8081 下游客户搜索不可用，因此 judge 明确标记结果集未验证；同时按最新边界要求继续基于字段语义、操作符语义、枚举能力和 ES 查询语法判断该 payload 与用户意图是否等价，没有退化为机械字段形态比对或自动 `uncertain`。

## check.md 审核 checklist

- [x] 机制源头检查：确认新增逻辑从 parser output 构造下游 payload，而不是只改 judge 文案。
- [x] 协议一致性：下游搜索证据进入 `RunTrace.project_fields`、`execution_trace`、`JudgeResult.evidence` / `boundary_decision`，仍走统一 `run_chain -> judge -> attribute -> check` 链路。
- [x] 项目边界清晰：8081 endpoint、payload 构造和 client_search 字段只在 client_search adapter/project docs 中，generic core 未硬编码。
- [x] 不伪装验证：下游不可用时 `result_set_verified=false`，reasoning 明确未验证 ES 实际结果集。
- [x] 下游不可用等价判断：实现和文档要求 judge 仍基于 parser 条件、字段/操作符/枚举语义和 ES 查询语法判断搜索语义等价，不自动 `uncertain`。
- [x] 等价查询原则：文档已允许在 ES 查询语义或结果集等价时接受与 prompt/config 中间形态不同的表达。
- [x] 避免过拟合：实现基于 parser 返回的通用 `conditions/query_logic` 构造 payload，不绑定固定 case。
- [x] 可追踪性：trace stage 保留下游 URL、payload、结果或错误，便于后续恢复 8081 后复核。

## 结论

本次修改已将更新后的 client_search judge boundary 接入 impl：有下游搜索结果时可用真实结果集证据判定；没有 8081/ES 接口时必须标记 ES 实际结果集未验证，但仍要基于当前 parser 条件和 ES 查询语义做等价判断，只有证据不足时才返回 `uncertain`。
