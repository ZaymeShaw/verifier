# 20260608 页面加载与标准化审查问题

## 问题

summary 页面打开和批量结果加载时容易卡住。

## 证据

- `impl/frontend/summary.html` 原先在 `switchProject()` 中自动调用 `loadLastChain()`，页面初始化就会从 sessionStorage 解析并渲染最近一次完整链路。
- `renderChain()` 原先把 `trace/judge/attribute/cluster/check/frontend_view/last_chain` 全量 JSON 写入多个 `<pre>`。
- `renderCasePool()` 原先一次渲染所有可见用例，并对每行的大对象反复 `JSON.stringify`。
- `impl/server.py` 原先在 `/api/batch_status` 完成时返回完整 batch result，前端轮询完成瞬间需要解析和渲染大体积 JSON。
- batch job events 原先不设上限，大批量任务会让 status 响应越来越大。

## 根因

页面首屏和轮询接口没有区分“用户需要立即看到的摘要”和“调试用全量原始数据”，导致大批量用例、完整 trace、raw_response、frontend_view 一起进入浏览器渲染路径。

## 已执行修复

- `impl/frontend/summary.html`
  - 页面切换项目时不再自动渲染 lastChain，改为用户点击“加载最近结果”后再加载。
  - case table 只展示前 100 条可见行，批量执行仍按完整已选用例执行。
  - 表格摘要不再对大对象完整 stringify，只展示对象前几个字段的轻量摘要。
  - raw panel 增加 `showCompact()` 截断大体积 JSON。
  - batch 完成后只在 raw 面板展示 batch/check/cluster 摘要，不再塞入完整 case_pool + batch。
  - progress log 前端最多保留 120 条。
- `impl/server.py`
  - `/api/batch_status` 完成时返回 compact batch result，保留 case_id、trace/judge/attribute 的关键摘要字段。
  - 后端 events 最多保留 200 条。
- `impl/protocols/frontend_protocol.md` / `impl/protocols/batch_protocol.md`
  - 补充大数据加载、可见行限制、batch status compact response 的协议约束。

## 后续建议

如果未来需要下载完整 batch 原始结果，应新增显式 debug/download 接口，而不是让 status 轮询和首屏页面默认承载全量 JSON。
