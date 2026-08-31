# behavior_enhanced_rules_args.yaml

- evidence_ref: `business-behavior-rules`
- location: `business://src/main/python/data/client_search_query_parse/behavior_enhanced_rules_args.yaml`
- source_revision: `a2cfd68ea351d5081d95857ca7bcbfac90434528`
- source_sha256: `162634b55fe16f884db6944a574ac1fa15302a38930ea2e3de93e9f4cdbf1961`

Regex/priority parser rules for behavior intent selection. current_behavior only; cannot be used as a normative gate.

---

text_processing:
  placeholder_pattern: \$[^$]+\$
  punctuation_pattern: '[\s，,。！？!?；;：:“”‘’''"《》「」【】（）()·•~～]+'
  query_noise_pattern: (?:帮我|请|麻烦|查找|查询|搜索|找出|筛选|看看|找|客户名单|客户|名单|的人|有哪些人)
  negation_pattern: (?:没有|没做过|没发生过|不曾|从未|尚未|未曾)
  existence_question_pattern: (?:有没有|有没|有无|是否有)
  business_id_pattern: \b(?:[A-Za-z]\s*)?\d{8,}\b
  number_pattern: \d+(?:\.\d+)?
  retrieval_noise_pattern: (?:帮我|麻烦|请问|请|查一下|查下|查询|查找|搜索|找出|筛选|筛一下|看看|看下|给我|发我|我想找|想找|谁|哪些|有没有|有无|是否有|有人|客户名单|名单|客户|的人|的客户|记录)
  activity_id_pattern: ^[A-Za-z0-9_]+$
  retrieval_synonyms:
  - pattern: (?:转出去|转给|转过|分享给|分享过|转发过)
    replacement: 转发
  - pattern: (?:买下来了|买下来|买下|买过|买了|购入|购买过)
    replacement: 购买
  - pattern: (?:点了赞|点过赞|赞过)
    replacement: 点赞
  - pattern: (?:约了|约过|预约过|预订过|预定过)
    replacement: 预约
  - pattern: (?:算过|算了|测算过|计算过)
    replacement: 测算
  - pattern: (?:领过|领了|拿到|拿了)
    replacement: 领取
  - pattern: (?:用过|用了)
    replacement: 使用
  - pattern: (?:看了一下|看了下)
    replacement: 查看
  - pattern: (?:送货|寄送|派送)
    replacement: 配送
  slot_type_terms:
  - fragments:
    - product
    - plan
    label: 产品
  - fragments:
    - article
    label: 文章
  - fragments:
    - topic
    label: 专题
  - fragments:
    - content
    label: 内容
  - fragments:
    - service
    - item
    label: 服务
  - fragments:
    - equity
    - rights
    - right
    - gift
    - prize
    label: 权益
  - fragments:
    - activity
    - name
    label: 活动
  - fragments:
    - video
    label: 视频
  - fragments:
    - tool
    label: 工具
  - fragments:
    - policy
    - polno
    label: 保单
  - fragments:
    - time
    - duration
    label: 时长
  - fragments:
    - club
    label: 俱乐部
  - fragments:
    - team
    label: 团队
  - fragments:
    - car
    label: 车辆
  - fragments:
    - amount
    - price
    - cost
    - prize
    label: 金额
pattern_vars:
  # 受限槽位不能跨越标点或新的并列行为边界。
  BEHAVIOR_PRODUCT_SLOT: '(?:(?!(?:，|,|。|！|!|？|\?|；|;|并且|而且|同时|以及|又|然后)).){1,32}?'
  BEHAVIOR_CLAUSE_GAP: '(?:(?!(?:，|,|。|！|!|？|\?|；|;|并且|而且|同时|以及|又|然后)).){0,12}'
  BEHAVIOR_SHORT_GAP: '(?:(?!(?:，|,|。|！|!|？|\?|；|;|并且|而且|同时|以及|又|然后)).){0,4}'
policies:
  implied_general_activity_suppressors:
    JGJ_Product_YJX_BUY_SUCCESS:
    - ZEB_PRODUCT_BUY
    - ZEB_PRODUCT_PAY
    - ZEB_PRODUCT_PAY_FINISH
    - ZEB_PRODUCT_SUBMIT
    - JGJ_Product_Succeed
    - ZEB_PRODUCT_PAY_FAIL
    - ZEB_PRODUCT_UNDERWRITE
    - ZEB_PRODUCT_UNDERWRITE_FAIL
    - JGJ_Product_YJX_BUY_FAILD
  duration_specificity:
    cue_pattern: (?:\d+(?:\.\d+)?\s*(?:秒|分钟|小时)|半分钟|时长|停留|仔细|认真)
    specific_by_general:
      ZEB_ZY_READ: ZEB_ZY_READEND
      ZEB_ZT_PRODUCT_READ: ZEB_ZT_PRODUCT_READEND
  multi_behavior_pattern: (?:同时|分别|以及|并且|而且|又.{0,12}又|既.{0,12}又)
rules:
- rule_id: behavior_class1
  activity: ZEB_INFO_TOOL
  activity_template: 在资讯《$articleName$》中，查看了工具“$tool$”
  priority: 100
  patterns:
  - 在资讯中(?:查看|看过|浏览)(?:了)?工具
  - 在资讯.{0,16}中(?:查看|看过|浏览)(?:了)?工具
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在资讯中(?:查看|看过|浏览)(?:了)?工具)
  is_supported: true
- rule_id: behavior_class2
  activity: ZEB_TOPIC_SHARE
  activity_template: 转发分享了资讯专题《$topicName$》
  priority: 80
  patterns:
  - (?:转发|分享)了?(?:资讯专题|专题)
  negative_patterns:
  - (?:没有|没|未|不曾|从未).{0,4}(?:转发|分享)
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:转发|分享)了?(?:资讯专题|专题))
  is_supported: true
- rule_id: behavior_class3
  activity: ZEB_ZY_READ
  activity_template: 查看增员素材《$articleName$》
  priority: 100
  patterns:
  - (?:查看|看过|浏览)增员素材
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:查看|看过|浏览)增员素材)
  is_supported: true
- rule_id: behavior_click_insure
  activity: JGJ_Product_Insure
  activity_template: 在金管家查看《$productName$》时点击了“我要投保”
  priority: 120
  patterns:
  - (?:点击|点过|按过).{0,4}(?:我要投保|立即投保)
  - (?:在金管家)?(?:查看|看过|浏览)(?:了)?[《“"]?{BEHAVIOR_PRODUCT_SLOT}[》”"]?(?:时|的时候)?(?:点击|点了?|点过|按过){BEHAVIOR_SHORT_GAP}(?:我要投保|立即投保)["“”]?
  - (?:看|查看|浏览)(?:了)?{BEHAVIOR_PRODUCT_SLOT}(?:时|的时候)?(?:点击|点了?|点过|按过){BEHAVIOR_SHORT_GAP}(?:我要投保|立即投保)
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:发起|开始|有明确)(?:了)?投保(?:动作)?(?:吗|呢)?
  - 在金管家{BEHAVIOR_CLAUSE_GAP}(?:发起|开始|有明确)(?:了)?投保(?:动作)?
  negative_patterns:
  - (?:没有|没|未|不曾|从未).{0,5}(?:点击|点过|按过).{0,4}(?:我要投保|立即投保)
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:点击|点过|按过).{0,4}(?:我要投保|立即投保))
  is_supported: true
- rule_id: behavior_class5
  activity_template: 点赞了智能拜访助手中的跟拍视频$videoName$
  priority: 100
  patterns:
  - 点赞了智能拜访助手中的跟拍视频
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:点赞了智能拜访助手中的跟拍视频)
  is_supported: true
  activities:
  - SMARTVISIT_AIVIDEO_THUMBSUP
  - SMARTVISIT_AIVIDEO_THUMBSUP_ZY
- rule_id: behavior_class6
  activity: onePA_ReadOrder
  activity_template: 浏览了ONE平安页面，并提交了展厅预约申请
  priority: 100
  patterns:
  - (?:浏览|查看|看过)(?:了)?ONE平安页面并(?:提交|递交)(?:了)?展厅预约申请
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:浏览|查看|看过)(?:了)?ONE平安页面并(?:提交|递交)(?:了)?展厅预约申请)
  is_supported: true
- rule_id: behavior_purchase_success
  activity: ZEB_PRODUCT_BUY
  activity_template: 购买产品“$productName$”时，购买成功
  priority: 115
  patterns:
  - (?:产品|商品)?.{0,5}(?:购买成功|成功购买)
  - (?:购买|买)(?:了)?{BEHAVIOR_PRODUCT_SLOT}(?:并且|且|后|时)?(?:购买成功|成功购买|买成了?)
  - (?:谁(?:已经)?|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:买成了?|购买成功|成功购买)(?:{BEHAVIOR_PRODUCT_SLOT})?
  - (?:产品|商品)?.{0,12}购买结果.{0,3}(?:为|是)?成功
  - (?:成功购买|购买成功){BEHAVIOR_CLAUSE_GAP}(?:产品|商品|险)
  negative_patterns:
  - (?:没有|没|未|不曾|从未).{0,5}(?:购买成功|成功购买)
  - 购买失败
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:产品|商品)?.{0,5}(?:购买成功|成功购买))
  is_supported: true
- rule_id: behavior_class8
  activity: ZEB_TOOL_READEND
  activity_template: 查看了展业工具“$toolName$”，时长$time$秒
  priority: 100
  patterns:
  - (?:查看|看过|浏览)(?:了)?展业工具时长秒
  - (?:查看|看过|浏览)(?:了)?展业工具.{0,16}时长.{0,16}秒
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:查看|看过|浏览)(?:了)?展业工具时长秒)
  is_supported: true
- rule_id: behavior_class9
  activity: ZEB_BUSINESS_CARD_ELITE_READEND
  activity_template: 查看了个人名片(精英版)，时长$time$秒
  priority: 100
  patterns:
  - (?:查看|看过|浏览)(?:了)?个人名片精英版时长秒
  - (?:查看|看过|浏览)(?:了)?个人名片精英版时长.{0,16}秒
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:查看|看过|浏览)(?:了)?个人名片精英版时长秒)
  is_supported: true
- rule_id: behavior_class10
  activity: ZEB_TOOL_SHARE
  activity_template: 转发分享了展业工具“$toolName$”
  priority: 100
  patterns:
  - (?:转发|分享)(?:了)?展业工具
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:转发|分享)(?:了)?展业工具)
  is_supported: true
