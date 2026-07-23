---
doc_type: startup
schema_version: 1
---

# 营销规划意图识别服务启动说明

- 前置条件：`${MARKETTING_PLANNING_INTENT_REPO}` 指向共享业务仓库，依赖已经安装。
- 启动方式：在 `${MARKETTING_PLANNING_INTENT_REPO}` 中执行业务仓库维护的 `start.sh`。
- 健康检查：确认 `127.0.0.1:9006` 可连接，并对意图识别接口执行最小合法请求。
- 成功信号：接口返回受支持的意图标签和置信度，verifier 才开始测评。
- 常见失败：仓库变量缺失、9006 端口冲突、共享服务未启动、返回标签不受支持或请求超时。

## 人工操作补充

整体流程是：                                                                                                                                         
1. 启动 market-plan 业务服务          
cd "${MARKETTING_PLANNING_INTENT_REPO}"
bash start.sh                         
                               
2. 服务监听 127.0.0.1:9006。
                                                                                
3. 重启verifier前端服务8020

4. 调用实时请求接口/api/v1/marketing-planning/intent-recognition、judge agent、归因attribute agent，看看能不能通

以上通过check agent审核（.claude/skills/evals/define/check.md）


projects/marketting-planning-intent和projects/marketting-planning项目共享同一个业务服务，只是测评的东西不一样
