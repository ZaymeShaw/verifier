# 202606091939 review

1. 第一个问题：跑完之后表格就被强行清空了，跑的时候其实是有东西的
2. 第二个问题：
    + Reference返回的东西不对（reference 应该是输入里面用户给的标准答案或者judge给出的参考答案），我在demand.md里面要求过要跟output保持相同的格式，现在感觉这块内容不对输出格式也不对
    + summary: 客户年龄≥45 并且客户性别为女的客户, structured_output: Array(2), logic: AND, status_code: 0, user_visible_text: 客户年龄≥45 并且客户性别为女的客户, empty_result_reason:summary: 客户购买了年金险或两全险（满足任意一种）, structured_output: Array(1), logic: AND, status_code: 0, user_visible_text: 投保险种类别包含年金、两全险的客户, empty_result_reason:。为啥是这种展示？我其实有点看不懂这是啥东西，你贴原始json我觉得也行啊？然后reference向output对齐一下这样

# 202606082130 review

13. 现在打开网页，以及网页加载时，经常卡住，是不是数据太多了，看看怎么优化下
14. 为啥会有这么多无用的聚簇？
15. “summary: 未识别到明确查询条件, structured_output: Array(0), logic: AND, status_code: 0, user_visible_text: 未识别到明确查询条件, empty_result_reason: empty_query”，为啥是这种结果，总感觉怪怪的，检查下，现在依然是这种结果。然后感觉是不是没启动好服务，去看下start.md
16. 你自己去看下live和judge和归因总结里面的judge，明显是不一样的。检查下，要对齐的，check.md审核（明显还是有这个问题，归因的judge不对，你自己uat试一下）（现在依然还是这个问题，你验证了半天在看啥）  ✅
    + 比如“45岁女性保费10万以上”中，live的judge结果是[ { "field": "clientAge", "operator": "RANGE", "value": { "min": 45, "max": 45 } }, { "field": "clientSex", "operator": "MATCH", "value": "女" }, { "field": "annPremSegNum", "operator": "GTE", "value": 100000 } ]
    + 但归因总结页的结果是summary: 未识别到明确查询条件, structured_output: Array(0), logic: AND, status_code: 0, user_visible_text: 未识别到明确查询条件, empty_result_reason: empty_query
    + 这明显有问题，你能不能去看下到底是什么问题，对齐下？？？uat验证直到合理 
17. 对于16的问题，你倒是去做uat把问题复线出来啊。然后改正。你这样，先点清空，再点构建mock用例池，再点批量归因，然后等他跑完，就会发现你的结果是错的跟live的judge不一样 ✅
18. 我寻思client_Search业务服务的请求结果也不是空的啊？？？”45岁女性保费10万以上“，为什么你会显示它的结果是空的？ ✅
19. 根据业务场景特点，如果输入不包含output则trace要先调取api生成output，如果输入包含output则直接提取，impl里面根据情况再协议范围内进行调整 
20. 跑完归因了，表格页面怎么没更新呢？？？怎么现在多出了这么多问题，现在的Output / 被评估输出、Reference、Score / Judge、归因摘要怎么都没东西。而且跑完之后连状态也没了。check.md审核。
21. 我感觉现在协议和两个项目之间的对齐，以及协议本身，都有点问题。按照check.md的逻辑完整校验下吧
22. 页面展示无效信息，现在跑完归因出现：“旧结果已清理，请重新批量归因”。我明明都重跑了为什么会有这种东西？而且不是会跑judge和归因吗，为什么不出来？。check.md审核
23. 为什么跑完之后结果用例池候选区的结果就没了？？？？从correct/incorrect全部变成pending了。

# 202606071426 review
<!-- 1. 感觉judge_boundary要写的东西太多太复杂，没搞懂到底要写啥 -->
<!-- 2. 我没看懂你为什么要这些字段，以及这些字段为什么是协议的一部分，不知道为什么你觉得写这些就能做好协议的边界区分 -->
5. 我现在写了一版projects/client_search/judge_boundary-template.md，我感觉这版本针对client_search项目的来说，做的还不错，我觉得应该想办法把里面的东西抽取一下出来，分一些到合适的到边界模版，或者judge的协议里面

1. 我更新了projects/client_search/judge_boundary-template.md，这个template我觉得写的还不错算写到点子上了，你考虑下通用的模版是不是可以参考这个考虑下模版的想法看应该怎么构建比较好，以及更新impl的其他东西，check.md审核
2. 现在judge服务不通。http://127.0.0.1:8020/frontend/live.html上，跑了结果是uncertain，check.md审核下
3. http://127.0.0.1:8020/frontend/summary.html。感觉现在归因的界面，很难看，麻烦支持下
4. 我让你参考http://127.0.0.1:8011/attribution_summary.html的方式做用例池协议，你现在做成啥了，感觉奇奇怪怪得。你先分析这个参考的用例池做了哪些东西，可视化到前端哪里比较好用的，方便用户的
5. 感觉现在还是有点不太一样，只有一个默认的用例池的感觉，我就问你假如我现在搞定了一批用例，没有加载某个搞定了的用例池之类的概念，还想再分析别的用例，那这时候跟之前做好的之间怎么管理配置？你看下http://127.0.0.1:8011/attribution_summary.html怎么做的
6. 用例池这个输入搞得好短，都看不清楚了，然后api的输出也不给，能不能做宽点，放不下就支持左右拉这样的
8. 请check.md审核。根据check的需求，无论mock judge/归因 judge/live页面judge等所有judge，都应该复用一套逻辑，attribute、mock构建样本、cluster也是同理，全部都应该复用一套，避免到时候好几套逻辑。源头构建方式也应该一致（这一点也要在协议里面体现）check agent审核
9. 构建mock用例池按钮失效了。检查下。check.md审核
10. 批量归因应该得支持下，并发跑数据。以及批量归因中怎么没反应了现在像卡住了一样，全部按钮uat一下哈？这个管理页面你很多直接复用http://127.0.0.1:8011/attribution_summary.html就好了
11. 为什么一直卡在批量归因中没有结果，也没有进度条？
12. 帮忙构建一批客户搜索项目的mock数据集json，你围绕客户搜索这个场景以及对应的数据库字段，设计多批不同类型的数据集，每批100条数据，并且标注数据维度类型

# 202606051853 review
1. 请求check和请求cluster是哪里来的，这两一个是群体性处理，一个是对代码的审查，你怎么对单个case执行？你检查下你为什么会这样设计，是不是哪里有问题？ ok



