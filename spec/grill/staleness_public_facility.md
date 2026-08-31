# 业务源漂移处理公共设施（Grilling 会话共识）

- 状态：设计共识已达成（2026-08-08/09，Q1–Q25），待按 §8 顺序实施。
- 范围：Core 公共设施，统一实现，项目无关。首个落地项目为 `client_search`；检测/警告能力对所有项目生效，写操作先在 `client_search` opt-in。
- 定位：业务源码经常变化是既定事实。评测系统不得因任意业务源变化而整体重新调查；重新调查本身的变化与不稳定性是隐含风险和成本。本设施把"变化 → 影响判定 → 处置"变成确定性、可增量、可审计的流程。
- 关联协议：`spec/grill/context_governance.md`、`docs/superpowers/specs/2026-08-06-investigation-staleness-policy-design.md`（strict/warn 策略的直接扩展与完成）。与 context_governance.md §12"先 client_search 后沉淀 Core"已协解（2026-08-09）：本设施按 §1 范围声明的例外条款直接 Core 化，`client_search` 为首个 opt-in 落地项目。

---

## 1. 核心立场

1. 业务代码经常变化必须被接受为常态，不是异常。
2. "重新调查"是昂贵且自带不稳定性的操作，只应发生在确实必要时，且范围必须最小化。
3. Reference 本来就不保证正确；一切以新资料为准，不纠缠新旧哪个对。
4. 本设施是 Core 公共资产，不为单个项目特判；后续优化在公共设施内进行。

---

## 2. 边界模型：按消费方式路由

变化是否"有影响"，不靠人工枚举哪类 diff 无害，而由**消费方式**决定。每个源文件的消费者必须登记消费模式；未登记消费方的文件变化，保守视为有影响。

| 消费模式 | 含义 | 例子 | 处置 |
|---|---|---|---|
| `key_live` | 按稳定 key 实时消费，runtime 拿新的就是 | `field_tools.py` 按字段名查、`capability_manifest.py` 全量重算 | 自动吸收：重钉 hash + 审计，不阻断不重查 |
| `positional_frozen` | 按位置/投影冻结消费 | planfullname `values[0:99]` 分块、embedding receipt 输入投影、key-index 条目 `search_text` | 整代重建（确定性机器流程），引用不跨代 |
| `frozen_conclusion` | 对资料内容的冻结判断被 runtime 消费 | material decisions | 定点重验证（Harness 复核该结论） |

原则：**变换旧了就重算，判断旧了才重查；重算还能顺便指出哪些判断该重查。**

- 位置型引用的单元 id 按位置生成、内容却从当前文件重物化，因此内容漂移会导致地址错位。位置型资产以"代（generation）"为单位，用输入 hash 标识整代；源变化后要么整代原子重建、要么门禁挡住，**引用永不跨代解析**。错误内容只要可能出现，整个位置空间都视为受影响（因此位置型漂移选择整体阻断而非部分降级）。
- 位置型重建是本地确定性机器流程，实际形态是"检测漂移 → 立即重建整代 → 继续运行"，阻断窗口只在重建失败或缺外部授权时存在。
- 升级条件：只有当重建结果与某条冻结结论冲突时，才从前两档升级为定点重验证。

---

## 3. 检测与判定

1. 检测粒度为切片级：调查冻结时把每条 EvidenceRef 的切片 hash 清单写入 manifest（当前 schema 无此字段，需扩展）。旧格式 manifest 退化为文件级检测；`client_search` 重新冻结一次补齐切片 hash。
2. 生成责任：切片 hash 由 investigation 冻结工具写入（谁冻结谁负责），solidify 只消费。
3. strict 与 warn 共用同一个边界函数，只是处置不同：
   - `warn`：记录漂移继续（运行期统一档位：Draft 与 Production 的 case 运行、调查校验脚本都是 warn，业务源小改不打死无关 case）；
   - `strict`：必须"变化被派生比对证明无影响，或已完成定点重验证并重钉 revision"后才放行（Solidify/Promotion/config_check 审计）。
4. strict 门禁要求先把源提交、再重钉 revision，消除工作区噪声误触发（当前全部漂移均为未提交工作区改动）。
5. 自动刷新必须是单个确定性原子操作：更新 manifest hash →（如需要）重建派生产物 → 写审计记录，不允许中间态。validation receipt 以结构指纹（剔除 hash/revision pin 后的 manifest 结构 sha256）为身份，absorb 重钉不作废收据；只有结构性改动（refs/tools/artifacts 变化）或工具字节变化才要求重发收据。
6. 自动吸收的保守约束：某 ref 只要被任何**无依赖键**的 material decision 引用，其漂移就不走自动吸收，该 decision 保守地必须重验证。v1 的 decision 是自由文本、无依赖键；新增 decision 必须写结构化依赖键（描述的 slice_key/字段键），之后才能精确命中"只重验证描述了被改切片的 decision"。
7. 漂移检测/记录属于确定性验证（hash 比对、机器可复验），不做业务材料充分性判断；与 context_governance.md §3.2"Runtime 只做确定性验证"边界一致（2026-08-09 协解确认）。
8. 大材料门禁：任何业务源材料全量超过阈值（默认 30k 字符）且未在 manifest 登记检索通道（`metadata.consumption` 的 `key_live`/`positional_frozen`）时，禁止整块注入 Runtime 上下文；调查层必须先补 key-index/切片再消费。`source_staleness_cli report-large-materials` 确定性报告该缺口，并扫描 `project.yaml` 声明的全部业务源（未登记进 manifest 的大文件同样报出，避免门禁盲区）。这是对 context_governance.md §6.2"Runtime 只加载已登记 segment"的落地约束。已落地：`enhanced-rules`（全量 40 万字符）按 field 建成 key-index（`impl/projects/client_search/draft/enhanced_rules_key_index.py`），Draft Judge 按键检索消费（key_live），不再整块/截断注入。