- rule_id: behavior_class11
  activity: KDE_ACTIVITY_VISIT_ASSISTANT
  activity_template: 在拜访助手预约咨询$articleName$
  priority: 100
  patterns:
  - 在拜访助手预约咨询
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在拜访助手预约咨询)
  is_supported: true
- rule_id: behavior_class12
  activity: JGJ_POLICY_SERVICE_01
  activity_template: '在金管家使用了$serviceName$服务，保险产品为$productName$，保单号（投保单号）: $policyNo$'
  priority: 100
  patterns:
  - 在金管家(?:使用|用过)(?:了)?服务保险产品为保单号投保单号
  - 在金管家(?:使用|用过)(?:了)?.{0,16}服务保险产品为.{0,16}保单号投保单号
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家(?:使用|用过)(?:了)?服务保险产品为保单号投保单号)
  is_supported: true
- rule_id: behavior_class13
  activity: JGJ_MEETINGE_BAO_SIGNIN_ON_SITE
  activity_template: 线下活动扫码签到成功，正在参加活动“$activityName$”
  priority: 100
  patterns:
  - 线下活动扫码签到成功正在参加活动
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:线下活动扫码签到成功正在参加活动)
  is_supported: true
- rule_id: behavior_class14
  activity: KDE_BDTG_RAU
  activity_template: 客户与您解除了保单管家服务关系，原因如下：$replaceReason$
  priority: 100
  patterns:
  - 客户与您解除了保单管家服务关系原因如下
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:客户与您解除了保单管家服务关系原因如下)
  is_supported: true
- rule_id: behavior_class15
  activity: ZEB_BUSINESS_CARD_READEND
  activity_template: 查看了个人名片(标准版)，时长$time$秒
  priority: 100
  patterns:
  - (?:查看|看过|浏览)(?:了)?个人名片标准版时长秒
  - (?:查看|看过|浏览)(?:了)?个人名片标准版时长.{0,16}秒
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:查看|看过|浏览)(?:了)?个人名片标准版时长秒)
  is_supported: true
- rule_id: behavior_class16
  activity: ZEB_INFO_ORDER
  activity_template: 在口袋E资讯《$articleName$》中，预约产品咨询$productName$
  priority: 100
  patterns:
  - 在口袋E资讯中预约产品咨询
  - 在口袋E资讯.{0,16}中预约产品咨询
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在口袋E资讯中预约产品咨询)
  is_supported: true
- rule_id: behavior_class17
  activity_template: 转发分享了产品“$productName$”
  priority: 100
  patterns:
  - (?:转发|分享)(?:了)?产品
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:转发|分享)(?:了)?产品)
  is_supported: true
  activities:
  - ZEB_PRODUCT_SHARE
  - SYZQ_ZEB_PRODUCT_SHARE
- rule_id: behavior_class18
  activity: ZEB_AGENTSTORE_SERVICE
  activity_template: 在保险小店中，预约了服务“$serviceName$”
  priority: 100
  patterns:
  - 在保险小店中[\s，,]*(?:预约|预订)(?:了|过)?服务
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在保险小店中(?:预约|预订)(?:了)?服务)
  is_supported: true
- rule_id: behavior_class19
  activity: JGJ_PKT_ACTIVITY_01
  activity_template: 参加了金管家拼团活动“$activityName$”，并成功开团
  priority: 100
  patterns:
  - (?:参加|参与)(?:了)?金管家拼团活动并成功开团
  - (?:参加|参与)(?:了)?金管家拼团活动.{0,16}并成功开团
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:在金管家{BEHAVIOR_CLAUSE_GAP})?(?:发起|创建|组织)(?:了)?拼团(?:吗|呢)?
  - (?:活动(?:里|中){BEHAVIOR_CLAUSE_GAP})?(?:做|当)(?:了)?团长
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:参加|参与)(?:了)?金管家拼团活动并成功开团)
  is_supported: true
- rule_id: behavior_class20
  activity: ZEB_CARD_READEND
  activity_template: 查看贺卡“$cardName$”，时长$time$秒
  priority: 100
  patterns:
  - (?:查看|看过|浏览)贺卡时长秒
  - (?:查看|看过|浏览)贺卡.{0,16}时长.{0,16}秒
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:查看|看过|浏览)贺卡时长秒)
  is_supported: true
- rule_id: behavior_class21
  activity: KDE_USER_AGENT_RISK_ASSESSMENT_HOME_PENSION
  activity_template: 参观$branch$居家养老展厅，展厅地址：$showroomAddress$
  priority: 100
  patterns:
  - 参观居家养老展厅展厅地址
  - 参观.{0,16}居家养老展厅展厅地址
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:参观居家养老展厅展厅地址)
  is_supported: true
- rule_id: behavior_class22
  activity: scanCode_activity_01
  activity_template: 在面访扫码结束后参加“码上有礼”活动，领取了权益“$rightsName$”
  priority: 100
  patterns:
  - 在面访扫码结束后参加码上有礼活动(?:领取|领过)(?:了)?权益
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在面访扫码结束后参加码上有礼活动(?:领取|领过)(?:了)?权益)
  is_supported: true
- rule_id: behavior_class23
  activity: JGJ_PKT_ACTIVITY_03
  activity_template: 参加了金管家砍团活动“$activityName$”，并成功开团
  priority: 100
  patterns:
  - (?:参加|参与)(?:了)?金管家砍团活动并成功开团
  - (?:参加|参与)(?:了)?金管家砍团活动.{0,16}并成功开团
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:参加|参与)(?:了)?金管家砍团活动并成功开团)
  is_supported: true
- rule_id: behavior_class24
  activity: ZEB_INFO_TITLE_VOTE
  activity_template: 在资讯《$articleName$》中，参与投票“$voteName$”
  priority: 100
  patterns:
  - 在资讯中(?:参与|参加)投票
  - 在资讯.{0,16}中(?:参与|参加)投票
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在资讯中(?:参与|参加)投票)
  is_supported: true
- rule_id: behavior_class25
  activity: ZEB_TOPIC_READEND
  activity_template: 查看了资讯专题《$topicName$》，时长$time$秒
  priority: 100
  patterns:
  - (?:查看|看过|浏览)(?:了)?资讯专题时长秒
  - (?:查看|看过|浏览)(?:了)?资讯专题.{0,16}时长.{0,16}秒
  - (?:查看|看过|浏览)(?:了)?[《“"]?{BEHAVIOR_PRODUCT_SLOT}专题[》”"]?
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:查看|看过|浏览)(?:了)?[《“"]?{BEHAVIOR_PRODUCT_SLOT}专题[》”"]?(?:吗|呢)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:查看|看过|浏览)(?:了)?资讯专题时长秒)
  is_supported: true
- rule_id: behavior_class26
  activity: ZEB_ZT_PRODUCT_READ
  activity_template: 浏览车险报价单“$productName$”
  priority: 100
  patterns:
  - (?:浏览|查看|看过)车险报价单
  - (?:浏览|查看|看过)(?:了|过)?.{0,30}车险报价(?:单)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:浏览|查看|看过)车险报价单)
  is_supported: true
- rule_id: behavior_class27
  activity: JGJ_PKT_ACTIVITY_02
  activity_template: 参加了金管家拼团活动“$activityName$”，并成功参团
  priority: 100
  patterns:
  - (?:参加|参与)(?:了)?金管家拼团活动并成功参团
  - (?:参加|参与)(?:了)?金管家拼团活动.{0,16}并成功参团
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:参加|参与)(?:了)?金管家拼团活动并成功参团)
  is_supported: true
- rule_id: behavior_payment_click
  activity: ZEB_PRODUCT_PAY
  activity_template: 购买产品“$productName$”时，点击支付
  priority: 120
  patterns:
  - (?:点击|点过|按过).{0,4}(?:支付|付款)
  - (?:进入|发起).{0,3}(?:支付|付款)(?:环节|流程)?
  - (?:购买|买)(?:了)?{BEHAVIOR_PRODUCT_SLOT}(?:时|的时候|过程中|后)?(?:点击|点过|按过|进入|发起){BEHAVIOR_SHORT_GAP}(?:支付|付款)(?:环节|流程)?
  - (?:产品)?购买流程中{BEHAVIOR_CLAUSE_GAP}(?:点击|点过|按过|进入|发起){BEHAVIOR_SHORT_GAP}(?:支付|付款)
  - 谁{BEHAVIOR_CLAUSE_GAP}(?:走到|到了){BEHAVIOR_SHORT_GAP}(?:支付|付款)(?:这一步|环节|流程)
  - (?:有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:点击|点过|按过){BEHAVIOR_SHORT_GAP}(?:支付|付款){BEHAVIOR_CLAUSE_GAP}(?:还没|未)(?:确认)?成功
  negative_patterns:
  - (?:没有|没|未|不曾|从未).{0,5}(?:点击|点过|进入|发起).{0,4}(?:支付|付款)
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:点击|点过|按过).{0,4}(?:支付|付款))
  is_supported: true
- rule_id: behavior_class29
  activity: ZEB_INFO_READEND
  activity_template: 阅读了资讯《$articleName$》，阅读时长$time$秒
  priority: 100
  patterns:
  - (?:阅读|读过|看过)(?:了)?资讯阅读时长秒
  - (?:阅读|读过|看过)(?:了)?资讯.{0,16}阅读时长.{0,16}秒
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:阅读|读过|看过)(?:了)?资讯阅读时长秒)
  is_supported: true
- rule_id: behavior_class30
  activity: ZEB_ZY_SHARE
  activity_template: 转发分享增员素材《$articleName$》
  priority: 100
  patterns:
  - 转发分享增员素材
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:转发分享增员素材)
  is_supported: true
- rule_id: behavior_fill_customer_info
  activity: P_C14
  activity_template: 购买$productName$已完成客户信息填写
  priority: 120
  patterns:
  - (?:完成|填写了?).{0,4}客户信息(?:填写)?
  - 卡在客户信息(?:填写|提交)(?:完成)?之后的购买
  negative_patterns:
  - (?:没有|没|未|不曾|从未).{0,5}(?:完成|填写).{0,4}客户信息
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:完成|填写了?).{0,4}客户信息(?:填写)?)
  is_supported: true
- rule_id: behavior_class32
  activity: JGJ_MEETINGE_BAO_SIGNUP_ONLINE
  activity_template: 邀请函报名成功，有意参加线下活动“$activityName$”
  priority: 100
  patterns:
  - 邀请报名成功有意参加线下活动
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:邀请报名成功有意参加线下活动)
  is_supported: true
