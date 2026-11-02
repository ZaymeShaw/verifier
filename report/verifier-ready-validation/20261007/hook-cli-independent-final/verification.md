# hook 独立验证

结论：修复后的 12 个完整 pi CLI 场景通过，另有 103 项 pytest 回归通过（包含 Node 的 23 个 hook 场景）。没有注册到项目扩展，未改主流程；真实业务 live 和 Qwen 语义审阅准确性仍未验证。

## 运行边界

本机 pi 0.87.1 显式加载临时仓库中的原样适配器，内置 write 真正写文件，原样 Python 门读取合成报告并计算状态。provider 是 127.0.0.1 的脚本模拟服务；它按脚本请求一次 write，之后反复尝试结束，让真实 hook 驱动后续请求。不存在外部模型请求。合成 PASS 和人工裁决数据是测试输入，不能作为真实上下文一致性证据。

临时仓库及私有 pi 配置退出后清理。每个场景保留 stdout、磁盘会话、provider 收到的请求和结果，见同目录 summary.json 及各场景子目录。源码指纹、根 run.sh、AGENTS、方案文件和全局 pi models/auth/settings/trust 内容在运行前后相同。

## 结果

| 场景 | 模拟 provider 请求 | hook 强制继续 | 上限提示 |
|---|---:|---:|---:|
| no_report | 8，磁盘恢复后另 1 次 | 6 | 首轮 1 次，恢复后再次提示 |
| docs_only | 2 | 0 | 0 |
| at_noop：`@impl` 写相同内容 | 8 | 6 | 1 |
| pass | 2 | 0 | 0 |
| pass_with_exception | 2 | 0 | 0 |
| stale | 8 | 6 | 1 |
| running | 8 | 6 | 1 |
| review_invalid | 8 | 6 | 1 |
| coverage_incomplete | 8 | 6 | 1 |
| hard_fail | 8 | 6 | 1 |
| inconsistent | 8 | 6 | 1 |
| needs_human | 8 | 6 | 1 |

实际 provider 请求中收到六轮注入消息；第七条上限通知落入磁盘会话，不再触发 provider。退出并重启 pi 后，同一磁盘会话只发生一次新请求，随后提示已有 6 次拦截，证明正常持久化下计数没有重置。有合成报告的场景均核对所有报告文件未被 hook 修改。

## 验证中发现并修复

1. write/edit 路径与 pi 的解析不同，`@impl` 相同内容写入会漏激活。修正 @、tilde、file URL、Unicode 空格及真实路径解析；完整 CLI 还暴露 macOS `/var` 与 `/private/var` 别名问题，现统一 realpath。旧失败记录保留在旁边的 hook-cli-debug-at，修复后的专门复测在 hook-cli-debug-at-fixed。
2. appendEntry 保存失败会被 pi runner 吞掉，使 hook 无消息提前结束。现在捕获并显示保存失败，仍返回拦截结果；用真实 runner 注入 ENOSPC 验证。磁盘完全无法保存记录时，不保证恢复后的计数完整，不能将其当正常通过。
3. 抢锁失败的命令仍会改写其他运行的失败状态，且自身异常清理发生在解锁后。现在只在持锁 operation 内记录失败，外层仅输出错误。真实 flock 回归证明抢锁失败不写报告，异常记录发生时锁仍在持有。

独立只读审查者复核上述修复，未发现剩余原问题。取消/错误结束、损坏状态、上限、其他扩展的 continuation 保留及普通会话恢复由回归覆盖。

## 复现

```bash
bash run.sh python hooks/verifier-ready/tests/pi_cli_harness.py \
  --out report/verifier-ready-validation/my-hook-cli-check
bash run.sh python -m pytest hooks/verifier-ready/tests tests/test_process_prompt_contract.py -q
```

完整 CLI 验证需要允许本机 127.0.0.1 临时服务；无需外部网络、业务凭据或全局 pi 配置修改。
