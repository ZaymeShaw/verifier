---
doc_type: startup
schema_version: 1
---

# 营销规划服务启动说明

- 前置条件：`${MARKETTING_PLANNING_REPO}` 指向业务仓库，依赖已经安装。
- 启动方式：在 `${MARKETTING_PLANNING_REPO}` 中执行业务仓库维护的 `start.sh`。
- 健康检查：确认 `127.0.0.1:9006` 可连接，并对规划接口执行最小合法请求。
- 成功信号：流式接口返回可解析事件并出现终止事件，verifier 才开始正式测评。
- 常见失败：仓库变量缺失、9006 端口冲突、依赖未启动、SSE 响应不完整或请求超时。

## 人工操作补充

整体流程是：                                                                                                                                         
1. 启动 market-plan 业务服务          
cd "${MARKETTING_PLANNING_REPO}"
bash start.sh                         
                               
2. 服务监听 127.0.0.1:9006。                        
                                                                                
3. 重启verifier前端服务8020

4. 调用实时请求接口http://127.0.0.1:9006/api/v1/marketing-planning/stream、judge agent、归因attribute agent，看看能不能通

以上通过check agent审核（.claude/skills/evals/define/check.md）
？