- rule_id: behavior_class33
  activity: scanCode_01
  activity_template: 完成了对TA的面访，面访内容：$activityName$
  priority: 100
  patterns:
  - (?:完成|做完)(?:了)?对TA的面访面访内容
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:已经|已)?(?:完成|做完)(?:了)?(?:面对面|线下)?拜访(?:吗|呢)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:完成|做完)(?:了)?对TA的面访面访内容)
  is_supported: true
- rule_id: behavior_class34
  activity: BZH_LIFE_PSSP_CUSTOMER_NEWS_NO2
  activity_template: $type$回访问卷中将您推荐给朋友的意愿较高为$number$分，看来Ta喜欢您提供的服务喔~
  priority: 100
  patterns:
  - 回访问卷中将您推荐给朋友的意愿较高为分看来Ta喜欢您提供的服务喔
  - 回访问卷中将您推荐给朋友的意愿较高为.{0,16}分看来Ta喜欢您提供的服务喔
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:回访问卷中将您推荐给朋友的意愿较高为分看来Ta喜欢您提供的服务喔)
  is_supported: true
- rule_id: behavior_class35
  activity: JGJ_READ_ENJOY_N01
  activity_template: 阅读了$typeName$的文章《$articleName$》，时长$time$秒
  priority: 100
  patterns:
  - (?:阅读|读过|看过)(?:了)?的文章时长秒
  - (?:阅读|读过|看过)(?:了)?.{0,16}的文章.{0,16}时长.{0,16}秒
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:阅读|读过|看过)(?:了)?的文章时长秒)
  is_supported: true
- rule_id: behavior_class36
  activity: JGJ_WANGCAI_ACCOUNT
  activity_template: 开通了旺财账户
  priority: 100
  patterns:
  - (?:开通|开启)(?:了)?旺财账户
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:开通|开启)(?:了)?旺财账户)
  is_supported: true
- rule_id: behavior_class37
  activity: JGJ_OPERATE_WON_PRIZE
  activity_template: 在金管家活动“$activityName$”中，获得奖品$prizeName$
  priority: 100
  patterns:
  - 在金管家活动中获得奖品
  - 在金管家活动.{0,16}中获得奖品
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:从|在)?活动(?:中|里){BEHAVIOR_CLAUSE_GAP}(?:拿到|获得|赢得|中了)(?:了)?{BEHAVIOR_CLAUSE_GAP}(?:奖品|奖)(?:吗|呢)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家活动中获得奖品)
  is_supported: true
- rule_id: behavior_like_article
  activity_template: 点赞了资讯《$articleName$》
  priority: 90
  patterns:
  - 点赞了?(?:资讯|文章)
  negative_patterns:
  - (?:没有|没|未|取消).{0,3}点赞
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:点赞了?(?:资讯|文章))
  is_supported: true
  activities:
  - ZEB_INFO_THUMBSUP
  - SYZQ_ZEB_INFO_THUMBSUP
- rule_id: behavior_class39
  activity: ZEB_ZT_PRODUCT_READEND
  activity_template: 浏览了车险报价单“$productName$”，时长$time$秒
  priority: 100
  patterns:
  - (?:浏览|查看|看过)(?:了)?车险报价单时长秒
  - (?:浏览|查看|看过)(?:了)?车险报价单.{0,16}时长.{0,16}秒
  - (?:浏览|查看|看过)(?:了|过)?.{0,30}车险报价(?:单)?.{0,12}\d+(?:\.\d+)?(?:秒|分钟|小时)
  - (?:仔细|认真)(?:浏览|查看|看过)(?:了|过)?.{0,30}车险报价(?:单)?
  - (?:有)?车险报价(?:单)?浏览时长(?:记录)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:浏览|查看|看过)(?:了)?车险报价单时长秒)
  is_supported: true
- rule_id: behavior_class40
  activity: ZEB_ZY_READEND
  activity_template: 查看了增员素材《$articleName$》，时长$time$秒
  priority: 100
  patterns:
  - (?:查看|看过|浏览)(?:了)?增员素材时长秒
  - (?:查看|看过|浏览)(?:了)?增员素材.{0,16}时长.{0,16}秒
  - (?:有)?增员素材浏览时长(?:记录)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:查看|看过|浏览)(?:了)?增员素材时长秒)
  is_supported: true
- rule_id: behavior_class41
  activity: smartVisit_evaluate
  activity_template: 在智能拜访助手-在线会客中，进行了会客评价
  priority: 100
  patterns:
  - 在智能拜访助手\-在线会客中进行了会客评价
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在智能拜访助手\-在线会客中进行了会客评价)
  is_supported: true
- rule_id: behavior_class42
  activity: homeBasedCare_read
  activity_template: 用户在金管家居家养老专区内浏览了《$content$》
  priority: 100
  patterns:
  - 用户在金管家居家养老专区内(?:浏览|查看|看过)(?:了)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:用户在金管家居家养老专区内(?:浏览|查看|看过)(?:了)?)
  is_supported: true
- rule_id: behavior_payment_success
  activity: ZEB_PRODUCT_PAY_FINISH
  activity_template: 购买产品“$productName$”时，完成支付
  priority: 130
  patterns:
  - (?:完成|成功).{0,3}(?:支付|付款)
  - (?:支付|付款).{0,3}(?:完成|成功)
  - (?:购买|买)(?:了)?{BEHAVIOR_PRODUCT_SLOT}(?:并且|且|后|时|的时候)?(?:完成|成功){BEHAVIOR_SHORT_GAP}(?:支付|付款)
  - (?:谁(?:的)?|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:产品)?订单{BEHAVIOR_CLAUSE_GAP}(?:已经|已)?(?:付完款|付款成功|支付成功|完成支付|已付款)
  - (?:已经|已)?(?:付完款|付款成功|支付成功|完成支付|已付款){BEHAVIOR_CLAUSE_GAP}(?:产品)?(?:订单|购买)?
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:成功)?完成(?:了)?(?:支付|付款)
  negative_patterns:
  - (?:没有|没|未|不曾|从未|尚未).{0,5}(?:完成|成功)?.{0,3}(?:支付|付款)
  - (?:支付|付款).{0,3}(?:失败|未成功)
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:完成|成功).{0,3}(?:支付|付款))
  is_supported: true
- rule_id: behavior_class44
  activity_template: 浏览了展业短视频“$videoName$”，时长$time$秒
  priority: 100
  patterns:
  - (?:浏览|查看|看过)(?:了)?展业短视频时长秒
  - (?:浏览|查看|看过)(?:了)?展业短视频.{0,16}时长.{0,16}秒
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:浏览|查看|看过)(?:了)?展业短视频时长秒)
  is_supported: true
  activities:
  - ZEB_VIDEO_READEND
  - SYZQ_ZEB_VIDEO_READEND
- rule_id: behavior_class45
  activity_template: 浏览了产品“$productName$”，浏览时长$time$秒
  priority: 100
  patterns:
  - (?:浏览|查看|看过)(?:了)?产品(?:浏览|查看|看过)时长秒
  - (?:浏览|查看|看过)(?:了)?产品.{0,16}(?:浏览|查看|看过)时长.{0,16}秒
  - (?:浏览|查看|看过)(?:了|过)?(?![^，,。！？!?；;\n]{0,40}(?:车险报价(?:单)?|转保产品))[\u4e00-\u9fa5A-Za-z0-9·]{1,30}(?:险|保险)(?:产品)?(?:的客户|客户|的人)?
  - (?:浏览|查看|看过)(?:了|过)?(?![^，,。！？!?；;\n]{0,40}(?:车险报价(?:单)?|转保产品)).{0,24}(?:产品页|产品详情)
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:浏览|查看|看过)(?:了)?产品(?:浏览|查看|看过)时长秒)
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:浏览|查看|看过)(?:了|过)?(?![^，,。！？!?；;\n]{0,40}(?:车险报价(?:单)?|转保产品))[\u4e00-\u9fa5A-Za-z0-9·]{1,30}(?:险|保险))
  is_supported: true
  activities:
  - ZEB_PRODUCT_READEND
  - SYZQ_ZEB_PRODUCT_READEND
- rule_id: behavior_class46
  activity: ZEB_PRODUCT_ORDER
  activity_template: 在口袋E产品贴“$productName$”中，预约产品咨询
  priority: 100
  patterns:
  - 在口袋E产品贴中[\s，,]*(?:预约|预订)(?:了|过)?产品咨询
  - 在口袋E产品贴.{0,24}中[\s，,]*(?:预约|预订)(?:了|过)?产品咨询
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在口袋E产品贴中预约产品咨询)
  is_supported: true
- rule_id: behavior_class47
  activity: ZEB_INFO_TITLE_PK
  activity_template: 在资讯《$articleName$》中，参与话题PK“$Pkname$”
  priority: 100
  patterns:
  - 在资讯中(?:参与|参加)话题PK
  - 在资讯.{0,16}中(?:参与|参加)话题PK
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在资讯中(?:参与|参加)话题PK)
  is_supported: true
- rule_id: behavior_class48
  activity: JGJ_OPERATE_SIGN_UP
  activity_template: 报名参加了金管家活动“$activityName$”
  priority: 100
  patterns:
  - 报名(?:参加|参与)(?:了)?金管家活动
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:报名(?:参加|参与)(?:了)?金管家活动)
  is_supported: true
- rule_id: behavior_class49
  activity: JGJ_PKT_ACTIVITY_04
  activity_template: 参加了金管家砍团活动“$activityName$”，并成功帮砍
  priority: 100
  patterns:
  - (?:参加|参与)(?:了)?金管家砍团活动并成功帮砍
  - (?:参加|参与)(?:了)?金管家砍团活动.{0,16}并成功帮砍
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:参加|参与)(?:了)?金管家砍团活动并成功帮砍)
  is_supported: true
- rule_id: behavior_class50
  activity: JGJ_MEETINGE_BAO_PRODUCT_PURCHASE
  activity_template: 在参加线下活动“$activityName$”时，预购了产品$productName$，金额$productPrize$元
  priority: 100
  patterns:
  - 在参加线下活动时预购了产品金额元
  - 在参加线下活动.{0,16}时预购了产品.{0,16}金额.{0,16}元
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在参加线下活动时预购了产品金额元)
  is_supported: true
