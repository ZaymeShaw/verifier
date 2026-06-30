# 参考资料
selenium可以使用此driver：material/chromedriver-149.zip

# role

你是**质检员**，不是算法的解说员或辩护律师。你的任务是**找bug**，不是解释算法"为什么可能对"。
核心原则：**默认怀疑，以事实为依据，主动找茬。**，


# checklist
每项check（比如check1）请固化一个测试脚本模版，通过编辑实现测试脚本进行测试，免得每次向我确认权限
测试脚本模版命名：impl/checklist/{checkid}.py（当前已有脚本时可以作为初始化baseline按需使用/更新使用）
<!-- 测试脚本-最小版模版命名：impl/checklist/{checkid}-min.py（当前已有脚本时可以作为初始化baseline按需使用/更新使用）（总体逻辑拷贝check1.py，但是只测试client_project的1-2条数据版本）（作为最小测试脚本） -->
为impl/checklist/{checkid}.py添加项目配置模块，允许配置测试项目/测试数量等配置信息，允许在脚本外部传参避免每次改脚本
## check1
通过selenium模拟打开summary前端页，全部4个项目逐个点击"清空数据"、选择mock数据、批量归因，然后查看批量归因结果是否正常

### mock数据选择原则
+ 目标优先+最简化原则：根据验证目标，选择所需的测试项目和测试数据，确定测试数据量和具体测试case，以最简化原则，通过最小量验证数据集得出所需结论
+ 全量验证：得出重大结论前需经过全量验证测试，包括宣称代码已经可用，此时默认每个项目选择2条数据（数据请保持一定的丰富性和差异性），client_search项目将样本选择数量提高到10，因为该场景大部分是fullfill
+ 不要选择语义上重复的数据


### 工作流

> 步骤1：执行check脚本产出check报告report.md
+ a)实施细节
    + 请用selenium打开浏览器测试，不要用后端接口，并且打开页面截图，查看b的运行完成结果，然后审核他们的值是否符合预期
    + 我建议你并行执行所有项目，不要等待啥的，你看看原理上是否可行，各项目之间是否会冲突
    + 请使用图形化界面而非headless
    + 跑完之后请清理自己开起的chrome driver程序（不要误删别人的）
+ b)完整结果记录：运行结果/截图/最后测试脚本放在本项目的tmp/{当前时间戳}/下，要让我看到
    - 批量归因中进度条数据
    - 用例池候选表格的output、reference、judge、归因摘要列。judge和归因摘要一定要给出详细分析结果，judge不要只给是否fullfill！我再强调一遍
+ c)结果截取
    - 每2分钟截取一次中间过程完整状态记录产出并覆盖report.md，如果判断已经完成就可以停止了程序了
    - 截图截的完整点不然我看不到，至少截到运行条、以及表格的judge、归因摘要信息
    - 给出当前运行状态下的完整详细结果（覆盖b)的完整结果记录，特别是judge和attr的结果一定要全）（report.md）（现在这个记录的不完整）
+ d)结果评估：每两分钟定期评估覆盖report.md，并且反馈claude验证

> 步骤1.5:claude code主进程修正与自迭代（非必要不执行）
+ e)故障重跑：当checklist脚本无法正常产出上述功能时，请迭代优化checklist脚本逻辑（通过claude 主进程实现而非测试脚本）
    - 报告没有代表性/不完整：每个项目至少测试一个有触发归因和没触发归因的案例，也就是每个项目至少触发一个not_fulfilled和fulfilled，如果部分项目未有则应该更换数据重新测试
    - 当出现除fullfilled和not_fullfilled的字段时，留意其是否有问题
    - 报告不可读：请你自己看下自己输出的结果，自己看不看的懂，看不懂就去优化代码重跑
    - 报告记录错误：请记录最终结果而不是最初脚本结果


> 步骤2：claude code主进程审核（创建一个独立的claude 子进程，用干净独立的上下文执行审核）
+ f)审核check脚本产出报告内容report.md（每当report.md更新时触发）
    - 从业务和技术角度出发，看分析的具体内容，评估 结果是否符合预期，包括页面本身功能、算法效果（各样本的judge和attr是否发挥了它应有的作用）。有无bug
    - 页面功能审核（进度条、候选区表格）
    - case明细算法内容审核（用例池候选区表格）（重点关注judge分析、attr归因分析明细内容）
        - 按项目纬度审核，是否有项目异常
        - 按列进行审核，是否某agent分析内容异常
        - 按行进行审核，是否特定样本异常(最常见问题)
        - 交叉审核，全局查看，检验是否有异常格子
    - 问题优先级：
        1. 最高优：整体页面可用性->整体算法功能可用性（按列审核）
        2. 第二优：项目算法功能可用性(按项目审核)->case by case算法功能可用性（按行审核）
        3. 第三优：整体算法效果质量->项目算法质量(按项目审核)->case-by-case算法效果可用性（按行审核）
+ g)推动问题解决：
    - 若checklist报告反映出测评系统问题，反馈问题并去推动优化测评系统verifier的代码，由用户确认后执行修复（通过claude 主进程实现而非测试脚本）
    - 清理无用的进程：浏览器打开用完后记得及时释放，这些都是你开的：--test-type=webdriver

### 报告格式
report.md 格式：                                     
                                                                               
‘’‘
# Checklist Report — {timestamp}                                             
                                                                               
  ## {project}                                                                

| # | Case ID | Input | Output | Reference | Verdict | Score | Judge no_issue| Attr | Time |                                                             
|----|---------|-------|--------|-----------|---------|-------|---------------|------|------|                                                             
| 1 | xxx | query文本 | ✓/✗ + 前200字 | ✓/✗ + 前200字 | fulfilled/not_fulfilled| 0-1 |完整judge分析，前500字 | 完整attr归因分析 ，前500字| elapsed |                          


  ## Evaluation                                                                
  - Parallel: ✅/❌                                                            
  - Attr triggered+not: X/4 projects                                           
  - Bugs: count + detail                                                     
  - Judge column issue: XX occurrences (should be > 0)                         
  - Output from real API: ✅/❌                                              
                                                                               
  ## Screenshots                                                             
  - (list all files) 
’‘’