---

## 4. 增量流程（五步）

增量性来自两个基础设施：**切片级 hash 清单**（知道哪里变了）+ **依赖键/引用图**（知道变化碰了谁）。

1. **定位**：对切片型 ref，用新文件重物化切片，逐切片比对冻结 hash 清单，得到精确变化集（如 `field=license_plate_no` 等 3 个切片变化，其余不变）。未切片 ref 整文件算变。
2. **分流**：按每条 ref 登记的消费模式路由；`key_live` 消费方无需动作。
3. **投影**：确定性计算受影响清单——变化切片 → 寻址这些切片的 key-index 条目（`evidence-navigation://ref/locator`）→ 引用该 ref 的 material decisions（有依赖键按键命中，无键保守全中）→ 输入投影变化的 embedding 条目。
4. **分档执行**：
   - 档 A（机器）：纯 `key_live` 且无 decision 牵涉 → 原子重钉 hash + 审计（收据以结构指纹为身份，无需重发）；
   - 档 B（机器）：位置型资产 → 整代重建（重分块、重生成导航条目、按条目内容 hash 键控只重嵌变化条目），新代 ID，引用不跨代；
   - 档 C（Harness）：只对投影命中的 decision 定点重验证——读"decision 原文 + 被改切片"，判定仍成立/更新/作废。不是重查项目，是复核几条结论。
5. **收口**：全部闭环后重钉 hash、（strict 场景）要求源已提交并重钉 revision、写全局审计账本，门禁重跑通过。

最坏情况退化到"整条 ref 的 decision 重验证"，永不退化到全项目重调查。

---

## 5. 门禁语义

- 运行期（Draft 与 Production 的 case 运行、调查校验脚本）：漂移只记录不阻断（warn）；位置型漂移触发整代重建，重建后继续。
- Solidify/Promotion/config_check 审计：strict；被引用文件的所有变化必须"证明无影响"或"完成定点重验证并重钉 revision"。
- 位置型资产漂移在 warn 下也整体阻断该位置空间，直到整代重建完成（错误内容一旦出现可能波及所有位置，不做部分降级）。
- 未登记消费方的文件变化：fail-closed，视为有影响。

---

## 6. embedding 与 Key-Index

- embedding receipt 改为按条目内容 hash 键控：只重嵌变化条目，receipt 记录逐条 hash（替代当前整体 `input_sha256` 失效）。
- key-index 条目（`search_text`、导航 locator）随其源切片变化确定性重建；重建是资产刷新，不是业务重调查。
- 位置型 key-index（如 planfullname 分块）以"代"为单位整体重建。

---

## 7. 可观测性

- warn 策略下的漂移 warnings 除进入 iteration report / receipt 的 `runtime_staleness` 外，同时写入 context-governance 全局审计账本（`global-context-audit-*.json`），形成漂移趋势，供 Harness 周期性审查，也作为"重新调查成本"的可观测数据。
- 每次自动刷新/整代重建/定点重验证均写审计记录（含 before/after hash、受影响清单、执行档位）。

---

## 8. 实施顺序

1. 把已批准的 warn 策略接入 `build_authority_environment`（最小改动，先让 Draft 实验不被工作区噪声挡住）。
2. manifest 切片 hash 持久化 + `client_search` 重新冻结补齐。
3. 消费模式登记 + `key_live` 自动吸收 + 原子刷新协议。
4. 条目级键控 embedding 重建 + 位置资产整代重建（引用不跨代）。
5. 受影响资产投影（diff → 切片 → 条目/decision 清单）。

---

## 9. 生效范围与迁移

- 检测/警告（只读、不改行为）立即对所有项目通用（staleness policy 本即 core-generic）。
- 自动刷新、整代重建等写操作先在 `client_search` opt-in，验证后推广。
- 旧 manifest 无切片 hash 时退化为文件级检测，不强制全量迁移。

---

## 10. 明确搁置

- 外部数据发送授权（刷新 embedding、跑 API contract 测试）：仍需用户显式批准。
- planfullname 类位置资产的稳定键设计（按值寻址/内容分块）：属调查层设计选择，不属本设施。

---

## 11. 设计摘要

```text
变化检测：切片级 hash 清单，定位"哪里变了"
影响判定：按消费方式路由，未登记消费 fail-closed
处置分档：
  key_live          → 自动吸收（重钉 hash）
  positional_frozen → 整代重建（引用不跨代）
  frozen_conclusion → 定点重验证（只复核受影响结论）
门禁：strict/warn 同一边界函数，两种处置
审计：漂移、刷新、重建、重验证全部留痕，进全局账本
```

最终判定标准：

> 业务源的常见变化不再触发整体重新调查；变化被确定性定位、按消费方式分流、以最小代价处置，且全过程可审计。
