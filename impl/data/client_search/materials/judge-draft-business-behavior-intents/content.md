# behavior_intent_definitions_args.yaml

- evidence_ref: `business-behavior-intents`
- location: `business://src/main/python/data/client_search_query_parse/behavior_intent_definitions_args.yaml`
- source_revision: `a2cfd68ea351d5081d95857ca7bcbfac90434528`
- source_sha256: `a22a44b8686fcfca0194307ad7451be65892aa3f3813375e0bcea7653936192e`

Defines customer_activity field, MATCH operator, supported activity enum space, and parser selection rules (aliases/templates). Space statements are inlive_boundary under M1; selection rules remain current_behavior.

---

field: customer_activity
source: docs/客户动态模板全量数据.xlsx
equivalent_activity_groups:
- [SMARTVISIT_AIVIDEO_THUMBSUP, SMARTVISIT_AIVIDEO_THUMBSUP_ZY]
- [ZEB_PRODUCT_SHARE, SYZQ_ZEB_PRODUCT_SHARE]
- [ZEB_INFO_THUMBSUP, SYZQ_ZEB_INFO_THUMBSUP]
- [ZEB_VIDEO_READEND, SYZQ_ZEB_VIDEO_READEND]
- [ZEB_PRODUCT_READEND, SYZQ_ZEB_PRODUCT_READEND]
- [ZEB_INFO_PRODUCT, SYZQ_ZEB_INFO_PRODUCT]
- [ZEB_INFO_SHARE, SYZQ_ZEB_INFO_SHARE]
- [ZEB_VIDEO_SHARE, SYZQ_ZEB_VIDEO_SHARE]
- [ZEB_INFO_READEND, SYZQ_ZEB_INFO_READEND]
- [LAIP_IVAP_VIDEO_N02, LAIP_IVAP_VIDEO_N04]
- [JGJ_MULTI_PRODUCT_RESERVE, JGJ_O2O_PRODUCT_RESERVE, JGJ_LIFE_PRODUCT_RESERVE]
- [JGJ_RIGHT_HOMESERVICE1, JGJ_RIGHT_HOMESERVICE2]
intents:
- candidate_id: behavior_candidate_001
  activity: ZEB_INFO_TOOL
  intent_category: 在资讯中查看了工具
  activity_template: 在资讯《$articleName$》中，查看了工具“$tool$”
  description: 客户在文章或资讯内容中打开、查看或使用客户画像、测算器等工具。
  selection_notes: 必须存在资讯或文章内查看工具的语义；预约工具讲解、单独完成测算不属于该候选。
  aliases:
  - 在资讯中查看了工具
  - 在资讯中查看工具
  - 查看了工具
  - 在资讯中看过工具
  - 在资讯中浏览了工具
  - 有过在资讯中查看工具行为
  - 曾经在资讯中查看工具
  - 在资讯中查看工具记录
  positive_examples:
  - 找在文章或资讯里使用过工具的客户
  - 查询在某篇资讯中打开客户画像、测算器等工具的人
  - 哪些客户查看了工具
  - 筛选出有过在资讯中看过工具行为的客户
  negative_examples:
  - 找在工具中留资预约服务讲解的客户
  - 查询单独完成养老测算或使用计算器的人
  - 查询从未在资讯中查看工具的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_002
  activity: ZEB_TOPIC_SHARE
  intent_category: 转发分享了资讯专题
  activity_template: 转发分享了资讯专题《$topicName$》
  description: 客户转发或分享资讯专题、专题栏目或专题集合。
  aliases:
  - 转发分享了资讯专题
  - 转发分享资讯专题
  - 转发了资讯专题
  - 分享了资讯专题
  - 有过转发分享资讯专题行为
  - 曾经转发分享资讯专题
  - 转发分享资讯专题记录
  positive_examples:
  - 找转发过资讯专题的客户
  - 查询把专题分享给别人的人
  - 哪些客户转发了资讯专题
  - 筛选出有过分享了资讯专题行为的客户
  negative_examples:
  - 找转发单篇资讯文章的客户
  - 查询分享展业工具或产品的人
  - 查询从未转发分享资讯专题的人
  confusing_intents:
  - ZEB_TOOL_SHARE
  - ZEB_PRODUCT_SHARE
  - ZEB_INFO_SHARE
  - SYZQ_ZEB_INFO_SHARE
  is_supported: true
- candidate_id: behavior_candidate_003
  activity: ZEB_ZY_READ
  intent_category: 查看增员素材
  activity_template: 查看增员素材《$articleName$》
  description: 客户查看或浏览增员素材的基础行为。
  aliases:
  - 查看增员素材
  - 浏览增员素材
  - 有过查看增员素材行为
  - 曾经查看增员素材
  - 查看增员素材记录
  positive_examples:
  - 找看过增员素材但没有限定查看时长的客户
  - 查询浏览过增员文章或增员素材的人
  - 哪些客户有过查看增员素材行为
  - 筛选出有过曾经查看增员素材行为的客户
  negative_examples:
  - 查看增员素材三分钟的客户
  - 在增员素材中停留超过六十秒的人
  - 查询从未查看增员素材的人
  confusing_intents:
  - ZEB_ZY_READEND
  is_supported: true
- candidate_id: behavior_candidate_004
  activity: JGJ_Product_Insure
  intent_category: 点击我要投保
  activity_template: 在金管家查看《$productName$》时点击了“我要投保”
  description: 表示客户发生了“点击我要投保”行为。
  aliases:
  - 点击我要投保
  - 点了我要投保
  - 在金管家查看时点击了我要投保
  - 点过我要投保
  - 点击立即投保
  - 按过投保按钮
  - 在金管家查看时点击我要投保
  - 查看时点击了我要投保
  positive_examples:
  - 找点击我要投保的客户
  - 查询点了我要投保的人
  - 哪些客户在金管家查看时点击了我要投保
  - 筛选出有过点过我要投保行为的客户
  negative_examples:
  - 找点击立即投保但未完成的客户
  - 找没有点击我要投保的客户
  - 排除点击我要投保的客户
  - 查询从未点击我要投保的人
  confusing_intents:
  - JGJ_Product_YJX_BUY_FAILD
  is_supported: true
- candidate_id: behavior_candidate_005
  activity: SMARTVISIT_AIVIDEO_THUMBSUP
  intent_category: 点赞了智能拜访助手中的跟拍视频
  activity_template: 点赞了智能拜访助手中的跟拍视频$videoName$
  description: 表示客户发生了“点赞了智能拜访助手中的跟拍视频”行为。
  aliases:
  - 点赞了智能拜访助手中的跟拍视频
  - 点赞智能拜访助手中的跟拍视频
  - 点过赞智能拜访助手中的跟拍视频
  - 有过点赞智能拜访助手中的跟拍视频行为
  - 曾经点赞智能拜访助手中的跟拍视频
  - 点赞智能拜访助手中的跟拍视频记录
  positive_examples:
  - 找点赞了智能拜访助手中的跟拍视频的客户
  - 查询点赞智能拜访助手中的跟拍视频的人
  - 哪些客户点过赞智能拜访助手中的跟拍视频
  - 筛选出有过点赞智能拜访助手中的跟拍视频行为的客户
  negative_examples:
  - 找没有点赞智能拜访助手中的跟拍视频的客户
  - 排除点赞智能拜访助手中的跟拍视频的客户
  - 查询从未点赞智能拜访助手中的跟拍视频的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_006
  activity: onePA_ReadOrder
  intent_category: 浏览了ONE平安页面并提交了展厅预约申请
  activity_template: 浏览了ONE平安页面，并提交了展厅预约申请
  description: 表示客户发生了“浏览了ONE平安页面并提交了展厅预约申请”行为。
  aliases:
  - 浏览了ONE平安页面并提交了展厅预约申请
  - 浏览ONE平安页面并提交展厅预约申请
  - 看过ONE平安页面并提交了展厅预约申请
  - 查看了ONE平安页面并提交了展厅预约申请
  - 浏览了ONE平安页面并提交了展厅预订申请
  - 浏览了ONE平安页面并递交了展厅预约申请
  - 有过浏览ONE平安页面并提交展厅预约申请行为
  - 曾经浏览ONE平安页面并提交展厅预约申请
  positive_examples:
  - 找浏览了ONE平安页面并提交了展厅预约申请的客户
  - 查询浏览ONE平安页面并提交展厅预约申请的人
  - 哪些客户看过ONE平安页面并提交了展厅预约申请
  - 筛选出有过查看了ONE平安页面并提交了展厅预约申请行为的客户
  negative_examples:
  - 找没有浏览ONE平安页面并提交展厅预约申请的客户
  - 排除浏览ONE平安页面并提交展厅预约申请的客户
  - 查询从未浏览ONE平安页面并提交展厅预约申请的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_007
  activity: ZEB_PRODUCT_BUY
  intent_category: 购买成功
  activity_template: 购买产品“$productName$”时，购买成功
  description: 表示客户发生了“购买成功”行为。
  aliases:
  - 购买成功
  - 产品购买成功
  - 购买产品时购买成功
  - 成功买到产品
  - 买产品成功
  - 买过产品时购买成功
  - 有过购买成功行为
  - 曾经购买成功
  positive_examples:
  - 找购买成功的客户
  - 查询产品购买成功的人
  - 哪些客户购买产品时购买成功
  - 筛选出有过成功买到产品行为的客户
  negative_examples:
  - 完成支付
  - 支付失败
  - 完成购买
  - 找完成支付的客户
  - 找完成购买的客户
  confusing_intents:
  - ZEB_PRODUCT_PAY_FINISH
  - JGJ_Product_Succeed
  - ZEB_PRODUCT_PAY_FAIL
  - JGJ_Product_YJX_BUY_SUCCESS
  is_supported: true
- candidate_id: behavior_candidate_008
  activity: ZEB_TOOL_READEND
  intent_category: 查看了展业工具时长秒
  activity_template: 查看了展业工具“$toolName$”，时长$time$秒
  description: 表示客户发生了“查看了展业工具时长秒”行为。
  aliases:
  - 查看了展业工具时长秒
  - 查看展业工具时长秒
  - 看过展业工具时长秒
  - 浏览了展业工具时长秒
  - 有过查看展业工具时长秒行为
  - 曾经查看展业工具时长秒
  - 查看展业工具时长秒记录
  positive_examples:
  - 找查看展业工具超过一分钟的客户
  - 查询查看了展业工具时长秒的人
  - 哪些客户查看展业工具时长秒
  - 筛选出有过看过展业工具时长秒行为的客户
  negative_examples:
  - 找没有查看展业工具的客户
  - 排除查看展业工具的客户
  - 查询从未查看展业工具的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_009
  activity: ZEB_BUSINESS_CARD_ELITE_READEND
  intent_category: 查看了个人名片精英版时长秒
  activity_template: 查看了个人名片(精英版)，时长$time$秒
  description: 表示客户发生了“查看了个人名片精英版时长秒”行为。
  aliases:
  - 查看了个人名片精英版时长秒
  - 查看个人名片精英版时长秒
  - 看过个人名片精英版时长秒
  - 浏览了个人名片精英版时长秒
  - 有过查看个人名片精英版时长秒行为
  - 曾经查看个人名片精英版时长秒
  - 查看个人名片精英版时长秒记录
  positive_examples:
  - 找查看个人名片精英版超过一分钟的客户
  - 查询查看了个人名片精英版时长秒的人
  - 哪些客户查看个人名片精英版时长秒
  - 筛选出有过看过个人名片精英版时长秒行为的客户
  negative_examples:
  - 找没有查看个人名片精英版的客户
  - 排除查看个人名片精英版的客户
  - 查询从未查看个人名片精英版的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_010
  activity: ZEB_TOOL_SHARE
  intent_category: 转发分享了展业工具
  activity_template: 转发分享了展业工具“$toolName$”
  description: 客户将测算器、计划书工具、客户画像等展业工具转发或分享给他人。
  aliases:
  - 转发分享了展业工具
  - 转发分享展业工具
  - 把展业工具转给别人
  - 分享过测算工具
  - 转发过计划书工具
  - 转发了展业工具
  - 分享了展业工具
  - 有过转发分享展业工具行为
  - 曾经转发分享展业工具
  - 转发分享展业工具记录
  positive_examples:
  - 找把展业工具分享给别人的客户
  - 查询转发过测算器或计划书工具的人
  - 哪些客户转发了展业工具
  - 筛选出有过分享了展业工具行为的客户
  negative_examples:
  - 找只使用或完成测算器但没有转发的客户
  - 查询转发过产品、资讯文章或资讯专题的人
  - 查询从未转发分享展业工具的人
  confusing_intents:
  - ZEB_TOPIC_SHARE
  - ZEB_PRODUCT_SHARE
  - ZEB_INFO_SHARE
  - SYZQ_ZEB_INFO_SHARE
  is_supported: true
- candidate_id: behavior_candidate_011
  activity: KDE_ACTIVITY_VISIT_ASSISTANT
  intent_category: 在拜访助手预约咨询
  activity_template: 在拜访助手预约咨询$articleName$
  description: 表示客户发生了“在拜访助手预约咨询”行为。
  aliases:
  - 在拜访助手预约咨询
  - 在拜访助手预订咨询
  - 有过在拜访助手预约咨询行为
  - 曾经在拜访助手预约咨询
  - 在拜访助手预约咨询记录
  positive_examples:
  - 找在拜访助手预约咨询的客户
  - 查询在拜访助手预订咨询的人
  - 哪些客户有过在拜访助手预约咨询行为
  - 筛选出有过曾经在拜访助手预约咨询行为的客户
  negative_examples:
  - 找没有在拜访助手预约咨询的客户
  - 排除在拜访助手预约咨询的客户
  - 查询从未在拜访助手预约咨询的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_012
  activity: JGJ_POLICY_SERVICE_01
  intent_category: 在金管家使用了服务保险产品为保单号投保单号
  activity_template: '在金管家使用了$serviceName$服务，保险产品为$productName$，保单号（投保单号）: $policyNo$'
  description: 客户在金管家使用某个具体服务，服务与保险产品或保单关联，但原文没有出现服务分类、资料变更或保全分类信息。
  selection_notes: 具体服务名、产品名或保单号可以作为事件参数；未明确“分类、资料变更、保全”等新版分类结构时选择本候选。明确服务分类或资料变更时选择 JGJ_POLICY_SERVICE_2026。
  aliases:
  - 在金管家使用了服务保险产品为涉及保单
  - 在金管家使用了服务保险产品为保单号投保单号
  - 在金管家使用服务保险产品为保单号投保单号
  - 使用了服务保险产品为保单号投保单号
  - 在金管家用过服务保险产品为保单号投保单号
  - 有过使用服务保险产品为保单号投保单号行为
  - 曾经使用服务保险产品为保单号投保单号
  - 使用服务保险产品为保单号投保单号记录
  positive_examples:
  - 找在金管家使用了服务保险产品为涉及保单的客户
  - 查询在金管家使用了服务保险产品为保单号投保单号的人
  - 哪些客户在金管家使用服务保险产品为保单号投保单号
  - 筛选出有过使用了服务保险产品为保单号投保单号行为的客户
  negative_examples:
  - 找办理客户资料变更或保全分类服务的客户
  - 查询明确使用某分类下服务的人
  - 找没有使用服务保险产品为涉及保单的客户
  - 排除使用服务保险产品为涉及保单的客户
  - 查询从未使用服务保险产品为涉及保单的人
  confusing_intents:
  - JGJ_POLICY_SERVICE_2026
  is_supported: true
- candidate_id: behavior_candidate_013
  activity: JGJ_MEETINGE_BAO_SIGNIN_ON_SITE
  intent_category: 线下活动扫码签到成功正在参加活动
  activity_template: 线下活动扫码签到成功，正在参加活动“$activityName$”
  description: 表示客户发生了“线下活动扫码签到成功正在参加活动”行为。
  aliases:
  - 线下活动扫码签到成功正在参加活动
  - 有过线下活动扫码签到成功正在参加活动行为
  - 曾经线下活动扫码签到成功正在参加活动
  - 线下活动扫码签到成功正在参加活动记录
  positive_examples:
  - 找线下活动扫码签到成功正在参加活动的客户
  - 查询有过线下活动扫码签到成功正在参加活动行为的人
  - 哪些客户曾经线下活动扫码签到成功正在参加活动
  - 筛选出有过线下活动扫码签到成功正在参加活动记录行为的客户
  negative_examples:
  - 找没有线下活动扫码签到成功正在参加活动的客户
  - 排除线下活动扫码签到成功正在参加活动的客户
  - 查询从未线下活动扫码签到成功正在参加活动的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_014
  activity: KDE_BDTG_RAU
  intent_category: 客户与您解除了保单管家服务关系原因如下
  activity_template: 客户与您解除了保单管家服务关系，原因如下：$replaceReason$
  description: 表示客户发生了“客户与您解除了保单管家服务关系原因如下”行为。
  aliases:
  - 客户与您解除了保单管家服务关系
  - 客户与您解除了保单管家服务关系原因如下
  - 客户与您解除保单管家服务关系原因如下
  - 有过客户与您解除保单管家服务关系原因如下行为
  - 曾经客户与您解除保单管家服务关系原因如下
  - 客户与您解除保单管家服务关系原因如下记录
  positive_examples:
  - 找客户与您解除了保单管家服务关系的客户
  - 查询客户与您解除了保单管家服务关系原因如下的人
  - 哪些客户与您解除保单管家服务关系原因如下
  - 筛选出有过客户与您解除保单管家服务关系原因如下行为的客户
  negative_examples:
  - 找没有客户与您解除保单管家服务关系的客户
  - 排除客户与您解除保单管家服务关系的客户
  - 查询从未客户与您解除保单管家服务关系的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_015
  activity: ZEB_BUSINESS_CARD_READEND
  intent_category: 查看了个人名片标准版时长秒
  activity_template: 查看了个人名片(标准版)，时长$time$秒
  description: 表示客户发生了“查看了个人名片标准版时长秒”行为。
  aliases:
  - 查看了个人名片标准版时长秒
  - 查看个人名片标准版时长秒
  - 看过个人名片标准版时长秒
  - 浏览了个人名片标准版时长秒
  - 有过查看个人名片标准版时长秒行为
  - 曾经查看个人名片标准版时长秒
  - 查看个人名片标准版时长秒记录
  positive_examples:
  - 找查看个人名片标准版超过一分钟的客户
  - 查询查看了个人名片标准版时长秒的人
  - 哪些客户查看个人名片标准版时长秒
  - 筛选出有过看过个人名片标准版时长秒行为的客户
  negative_examples:
  - 找没有查看个人名片标准版的客户
  - 排除查看个人名片标准版的客户
  - 查询从未查看个人名片标准版的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_016
  activity: ZEB_INFO_ORDER
  intent_category: 在口袋E资讯中预约产品咨询
  activity_template: 在口袋E资讯《$articleName$》中，预约产品咨询$productName$
  description: 客户在口袋E资讯文章场景中发起产品咨询预约。
  aliases:
  - 在口袋E资讯中预约产品咨询
  - 预约产品咨询
  - 在口袋E资讯中预订产品咨询
  - 有过预约产品咨询行为
  - 曾经预约产品咨询
  - 预约产品咨询记录
  positive_examples:
  - 找阅读口袋E资讯后预约产品咨询的客户
  - 查询从资讯文章发起产品咨询的人
  - 哪些客户在口袋E资讯中预订产品咨询
  - 筛选出有过预约产品咨询行为的客户
  negative_examples:
  - 找在口袋E产品贴中预约咨询的客户
  - 查询在金管家直接预约了解产品的人
  - 查询从未预约产品咨询的人
  confusing_intents:
  - ZEB_PRODUCT_ORDER
  - JGJ_ONLINE_SCENE_PRODUCT_RESERVE
  - JGJ_MULTI_PRODUCT_RESERVE
  is_supported: true
- candidate_id: behavior_candidate_017
  activity: ZEB_PRODUCT_SHARE
  intent_category: 转发分享了产品
  activity_template: 转发分享了产品“$productName$”
  description: 客户把保险产品、产品方案或产品链接转发给他人，核心动作是转发或分享产品，不是预约讲解或咨询服务。
  selection_notes: 原文明确“转发、分享、传播”产品或产品链接时选择本候选；即使对象名包含“家庭财富保障方案”，也不能改选方案讲解服务预约。只有“预约、咨询、讲解”才属于服务预约。
  aliases:
  - 转发分享了产品
  - 转发分享产品
  - 转发了产品
  - 分享了产品
  - 有过转发分享产品行为
  - 曾经转发分享产品
  - 转发分享产品记录
  positive_examples:
  - 找转发过保险产品方案的客户
  - 查询把产品链接分享给别人的客户
  - 哪些客户传播过产品介绍
  - 筛选有产品转发行为的客户
  negative_examples:
  - 查询预约家庭财富保障方案讲解的客户
  - 找咨询过某个产品的客户
  - 找没有转发分享产品的客户
  confusing_intents:
  - JGJ_FORTUNE_SERVICE_RESERVE
  - ZEB_INFO_SHARE
  is_supported: true
- candidate_id: behavior_candidate_018
  activity: ZEB_AGENTSTORE_SERVICE
  intent_category: 在保险小店中预约了服务
  activity_template: 在保险小店中，预约了服务“$serviceName$”
  description: 表示客户发生了“在保险小店中预约了服务”行为。
  aliases:
  - 在保险小店中预约了服务
  - 在保险小店中预约服务
  - 预约了服务
  - 在保险小店中预订了服务
  - 有过在保险小店中预约服务行为
  - 曾经在保险小店中预约服务
  - 在保险小店中预约服务记录
  positive_examples:
  - 找在保险小店中预约了服务的客户
  - 查询在保险小店中预约服务的人
  - 哪些客户预约了服务
  - 筛选出有过在保险小店中预订了服务行为的客户
  negative_examples:
  - 找没有在保险小店中预约服务的客户
  - 排除在保险小店中预约服务的客户
  - 查询从未在保险小店中预约服务的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_019
  activity: JGJ_PKT_ACTIVITY_01
  intent_category: 参加了金管家拼团活动并成功开团
  activity_template: 参加了金管家拼团活动“$activityName$”，并成功开团
  description: 客户发起、创建或组织金管家拼团并成功开团，在团中承担团长角色。
  selection_notes: “发起拼团、成功开团、创建团、组织拼团、做团长”选择本候选；加入或参团属于 JGJ_PKT_ACTIVITY_02，发起砍团属于 JGJ_PKT_ACTIVITY_03，帮砍不属于本候选。
  aliases:
  - 参加了金管家拼团活动并成功开团
  - 参加金管家拼团活动并成功开团
  - 参与了金管家拼团活动并成功开团
  - 有过参加金管家拼团活动并成功开团行为
  - 曾经参加金管家拼团活动并成功开团
  - 参加金管家拼团活动并成功开团记录
  positive_examples:
  - 找参加了金管家拼团活动并成功开团的客户
  - 查询参加金管家拼团活动并成功开团的人
  - 哪些客户参与了金管家拼团活动并成功开团
  - 筛选出有过参加金管家拼团活动并成功开团行为的客户
  negative_examples:
  - 找加入拼团或普通参团的客户
  - 查询帮助别人砍团的人
  - 找没有参加金管家拼团活动并成功开团的客户
  - 排除参加金管家拼团活动并成功开团的客户
  - 查询从未参加金管家拼团活动并成功开团的人
  confusing_intents:
  - JGJ_PKT_ACTIVITY_02
  - JGJ_PKT_ACTIVITY_03
  - JGJ_PKT_ACTIVITY_04
  is_supported: true
