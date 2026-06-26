# 需要拥有的前端页

我觉得对于每个待测评的项目，都有必要有一个live请求的前端，以及一个归因总结页

+ live请求页：
    + 在线实时请求项目服务，获取返回
    + 请求judge agent评估
    + 请求attribute agent归因问题）
+ 归因总结页：（你可以模仿http://127.0.0.1:8011/attribution_summary.html）
    + 基础算法能力：（按顺序）
        + mock：模拟用户意图，与系统进行交互
        + live：基于mock的输入请求系统获取结果
        + judge：评估系统结果的正确性、评分等
        + attribute：系统出问题时，进行问题归因
        + cluster：对发现的问题，进行聚合
    + 功能（记住也得是协议式的）
        + 支持构建mock数据集，使用mock agent
        + 支持用例池管理相关内容（模仿http://127.0.0.1:8011/attribution_summary.html）
            - 支持用户上传自定义数据集，进行批量归因（请支持通过文件的方式上传）
            - 支持用例池管理、聚簇管理等，用例池库/用例池候选区支持持久化方便管理（不然每次不小心刷新下，数据就没了）
        + 支持用例池表实时构建与可视化
            - output/reference中两个前端格子使用一样的大小，让人看的方便点
            - 请使reference格式与output保持格式一致，因为他们理论上就是有相同格式的-      
            - 不同case之间的judge/attribute等应该独立，有独立的上下文，彼此没有相互依赖，不相互干扰
            - judge/归因失败时应实现跳过/重试机制
        + analysis agent在实现impl/project前端时需要做的，包括但不限于以下（请根据项目需求进行扩展，在协议范围内进行调整）
            - output的获取：输入有预测输出output则直接取其作为output，输入没有output的话需要通过业务服务调取api等方式获取output
            - reference的获取：输入有reference就去输入的reference，输入没有reference则需要judge agent生成reference
            - 如果output/reference过于冗长，请impl/project中的实现去做字段选择和截取
            - 如果output/reference的格式是json，请以格式化换行的方式展示来看的清楚点
            - 通过api调用，非数据集给定output的场景，output请实时请求api给出，而非提前提供，在业务live跑完之后显示出来，无论构建mock用例池还是批量构建mock数据都要注意这点
            - 如果reference和output原始格式不一致，需要格式转换的话。请对reference进行格式转换，与output对齐格式（不改内容仅对齐格式）

可能面临的冲突：不同项目的请求格式、业务需求、评估逻辑、归因代码核心链路都有所不同，评估系统需要有更好的灵活性，同时也能有解决问题的能力
