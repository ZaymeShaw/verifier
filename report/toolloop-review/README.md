# 复用现有机制的只读验证

入口：[现有轴展示组件的离线预览](existing-axes-view.html)。打开后选择“按案例看”，点击案例与轴交叉的格子可展开逐项原判。

本页由现有 `impl/frontend/axes_experiment.js` 和 `axes_overview.js` 直接渲染，不是新建前端系统。数据转换调用 `impl/core/table_view.py::eval_axes_summary`，并用 `axes_clustering.build_material` 验证聚类输入：5条历史运行、6个轴、30个轴级引用。

**范围：**1条Agno旧runner结果 + 4条暂停推进的llmtracing历史v0结果，均有来源记录；不是当前Agno ToolLoop成绩，不是同版本质量对比。图表只展示原判分布，不是正确率。未调用聚类模型、未运行业务/评判、未写入当前候选区。

离线页面禁用语义聚类按钮，避免浏览文件时触发模型；线上入口在summary主页“展示试验：轴分布”。源码支持保存标准、显式发起聚类、查看状态与下钻原判。当前后端服务是否已加载该版本，本次未部署验证。

浏览器检查：5行、6轴；1440×1000无水平溢出；切换到按案例看后，能展开模型轴的9条逐项理由；没有JS控制台错误。截图在preview.png（本次工具未提供图像视觉审查能力，不声称完成视觉质量验收）。

## 已有机制与用途

|能力|实现|用途与边界|
|---|---|---|
|固定输入与试评分|build-eval；现有grading-review.md、冻结输入与版本记录|判断verifier是否判对；暂定人工核验，不与原判混淆|
|批次与单例浏览|summary.html、axes_experiment.js、axes_overview.js|看轴分布、案例矩阵、原始理由、输入输出；显示的是原判|
|轴语义聚类|axes_clustering.py、axes_clustering_jobs.py|按轴→原枚举→reason类型组织阅读，保持成员覆盖与标签；调用LLM，需要批准|
|上下文查看|context.html及context_store|查看实际评判调用及工具交互；不能只用原判reason证明证据成立|
|当前运行存储|run_store.py|维护当前候选区及最新结果，防止过期写回；不是跨版本冻结基线库|
|归因聚类|cluster.py|按已有Attribute findings的conclusion归组；不是任意case的语义聚类，不凭空产生根因|
|发现台账|findings_ledger.py / explore.html|整案harness/judge分歧分类；不能直接表达所有逐轴引用错误|

## 真正需要补的接线（未实施）

1. 新Agno ToolLoop报告进入现有标准结果/展示通道，而不是只落临时JSON；当前Agno ToolLoop返回axes，标准表格消费report.results，需要在项目adapter统一，不重做展示算法。
2. 运行中的候选区不能随意覆盖。当前LatestRunStore只保留每行最新结果；跨版本基线继续保持独立不可变档案，不当作latest库的替代用途。
3. 原判、人工复核和执行审计是三类信息。现有语义聚类只读reason，不读完整trace，不能自动发现错误的sound或证明根因。
4. axes_experiment现有详情不展示loop_calls/completion_checks和完整来源链；应考虑接到现有context/详情入口，而不是再造一个总览系统。

导出脚本：`/Users/xiaozijian/miniconda3/envs/agno/bin/python report/toolloop-review/export_existing.py`。
只重新渲染上述固定历史记录，不启动模型。原始来源与SHA见provenance.json。本地文件含业务内容，不应提交或对外发布。
