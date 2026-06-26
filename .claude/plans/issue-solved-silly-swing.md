# Issue-Solved Hook 循环逻辑分析报告

## 背景

用户要求分析 `hooks/issue-solved/stop-hook.sh` 实现的循环逻辑，重点关注：
- 是否存在无限循环风险？
- 循环是否在合理的时候结束？
- 是否在合适的时候继续进行？

## 核心设计

### 触发机制

Stop hook — 只在 Claude 会话**结束/退出时**触发。**没有定时器、没有 cron、没有自调用机制。**

### 数据流

```
用户关闭会话
  ↓
Stop hook 触发
  ↓
扫描 issue/*.md 的 frontmatter
  ├── 无 closed → exit 0（放行）
  ├── closed + 全部 APPROVED → exit 0（放行）
  ├── closed + 缺少审核 → block（要求启动审核 agent）
  └── closed + REJECTED
       ├── issue 已更新 → 删旧审核，重新审核（走"缺少审核"路径）
       └── issue 未更新 → block（要求修复）
```

---

## 循环分析：三种情况

### 情况 1：审核通过（APPROVED）

```
closed + APPROVED → exit 0 ✅ 终止
```

**合理结束。** 一次通过。

### 情况 2：缺少审核 → 审核不通过 → 修复 → 重新 close → 重新审核

```
closed + 无审核 → block → 审核 agent 写入 verdict
  ├── APPROVED → exit 0 ✅ 终止
  └── REJECTED → issue 变 open → 用户关闭 → hook 扫描发现 open → exit 0 ✅ 放行
                    ↓
                用户修复 → status: closed
                    ↓
                关闭会话 → hook 检查
                  ├── APPROVED → exit 0 ✅
                  └── REJECTED + 已更新 → 删旧审核，重新审核
```

**关键点**：
- REJECTED 后 `audit-prompt.md` 要求审核 agent 将 issue 的 `status:` 改为 `open`
- Hook 发现 `status: open` → 跳过 → **直接放行**
- 用户**不会被困住**，可以正常退出
- 用户有时间自行修复，改回 `closed` 后重新触发审核

**这是合理的行为**（用户已确认）。

### 情况 3：REJECTED + issue 未更新 → 再次 block

```
REJECTED + issue 文件未修改 → block
  ↓ 用户再次关闭
REJECTED + issue 文件未修改 → block（再次）
  ↓ ...
→ 死循环？
```

**不，不是死循环。** 因为：
1. 用户只能通过 **关闭会话** 触发 hook — 如果用户被 block，就不关闭会话
2. 被 block 后用户有两条出路：
   - 修复问题 → 更新 issue 文件 → `status: closed` → 关闭 → mtime 检测到更新 → 删旧审核 → 重新审核
   - 手动删除审核文件 `rm issue/audit/{issueid}.txt` 或改为 `status: open`
3. **mtime 机制自动打破循环**：`issue 修改时间 > 审核文件修改时间` → 自动走重新审核路径

---

## 特殊场景分析

### 场景 A：同时存在多个 closed issue

| 组合 | 结果 | 合理性 |
|------|------|--------|
| 全部 APPROVED | allow | ✅ |
| 有缺少审核 + 其他忽略 | block（要求审核缺少的） | ✅ "无审核"优先级最高 |
| 有 REJECTED（未更新）+ 其他 APPROVED | block（要求修复 REJECTED） | ✅ |
| 有 REJECTED（已更新）+ 其他 APPROVED | 删旧审核，重新审核 REJECTED | ✅ mtime 正确触发 |
| 全部 REJECTED | block | ✅ 合理 |

### 场景 B：审核 agent 执行过程中用户中断会话

审核 agent 写入 verdict 是**原子写入**操作 — 要么完全写完，要么文件不存在。如果审核 agent 未完成，verdict 文件不存在 → 下次 hook 触发时走"缺少审核"路径 → 重新开始审核。**不会残留不完整状态。**

### 场景 C：用户手动删除审核文件

如果用户手动 `rm issue/audit/issue3.txt`，下次 hook 触发时：
- 有 `closed` issue → 无审核文件 → **走"缺少审核"路径**
- 合理：强制启动审核，不允许绕过

### 场景 D：审核 agent 反复 REJECTED（真正的无限循环理论路径）

```
审核 agent 写入 REJECTED → issue 变 open → 用户退出
→ 用户修复 → 改回 closed → 关闭会话
→ 审核 agent 再次写入 REJECTED → issue 变 open → 用户退出
→ 用户再次修复 → ...
```

**理论上可能循环，但不属于"无限"循环**：
- 每次循环用户都有机会**实质性修复代码**
- 审核 agent 的判定有**严格的 4 条标准**（代码改动 + 直接针对 + 独立验证 + 问题消失），不是随机拒绝
- 用户可以通过修改审核标准或手动改为 `APPROVED` 在任何一轮终止循环

### 场景 E：config.yaml 误配置

如果 `CLOSED_VALUE` 或 `APPROVED_VALUE` 配置错误（如大小写不匹配），可能导致：
- 已 close 的 issue 不被识别为 closed → hook 放行 → 绕过审核 ❌
- APPROVED 审核被误判为 REJECTED → 不必要的 block ❌

**建议**：config 应保持默认值，修改后需确保 `audit-prompt.md` 的输出格式与之匹配。

---

## 循环总结

| 维度 | 结论 |
|------|------|
| **无限循环风险** | ❌ 不存在。hook 只由会话关闭触发，没有自调用机制 |
| **合理结束** | ✅ APPROVED 终止，REJECTED 后 issue 变 open 让用户正常退出 |
| **合理继续** | ✅ 用户修复并改回 closed 后，mtime 机制自动触发重新审核 |
| **REJECTED 后** | ✅ 不会死锁用户 — issue 变 open → 正常退出 |
| **审核未完成** | ✅ 残留状态被正确处理（无文件 = 重新审核） |
| **多重 issue** | ✅ 优先级正确：无审核 > REJECTED > APPROVED |

## 风险点

1. **配置一致性风险**：`config.yaml` 的 `verdict_field` / `approved_value` / `rejected_value` 必须与 `audit-prompt.md` 的输出格式精确匹配（大小写敏感 grep）
2. **mtime 依赖**：`stat -f %m` 在 macOS 和 Linux 上参数不同（`-f %m` vs `-c %Y`），虽然已经分别处理，但在某些定制环境中可能仍不兼容
3. **timeout=120s**：审核 agent 运行时间如果超过 120 秒，hook 被强行终止，但不会影响审核 agent 的写入结果（审核 agent 独立运行）