- candidate_id: behavior_candidate_020
  activity: ZEB_CARD_READEND
  intent_category: 查看贺卡时长秒
  activity_template: 查看贺卡“$cardName$”，时长$time$秒
  description: 客户查看、浏览或打开代理人发送的贺卡，事件可以记录查看时长。
  selection_notes: 时长是可选槽位，用户未说具体秒数仍可选择；查看资讯、专题或产品不属于该候选。
  aliases:
  - 查看贺卡时长秒
  - 浏览贺卡时长秒
  - 有过查看贺卡时长秒行为
  - 曾经查看贺卡时长秒
  - 查看贺卡时长秒记录
  positive_examples:
  - 找查看过我发送贺卡的客户
  - 查询打开或浏览贺卡的人
  - 哪些客户浏览贺卡时长秒
  - 筛选出有过查看贺卡时长秒行为的客户
  negative_examples:
  - 找查看资讯文章、专题或产品的人
  - 查询发送或制作贺卡但没有查看贺卡的人
  - 查询从未查看贺卡的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_021
  activity: KDE_USER_AGENT_RISK_ASSESSMENT_HOME_PENSION
  intent_category: 参观居家养老展厅展厅地址
  activity_template: 参观$branch$居家养老展厅，展厅地址：$showroomAddress$
  description: 表示客户发生了“参观居家养老展厅展厅地址”行为。
  aliases:
  - 参观居家养老展厅展厅地址
  - 有过参观居家养老展厅展厅地址行为
  - 曾经参观居家养老展厅展厅地址
  - 参观居家养老展厅展厅地址记录
  positive_examples:
  - 找参观居家养老展厅展厅地址的客户
  - 查询有过参观居家养老展厅展厅地址行为的人
  - 哪些客户曾经参观居家养老展厅展厅地址
  - 筛选出有过参观居家养老展厅展厅地址记录行为的客户
  negative_examples:
  - 找没有参观居家养老展厅展厅地址的客户
  - 排除参观居家养老展厅展厅地址的客户
  - 查询从未参观居家养老展厅展厅地址的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_022
  activity: scanCode_activity_01
  intent_category: 在面访扫码结束后参加码上有礼活动领取了权益
  activity_template: 在面访扫码结束后参加“码上有礼”活动，领取了权益“$rightsName$”
  description: 表示客户发生了“在面访扫码结束后参加码上有礼活动领取了权益”行为。
  aliases:
  - 在面访扫码结束后参加码上有礼活动领取了权益
  - 在面访扫码结束后参加码上有礼活动领取权益
  - 在面访扫码结束后参加码上有礼活动领过权益
  - 在面访扫码结束后参加码上有礼活动领过了权益
  - 有过在面访扫码结束后参加码上有礼活动领取权益行为
  - 曾经在面访扫码结束后参加码上有礼活动领取权益
  - 在面访扫码结束后参加码上有礼活动领取权益记录
  positive_examples:
  - 找在面访扫码结束后参加码上有礼活动领取了权益的客户
  - 查询在面访扫码结束后参加码上有礼活动领取权益的人
  - 哪些客户在面访扫码结束后参加码上有礼活动领过权益
  - 筛选出有过在面访扫码结束后参加码上有礼活动领过了权益行为的客户
  negative_examples:
  - 找没有在面访扫码结束后参加码上有礼活动领取权益的客户
  - 排除在面访扫码结束后参加码上有礼活动领取权益的客户
  - 查询从未在面访扫码结束后参加码上有礼活动领取权益的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_023
  activity: JGJ_PKT_ACTIVITY_03
  intent_category: 参加了金管家砍团活动并成功开团
  activity_template: 参加了金管家砍团活动“$activityName$”，并成功开团
  description: 表示客户发生了“参加了金管家砍团活动并成功开团”行为。
  aliases:
  - 参加了金管家砍团活动并成功开团
  - 参加金管家砍团活动并成功开团
  - 参与了金管家砍团活动并成功开团
  - 有过参加金管家砍团活动并成功开团行为
  - 曾经参加金管家砍团活动并成功开团
  - 参加金管家砍团活动并成功开团记录
  positive_examples:
  - 找参加了金管家砍团活动并成功开团的客户
  - 查询参加金管家砍团活动并成功开团的人
  - 哪些客户参与了金管家砍团活动并成功开团
  - 筛选出有过参加金管家砍团活动并成功开团行为的客户
  negative_examples:
  - 找没有参加金管家砍团活动并成功开团的客户
  - 排除参加金管家砍团活动并成功开团的客户
  - 查询从未参加金管家砍团活动并成功开团的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_024
  activity: ZEB_INFO_TITLE_VOTE
  intent_category: 在资讯中参与投票
  activity_template: 在资讯《$articleName$》中，参与投票“$voteName$”
  description: 表示客户发生了“在资讯中参与投票”行为。
  aliases:
  - 在资讯中参与投票
  - 在资讯中参加投票
  - 有过在资讯中参与投票行为
  - 曾经在资讯中参与投票
  - 在资讯中参与投票记录
  positive_examples:
  - 找在资讯中参与投票的客户
  - 查询在资讯中参加投票的人
  - 哪些客户有过在资讯中参与投票行为
  - 筛选出有过曾经在资讯中参与投票行为的客户
  negative_examples:
  - 找没有在资讯中参与投票的客户
  - 排除在资讯中参与投票的客户
  - 查询从未在资讯中参与投票的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_025
  activity: ZEB_TOPIC_READEND
  intent_category: 查看了资讯专题时长秒
  activity_template: 查看了资讯专题《$topicName$》，时长$time$秒
  description: 客户查看资讯专题，事件记录包含秒、分钟或停留时长信息。
  aliases:
  - 查看了资讯专题时长秒
  - 查看资讯专题时长秒
  - 看过资讯专题时长秒
  - 浏览了资讯专题时长秒
  - 有过查看资讯专题时长秒行为
  - 曾经查看资讯专题时长秒
  - 查看资讯专题时长秒记录
  positive_examples:
  - 找查看资讯专题超过一分钟的客户
  - 查询在某个资讯专题停留过一段时间的人
  - 哪些客户查看资讯专题时长秒
  - 筛选出有过看过资讯专题时长秒行为的客户
  negative_examples:
  - 找只转发资讯专题但没有查看的客户
  - 查询阅读单篇资讯文章时长的人
  - 查询从未查看资讯专题的人
  confusing_intents:
  - ZEB_INFO_READEND
  - JGJ_READ_ENJOY_N01
  - SYZQ_ZEB_INFO_READEND
  is_supported: true
- candidate_id: behavior_candidate_026
  activity: ZEB_ZT_PRODUCT_READ
  intent_category: 浏览车险报价单
  activity_template: 浏览车险报价单“$productName$”
  description: 表示客户发生了“浏览车险报价单”行为。
  aliases:
  - 浏览车险报价单
  - 查看车险报价单
  - 有过浏览车险报价单行为
  - 曾经浏览车险报价单
  - 浏览车险报价单记录
  positive_examples:
  - 找浏览车险报价单的客户
  - 查询查看车险报价单的人
  - 哪些客户有过浏览车险报价单行为
  - 筛选出有过曾经浏览车险报价单行为的客户
  negative_examples:
  - 找没有浏览车险报价单的客户
  - 排除浏览车险报价单的客户
  - 查询从未浏览车险报价单的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_027
  activity: JGJ_PKT_ACTIVITY_02
  intent_category: 参加了金管家拼团活动并成功参团
  activity_template: 参加了金管家拼团活动“$activityName$”，并成功参团
  description: 表示客户发生了“参加了金管家拼团活动并成功参团”行为。
  aliases:
  - 参加了金管家拼团活动并成功参团
  - 参加金管家拼团活动并成功参团
  - 参与了金管家拼团活动并成功参团
  - 有过参加金管家拼团活动并成功参团行为
  - 曾经参加金管家拼团活动并成功参团
  - 参加金管家拼团活动并成功参团记录
  positive_examples:
  - 找参加了金管家拼团活动并成功参团的客户
  - 查询参加金管家拼团活动并成功参团的人
  - 哪些客户参与了金管家拼团活动并成功参团
  - 筛选出有过参加金管家拼团活动并成功参团行为的客户
  negative_examples:
  - 找没有参加金管家拼团活动并成功参团的客户
  - 排除参加金管家拼团活动并成功参团的客户
  - 查询从未参加金管家拼团活动并成功参团的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_028
  activity: ZEB_PRODUCT_PAY
  intent_category: 点击支付
  activity_template: 购买产品“$productName$”时，点击支付
  description: 客户点击付款按钮、发起支付或进入产品购买的支付环节。
  selection_notes: 仅表示流程走到支付步骤；原句明确支付成功或支付失败时必须选择对应结果候选。
  aliases:
  - 点击支付
  - 点击付款
  - 点过支付
  - 点过付款按钮
  - 进入支付环节
  - 购买产品时点击支付
  - 点过支付按钮
  - 进入付款环节
  positive_examples:
  - 找已经走到支付这一步的客户
  - 查点击付款或发起支付但未说明结果的人
  - 找点击支付的客户
  - 查询点击付款的人
  - 哪些客户点过支付
  negative_examples:
  - 找支付成功的客户
  - 找支付失败的客户
  - 找没有点击支付的客户
  - 找完成支付的客户
  - 排除点击支付的客户
  confusing_intents:
  - ZEB_PRODUCT_PAY_FINISH
  - ZEB_PRODUCT_PAY_FAIL
  is_supported: true
- candidate_id: behavior_candidate_029
  activity: ZEB_INFO_READEND
  intent_category: 阅读了资讯阅读时长秒
  activity_template: 阅读了资讯《$articleName$》，阅读时长$time$秒
  description: 客户阅读普通单篇资讯或文章，事件包含文章名称和阅读时长。
  selection_notes: 未明确文章业务分类时优先选择；明确保险基础、名医出诊等 typeName 分类时选择分类文章阅读候选。
  aliases:
  - 阅读资讯文章时长
  - 阅读文章超过一段时间
  - 阅读了资讯阅读时长秒
  - 阅读资讯阅读时长秒
  - 读过资讯阅读时长秒
  - 看过资讯阅读时长秒
  - 有过阅读资讯阅读时长秒行为
  - 曾经阅读资讯阅读时长秒
  - 阅读资讯阅读时长秒记录
  positive_examples:
  - 找阅读某篇普通资讯超过一分钟的客户
  - 查询阅读具名文章并记录阅读时长的人
  - 哪些客户阅读资讯阅读时长秒
  - 筛选出有过读过资讯阅读时长秒行为的客户
  negative_examples:
  - 找明确阅读保险基础、名医出诊等分类文章的客户
  - 查询资讯专题或产品页面的查看时长
  - 找没有阅读资讯的客户
  - 查询从未阅读资讯的人
  confusing_intents:
  - SYZQ_ZEB_INFO_READEND
  is_supported: true
- candidate_id: behavior_candidate_030
  activity: ZEB_ZY_SHARE
  intent_category: 转发分享增员素材
  activity_template: 转发分享增员素材《$articleName$》
  description: 表示客户发生了“转发分享增员素材”行为。
  aliases:
  - 转发分享增员素材
  - 转发增员素材
  - 分享增员素材
  - 有过转发分享增员素材行为
  - 曾经转发分享增员素材
  - 转发分享增员素材记录
  positive_examples:
  - 找转发分享增员素材的客户
  - 查询转发增员素材的人
  - 哪些客户分享增员素材
  - 筛选出有过转发分享增员素材行为的客户
  negative_examples:
  - 找没有转发分享增员素材的客户
  - 排除转发分享增员素材的客户
  - 查询从未转发分享增员素材的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_031
  activity: P_C14
  intent_category: 填写客户信息
  activity_template: 购买$productName$已完成客户信息填写
  description: 客户在产品购买或投保流程中完成客户资料、投保资料或客户信息填写；处于客户信息提交之后也表示该阶段已经完成。
  selection_notes: 原文对象是“客户信息、客户资料、投保资料”时选择本候选，即使使用“提交”一词也不等于提交订单；只有明确订单信息、订单提交时才选择 ZEB_PRODUCT_SUBMIT。
  aliases:
  - 完成客户信息填写
  - 填写了客户信息
  - 购买产品时完成客户信息填写
  - 填完客户资料
  - 完成投保信息填写
  - 填写投保人信息
  - 做完客户信息填写
  - 购买已完成客户信息填写
  positive_examples:
  - 找完成客户信息填写的客户
  - 查询填写了客户信息的人
  - 哪些客户购买产品时完成客户信息填写
  - 筛选出有过填完客户资料行为的客户
  negative_examples:
  - 找提交订单的客户
  - 找没有完成客户信息填写的客户
  - 排除完成客户信息填写的客户
  - 查询从未完成客户信息填写的人
  confusing_intents:
  - ZEB_PRODUCT_SUBMIT
  is_supported: true
- candidate_id: behavior_candidate_032
  activity: JGJ_MEETINGE_BAO_SIGNUP_ONLINE
  intent_category: 邀请报名成功有意参加线下活动
  activity_template: 邀请函报名成功，有意参加线下活动“$activityName$”
  description: 表示客户发生了“邀请报名成功有意参加线下活动”行为。
  aliases:
  - 邀请报名成功有意参加线下活动
  - 有过邀请报名成功有意参加线下活动行为
  - 曾经邀请报名成功有意参加线下活动
  - 邀请报名成功有意参加线下活动记录
  positive_examples:
  - 找邀请报名成功有意参加线下活动的客户
  - 查询有过邀请报名成功有意参加线下活动行为的人
  - 哪些客户曾经邀请报名成功有意参加线下活动
  - 筛选出有过邀请报名成功有意参加线下活动记录行为的客户
  negative_examples:
  - 找没有邀请报名成功有意参加线下活动的客户
  - 排除邀请报名成功有意参加线下活动的客户
  - 查询从未邀请报名成功有意参加线下活动的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_033
  activity: scanCode_01
  intent_category: 完成了对TA的面访面访内容
  activity_template: 完成了对TA的面访，面访内容：$activityName$
  description: 代理人与客户已经完成面对面或线下面访，记录面访本身已经发生。
  selection_notes: 明确“完成面访、面对面拜访完成、已有面访记录”时选择本候选；只有明确评价、反馈、打分时才选择面对面拜访评价候选。
  aliases:
  - 完成了对TA的面访面访内容
  - 完成对TA的面访面访内容
  - 做完了对TA的面访面访内容
  - 有过完成对TA的面访面访内容行为
  - 曾经完成对TA的面访面访内容
  - 完成对TA的面访面访内容记录
  positive_examples:
  - 找完成了对TA的面访面访内容的客户
  - 查询完成对TA的面访面访内容的人
  - 哪些客户做完了对TA的面访面访内容
  - 筛选出有过完成对TA的面访面访内容行为的客户
  negative_examples:
  - 找对面对面拜访提交过评价的客户
  - 查询在线会客评价记录
  - 找没有完成对TA的面访面访内容的客户
  - 排除完成对TA的面访面访内容的客户
  - 查询从未完成对TA的面访面访内容的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_034
  activity: BZH_LIFE_PSSP_CUSTOMER_NEWS_NO2
  intent_category: 回访问卷中将您推荐给朋友的意愿较高为分看来Ta喜欢您提供的服务喔
  activity_template: $type$回访问卷中将您推荐给朋友的意愿较高为$number$分，看来Ta喜欢您提供的服务喔~
  description: 表示客户发生了“回访问卷中将您推荐给朋友的意愿较高为分看来Ta喜欢您提供的服务喔”行为。
  aliases:
  - 回访问卷中将您推荐给朋友的意愿较高为分
  - 回访问卷中将您推荐给朋友的意愿较高为分看来Ta喜欢您提供的服务喔
  - 回访问卷推荐意愿高
  - 愿意把您推荐给朋友
  - 服务推荐意愿评分较高
  - NPS推荐意愿高
  positive_examples:
  - 找回访问卷中将您推荐给朋友的意愿较高为分的客户
  - 查询回访问卷中将您推荐给朋友的意愿较高为分看来Ta喜欢您提供的服务喔的人
  - 哪些客户回访问卷推荐意愿高
  - 筛选出有过愿意把您推荐给朋友行为的客户
  negative_examples:
  - 找没有回访问卷中将您推荐给朋友的意愿较高为分的客户
  - 排除回访问卷中将您推荐给朋友的意愿较高为分的客户
  - 查询从未回访问卷中将您推荐给朋友的意愿较高为分的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_035
  activity: JGJ_READ_ENJOY_N01
  intent_category: 阅读了的文章时长秒
  activity_template: 阅读了$typeName$的文章《$articleName$》，时长$time$秒
  description: 客户阅读带明确 typeName 业务分类的文章，例如保险基础、名医出诊等类型。
  selection_notes: 只有原句在标题之外明确说明文章属于某个业务分类时选择；书名号中的文章标题、经营手册名称或标题里的保险词汇都不能当作 typeName 分类。只有文章标题时选择普通资讯阅读候选。
  aliases:
  - 阅读了的文章时长秒
  - 阅读的文章时长秒
  - 读过的文章时长秒
  - 看过的文章时长秒
  - 有过阅读的文章时长秒行为
  - 曾经阅读的文章时长秒
  - 阅读的文章时长秒记录
  positive_examples:
  - 找阅读保险基础类文章的客户
  - 查询看过名医出诊等明确分类文章的人
  - 哪些客户阅读的文章时长秒
  - 筛选出有过读过的文章时长秒行为的客户
  negative_examples:
  - 找只给出文章标题但没有文章分类的普通资讯阅读客户
  - 查询阅读某本经营手册或具名指南的客户
  - 查询阅读资讯专题或产品页面的人
  - 查询从未阅读文章的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_036
  activity: JGJ_WANGCAI_ACCOUNT
  intent_category: 开通了旺财账户
  activity_template: 开通了旺财账户
  description: 表示客户发生了“开通了旺财账户”行为。
  aliases:
  - 开通了旺财账户
  - 开通旺财账户
  - 开启了旺财账户
  - 有过开通旺财账户行为
  - 曾经开通旺财账户
  - 开通旺财账户记录
  positive_examples:
  - 找开通了旺财账户的客户
  - 查询开通旺财账户的人
  - 哪些客户开启了旺财账户
  - 筛选出有过开通旺财账户行为的客户
  negative_examples:
  - 找没有开通旺财账户的客户
  - 排除开通旺财账户的客户
  - 查询从未开通旺财账户的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_037
  activity: JGJ_OPERATE_WON_PRIZE
  intent_category: 在金管家活动中获得奖品
  activity_template: 在金管家活动“$activityName$”中，获得奖品$prizeName$
  description: 客户在金管家活动中中奖、获奖或已经拿到奖品，表达的是获奖结果本身。
  selection_notes: “中奖、获奖、拿到奖品、获得奖品”选择本候选；明确奖品需要代理人递送或上门配送时选择 JGJ_ACTIVITY_REAl_PRIZE，团活动待配送选择 JGJ_SH_MS_PT。
  aliases:
  - 在金管家活动中获得奖品
  - 活动中获得奖品
  - 有过活动中获得奖品行为
  - 曾经活动中获得奖品
  - 活动中获得奖品记录
  positive_examples:
  - 找在金管家活动中中奖并获得奖品的客户
  - 查询活动获奖名单
  - 哪些客户有过活动中获得奖品行为
  - 筛选出有过曾经活动中获得奖品行为的客户
  negative_examples:
  - 找领取奖品后需要代理人上门配送的客户
  - 查询在俱乐部领取权益的人
  - 查询从未活动中获得奖品的人
  confusing_intents:
  - JGJ_ACTIVITY_REAl_PRIZE
  - JGJ_CLUB_RIGHT_GET
  is_supported: true
- candidate_id: behavior_candidate_038
  activity: ZEB_INFO_THUMBSUP
  intent_category: 点赞了资讯
  activity_template: 点赞了资讯《$articleName$》
  description: 客户对资讯文章执行点赞或点过赞操作。
  aliases:
  - 点赞了资讯
  - 点赞资讯
  - 点过赞资讯
  - 给文章点赞
  - 给资讯文章点了赞
  - 文章点赞记录
  - 有过点赞资讯行为
  - 曾经点赞资讯
  - 点赞资讯记录
  positive_examples:
  - 找给资讯文章点过赞的客户
  - 查询文章点赞记录
  - 哪些客户点过赞资讯
  - 筛选出有过点赞资讯行为的客户
  negative_examples:
  - 找没有点赞资讯的客户
  - 排除点赞资讯的客户
  - 查询从未点赞资讯的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_039
  activity: ZEB_ZT_PRODUCT_READEND
  intent_category: 浏览了车险报价单时长秒
  activity_template: 浏览了车险报价单“$productName$”，时长$time$秒
  description: 表示客户发生了“浏览了车险报价单时长秒”行为。
  aliases:
  - 浏览了车险报价单时长秒
  - 浏览车险报价单时长秒
  - 看过车险报价单时长秒
  - 查看了车险报价单时长秒
  - 有过浏览车险报价单时长秒行为
  - 曾经浏览车险报价单时长秒
  - 浏览车险报价单时长秒记录
  positive_examples:
  - 找浏览车险报价单超过一分钟的客户
  - 查询浏览了车险报价单时长秒的人
  - 哪些客户浏览车险报价单时长秒
  - 筛选出有过看过车险报价单时长秒行为的客户
  negative_examples:
  - 找没有浏览车险报价单的客户
  - 排除浏览车险报价单的客户
  - 查询从未浏览车险报价单的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_040
  activity: ZEB_ZY_READEND
  intent_category: 查看了增员素材时长秒
  activity_template: 查看了增员素材《$articleName$》，时长$time$秒
  description: 客户查看增员素材，事件记录包含秒、分钟或停留时长信息。
  aliases:
  - 查看了增员素材时长秒
  - 查看增员素材时长秒
  - 看过增员素材时长秒
  - 浏览了增员素材时长秒
  - 有过查看增员素材时长秒行为
  - 曾经查看增员素材时长秒
  - 查看增员素材时长秒记录
  positive_examples:
  - 找查看增员素材超过一分钟的客户
  - 查询在增员素材中停留过一段时间的人
  - 哪些客户查看增员素材时长秒
  - 筛选出有过看过增员素材时长秒行为的客户
  negative_examples:
  - 找看过增员素材但没有提及时长的人
  - 查询转发过增员素材的人
  - 查询从未查看增员素材的人
  confusing_intents:
  - ZEB_ZY_READ
  is_supported: true
