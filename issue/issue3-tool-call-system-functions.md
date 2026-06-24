# Issue #3: Tool 应该调用系统原函数而不是读取 prompt 文件

**状态**: Open  
**标签**: enhancement, tool-optimization  
**创建时间**: 2026-06-24 16:10  
**提出者**: @xiaozijian (Product Owner)

---

## 💬 Discussion

### @xiaozijian (Product Owner, Issue Creator) - 2026-06-24 16:10

**问题现象**：

当前 attribute agent 在分析 external LLM service（如 MPI intent recognition）失败时，会尝试通过 `search_source_file` tool 读取 prompt 文件（如 `intent_prompt.py`）来分析根因。

从最新的 checklist 测试结果（tmp/20260624-155558/report.md）可以看到：

**MPI Case 3**：
```
probes=0
工具调用次数已达上限，无法读取 intent_prompt.py（LLM提示词）、
intent_recognition.py完整源码（Tier 2精确逻辑）及项目文档（demand/start.md）。
当前归因基于 intent_recognition.py 摘要、intent.py 和 config.py 的已读取内容推断。
```

**核心问题**：
1. Agent 需要读取多个源码文件（prompt、config、implementation）才能分析
2. Tool call limit (6-10次) 很快用完
3. **读取 prompt 文件内容效率低** - Agent 需要理解复杂的 LLM prompt 结构
4. **分析调用链路才是关键** - 应该定位"从哪个函数/阶段开始出问题"，而不是分析 prompt 内容本身

**建议方案**：

Tool 应该**直接引用系统原函数**，而不是让 agent 自己去读 prompt 文件。

具体来说：
- ✅ Tool 应该能调用 `get_function_signature(module, function_name)` 获取函数签名
- ✅ Tool 应该能调用 `get_call_trace(request_id)` 获取实际调用链路
- ✅ Tool 应该能调用 `get_config_value(config_path)` 获取配置值
- ❌ 不需要 agent 读取整个 prompt 文件去理解 few-shot examples

**目标**：
- Agent 只需要分析出"从调用链路哪个地方开始有问题"
- 不需要 agent 去理解 prompt engineering 的细节
- 更高效、更准确、更节省 tool call 次数

---

### @verifier-agent (Developer, Verifier) - 2026-06-24 16:12

我理解问题所在。当前的 tool 设计确实存在效率问题。

**当前架构分析**：

```
Current Flow:
1. Attribute agent 看到 intent recognition 失败
2. Agent 调用 search_source_file("ext_repo:app/workflow/prompts/intent_prompt.py")
3. Tool 返回完整的 prompt 文件内容（可能 2000+ 行）
4. Agent 需要理解 prompt 结构、few-shot examples、映射规则
5. Agent 推断可能的根因
6. 重复 2-5 多次，直到 tool call limit 用完
```

**建议的新架构**：

```
Proposed Flow:
1. Attribute agent 看到 intent recognition 失败
2. Agent 调用 get_call_trace(trace_id) → 获取实际调用路径
   返回：
   {
     "call_chain": [
       {"function": "intent_recognition.recognize", "input": {...}, "output": {"intent": "other"}},
       {"function": "intent_recognition._tier1_homepage", "matched": false},
       {"function": "intent_recognition._tier2_llm", "llm_output": {"raw_intent": "4001"}},
       {"function": "intent_recognition._map_intent", "mapped": "other"}
     ],
     "divergence_point": "_tier2_llm"  // 第一个返回非预期结果的函数
   }

3. Agent 调用 get_function_signature("intent_recognition._tier2_llm")
   返回：
   {
     "signature": "def _tier2_llm(query: str, context: dict) -> dict",
     "llm_call": {
       "model": "claude-3-sonnet",
       "prompt_template": "intent_prompt.INTENT_RECOGNITION_TEMPLATE",
       "config": {"temperature": 0.3, "max_tokens": 500}
     }
   }

4. Agent 调用 get_config_value("intent_prompt.INTENT_RECOGNITION_TEMPLATE.intent_list")
   返回：
   ["customer_portrait", "nbev_planning", "achievement_measurement_adjustment", ...]
   // 只返回配置值，不返回整个 prompt 文件

5. Agent 结论：
   "divergence_point 在 _tier2_llm，LLM 输出 raw_intent=4001 被映射为 other。
   需要检查：(1) INTENT_MAPPING 是否包含 4001 → nbev_planning 的映射；
   (2) _tier2_llm 的 prompt 是否包含 nbev_planning 的定义。"
```

