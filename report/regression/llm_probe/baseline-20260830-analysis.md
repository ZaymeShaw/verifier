# llm_probe 判定基线分析（2026-08-30）

采集脚本：`run_baseline.py`（live → judge → 轴2 carrier，不跑 attribute）。
数据：`baseline-20260830.json`，16 case（client_search×6 / policy_search×3 / mpi×7），
代码为改造前版本（judge 无 output_text_parsed、carrier reasoning_effort=low、无检索式消费），
数据为当时的 capability_map（client_search boundary = {material://llm_probe/name_exact}，其余无 boundary）。

## 总体分布

| 指标 | 数值 |
|---|---|
| overall fulfilled / not_fulfilled / not_evaluable | 6 / 10 / 0 |
| 条目级 not_evaluable | 2（均为非 blocking） |
| 轴2归位 | 全部「说不清」（16 条 placement，0 做错了 / 0 做不了） |
| 轴2归位失败（errors） | 0 |

## badcase 清单（期望判定 vs 实际）

| # | case | 现象 | 期望的正确判定 | 归因分类 |
|---|---|---|---|---|
| B1 | client_search-name | 轴1条目 NE「不支持表述明确说明能力边界」 | 该期望不应被派生（能力描述未含此职责时）或不判 NE | 期望派生越界：capability 文本里的「不支持的表述应明确拒绝」是轴2体裁，漏进轴1 e |
| B2 | mpi-customer-portrait | 轴1条目 NE「不生成 SSE 卡片」 | 同上 | 同 B1（「不进入多轮规划、不生成 SSE 卡片」写在 capability 里） |
| B3 | client_search-name | 轴2「说不清/口径分歧」 | 做错了（全名等值在能力空间内，实际走了 prefix） | 轴2体裁不匹配：boundary 引的 name_exact 是解析规则片段，非边界陈述；effort=low |
| B4 | client_search-unsupported | 轴2「说不清/空间未受治理」 | 做不了（家庭结构俗语不在字段空间）——前提是 boundary 覆盖字段空间 | 供给缺口：boundary 未覆盖「哪些维度可搜」；大资料（field_definitions_args 327k）超预算无法引用 |
| B5 | 其余 9 条 placement | 「说不清/空间未受治理」 | 符合协议（预设未填 boundary），非误判；但反映 boundary 供给成本高 | 供给缺口 |

## 验证的诊断假设

1. **轴2语义漏进轴1**（B1/B2）：两条 NE 全部来自 capability 文本里的边界语句派生的期望。判后承载性问题被轴1用 NE 兜住 → 体裁分工（capability 只写职责，边界移到 boundary）可消除。
2. **轴2资料体裁不匹配**（B3）：用户引对了资料（name_exact 含全名保留规则），LLM 仍判「口径分歧」——解析规则体裁需要 LLM 反推能力空间，间接易错。
3. **大资料硬矛盾**（B4）：真正的能力空间资料 field_definitions_args 327,651 字符 > 50k 预算，引用即报错，用户被迫手剪片段 → 检索式消费解决。
4. **judge 证据可读性**：本批未直接造成 overall NE，但 output_text 是转义 JSON 串，structured-output enforce 重试频发（见运行日志），是延迟与不稳定来源。

## 改动后的验收口径

重跑 `run_baseline.py --only llm-probe-client_search-name,llm-probe-client_search-unsupported,llm-probe-mpi-customer-portrait`：

- B1/B2：不再派生边界体裁期望，条目级 NE 消失；
- B3：轴2判「做错了」，citations 带 material uri + Lx-Ly 行定位，placement 带 tool_trail；
- B4：boundary 直接引用 327k 的 field_definitions_args（自动转检索目录），轴2判「做不了」并引用字段空间依据；
- 其余 case 判定不回退（fulfilled 保持 fulfilled）。

## 验收结果（同日，after-phase123 / after-phase123-v2）

第一轮 after 跑出一个新问题：NE 收紧文案里「能力描述没写的要求不存在」把**输入字面语义**也压掉了，
张伟 case 轴1错判 fulfilled（prefix 放大语义未被追责）。修正为「期望来自能力描述职责 + 输入字面语义，
语义放大/缩小即 not_fulfilled」，见 `after-phase123-v2-20260830.json`：

| badcase | 基线 | 验收结果 |
|---|---|---|
| B1（name 的边界体裁 NE） | 条目 NE | 消失；期望收敛为「输出结构化条件（F）+ 保持等值语义（NF）」 |
| B2（SSE 体裁 NE） | 条目 NE | 消失 |
| B3（name 轴2） | 说不清/口径分歧 | **做错了**：5 次工具调用检索 327k 资料，citations 带 `material://llm_probe/field_definitions_args` + L29-L35 / L39-L50 / L51-L56 / L55-L58 行定位，placement 带 tool_trail |
| B4（unsupported） | 轴1 NF + 轴2说不清 | 轴1 fulfilled——重新核对发现业务实际支持家庭关系字段（familyInfo.familyrelation），基线的 NF 是「凭空要求拒绝」的误判；改动后判定正确 |
| mpi-customer-portrait 轴2 | 说不清 | **做错了**（boundary 补充意图标签空间后可判）；轴1 NF 保持（意图确实被误路由到 4001） |

结论：四类归因（体裁漏轴1、轴2体裁不匹配、大资料供给、证据可读性）全部闭环。
唯一的判定回退风险（输入语义被「不发明要求」规则误伤）已在 v2 修正并复验。

## 工具箱返工后的复验（同日，after-toolbox）

按泛化审查返工：检索工具孵化进 `impl/projects/llm_probe/material_tools.py`（outline/search/read，
格式处理器只认格式不认项目），TextCarrier 改骨架先行 + citation 机械核验打回重试 +
tool_trail=receipt，reasoning_effort 降至 **low**。见 `after-toolbox-20260830.json`：

| case | 轴1 | 轴2 | 工具行为 |
|---|---|---|---|
| client_search-name | NF（等值语义） | **做错了**，citation `field_definitions_args#L32-L69` 逐字引用过机械核验 | outline 先行（第一步即拿到 intents 菜单）→ search → read，共 6 次调用，全带 returned_locators 回执 |
| mpi-customer-portrait | NF ×4 | 意图期望**做错了**（boundary 逐字引用）；3 条槽位期望说不清/口径分歧——boundary 未声明槽位清单，诚实供给缺口而非误判 | 纯 boundary 文本，无需检索 |

low effort 下判定与 medium 版一致，验证「智能在外壳」的设计：骨架菜单压缩决策空间，
机械核验兜住引用真实性。假引用打回重试的闭环由单测覆盖
（`test_fake_citation_is_rejected_and_exhausts_retries`）。

## 轴1对照：llm_probe 探测 vs 原生 client_search（同查询同输出）

脚本 `compare_axis1_client_search.py`，数据 `axis1-compare-20260830.json`。
5 条查询双侧各跑 live+judge：

| 查询 | llm_probe | 原生 client_search | 一致性 |
|---|---|---|---|
| 客户姓名是张伟的人 | NF（等值语义未保持） | NF（未按姓名精确筛选） | ✓ 同判同因 |
| 五十岁以上的客户 | F | F | ✓ |
| 不要买了年金险的客户 | F | F | ✓ |
| 45岁+女+保费1万+ | F（4条期望全过） | F（4条期望全过，粒度几乎一致） | ✓ |
| 上有老下有小 | **F** | **NF**：familyrelation 仅声明支持 CONTAINS，子女条件却用 MATCH，下游不可执行 | ✗ 分歧 |

结论：
1. 语义保真类判定（等值/范围/排除/组合逻辑）双侧一致，llm_probe 轴1的期望派生
   规则（能力职责+输入字面语义）够用，且更快（48-225s vs 88-289s）。
2. family-slang 分歧的初判归因（「领域资料差距」）**是错的**，见下节修正。

## 定位体裁修正（同日，after-positioning）

family-slang 的真错因：输出的两个同字段条件（familyrelation CONTAINS[父母,祖辈] AND
MATCH 子女）在 ES nested 语义下落同一成员记录，互斥致空集——「家里同时有两类成员」
在该扁平条件语言里不可表达，正确交付是明确说明而非编造（原生场景名 unsupported_family_phrase）。
llm_probe judge 漏判不是缺字段资料，而是 capability 写成了**实现视角**（「输出结构化搜索条件」），
恰是 fulfilled.md §1 明令排除的写法——judge 只能对形状打分，不会把条件当查询推演。

修正：三个预设 capability 重写为**系统定位三问**（①用户拿它办什么事②交付物被谁怎么
消费执行③什么算办成），模板进 README/资料页/checklist。复跑 5 case
（`after-positioning-20260830.json`）：

| case | 修正前 | 修正后 |
|---|---|---|
| unsupported（上有老下有小） | F（表面语义通过） | **NF**：judge 自行推出「平面 AND 落同一成员作用域，互斥关系检不回目标人群」 |
| name（张伟） | NF | NF（保持；轴2做错了+资料引用） |
| age / exclusion | F | F（保持） |
| multi（保费一万以上） | F | **NF**：本次输出 annPremSegNum GT 10000 排除恰好一万——「以上」含本数，语义缩小；判据自洽（超过45→GTE 46 判对）。被测 parser 非确定性，前后两次输出操作符可能不同 |

轴2随动：unsupported 的组合语义期望归「说不清/口径分歧」——boundary（字段表）确实没写
多 familyrelation 条件的成员作用域语义，诚实缺口；要判「做不了」需在 boundary 补一句
成员作用域声明，属资料供给，不属判定逻辑。