- candidate_id: behavior_candidate_041
  activity: smartVisit_evaluate
  intent_category: 在智能拜访助手-在线会客中进行了会客评价
  activity_template: 在智能拜访助手-在线会客中，进行了会客评价
  description: 表示客户发生了“在智能拜访助手-在线会客中进行了会客评价”行为。
  aliases:
  - 在智能拜访助手-在线会客中进行了会客评价
  - 在智能拜访助手-在线会客中进行会客评价
  - -在线会客中进行了会客评价
  - 有过-在线会客中进行会客评价行为
  - 曾经-在线会客中进行会客评价
  - -在线会客中进行会客评价记录
  positive_examples:
  - 找在智能拜访助手-在线会客中进行了会客评价的客户
  - 查询在智能拜访助手-在线会客中进行会客评价的人
  - 哪些客户-在线会客中进行了会客评价
  - 筛选出有过-在线会客中进行会客评价行为的客户
  negative_examples:
  - 找没有-在线会客中进行会客评价的客户
  - 排除-在线会客中进行会客评价的客户
  - 查询从未-在线会客中进行会客评价的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_042
  activity: homeBasedCare_read
  intent_category: 用户在金管家居家养老专区内浏览了
  activity_template: 用户在金管家居家养老专区内浏览了《$content$》
  description: 客户进入金管家居家养老专区并浏览、查看其中的内容或服务介绍，核心事实是专区内的内容浏览。
  selection_notes: 原文明确“进入、浏览、查看、看过居家养老专区或专区内容”时选择本候选；仅表达对居家养老服务感兴趣或关注服务、但没有专区浏览事实时不选。
  aliases:
  - 用户在金管家居家养老专区内浏览了
  - 用户在金管家居家养老专区内浏览
  - 居家养老专区内浏览了
  - 用户在金管家居家养老专区内看过
  - 用户在金管家居家养老专区内查看了
  - 有过居家养老专区内浏览行为
  - 曾经居家养老专区内浏览
  - 居家养老专区内浏览记录
  positive_examples:
  - 找浏览过金管家居家养老专区的客户
  - 查询查看过养老专区服务内容的人
  - 哪些客户进入专区看过内容
  - 筛选有居家养老专区浏览记录的客户
  negative_examples:
  - 找关注家庭陪护服务的客户
  - 查询对居家养老健康管理感兴趣的人
  - 找没有居家养老专区内浏览的客户
  confusing_intents:
  - JGJ_JJYL_SERVICE_RESERVE
  is_supported: true
- candidate_id: behavior_candidate_043
  activity: ZEB_PRODUCT_PAY_FINISH
  intent_category: 完成支付
  activity_template: 购买产品“$productName$”时，完成支付
  description: 表示客户发生了“完成支付”行为。
  aliases:
  - 完成支付
  - 支付成功
  - 付款成功
  - 购买产品时完成支付
  - 完成付款
  - 做完支付
  - 购买产品时做完支付
  - 买过产品时完成支付
  positive_examples:
  - 找完成支付的客户
  - 查询支付成功的人
  - 哪些客户付款成功
  - 筛选出有过购买产品时完成支付行为的客户
  negative_examples:
  - 点击支付
  - 支付失败
  - 没有支付成功
  - 找购买成功的客户
  - 找点击支付的客户
  confusing_intents:
  - ZEB_PRODUCT_BUY
  - ZEB_PRODUCT_PAY
  - ZEB_PRODUCT_PAY_FAIL
  is_supported: true
- candidate_id: behavior_candidate_044
  activity: ZEB_VIDEO_READEND
  intent_category: 浏览了展业短视频时长秒
  activity_template: 浏览了展业短视频“$videoName$”，时长$time$秒
  description: 表示客户发生了“浏览了展业短视频时长秒”行为。
  aliases:
  - 浏览了展业短视频时长秒
  - 浏览展业短视频时长秒
  - 看过展业短视频时长秒
  - 查看了展业短视频时长秒
  - 有过浏览展业短视频时长秒行为
  - 曾经浏览展业短视频时长秒
  - 浏览展业短视频时长秒记录
  positive_examples:
  - 找浏览展业短视频超过一分钟的客户
  - 查询浏览了展业短视频时长秒的人
  - 哪些客户浏览展业短视频时长秒
  - 筛选出有过看过展业短视频时长秒行为的客户
  negative_examples:
  - 找没有浏览展业短视频的客户
  - 排除浏览展业短视频的客户
  - 查询从未浏览展业短视频的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_045
  activity: ZEB_PRODUCT_READEND
  intent_category: 浏览了产品浏览时长秒
  activity_template: 浏览了产品“$productName$”，浏览时长$time$秒
  description: 客户浏览或查看某个产品，事件记录包含秒、分钟或停留时长信息。
  aliases:
  - 浏览产品时长
  - 查看产品停留时长
  - 在产品页面停留
  - 浏览产品若干秒
  - 产品浏览了多久
  - 浏览了产品浏览时长秒
  - 浏览产品浏览时长秒
  - 看过产品浏览时长秒
  - 查看了产品浏览时长秒
  - 有过浏览产品浏览时长秒行为
  - 曾经浏览产品浏览时长秒
  - 浏览产品浏览时长秒记录
  positive_examples:
  - 找浏览某个产品若干秒的客户
  - 查询在产品页面停留过一段时间的人
  - 哪些客户浏览产品浏览时长秒
  - 筛选出有过看过产品浏览时长秒行为的客户
  negative_examples:
  - 找只说看过产品但没有时长线索的人
  - 查询在资讯中进一步查看产品的客户
  - 查询从未浏览产品的人
  confusing_intents:
  - ZEB_INFO_PRODUCT
  - SYZQ_ZEB_INFO_PRODUCT
  is_supported: true
- candidate_id: behavior_candidate_046
  activity: ZEB_PRODUCT_ORDER
  intent_category: 在口袋E产品贴中预约产品咨询
  activity_template: 在口袋E产品贴“$productName$”中，预约产品咨询
  description: 客户从口袋E产品贴页面发起产品咨询预约。
  aliases:
  - 在口袋E产品贴中预约产品咨询
  - 产品贴中预约产品咨询
  - 在口袋E产品贴中预订产品咨询
  - 有过产品贴中预约产品咨询行为
  - 曾经产品贴中预约产品咨询
  - 产品贴中预约产品咨询记录
  positive_examples:
  - 找从口袋E产品贴预约咨询的客户
  - 查询在产品贴页面提交产品咨询的人
  - 哪些客户在口袋E产品贴中预订产品咨询
  - 筛选出有过产品贴中预约产品咨询行为的客户
  negative_examples:
  - 找阅读口袋E资讯后预约产品咨询的客户
  - 查询在金管家直接预约产品的人
  - 查询从未产品贴中预约产品咨询的人
  confusing_intents:
  - ZEB_INFO_ORDER
  - JGJ_ONLINE_SCENE_PRODUCT_RESERVE
  - JGJ_MULTI_PRODUCT_RESERVE
  is_supported: true
- candidate_id: behavior_candidate_047
  activity: ZEB_INFO_TITLE_PK
  intent_category: 在资讯中参与话题PK
  activity_template: 在资讯《$articleName$》中，参与话题PK“$Pkname$”
  description: 表示客户发生了“在资讯中参与话题PK”行为。
  aliases:
  - 在资讯中参与话题PK
  - 参与话题PK
  - 在资讯中参加话题PK
  - 有过参与话题PK行为
  - 曾经参与话题PK
  - 参与话题PK记录
  positive_examples:
  - 找在资讯中参与话题PK的客户
  - 查询参与话题PK的人
  - 哪些客户在资讯中参加话题PK
  - 筛选出有过参与话题PK行为的客户
  negative_examples:
  - 找没有参与话题PK的客户
  - 排除参与话题PK的客户
  - 查询从未参与话题PK的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_048
  activity: JGJ_OPERATE_SIGN_UP
  intent_category: 报名参加了金管家活动
  activity_template: 报名参加了金管家活动“$activityName$”
  description: 客户报名参加普通金管家活动。
  aliases:
  - 报名参加了金管家活动
  - 报名参加金管家活动
  - 报名了金管家活动
  - 报名参与了金管家活动
  - 有过报名参加金管家活动行为
  - 曾经报名参加金管家活动
  - 报名参加金管家活动记录
  positive_examples:
  - 找报名普通金管家活动的客户
  - 查询提交过金管家活动报名的人
  - 哪些客户报名了金管家活动
  - 筛选出有过报名参与了金管家活动行为的客户
  negative_examples:
  - 找在金管家俱乐部里报名活动的客户
  - 查询参加拼团并成功参团的人
  - 查询从未报名参加金管家活动的人
  confusing_intents:
  - JGJ_PKT_ACTIVITY_02
  - JGJ_ACTIVITY_APPLY_CHECK
  - JGJ_CLUB_ACTIVITY_JOIN
  - jgj_real_activity_OlderDance_Apply
  - jgj_real_activity_OlderDance_Creat
  is_supported: true
- candidate_id: behavior_candidate_049
  activity: JGJ_PKT_ACTIVITY_04
  intent_category: 参加了金管家砍团活动并成功帮砍
  activity_template: 参加了金管家砍团活动“$activityName$”，并成功帮砍
  description: 表示客户发生了“参加了金管家砍团活动并成功帮砍”行为。
  aliases:
  - 参加了金管家砍团活动并成功帮砍
  - 参加金管家砍团活动并成功帮砍
  - 参与了金管家砍团活动并成功帮砍
  - 有过参加金管家砍团活动并成功帮砍行为
  - 曾经参加金管家砍团活动并成功帮砍
  - 参加金管家砍团活动并成功帮砍记录
  positive_examples:
  - 找参加了金管家砍团活动并成功帮砍的客户
  - 查询参加金管家砍团活动并成功帮砍的人
  - 哪些客户参与了金管家砍团活动并成功帮砍
  - 筛选出有过参加金管家砍团活动并成功帮砍行为的客户
  negative_examples:
  - 找没有参加金管家砍团活动并成功帮砍的客户
  - 排除参加金管家砍团活动并成功帮砍的客户
  - 查询从未参加金管家砍团活动并成功帮砍的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_050
  activity: JGJ_MEETINGE_BAO_PRODUCT_PURCHASE
  intent_category: 在参加线下活动时预购了产品金额元
  activity_template: 在参加线下活动“$activityName$”时，预购了产品$productName$，金额$productPrize$元
  description: 表示客户发生了“在参加线下活动时预购了产品金额元”行为。
  aliases:
  - 在参加线下活动时预购了产品金额元
  - 在参加线下活动时预购产品金额元
  - 有过在参加线下活动时预购产品金额元行为
  - 曾经在参加线下活动时预购产品金额元
  - 在参加线下活动时预购产品金额元记录
  positive_examples:
  - 找在参加线下活动时预购了产品金额元的客户
  - 查询在参加线下活动时预购产品金额元的人
  - 哪些客户有过在参加线下活动时预购产品金额元行为
  - 筛选出有过曾经在参加线下活动时预购产品金额元行为的客户
  negative_examples:
  - 找没有在参加线下活动时预购产品金额元的客户
  - 排除在参加线下活动时预购产品金额元的客户
  - 查询从未在参加线下活动时预购产品金额元的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_051
  activity: KDE_BDTG_DTG
  intent_category: 完成了保单托管授权
  activity_template: 完成了保单托管授权
  description: 表示客户发生了“完成了保单托管授权”行为。
  aliases:
  - 完成了保单托管授权
  - 完成保单托管授权
  - 做完了保单托管授权
  - 有过完成保单托管授权行为
  - 曾经完成保单托管授权
  - 完成保单托管授权记录
  positive_examples:
  - 找完成了保单托管授权的客户
  - 查询完成保单托管授权的人
  - 哪些客户做完了保单托管授权
  - 筛选出有过完成保单托管授权行为的客户
  negative_examples:
  - 找没有完成保单托管授权的客户
  - 排除完成保单托管授权的客户
  - 查询从未完成保单托管授权的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_052
  activity: LAIP_IVAP_VIDEO_N03
  intent_category: 浏览了跟拍视频
  activity_template: 浏览了跟拍视频$videoTitle$
  description: 表示客户发生了“浏览了跟拍视频”行为。
  aliases:
  - 浏览了跟拍视频
  - 浏览跟拍视频
  - 看过跟拍视频
  - 查看了跟拍视频
  - 有过浏览跟拍视频行为
  - 曾经浏览跟拍视频
  - 浏览跟拍视频记录
  positive_examples:
  - 找浏览了跟拍视频的客户
  - 查询浏览跟拍视频的人
  - 哪些客户看过跟拍视频
  - 筛选出有过查看了跟拍视频行为的客户
  negative_examples:
  - 找没有浏览跟拍视频的客户
  - 排除浏览跟拍视频的客户
  - 查询从未浏览跟拍视频的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_053
  activity: ZEB_PRODUCT_SUBMIT
  intent_category: 提交订单
  activity_template: 购买产品“$productName$”时，提交订单信息
  description: 客户在产品购买流程中已经填写并提交订单或订单信息，可能尚未进入支付或尚未付款。
  selection_notes: “填完订单、提交订单、订单已提交”选择本候选；“还没支付、未付款”只说明后续支付尚未发生，不能额外输出点击支付。客户资料填写属于 P_C14。
  aliases:
  - 提交订单
  - 提交订单信息
  - 购买产品时提交订单信息
  - 递交订单信息
  - 下单并提交
  - 递交订单
  - 购买产品时递交订单信息
  - 买过产品时提交订单信息
  positive_examples:
  - 找提交订单的客户
  - 查询提交订单信息的人
  - 哪些客户购买产品时提交订单信息
  - 筛选出有过递交订单信息行为的客户
  negative_examples:
  - 找完成客户信息填写的客户
  - 找完成购买的客户
  - 找只点击支付但没有提交订单语义的客户
  - 找没有提交订单的客户
  - 排除提交订单的客户
  - 查询从未提交订单的人
  confusing_intents:
  - P_C14
  - JGJ_Product_Succeed
  is_supported: true
- candidate_id: behavior_candidate_054
  activity: JGJ_Product_Succeed
  intent_category: 完成购买
  activity_template: 完成购买《$productName$》
  description: 表示客户发生了“完成购买”行为。
  aliases:
  - 完成购买
  - 买完产品
  - 完成产品购买
  - 做完购买
  - 有过完成购买行为
  - 曾经完成购买
  - 完成购买记录
  positive_examples:
  - 找完成购买的客户
  - 查询买完产品的人
  - 哪些客户完成产品购买
  - 筛选出有过做完购买行为的客户
  negative_examples:
  - 找购买成功的客户
  - 找完成支付的客户
  - 找没有完成购买的客户
  - 排除完成购买的客户
  - 查询从未完成购买的人
  confusing_intents:
  - ZEB_PRODUCT_BUY
  - ZEB_PRODUCT_PAY_FINISH
  - JGJ_Product_YJX_BUY_SUCCESS
  is_supported: true
- candidate_id: behavior_candidate_055
  activity: ZEB_PRODUCT_PAY_FAIL
  intent_category: 支付失败
  activity_template: 购买产品“$productName$”时，支付失败
  description: 表示客户发生了“支付失败”行为。
  aliases:
  - 支付失败
  - 付款失败
  - 购买产品时支付失败
  - 支付未成功
  - 买过产品时支付失败
  - 购买产品时支付未成功
  - 有过支付失败行为
  - 曾经支付失败
  positive_examples:
  - 找支付失败的客户
  - 查询付款失败的人
  - 哪些客户购买产品时支付失败
  - 筛选出有过支付未成功行为的客户
  negative_examples:
  - 点击支付
  - 完成支付
  - 支付成功
  - 找点击支付的客户
  - 找完成支付的客户
  confusing_intents:
  - ZEB_PRODUCT_PAY
  - ZEB_PRODUCT_PAY_FINISH
  is_supported: true
- candidate_id: behavior_candidate_056
  activity: ZEB_INFO_PRODUCT
  intent_category: 在资讯中查看了产品
  activity_template: 在资讯《$articleName$》中，查看了产品“$productName$”
  description: 客户阅读资讯或文章时，从资讯内容进一步进入并查看保险产品或产品详情，事件同时包含资讯来源和产品查看动作。
  selection_notes: 必须同时保留“资讯/文章来源”和“查看/进入产品”的跨内容动作；只浏览资讯选资讯阅读，只直接浏览产品选产品浏览，只在活动中查看方案选活动产品兴趣。
  aliases:
  - 在资讯中查看了产品
  - 在资讯中查看产品
  - 查看了产品
  - 在资讯中看过产品
  - 在资讯中浏览了产品
  - 有过在资讯中查看产品行为
  - 曾经在资讯中查看产品
  - 在资讯中查看产品记录
  positive_examples:
  - 找从资讯文章点进产品详情的客户
  - 查询看文章时进一步查看保险产品的人
  - 哪些客户通过资讯内容进入了产品页面
  - 筛选资讯带来的产品浏览客户
  negative_examples:
  - 找在活动中查看臻享医方案的客户
  - 找只阅读过资讯文章的客户
  - 查询直接浏览产品详情的人
  - 找没有在资讯中查看产品的客户
  confusing_intents:
  - SYZQ_ZEB_INFO_PRODUCT
  is_supported: true
- candidate_id: behavior_candidate_057
  activity: smartVisit_ftf_evaluate
  intent_category: 在智能拜访助手-面对面拜访进行了评价
  activity_template: 在智能拜访助手-面对面拜访中，进行了评价
  description: 表示客户发生了“在智能拜访助手-面对面拜访进行了评价”行为。
  aliases:
  - 在智能拜访助手-面对面拜访进行了评价
  - 在智能拜访助手-面对面拜访进行评价
  - -面对面拜访进行了评价
  - 有过-面对面拜访进行评价行为
  - 曾经-面对面拜访进行评价
  - -面对面拜访进行评价记录
  positive_examples:
  - 找在智能拜访助手-面对面拜访进行了评价的客户
  - 查询在智能拜访助手-面对面拜访进行评价的人
  - 哪些客户-面对面拜访进行了评价
  - 筛选出有过-面对面拜访进行评价行为的客户
  negative_examples:
  - 找没有-面对面拜访进行评价的客户
  - 排除-面对面拜访进行评价的客户
  - 查询从未-面对面拜访进行评价的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_058
  activity: ZEB_PRODUCT_UNDERWRITE
  intent_category: 核保成功
  activity_template: 购买产品“$productName$”时，核保成功
  description: 寿险或健康险产品购买流程中的核保成功或核保通过。
  selection_notes: 原句明确车辆、车险或汽车核保时必须选择车辆核保结论候选，不选本候选。
  aliases:
  - 核保成功
  - 通过核保
  - 购买产品时核保成功
  - 核保通过
  - 买过产品时核保成功
  - 有过核保成功行为
  - 曾经核保成功
  - 核保成功记录
  positive_examples:
  - 找核保成功的客户
  - 查询通过核保的人
  - 哪些客户购买产品时核保成功
  - 筛选出有过核保通过行为的客户
  negative_examples:
  - 找车辆、车险或汽车核保通过的客户
  - 找寿险产品核保失败或未通过的客户
  - 排除核保成功的客户
  - 查询从未核保成功的人
  confusing_intents:
  - ZEB_PRODUCT_UNDERWRITE_FAIL
  is_supported: true
- candidate_id: behavior_candidate_059
  activity: ZEB_INFO_SHARE
  intent_category: 转发分享了资讯
  activity_template: 转发分享了资讯《$articleName$》
  description: 客户转发或分享资讯内容，原始内容槽位类型为专题名称。
  aliases:
  - 转发分享了资讯
  - 转发分享资讯
  - 转发了资讯
  - 分享了资讯
  - 有过转发分享资讯行为
  - 曾经转发分享资讯
  - 转发分享资讯记录
  positive_examples:
  - 找转发分享了资讯的客户
  - 查询转发分享资讯的人
  - 哪些客户转发了资讯
  - 筛选出有过分享了资讯行为的客户
  negative_examples:
  - 找明确转发资讯专题的客户
  - 查询明确分享资讯文章的人
  - 查询从未转发分享资讯的人
  confusing_intents:
  - ZEB_TOPIC_SHARE
  - SYZQ_ZEB_INFO_SHARE
  is_supported: true