- rule_id: behavior_policy_custody
  activity: KDE_BDTG_DTG
  activity_template: 完成了保单托管授权
  priority: 100
  patterns:
  - 完成了?保单托管授权
  negative_patterns:
  - (?:没有|没|未).{0,4}完成保单托管授权
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:完成了?保单托管授权)
  is_supported: true
- rule_id: behavior_class52
  activity: LAIP_IVAP_VIDEO_N03
  activity_template: 浏览了跟拍视频$videoTitle$
  priority: 100
  patterns:
  - (?:浏览|查看|看过)(?:了)?跟拍视频
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:浏览|查看|看过|打开|点开)(?:了|过)?跟拍视频(?:吗|呢)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:浏览|查看|看过)(?:了)?跟拍视频)
  is_supported: true
- rule_id: behavior_submit_order
  activity: ZEB_PRODUCT_SUBMIT
  activity_template: 购买产品“$productName$”时，提交订单信息
  priority: 120
  patterns:
  - 提交了?(?:订单|订单信息)
  - (?:购买|买)(?:了)?{BEHAVIOR_PRODUCT_SLOT}(?:时|的时候|过程中|后)?(?:已经|已)?提交了?(?:订单|订单信息)
  - (?:谁(?:的)?|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:产品)?订单{BEHAVIOR_CLAUSE_GAP}(?:已经|已)?提交
  - (?:产品)?购买流程{BEHAVIOR_CLAUSE_GAP}(?:走到|到了){BEHAVIOR_SHORT_GAP}提交订单
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:填完|填写完|提交了?)(?:订单|订单信息){BEHAVIOR_CLAUSE_GAP}(?:还没|未)(?:支付|付款)(?:吗|呢)?
  negative_patterns:
  - (?:没有|没|未|不曾|从未).{0,4}提交(?:订单|订单信息)
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:提交了?(?:订单|订单信息))
  is_supported: true
- rule_id: behavior_complete_purchase
  activity: JGJ_Product_Succeed
  activity_template: 完成购买《$productName$》
  priority: 110
  patterns:
  - (?:完成购买|买完了?)
  negative_patterns:
  - (?:没有|没|未|不曾|从未).{0,5}(?:完成购买|买完)
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:完成购买|买完了?))
  is_supported: true
- rule_id: behavior_payment_failed
  activity: ZEB_PRODUCT_PAY_FAIL
  activity_template: 购买产品“$productName$”时，支付失败
  priority: 140
  patterns:
  - (?:支付|付款).{0,3}(?:失败|没成功|未成功|不成功|异常)
  - (?:购买|买)(?:了)?{BEHAVIOR_PRODUCT_SLOT}(?:时|的时候|过程中|后)?(?:支付|付款).{0,3}(?:失败|没成功|未成功|不成功|异常)
  - (?:谁(?:的)?|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:支付|付款).{0,3}(?:失败|没成功|未成功|不成功|异常)(?:需要跟进)?
  - (?:有没有){BEHAVIOR_CLAUSE_GAP}(?:支付|付款).{0,3}(?:失败|没成功|未成功|不成功|异常)(?:需要跟进)?
  - '{BEHAVIOR_PRODUCT_SLOT}(?:支付|付款)(?:失败|没成功|未成功|不成功|异常)(?:需要跟进)?'
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:支付|付款).{0,3}(?:失败|未成功))
  is_supported: true
- rule_id: behavior_class56
  activity: ZEB_INFO_PRODUCT
  activity_template: 在资讯《$articleName$》中，查看了产品“$productName$”
  priority: 100
  patterns:
  - 在资讯中(?:查看|看过|浏览)(?:了)?产品
  - 在资讯.{0,16}中(?:查看|看过|浏览)(?:了)?产品
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在资讯中(?:查看|看过|浏览)(?:了)?产品)
  is_supported: true
- rule_id: behavior_class57
  activity: smartVisit_ftf_evaluate
  activity_template: 在智能拜访助手-面对面拜访中，进行了评价
  priority: 100
  patterns:
  - 在智能拜访助手\-面对面拜访进行了评价
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在智能拜访助手\-面对面拜访进行了评价)
  is_supported: true
- rule_id: behavior_underwriting_success
  activity: ZEB_PRODUCT_UNDERWRITE
  activity_template: 购买产品“$productName$”时，核保成功
  priority: 130
  patterns:
  - 核保(?:成功|通过)
  - 通过了?核保
  - (?:购买|买)(?:了)?{BEHAVIOR_PRODUCT_SLOT}(?:时|的时候|过程中|后)?核保(?:成功|通过)
  - (?:谁(?:的)?|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:产品)?{BEHAVIOR_CLAUSE_GAP}核保(?:成功|通过)(?:了)?
  - (?:产品)?{BEHAVIOR_CLAUSE_GAP}核保(?:成功|通过){BEHAVIOR_CLAUSE_GAP}(?:可以|可){BEHAVIOR_SHORT_GAP}继续办理
  - '(?!.*(?:车辆|车险|汽车)){BEHAVIOR_PRODUCT_SLOT}核保(?:成功|通过)(?:了)?'
  negative_patterns:
  - 核保(?:失败|未通过)
  - (?:没有|没|未).{0,3}通过核保
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:核保(?:成功|通过))
  is_supported: true
- rule_id: behavior_class59
  activity: ZEB_INFO_SHARE
  activity_template: 转发分享了资讯《$articleName$》
  priority: 80
  patterns:
  - (?:转发|分享)了?(?:资讯|专题)
  negative_patterns:
  - (?:没有|没|未|不曾|从未).{0,4}(?:转发|分享)
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:转发|分享)了?(?:资讯|专题))
  is_supported: true
- rule_id: behavior_class60
  activity_template: 转发分享了展业短视频“$videoName$”
  priority: 100
  patterns:
  - (?:转发|分享)(?:了)?展业短视频
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:转发|分享)(?:了)?展业短视频)
  is_supported: true
  activities:
  - ZEB_VIDEO_SHARE
  - SYZQ_ZEB_VIDEO_SHARE
- rule_id: behavior_class61
  activity: JGJ_CHRONIC_DISEASE_03
  activity_template: 赠送了亲友慢病服务包
  priority: 100
  patterns:
  - 赠送了亲友慢病服务包
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:赠送了亲友慢病服务包)
  is_supported: true
- rule_id: behavior_class62
  activity: JGJ_MEETINGE_BAO_TRAIN_SIGNUP
  activity_template: 在参加线下活动“$activityName$”时，报名了岗职培训班
  priority: 100
  patterns:
  - 在参加线下活动时(?:报名|参加报名)(?:了)?岗职培训班
  - 在参加线下活动.{0,16}时(?:报名|参加报名)(?:了)?岗职培训班
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在参加线下活动时(?:报名|参加报名)(?:了)?岗职培训班)
  is_supported: true
- rule_id: behavior_class63
  activity: BZH_LIFE_PSSP_CUSTOMER_NEWS_NO1
  activity_template: $type$回访问卷中对您的服务满意度为$content$，看来Ta喜欢您提供的服务喔~
  priority: 100
  patterns:
  - 回访问卷中对您的服务满意度为看来Ta喜欢您提供的服务喔
  - 回访问卷中对您的服务满意度为.{0,16}看来Ta喜欢您提供的服务喔
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:回访问卷中对您的服务满意度为看来Ta喜欢您提供的服务喔)
  is_supported: true
- rule_id: behavior_class64
  activity: ZSB_PROPOSAL_WECHATSHARE_01
  activity_template: 在微信中打开了$productName$建议书
  priority: 100
  patterns:
  - 在微信中打开了建议书
  - 在微信中打开了.{0,16}建议书
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在微信中打开了建议书)
  is_supported: true
- rule_id: behavior_class65
  activity: KDE_BDTG_DFH
  activity_template: 已完成1份保单照片上传
  priority: 100
  patterns:
  - 已完成1份保单照片上传
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:已完成1份保单照片上传)
  is_supported: true
- rule_id: behavior_class66
  activity_template: 预约了跟拍视频$videoTitle$
  priority: 100
  patterns:
  - (?:预约|预订)(?:了)?跟拍视频
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:预约|预订)(?:了)?跟拍视频)
  is_supported: true
  activities:
  - LAIP_IVAP_VIDEO_N02
  - LAIP_IVAP_VIDEO_N04
- rule_id: behavior_underwriting_failed
  activity: ZEB_PRODUCT_UNDERWRITE_FAIL
  activity_template: 购买产品“$productName$”时，核保失败
  priority: 140
  patterns:
  - 核保(?:失败|未通过)
  - 未通过核保
  - (?:购买|买)(?:了)?{BEHAVIOR_PRODUCT_SLOT}(?:时|的时候|过程中|后)?核保(?:失败|没通过|未通过|不成功)
  - (?:谁(?:的)?|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:产品)?{BEHAVIOR_CLAUSE_GAP}核保(?:失败|没通过|未通过|不成功)(?:需要跟进)?
  - '(?!.*(?:车辆|车险|汽车)){BEHAVIOR_PRODUCT_SLOT}核保(?:失败|没通过|未通过|不成功)(?:需要跟进)?'
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:核保(?:失败|未通过))
  is_supported: true
- rule_id: behavior_class68
  activity: futureCity_read
  activity_template: 参观了平安未来城线上展厅，本次参观时长$opaDuration$，参观的场馆有$opaRooms$
  priority: 100
  patterns:
  - 参观了平安未来城线上展厅本次参观时长参观的场馆有
  - 参观了平安未来城线上展厅本次参观时长.{0,16}参观的场馆有
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:参观了平安未来城线上展厅本次参观时长参观的场馆有)
  is_supported: true
- rule_id: behavior_class69
  activity: careExhibition_signup
  activity_template: 报名了$time$的$showroomName$参观
  priority: 100
  patterns:
  - (?:报名|参加报名)(?:了)?的参观
  - (?:报名|参加报名)(?:了)?.{0,16}的.{0,16}参观
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:报名|参加报名)(?:了)?的参观)
  is_supported: true
- rule_id: behavior_class70
  activity: ZEB_TOOL_READ_SERVICE_ORDER
  activity_template: 在工具《$articleName$》中，留资预约了服务讲解
  priority: 100
  patterns:
  - 在工具中[\s，,]*留资(?:预约|预订)(?:了|过)?服务讲解
  - 在工具.{0,24}中[\s，,]*留资(?:预约|预订)(?:了|过)?服务讲解
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在工具中留资(?:预约|预订)(?:了)?服务讲解)
  is_supported: true
