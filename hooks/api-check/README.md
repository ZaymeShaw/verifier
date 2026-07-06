# API fixture check

这个测试套件以 curl 视角检查 API：构建 fixture 请求体，把请求体喂给真实 FastAPI route，真实进入 service/pipeline/project adapter，记录项目/API/请求体/响应体，并校验响应是否符合预期 schema。

真实性原则见 `AUTHENTICITY.md`：报告必须记录真实 schema、真实 mock/fixture 数据、真实 API 调用、真实 curl 和真实返回结果；测出 500/schema mismatch 也是有效结果，不能用伪造 curl、base64 包装或复用响应把问题藏掉。

最小 case 长这样：

```python
request = {
    "project": "fixture_project",
    "trace": load_fixture("impl.core.schema.trace.RunTrace", as_dict=True),
}
response = await client.post("/api/judge", json=request)
result = normalize_judge_result(response.json())
```

批量 case 写在 `api_check_registry.py`，每个 case 会和多个项目做交叉测试。

运行回归测试：

```bash
python -m impl.server --port 8021
python -m pytest hooks/api-check
```

默认测试地址读取 `impl/config.yaml` 的 `uat.host` / `uat.port`。
也可以用 `API_CHECK_BASE_URL` 显式覆盖已启动的服务：

```bash
API_CHECK_BASE_URL=http://127.0.0.1:18020 python -m pytest hooks/api-check
```

生成 Excel 表格报告：

```bash
python -m impl.server --port 8021
python hooks/api-check/write_api_check_excel.py
```

兼容旧脚本名也会生成 Excel：

```bash
python hooks/api-check/write_api_check_csv.py
```

输出路径：

```text
report/api-check/{timestamp}/api-check.xlsx
```

Excel 字段：

```text
project,case,api,http_status,curl,request_body,response_body,expected_schema,checked_response_path,schema_check,schema_error
```

查看 JSON 版报告：

```bash
python hooks/api-check/show_api_fixture_flow.py
```

在 pytest 中打印每个 API 输入/输出：

```bash
API_CHECK_VERBOSE=1 python -m pytest -s hooks/api-check
```