- candidate_id: behavior_candidate_060
  activity: ZEB_VIDEO_SHARE
  intent_category: 转发分享了展业短视频
  activity_template: 转发分享了展业短视频“$videoName$”
  description: 表示客户发生了“转发分享了展业短视频”行为。
  aliases:
  - 转发分享了展业短视频
  - 转发分享展业短视频
  - 转发了展业短视频
  - 分享了展业短视频
  - 有过转发分享展业短视频行为
  - 曾经转发分享展业短视频
  - 转发分享展业短视频记录
  positive_examples:
  - 找转发分享了展业短视频的客户
  - 查询转发分享展业短视频的人
  - 哪些客户转发了展业短视频
  - 筛选出有过分享了展业短视频行为的客户
  negative_examples:
  - 找没有转发分享展业短视频的客户
  - 排除转发分享展业短视频的客户
  - 查询从未转发分享展业短视频的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_061
  activity: JGJ_CHRONIC_DISEASE_03
  intent_category: 赠送了亲友慢病服务包
  activity_template: 赠送了亲友慢病服务包
  description: 表示客户发生了“赠送了亲友慢病服务包”行为。
  aliases:
  - 赠送了亲友慢病服务包
  - 赠送亲友慢病服务包
  - 有过赠送亲友慢病服务包行为
  - 曾经赠送亲友慢病服务包
  - 赠送亲友慢病服务包记录
  positive_examples:
  - 找赠送了亲友慢病服务包的客户
  - 查询赠送亲友慢病服务包的人
  - 哪些客户有过赠送亲友慢病服务包行为
  - 筛选出有过曾经赠送亲友慢病服务包行为的客户
  negative_examples:
  - 找没有赠送亲友慢病服务包的客户
  - 排除赠送亲友慢病服务包的客户
  - 查询从未赠送亲友慢病服务包的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_062
  activity: JGJ_MEETINGE_BAO_TRAIN_SIGNUP
  intent_category: 在参加线下活动时报名了岗职培训班
  activity_template: 在参加线下活动“$activityName$”时，报名了岗职培训班
  description: 表示客户发生了“在参加线下活动时报名了岗职培训班”行为。
  aliases:
  - 在参加线下活动时报名了岗职培训班
  - 在参加线下活动时报名岗职培训班
  - 在参加线下活动时报了名岗职培训班
  - 有过在参加线下活动时报名岗职培训班行为
  - 曾经在参加线下活动时报名岗职培训班
  - 在参加线下活动时报名岗职培训班记录
  positive_examples:
  - 找在参加线下活动时报名了岗职培训班的客户
  - 查询在参加线下活动时报名岗职培训班的人
  - 哪些客户在参加线下活动时报了名岗职培训班
  - 筛选出有过在参加线下活动时报名岗职培训班行为的客户
  negative_examples:
  - 找没有在参加线下活动时报名岗职培训班的客户
  - 排除在参加线下活动时报名岗职培训班的客户
  - 查询从未在参加线下活动时报名岗职培训班的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_063
  activity: BZH_LIFE_PSSP_CUSTOMER_NEWS_NO1
  intent_category: 回访问卷中对您的服务满意度为看来Ta喜欢您提供的服务喔
  activity_template: $type$回访问卷中对您的服务满意度为$content$，看来Ta喜欢您提供的服务喔~
  description: 表示客户发生了“回访问卷中对您的服务满意度为看来Ta喜欢您提供的服务喔”行为。
  aliases:
  - 回访问卷中对您的服务满意度为
  - 回访问卷中对您的服务满意度为看来Ta喜欢您提供的服务喔
  - 回访问卷服务满意
  - 服务满意度较高
  - 回访评价服务满意
  - 客户对服务满意
  positive_examples:
  - 找回访问卷中对您的服务满意度为的客户
  - 查询回访问卷中对您的服务满意度为看来Ta喜欢您提供的服务喔的人
  - 哪些客户回访问卷服务满意
  - 筛选出有过服务满意度较高行为的客户
  negative_examples:
  - 找没有回访问卷中对您的服务满意度为的客户
  - 排除回访问卷中对您的服务满意度为的客户
  - 查询从未回访问卷中对您的服务满意度为的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_064
  activity: ZSB_PROPOSAL_WECHATSHARE_01
  intent_category: 在微信中打开了建议书
  activity_template: 在微信中打开了$productName$建议书
  description: 表示客户发生了“在微信中打开了建议书”行为。
  aliases:
  - 在微信中打开了建议书
  - 在微信中打开建议书
  - 打开了建议书
  - 有过打开建议书行为
  - 曾经打开建议书
  - 打开建议书记录
  positive_examples:
  - 找在微信中打开了建议书的客户
  - 查询在微信中打开建议书的人
  - 哪些客户打开了建议书
  - 筛选出有过打开建议书行为的客户
  negative_examples:
  - 找没有打开建议书的客户
  - 排除打开建议书的客户
  - 查询从未打开建议书的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_065
  activity: KDE_BDTG_DFH
  intent_category: 已完成1份保单照片上传
  activity_template: 已完成1份保单照片上传
  description: 表示客户发生了“已完成1份保单照片上传”行为。
  aliases:
  - 已完成1份保单照片上传
  - 已做完1份保单照片上传
  - 有过已完成1份保单照片上传行为
  - 曾经已完成1份保单照片上传
  - 已完成1份保单照片上传记录
  positive_examples:
  - 找已完成1份保单照片上传的客户
  - 查询已做完1份保单照片上传的人
  - 哪些客户有过已完成1份保单照片上传行为
  - 筛选出有过曾经已完成1份保单照片上传行为的客户
  negative_examples:
  - 找没有已完成1份保单照片上传的客户
  - 排除已完成1份保单照片上传的客户
  - 查询从未已完成1份保单照片上传的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_066
  activity: LAIP_IVAP_VIDEO_N02
  intent_category: 预约了跟拍视频
  activity_template: 预约了跟拍视频$videoTitle$
  description: 表示客户发生了“预约了跟拍视频”行为。
  aliases:
  - 预约了跟拍视频
  - 预约跟拍视频
  - 预订了跟拍视频
  - 有过预约跟拍视频行为
  - 曾经预约跟拍视频
  - 预约跟拍视频记录
  positive_examples:
  - 找预约了跟拍视频的客户
  - 查询预约跟拍视频的人
  - 哪些客户预订了跟拍视频
  - 筛选出有过预约跟拍视频行为的客户
  negative_examples:
  - 找没有预约跟拍视频的客户
  - 排除预约跟拍视频的客户
  - 查询从未预约跟拍视频的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_067
  activity: ZEB_PRODUCT_UNDERWRITE_FAIL
  intent_category: 核保失败
  activity_template: 购买产品“$productName$”时，核保失败
  description: 寿险或健康险产品购买流程中的核保失败、未通过或不成功。
  selection_notes: 原句明确车辆、车险或汽车核保时必须选择车辆核保结论候选，不选本候选。
  aliases:
  - 核保失败
  - 未通过核保
  - 购买产品时核保失败
  - 核保未通过
  - 核保未成功
  - 买过产品时核保失败
  - 购买产品时核保未成功
  - 有过核保失败行为
  positive_examples:
  - 找核保失败的客户
  - 查询未通过核保的人
  - 哪些客户购买产品时核保失败
  - 筛选出有过核保未通过行为的客户
  negative_examples:
  - 找车辆、车险或汽车核保未通过的客户
  - 找寿险产品核保成功或通过的客户
  - 排除核保失败的客户
  - 查询从未核保失败的人
  confusing_intents:
  - ZEB_PRODUCT_UNDERWRITE
  is_supported: true
- candidate_id: behavior_candidate_068
  activity: futureCity_read
  intent_category: 参观了平安未来城线上展厅本次参观时长参观的场馆有
  activity_template: 参观了平安未来城线上展厅，本次参观时长$opaDuration$，参观的场馆有$opaRooms$
  description: 表示客户发生了“参观了平安未来城线上展厅本次参观时长参观的场馆有”行为。
  aliases:
  - 参观了平安未来城线上展厅本次参观时长参观的场馆有
  - 参观平安未来城线上展厅本次参观时长参观的场馆有
  - 有过参观平安未来城线上展厅本次参观时长参观的场馆有行为
  - 曾经参观平安未来城线上展厅本次参观时长参观的场馆有
  - 参观平安未来城线上展厅本次参观时长参观的场馆有记录
  positive_examples:
  - 找参观了平安未来城线上展厅本次参观时长参观的场馆有的客户
  - 查询参观平安未来城线上展厅本次参观时长参观的场馆有的人
  - 哪些客户有过参观平安未来城线上展厅本次参观时长参观的场馆有行为
  - 筛选出有过曾经参观平安未来城线上展厅本次参观时长参观的场馆有行为的客户
  negative_examples:
  - 找没有参观平安未来城线上展厅本次参观时长参观的场馆有的客户
  - 排除参观平安未来城线上展厅本次参观时长参观的场馆有的客户
  - 查询从未参观平安未来城线上展厅本次参观时长参观的场馆有的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_069
  activity: careExhibition_signup
  intent_category: 报名了的参观
  activity_template: 报名了$time$的$showroomName$参观
  description: 客户预约或报名在指定时间参观某个线下展厅。
  aliases:
  - 预约展厅参观
  - 展厅参观预约
  - 报名参观展厅
  - 预约线下展厅
  - 展厅预约记录
  positive_examples:
  - 找预约参观线下展厅的客户
  - 查询指定时间的展厅预约名单
  - 哪些客户报名参观过展厅
  - 筛选提交过展厅参观预约的客户
  negative_examples:
  - 找已经到访并完成展厅参观的客户
  - 查询线上展厅浏览时长记录
  - 查询从未预约展厅参观的人
  confusing_intents:
  - KDE_USER_AGENT_RISK_ASSESSMENT_HOME_PENSION
  - futureCity_read
  is_supported: true
- candidate_id: behavior_candidate_070
  activity: ZEB_TOOL_READ_SERVICE_ORDER
  intent_category: 在工具中留资预约了服务讲解
  activity_template: 在工具《$articleName$》中，留资预约了服务讲解
  description: 表示客户发生了“在工具中留资预约了服务讲解”行为。
  aliases:
  - 在工具中留资预约了服务讲解
  - 在工具中留资预约服务讲解
  - 在工具中留资预订了服务讲解
  - 有过在工具中留资预约服务讲解行为
  - 曾经在工具中留资预约服务讲解
  - 在工具中留资预约服务讲解记录
  positive_examples:
  - 找在工具中留资预约了服务讲解的客户
  - 查询在工具中留资预约服务讲解的人
  - 哪些客户在工具中留资预订了服务讲解
  - 筛选出有过在工具中留资预约服务讲解行为的客户
  negative_examples:
  - 找没有在工具中留资预约服务讲解的客户
  - 排除在工具中留资预约服务讲解的客户
  - 查询从未在工具中留资预约服务讲解的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_071
  activity: taxCalculator_use
  intent_category: 使用节税计算器并进行了测算
  activity_template: 使用节税计算器，并进行了测算
  description: 客户使用节税计算器并完成节税测算。
  aliases:
  - 使用节税计算器并进行了测算
  - 使用节税计算器并进行测算
  - 有过使用节税计算器并进行测算行为
  - 曾经使用节税计算器并进行测算
  - 使用节税计算器并进行测算记录
  positive_examples:
  - 找使用节税计算器做过测算的客户
  - 查询只完成节税测算的人
  - 哪些客户有过使用节税计算器并进行测算行为
  - 筛选出有过曾经使用节税计算器并进行测算行为的客户
  negative_examples:
  - 找节税测算后预约税优服务的客户
  - 查询只预约税优咨询但没有使用计算器的人
  - 查询从未使用节税计算器并进行测算的人
  confusing_intents:
  - taxCalculator_reserve
  is_supported: true
- candidate_id: behavior_candidate_072
  activity: taxSubject_order
  intent_category: 浏览内容并预约税优服务
  activity_template: 浏览《$articleName$》内容，并预约税优服务
  description: 客户先浏览某篇内容，再预约税优服务。
  aliases:
  - 浏览内容并预约税优服务
  - 查看内容并预约税优服务
  - 浏览内容并预订税优服务
  - 有过浏览内容并预约税优服务行为
  - 曾经浏览内容并预约税优服务
  - 浏览内容并预约税优服务记录
  positive_examples:
  - 找看完内容后预约税优服务的客户
  - 查询浏览文章并提交税优预约的人
  - 哪些客户浏览内容并预订税优服务
  - 筛选出有过浏览内容并预约税优服务行为的客户
  negative_examples:
  - 找只预约税优服务但没有浏览内容的客户
  - 查询使用节税计算器后预约税优服务的人
  - 查询从未浏览内容并预约税优服务的人
  confusing_intents:
  - SYZQ_ZEB_INFO_ORDER
  - taxCalculator_reserve
  - SYZQ_ZEB_PRODUCT_ORDER
  is_supported: true
- candidate_id: behavior_candidate_073
  activity: SYZQ_ZEB_INFO_READEND
  intent_category: 阅读了资讯时长秒
  activity_template: 阅读了资讯《$articleName$》，时长$time$秒
  description: 客户阅读单篇资讯，事件记录包含时长或停留时长信息。
  aliases:
  - 阅读了资讯时长秒
  - 阅读资讯时长秒
  - 读过资讯时长秒
  - 看过资讯时长秒
  - 有过阅读资讯时长秒行为
  - 曾经阅读资讯时长秒
  - 阅读资讯时长秒记录
  positive_examples:
  - 找在某篇资讯停留几分钟的客户
  - 查询仔细阅读过资讯的人
  - 哪些客户阅读资讯时长秒
  - 筛选出有过读过资讯时长秒行为的客户
  negative_examples:
  - 找只说看过资讯但没有时长线索的人
  - 查询资讯专题的查看时长
  - 找没有阅读资讯的客户
  - 查询从未阅读资讯的人
  confusing_intents:
  - ZEB_INFO_READEND
  is_supported: true
- candidate_id: behavior_candidate_074
  activity: SYZQ_ZEB_INFO_ORDER
  intent_category: 在口袋E资讯中预约了税优服务
  activity_template: 在口袋E资讯《$articleName$》中，预约了税优服务
  description: 客户通过口袋E资讯渠道预约税优服务。
  aliases:
  - 在口袋E资讯中预约了税优服务
  - 在口袋E资讯中预约税优服务
  - 预约了税优服务
  - 在口袋E资讯中预订了税优服务
  - 有过预约税优服务行为
  - 曾经预约税优服务
  - 预约税优服务记录
  positive_examples:
  - 找从口袋E资讯预约税优服务的客户
  - 查询通过口袋E文章发起税优预约的人
  - 哪些客户预约了税优服务
  - 筛选出有过在口袋E资讯中预订了税优服务行为的客户
  negative_examples:
  - 找使用节税计算器后预约税优服务的客户
  - 查询在金管家税务场景了解如何购买税优险的人
  - 查询从未预约税优服务的人
  confusing_intents:
  - taxSubject_order
  - JGJ_SY_SCENE_PRODUCT_RESERVE
  - taxCalculator_reserve
  - SYZQ_ZEB_PRODUCT_ORDER
  is_supported: true
- candidate_id: behavior_candidate_075
  activity: SYZQ_ZEB_INFO_PRODUCT
  intent_category: 在资讯中查看了产品
  activity_template: 在资讯《$articleName$》中，查看了产品“$productName$”
  description: 客户在资讯文章中进一步查看某个产品。
  aliases:
  - 从资讯中点开产品
  - 在资讯里查看产品方案
  - 在资讯中查看了产品
  - 在资讯中查看产品
  - 查看了产品
  - 在资讯中看过产品
  - 在资讯中浏览了产品
  - 有过在资讯中查看产品行为
  - 曾经在资讯中查看产品
  - 在资讯中查看产品记录
  positive_examples:
  - 找在资讯中查看了产品的客户
  - 查询在资讯中查看产品的人
  - 哪些客户查看了产品
  - 筛选出有过在资讯中看过产品行为的客户
  negative_examples:
  - 找在活动中查看臻享医方案的客户
  - 找没有在资讯中查看产品的客户
  - 排除在资讯中查看产品的客户
  - 查询从未在资讯中查看产品的人
  confusing_intents:
  - ZEB_INFO_PRODUCT
  is_supported: true
- candidate_id: behavior_candidate_076
  activity: onlineActivity_ZXJYKMH
  intent_category: 参与活动并查看臻享医开门红限时方案
  activity_template: 参与”$activityName$“活动，并查看臻享家医开门红限时方案
  description: 表示客户发生了“参与活动并查看臻享医开门红限时方案”行为。
  aliases:
  - 参与活动并查看臻享医开门红限时方案
  - 参与活动并浏览臻享医开门红限时方案
  - 参加活动并查看臻享医开门红限时方案
  - 有过参与活动并查看臻享医开门红限时方案行为
  - 曾经参与活动并查看臻享医开门红限时方案
  - 参与活动并查看臻享医开门红限时方案记录
  positive_examples:
  - 找参与活动并查看臻享医开门红限时方案的客户
  - 查询参与活动并浏览臻享医开门红限时方案的人
  - 哪些客户参加活动并查看臻享医开门红限时方案
  - 筛选出有过参与活动并查看臻享医开门红限时方案行为的客户
  negative_examples:
  - 找没有参与活动并查看臻享医开门红限时方案的客户
  - 排除参与活动并查看臻享医开门红限时方案的客户
  - 查询从未参与活动并查看臻享医开门红限时方案的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_077
  activity: contactInfo_click
  intent_category: 渠道金管家客户已绑定您并领取了留资福利
  activity_template: '"$leadChannel$"渠道金管家$customerType$客户已绑定您，并领取了留资福利'
  description: 表示客户发生了“渠道金管家客户已绑定您并领取了留资福利”行为。
  aliases:
  - 渠道金管家客户已绑定您并领取了留资福利
  - 渠道金管家客户已绑定您并领取留资福利
  - 渠道金管家客户已绑定您并领过留资福利
  - 渠道金管家客户已绑定您并领过了留资福利
  - 有过渠道金管家客户已绑定您并领取留资福利行为
  - 曾经渠道金管家客户已绑定您并领取留资福利
  - 渠道金管家客户已绑定您并领取留资福利记录
  positive_examples:
  - 找渠道金管家客户已绑定您并领取了留资福利的客户
  - 查询渠道金管家客户已绑定您并领取留资福利的人
  - 哪些客户渠道金管家客户已绑定您并领过留资福利
  - 筛选出有过渠道金管家客户已绑定您并领过了留资福利行为的客户
  negative_examples:
  - 找没有渠道金管家客户已绑定您并领取留资福利的客户
  - 排除渠道金管家客户已绑定您并领取留资福利的客户
  - 查询从未渠道金管家客户已绑定您并领取留资福利的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_078
  activity: jgj_eduClub_join
  intent_category: 已加入教育俱乐部会员对教育有较高兴趣
  activity_template: 已加入教育俱乐部会员，对教育有较高兴趣
  description: 表示客户发生了“已加入教育俱乐部会员对教育有较高兴趣”行为。
  aliases:
  - 已加入教育俱乐部会员对教育有较高兴趣
  - 已成为教育俱乐部会员对教育有较高兴趣
  - 有过已加入教育俱乐部会员对教育有较高兴趣行为
  - 曾经已加入教育俱乐部会员对教育有较高兴趣
  - 已加入教育俱乐部会员对教育有较高兴趣记录
  positive_examples:
  - 找已加入教育俱乐部会员对教育有较高兴趣的客户
  - 查询已成为教育俱乐部会员对教育有较高兴趣的人
  - 哪些客户有过已加入教育俱乐部会员对教育有较高兴趣行为
  - 筛选出有过曾经已加入教育俱乐部会员对教育有较高兴趣行为的客户
  negative_examples:
  - 找没有已加入教育俱乐部会员对教育有较高兴趣的客户
  - 排除已加入教育俱乐部会员对教育有较高兴趣的客户
  - 查询从未已加入教育俱乐部会员对教育有较高兴趣的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_079
  activity: BDGJ_WXMINIAPP_BDGJ_APPLY
  intent_category: 通过平安保单管家小程序开通保单管家服务
  activity_template: 通过平安保单管家小程序开通保单管家服务
  description: 客户通过“平安保单管家”专属小程序开通保单管家服务；需与金管家APP和金管家小程序渠道区分。
  aliases:
  - 通过平安保单管家小程序开通保单管家服务
  - 开通保单管家
  - 开启保单管家服务
  - 开通保单管家服务
  - 通过平安保单管家小程序开启保单管家服务
  - 有过开通保单管家服务行为
  - 曾经开通保单管家服务
  - 开通保单管家服务记录
  positive_examples:
  - 找通过平安保单管家小程序开通保单管家服务的客户
  - 查询在平安保单管家小程序完成开通的人
  - 哪些客户开启保单管家服务
  - 筛选出有过开通保单管家服务行为的客户
  negative_examples:
  - 找通过金管家APP开通保单管家的客户
  - 查询通过金管家小程序开通保单管家的人
  - 查询从未开通保单管家服务的人
  confusing_intents:
  - BDGJ_JGJAPP_APPLY
  - BDGJ_WXMINIAPP_JGJ_APPLY
  is_supported: true
- candidate_id: behavior_candidate_080
  activity: MIT_PROPOSAL_READEND
  intent_category: 在微信阅读了建议书时长秒
  activity_template: 在微信阅读了建议书“$productName$”，时长$time$秒
  description: 表示客户发生了“在微信阅读了建议书时长秒”行为。
  aliases:
  - 在微信阅读了建议书时长秒
  - 在微信阅读建议书时长秒
  - 阅读了建议书时长秒
  - 在微信读过建议书时长秒
  - 在微信看过建议书时长秒
  - 有过阅读建议书时长秒行为
  - 曾经阅读建议书时长秒
  positive_examples:
  - 找在微信阅读建议书超过一分钟的客户
  - 查询在微信阅读了建议书时长秒的人
  - 哪些客户在微信阅读建议书时长秒
  - 筛选出有过阅读了建议书时长秒行为的客户
  negative_examples:
  - 找没有阅读建议书的客户
  - 排除阅读建议书的客户
  - 查询从未阅读建议书的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_081
  activity: JGJ_ONLINE_SCENE_PRODUCT_RESERVE
  intent_category: 通过金管家APP预约了解
  activity_template: 通过金管家APP预约了解「“$productName$”」
  description: 客户通过金管家APP渠道预约了解或咨询某个产品。
  selection_notes: 必须有金管家APP渠道线索；明确APP时优先于产品名称对应的专属服务预约候选。
  aliases:
  - 通过金管家APP预约了解
  - 通过金管家APP预约咨询
  - 通过金管家APP想了解
  - 有过通过金管家APP预约了解行为
  - 曾经通过金管家APP预约了解
  - 通过金管家APP预约了解记录
  positive_examples:
  - 找通过金管家APP预约了解产品的客户
  - 查询在金管家APP发起产品咨询的人
  - 哪些客户通过金管家APP想了解
  - 筛选出有过通过金管家APP预约了解行为的客户
  negative_examples:
  - 找未说明金管家APP渠道、只预约家庭财富保障讲解服务的客户
  - 查询通过权益专区或口袋E预约服务的人
  - 查询从未通过金管家APP预约了解的人
  confusing_intents:
  - ZEB_INFO_ORDER
  - ZEB_PRODUCT_ORDER
  - JGJ_RIGHT_RESERVE
  - JGJ_MULTI_PRODUCT_RESERVE
  is_supported: true