- rule_id: behavior_class71
  activity: taxCalculator_use
  activity_template: 使用节税计算器，并进行了测算
  priority: 100
  patterns:
  - 使用节税计算器并进行了测算
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:使用节税计算器并进行了测算)
  is_supported: true
- rule_id: behavior_class72
  activity: taxSubject_order
  activity_template: 浏览《$articleName$》内容，并预约税优服务
  priority: 100
  patterns:
  - (?:浏览|查看|看过)内容并预约税优服务
  - (?:浏览|查看|看过).{0,16}内容并预约税优服务
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:浏览|查看|看过)内容并预约税优服务)
  is_supported: true
- rule_id: behavior_class73
  activity: SYZQ_ZEB_INFO_READEND
  activity_template: 阅读了资讯《$articleName$》，时长$time$秒
  priority: 100
  patterns:
  - (?:阅读|读过|看过)(?:了)?资讯时长秒
  - (?:阅读|读过|看过)(?:了)?资讯.{0,16}时长.{0,16}秒
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:阅读|读过|看过)(?:了)?资讯时长秒)
  is_supported: true
- rule_id: behavior_class74
  activity: SYZQ_ZEB_INFO_ORDER
  activity_template: 在口袋E资讯《$articleName$》中，预约了税优服务
  priority: 100
  patterns:
  - 在口袋E资讯中(?:预约|预订)(?:了)?税优服务
  - 在口袋E资讯.{0,16}中(?:预约|预订)(?:了)?税优服务
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在口袋E资讯中(?:预约|预订)(?:了)?税优服务)
  is_supported: true
- rule_id: behavior_class75
  activity: SYZQ_ZEB_INFO_PRODUCT
  activity_template: 在资讯《$articleName$》中，查看了产品“$productName$”
  priority: 100
  patterns:
  - 在资讯中(?:查看|看过|浏览)(?:了)?产品
  - 在资讯.{0,16}中(?:查看|看过|浏览)(?:了)?产品
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在资讯中(?:查看|看过|浏览)(?:了)?产品)
  is_supported: true
- rule_id: behavior_class76
  activity: onlineActivity_ZXJYKMH
  activity_template: 参与”$activityName$“活动，并查看臻享家医开门红限时方案
  priority: 100
  patterns:
  - (?:参与|参加)活动并(?:查看|看过|浏览)臻享医开门红限时方案
  - (?:参与|参加).{0,16}活动并(?:查看|看过|浏览)臻享医开门红限时方案
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:参与|参加)活动并(?:查看|看过|浏览)臻享医开门红限时方案)
  is_supported: true
- rule_id: behavior_class77
  activity: contactInfo_click
  activity_template: '"$leadChannel$"渠道金管家$customerType$客户已绑定您，并领取了留资福利'
  priority: 100
  patterns:
  - 渠道金管家客户已绑定您并(?:领取|领过)(?:了)?留资福利
  - 渠道金管家.{0,16}客户已绑定您并(?:领取|领过)(?:了)?留资福利
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:渠道金管家客户已绑定您并(?:领取|领过)(?:了)?留资福利)
  is_supported: true
- rule_id: behavior_class78
  activity: jgj_eduClub_join
  activity_template: 已加入教育俱乐部会员，对教育有较高兴趣
  priority: 100
  patterns:
  - 已加入教育俱乐部会员对教育有较高兴趣
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:已加入教育俱乐部会员对教育有较高兴趣)
  is_supported: true
- rule_id: behavior_class79
  activity: BDGJ_WXMINIAPP_BDGJ_APPLY
  activity_template: 通过平安保单管家小程序开通保单管家服务
  priority: 95
  patterns:
  - (?:通过|从|在)?(?:平安)?保单管家小程序{BEHAVIOR_CLAUSE_GAP}(?:开通|开)(?:了)?(?:保单管家(?:服务|托管)?|保单托管|托管|服务)?
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:通过|从|在)(?:平安)?保单管家小程序{BEHAVIOR_CLAUSE_GAP}(?:开通|开)(?:了)?(?:保单管家(?:服务|托管)?|保单托管|托管|服务)?
  negative_patterns:
  - (?:没有|没|未).{0,4}开通保单管家服务
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:通过平安保单管家小程序)?开通了?保单管家服务)
  is_supported: true
- rule_id: behavior_class80
  activity: MIT_PROPOSAL_READEND
  activity_template: 在微信阅读了建议书“$productName$”，时长$time$秒
  priority: 100
  patterns:
  - 在微信(?:阅读|读过|看过)(?:了)?建议书时长秒
  - 在微信(?:阅读|读过|看过)(?:了)?建议书.{0,16}时长.{0,16}秒
  - 在微信{BEHAVIOR_CLAUSE_GAP}(?:仔细|认真)?(?:阅读|读过|看过)(?:了)?(?:{BEHAVIOR_PRODUCT_SLOT})?建议书
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}在微信{BEHAVIOR_CLAUSE_GAP}(?:仔细|认真)?(?:阅读|读过|看过)(?:了)?(?:{BEHAVIOR_PRODUCT_SLOT})?建议书
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在微信(?:阅读|读过|看过)(?:了)?建议书时长秒)
  is_supported: true
- rule_id: behavior_class81
  activity: JGJ_ONLINE_SCENE_PRODUCT_RESERVE
  activity_template: 通过金管家APP预约了解「“$productName$”」
  priority: 100
  patterns:
  - 通过金管家APP(?:预约了解|预约咨询|想了解)
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:通过金管家APP(?:预约了解|预约咨询|想了解))
  is_supported: true
- rule_id: behavior_class82
  activity: OLDCARE_TEST_USE
  activity_template: 完成了养老缺口测算
  priority: 100
  patterns:
  - (?:完成|做完)(?:了)?养老缺口测算
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:完成|做完)(?:了)?养老缺口测算)
  is_supported: true
- rule_id: behavior_class83
  activity: JGJ_CLUB_READ
  activity_template: 在金管家$clubName$俱乐部中，查看了$itemName$
  priority: 100
  patterns:
  - 在金管家俱乐部中(?:查看|看过|浏览)(?:了)?
  - 在金管家.{0,16}俱乐部中(?:查看|看过|浏览)(?:了)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家俱乐部中(?:查看|看过|浏览)(?:了)?)
  is_supported: true
- rule_id: behavior_class84
  activity: JGJ_FREEINSUR_JOIN_TEAM
  activity_template: 参与赠险组队活动，并与用户$shareClientName$完成组队领取
  priority: 100
  patterns:
  - (?:参与|参加)赠险组队活动并与用户完成组队领取
  - (?:参与|参加)赠险组队活动并与用户.{0,16}完成组队领取
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:参与|参加)赠险组队活动并与用户完成组队领取)
  is_supported: true
- rule_id: behavior_class85
  activity: JGJ_ACTIVITY_REAl_PRIZE
  activity_template: 在活动“$activityname$”中领取了奖品“$prizeName$”，该奖品需代理人上门递送。
  priority: 100
  patterns:
  - 在活动中(?:领取|领过)(?:了)?奖品该奖品需代理人上门递送
  - 在活动.{0,16}中(?:领取|领过)(?:了)?奖品.{0,16}该奖品需代理人上门递送
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在活动中(?:领取|领过)(?:了)?奖品该奖品需代理人上门递送)
  is_supported: true
- rule_id: behavior_class86
  activity: JGJ_POLICY_CLAIM_ASSIST
  activity_template: 成为了你名下老客户$inviterName$的紧急联络人，并领取了你赠送的权益$giftName$，他们之间的关系为$relationShip$
  priority: 100
  patterns:
  - 成为了你名下老客户的紧急联络人并(?:领取|领过)(?:了)?你赠送的权益他们之间的关系为
  - 成为了你名下老客户.{0,16}的紧急联络人并(?:领取|领过)(?:了)?你赠送的权益.{0,16}他们之间的关系为
  - (?:谁)?(?:被|由)?(?:老客户|客户){BEHAVIOR_CLAUSE_GAP}(?:设成|设置为|设为|指定为)(?:了)?紧急(?:联络人|联系人)
  - (?:成为|成了|成为了){BEHAVIOR_CLAUSE_GAP}紧急(?:联络人|联系人){BEHAVIOR_CLAUSE_GAP}(?:并|且)?(?:领取|领过|领了){BEHAVIOR_CLAUSE_GAP}权益
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:成为了你名下老客户的紧急联络人并(?:领取|领过)(?:了)?你赠送的权益他们之间的关系为)
  is_supported: true
- rule_id: behavior_class87
  activity: jgj_eduClub_test
  activity_template: 在金管家教育俱乐部中进行了测评，并了解“$services$”服务
  priority: 100
  patterns:
  - 在金管家教育俱乐部中进行了测评并了解服务
  - 在金管家教育俱乐部中进行了测评并了解.{0,16}服务
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家教育俱乐部中进行了测评并了解服务)
  is_supported: true
- rule_id: behavior_class88
  activity: JGJ_JYNJ25_PRODUCT_RESERVE
  activity_template: 在金管家预定利率场景预约了解「2.5%预定利率」产品，快去联系喔！
  priority: 100
  patterns:
  - 在金管家预定利率场景(?:预约了解|预约咨询|想了解)2\.5%预定利率产品快去联系喔
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:想了解|预约了解|预约咨询|咨询){BEHAVIOR_CLAUSE_GAP}2\.5%?预定利率产品
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家预定利率场景(?:预约了解|预约咨询|想了解)2\.5%预定利率产品快去联系喔)
  is_supported: true
- rule_id: behavior_class89
  activity: JGJ_SY_SCENE_PRODUCT_RESERVE
  activity_template: 在金管家税优场景预约了解「如何购买税优险」
  priority: 100
  patterns:
  - 在金管家税务场景(?:预约了解|预约咨询|想了解)如何购买税优险
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家税务场景(?:预约了解|预约咨询|想了解)如何购买税优险)
  is_supported: true
- rule_id: behavior_class90
  activity: PINGAN_WEB_RESERVE_2
  activity_template: 在平安人寿官网向您发起了预约申请
  priority: 100
  patterns:
  - 在平安人寿官网向您发起了预约申请
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在平安人寿官网向您发起了预约申请)
  is_supported: true