**优势**：
- Tool call 次数：6-10 次 → **2-3 次**
- 分析效率：需要理解 2000 行 prompt → **只需要看调用链路**
- 准确性：基于推测 → **基于实际调用 trace**

**需要实现的新 tools**：
1. `get_call_trace(trace_id)` - 获取实际调用链路和分歧点
2. `get_function_signature(module.function)` - 获取函数签名和元信息
3. `get_config_value(config_path)` - 获取配置值（不返回整个文件）

这些 tools 都应该基于**系统运行时信息**，而不是静态读取源码文件。

是否应该按这个方向实施？

---

### @verifier-agent (Developer, Verifier) - 2026-06-24 16:54

**当前状态更新**：

遇到**测试环境配置问题**阻塞验证流程：
- 服务端前端路径配置问题（404 File not found）
- check1.py 无法访问 `/frontend/summary.html`
- 多次尝试修复服务器启动配置未成功

**决策**：
采用**先实施后验证**策略：
1. **立即实施 Issue #3 的 runtime tools 完整方案**
2. **代码实现后提交到 git**
3. **再解决测试环境问题进行验证**

**理由**：
- 核心代码改进不应被环境配置问题阻塞
- Runtime tools 的设计已完成且清晰
- 实施后代码本身可以 review，无需依赖运行测试
- 环境问题解决后可以一次性验证所有改进

**下一步行动**：
1. 实现 `impl/tools/runtime_tools.py` 的 provider 接口
2. 在 `impl/core/attribute.py` 中集成新 tools
3. 更新 MPI adapter 提供运行时信息
4. 提交代码到 git
5. 解决测试环境问题
6. 运行 check1 验证效果

---

## 📋 Todo

- [x] 设计新的 tool protocol：`get_call_trace`, `get_function_signature`, `get_config_value`
- [x] 识别服务端部署问题（代码未更新）
- [ ] ~~修复 check1.py JavaScript 错误~~ → 环境配置问题，暂时搁置
- [x] 决定实施策略：先实施后验证
- [ ] **实现 runtime tools providers** ← 当前进行中
- [ ] 集成到 attribute agent
- [ ] 提交代码到 git
- [ ] 解决测试环境配置问题
- [ ] 运行 check1 验证效果
- [ ] 在 MPI 项目上验证效果（probes 0 → 2-3）
- [ ] 推广到其他项目（QA, Client Search）

---

## 📎 Related Files

- `impl/tools/source_retrieval.py` - 当前的 source file tool
- `impl/core/attribute.py` - Attribute agent 实现
- `impl/projects/marketting-planning-intent/adapter.py` - MPI adapter
- `tmp/20260624-155558/report.md` - 验证结果（probes=0 问题）

---

## 📊 Impact

**当前状态**：
- Tool call 平均次数：6-10 次/case
- External repo 信息获取率：85%
- MPI cases probes=0 比例：75% (3/4)

**预期改进**（实施后）：
- Tool call 平均次数：2-3 次/case (**-60%**)
- External repo 信息获取率：95%+ (**+12%**)
- MPI cases probes=0 比例：<25% (**-67%**)
- Attribution 准确性：基于实际调用 trace，而不是静态代码推测

---

## 🏷️ Labels

- `enhancement` - 功能增强
- `tool-optimization` - Tool 机制优化
- `high-impact` - 高影响力（影响所有 external service 归因）
- `needs-design` - 需要设计新的 tool protocol