- candidate_id: behavior_candidate_082
  activity: OLDCARE_TEST_USE
  intent_category: 完成了养老缺口测算
  activity_template: 完成了养老缺口测算
  description: 表示客户发生了“完成了养老缺口测算”行为。
  aliases:
  - 完成了养老缺口测算
  - 完成养老缺口测算
  - 做完了养老缺口测算
  - 有过完成养老缺口测算行为
  - 曾经完成养老缺口测算
  - 完成养老缺口测算记录
  positive_examples:
  - 找完成了养老缺口测算的客户
  - 查询完成养老缺口测算的人
  - 哪些客户做完了养老缺口测算
  - 筛选出有过完成养老缺口测算行为的客户
  negative_examples:
  - 找转发或分享养老金测算器但没有完成测算的客户
  - 查询只打开测算工具但未完成测算的人
  - 查询从未完成养老缺口测算的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_083
  activity: JGJ_CLUB_READ
  intent_category: 在金管家俱乐部中查看了
  activity_template: 在金管家$clubName$俱乐部中，查看了$itemName$
  description: 表示客户发生了“在金管家俱乐部中查看了”行为。
  aliases:
  - 在金管家俱乐部中查看了
  - 在金管家俱乐部中查看
  - 俱乐部中查看了
  - 在金管家俱乐部中看过
  - 在金管家俱乐部中浏览了
  - 有过俱乐部中查看行为
  - 曾经俱乐部中查看
  - 俱乐部中查看记录
  positive_examples:
  - 找在金管家俱乐部中查看了的客户
  - 查询在金管家俱乐部中查看的人
  - 哪些客户俱乐部中查看了
  - 筛选出有过在金管家俱乐部中看过行为的客户
  negative_examples:
  - 找没有俱乐部中查看的客户
  - 排除俱乐部中查看的客户
  - 查询从未俱乐部中查看的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_084
  activity: JGJ_FREEINSUR_JOIN_TEAM
  intent_category: 参与赠险组队活动并与用户完成组队领取
  activity_template: 参与赠险组队活动，并与用户$shareClientName$完成组队领取
  description: 表示客户发生了“参与赠险组队活动并与用户完成组队领取”行为。
  aliases:
  - 参与赠险组队活动并与用户完成组队领取
  - 参加赠险组队活动并与用户完成组队领取
  - 参与赠险组队活动并与用户做完组队领取
  - 参与赠险组队活动并与用户完成组队领过
  - 有过参与赠险组队活动并与用户完成组队领取行为
  - 曾经参与赠险组队活动并与用户完成组队领取
  - 参与赠险组队活动并与用户完成组队领取记录
  positive_examples:
  - 找参与赠险组队活动并与用户完成组队领取的客户
  - 查询参加赠险组队活动并与用户完成组队领取的人
  - 哪些客户参与赠险组队活动并与用户做完组队领取
  - 筛选出有过参与赠险组队活动并与用户完成组队领过行为的客户
  negative_examples:
  - 找没有参与赠险组队活动并与用户完成组队领取的客户
  - 排除参与赠险组队活动并与用户完成组队领取的客户
  - 查询从未参与赠险组队活动并与用户完成组队领取的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_085
  activity: JGJ_ACTIVITY_REAl_PRIZE
  intent_category: 在活动中领取了奖品该奖品需代理人上门递送
  activity_template: 在活动“$activityname$”中领取了奖品“$prizeName$”，该奖品需代理人上门递送。
  description: 客户在活动中领取奖品，并且该奖品明确需要代理人上门递送；“领取奖品”和“待上门配送”两个条件都应成立。
  aliases:
  - 在活动中领取了奖品该奖品需代理人上门递送
  - 在活动中领取奖品该奖品需代理人上门递送
  - 在活动中领过奖品该奖品需代理人上门递送
  - 在活动中领过了奖品该奖品需代理人上门递送
  - 有过在活动中领取奖品该奖品需代理人上门递送行为
  - 曾经在活动中领取奖品该奖品需代理人上门递送
  - 在活动中领取奖品该奖品需代理人上门递送记录
  positive_examples:
  - 找活动中奖品已领取但还需要上门配送的客户
  - 查询需要代理人递送活动奖品的人
  - 哪些客户在活动中领过奖品该奖品需代理人上门递送
  - 筛选出有过在活动中领过了奖品该奖品需代理人上门递送行为的客户
  negative_examples:
  - 找只获得活动奖品但没有配送要求的客户
  - 查询在俱乐部领取权益的人
  - 查询从未在活动中领取奖品该奖品需代理人上门递送的人
  confusing_intents:
  - JGJ_OPERATE_WON_PRIZE
  - JGJ_CLUB_RIGHT_GET
  is_supported: true
- candidate_id: behavior_candidate_086
  activity: JGJ_POLICY_CLAIM_ASSIST
  intent_category: 成为了你名下老客户的紧急联络人并领取了你赠送的权益他们之间的关系为
  activity_template: 成为了你名下老客户$inviterName$的紧急联络人，并领取了你赠送的权益$giftName$，他们之间的关系为$relationShip$
  description: 表示客户发生了“成为了你名下老客户的紧急联络人并领取了你赠送的权益他们之间的关系为”行为。
  aliases:
  - 成为了你名下老客户的紧急联络人并领取了你赠送的权益他们之间的关系为
  - 成为你名下老客户的紧急联络人并领取你赠送的权益他们之间的关系为
  - 成为了你名下老客户的紧急联络人并领过你赠送的权益他们之间的关系为
  - 成为了你名下老客户的紧急联络人并领过了你赠送的权益他们之间的关系为
  positive_examples:
  - 找成为了你名下老客户的紧急联络人并领取了你赠送的权益他们之间的关系为的客户
  - 查询成为你名下老客户的紧急联络人并领取你赠送的权益他们之间的关系为的人
  - 哪些客户成为了你名下老客户的紧急联络人并领过你赠送的权益他们之间的关系为
  - 筛选出有过成为了你名下老客户的紧急联络人并领过了你赠送的权益他们之间的关系为行为的客户
  negative_examples:
  - 找没有成为你名下老客户的紧急联络人并领取你赠送的权益他们之间的关系为的客户
  - 排除成为你名下老客户的紧急联络人并领取你赠送的权益他们之间的关系为的客户
  - 查询从未成为你名下老客户的紧急联络人并领取你赠送的权益他们之间的关系为的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_087
  activity: jgj_eduClub_test
  intent_category: 在金管家教育俱乐部中进行了测评并了解服务
  activity_template: 在金管家教育俱乐部中进行了测评，并了解“$services$”服务
  description: 表示客户发生了“在金管家教育俱乐部中进行了测评并了解服务”行为。
  aliases:
  - 在金管家教育俱乐部中进行了测评并了解服务
  - 在金管家教育俱乐部中进行测评并了解服务
  - 教育俱乐部中进行了测评并了解服务
  - 有过教育俱乐部中进行测评并了解服务行为
  - 曾经教育俱乐部中进行测评并了解服务
  - 教育俱乐部中进行测评并了解服务记录
  positive_examples:
  - 找在金管家教育俱乐部中进行了测评并了解服务的客户
  - 查询在金管家教育俱乐部中进行测评并了解服务的人
  - 哪些客户教育俱乐部中进行了测评并了解服务
  - 筛选出有过教育俱乐部中进行测评并了解服务行为的客户
  negative_examples:
  - 找没有教育俱乐部中进行测评并了解服务的客户
  - 排除教育俱乐部中进行测评并了解服务的客户
  - 查询从未教育俱乐部中进行测评并了解服务的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_088
  activity: JGJ_JYNJ25_PRODUCT_RESERVE
  intent_category: 在金管家预定利率场景预约了解2.5%预定利率产品快去联系喔
  activity_template: 在金管家预定利率场景预约了解「2.5%预定利率」产品，快去联系喔！
  description: 表示客户发生了“在金管家预定利率场景预约了解2.5%预定利率产品快去联系喔”行为。
  aliases:
  - 在金管家预定利率场景预约了解2.5%预定利率产品
  - 在金管家预定利率场景预约了解2.5%预定利率产品快去联系喔
  - 预定利率场景预约了解2.5%预定利率产品快去联系喔
  - 在金管家预定利率场景预约咨询2.5%预定利率产品快去联系喔
  - 在金管家预定利率场景想了解2.5%预定利率产品快去联系喔
  positive_examples:
  - 找在金管家预定利率场景预约了解2.5%预定利率产品的客户
  - 查询在金管家预定利率场景预约了解2.5%预定利率产品快去联系喔的人
  - 哪些客户预定利率场景预约了解2.5%预定利率产品快去联系喔
  - 筛选出有过在金管家预定利率场景预约咨询2.5%预定利率产品快去联系喔行为的客户
  negative_examples:
  - 找没有预定利率场景预约了解2.5%预定利率产品的客户
  - 排除预定利率场景预约了解2.5%预定利率产品的客户
  - 查询从未预定利率场景预约了解2.5%预定利率产品的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_089
  activity: JGJ_SY_SCENE_PRODUCT_RESERVE
  intent_category: 在金管家税务场景预约了解如何购买税优险
  activity_template: 在金管家税优场景预约了解「如何购买税优险」
  description: 客户在金管家税务场景预约了解如何购买税优险；必须包含税务场景或购买税优险的明确线索。
  aliases:
  - 在金管家税务场景预约了解如何购买税优险
  - 税务场景预约了解如何购买税优险
  - 在金管家税务场景预约咨询如何购买税优险
  - 在金管家税务场景想了解如何购买税优险
  - 有过税务场景预约了解如何购买税优险行为
  - 曾经税务场景预约了解如何购买税优险
  - 税务场景预约了解如何购买税优险记录
  positive_examples:
  - 找在金管家税务专区咨询如何购买税优险的客户
  - 查询预约了解税优险购买方式的人
  - 哪些客户在金管家税务场景预约咨询如何购买税优险
  - 筛选出有过在金管家税务场景想了解如何购买税优险行为的客户
  negative_examples:
  - 找从口袋E资讯预约税优服务的客户
  - 查询预约税优政策和保险产品咨询的人
  - 查询从未税务场景预约了解如何购买税优险的人
  confusing_intents:
  - SYZQ_ZEB_INFO_ORDER
  - taxCalculator_reserve
  - SYZQ_ZEB_PRODUCT_ORDER
  is_supported: true
- candidate_id: behavior_candidate_090
  activity: PINGAN_WEB_RESERVE_2
  intent_category: 在平安人寿官网向您发起了预约申请
  activity_template: 在平安人寿官网向您发起了预约申请
  description: 表示客户发生了“在平安人寿官网向您发起了预约申请”行为。
  aliases:
  - 在平安人寿官网向您发起了预约申请
  - 在平安人寿官网向您发起预约申请
  - 向您发起了预约申请
  - 在平安人寿官网向您发起了预订申请
  - 有过向您发起预约申请行为
  - 曾经向您发起预约申请
  - 向您发起预约申请记录
  positive_examples:
  - 找在平安人寿官网向您发起了预约申请的客户
  - 查询在平安人寿官网向您发起预约申请的人
  - 哪些客户向您发起了预约申请
  - 筛选出有过在平安人寿官网向您发起了预订申请行为的客户
  negative_examples:
  - 找没有向您发起预约申请的客户
  - 排除向您发起预约申请的客户
  - 查询从未向您发起预约申请的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_091
  activity: JGJ_RIGHT_RESERVE
  intent_category: 在金管家中预约了解
  activity_template: 在金管家$equityZoneName$中预约了解「“$reserveItemName$”」
  description: 客户在金管家的权益专区或权益场景中预约了解具体服务项目。
  aliases:
  - 在金管家中预约了解
  - 在金管家中预约咨询
  - 在金管家权益专区预约了解
  - 在金管家权益场景预约服务
  - 在金管家中想了解
  - 有过在金管家中预约了解行为
  - 曾经在金管家中预约了解
  - 在金管家中预约了解记录
  positive_examples:
  - 找在金管家权益专区预约了解服务的客户
  - 查询从金管家权益场景发起预约的人
  - 哪些客户在金管家中想了解
  - 筛选出有过在金管家中预约了解行为的客户
  negative_examples:
  - 找在金管家APP预约了解产品的客户
  - 查询在保险小店预约服务的人
  - 查询从未在金管家中预约了解的人
  confusing_intents:
  - ZEB_AGENTSTORE_SERVICE
  - JGJ_ONLINE_SCENE_PRODUCT_RESERVE
  - JGJ_VIPRIGHT_UPGRADE
  - JGJ_MULTI_PRODUCT_RESERVE
  is_supported: true
- candidate_id: behavior_candidate_092
  activity: JGJ_VISIT_RESERVE
  intent_category: 在面访服务预约函中提交了预约
  activity_template: 在“面访服务预约函”中提交了预约 "$serviceLetterTitle$"
  description: 表示客户发生了“在面访服务预约函中提交了预约”行为。
  aliases:
  - 在面访服务预约函中提交了预约
  - 在面访服务预约函中提交预约
  - 在面访服务预订函中提交了预约
  - 在面访服务预约函中递交了预约
  - 有过在面访服务预约函中提交预约行为
  - 曾经在面访服务预约函中提交预约
  - 在面访服务预约函中提交预约记录
  positive_examples:
  - 找在面访服务预约函中提交了预约的客户
  - 查询在面访服务预约函中提交预约的人
  - 哪些客户在面访服务预订函中提交了预约
  - 筛选出有过在面访服务预约函中递交了预约行为的客户
  negative_examples:
  - 找没有在面访服务预约函中提交预约的客户
  - 排除在面访服务预约函中提交预约的客户
  - 查询从未在面访服务预约函中提交预约的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_093
  activity: JGJ_VIPRIGHT_UPGRADE
  intent_category: 在金管家预约了解会员升级
  activity_template: 在金管家预约了解会员升级「$upgradeDetail$」
  description: 表示客户发生了“在金管家预约了解会员升级”行为。
  aliases:
  - 在金管家预约了解会员升级
  - 预约了解会员升级
  - 在金管家预约咨询会员升级
  - 在金管家想了解会员升级
  - 有过预约了解会员升级行为
  - 曾经预约了解会员升级
  - 预约了解会员升级记录
  positive_examples:
  - 找在金管家预约了解会员升级的客户
  - 查询预约了解会员升级的人
  - 哪些客户在金管家预约咨询会员升级
  - 筛选出有过在金管家想了解会员升级行为的客户
  negative_examples:
  - 找没有预约了解会员升级的客户
  - 排除预约了解会员升级的客户
  - 查询从未预约了解会员升级的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_094
  activity: JGJ_ACTIVITY_APPLY_CHECK
  intent_category: 在金管家报名了部课活动请尽快审核客户是否通过
  activity_template: 在金管家报名了部课活动“$activityName$”，请尽快审核客户是否通过
  description: 表示客户发生了“在金管家报名了部课活动请尽快审核客户是否通过”行为。
  aliases:
  - 在金管家报名了部课活动请尽快审核客户是否通过
  - 在金管家报名部课活动请尽快审核客户是否通过
  - 报名了部课活动请尽快审核客户是否通过
  - 在金管家报了名部课活动请尽快审核客户是否通过
  - 有过报名部课活动请尽快审核客户是否通过行为
  - 曾经报名部课活动请尽快审核客户是否通过
  - 报名部课活动请尽快审核客户是否通过记录
  positive_examples:
  - 找在金管家报名了部课活动请尽快审核客户是否通过的客户
  - 查询在金管家报名部课活动请尽快审核客户是否通过的人
  - 哪些客户报名了部课活动请尽快审核客户是否通过
  - 筛选出有过在金管家报了名部课活动请尽快审核客户是否通过行为的客户
  negative_examples:
  - 找没有报名部课活动请尽快审核客户是否通过的客户
  - 排除报名部课活动请尽快审核客户是否通过的客户
  - 查询从未报名部课活动请尽快审核客户是否通过的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_095
  activity: JGJ_TECH_CLUB_TEST
  intent_category: 在金管家教育俱乐部使用了留学计算器进行费用测算选择了意向国家意向阶段留学费用
  activity_template: 在金管家教育俱乐部，使用了留学计算器进行费用测算（选择了意向国家$IntendedCountries$，意向阶段$IntentionStage$，留学费用$cost$）
  description: 表示客户发生了“在金管家教育俱乐部使用了留学计算器进行费用测算选择了意向国家意向阶段留学费用”行为。
  aliases:
  - 在金管家教育俱乐部使用了留学计算器进行费用测算选择了意向国家意向阶段留学费用
  - 在金管家教育俱乐部使用留学计算器进行费用测算选择意向国家意向阶段留学费用
  - 教育俱乐部使用了留学计算器进行费用测算选择了意向国家意向阶段留学费用
  - 在金管家教育俱乐部用过留学计算器进行费用测算选择了意向国家意向阶段留学费用
  positive_examples:
  - 找在金管家教育俱乐部使用了留学计算器进行费用测算选择了意向国家意向阶段留学费用的客户
  - 查询在金管家教育俱乐部使用留学计算器进行费用测算选择意向国家意向阶段留学费用的人
  - 哪些客户教育俱乐部使用了留学计算器进行费用测算选择了意向国家意向阶段留学费用
  - 筛选出有过在金管家教育俱乐部用过留学计算器进行费用测算选择了意向国家意向阶段留学费用行为的客户
  negative_examples:
  - 找没有教育俱乐部使用留学计算器进行费用测算选择意向国家意向阶段留学费用的客户
  - 排除教育俱乐部使用留学计算器进行费用测算选择意向国家意向阶段留学费用的客户
  - 查询从未教育俱乐部使用留学计算器进行费用测算选择意向国家意向阶段留学费用的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_096
  activity: jgj_beiqingTest
  intent_category: 在金管家完成了北清教育测评
  activity_template: 在金管家完成了北清教育测评
  description: 表示客户发生了“在金管家完成了北清教育测评”行为。
  aliases:
  - 在金管家完成了北清教育测评
  - 在金管家完成北清教育测评
  - 完成了北清教育测评
  - 在金管家做完了北清教育测评
  - 有过完成北清教育测评行为
  - 曾经完成北清教育测评
  - 完成北清教育测评记录
  positive_examples:
  - 找在金管家完成了北清教育测评的客户
  - 查询在金管家完成北清教育测评的人
  - 哪些客户完成了北清教育测评
  - 筛选出有过在金管家做完了北清教育测评行为的客户
  negative_examples:
  - 找没有完成北清教育测评的客户
  - 排除完成北清教育测评的客户
  - 查询从未完成北清教育测评的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_097
  activity: BDGJ_JGJAPP_APPLY
  intent_category: 通过金管家app开通保单管家服务
  activity_template: 通过金管家app开通保单管家服务
  description: 客户通过金管家APP开通保单管家服务。
  aliases:
  - 通过金管家app开通保单管家服务
  - 在金管家APP开通保单管家
  - APP开通保单管家服务
  - 开通保单管家服务
  - 通过金管家app开启保单管家服务
  - 有过开通保单管家服务行为
  - 曾经开通保单管家服务
  - 开通保单管家服务记录
  positive_examples:
  - 找通过金管家app开通保单管家服务的客户
  - 查询在金管家APP开通保单管家的人
  - 哪些客户APP开通保单管家服务
  - 筛选出有过开通保单管家服务行为的客户
  negative_examples:
  - 找通过平安保单管家小程序开通服务的客户
  - 查询通过金管家小程序开通保单管家的人
  - 查询从未开通保单管家服务的人
  confusing_intents:
  - BDGJ_WXMINIAPP_BDGJ_APPLY
  - BDGJ_WXMINIAPP_JGJ_APPLY
  is_supported: true
- candidate_id: behavior_candidate_098
  activity: JGJ_MULTI_PRODUCT_RESERVE
  intent_category: 在金管家预约了解产品
  activity_template: 在金管家预约了解产品“$productName$”
  description: 客户在金管家预约了解具体保险产品。
  aliases:
  - 在金管家预约了解产品
  - 在金管家预约咨询产品
  - 在金管家想了解产品
  - 有过在金管家预约了解产品行为
  - 曾经在金管家预约了解产品
  - 在金管家预约了解产品记录
  positive_examples:
  - 找在金管家预约了解保险产品的客户
  - 查询在金管家提交产品咨询的人
  - 哪些客户在金管家想了解产品
  - 筛选出有过在金管家预约了解产品行为的客户
  negative_examples:
  - 找在金管家权益专区预约服务的客户
  - 查询预约家庭财富保障方案讲解的人
  - 查询从未在金管家预约了解产品的人
  confusing_intents:
  - JGJ_ONLINE_SCENE_PRODUCT_RESERVE
  - JGJ_RIGHT_RESERVE
  - JGJ_FORTUNE_SERVICE_RESERVE
  - SYZQ_ZEB_PRODUCT_ORDER
  is_supported: true
- candidate_id: behavior_candidate_099
  activity: JGJ_FORTUNE_SERVICE_RESERVE
  intent_category: 在金管家预约了家庭财富保障方案讲解服务
  activity_template: 在金管家预约了「家庭财富保障方案讲解」服务
  description: 客户预约家庭财富保障方案讲解服务。
  selection_notes: 必须明确家庭财富保障方案讲解；泛化服务预约或明确通过金管家APP预约产品时不选本候选。
  aliases:
  - 在金管家预约了家庭财富保障方案讲解服务
  - 在金管家预约家庭财富保障方案讲解服务
  - 预约了家庭财富保障方案讲解服务
  - 在金管家预订了家庭财富保障方案讲解服务
  - 有过预约家庭财富保障方案讲解服务行为
  - 曾经预约家庭财富保障方案讲解服务
  - 预约家庭财富保障方案讲解服务记录
  positive_examples:
  - 找在金管家预约了家庭财富保障方案讲解服务的客户
  - 查询在金管家预约家庭财富保障方案讲解服务的人
  - 哪些客户预约了家庭财富保障方案讲解服务
  - 筛选出有过在金管家预订了家庭财富保障方案讲解服务行为的客户
  negative_examples:
  - 找只说预约某项服务但没有家庭财富保障方案线索的客户
  - 查询明确通过金管家APP预约了解产品的人
  - 查询从未预约家庭财富保障方案讲解服务的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_100
  activity: JGJ_ZJZA_RIGHT_STARTUP
  intent_category: 开启了重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预约避免浪费
  activity_template: 开启了重疾专案管理，Ta还有1项探视关怀服务待开启，及时联系TA并帮忙预约，避免浪费
  description: 表示客户发生了“开启了重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预约避免浪费”行为。
  aliases:
  - 开启了重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预约避免浪费
  - 开启重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预约避免浪费
  - 开启了重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预订避免浪费
  positive_examples:
  - 找开启了重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预约避免浪费的客户
  - 查询开启重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预约避免浪费的人
  - 哪些客户开启了重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预订避免浪费
  negative_examples:
  - 找没有开启重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预约避免浪费的客户
  - 排除开启重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预约避免浪费的客户
  - 查询从未开启重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预约避免浪费的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_101
  activity: taxCalculator_reserve
  intent_category: 使用节税计算器并预约税优服务
  activity_template: 使用节税计算器，并预约税优服务
  description: 客户先使用节税计算器完成测算，再预约税优服务。
  aliases:
  - 使用节税计算器并预约税优服务
  - 使用节税计算器并预订税优服务
  - 有过使用节税计算器并预约税优服务行为
  - 曾经使用节税计算器并预约税优服务
  - 使用节税计算器并预约税优服务记录
  positive_examples:
  - 找节税测算后继续预约税优服务的客户
  - 查询使用节税计算器并提交税优预约的人
  - 哪些客户有过使用节税计算器并预约税优服务行为
  - 筛选出有过曾经使用节税计算器并预约税优服务行为的客户
  negative_examples:
  - 找只使用节税计算器完成测算的客户
  - 查询只预约税优咨询但没有使用计算器的人
  - 查询从未使用节税计算器并预约税优服务的人
  confusing_intents:
  - taxCalculator_use
  - taxSubject_order
  - SYZQ_ZEB_INFO_ORDER
  - SYZQ_ZEB_PRODUCT_ORDER
  is_supported: true
