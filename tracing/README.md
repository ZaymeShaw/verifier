# Verifier 实例和 LLM Trace

日常只需指定服务端口，启动器自动查询或创建稳定的实例映射：

```bash
bash run.sh tracing run server --port 8021
bash run.sh tracing run server --port 8022
```

`.runtime/instances.json` 保存端口到实例 ID 的映射，以及每个实例的三个中转端口。数据目录使用实例 ID，不使用服务端口。再次启动相同端口会复用相同实例和数据。独占文件锁在打开数据库和启动中转前取得，两个服务误绑定同一实例时第二个服务启动失败；退出或崩溃后锁由操作系统释放。

直接 `bash run.sh server --port 8021` 同样使用实例隔离的数据目录，模型按原始 `.env` 上游配置运行。要采集模型请求使用上面的 tracing 启动方式。

## 本机目录

```text
.runtime/instances.json
.runtime/instances.lock
.runtime/instances/<instance-id>/
  server.lock
  data/
    latest_runs.sqlite3
    case_pools.json
    context_store/
    context_runtime/
    <project>/                    # 资料、预设、会话、台账等
  tracing/
    .env.verifier_*                # 自动生成的凭证文件，0600
    config.verifier_*.yaml
    logs/verifier_*/
    reports/
    run/
```

根目录 `.env` 保留原始上游和密钥；`tracing/config.yaml` 指定 llmtracing 安装路径、中转端口分配起点和 LiteLLM 参数。实际中转端口在首次创建实例时自动分配并保存。启动 tracing 只覆盖服务子进程的模型地址/凭证，不改写 `.env`。模型和 fallback 路由保留原配置，`reasoning_effort` 显式透传。

实例运行数据、凭证、映射和报告全部 gitignore。项目代码、项目协议和静态配置仍在原来的代码目录。新端口创建新工作区；需要保留某实例的数据而换端口，先停止该服务，再执行：

```bash
bash run.sh tracing bind --from-port 8021 --port 8031
bash run.sh tracing run server --port 8031
```

目标端口已有映射或原实例正在运行时，重新绑定会被拒绝。CLI/Python 如需使用对应工作区和中转，可在该实例未运行服务时执行 `bash run.sh tracing run --port 8021 python your_script.py`。

## 前端和 HTML

在「归因总结」页运行一批评测，点击「查看用例池 LLM Trace」即可打开该实例当前用例行对应的模型请求和响应。A 成功、B 失败后只补跑 B，报告保留 A 的原执行，只展示 B 的新执行；旧 B 的失败调用不会混入。后端报告只读本实例日志；另一个实例的批次会被拒绝。HTML 使用独立临时目录，响应读取后自动删除。运行中点击得到快照，结束后刷新可更新；没有采集记录会提示经 tracing 启动服务。

终端也可导出：

```bash
bash run.sh tracing show --port 8021
bash run.sh tracing status --port 8021
bash run.sh tracing runs --port 8021
bash run.sh tracing report --port 8021 --project llm_probe --open
bash run.sh tracing report --port 8021 --run-id '<run_id>' --out .runtime/instances/<instance-id>/tracing/reports/my-run
```

不指定 `--port` 时使用公共配置的服务端口；服务内调用使用当前进程端口。run_id 对应前端 job_id。不同实例即使使用相同项目，也有各自的候选区、批次、结果、上下文及采集数据。

## 保留策略

批次结束后自动维护本实例采集日志：每个项目保留当前用例行对应的执行。每次提交以 job_id 和请求行序号形成 execution_id，写入模型请求 header，并随结果保存；同名 case 不会互相覆盖。一次提交内部的自动重试、降级和失败调用属于同一执行，仍保留；前端补跑产生新 job_id，只替换所选行的执行。当前用例池报告展示用例评测调用，不包含独立健康探测和批次汇总调用。同一实例还有其他批次在运行时跳过清理。使用 llmtracing 现有轮转功能压缩，再由 verifier 按 execution_id 过滤归档；保留请求关联的终态事件。迟到的 callback 写入当前日志，下一次维护再处理。启动新批次、清理和 HTML 读取使用同一把日志锁，避免互相打断。

```bash
bash run.sh tracing cleanup --port 8021 --dry-run
bash run.sh tracing cleanup --port 8021
```

补跑完成后，被替换行的旧执行日志可在维护时清除，未补跑行的日志继续保留；前端结果不随 tracing 清理删除。导出和清理读取相同的当前行执行集合。实例 reports 下的报告声明 execution_id 清单，只要包含已被替换的执行就清理该报告，避免旧 HTML 继续混入失败记录。旧结果若没有保存执行身份，报告明确提示缺失行，清理跳过整个实例，不能凭 case_id 猜关联；重新执行这些行后即可精确关联。显式导出到实例 tracing/reports 以外的文件视为用户留存，不参与清理。上下文、资料、数据库、配置、凭证和原始 `.env` 备份不属于 tracing 清理范围。

llmtracing 的采集、轮转、查询和 HTML 生成实现继续复用；实例划分和保留策略均在 verifier 仓库实现。
