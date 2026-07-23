---
doc_type: startup
schema_version: 1
---

# 客户搜索启动说明

- 前置条件：`${CLIENT_SEARCH_REPO}` 指向业务仓库，业务依赖和 Elasticsearch 已准备完成。
- 启动方式：在业务仓库按其标准方式启动 8000 端口服务；verifier 由仓库根目录 `run.sh` 启动。
- 健康检查：对 `POST /api/v1/client_search_query_parse_no_encipher` 发起最小合法请求，并确认依赖检查无错误。
- 成功信号：接口返回可解析响应，随后 judge 与 attribute 链路可执行。
- 常见失败：8000 端口未监听、Elasticsearch 不可用、索引未初始化或 `${CLIENT_SEARCH_REPO}` 未配置。

## 人工维护的操作补充

# 用户编写，非ai编写

启动服务流程
1. 启动项目业务服务，对应8000端口
2. 启动前端分析界面，对应8020端口
3. 确保es正常可用，按以下更新es数据

curl --location --request POST 'http://localhost:8000/api/v1/fields/reindex' \
--header 'Content-Type: application/json' \
--data-raw '{
  "force_reindex_fields": true
}
'

4. 调用实时请求接口/api/v1/client_search_query_parse_no_encipher、judge agent、归因attribute agent，看看能不能通

以上通过check agent审核（.claude/skills/evals/define/check.md）