- candidate_id: behavior_candidate_102
  activity: JGJ_CLUB_JOIN
  intent_category: 已加入金管家俱乐部会员对有较高兴趣
  activity_template: 已加入金管家$clubName$俱乐部会员，对$scene$有较高兴趣
  description: 客户已经加入金管家某俱乐部，并对指定场景表现出较高兴趣。
  aliases:
  - 已加入金管家俱乐部会员对有较高兴趣
  - 已成为金管家俱乐部会员对有较高兴趣
  - 有过已加入金管家俱乐部会员对有较高兴趣行为
  - 曾经已加入金管家俱乐部会员对有较高兴趣
  - 已加入金管家俱乐部会员对有较高兴趣记录
  positive_examples:
  - 找已入会并对某类服务有兴趣的俱乐部会员
  - 查询加入金管家俱乐部后的场景意向客户
  - 哪些客户有过已加入金管家俱乐部会员对有较高兴趣行为
  - 筛选出有过曾经已加入金管家俱乐部会员对有较高兴趣行为的客户
  negative_examples:
  - 找入会后选择您作为保险规划师的客户
  - 查询只加入俱乐部但没有表达场景兴趣的人
  - 查询从未已加入金管家俱乐部会员对有较高兴趣的人
  confusing_intents:
  - jgj_eduClub_join
  - JGJ_CLUB_JOIN_BIND
  - JGJ_SNOWCLUB_JOIN
  is_supported: true
- candidate_id: behavior_candidate_103
  activity: JGJ_CLUB_JOIN_BIND
  intent_category: 已加入金管家俱乐部会员并选择您作为保险规划师对有较高兴趣
  activity_template: 已加入金管家$clubName$俱乐部会员并选择您作为保险规划师，对$scene$有较高兴趣
  description: 客户已加入金管家俱乐部、选择“您”作为保险规划师，并对指定场景有较高兴趣；三个条件共同构成该意图。
  aliases:
  - 已加入金管家俱乐部会员并选择您作为保险规划师对有较高兴趣
  - 加入俱乐部并选择保险规划师
  - 成为俱乐部会员并选您为规划师
  - 俱乐部会员选择了保险规划师
  - 已成为金管家俱乐部会员并选择您作为保险规划师对有较高兴趣
  positive_examples:
  - 找入会后选您为保险规划师并表达场景兴趣的客户
  - 查询选择我作为规划师的金管家俱乐部意向会员
  - 哪些客户成为俱乐部会员并选您为规划师
  - 筛选出有过俱乐部会员选择了保险规划师行为的客户
  negative_examples:
  - 找已入会并有兴趣但没有选择保险规划师的客户
  - 查询只选择保险规划师但没有场景兴趣的人
  - 查询从未已加入金管家俱乐部会员并选择您作为保险规划师对有较高兴趣的人
  confusing_intents:
  - JGJ_CLUB_JOIN
  - JGJ_SNOWCLUB_JOIN
  is_supported: true
- candidate_id: behavior_candidate_104
  activity: JGJ_CLUB_ACTIVITY_JOIN
  intent_category: 在金管家俱乐部中报名了活动
  activity_template: 在金管家$clubName$俱乐部中，报名了活动$itemName$
  description: 客户在金管家的具体俱乐部内报名活动。
  aliases:
  - 在金管家俱乐部中报名了活动
  - 在金管家俱乐部中报名活动
  - 俱乐部中报名了活动
  - 在金管家俱乐部中报了名活动
  - 有过俱乐部中报名活动行为
  - 曾经俱乐部中报名活动
  - 俱乐部中报名活动记录
  positive_examples:
  - 找在金管家俱乐部里报名活动的客户
  - 查询俱乐部活动报名名单
  - 哪些客户俱乐部中报名了活动
  - 筛选出有过在金管家俱乐部中报了名活动行为的客户
  negative_examples:
  - 找报名普通金管家活动的客户
  - 查询在俱乐部领取权益的人
  - 查询从未俱乐部中报名活动的人
  confusing_intents:
  - JGJ_OPERATE_SIGN_UP
  - JGJ_CLUB_READ
  - JGJ_CLUB_RIGHT_GET
  is_supported: true
- candidate_id: behavior_candidate_105
  activity: KDE_DS_COVERAGE_READ
  intent_category: 在微信中浏览了保障检视报告浏览时长秒
  activity_template: 在微信中浏览了"$clientName$$clientTitle$"保障检视报告，浏览时长$time$秒
  description: 表示客户发生了“在微信中浏览了保障检视报告浏览时长秒”行为。
  aliases:
  - 在微信中浏览了保障检视报告浏览时长秒
  - 在微信中浏览保障检视报告浏览时长秒
  - 浏览了保障检视报告浏览时长秒
  - 在微信中看过保障检视报告浏览时长秒
  - 在微信中查看了保障检视报告浏览时长秒
  - 有过浏览保障检视报告浏览时长秒行为
  - 曾经浏览保障检视报告浏览时长秒
  positive_examples:
  - 找在微信浏览保障检视报告超过一分钟的客户
  - 查询在微信中浏览了保障检视报告浏览时长秒的人
  - 哪些客户在微信中浏览保障检视报告浏览时长秒
  - 筛选出有过浏览了保障检视报告浏览时长秒行为的客户
  negative_examples:
  - 找没有浏览保障检视报告的客户
  - 排除浏览保障检视报告的客户
  - 查询从未浏览保障检视报告的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_106
  activity: BDGJ_WXMINIAPP_JGJ_APPLY
  intent_category: 通过金管家小程序开通保单管家服务
  activity_template: 通过金管家小程序开通保单管家服务
  description: 客户通过金管家小程序开通保单管家服务。
  aliases:
  - 通过金管家小程序开通保单管家服务
  - 在金管家小程序开通保单管家
  - 小程序开通保单管家服务
  - 开通保单管家服务
  - 通过金管家小程序开启保单管家服务
  - 有过开通保单管家服务行为
  - 曾经开通保单管家服务
  - 开通保单管家服务记录
  positive_examples:
  - 找通过金管家小程序开通保单管家服务的客户
  - 查询在金管家小程序开通保单管家的人
  - 哪些客户小程序开通保单管家服务
  - 筛选出有过开通保单管家服务行为的客户
  negative_examples:
  - 找通过金管家APP开通保单管家的客户
  - 查询通过平安保单管家小程序开通服务的人
  - 查询从未开通保单管家服务的人
  confusing_intents:
  - BDGJ_WXMINIAPP_BDGJ_APPLY
  - BDGJ_JGJAPP_APPLY
  is_supported: true
- candidate_id: behavior_candidate_107
  activity: JGJ_PROPOSAL_SERVICE_RESERVE
  intent_category: 在金管家预约了定制投保建议书服务
  activity_template: 在金管家预约了定制投保建议书服务
  description: 表示客户发生了“在金管家预约了定制投保建议书服务”行为。
  aliases:
  - 在金管家预约了定制投保建议书服务
  - 在金管家预约定制投保建议书服务
  - 预约了定制投保建议书服务
  - 在金管家预订了定制投保建议书服务
  - 有过预约定制投保建议书服务行为
  - 曾经预约定制投保建议书服务
  - 预约定制投保建议书服务记录
  positive_examples:
  - 找在金管家预约了定制投保建议书服务的客户
  - 查询在金管家预约定制投保建议书服务的人
  - 哪些客户预约了定制投保建议书服务
  - 筛选出有过在金管家预订了定制投保建议书服务行为的客户
  negative_examples:
  - 找没有预约定制投保建议书服务的客户
  - 排除预约定制投保建议书服务的客户
  - 查询从未预约定制投保建议书服务的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_108
  activity: JGJ_SNOWCLUB_JOIN
  intent_category: 加入了雪友俱乐部会员选择您作为保险规划师
  activity_template: 加入了雪友俱乐部会员，选择您作为保险规划师
  description: 表示客户发生了“加入了雪友俱乐部会员选择您作为保险规划师”行为。
  aliases:
  - 加入了雪友俱乐部会员选择您作为保险规划师
  - 加入雪友俱乐部会员选择您作为保险规划师
  - 成为了雪友俱乐部会员选择您作为保险规划师
  - 有过加入雪友俱乐部会员选择您作为保险规划师行为
  - 曾经加入雪友俱乐部会员选择您作为保险规划师
  - 加入雪友俱乐部会员选择您作为保险规划师记录
  positive_examples:
  - 找加入了雪友俱乐部会员选择您作为保险规划师的客户
  - 查询加入雪友俱乐部会员选择您作为保险规划师的人
  - 哪些客户成为了雪友俱乐部会员选择您作为保险规划师
  - 筛选出有过加入雪友俱乐部会员选择您作为保险规划师行为的客户
  negative_examples:
  - 找没有加入雪友俱乐部会员选择您作为保险规划师的客户
  - 排除加入雪友俱乐部会员选择您作为保险规划师的客户
  - 查询从未加入雪友俱乐部会员选择您作为保险规划师的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_109
  activity: JGJ_RIGHT_ACTIVATE
  intent_category: 在金管家中激活了权益
  activity_template: 在金管家中激活了权益“$equityName$”
  description: 客户在金管家激活、启用某项权益，或权益状态明确为已激活；激活后尚未使用仍属于权益激活行为。
  selection_notes: 原文明确“激活、启用、已激活”时直接选择本候选；不要因为同时出现“未使用”而删除激活行为。领取、预约、使用、兑换权益分别属于其他阶段。
  aliases:
  - 在金管家中激活了权益
  - 在金管家中激活权益
  - 激活了权益
  - 有过在金管家中激活权益行为
  - 曾经在金管家中激活权益
  - 在金管家中激活权益记录
  positive_examples:
  - 找在金管家中激活了权益的客户
  - 查询在金管家中激活权益的人
  - 哪些客户激活了权益
  - 筛选出有过在金管家中激活权益行为的客户
  negative_examples:
  - 找领取了权益的客户
  - 查询预约或使用权益的人
  - 找没有在金管家中激活权益的客户
  - 排除在金管家中激活权益的客户
  - 查询从未在金管家中激活权益的人
  confusing_intents:
  - JGJ_RIGHT_USE
  - JGJ_CLUB_RIGHT_GET
  - JGJ_RIGHT_GET2
  is_supported: true
- candidate_id: behavior_candidate_110
  activity: JGJ_RIGHT_USE
  intent_category: 在金管家中使用了权益
  activity_template: 在金管家中使用了权益“$equityName$”
  description: 客户在金管家实际使用、用过或消费某项权益，核心阶段是权益已经被使用。
  selection_notes: 原文明确“使用权益、用过权益、权益已使用”时直接选择本候选；激活、领取、预约或兑换不等于使用。
  aliases:
  - 在金管家中使用了权益
  - 在金管家中使用权益
  - 使用了权益
  - 在金管家中用过权益
  - 有过在金管家中使用权益行为
  - 曾经在金管家中使用权益
  - 在金管家中使用权益记录
  positive_examples:
  - 找在金管家中使用了权益的客户
  - 查询在金管家中使用权益的人
  - 哪些客户使用了权益
  - 筛选出有过在金管家中用过权益行为的客户
  negative_examples:
  - 找只激活但尚未使用权益的客户
  - 查询领取或预约权益的人
  - 找没有在金管家中使用权益的客户
  - 排除在金管家中使用权益的客户
  - 查询从未在金管家中使用权益的人
  confusing_intents:
  - JGJ_RIGHT_ACTIVATE
  - JGJ_CLUB_RIGHT_GET
  - JGJ_RIGHT_GET2
  is_supported: true
- candidate_id: behavior_candidate_111
  activity: PINGAN_WEB_RESERVE
  intent_category: 在平安人寿官网预约了解产品
  activity_template: 在平安人寿官网预约了解产品“$productName$”
  description: 表示客户发生了“在平安人寿官网预约了解产品”行为。
  aliases:
  - 在平安人寿官网预约了解产品
  - 在平安人寿官网预约咨询产品
  - 在平安人寿官网想了解产品
  - 有过在平安人寿官网预约了解产品行为
  - 曾经在平安人寿官网预约了解产品
  - 在平安人寿官网预约了解产品记录
  positive_examples:
  - 找在平安人寿官网预约了解产品的客户
  - 查询在平安人寿官网预约咨询产品的人
  - 哪些客户在平安人寿官网想了解产品
  - 筛选出有过在平安人寿官网预约了解产品行为的客户
  negative_examples:
  - 找没有在平安人寿官网预约了解产品的客户
  - 排除在平安人寿官网预约了解产品的客户
  - 查询从未在平安人寿官网预约了解产品的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_112
  activity: JGJ_JJYL_SERVICE_RESERVE
  intent_category: 浏览了对居家养老的服务感兴趣
  activity_template: 浏览了“$activityItems$”，对居家养老的“$serviceItems$”服务感兴趣
  description: 客户浏览养老、税优或相关活动内容后，对居家养老健康管理、家庭陪护等具体居家养老服务表达关注或兴趣；这是“内容浏览后形成服务兴趣”的复合事件。
  selection_notes: 需要同时识别内容浏览和对具体居家养老服务的兴趣、关注或意向。仅浏览居家养老专区内容选专区浏览；仅预约养老规划选养老服务预约；仅泛化地说对养老专题感兴趣不足以确定本候选。
  aliases:
  - 浏览了对居家养老的服务感兴趣
  - 浏览对居家养老的服务感兴趣
  - 看过对居家养老的服务感兴趣
  - 查看了对居家养老的服务感兴趣
  - 有过浏览对居家养老的服务感兴趣行为
  - 曾经浏览对居家养老的服务感兴趣
  - 浏览对居家养老的服务感兴趣记录
  positive_examples:
  - 找看过养老内容后关注家庭陪护服务的客户
  - 查询浏览相关内容并对居家养老健康管理感兴趣的人
  - 哪些客户看过活动内容后形成养老服务意向
  - 筛选浏览内容后关注具体居家养老服务的客户
  negative_examples:
  - 找只浏览过居家养老专区内容的客户
  - 查询直接预约养老规划服务的人
  - 找只说对养老专题感兴趣的人
  - 找没有浏览对居家养老的服务感兴趣的客户
  confusing_intents:
  - homeBasedCare_read
  - JGJ_OLDCARE_SERVICE_RESERVE
  - ZEB_TOPIC_READEND
  is_supported: true
- candidate_id: behavior_candidate_113
  activity: SYZQ_ZEB_PRODUCT_ORDER
  intent_category: 预约提供的税优政策和保险产品咨询服务
  activity_template: 预约您提供“$productName$”的税优政策和保险产品咨询服务
  description: 客户预约税优政策与保险产品的综合咨询服务。
  aliases:
  - 预约提供的税优政策和保险产品咨询服务
  - 预订提供的税优政策和保险产品咨询服务
  - 有过预约提供的税优政策和保险产品咨询服务行为
  - 曾经预约提供的税优政策和保险产品咨询服务
  - 预约提供的税优政策和保险产品咨询服务记录
  positive_examples:
  - 找预约税优政策和保险产品综合咨询的客户
  - 查询提交过税优保险咨询预约的人
  - 哪些客户有过预约提供的税优政策和保险产品咨询服务行为
  - 筛选出有过曾经预约提供的税优政策和保险产品咨询服务行为的客户
  negative_examples:
  - 找从口袋E资讯预约税优服务的客户
  - 查询使用节税计算器后预约税优服务的人
  - 查询从未预约提供的税优政策和保险产品咨询服务的人
  confusing_intents:
  - SYZQ_ZEB_INFO_ORDER
  - JGJ_SY_SCENE_PRODUCT_RESERVE
  - taxCalculator_reserve
  is_supported: true
- candidate_id: behavior_candidate_114
  activity: SYZQ_ZEB_INFO_SHARE
  intent_category: 转发分享了资讯
  activity_template: 转发分享了资讯《$articleName$》
  description: 客户转发或分享单篇资讯文章，原始槽位名为 articleName；明确出现专题时不应选择该意图。
  aliases:
  - 转发分享了资讯
  - 转发分享资讯
  - 转发了资讯
  - 分享了资讯
  - 有过转发分享资讯行为
  - 曾经转发分享资讯
  - 转发分享资讯记录
  positive_examples:
  - 找转发过资讯文章的客户
  - 查询分享过某篇文章的人
  - 哪些客户转发了资讯
  - 筛选出有过分享了资讯行为的客户
  negative_examples:
  - 找转发资讯专题的客户
  - 查询分享展业工具或产品的人
  - 查询从未转发分享资讯的人
  confusing_intents:
  - ZEB_TOPIC_SHARE
  - ZEB_INFO_SHARE
  is_supported: true
- candidate_id: behavior_candidate_115
  activity: JGJ_CLUB_RIGHT_GET
  intent_category: 在金管家俱乐部中领取了权益
  activity_template: 在金管家$clubName$俱乐部中，领取了权益$itemName$
  description: 表示客户发生了“在金管家俱乐部中领取了权益”行为。
  aliases:
  - 在金管家俱乐部中领取了权益
  - 在金管家俱乐部中领取权益
  - 俱乐部中领取了权益
  - 在金管家俱乐部中领过权益
  - 在金管家俱乐部中领过了权益
  - 有过俱乐部中领取权益行为
  - 曾经俱乐部中领取权益
  - 俱乐部中领取权益记录
  positive_examples:
  - 找在金管家俱乐部中领取了权益的客户
  - 查询在金管家俱乐部中领取权益的人
  - 哪些客户俱乐部中领取了权益
  - 筛选出有过在金管家俱乐部中领过权益行为的客户
  negative_examples:
  - 找没有俱乐部中领取权益的客户
  - 排除俱乐部中领取权益的客户
  - 查询从未俱乐部中领取权益的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_116
  activity: CHENGXING_LIVE_RESERVE
  intent_category: 在视频号直播间购买了咨询链接
  activity_template: 在视频号直播间购买了咨询链接“$serviceName$"
  description: 表示客户发生了“在视频号直播间购买了咨询链接”行为。
  aliases:
  - 在视频号直播间购买了咨询链接
  - 在视频号直播间购买咨询链接
  - 购买了咨询链接
  - 在视频号直播间买了咨询链接
  - 有过购买咨询链接行为
  - 曾经购买咨询链接
  - 购买咨询链接记录
  positive_examples:
  - 找在视频号直播间购买了咨询链接的客户
  - 查询在视频号直播间购买咨询链接的人
  - 哪些客户购买了咨询链接
  - 筛选出有过在视频号直播间买了咨询链接行为的客户
  negative_examples:
  - 找没有购买咨询链接的客户
  - 排除购买咨询链接的客户
  - 查询从未购买咨询链接的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_117
  activity: CHENGXING_LIVE_CANCEL_RESERVE
  intent_category: 取消橙星直播间购买的服务咨询订单进行了退单退款
  activity_template: 取消橙星直播间购买的服务咨询订单“$serviceName$”，进行了退单退款
  description: 表示客户发生了“取消橙星直播间购买的服务咨询订单进行了退单退款”行为。
  aliases:
  - 取消橙星直播间购买的服务咨询订单进行了退单退款
  - 取消咨询服务订单
  - 服务咨询订单退单
  - 咨询订单退款
  - 取消橙星直播间购买的服务咨询订单进行退单退款
  - 退订橙星直播间购买的服务咨询订单进行了退单退款
  - 有过取消橙星直播间购买的服务咨询订单进行退单退款行为
  - 曾经取消橙星直播间购买的服务咨询订单进行退单退款
  positive_examples:
  - 找取消橙星直播间购买的服务咨询订单进行了退单退款的客户
  - 查询取消咨询服务订单的人
  - 哪些客户服务咨询订单退单
  - 筛选出有过咨询订单退款行为的客户
  negative_examples:
  - 找没有取消橙星直播间购买的服务咨询订单进行退单退款的客户
  - 排除取消橙星直播间购买的服务咨询订单进行退单退款的客户
  - 查询从未取消橙星直播间购买的服务咨询订单进行退单退款的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_118
  activity: JGJ_OLDCARE_SERVICE_RESERVE
  intent_category: 在金管家预约了养老规划服务快去联系喔
  activity_template: 在金管家预约了「养老规划服务」，快去联系喔！
  description: 表示客户发生了“在金管家预约了养老规划服务快去联系喔”行为。
  aliases:
  - 在金管家预约了养老规划服务
  - 在金管家预约了养老规划服务快去联系喔
  - 在金管家预约养老规划服务快去联系喔
  - 预约了养老规划服务快去联系喔
  - 在金管家预订了养老规划服务快去联系喔
  - 有过预约养老规划服务快去联系喔行为
  - 曾经预约养老规划服务快去联系喔
  - 预约养老规划服务快去联系喔记录
  positive_examples:
  - 找在金管家预约了养老规划服务的客户
  - 查询在金管家预约了养老规划服务快去联系喔的人
  - 哪些客户在金管家预约养老规划服务快去联系喔
  - 筛选出有过预约了养老规划服务快去联系喔行为的客户
  negative_examples:
  - 找没有预约养老规划服务的客户
  - 排除预约养老规划服务的客户
  - 查询从未预约养老规划服务的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_119
  activity: JGJ_ACTIVITY_PABNX_RESERVE
  intent_category: 在参与平安伴你行活动时点击预约了解
  activity_template: 在参与“平安伴你行”活动时，点击预约了解$reservationItemName$
  description: 表示客户发生了“在参与平安伴你行活动时点击预约了解”行为。
  aliases:
  - 在参与平安伴你行活动时点击预约了解
  - 在参与平安伴你行活动时点击预约咨询
  - 在参与平安伴你行活动时点击想了解
  - 在参加平安伴你行活动时点击预约了解
  - 在参与平安伴你行活动时点过预约了解
  - 有过在参与平安伴你行活动时点击预约了解行为
  - 曾经在参与平安伴你行活动时点击预约了解
  - 在参与平安伴你行活动时点击预约了解记录
  positive_examples:
  - 找在参与平安伴你行活动时点击预约了解的客户
  - 查询在参与平安伴你行活动时点击预约咨询的人
  - 哪些客户在参与平安伴你行活动时点击想了解
  - 筛选出有过在参加平安伴你行活动时点击预约了解行为的客户
  negative_examples:
  - 找没有在参与平安伴你行活动时点击预约了解的客户
  - 排除在参与平安伴你行活动时点击预约了解的客户
  - 查询从未在参与平安伴你行活动时点击预约了解的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_120
  activity: JGJ_RESERVE_TPA
  intent_category: 在金管家泰安系列介绍中查看并预约了
  activity_template: 在金管家添平安系列介绍中查看并预约了「“$reserveItemName$”」
  description: 表示客户发生了“在金管家泰安系列介绍中查看并预约了”行为。
  aliases:
  - 在金管家泰安系列介绍中查看并预约了
  - 在金管家泰安系列介绍中查看并预约
  - 泰安系列介绍中查看并预约了
  - 在金管家泰安系列介绍中浏览并预约了
  - 在金管家泰安系列介绍中查看并预订了
  - 有过泰安系列介绍中查看并预约行为
  - 曾经泰安系列介绍中查看并预约
  - 泰安系列介绍中查看并预约记录
  positive_examples:
  - 找在金管家泰安系列介绍中查看并预约了的客户
  - 查询在金管家泰安系列介绍中查看并预约的人
  - 哪些客户泰安系列介绍中查看并预约了
  - 筛选出有过在金管家泰安系列介绍中浏览并预约了行为的客户
  negative_examples:
  - 找没有泰安系列介绍中查看并预约的客户
  - 排除泰安系列介绍中查看并预约的客户
  - 查询从未泰安系列介绍中查看并预约的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_121
  activity: JGJ_RIGHT_MedicalEscort_Used
  intent_category: 朋友或家属在金管家权益中预约了的陪诊服务
  activity_template: 朋友或家属在金管家权益中，预约了$servertime$的陪诊服务
  description: 明确由客户的朋友、亲友或家属代为发起金管家权益陪诊预约，预约主体不是客户本人。
  selection_notes: 只有原文明确朋友、亲友、家属、代约或代为预约时选择本候选；没有关系人线索时默认是客户本人预约，选择 JGJ_RIGHT_MedicalEscort。
  aliases:
  - 朋友或家属在金管家权益中预约的陪诊服务
  - 朋友或家属在金管家权益中预约了的陪诊服务
  - 朋友或家属在金管家权益中预订了的陪诊服务
  - 有过朋友或家属在金管家权益中预约的陪诊服务行为
  - 曾经朋友或家属在金管家权益中预约的陪诊服务
  - 朋友或家属在金管家权益中预约的陪诊服务记录
  positive_examples:
  - 找朋友或家属在金管家权益中预约的陪诊服务的客户
  - 查询朋友或家属在金管家权益中预约了的陪诊服务的人
  - 哪些客户朋友或家属在金管家权益中预订了的陪诊服务
  - 筛选出有过朋友或家属在金管家权益中预约的陪诊服务行为的客户
  negative_examples:
  - 找客户本人使用权益预约陪诊的人
  - 查询没有说明朋友或家属的陪诊预约
  - 找没有朋友或家属在金管家权益中预约的陪诊服务的客户
  - 排除朋友或家属在金管家权益中预约的陪诊服务的客户
  - 查询从未朋友或家属在金管家权益中预约的陪诊服务的人
  confusing_intents:
  - JGJ_RIGHT_MedicalEscort
  is_supported: true