- rule_id: behavior_class91
  activity: JGJ_RIGHT_RESERVE
  activity_template: 在金管家$equityZoneName$中预约了解「“$reserveItemName$”」
  priority: 100
  patterns:
  - 在金管家中(?:预约了解|预约咨询|想了解|预约(?:了|过)?解)
  - 在金管家.{0,24}中(?:预约了解|预约咨询|想了解|预约(?:了|过)?解)
  - 在金管家(?:权益专区|权益区|权益中心)(?:中|里)?{BEHAVIOR_CLAUSE_GAP}(?:预约了解|预约咨询|想了解|预约(?:了|过)?解){BEHAVIOR_CLAUSE_GAP}(?:服务|产品)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家中(?:预约了解|预约咨询|想了解))
  is_supported: true
- rule_id: behavior_class92
  activity: JGJ_VISIT_RESERVE
  activity_template: 在“面访服务预约函”中提交了预约 "$serviceLetterTitle$"
  priority: 100
  patterns:
  - 在面访服务预约函中(?:提交|递交)(?:了)?预约
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在面访服务预约函中(?:提交|递交)(?:了)?预约)
  is_supported: true
- rule_id: behavior_class93
  activity: JGJ_VIPRIGHT_UPGRADE
  activity_template: 在金管家预约了解会员升级「$upgradeDetail$」
  priority: 100
  patterns:
  - 在金管家(?:预约了解|预约咨询|想了解)会员升级
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家(?:预约了解|预约咨询|想了解)会员升级)
  is_supported: true
- rule_id: behavior_class94
  activity: JGJ_ACTIVITY_APPLY_CHECK
  activity_template: 在金管家报名了部课活动“$activityName$”，请尽快审核客户是否通过
  priority: 100
  patterns:
  - 在金管家(?:报名|参加报名)(?:了)?部课活动请尽快审核客户是否通过
  - 在金管家(?:报名|参加报名)(?:了)?部课活动.{0,16}请尽快审核客户是否通过
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家(?:报名|参加报名)(?:了)?部课活动请尽快审核客户是否通过)
  is_supported: true
- rule_id: behavior_class95
  activity: JGJ_TECH_CLUB_TEST
  activity_template: 在金管家教育俱乐部，使用了留学计算器进行费用测算（选择了意向国家$IntendedCountries$，意向阶段$IntentionStage$，留学费用$cost$）
  priority: 100
  patterns:
  - (?:在金管家教育俱乐部)?(?:使用|用过|用)(?:了)?留学计算器(?:进行|做|完成|算)?(?:了|过)?(?:费用)?测算
  - 在金管家教育俱乐部(?:使用|用过)(?:了)?留学计算器进行费用测算选择了意向国家意向阶段留学费用
  - 在金管家教育俱乐部(?:使用|用过)(?:了)?留学计算器进行费用测算选择了意向国家.{0,16}意向阶段.{0,16}留学费用
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:在金管家教育俱乐部)?(?:使用|用过|用)(?:了)?留学计算器(?:进行|做|完成|算)?(?:了|过)?(?:费用)?测算)
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家教育俱乐部(?:使用|用过)(?:了)?留学计算器进行费用测算选择了意向国家意向阶段留学费用)
  is_supported: true
- rule_id: behavior_class96
  activity: jgj_beiqingTest
  activity_template: 在金管家完成了北清教育测评
  priority: 100
  patterns:
  - 在金管家(?:完成|做完)(?:了)?北清教育测评
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家(?:完成|做完)(?:了)?北清教育测评)
  is_supported: true
- rule_id: behavior_class97
  activity: BDGJ_JGJAPP_APPLY
  activity_template: 通过金管家app开通保单管家服务
  priority: 95
  patterns:
  - (?:通过|从|在)?(?:平安)?金管家(?:app|APP){BEHAVIOR_CLAUSE_GAP}(?:开通|开)(?:了)?(?:保单管家(?:服务|托管)?|保单托管|托管|服务)?
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:通过|从|在)(?:平安)?金管家(?:app|APP){BEHAVIOR_CLAUSE_GAP}(?:开通|开)(?:了)?(?:保单管家(?:服务|托管)?|保单托管|托管|服务)?
  - APP渠道{BEHAVIOR_CLAUSE_GAP}(?:开通|开)(?:了)?(?:保单管家(?:服务|托管)?|保单托管|托管|服务)?
  negative_patterns:
  - (?:没有|没|未).{0,4}开通保单管家服务
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:通过平安保单管家小程序)?开通了?保单管家服务)
  is_supported: true
- rule_id: behavior_class98
  activity_template: 在金管家预约了解产品“$productName$”
  priority: 100
  patterns:
  - 在金管家(?:预约了解|预约咨询|想了解)产品
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家(?:预约了解|预约咨询|想了解)产品)
  is_supported: true
  activities:
  - JGJ_MULTI_PRODUCT_RESERVE
  - JGJ_O2O_PRODUCT_RESERVE
  - JGJ_LIFE_PRODUCT_RESERVE
- rule_id: behavior_class99
  activity: JGJ_FORTUNE_SERVICE_RESERVE
  activity_template: 在金管家预约了「家庭财富保障方案讲解」服务
  priority: 100
  patterns:
  - 在金管家(?:预约|预订)(?:了)?家庭财富保障方案讲解服务
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家(?:预约|预订)(?:了)?家庭财富保障方案讲解服务)
  is_supported: true
- rule_id: behavior_class100
  activity: JGJ_ZJZA_RIGHT_STARTUP
  activity_template: 开启了重疾专案管理，Ta还有1项探视关怀服务待开启，及时联系TA并帮忙预约，避免浪费
  priority: 100
  patterns:
  - 开启了重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预约避免浪费
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:开启了重疾专案管理Ta还有1项探视关怀服务待开启及时联系TA并帮忙预约避免浪费)
  is_supported: true
- rule_id: behavior_class101
  activity: taxCalculator_reserve
  activity_template: 使用节税计算器，并预约税优服务
  priority: 100
  patterns:
  - 使用节税计算器并预约税优服务
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:使用节税计算器并预约税优服务)
  is_supported: true
- rule_id: behavior_class102
  activity_template: 已加入金管家$clubName$俱乐部会员，对$scene$有较高兴趣
  priority: 100
  patterns:
  - 已加入金管家俱乐部会员对有较高兴趣
  - 已加入金管家.{0,16}俱乐部会员[\s，,]*对.{0,16}有较高兴趣
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:已加入金管家俱乐部会员对有较高兴趣)
  is_supported: true
  activities:
  - JGJ_CLUB_JOIN
  - '1773735520064'
- rule_id: behavior_class103
  activity: JGJ_CLUB_JOIN_BIND
  activity_template: 已加入金管家$clubName$俱乐部会员并选择您作为保险规划师，对$scene$有较高兴趣
  priority: 100
  patterns:
  - 已加入金管家俱乐部会员并选择您作为保险规划师对有较高兴趣
  - 已加入金管家.{0,16}俱乐部会员并选择您作为保险规划师对.{0,16}有较高兴趣
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:已加入金管家俱乐部会员并选择您作为保险规划师对有较高兴趣)
  is_supported: true
- rule_id: behavior_class104
  activity: JGJ_CLUB_ACTIVITY_JOIN
  activity_template: 在金管家$clubName$俱乐部中，报名了活动$itemName$
  priority: 100
  patterns:
  - 在金管家俱乐部中(?:报名|参加报名)(?:了)?活动
  - 在金管家.{0,16}俱乐部中(?:报名|参加报名)(?:了)?活动
  - 在金管家{BEHAVIOR_PRODUCT_SLOT}俱乐部(?:中|里)?{BEHAVIOR_CLAUSE_GAP}(?:报名|参加报名|报了名)(?:了)?{BEHAVIOR_CLAUSE_GAP}活动
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家俱乐部中(?:报名|参加报名)(?:了)?活动)
  is_supported: true
- rule_id: behavior_class105
  activity: KDE_DS_COVERAGE_READ
  activity_template: 在微信中浏览了"$clientName$$clientTitle$"保障检视报告，浏览时长$time$秒
  priority: 100
  patterns:
  - 在微信中(?:浏览|查看|看过)(?:了)?保障检视报告(?:浏览|查看|看过)时长秒
  - 在微信中(?:浏览|查看|看过)(?:了)?.{0,16}保障检视报告(?:浏览|查看|看过)时长.{0,16}秒
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在微信中(?:浏览|查看|看过)(?:了)?保障检视报告(?:浏览|查看|看过)时长秒)
  is_supported: true
- rule_id: behavior_class106
  activity: BDGJ_WXMINIAPP_JGJ_APPLY
  activity_template: 通过金管家小程序开通保单管家服务
  priority: 95
  patterns:
  - (?:通过|从|在)?金管家小程序{BEHAVIOR_CLAUSE_GAP}(?:开通|开)(?:了)?(?:保单管家(?:服务|托管)?|保单托管|托管|服务)?
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:通过|从|在)金管家小程序{BEHAVIOR_CLAUSE_GAP}(?:开通|开)(?:了)?(?:保单管家(?:服务|托管)?|保单托管|托管|服务)?
  negative_patterns:
  - (?:没有|没|未).{0,4}开通保单管家服务
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:通过平安保单管家小程序)?开通了?保单管家服务)
  is_supported: true
- rule_id: behavior_class107
  activity: JGJ_PROPOSAL_SERVICE_RESERVE
  activity_template: 在金管家预约了定制投保建议书服务
  priority: 100
  patterns:
  - 在金管家(?:预约|预订)(?:了)?定制投保建议书服务
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家(?:预约|预订)(?:了)?定制投保建议书服务)
  is_supported: true
- rule_id: behavior_class108
  activity: JGJ_SNOWCLUB_JOIN
  activity_template: 加入了雪友俱乐部会员，选择您作为保险规划师
  priority: 100
  patterns:
  - 加入了雪友俱乐部会员选择您作为保险规划师
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:加入了雪友俱乐部会员选择您作为保险规划师)
  is_supported: true
- rule_id: behavior_class109
  activity: JGJ_RIGHT_ACTIVATE
  activity_template: 在金管家中激活了权益“$equityName$”
  priority: 100
  patterns:
  - 在金管家中激活了权益
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:在金管家{BEHAVIOR_CLAUSE_GAP})?(?:激活|启用)(?:过|了)?{BEHAVIOR_CLAUSE_GAP}(?:{BEHAVIOR_PRODUCT_SLOT})?权益(?:吗|呢)?
  - (?:{BEHAVIOR_PRODUCT_SLOT})?权益(?:已经|已)?激活{BEHAVIOR_CLAUSE_GAP}(?:但|且|并且)?(?:尚未|还没|未)(?:使用|用过)
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家中激活了权益)
  is_supported: true
