整体流程是：                                                                                                                                         
1. 启动 market-plan 业务服务          
cd /Users/xiaozijian/WorkSpace/package/marketing-planning
bash start.sh                         
                               
2. 服务监听 127.0.0.1:9006。                        
                                                                                
3. 重启verifier前端服务8020

4. 调用实时请求接口http://127.0.0.1:9006/api/v1/marketing-planning/stream、judge agent、归因attribute agent，看看能不能通

以上通过check agent审核（.claude/skills/evals/define/check.md）
？