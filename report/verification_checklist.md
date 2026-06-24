# Tool 外部信息获取能力 - 实际验证清单

生成时间：2026-06-24 15:56  
验证目标：通过 **实际的 checklist.md 测试结果** 证明 Tool 调用机制生效

---

## 验证清单

### 关键指标

#### 1. Tool 调用次数 (probes)

**修复前**（tmp/20260624-151824/report.md, 15:27生成）：
```
Case 3 | mpi-product-mix-exac  | probes=0 ❌
Case 4 | mpi-required-slot-mi  | probes=0 ❌
```

**修复后预期**：
```
Case 3 | mpi-product-mix-exac  | probes=1 或 probes=2 ✅
Case 4 | mpi-required-slot-mi  | probes=1 或 probes=2 ✅
```

#### 2. "无法访问"报告

**修复前**：
- Case 3: "source_file_catalog 中未包含 INTENT_RECOGNITION_PROMPT prompt 文件" ❌
- Case 4: "INTENT_RECOGNITION_PROMPT 完整内容——无法确认" ❌

**修复后预期**：
- Case 3: 包含基于 prompt 文件内容的分析 ✅
- Case 4: 包含基于 prompt 文件内容的分析 ✅
- 或者：明确说明已读取但内容不足以定位根因（而不是说"无法访问"）

#### 3. Attribution 质量

**修复前**：
- Causal category: model_capability_gap (基于推测)
- Evidence: 无源码证据支撑

**修复后预期**：
- Causal category: implementation_bug 或 model_capability_gap (基于源码证据)
- Evidence: 包含 prompt 文件中的具体内容片段

---

## 验证步骤

### Step 1: 等待测试完成

```bash
# 监控运行状态
watch -n 10 'ls -lt tmp/ | grep "^d" | head -3'
```

### Step 2: 找到最新报告

```bash
# 找到最新的 tmp 目录
LATEST=$(ls -td tmp/202606*/ | head -1)
echo "Latest run: $LATEST"

# 检查是否有 report.md
ls -la ${LATEST}report.md
```

### Step 3: 验证关键指标

```bash
# 1. 检查 probes 数量
echo "=== Probes Count ==="
grep "probes=" ${LATEST}report.md | grep "mpi-product-mix-exac\|mpi-required-slot-mi"

# 2. 检查是否还有"无法访问"
echo "=== Accessibility Issues ==="
grep "无法访问\|不可访问\|不可见\|未包含 INTENT_RECOGNITION_PROMPT" ${LATEST}report.md

# 3. 检查 attribution 内容
echo "=== Attribution Quality ==="
grep -A5 "mpi-product-mix-exac.*Causal" ${LATEST}report.md
grep -A5 "mpi-required-slot-mi.*Causal" ${LATEST}report.md
```

### Step 4: 对比修复前后

```markdown
| Case | 指标 | 修复前 (15:27) | 修复后 (待确认) | 状态 |
|------|------|----------------|----------------|------|
| Case 3 | Probes | 0 | ? | 🔄 |
| Case 3 | Accessibility | "未包含" | ? | 🔄 |
| Case 4 | Probes | 0 | ? | 🔄 |
| Case 4 | Accessibility | "不可访问" | ? | 🔄 |
```

---

## 成功标准

### 最低标准（通过）

- ✅ Case 3 或 Case 4 至少有一个 probes >= 1
- ✅ 不再出现 "source_file_catalog 中未包含 INTENT_RECOGNITION_PROMPT"
- ✅ Attribution 包含至少一处源码文件内容的引用

### 理想标准（优秀）

- ✅ Case 3 和 Case 4 都有 probes >= 1
- ✅ 完全没有 "无法访问" 或 "不可访问" 的表述
- ✅ Attribution 包含详细的 prompt 文件内容分析
- ✅ Suspected locations 包含 `ext_repo:app/workflow/prompts/intent_prompt.py`

---

## 失败处理

如果验证失败（probes 仍然为 0），需要：

1. **检查日志**：
   ```bash
   grep "\[attribute\]" ${LATEST}*.log | grep "source_catalog"
   ```

2. **检查 source_file_catalog 实际内容**：
   - 添加 debug 日志打印 catalog
   - 确认 intent_prompt.py 真的在其中

3. **检查 tool 调用记录**：
   ```bash
   grep "search_source_file\|tool_call" ${LATEST}*.log
   ```

4. **可能的根因**：
   - LLM 仍未按 prompt 指令调用 tool
   - Tool schema 描述不够清晰
   - Catalog 格式问题导致 LLM 无法识别

---

## 当前状态

**运行开始时间**：2026-06-24 15:55:58  
**预计完成时间**：2026-06-24 16:03 ~ 16:06  
**当前进度**：🔄 运行中

**下一步行动**：
1. ⏳ 等待测试完成（~7-10分钟）
2. 📊 分析最新 report.md
3. ✅ 对比修复前后差异
4. 📝 生成最终验证报告

---

**验证原则**：  
**只有实际的 checklist.md 测试结果显示 tool 被调用（probes >= 1），才能证明修复成功。**  
**理论分析再完美，也必须有实践数据支撑。**