- rule_id: behavior_class110
  activity: JGJ_RIGHT_USE
  activity_template: 在金管家中使用了权益“$equityName$”
  priority: 100
  patterns:
  - 在金管家中(?:使用|用过)(?:了)?权益
  - 在金管家{BEHAVIOR_CLAUSE_GAP}(?:使用|用过)(?:了)?{BEHAVIOR_PRODUCT_SLOT}权益
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:在金管家{BEHAVIOR_CLAUSE_GAP})?(?:使用|用过)(?:了)?{BEHAVIOR_CLAUSE_GAP}(?:{BEHAVIOR_PRODUCT_SLOT})?权益(?:吗|呢)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家中(?:使用|用过)(?:了)?权益)
  is_supported: true
- rule_id: behavior_class111
  activity: PINGAN_WEB_RESERVE
  activity_template: 在平安人寿官网预约了解产品“$productName$”
  priority: 100
  patterns:
  - 在平安人寿官网(?:预约了解|预约咨询|想了解)产品
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在平安人寿官网(?:预约了解|预约咨询|想了解)产品)
  is_supported: true
- rule_id: behavior_class112
  activity: JGJ_JJYL_SERVICE_RESERVE
  activity_template: 浏览了“$activityItems$”，对居家养老的“$serviceItems$”服务感兴趣
  priority: 100
  patterns:
  - (?:浏览|查看|看过)(?:了)?对居家养老的服务感兴趣
  - (?:浏览|查看|看过)(?:了)?.{0,16}对居家养老的.{0,16}服务感兴趣
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:浏览|查看|看过)(?:了)?对居家养老的服务感兴趣)
  is_supported: true
- rule_id: behavior_class113
  activity: SYZQ_ZEB_PRODUCT_ORDER
  activity_template: 预约您提供“$productName$”的税优政策和保险产品咨询服务
  priority: 100
  patterns:
  - 预约提供的税优政策和保险产品咨询服务
  - 预约提供.{0,16}的税优政策和保险产品咨询服务
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:预约提供的税优政策和保险产品咨询服务)
  is_supported: true
- rule_id: behavior_class114
  activity: SYZQ_ZEB_INFO_SHARE
  activity_template: 转发分享了资讯《$articleName$》
  priority: 80
  patterns:
  - (?:转发|分享)了?(?:资讯|专题)
  negative_patterns:
  - (?:没有|没|未|不曾|从未).{0,4}(?:转发|分享)
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:转发|分享)了?(?:资讯|专题))
  is_supported: true
- rule_id: behavior_class115
  activity: JGJ_CLUB_RIGHT_GET
  activity_template: 在金管家$clubName$俱乐部中，领取了权益$itemName$
  priority: 100
  patterns:
  - 在金管家俱乐部中(?:领取|领过)(?:了)?权益
  - 在金管家.{0,16}俱乐部中(?:领取|领过)(?:了)?权益
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家俱乐部中(?:领取|领过)(?:了)?权益)
  is_supported: true
- rule_id: behavior_class116
  activity: CHENGXING_LIVE_RESERVE
  activity_template: 在视频号直播间购买了咨询链接“$serviceName$"
  priority: 100
  patterns:
  - 在视频号直播间(?:购买|买过|买了)咨询链接
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在视频号直播间(?:购买|买过|买了)咨询链接)
  is_supported: true
- rule_id: behavior_cancel_consulting_order
  activity: CHENGXING_LIVE_CANCEL_RESERVE
  activity_template: 取消橙星直播间购买的服务咨询订单“$serviceName$”，进行了退单退款
  priority: 130
  patterns:
  - (?:取消|退订|退掉).{0,8}(?:服务咨询|咨询服务)(?:订单)?
  - (?:服务咨询|咨询服务)订单.{0,5}(?:退单|退款)
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:取消|退订|退掉).{0,8}(?:服务咨询|咨询服务)(?:订单)?)
  is_supported: true
- rule_id: behavior_class118
  activity: JGJ_OLDCARE_SERVICE_RESERVE
  activity_template: 在金管家预约了「养老规划服务」，快去联系喔！
  priority: 100
  patterns:
  - 在金管家(?:预约|预订)(?:了)?养老规划服务快去联系喔
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家(?:预约|预订)(?:了)?养老规划服务快去联系喔)
  is_supported: true
- rule_id: behavior_class119
  activity: JGJ_ACTIVITY_PABNX_RESERVE
  activity_template: 在参与“平安伴你行”活动时，点击预约了解$reservationItemName$
  priority: 100
  patterns:
  - 在(?:参与|参加)[「"'“]?平安伴你行[」"'”]?活动时[\s，,]*点击(?:预约了解|预约咨询|想了解|预约(?:了|过)?解)
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在(?:参与|参加)平安伴你行活动时点击(?:预约了解|预约咨询|想了解))
  is_supported: true
- rule_id: behavior_class120
  activity: JGJ_RESERVE_TPA
  activity_template: 在金管家添平安系列介绍中查看并预约了「“$reserveItemName$”」
  priority: 100
  patterns:
  - 在金管家泰安系列介绍中(?:查看|看过|浏览)并(?:预约|预订)(?:了)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家泰安系列介绍中(?:查看|看过|浏览)并(?:预约|预订)(?:了)?)
  is_supported: true
- rule_id: behavior_class121
  activity: JGJ_RIGHT_MedicalEscort_Used
  activity_template: 朋友或家属在金管家权益中，预约了$servertime$的陪诊服务
  priority: 100
  patterns:
  - 朋友或家属在金管家权益中(?:预约|预订)(?:了)?的陪诊服务
  - 朋友或家属在金管家权益中(?:预约|预订)(?:了)?.{0,16}的陪诊服务
  - (?:由|通过)?(?:朋友或家属|朋友|亲友|家属)(?:代为|代替|帮忙|发起)?(?:预约|预订|代约)(?:了)?陪诊(?:服务)?
  - 由(?:朋友或家属|朋友|亲友|家属)发起的陪诊预约
  - (?:谁(?:的)?|有人|有没有(?:客户)?){BEHAVIOR_CLAUSE_GAP}(?:朋友或家属|朋友|亲友|家属){BEHAVIOR_SHORT_GAP}(?:通过权益)?(?:预约|预订|代约)(?:了)?陪诊(?:服务)?(?:吗|呢)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:朋友或家属在金管家权益中(?:预约|预订)(?:了)?的陪诊服务)
  is_supported: true
- rule_id: behavior_class122
  activity: JGJ_RIGHT_MedicalEscort
  activity_template: 在金管家权益中，预约了$servertime$的陪诊服务
  priority: 100
  patterns:
  - 在金管家权益中(?:预约|预订)(?:了)?的陪诊服务
  - 在金管家权益中(?:预约|预订)(?:了)?.{0,16}的陪诊服务
  - 在金管家权益中(?:预约|预订)(?:了)?陪诊(?:服务)?
  - (?:谁|有人|有没有客户?)(?:使用|通过)?权益(?:预约|预订)(?:了)?陪诊(?:服务)?(?:吗|呢)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家权益中(?:预约|预订)(?:了)?的陪诊服务)
  is_supported: true
- rule_id: behavior_class123
  activity: JGJ_Product_YJX_ZHUANBAO_READ
  activity_template: 浏览了转保产品“$productname$”
  priority: 100
  patterns:
  - (?:浏览|查看|看过)(?:了)?转保产品
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:浏览|查看|看过)(?:了)?转保产品)
  is_supported: true
- rule_id: behavior_class124
  activity: JGJ_Product_YJX_BUY_SUCCESS
  activity_template: 购买产品“$productname$”
  priority: 100
  patterns:
  - (?:购买|买过|买了)产品
  - 购买产品
  - (?:购买|买过|买了){BEHAVIOR_PRODUCT_SLOT}(?:产品|险)
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:购买|买过|买了){BEHAVIOR_PRODUCT_SLOT}(?:产品|险)
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:有)?产品购买行为
  - (?:已|已经)(?:购买|买过|买了){BEHAVIOR_CLAUSE_GAP}(?:产品|商品|险)
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:购买|买过|买了)产品)
  is_supported: true
- rule_id: behavior_click_insure_not_completed
  activity: JGJ_Product_YJX_BUY_FAILD
  activity_template: 点击了立即投保“$productname$”产品，但未完成投保
  priority: 150
  patterns:
  - (?:点击|点过){BEHAVIOR_SHORT_GAP}(?:立即投保|我要投保){BEHAVIOR_PRODUCT_SLOT}(?:未完成|没完成|没有完成)(?:投保)?
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:点击|点了?|点过){BEHAVIOR_SHORT_GAP}(?:立即投保|我要投保|投保){BEHAVIOR_CLAUSE_GAP}(?:未完成|没完成|没有完成|没办完|中途放弃|流失)
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:中途放弃|放弃了?){BEHAVIOR_CLAUSE_GAP}投保
  - (?:立即投保|我要投保|投保).{0,12}(?:后|之后)(?:的)?(?:流失|中途放弃)
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:(?:点击|点过).{0,4}(?:立即投保|我要投保).{0,8}(?:未完成|没完成|没有完成)(?:投保)?)
  is_supported: true
- rule_id: behavior_class126
  activity: jgj_real_activity_OlderDance_Apply
  activity_template: 在金管家微信小程序「银龄舞集报名活动」中，加入了您绑定的舞蹈队$teamName$
  priority: 100
  patterns:
  - 在金管家微信小程序银龄舞集报名活动中加入了您绑定的舞蹈队
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家微信小程序银龄舞集报名活动中加入了您绑定的舞蹈队)
  is_supported: true
- rule_id: behavior_class127
  activity: CHENGXING_LIVE_RESERVE_DY
  activity_template: 在抖音直播间预约了保险咨询服务
  priority: 100
  patterns:
  - 在抖音直播间(?:预约|预订)(?:了)?保险咨询服务
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在抖音直播间(?:预约|预订)(?:了)?保险咨询服务)
  is_supported: true
- rule_id: behavior_class128
  activity: OnePokect_Culturegiif_Order
  activity_template: 已在壹钱包完成文创定制，请查看文创礼遇平台购物车并确认订单
  priority: 100
  patterns:
  - 已在壹钱包完成文创建制请(?:查看|看过|浏览)文创礼遇平台购物车并确认订单
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:已在壹钱包完成文创建制请(?:查看|看过|浏览)文创礼遇平台购物车并确认订单)
  is_supported: true
