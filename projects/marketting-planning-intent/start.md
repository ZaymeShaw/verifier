整体流程是：                                                                                                                                         
1. 启动 market-plan 业务服务          
cd /Users/xiaozijian/WorkSpace/package/marketing-planning
bash start.sh                         
                               
2. 服务监听 127.0.0.1:9006。
                                                                                
3. 重启verifier前端服务8020

4. 调用实时请求接口/api/v1/marketing-planning/intent-recognition、judge agent、归因attribute agent，看看能不能通

以上通过check agent审核（.claude/skills/evals/define/check.md）


projects/marketting-planning-intent和projects/marketting-planning项目共享同一个业务服务，只是测评的东西不一样