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