- candidate_id: behavior_candidate_122
  activity: JGJ_RIGHT_MedicalEscort
  intent_category: 在金管家权益中预约了的陪诊服务
  activity_template: 在金管家权益中，预约了$servertime$的陪诊服务
  description: 客户本人在金管家权益中预约陪诊服务；未提及其他预约主体时默认由客户本人发起。
  selection_notes: 原文只有“使用或通过权益预约陪诊”且没有朋友、亲友、家属、代约等关系人线索时选择本候选；明确关系人代约时选择 JGJ_RIGHT_MedicalEscort_Used。
  aliases:
  - 在金管家权益中预约的陪诊服务
  - 在金管家权益中预约了的陪诊服务
  - 权益中预约了的陪诊服务
  - 在金管家权益中预订了的陪诊服务
  - 有过权益中预约的陪诊服务行为
  - 曾经权益中预约的陪诊服务
  - 权益中预约的陪诊服务记录
  positive_examples:
  - 找在金管家权益中预约的陪诊服务的客户
  - 查询在金管家权益中预约了的陪诊服务的人
  - 哪些客户权益中预约了的陪诊服务
  - 筛选出有过在金管家权益中预订了的陪诊服务行为的客户
  negative_examples:
  - 找朋友或家属代为预约陪诊的客户
  - 找没有权益中预约的陪诊服务的客户
  - 排除权益中预约的陪诊服务的客户
  - 查询从未权益中预约的陪诊服务的人
  confusing_intents:
  - JGJ_RIGHT_MedicalEscort_Used
  is_supported: true
- candidate_id: behavior_candidate_123
  activity: JGJ_Product_YJX_ZHUANBAO_READ
  intent_category: 浏览了转保产品
  activity_template: 浏览了转保产品“$productname$”
  description: 表示客户发生了“浏览了转保产品”行为。
  aliases:
  - 浏览了转保产品
  - 浏览转保产品
  - 看过转保产品
  - 查看了转保产品
  - 有过浏览转保产品行为
  - 曾经浏览转保产品
  - 浏览转保产品记录
  positive_examples:
  - 找浏览了转保产品的客户
  - 查询浏览转保产品的人
  - 哪些客户看过转保产品
  - 筛选出有过查看了转保产品行为的客户
  negative_examples:
  - 找没有浏览转保产品的客户
  - 排除浏览转保产品的客户
  - 查询从未浏览转保产品的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_124
  activity: JGJ_Product_YJX_BUY_SUCCESS
  intent_category: 购买产品
  activity_template: 购买产品“$productname$”
  description: 表示客户发生了“购买产品”行为。
  aliases:
  - 购买了产品
  - 买了产品
  - 购买产品
  - 下单购买产品
  - 买过产品
  - 有过购买产品行为
  - 曾经购买产品
  - 购买产品记录
  positive_examples:
  - 找购买了产品的客户
  - 查询买了产品的人
  - 哪些客户购买产品
  - 筛选出有过下单购买产品行为的客户
  negative_examples:
  - 找购买成功的客户
  - 找完成购买的客户
  - 找没有购买产品的客户
  - 排除购买产品的客户
  - 查询从未购买产品的人
  confusing_intents:
  - ZEB_PRODUCT_BUY
  - JGJ_Product_Succeed
  is_supported: true
- candidate_id: behavior_candidate_125
  activity: JGJ_Product_YJX_BUY_FAILD
  intent_category: 点击投保但未完成
  activity_template: 点击了立即投保“$productname$”产品，但未完成投保
  description: 表示客户发生了“点击投保但未完成”行为。
  aliases:
  - 点击立即投保但未完成
  - 点了投保但没完成投保
  - 点击了立即投保产品但未完成投保
  - 点击投保但未完成
  - 点了立即投保但没投保成功
  - 投保流程未完成
  - 点击立即投保但未做完
  - 点过立即投保但未完成
  positive_examples:
  - 找点击立即投保但未完成的客户
  - 查询点了投保但没完成投保的人
  - 哪些客户点击了立即投保产品但未完成投保
  - 筛选出有过点击投保但未完成行为的客户
  negative_examples:
  - 找点击我要投保的客户
  - 找购买了产品的客户
  - 找没有点击立即投保但未完成的客户
  - 排除点击立即投保但未完成的客户
  - 查询从未点击立即投保但未完成的人
  confusing_intents:
  - JGJ_Product_Insure
  - JGJ_Product_YJX_BUY_SUCCESS
  is_supported: true
- candidate_id: behavior_candidate_126
  activity: jgj_real_activity_OlderDance_Apply
  intent_category: 在金管家微信小程序银龄舞集报名活动中加入了您绑定的舞蹈队
  activity_template: 在金管家微信小程序「银龄舞集报名活动」中，加入了您绑定的舞蹈队$teamName$
  description: 表示客户发生了“在金管家微信小程序银龄舞集报名活动中加入了您绑定的舞蹈队”行为。
  aliases:
  - 在金管家微信小程序银龄舞集报名活动中加入了您绑定的舞蹈队
  - 在金管家微信小程序银龄舞集报名活动中加入您绑定的舞蹈队
  - 银龄舞集报名活动中加入了您绑定的舞蹈队
  - 在金管家微信小程序银龄舞集报名活动中成为了您绑定的舞蹈队
  - 有过银龄舞集报名活动中加入您绑定的舞蹈队行为
  - 曾经银龄舞集报名活动中加入您绑定的舞蹈队
  - 银龄舞集报名活动中加入您绑定的舞蹈队记录
  positive_examples:
  - 找在金管家微信小程序银龄舞集报名活动中加入了您绑定的舞蹈队的客户
  - 查询在金管家微信小程序银龄舞集报名活动中加入您绑定的舞蹈队的人
  - 哪些客户银龄舞集报名活动中加入了您绑定的舞蹈队
  - 筛选出有过在金管家微信小程序银龄舞集报名活动中成为了您绑定的舞蹈队行为的客户
  negative_examples:
  - 找没有银龄舞集报名活动中加入您绑定的舞蹈队的客户
  - 排除银龄舞集报名活动中加入您绑定的舞蹈队的客户
  - 查询从未银龄舞集报名活动中加入您绑定的舞蹈队的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_127
  activity: CHENGXING_LIVE_RESERVE_DY
  intent_category: 在抖音直播间预约了保险咨询服务
  activity_template: 在抖音直播间预约了保险咨询服务
  description: 表示客户发生了“在抖音直播间预约了保险咨询服务”行为。
  aliases:
  - 在抖音直播间预约了保险咨询服务
  - 在抖音直播间预约保险咨询服务
  - 预约了保险咨询服务
  - 在抖音直播间预订了保险咨询服务
  - 有过预约保险咨询服务行为
  - 曾经预约保险咨询服务
  - 预约保险咨询服务记录
  positive_examples:
  - 找在抖音直播间预约了保险咨询服务的客户
  - 查询在抖音直播间预约保险咨询服务的人
  - 哪些客户预约了保险咨询服务
  - 筛选出有过在抖音直播间预订了保险咨询服务行为的客户
  negative_examples:
  - 找没有预约保险咨询服务的客户
  - 排除预约保险咨询服务的客户
  - 查询从未预约保险咨询服务的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_128
  activity: OnePokect_Culturegiif_Order
  intent_category: 已在壹钱包完成文创建制请查看文创礼遇平台购物车并确认订单
  activity_template: 已在壹钱包完成文创定制，请查看文创礼遇平台购物车并确认订单
  description: 表示客户发生了“已在壹钱包完成文创建制请查看文创礼遇平台购物车并确认订单”行为。
  aliases:
  - 已在壹钱包完成文创建制请查看文创礼遇平台购物车并确认订单
  - 已在壹钱包完成文创建制请浏览文创礼遇平台购物车并确认订单
  - 已在壹钱包做完文创建制请查看文创礼遇平台购物车并确认订单
  positive_examples:
  - 找已在壹钱包完成文创建制请查看文创礼遇平台购物车并确认订单的客户
  - 查询已在壹钱包完成文创建制请浏览文创礼遇平台购物车并确认订单的人
  - 哪些客户已在壹钱包做完文创建制请查看文创礼遇平台购物车并确认订单
  negative_examples:
  - 找没有已在壹钱包完成文创建制请查看文创礼遇平台购物车并确认订单的客户
  - 排除已在壹钱包完成文创建制请查看文创礼遇平台购物车并确认订单的客户
  - 查询从未已在壹钱包完成文创建制请查看文创礼遇平台购物车并确认订单的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_129
  activity: ztProduct_ZJ_Car_Conclusion
  intent_category: 名下车辆核保结论已下发核保结论为
  activity_template: 名下车辆$carNo$核保结论已下发，核保结论为$conclusion$
  description: 车辆、车险或汽车的核保结论已经下发，包括车辆核保通过或未通过。
  selection_notes: 明确车辆语境时优先于普通寿险或健康险产品核保候选。
  aliases:
  - 名下车辆核保结论已下发核保结论为
  - 有过名下车辆核保结论已下发核保结论为行为
  - 曾经名下车辆核保结论已下发核保结论为
  - 名下车辆核保结论已下发核保结论为记录
  positive_examples:
  - 找车辆或车险核保通过的客户
  - 查询汽车核保未通过或核保结论已下发的人
  - 哪些客户曾经名下车辆核保结论已下发核保结论为
  - 筛选出有过名下车辆核保结论已下发核保结论为记录行为的客户
  negative_examples:
  - 找寿险、健康险产品核保成功的客户
  - 查询没有车辆语境的普通产品核保结果
  - 查询从未名下车辆核保结论已下发核保结论为的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_130
  activity: ztProduct_ZJ_Car_Conclusion_2
  intent_category: 名下车辆验车结论已下发验车结论为
  activity_template: 名下车辆$carNo$验车结论已下发，验车结论为$conclusion$
  description: 表示客户发生了“名下车辆验车结论已下发验车结论为”行为。
  aliases:
  - 名下车辆验车结论已下发验车结论为
  - 有过名下车辆验车结论已下发验车结论为行为
  - 曾经名下车辆验车结论已下发验车结论为
  - 名下车辆验车结论已下发验车结论为记录
  positive_examples:
  - 找名下车辆验车结论已下发验车结论为的客户
  - 查询有过名下车辆验车结论已下发验车结论为行为的人
  - 哪些客户曾经名下车辆验车结论已下发验车结论为
  - 筛选出有过名下车辆验车结论已下发验车结论为记录行为的客户
  negative_examples:
  - 找没有名下车辆验车结论已下发验车结论为的客户
  - 排除名下车辆验车结论已下发验车结论为的客户
  - 查询从未名下车辆验车结论已下发验车结论为的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_131
  activity: ztProduct_ZJ_Car_Renewal
  intent_category: 对车辆进行了
  activity_template: 对车辆$carNo$进行了$activity$
  description: 客户对名下车辆执行报价、续保或其他明确车辆操作，操作名称由事件槽位记录。
  aliases:
  - 对车辆进行操作
  - 给车辆做报价
  - 车辆报价记录
  - 名下车辆操作记录
  - 对自己的车做过处理
  positive_examples:
  - 找给名下车辆做过报价的客户
  - 查询有明确车辆操作记录的人
  - 哪些客户对自己的车执行过业务操作
  - 筛选车辆报价或续保行为记录
  negative_examples:
  - 找只浏览车险报价单的客户
  - 查询车辆核保结论已下发的人
  - 查询从未进行车辆业务操作的人
  confusing_intents:
  - ZEB_ZT_PRODUCT_READ
  - ZEB_ZT_PRODUCT_READEND
  - ztProduct_ZJ_Car_Conclusion
  - ztProduct_ZJ_Car_Conclusion_2
  is_supported: true
- candidate_id: behavior_candidate_132
  activity: ztProduct_ZJ_Health_Claims
  intent_category: 名下健康险保单案件情况案件类型
  activity_template: 名下健康险保单$polno$，案件情况：$caseStatus$，案件类型：$caseType$
  description: 表示客户发生了“名下健康险保单案件情况案件类型”行为。
  aliases:
  - 名下健康险保单案件情况案件类型
  - 有过名下健康险保单案件情况案件类型行为
  - 曾经名下健康险保单案件情况案件类型
  - 名下健康险保单案件情况案件类型记录
  positive_examples:
  - 找名下健康险保单案件情况案件类型的客户
  - 查询有过名下健康险保单案件情况案件类型行为的人
  - 哪些客户曾经名下健康险保单案件情况案件类型
  - 筛选出有过名下健康险保单案件情况案件类型记录行为的客户
  negative_examples:
  - 找没有名下健康险保单案件情况案件类型的客户
  - 排除名下健康险保单案件情况案件类型的客户
  - 查询从未名下健康险保单案件情况案件类型的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_133
  activity: jgj_real_activity_OlderDance_Creat
  intent_category: 在金管家微信小程序银龄舞集报名活动中提交了舞蹈队的报名审核申请
  activity_template: 在金管家微信小程序「银龄舞集报名活动」中，提交了舞蹈队$teamName$的报名审核申请
  description: 表示客户发生了“在金管家微信小程序银龄舞集报名活动中提交了舞蹈队的报名审核申请”行为。
  aliases:
  - 在金管家微信小程序银龄舞集报名活动中提交了舞蹈队的报名审核申请
  - 在金管家微信小程序银龄舞集报名活动中提交舞蹈队的报名审核申请
  - 银龄舞集报名活动中提交了舞蹈队的报名审核申请
  - 在金管家微信小程序银龄舞集报名活动中递交了舞蹈队的报名审核申请
  - 有过银龄舞集报名活动中提交舞蹈队的报名审核申请行为
  - 曾经银龄舞集报名活动中提交舞蹈队的报名审核申请
  - 银龄舞集报名活动中提交舞蹈队的报名审核申请记录
  positive_examples:
  - 找在金管家微信小程序银龄舞集报名活动中提交了舞蹈队的报名审核申请的客户
  - 查询在金管家微信小程序银龄舞集报名活动中提交舞蹈队的报名审核申请的人
  - 哪些客户银龄舞集报名活动中提交了舞蹈队的报名审核申请
  - 筛选出有过在金管家微信小程序银龄舞集报名活动中递交了舞蹈队的报名审核申请行为的客户
  negative_examples:
  - 找没有银龄舞集报名活动中提交舞蹈队的报名审核申请的客户
  - 排除银龄舞集报名活动中提交舞蹈队的报名审核申请的客户
  - 查询从未银龄舞集报名活动中提交舞蹈队的报名审核申请的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_134
  activity: ztProduct_ZJ_Property_Claims
  intent_category: 名下产险保单案件经过
  activity_template: 名下产险保单$situation$，案件经过：$desribe$
  description: 表示客户发生了“名下产险保单案件经过”行为。
  aliases:
  - 名下产险保单案件经过
  - 有过名下产险保单案件经过行为
  - 曾经名下产险保单案件经过
  - 名下产险保单案件经过记录
  positive_examples:
  - 找名下产险保单案件经过的客户
  - 查询有过名下产险保单案件经过行为的人
  - 哪些客户曾经名下产险保单案件经过
  - 筛选出有过名下产险保单案件经过记录行为的客户
  negative_examples:
  - 找没有名下产险保单案件经过的客户
  - 排除名下产险保单案件经过的客户
  - 查询从未名下产险保单案件经过的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_135
  activity: JGJ_READCLUB_ACTIVITY_JOIN
  intent_category: 在金管家提交了预报名报名信息请详情
  activity_template: 在金管家提交了$scene$预报名，报名信息请见详情
  description: 表示客户发生了“在金管家提交了预报名报名信息请详情”行为。
  aliases:
  - 在金管家提交了预报名报名信息请详情
  - 在金管家提交预报名报名信息请详情
  - 提交了预报名报名信息请详情
  - 在金管家递交了预报名报名信息请详情
  - 有过提交预报名报名信息请详情行为
  - 曾经提交预报名报名信息请详情
  - 提交预报名报名信息请详情记录
  positive_examples:
  - 找在金管家提交了预报名报名信息请详情的客户
  - 查询在金管家提交预报名报名信息请详情的人
  - 哪些客户提交了预报名报名信息请详情
  - 筛选出有过在金管家递交了预报名报名信息请详情行为的客户
  negative_examples:
  - 找没有提交预报名报名信息请详情的客户
  - 排除提交预报名报名信息请详情的客户
  - 查询从未提交预报名报名信息请详情的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_136
  activity: KDE_ClientNote_Ai
  intent_category: 创建AI客户笔记
  activity_template: 创建AI客户笔记
  description: 客户创建明确标注为AI生成、AI辅助或智能类型的客户笔记。
  aliases:
  - 创建AI客户笔记
  - 新建AI客户笔记
  - 生成AI客户笔记
  - 创建智能客户笔记
  - 有过创建AI客户笔记行为
  - 曾经创建AI客户笔记
  - 创建AI客户笔记记录
  positive_examples:
  - 找创建过AI客户笔记的客户
  - 查询生成过智能客户笔记的人
  - 哪些客户曾经创建AI客户笔记
  - 筛选出有过创建AI客户笔记记录行为的客户
  negative_examples:
  - 找创建普通客户笔记的客户
  - 查询创建手工客户笔记的人
  - 查询从未创建AI客户笔记的人
  confusing_intents:
  - KDE_ClientNote_Normal
  is_supported: true
- candidate_id: behavior_candidate_137
  activity: JGJ_FANDENG_ACTIVITY_CYYX
  intent_category: 客户在活动中表示了有意向参与樊登家庭教育讲座
  activity_template: 客户在$activityName$活动中，表示了有意向参与“樊登家庭教育讲座”
  description: 客户在活动场景中表达参加樊登家庭教育讲座的意向。
  aliases:
  - 客户在活动中表示了有意向参与樊登家庭教育讲座
  - 客户在活动中表示有意向参与樊登家庭教育讲座
  - 客户在活动中表示了有意向参加樊登家庭教育讲座
  - 有过客户在活动中表示有意向参与樊登家庭教育讲座行为
  - 曾经客户在活动中表示有意向参与樊登家庭教育讲座
  - 客户在活动中表示有意向参与樊登家庭教育讲座记录
  positive_examples:
  - 找在活动中表达樊登家庭教育讲座意向的客户
  - 查询想参加樊登家庭教育讲座的人
  - 哪些客户在活动中表示了有意向参加樊登家庭教育讲座
  - 筛选出有过客户在活动中表示有意向参与樊登家庭教育讲座行为的客户
  negative_examples:
  - 找通过老客户分享链接产生讲座意向的客户
  - 查询已经完成线下活动报名的人
  - 查询从未客户在活动中表示有意向参与樊登家庭教育讲座的人
  confusing_intents:
  - JGJ_MEETINGE_BAO_SIGNUP_ONLINE
  - JGJ_FANDENG_ACTIVITY_LYX
  is_supported: true
- candidate_id: behavior_candidate_138
  activity: JGJ_JJQYGZH
  intent_category: 在金管家确认了您分享的居家权益告知函
  activity_template: 在金管家确认了您分享的“居家权益告知函”
  description: 表示客户发生了“在金管家确认了您分享的居家权益告知函”行为。
  aliases:
  - 在金管家确认了您分享的居家权益告知函
  - 在金管家确认您分享的居家权益告知函
  - 确认了您分享的居家权益告知函
  - 有过确认您分享的居家权益告知函行为
  - 曾经确认您分享的居家权益告知函
  - 确认您分享的居家权益告知函记录
  positive_examples:
  - 找在金管家确认了您分享的居家权益告知函的客户
  - 查询在金管家确认您分享的居家权益告知函的人
  - 哪些客户确认了您分享的居家权益告知函
  - 筛选出有过确认您分享的居家权益告知函行为的客户
  negative_examples:
  - 找没有确认您分享的居家权益告知函的客户
  - 排除确认您分享的居家权益告知函的客户
  - 查询从未确认您分享的居家权益告知函的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_139
  activity: JGJ_RIGHT_HOMESERVICE1
  intent_category: 客户关系人动态行为
  activity_template: 客户 $relation$$action$$item$
  description: 客户的家属、亲友、同事等关系人针对某个项目发生推荐、领取、查看或参与行为。
  aliases:
  - 客户关系人动态行为
  - 家属发生行为
  - 亲友发生行为
  - 客户家属领取项目
  - 客户亲友参与活动
  - 客户同事推荐服务
  - 客户关系人推荐项目
  - 客户身边人发生行为
  positive_examples:
  - 找家属领取过服务项目的客户
  - 查询亲友或同事推荐过项目的客户
  - 哪些客户的关系人参与过活动
  - 筛选关系人查看过指定内容的客户
  negative_examples:
  - 找客户本人领取服务项目的记录
  - 查询客户本人参加活动的行为
  - 查询从未客户关系人动态行为的人
  confusing_intents:
  - JGJ_CHRONIC_DISEASE_03
  - JGJ_POLICY_CLAIM_ASSIST
  - JGJ_RIGHT_MedicalEscort_Used
  is_supported: true
