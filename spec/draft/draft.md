修订版：纯 draft 骨架（角色无关、协议无关）

阶段 0：config 初始化

project_id: "<project>"
objective: |                  # 本轮 draft 要改什么
...
mock_source: "<path>"         # 冻结评测数据来源
material:                     # 项目知识来源
- path: "..."
    note: "..."
mock_frozen: true
review: |
...
max_iterations: 5
report_path: "impl/projects/<project>/draft/<role>_comparison_report.md"
# 角色特异扩展字段从角色层补

阶段 1：material 收集（独立于 mock）

按 config 的 material 字段读项目源码/配置/文档/<role>_boundary-template.md/现有 adapter/tool/schema，建立项目知识。

产出：draft 对项目的理解，不进 case。约束：只读不改。

阶段 2：mock 数据构建/加载（独立于 material）

加载 mock_source，构建冻结的评测 case。

case 契约（draft 机制只定这三条）：

1. case 装的是"跑一次 draft 所需的全部入参"——具体字段由当前 ProjectXxx 的模板方法签名 + 扩展点签名派生，draft 不预判字段名。
2. case 必须带"期望"——对比 current vs draft 时判断哪边对，"期望"形态由角色/项目定（reference / expected_intent / 业务标注 / expected_check 都行）。
3. case 冻结，loop 中不改，要改必须用户明确更新 config。

阶段 3：draft 实现（按当前协议规范）

draft 实现落在 impl/projects/<project>/draft/<role>.py，继承 ProjectXxx：

from impl.core.<role>_protocol import ProjectXxx

class DraftXxx(ProjectXxx):
    """Draft 版的项目层实现。"""

    # 实现当前协议要求的所有 @abstractmethod（具体哪些由 *_protocol.py 决定）
    def build_context(self, ...):
        return {
            "system_prompt_override": """...""",
            "user_prompt_extras": {...},
            "tools": [...],  # 可选
        }

    # 可选覆盖的扩展点按需覆盖
    ...

协议约束（draft 机制只定这三条硬约束，不预判扩展点清单）：

1. 继承 ProjectXxx，不另写函数式入口。
2. 不覆盖模板方法（@final）和内部方法（_ 前缀）——协议层 _FORBIDDEN_OVERRIDES + __init_subclass__ 已经硬约束，draft 自然受约束。
3. 实现当前协议要求的所有 @abstractmethod——清单由当前 *_protocol.py 决定，draft 不预判。

tool 接入（attribute/judge 都可能用，按效果定）：

- draft 在 build_context 返回的 tools 里挂项目特异 tool（来自 impl/projects/<project>/draft/tools/）。
- tool 经统一 ToolRegistry + ToolOrchestrator + agno 桥接，不经项目 adapter 中转。
- 角色特异的 tool 边界（如 judge 默认屏蔽内部代码信息）由角色层定，draft 机制不规定。

阶段 4：自检

- draft 实现继承 ProjectXxx，未覆盖模板方法/内部方法（__init_subclass__ 检查通过）。
- 当前协议要求的所有 @abstractmethod 都实现了。
- 入口签名（模板方法）和正式版一致——loader 切换无感。
- 无 case id / 样本序号 / 当前样本专属数值硬编码。
- 不伪造强度——证据不足时按角色规则标（attribute: none/weak；judge: not_evaluable），不伪造 strong / 不假装判断得了。
- fulfilled case 不被强行失败。
- tool（如有）经 ToolRegistry + agno 桥接，不经项目 adapter 中转。
- draft 落在 draft/，loader 默认不加载。
- 已做 compile/import + 局部 probe 或 targeted run。

阶段 5：current vs draft 对比

同一批冻结 case，current（正式版 ProjectXxx 实现）和 draft 各跑一遍，比"证据质量 / 链路定位 / 不过拟合 / 不伪造"，不比刷分。

对比逻辑骨架（角色特异的是 _result_summary 抽取的字段——由角色层根据当前 XxxResult schema 定）：