- rule_id: behavior_class129
  activity: ztProduct_ZJ_Car_Conclusion
  activity_template: 名下车辆$carNo$核保结论已下发，核保结论为$conclusion$
  priority: 100
  patterns:
  - 名下车辆核保结论已下发核保结论为
  - 名下车辆.{0,16}核保结论已下发核保结论为
  - (?:有没有客户?|谁的)?{BEHAVIOR_CLAUSE_GAP}(?:车辆|车险|汽车){BEHAVIOR_CLAUSE_GAP}核保(?:结果|结论)?{BEHAVIOR_CLAUSE_GAP}(?:为|是)?(?:通过|未通过|不通过|失败|成功|出来了|已下发)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:名下车辆核保结论已下发核保结论为)
  is_supported: true
- rule_id: behavior_class130
  activity: ztProduct_ZJ_Car_Conclusion_2
  activity_template: 名下车辆$carNo$验车结论已下发，验车结论为$conclusion$
  priority: 100
  patterns:
  - 名下车辆验车结论已下发验车结论为
  - 名下车辆.{0,16}验车结论已下发验车结论为
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:名下车辆验车结论已下发验车结论为)
  is_supported: true
- rule_id: behavior_class131
  activity: ztProduct_ZJ_Car_Renewal
  activity_template: 对车辆$carNo$进行了$activity$
  priority: 100
  patterns:
  - 对车辆进行了
  - 对车辆.{0,16}进行了
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:对车辆进行了)
  is_supported: true
- rule_id: behavior_class132
  activity: ztProduct_ZJ_Health_Claims
  activity_template: 名下健康险保单$polno$，案件情况：$caseStatus$，案件类型：$caseType$
  priority: 100
  patterns:
  - 名下健康险保单案件情况案件类型
  - 名下健康险保单.{0,16}案件情况.{0,16}案件类型
  - (?:谁的|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:健康险|健康保险){BEHAVIOR_CLAUSE_GAP}(?:理赔|理赔案件|案件){BEHAVIOR_CLAUSE_GAP}(?:还在|正在|处于)?(?:处理中|处理|未结案|已结案)
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:名下健康险保单案件情况案件类型)
  is_supported: true
- rule_id: behavior_class133
  activity: jgj_real_activity_OlderDance_Creat
  activity_template: 在金管家微信小程序「银龄舞集报名活动」中，提交了舞蹈队$teamName$的报名审核申请
  priority: 100
  patterns:
  - 在金管家微信小程序银龄舞集报名活动中(?:提交|递交)(?:了)?舞蹈队的报名审核申请
  - 在金管家微信小程序银龄舞集报名活动中(?:提交|递交)(?:了)?舞蹈队.{0,16}的报名审核申请
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家微信小程序银龄舞集报名活动中(?:提交|递交)(?:了)?舞蹈队的报名审核申请)
  is_supported: true
- rule_id: behavior_class134
  activity: ztProduct_ZJ_Property_Claims
  activity_template: 名下产险保单$situation$，案件经过：$desribe$
  priority: 100
  patterns:
  - 名下产险保单案件经过
  - 名下产险保单.{0,16}案件经过
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:名下产险保单案件经过)
  is_supported: true
- rule_id: behavior_class135
  activity: JGJ_READCLUB_ACTIVITY_JOIN
  activity_template: 在金管家提交了$scene$预报名，报名信息请见详情
  priority: 100
  patterns:
  - 在金管家(?:提交|递交)(?:了)?预报名报名信息请详情
  - 在金管家(?:提交|递交)(?:了)?.{0,16}预报名报名信息请详情
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家(?:提交|递交)(?:了)?预报名报名信息请详情)
  is_supported: true
- rule_id: behavior_class136
  activity: KDE_ClientNote_Ai
  activity_template: 创建AI客户笔记
  priority: 110
  patterns:
  - (?:创建|新建|新增|生成)(?:过|了)?(?:AI|智能)(?:客户)?笔记
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:创建|新建|新增|生成)(?:过|了)?(?:AI|智能)(?:客户)?笔记(?:吗|呢)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:创建AI客户笔记)
  is_supported: true
- rule_id: behavior_class137
  activity: JGJ_FANDENG_ACTIVITY_CYYX
  activity_template: 客户在$activityName$活动中，表示了有意向参与“樊登家庭教育讲座”
  priority: 100
  patterns:
  - 客户在活动中表示了有意向(?:参与|参加)樊登家庭教育讲座
  - 客户在.{0,16}活动中表示了有意向(?:参与|参加)樊登家庭教育讲座
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:客户在活动中表示了有意向(?:参与|参加)樊登家庭教育讲座)
  is_supported: true
- rule_id: behavior_class138
  activity: JGJ_JJQYGZH
  activity_template: 在金管家确认了您分享的“居家权益告知函”
  priority: 100
  patterns:
  - 在金管家确认了您分享的居家权益告知函
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家确认了您分享的居家权益告知函)
  is_supported: true
- rule_id: behavior_class139
  activity_template: 客户 $relation$$action$$item$
  priority: 100
  patterns:
  - ^客户.{1,12}(?:关系|动作|事项|项目).{0,12}$
  - 客户[\s，,]*(?:父亲|母亲|父母|爸爸|妈妈|儿子|女儿|子女|配偶|爱人|丈夫|妻子|家属|亲友|朋友).{0,6}(?:领取|查看|浏览|参与|参加|预约|使用).{1,20}
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:^客户.{1,12}(?:关系|动作|事项|项目).{0,12}$)
  is_supported: true
  activities:
  - JGJ_RIGHT_HOMESERVICE1
  - JGJ_RIGHT_HOMESERVICE2
- rule_id: behavior_class140
  activity: JGJ_POLICY_SERVICE_2026
  activity_template: '在金管家使用了「$serviceType$」分类的「$serviceName$」服务，保险产品为「$productName$」，保单号（投保单号）: $policyNo$'
  priority: 100
  patterns:
  - 在金管家(?:使用|用过)(?:了)?分类的服务保险产品为保单号投保单号
  - 在金管家(?:使用|用过)(?:了)?.{0,16}分类的.{0,16}服务保险产品为.{0,16}保单号投保单号
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家(?:使用|用过)(?:了)?分类的服务保险产品为保单号投保单号)
  is_supported: true
- rule_id: behavior_class141
  activity: JGJ_YSS_CT
  activity_template: '在金管家参团了$activityName$线下活动

    · 参团场次：$activitytime$

    · 参团人数：$activityNumber$'
  priority: 100
  patterns:
  - 在金管家参团了线下活动参团场次参团人数
  - 在金管家参团了.{0,16}线下活动参团场次.{0,16}参团人数
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:在金管家参团了线下活动参团场次参团人数)
  is_supported: true
- rule_id: behavior_class142
  activity: KDE_ClientNote_Normal
  activity_template: 创建「$type$」客户笔记
  priority: 100
  patterns:
  - 创建客户笔记
  - 创建.{0,16}客户笔记
  - (?:新建|新增)(?:过|了)?客户笔记
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:创建|新建|新增)(?:过|了)?客户笔记(?:吗|呢)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:创建客户笔记)
  is_supported: true
- rule_id: behavior_class143
  activity: JGJ_FANDENG_ACTIVITY_LYX
  activity_template: 通过您的客户$oldName$分享的$activityName$活动链接参与活动，表示了有意向参与“樊登家庭教育讲座”
  priority: 100
  patterns:
  - 通过您的客户分享的活动链接(?:参与|参加)活动表示了有意向(?:参与|参加)樊登家庭教育讲座
  - 通过您的客户.{0,16}分享的.{0,16}活动链接(?:参与|参加)活动表示了有意向(?:参与|参加)樊登家庭教育讲座
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:通过您的客户分享的活动链接(?:参与|参加)活动表示了有意向(?:参与|参加)樊登家庭教育讲座)
  is_supported: true
- rule_id: behavior_class144
  activity: JGJ_SH_MS_PT
  activity_template: 您发起的团活动$name$待向该客户配送货物，请尽快完成配送流程以保证服务时效性
  priority: 100
  patterns:
  - 您发起的团活动待向该客户配送货物请尽快完成配送流程以保证服务时效性
  - 您发起的团活动.{0,16}待向该客户配送货物请尽快完成配送流程以保证服务时效性
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:您发起的团活动待向该客户配送货物请尽快完成配送流程以保证服务时效性)
  is_supported: true
- rule_id: behavior_class145
  activity: JGJ_RIGHT_GET2
  activity_template: 兑换了「$rightsName$」权益，建议您完成相关服务
  priority: 100
  patterns:
  - 兑换了权益建议您完成相关服务
  - 兑换了.{0,16}权益建议您完成相关服务
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:兑换了权益建议您完成相关服务)
  is_supported: true
- rule_id: behavior_class146
  activity: JGJ_YSS_YYCT
  activity_template: '通过客户$oldcustomer$邀请，参团了$activityName$线下活动

    · 参团场次：$activitytime$

    · 参团人数：$activityNumber$'
  priority: 100
  patterns:
  - 通过客户邀请参团了线下活动参团场次参团人数
  - 通过客户.{0,16}邀请参团了.{0,16}线下活动参团场次.{0,16}参团人数
  - (?:经|通过|由){BEHAVIOR_PRODUCT_SLOT}邀请{BEHAVIOR_CLAUSE_GAP}(?:\d+|[一二两三四五六七八九十百]+)人?参团
  - (?:谁|有人|有没有客户?){BEHAVIOR_CLAUSE_GAP}(?:经|通过|由){BEHAVIOR_PRODUCT_SLOT}邀请{BEHAVIOR_CLAUSE_GAP}(?:\d+|[一二两三四五六七八九十百]+)人?参团(?:吗|呢)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}(?:通过客户邀请参团了线下活动参团场次参团人数)
  is_supported: true
- rule_id: behavior_growth_fund_education_assessment
  activity: '1773973964997'
  activity_template: 您的客户在金管家-成长基金教育测评完成了测评
  priority: 100
  patterns:
  - 成长基金教育测评(?:完成|做完|做过)?
  negative_patterns:
  - (?:没有|没|未曾|不曾|从未|尚未).{0,8}成长基金教育测评
  is_supported: true
