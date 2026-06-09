# 需求

参考项目中，其judge、attribute、check这些做的还不错。我想把这套逻辑，迁移到本项目等通用评估系统上，完成demand.md的需求

# 项目定位

通用的评估、归因系统

# 迁移原则

1. 通用化：
2. 

# 项目新的需求

1. 既可用于客户搜索需求，也可用于其他更多的场景，需要更高的通用性
2. 做一些更通用的agent
3. 做一些更通用的测评系统前端


# 需要避免的问题
1. ai可能把原来的用户好的思路改的面目全非，过多罗列，只能勉强完成任务，但是缺乏了本身的泛化能力，反而无法完成好需求
2. ai修改后，也怕新项目和当前项目的逻辑部分不适配，当前项目希望支持的是通用的评估系统，而非单一的客户搜索项目测评。避免将此前项目的局限部分，照搬到本项目中
3. 现在客户搜索测试的效果还不错，我怕你迁移完后效果崩了，有两种崩掉的可能性
    + 你把原来人家的流程，迁移过程中给改崩了
    + 你试图把方案改的通用化，结果把方案改的失去judge/attribute归因能力了
4. 不要把项目相关的专用概念/字段搬进通用系统，迁移客户搜索相关前端、agent等耦合风险很高，你要拆出来
5. ai以为自己知道哪些是客户搜索专用的哪些不是，然后自作聪明的改，结果迁不对，把通用的和专用的混淆

# 要迁移什么

实际上取决于迁移什么东西能完成我们的目标（也即demand.md）
我理解要迁移的是机制和方法论，但是机制和方法论迁移后，怎么具体落地到实现/代码上，我理解可以这样思考（比如机制/方法论迁移到meta里面，然后针对项目的测评具体实现落地到projects里面）

# 怎么迁移

1. 思考现在客户搜索评估做的好的原因，要迁移方法论和解决方案，而不是机械的协议、规则，这些东西一是换项目就失效了，而是没有真正体现测试的精髓，换项目就达不到原来的好效果了
2. 重点！仔细思考：对于所有迁移项，给出通用、标准化、不伤害当前效果的（超级重点，要仔细思考解决方案）、合理的、有泛化性的迁移方案，在用户确认后执行，告诉用户具体怎么迁
3. 模拟验证：
    + 打开项目api，构建测试数据，模拟验证项目api是否正常运行
    + 运行测评链路，测评api运行结果（judge-attribute）
    + 用户模拟uat，点击前端按钮进行测评
4. 实现能通过本项目+projects重构llm_client_search的评估系统，可以理解为如果本项目构建的好，那么按本套方法论，/Users/xiaozijian/WorkSpace/projects/claude_code/llm_client_search_0513/llm_client_search的前端评测项目是本项目中针对client_search的一个实现。并且若启动一个新项目的启动下，只要明确填写好projects/<client_search>的一些信息，就能实现效果同样好但是可支持其他项目测评系统实现


# 迁移的注意事项

# 迁移参考

## 参考项目

/Users/xiaozijian/WorkSpace/projects/claude_code/llm_client_search_0513/llm_client_search

### 核心agent：
+ check agent：.claude/skills/evals/define/check.md
+ judge agent：search-test-case/llm_attribution_server.py 中的judge逻辑
+ attribute agent：search-test-case/llm_attribution_server.py 中的judge逻辑

### 核心前端

我觉得对于每个待测评的项目，都有必要有一个live请求的前端

+ live 请求核心参考前端：http://127.0.0.1:8011/live_query.html
+ 归因总结页核心参考前端：http://127.0.0.1:8011/attribution_summary.html