def compare_<role>_outputs(spec, adapter, cases, current_impl, draft_impl):
    rows = []
    for case in cases:
        current_out = _result_summary(_run_<role>(current_impl, spec, adapter, case))
        draft_out = _result_summary(_run_<role>(draft_impl, spec, adapter, case))
        rows.append({
            "case_key": case.get("case_key"),
            "case_status": _case_status(case),  # 角色特异，从 case 里取状态字段
            "current": current_out,
            "draft": draft_out,
            "quality_notes": _quality_notes(current_out, draft_out),
        })
    return {
        "case_count": len(rows),
        "rows": rows,
        "decision_rule": "Promote only when draft improves evidence quality / link localization without overfit or inflated strength.",
    }

_run_<role> 怎么从 case 取参数喂给模板方法、_result_summary 抽哪些字段、_case_status 从 case 取什么——这三处角色特异，由角色层根据当前协议签名 + schema
定。draft 机制不预判。

阶段 6：loop 迭代 / promotion

读 config → 收集 material → 构建冻结 mock → 生成 draft 实现
    → 自检通过？
        → 否：修 draft，回到自检
        → 是：current vs draft 对比
            → draft 更优？
                → 是：出对比报告 + promotion checklist，等用户确认
                → 否：用户用 prompt 调整需求 → 修 draft/tool → 回到对比
    → 达 max_iterations 还没更优？
        → 记录 blocker，出报告，不 promotion
        
promotion checklist：

- draft 类可 import，继承 ProjectXxx。
- 当前协议要求的所有 @abstractmethod 实现完整。
- 代表 case 的 targeted run 通过。
- mock 对比报告显示 draft 优于或不弱于 current。
- 不伪造强度 / 不强判。
- production loader 不加载 draft。
- 人工确认后才 promotion：搬移 draft/<role>.py → <role>.py，project.yaml 关掉 *_draft.enabled。

阶段 7（可选）：一次性结论

draft 跑对比时顺带产出当前 case 的一次性结论作为"效果预览"，不等同 promotion。

---
draft 机制角色无关的部分 vs 角色特异部分（重新划清）

draft 机制本身（角色无关，公共层写死）：

- 7 个阶段流程。
- config 字段骨架（project_id / objective / mock_source / material / mock_frozen / review / max_iterations / report_path）。
- 三条硬约束：继承 ProjectXxx、不覆盖模板方法/内部方法、实现当前协议所有 @abstractmethod。
- 三条 case 契约：装全部入参、带期望、冻结。
- decision_rule：比证据质量/链路定位/不过拟合/不伪造，不比刷分。
- promotion 必须人工确认。

角色特异部分（角色层填，draft 机制不预判）：

- case 具体字段（从当前 ProjectXxx 模板方法签名 + 扩展点签名派生）。
- _run_<role> 怎么从 case 取参喂给模板方法。
- _result_summary 抽哪些字段（从当前 XxxResult schema 派生）。
- _case_status 从 case 取什么状态字段。
- 角色特异的 tool 边界（如 judge 默认屏蔽内部代码）。
- 角色特异的"伪造强度"判定（attribute: 伪造 strong；judge: 伪造 fulfilled/not_fulfilled）。

---
一个新问题想确认

既然 case 结构和扩展点清单都"由当前协议派生、draft 不预判"，那 draft skill 在执行阶段 2/3 时，怎么知道当前协议长什么样？

我理解是：draft skill 在跑的时候，先读 impl/core/<role>_protocol.py——动态发现 ProjectXxx 的方法表（哪些是 @abstractmethod、哪些是 @final、哪些是 _
前缀、模板方法签名是什么）。draft skill 不靠"自己脑子里记的扩展点清单"，靠"读当前协议文件"。

这意味着 draft skill 要有一段"协议自省"逻辑——读 *_protocol.py，提取 ProjectXxx 的方法签名和扩展点清单。这段逻辑本身是 draft
机制的一部分（角色无关），但提取出来的结果是角色特异的。

这个理解对吗？还是你期望 draft 实现者（人或 AI）自己去读协议、draft skill 不做自省？你指点。




这个理解对的，就是你说的那样