- candidate_id: behavior_candidate_140
  activity: JGJ_POLICY_SERVICE_2026
  intent_category: 在金管家使用了分类的服务保险产品为保单号投保单号
  activity_template: '在金管家使用了「$serviceType$」分类的「$serviceName$」服务，保险产品为「$productName$」，保单号（投保单号）: $policyNo$'
  description: 客户在金管家使用明确服务分类下的服务，或办理资料变更、保全等具有确定分类归属的新版保单服务。
  selection_notes: 必须明确出现服务分类，或明确资料变更、保全等分类型服务动作；只有具体服务名、产品名、保单号或泛化“使用保单服务”时选择 JGJ_POLICY_SERVICE_01，不要仅凭保单号选择本候选。
  aliases:
  - 在金管家办理保单服务
  - 客户资料变更服务
  - 保单资料变更记录
  - 使用保单关联服务
  - 金管家保单服务记录
  - 在金管家使用了分类的服务保险产品为涉及保单
  - 在金管家使用了分类的服务保险产品为保单号投保单号
  - 在金管家使用分类的服务保险产品为保单号投保单号
  - 使用了分类的服务保险产品为保单号投保单号
  - 在金管家用过分类的服务保险产品为保单号投保单号
  - 有过使用分类的服务保险产品为保单号投保单号行为
  - 曾经使用分类的服务保险产品为保单号投保单号
  - 使用分类的服务保险产品为保单号投保单号记录
  positive_examples:
  - 找在金管家办过客户资料变更服务的人
  - 查询使用过保单关联服务的客户
  - 哪些客户在金管家使用分类的服务保险产品为保单号投保单号
  - 筛选出有过使用了分类的服务保险产品为保单号投保单号行为的客户
  negative_examples:
  - 找只开通保单管家但没有办理服务的客户
  - 查询完成保单托管授权的人
  - 查询只给出具体服务名和保单号但没有服务分类的人
  - 查询从未使用分类的服务保险产品为涉及保单的人
  confusing_intents:
  - JGJ_POLICY_SERVICE_01
  - KDE_BDTG_DTG
  - BDGJ_WXMINIAPP_BDGJ_APPLY
  - BDGJ_JGJAPP_APPLY
  - BDGJ_WXMINIAPP_JGJ_APPLY
  is_supported: true
- candidate_id: behavior_candidate_141
  activity: JGJ_YSS_CT
  intent_category: 在金管家参团了线下活动参团场次参团人数
  activity_template: '在金管家参团了$activityName$线下活动

    · 参团场次：$activitytime$

    · 参团人数：$activityNumber$'
  description: 客户直接在金管家参加线下团活动，事件记录包含场次或参团人数。
  aliases:
  - 在金管家参团了线下活动参团场次参团人数
  - 在金管家参团线下活动参团场次参团人数
  - 参团了线下活动参团场次参团人数
  - 有过参团线下活动参团场次参团人数行为
  - 曾经参团线下活动参团场次参团人数
  - 参团线下活动参团场次参团人数记录
  positive_examples:
  - 找直接在金管家参加线下团活动的客户
  - 查询带场次或人数信息的参团记录
  - 哪些客户参团了线下活动参团场次参团人数
  - 筛选出有过参团线下活动参团场次参团人数行为的客户
  negative_examples:
  - 找通过老客户邀请参加线下团活动的人
  - 查询普通拼团活动成功参团的客户
  - 查询从未参团线下活动参团场次参团人数的人
  confusing_intents:
  - JGJ_PKT_ACTIVITY_02
  - JGJ_YSS_YYCT
  is_supported: true
- candidate_id: behavior_candidate_142
  activity: KDE_ClientNote_Normal
  intent_category: 创建客户笔记
  activity_template: 创建「$type$」客户笔记
  description: 客户创建带有某种类型标签的普通客户笔记。
  aliases:
  - 创建客户笔记
  - 有过创建客户笔记行为
  - 曾经创建客户笔记
  - 创建客户笔记记录
  positive_examples:
  - 找创建过普通客户笔记的客户
  - 查询新建某类客户笔记的人
  - 哪些客户曾经创建客户笔记
  - 筛选出有过创建客户笔记记录行为的客户
  negative_examples:
  - 找创建AI客户笔记的客户
  - 查询生成过智能客户笔记的人
  - 查询从未创建客户笔记的人
  confusing_intents:
  - KDE_ClientNote_Ai
  is_supported: true
- candidate_id: behavior_candidate_143
  activity: JGJ_FANDENG_ACTIVITY_LYX
  intent_category: 通过您的客户分享的活动链接参与活动表示了有意向参与樊登家庭教育讲座
  activity_template: 通过您的客户$oldName$分享的$activityName$活动链接参与活动，表示了有意向参与“樊登家庭教育讲座”
  description: 客户通过另一位客户分享的活动链接参与活动，并表达参加樊登家庭教育讲座的意向；分享人和链接来源是必要区别。
  aliases:
  - 通过您的客户分享的活动链接参与活动表示了有意向参与樊登家庭教育讲座
  - 通过您的客户分享的活动链接参与活动表示有意向参与樊登家庭教育讲座
  - 通过您的客户分享的活动链接参加活动表示了有意向参与樊登家庭教育讲座
  positive_examples:
  - 找通过老客户分享链接产生讲座意向的人
  - 查询由客户转介绍活动链接带来的讲座意向客户
  - 哪些客户通过您的客户分享的活动链接参加活动表示了有意向参与樊登家庭教育讲座
  negative_examples:
  - 找没有分享链接来源的普通讲座意向客户
  - 查询直接报名线下活动的人
  - 查询从未通过您的客户分享的活动链接参与活动表示有意向参与樊登家庭教育讲座的人
  confusing_intents:
  - JGJ_FANDENG_ACTIVITY_CYYX
  is_supported: true
- candidate_id: behavior_candidate_144
  activity: JGJ_SH_MS_PT
  intent_category: 您发起的团活动待向该客户配送货物请尽快完成配送流程以保证服务时效性
  activity_template: 您发起的团活动$name$待向该客户配送货物，请尽快完成配送流程以保证服务时效性
  description: 团购或团活动产生的货物处于待配送状态，需要完成配送流程。
  selection_notes: 必须同时存在团活动和待配送语义；普通活动中奖、领取奖品或非团活动上门递送不属于该候选。
  aliases:
  - 您发起的团活动待向该客户配送货物请尽快完成配送流程以保证服务时效性
  - 团活动货物待配送
  - 待向客户配送团活动货物
  - 团购货物等待配送
  - 待完成配送流程
  - 您发起的团活动待向该客户配送货物请尽快做完配送流程以保证服务时效性
  positive_examples:
  - 找您发起的团活动待向该客户配送货物请尽快完成配送流程以保证服务时效性的客户
  - 查询团活动货物待配送的人
  - 哪些客户待向客户配送团活动货物
  - 筛选出有过团购货物等待配送行为的客户
  negative_examples:
  - 找普通活动中获得或领取奖品的客户
  - 查询非团活动产生的上门递送奖品记录
  - 查询从未您发起的团活动待向该客户配送货物请尽快完成配送流程以保证服务时效性的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_145
  activity: JGJ_RIGHT_GET2
  intent_category: 兑换了权益建议您完成相关服务
  activity_template: 兑换了「$rightsName$」权益，建议您完成相关服务
  description: 表示客户发生了“兑换了权益建议您完成相关服务”行为。
  aliases:
  - 兑换了权益建议您完成相关服务
  - 兑换权益建议您完成相关服务
  - 兑换了权益建议您做完相关服务
  - 有过兑换权益建议您完成相关服务行为
  - 曾经兑换权益建议您完成相关服务
  - 兑换权益建议您完成相关服务记录
  positive_examples:
  - 找兑换了权益建议您完成相关服务的客户
  - 查询兑换权益建议您完成相关服务的人
  - 哪些客户兑换了权益建议您做完相关服务
  - 筛选出有过兑换权益建议您完成相关服务行为的客户
  negative_examples:
  - 找没有兑换权益建议您完成相关服务的客户
  - 排除兑换权益建议您完成相关服务的客户
  - 查询从未兑换权益建议您完成相关服务的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_146
  activity: JGJ_YSS_YYCT
  intent_category: 通过客户邀请参团了线下活动参团场次参团人数
  activity_template: '通过客户$oldcustomer$邀请，参团了$activityName$线下活动

    · 参团场次：$activitytime$

    · 参团人数：$activityNumber$'
  description: 客户经另一位客户邀请后参加线下团活动，事件记录包含活动、场次或人数信息。
  aliases:
  - 通过客户邀请参团了线下活动参团场次参团人数
  - 通过客户邀请参团线下活动参团场次参团人数
  - 经老客户邀请参加线下团活动
  - 被客户邀请后参团
  - 客户转介绍参团
  - 有过通过客户邀请参团线下活动参团场次参团人数行为
  - 曾经通过客户邀请参团线下活动参团场次参团人数
  - 通过客户邀请参团线下活动参团场次参团人数记录
  positive_examples:
  - 找经老客户邀请参加线下团活动的人
  - 查询由客户转介绍后参团的记录
  - 哪些客户有过通过客户邀请参团线下活动参团场次参团人数行为
  - 筛选出有过曾经通过客户邀请参团线下活动参团场次参团人数行为的客户
  negative_examples:
  - 找直接在金管家参加线下团活动的客户
  - 查询没有邀请来源的普通参团记录
  - 查询从未通过客户邀请参团线下活动参团场次参团人数的人
  confusing_intents:
  - JGJ_PKT_ACTIVITY_02
  - JGJ_YSS_CT
  is_supported: true
- candidate_id: behavior_candidate_147
  activity: SMARTVISIT_AIVIDEO_THUMBSUP_ZY
  intent_category: 点赞了智能拜访助手中的跟拍视频
  activity_template: 点赞了智能拜访助手中的跟拍视频$videoName$
  description: 表示客户发生了“点赞了智能拜访助手中的跟拍视频”行为。
  aliases:
  - 点赞了智能拜访助手中的跟拍视频
  - 点赞智能拜访助手中的跟拍视频
  - 点过赞智能拜访助手中的跟拍视频
  - 有过点赞智能拜访助手中的跟拍视频行为
  - 曾经点赞智能拜访助手中的跟拍视频
  - 点赞智能拜访助手中的跟拍视频记录
  positive_examples:
  - 找点赞了智能拜访助手中的跟拍视频的客户
  - 查询点赞智能拜访助手中的跟拍视频的人
  - 哪些客户点过赞智能拜访助手中的跟拍视频
  - 筛选出有过点赞智能拜访助手中的跟拍视频行为的客户
  negative_examples:
  - 找没有点赞智能拜访助手中的跟拍视频的客户
  - 排除点赞智能拜访助手中的跟拍视频的客户
  - 查询从未点赞智能拜访助手中的跟拍视频的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_148
  activity: SYZQ_ZEB_PRODUCT_SHARE
  intent_category: 转发分享了产品
  activity_template: 转发分享了产品“$productName$”
  description: 表示客户发生了“转发分享了产品”行为。
  aliases:
  - 转发分享了产品
  - 转发分享产品
  - 转发了产品
  - 分享了产品
  - 有过转发分享产品行为
  - 曾经转发分享产品
  - 转发分享产品记录
  positive_examples:
  - 找转发分享了产品的客户
  - 查询转发分享产品的人
  - 哪些客户转发了产品
  - 筛选出有过分享了产品行为的客户
  negative_examples:
  - 找没有转发分享产品的客户
  - 排除转发分享产品的客户
  - 查询从未转发分享产品的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_149
  activity: SYZQ_ZEB_INFO_THUMBSUP
  intent_category: 点赞了资讯
  activity_template: 点赞了资讯《$articleName$》
  description: 客户对资讯文章执行点赞或点过赞操作。
  aliases:
  - 点赞了资讯
  - 点赞资讯
  - 点过赞资讯
  - 给文章点赞
  - 给资讯文章点了赞
  - 文章点赞记录
  - 有过点赞资讯行为
  - 曾经点赞资讯
  - 点赞资讯记录
  positive_examples:
  - 找给资讯文章点过赞的客户
  - 查询文章点赞记录
  - 哪些客户点过赞资讯
  - 筛选出有过点赞资讯行为的客户
  negative_examples:
  - 找没有点赞资讯的客户
  - 排除点赞资讯的客户
  - 查询从未点赞资讯的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_150
  activity: SYZQ_ZEB_VIDEO_READEND
  intent_category: 浏览了展业短视频时长秒
  activity_template: 浏览了展业短视频“$videoName$”，时长$time$秒
  description: 表示客户发生了“浏览了展业短视频时长秒”行为。
  aliases:
  - 浏览了展业短视频时长秒
  - 浏览展业短视频时长秒
  - 看过展业短视频时长秒
  - 查看了展业短视频时长秒
  - 有过浏览展业短视频时长秒行为
  - 曾经浏览展业短视频时长秒
  - 浏览展业短视频时长秒记录
  positive_examples:
  - 找浏览展业短视频超过一分钟的客户
  - 查询浏览了展业短视频时长秒的人
  - 哪些客户浏览展业短视频时长秒
  - 筛选出有过看过展业短视频时长秒行为的客户
  negative_examples:
  - 找没有浏览展业短视频的客户
  - 排除浏览展业短视频的客户
  - 查询从未浏览展业短视频的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_151
  activity: SYZQ_ZEB_PRODUCT_READEND
  intent_category: 浏览了产品浏览时长秒
  activity_template: 浏览了产品“$productName$”，浏览时长$time$秒
  description: 客户浏览或查看某个产品，事件记录包含秒、分钟或停留时长信息。
  aliases:
  - 浏览产品时长
  - 查看产品停留时长
  - 在产品页面停留
  - 浏览产品若干秒
  - 产品浏览了多久
  - 浏览了产品浏览时长秒
  - 浏览产品浏览时长秒
  - 看过产品浏览时长秒
  - 查看了产品浏览时长秒
  - 有过浏览产品浏览时长秒行为
  - 曾经浏览产品浏览时长秒
  - 浏览产品浏览时长秒记录
  positive_examples:
  - 找浏览某个产品若干秒的客户
  - 查询在产品页面停留过一段时间的人
  - 哪些客户浏览产品浏览时长秒
  - 筛选出有过看过产品浏览时长秒行为的客户
  negative_examples:
  - 找只说看过产品但没有时长线索的人
  - 查询在资讯中进一步查看产品的客户
  - 查询从未浏览产品的人
  confusing_intents:
  - ZEB_INFO_PRODUCT
  - SYZQ_ZEB_INFO_PRODUCT
  is_supported: true
- candidate_id: behavior_candidate_152
  activity: SYZQ_ZEB_VIDEO_SHARE
  intent_category: 转发分享了展业短视频
  activity_template: 转发分享了展业短视频“$videoName$”
  description: 表示客户发生了“转发分享了展业短视频”行为。
  aliases:
  - 转发分享了展业短视频
  - 转发分享展业短视频
  - 转发了展业短视频
  - 分享了展业短视频
  - 有过转发分享展业短视频行为
  - 曾经转发分享展业短视频
  - 转发分享展业短视频记录
  positive_examples:
  - 找转发分享了展业短视频的客户
  - 查询转发分享展业短视频的人
  - 哪些客户转发了展业短视频
  - 筛选出有过分享了展业短视频行为的客户
  negative_examples:
  - 找没有转发分享展业短视频的客户
  - 排除转发分享展业短视频的客户
  - 查询从未转发分享展业短视频的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_153
  activity: LAIP_IVAP_VIDEO_N04
  intent_category: 预约了跟拍视频
  activity_template: 预约了跟拍视频$videoTitle$
  description: 表示客户发生了“预约了跟拍视频”行为。
  aliases:
  - 预约了跟拍视频
  - 预约跟拍视频
  - 预订了跟拍视频
  - 有过预约跟拍视频行为
  - 曾经预约跟拍视频
  - 预约跟拍视频记录
  positive_examples:
  - 找预约了跟拍视频的客户
  - 查询预约跟拍视频的人
  - 哪些客户预订了跟拍视频
  - 筛选出有过预约跟拍视频行为的客户
  negative_examples:
  - 找没有预约跟拍视频的客户
  - 排除预约跟拍视频的客户
  - 查询从未预约跟拍视频的人
  confusing_intents: []
  is_supported: true
- candidate_id: behavior_candidate_154
  activity: JGJ_O2O_PRODUCT_RESERVE
  intent_category: 在金管家预约了解产品
  activity_template: 在金管家预约了解产品“$productName$”
  description: 客户在金管家预约了解具体保险产品。
  aliases:
  - 在金管家预约了解产品
  - 在金管家预约咨询产品
  - 在金管家想了解产品
  - 有过在金管家预约了解产品行为
  - 曾经在金管家预约了解产品
  - 在金管家预约了解产品记录
  positive_examples:
  - 找在金管家预约了解保险产品的客户
  - 查询在金管家提交产品咨询的人
  - 哪些客户在金管家想了解产品
  - 筛选出有过在金管家预约了解产品行为的客户
  negative_examples:
  - 找在金管家权益专区预约服务的客户
  - 查询预约家庭财富保障方案讲解的人
  - 查询从未在金管家预约了解产品的人
  confusing_intents:
  - JGJ_ONLINE_SCENE_PRODUCT_RESERVE
  - JGJ_RIGHT_RESERVE
  - JGJ_FORTUNE_SERVICE_RESERVE
  - SYZQ_ZEB_PRODUCT_ORDER
  is_supported: true
- candidate_id: behavior_candidate_155
  activity: JGJ_LIFE_PRODUCT_RESERVE
  intent_category: 在金管家预约了解产品
  activity_template: 在金管家预约了解产品“$productName$”
  description: 客户在金管家预约了解具体保险产品。
  aliases:
  - 在金管家预约了解产品
  - 在金管家预约咨询产品
  - 在金管家想了解产品
  - 有过在金管家预约了解产品行为
  - 曾经在金管家预约了解产品
  - 在金管家预约了解产品记录
  positive_examples:
  - 找在金管家预约了解保险产品的客户
  - 查询在金管家提交产品咨询的人
  - 哪些客户在金管家想了解产品
  - 筛选出有过在金管家预约了解产品行为的客户
  negative_examples:
  - 找在金管家权益专区预约服务的客户
  - 查询预约家庭财富保障方案讲解的人
  - 查询从未在金管家预约了解产品的人
  confusing_intents:
  - JGJ_ONLINE_SCENE_PRODUCT_RESERVE
  - JGJ_RIGHT_RESERVE
  - JGJ_FORTUNE_SERVICE_RESERVE
  - SYZQ_ZEB_PRODUCT_ORDER
  is_supported: true
- candidate_id: behavior_candidate_156
  activity: '1773735520064'
  intent_category: 已加入金管家俱乐部会员对有较高兴趣
  activity_template: 已加入金管家$clubName$俱乐部会员，对$scene$有较高兴趣。
  description: 客户已经加入金管家某俱乐部，并对指定场景表现出较高兴趣。
  aliases:
  - 已加入金管家俱乐部会员对有较高兴趣
  - 已成为金管家俱乐部会员对有较高兴趣
  - 有过已加入金管家俱乐部会员对有较高兴趣行为
  - 曾经已加入金管家俱乐部会员对有较高兴趣
  - 已加入金管家俱乐部会员对有较高兴趣记录
  positive_examples:
  - 找已入会并对某类服务有兴趣的俱乐部会员
  - 查询加入金管家俱乐部后的场景意向客户
  - 哪些客户有过已加入金管家俱乐部会员对有较高兴趣行为
  - 筛选出有过曾经已加入金管家俱乐部会员对有较高兴趣行为的客户
  negative_examples:
  - 找入会后选择您作为保险规划师的客户
  - 查询只加入俱乐部但没有表达场景兴趣的人
  - 查询从未已加入金管家俱乐部会员对有较高兴趣的人
  confusing_intents:
  - jgj_eduClub_join
  - JGJ_CLUB_JOIN_BIND
  - JGJ_SNOWCLUB_JOIN
  is_supported: true
- candidate_id: behavior_candidate_157
  activity: JGJ_RIGHT_HOMESERVICE2
  intent_category: 客户关系人动态行为
  activity_template: 客户 $relation$$action$$item$
  description: 客户的家属、亲友、同事等关系人针对某个项目发生推荐、领取、查看或参与行为。
  aliases:
  - 客户关系人动态行为
  - 家属发生行为
  - 亲友发生行为
  - 客户家属领取项目
  - 客户亲友参与活动
  - 客户同事推荐服务
  - 客户关系人推荐项目
  - 客户身边人发生行为
  positive_examples:
  - 找家属领取过服务项目的客户
  - 查询亲友或同事推荐过项目的客户
  - 哪些客户的关系人参与过活动
  - 筛选关系人查看过指定内容的客户
  negative_examples:
  - 找客户本人领取服务项目的记录
  - 查询客户本人参加活动的行为
  - 查询从未客户关系人动态行为的人
  confusing_intents:
  - JGJ_CHRONIC_DISEASE_03
  - JGJ_POLICY_CLAIM_ASSIST
  - JGJ_RIGHT_MedicalEscort_Used
  is_supported: true
- candidate_id: behavior_candidate_158
  activity: '1773973964997'
  activity_template: 您的客户在金管家-成长基金教育测评完成了测评
  intent_category: 成长基金教育测评完成
  description: 表示客户完成了金管家成长基金教育测评。
  aliases:
  - 成长基金教育测评完成
  - 完成成长基金教育测评
  - 做完成长基金教育测评
  positive_examples:
  - 找完成成长基金教育测评的客户
  - 查询做过成长基金教育测评的人
  negative_examples:
  - 找没有完成成长基金教育测评的客户
  confusing_intents: []
  is_supported: true
