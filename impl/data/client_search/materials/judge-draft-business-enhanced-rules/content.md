# enhanced_rules_args.yaml

- evidence_ref: `business-enhanced-rules`
- location: `business://src/main/python/data/client_search_query_parse/enhanced_rules_args.yaml`
- source_revision: `a2cfd68ea351d5081d95857ca7bcbfac90434528`
- source_sha256: `f5c8a2ccccf59e0c395aaeb460e5c8d82476faa02b23a81a6f628122e77aa39c`

年龄/时间/状态等复杂口语模式如何落到字段与操作符（含 merge_to_llm 行为），与 field_definitions 一起决定解析行为。

---

# Level 2 增强规则配置 - 按客户信息表格字段顺序排列
#
# 规则结构：
# - name: 规则名称
# - is_supported: 是否支持（可选，false 表示可命中但最终会被过滤，并提示该字段暂不支持）
# - patterns: 正则表达式列表
# - field: 目标字段
# - operator: 操作符 (MATCH, GTE, LTE, RANGE, CONTAINS, NOT_CONTAINS, MATCH)
# - value_type: 值类型 (static, capture, range, transform)
# - value: 静态值或值处理配置
# - priority: 优先级

pattern_vars:
  CW: '[，,。\.？\?\！! ：\:\u4e00-\u9fa5]'
  SEARCH: '(?:哪些客户|我的哪些客户|我有哪些客户|我的客户中(?:有哪些)?|查找|查询|查|找|找一下|查一下|检索|搜索|搜|帮我查询|帮我查查|帮我查|帮我找|帮我搜索|帮我搜|给我看看|帮我看看|看看|哪些是|谁是|给我捞一批|捞一批|筛选)?(?:一下)?'
  SEARCH_REQUIRED: '(?:我的哪些客户|我有哪些客户|我的客户中(?:有哪些)?|查找|查询|查|找|找一下|查一下|检索|搜索|搜|帮我查询|帮我查查|帮我查|帮我找|帮我搜索|帮我搜|给我看看|帮我看看|看看|哪些是|谁是|给我捞一批|捞一批|筛选)(?:一下|下)?(?:[，, ]{0,2})'
  CUSTOMER_SUFFIX: '(?:的客户|客户|有哪些客户|有哪些人|名单|的人|人|的｜的客户|客户|客户名单|的?名单|的人|人)?'
  BUSINESS_ALNUM: '[A-Za-z0-9]'
  BUSINESS_DIGIT: '[0-9]'
  CUSTOMER_C_PREFIX: '[Cc]'
  CUSTOMER_ZERO_PREFIX: '00'
  POLICY_PA_PREFIX: '[PpAa]'
  POLICY_GP_PREFIX: '[Gg][Pp]'
  SUFFIX_WORD: '(?:尾号|尾数|末尾|最后四位|后四位|后几位|结尾)'
  MOBILE_FIELD_WORD: '(?:手机|手机号|手机号码|电话|电话号码|联系方式)'
  CLIENT_NO_FIELD_WORD: '(?:客户号|客户编号|客户代码|客户ID|客户id)'
  POLICY_NO_FIELD_WORD: '(?:保单|保单号|保单号码|保单编号|保单代码|保单ID|保单id)'
  # 地址规则专用语义变量。与全局 SEARCH 解耦，避免地址优化影响其他 L2 规则。
  ADDRESS_SEARCH: '(?:(?:我的哪些客户|我有哪些客户|我的客户中(?:有哪些)?|查找|查询|查|检索|搜索|搜|找|筛选|筛|看|看看|拜访|帮我查询|帮我查|帮我搜索|帮我搜|帮我找|帮我筛选|帮我筛|给我找|给我筛选|给我筛|给我看看|帮我看看|想拜访)(?:一下|下)?(?:[，,、\s]{0,2}))?'
  ADDRESS_CONTACT_SCOPE: '(?:联系地址|通讯地址|通信地址)'
  ADDRESS_FAMILY_SCOPE: '(?:家庭地址|家庭住址)'
  ADDRESS_RESIDENCE_CUE: '(?:居住地址(?:是|为|在|位于)?|住址(?:是|为|在|位于)?|住(?:在)?|居住在|定居在?|家住|家在|现居|老家在?|户籍(?:在)?|户口在|籍贯(?:是|在)?)'
  ADDRESS_CURRENT_LOCATION: '(?:当前位置|我的位置|我所在的位置|我附近|附近|我周围|我周边|我身边|我这里|我的附近|坐席附近|坐席周围|坐席周边|代理人附近|代理人周围|代理人周边|当前用户周围|当前用户周边|我旁边|旁边|代理人旁边|坐席旁边)'
  ADDRESS_PLACE_RELATION: '(?:方圆|周边|附近|周围|旁边)'
  ADDRESS_INSIDE_BOUNDARY: '(?:内|以内|之内|范围内|之内范围|以内范围)'
  ADDRESS_OUTSIDE_BOUNDARY: '(?:外|之外|以外|之外范围|以外范围)'
  ADDRESS_CONTAINS_CUE: '(?:包含|含有|含|有没有写|是否写有|是否包含|有写|写有|有|带有|带)'
  ADDRESS_TEXT_GUARD: '(?!.*(?:\d+(?:\.\d+)?\s*(?:公里|千米|km|米)|方圆|周边|附近|周围|旁边))'
  ADDRESS_VALUE: '[a-zA-Z0-9\u4e00-\u9fa5·•\-\#\(\)（）]{2,60}?'
  ADDRESS_CUSTOMER_SUFFIX: '(?:的客户名单|的客户|客户名单|客户|有哪些客户|有哪些人|有客户吗|名单|的人|的)?'
  ADDRESS_DEICTIC_SUFFIX: '(?:那边|这边|一带|片区|区域)?'
  ADDRESS_POST_SEARCH: '(?:[，,、\s]*(?:给我|帮我)?(?:查查|查一下|查下|查询|看看|看下|看一下|筛选|筛一下|筛下|列出来|找出来|显示出来)(?:这些|一下)?(?:客户)?)?'
  ADDRESS_RELATIVE_LOCATION: '(?:对面|旁边|隔壁|沿线|入口|出口|东侧|西侧|南侧|北侧|以东|以西|以南|以北|环内|环外)'
  ADDRESS_ROLE_EXCLUSION: '(?!.*(?:投保人|被保人|客户经理|代理人|联系人|家庭成员|家属|受益人))'
  ADDRESS_ENTITY: '[a-zA-Z0-9\u4e00-\u9fa5·•\-\#\(\)（）]{1,60}?(?:省|市|区|县|旗|州|盟|镇|乡|苏木|街道|办事处|村|路|街|巷|弄|号|栋|幢|单元|楼|座|室|小区|花园|公馆|大厦|广场|园区|社区|胡同|新城|名都|华庭|嘉园|苑|里|庄|营|屯|港|桥|站|湾|湖|河|岛|中心|商圈|CBD|大学城|开发区|高新区)'

# 普通规则统一使用可选搜索前缀和客户后缀。地址规则保留独立边界，
# SEARCH_REQUIRED 保留强制搜索语义；已有边界不会重复添加。
pattern_boundary_policy:
  enabled: true
  prefix: "{SEARCH}"
  suffix: "{CUSTOMER_SUFFIX}"
  preserve_prefixes:
    - "{SEARCH}"
    - "{SEARCH_REQUIRED}"
    - "{ADDRESS_SEARCH}"
  excluded_prefixes:
    - "{ADDRESS_SEARCH}"
  preserve_suffixes:
    - "{CUSTOMER_SUFFIX}"
    - "{ADDRESS_CUSTOMER_SUFFIX}"

bare_value_weak_match:
  pattern: '[A-Za-z0-9*]{1,64}'
  operator: "MATCH"
  confidence: 0.6
  # L1/L2 均未确认命中时，裸值扩展为多个候选字段，并由 QueryRouter 使用 OR 逻辑返回。
  fields:
    - "clientNo"
    - "polNo"
    - "clientMobile"

identifier_list_rules:
  - name: "客户号-批量精确匹配"
    field: "clientNo"
    operator: "CONTAINS"
    item_pattern: '(?:[Cc][A-Za-z0-9]{1,12}|00[A-Za-z0-9]{1,12})'
    separator_pattern: '[,、;；|｜]+'
    prefix_aliases:
      - "请将以下客户号转化为姓名"
      - "客户编号逗号分隔清单"
      - "请通过如下客户号，找出对应的客户名字"
      - "请通过如下客户号，找出对应的客户姓名"
      - "请通过如下客户号，客户号找出对应的客户名字"
      - "通过如下客户号，客户号找出相对应的客户信息"
      - "搜索以下客户的客户清单"
      - "通过客户的编号，找出客户的姓名"
      - "请把以下编号转换为姓名"
      - "找出如下客户号对应姓名"
      - "找出客户号对应姓名"
    patterns:
      # 客户号可唯一定位客户：允许编号列表前后出现任意说明文本。
      # ASCII 边界避免从 LC 理赔号或超长编号中截取 C... 误命中。
      - '[\s\S]*?(?<![A-Za-z0-9])(?P<values>{ITEM}(?:{SEP}{ITEM})+)(?![A-Za-z0-9])[\s\S]*'
      - '(?P<values>{ITEM}(?:{SEP}{ITEM})+)(?:{SEP})?'
      - '(?:(?:查询|查找|查|搜索|筛选|帮我查|帮我找)?(?:以下|这些|这批|多个|一批)?(?:客户号|客户编号|客户ID|客户id|客户代码)(?:为|是|如下|列表|清单|:)?)(?P<values>{ITEM}(?:{SEP}{ITEM})+)(?:{SEP})?(?:的客户|这些客户|客户名单|名单|客户)?'
    transform: "upper"
    min_items: 2
    max_items: 2000
    query_logic: "AND"
    priority: 100

  - name: "保单号-批量精确匹配"
    field: "polNo"
    operator: "CONTAINS"
    item_pattern: '(?:[PpAa][A-Za-z0-9]{14,17}|[Gg][Pp][A-Za-z0-9]{14})'
    separator_pattern: '[,、;；|｜]+'
    patterns:
      # 带字母前缀的保单号格式足够明确，允许列表前后存在任意文本。
      - '[\s\S]*?(?<![A-Za-z0-9])(?P<values>{ITEM}(?:{SEP}{ITEM})+)(?![A-Za-z0-9])[\s\S]*'
      - '(?P<values>{ITEM}(?:{SEP}{ITEM})+)(?:{SEP})?'
      - '(?:(?:查询|查找|查|搜索|筛选|帮我查|帮我找)?(?:以下|这些|这批|多个|一批)?(?:保单号|保单号码|保单编号|保险单号|保险单编号)(?:为|是|如下|列表|清单|:)?)(?P<values>{ITEM}(?:{SEP}{ITEM})+)(?:{SEP})?(?:的客户|这些客户|客户名单|名单|客户)?'
    transform: "upper"
    min_items: 2
    max_items: 2000
    query_logic: "OR"
    priority: 100

  # 纯数字无法仅凭格式区分保单号和其他编号，因此必须有明确保单号字段词。
  - name: "纯数字保单号-批量精确匹配"
    field: "polNo"
    operator: "CONTAINS"
    item_pattern: '[0-9]{15,17}'
    separator_pattern: '[,、;；|｜]+'
    patterns:
      # 纯数字仍必须带明确“保单号”字段词，只放宽字段表达前后的文本。
      - '[\s\S]*?(?:(?:查询|查找|查|搜索|筛选|帮我查|帮我找)?(?:以下|这些|这批|多个|一批)?(?:保单号|保单号码|保单编号|保险单号|保险单编号)(?:为|是|如下|列表|清单|:)?)(?P<values>{ITEM}(?:{SEP}{ITEM})+)(?![A-Za-z0-9])[\s\S]*'
      - '(?:(?:查询|查找|查|搜索|筛选|帮我查|帮我找)?(?:以下|这些|这批|多个|一批)?(?:保单号|保单号码|保单编号|保险单号|保险单编号)(?:为|是|如下|列表|清单|:)?)(?P<values>{ITEM}(?:{SEP}{ITEM})+)(?:{SEP})?(?:的客户|这些客户|客户名单|名单|客户)?'
    min_items: 2
    max_items: 2000
    query_logic: "OR"
    priority: 100


rules:

  # ==================== 未指明号码类型的尾号 ====================

  - name: "裸尾号-手机号或客户号"
    # 查询只说“尾号”而未说明号码类型时，手机号和客户号均可能命中。
    patterns:
      - '{SEARCH}(?:客户(?:的)?|号码(?:的)?)?(?:尾号|尾数|末尾)(?:为|是)?[：:\s]?(\d{1,11}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:客户(?:的)?|号码(?:的)?)?(?:尾号(?:的)?)?(?:最后|末|后)(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:尾号)?(?:为|是)?[：:\s]?(\d{1,11}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(\d{1,11})(?:作为|是|为)?(?:尾号|尾数|末尾){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:客户(?:的)?|号码(?:的)?)?以(\d{1,11})(?:作为)?(?:尾号|结尾){CUSTOMER_SUFFIX}'
    field: "clientMobile"
    operator: "MATCH"
    match_mode: "suffix"
    value_type: "capture"
    value:
      group: 1
      transform: "strip_non_digits"
    priority: 22
    query_logic: "OR"
    merge_to_llm: false
    extra_conditions:
      - field: "clientNo"
        operator: "MATCH"
        match_mode: "suffix"
        value_type: "capture"
        value:
          group: 1

  # ==================== 姓名 (searchClientName) ====================

  - name: "姓名-姓氏前缀"
    patterns:
      - '{SEARCH}([\u4e00-\u9fa5]{1,2})'
      - '{SEARCH}(?:的客户|客户)?姓(?:氏)?(?:为|是)?([\u4e00-\u9fa5]{1,2}?)(?:的客户|客户)?'
      - '{SEARCH}(?:客户)?(?:姓名|名字)?(?:为|是)?([\u4e00-\u9fa5]{1,2}?)姓(?:的客户|客户)?'
    field: "searchClientName"
    operator: "MATCH"
    match_mode: "prefix"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_surname_prefix"
    priority: 30
    merge_to_llm: false

#  - name: "姓名-显式称呼上下文"
#    patterns:
#      - '{SEARCH}(?:的客户|客户)?(?:叫|名叫|叫做|姓名是|姓名为|名字是|客户叫)([\u4e00-\u9fa5]{2,4}?)(?:的客户|客户)?'
#    field: "searchClientName"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 27
#    merge_to_llm: false

#  - name: "姓名-显式客户上下文"
#    patterns:
#      - '{SEARCH_REQUIRED}(?![\u4e00-\u9fa5]{0,3}(?:叫|姓名|名字))([\u4e00-\u9fa5]{2,4}?)(?:的客户|客户|本人)'
#      - '(?!{SEARCH_REQUIRED})(?![\u4e00-\u9fa5]{0,3}(?:叫|姓名|名字))([\u4e00-\u9fa5]{2,4}?)(?:的客户|客户|本人)'
#    field: "searchClientName"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "validated_person_name"
#    priority: 26
#    merge_to_llm: false

  - name: "姓名-保单上下文"
    patterns:
      - '{SEARCH_REQUIRED}([\u4e00-\u9fa5]{2,4}?)(?:的)?保单'
      - '(?!{SEARCH_REQUIRED})([\u4e00-\u9fa5]{2,4}?)(?:的)?保单'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 26
    merge_to_llm: false

  - name: "姓名-字段名无值"
    patterns:
      - '{SEARCH}(?!(?:客户|本人|我的))([\u4e00-\u9fa5]{2,4}?)(?:的)?(?:保单|保单号|保单编号|保单号码|身份证号|身份证号码|证件号|手机号|客户号|出生日期|生日|出生日|身份证号号码|保险单号)(?:是多少|是什么|查询|查一下)?'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 5
    merge_to_llm: false

  - name: "姓名-匹配"
    patterns:
      - '{SEARCH}(?:的客户|客户)?(?:叫|名叫|姓名是|姓名为|姓名匹配)(?!的客)([\u4e00-\u9fa5]{2,4}?)(?:的客户|客户)?'
      - '{SEARCH}(?:的客户|客户)?姓([\u4e00-\u9fa5])(?:的)?(?:[，,])?(?:的客户|客户)?'
      - '{SEARCH}(?:的客户|客户)?名字(?:带|含|包含|有|里有|中有|里包含|为|叫|是)([\u4e00-\u9fa5]{1,4}?)的客户'
      - '{SEARCH}找叫([\u4e00-\u9fa5]{2,4}?)(?:的客户|客户)?'
      - '{SEARCH}(?:的客户|客户)?(?:叫|名叫|姓名是|姓名为|姓名匹配)(?!的客)([a-zA-Z ]{1,20}?)(?:的客户|客户)?'
      - '{SEARCH}(?:的客户|客户)?姓([a-zA-Z ]{1,20})(?:的)?(?:[，,])?(?:的客户|客户)?'
      - '{SEARCH}(?:的客户|客户)?名字(?:带|含|包含|有|里有|中有|里包含|为|叫|是)([a-zA-Z ]{1,20})的客户'
      - '{SEARCH}找叫([a-zA-Z ]{1,20})(?:的客户|客户)?'
      - '{SEARCH}(?:的客户|客户)?(?:叫|名叫|叫做|姓名是|姓名为|名字是|客户叫)([\u4e00-\u9fa5]{2,4}?)(?:的客户|客户)?'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 10
    merge_to_llm: false

  - name: "姓名-本人上下文"
    patterns:
      - '{SEARCH}([\u4e00-\u9fa5]{2,4}?)本人'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 10
    merge_to_llm: false

  - name: "姓名-英文本人上下文"
    patterns:
      - '{SEARCH}([a-zA-Z ]{1,20})本人'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 10
    merge_to_llm: false

  - name: "明确客户姓名上下文"
    patterns:
      - '{SEARCH}(?:客户姓名|客户名字|姓名|名字)(?:是|为|叫)?([\u4e00-\u9fa5]{2,4}?)(?:的客户名单|的客户|客户名单|客户|名单|的人|本人|代理人)?$'
      - '{SEARCH}客户(?:姓名)?(?:是|为|叫)([\u4e00-\u9fa5]{2,4}?)(?:的客户名单|的客户|客户名单|客户|名单|的人|本人|代理人)?$'
      - '{SEARCH}客户([\u4e00-\u9fa5]{2,4}?)(?:的客户名单|的客户|客户名单|客户|名单|的人|本人|代理人)?$'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 90
    confidence_level: "STRONG"
    full_match_required: true
    merge_to_llm: false

  - name: "姓名-模糊匹配"
    patterns:
      - '{SEARCH}([\u4e00-\u9fa5]{1,3})'
      - '{SEARCH}([a-zA-Z ]{1,20})'
    pattern_boundary:
      customer_suffix: false
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 1
    merge_to_llm: false

  - name: "姓名-模糊匹配-姓"
    patterns:
      - '{SEARCH}([\u4e00-\u9fa5]{1})'
    field: "searchClientName"
    operator: "MATCH"
    match_mode: "prefix"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_surname_prefix"
    priority: 2
    merge_to_llm: false

  - name: "姓名-名下询问住院医疗"
    patterns:
      - '{SEARCH}([\u4e00-\u9fa5]{2,4}?)名下是否有住院医疗保险'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 22
    merge_to_llm: false

  - name: "姓名-投保人缴费统计"
    patterns:
      - '{SEARCH}([\u4e00-\u9fa5]{2,4}?)\d{1,2}月到\d{1,2}月作为投保人[，,]?累计还有几份保单缴费'
    field: "polNoInfo.applicantname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 22
    merge_to_llm: false

  - name: "姓名-保单权益领取状态询问"
    patterns:
      - '{SEARCH}([\u4e00-\u9fa5]{2,4}?)的(?:生存金|满期金|年金|红利)(?:是否|有没有|有没|是否已经)?(?:领取|领过|到账)(?:了|过|吗|么|？|\?)?'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 24
    merge_to_llm: false

  - name: "姓名+男性兄弟姐妹"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{1,4}?)(?:的|有)?(?:弟弟|哥哥|兄长|兄弟(?!姐妹))'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 24
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "姓名+女性兄弟姐妹"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{1,4}?)(?:的|有)?(?:姐姐|妹妹|(?<!兄弟)姐妹)'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 24
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "姓名+父亲"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{1,4}?)(?:的|有)?(?:父亲|爸爸|爸|父亲本人)'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 24
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "姓名+母亲"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{1,4}?)(?:的|有)?(?:母亲|妈妈|妈|母亲本人)'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 24
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "姓名+儿子"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{1,4}?)(?:的|有)?(?:儿子|男孩|男娃)'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 24
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "姓名+女儿"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{1,4}?)(?:的|有)?(?:女儿|女孩|闺女|女娃)'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 24
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "姓名+男性配偶"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{1,4}?)(?:的|有)?(?:丈夫|老公|先生)'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 24
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "姓名+女性配偶"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{1,4}?)(?:的|有)?(?:妻子|老婆|太太)'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 24
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "姓名+泛化家庭关系"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{2,4}?)(?:有|家里有|家中有|的)(?:父母|爸妈)'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 23
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"

  - name: "姓名+泛化子女关系"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{2,4}?)(?:有|育有|家里有|家中有|的)(?:子女|孩子|小孩)'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 23
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "姓名+泛化兄弟姐妹关系"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{2,4}?)(?:有|家里有|家中有|的)(?:兄弟姐妹|兄妹|姐弟)'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 23
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"

  - name: "姓名+泛化配偶关系"
    patterns:
      - '{SEARCH}(?!(?:家里|家中|家有|家人|本人|自己|客户))([\u4e00-\u9fa5]{2,4}?)(?:有|的)(?:配偶|爱人)'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "validated_person_name"
    priority: 23
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"

  - name: "母亲投保-客户姓名片段"
    patterns:
      - '([\u4e00-\u9fa5]{2,4})给她的'
    field: "searchClientName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 24
    merge_to_llm: false

  - name: "母亲投保-母亲姓名片段"
    patterns:
      - '母亲([\u4e00-\u9fa5]{2,4})买的感恩母亲[，,]?我现在想查一下被保险人[\u4e00-\u9fa5]{2,4}的信息'
    field: "familyInfo.familyclientname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 24
    merge_to_llm: false
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"

  - name: "手机号-尾号"
    patterns:
      - '{SEARCH}(?:本人)?{MOBILE_FIELD_WORD}(?:的)?{SUFFIX_WORD}(?:为|是)?[：:\s]?(\d{1,11}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(\d{1,11})(?:的)?{MOBILE_FIELD_WORD}(?:的)?{SUFFIX_WORD}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:1[3-9]\d)(?:\*{3,}|\*+)(\d{4})'
      - '{SEARCH}(?:本人)?(?:手机|手机号|手机号码|电话|电话号码|联系方式){CW}{0,2}(?:尾号|尾数|末尾|最后四位|后四位|后几位|结尾)(?:为|是)?[：:\s]?(\d{1,11}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:本人)?(?:手机|手机号|手机号码|电话|电话号码|联系方式)(?:以)?(\d{1,11})(?:结尾|为尾号|作尾号)(?:的客户|客户)?'
      - '{SEARCH}(?:本人)?(?:手机号|手机号码|电话号码|手机)(?:的)?(?:尾号|结尾|末尾)(?:为|是)?(?:的)?(\d{1,11})(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:本人)?(?:手机号|手机号码|电话号码|手机)(?:的)?(?:最后|末|后)(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?(\d+)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:本人)?(?:手机号|手机号码|电话号码|手机)(?:的)?结尾(?:是|为)?(\d+)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:本人)?(?:手机|手机号|手机号码|电话|联系方式){CW}{0,2}(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:为|是)?[：:\s]?(\d{1,11})(?:的客户|客户)?'
      - '{SEARCH}(?:本人)?(?:手机|手机号|手机号码|电话|联系方式){CW}{0,2}(\d{1,11})(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:的客户|客户)?'
      - '{SEARCH}(?:尾号|尾数|末尾|后四位|后几位)(?:为|是)?[：:\s]?(\d{1,11})(?:的)?(?:手机|手机号|手机号码|电话|联系方式)(?:的客户|客户)?'
      - '{SEARCH}(\d{1,11})(?:尾号|尾数|末尾|后四位|后几位)(?:的)?(?:手机|手机号|手机号码|电话|联系方式)(?:的客户|客户)?'
    field: "clientMobile"
    operator: "MATCH"
    match_mode: "suffix"
    value_type: "capture"
    value:
      group: 1
      transform: "strip_non_digits"
    priority: 18
    merge_to_llm: false

  - name: "手机号-匹配"
    patterns:
      - '{SEARCH}?(1[3-9]\d{9})'
      - '{SEARCH}?((?:\d{2,4}-){2,3}\d{2,4})'
      - '{SEARCH}(?:本人)?(?:手机号|手机号码|手机|电话|联系方式){CW}{0,2}(\d{1,11})(?:的客户|客户)?'
      - '{SEARCH}(?:本人)?(?:手机号|手机号码|手机|电话|联系方式){CW}{0,2}((?:\d{2,4}-){2,3}\d{2,4})(?:的客户|客户)?'
      - '{SEARCH}(?:本人)?(?:手机号|手机号码|手机|电话|联系方式)(?:为|是|匹配|等于|包含|含有|带有)?[：:\s]?(\d{1,11})(?:的客户|客户)?'
      - '{SEARCH}(?:本人)?(?:手机号|手机号码|手机|电话|联系方式)(?:为|是|匹配|等于|包含|含有|带有)?[：:\s]?((?:\d{2,4}-){2,3}\d{2,4})(?:的客户|客户)?'
      - '{SEARCH}(?:本人)?(?:手机号|手机号码|手机|电话|联系方式)(?:前缀|开头|以)(?:为|是)?[：:\s]?(\d{1,11})(?:开头)?(?:的客户|客户)?'
      - '{SEARCH}(?:本人)?(?:手机号|手机号码|手机|电话|联系方式){CW}{0,2}(\d{1,11})(?:开头|前缀)(?:的客户|客户)?'
      - '{SEARCH}(?:本人)?(?:手机号|手机号码|手机|电话|联系方式)(?:号段|段)(?:为|是)?[：:\s]?(\d{1,11})(?:的客户|客户)?'
      - '{SEARCH}(\d{1,11})(?:开头|号段|段)(?:的)?(?:手机|手机号|手机号码|电话|联系方式)(?:的客户|客户)?'
    field: "clientMobile"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "strip_non_digits"
    priority: 10
    merge_to_llm: false

  - name: "手机号-连字符格式"
    patterns:
      - '{SEARCH}(1[3-9]\d-\d{4}(?:-\d{4})?)(?:的客户|客户)?'
    field: "clientMobile"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "strip_non_digits"
    priority: 25
    merge_to_llm: false

  - name: "性别-枚举"
    enum_ref: "clientSex"
    patterns_template:
      - '{SEARCH}性别[为是：:]{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))性(?:客户)?'
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))客户'
    field: "clientSex"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 9
    merge_to_llm: false

  - name: "性别-简单"
    # 用于组合规则，只匹配"男"或"女"
    patterns:
      - '(?<!子)(?<!儿)(?<!孙)(男|女)(?!儿)(?:性|生)?(?!.*(?:、|，|,|和|或|及|与|以及).*(?:男|女))'
    field: "clientSex"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 8
    merge_to_llm: false

  # ==================== 属相 (clientZodiac) ====================

  - name: "属相-枚举"
    is_supported: false
    enum_ref: "clientZodiac"
    patterns_template:
      - '{SEARCH}(?:客户)?(?:属相|生肖)(?:为|是|属)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}属{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:属相|生肖){CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}{CUSTOMER_SUFFIX}'
    field: "clientZodiac"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 31
    merge_to_llm: false

  # ==================== 年龄 (clientAge) ====================
  - name: "年龄-中文精确"
    # 二十岁 / 三十岁 → 精确匹配整十年龄
    patterns:
      - '{SEARCH}(?:年龄)?([一二三四五六七八九]?十)岁(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "chinese_decade_plus_range"
      offset: 0
      range: 0
    priority: 10
    override_fields:
      - "clientAge"
    merge_to_llm: false

  - name: "年龄-中文以上"
    # 二十岁以上 / 三十岁以上 → chinese_decade_plus_range + 大范围模拟GTE
    patterns:
      - '{SEARCH}(?:年龄)?([一二三四五六七八九]?十)岁?以上(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "chinese_decade_plus_range"
      offset: 0
      range: 120
    priority: 10
    override_fields:
      - "clientAge"
    merge_to_llm: false

  - name: "年龄-中文年代几岁"
    patterns:
      - '{SEARCH}(?:年龄)?([一二三四五六七八九]?十)几岁(?:的客户|客户)?'
      - '{SEARCH}(?:年龄)?([一二三四五六七八九]?十)多岁(?:的客户|客户)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "chinese_decade_plus_range"
      offset: 0
      range: 9
    priority: 10
    merge_to_llm: false

  - name: "年龄-中文及以下"
    patterns:
      - '{SEARCH}(?:年龄)?([一二三四五六七八九十])周?岁?及?以下(?:生日)?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}(?:年龄)?(?:小于等于|不大于|不超过)([一二三四五六七八九十])周?岁?(?:生日)?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "clientAge"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
    priority: 10
    override_fields:
      - "birthdayMd"
      - "clientBirthday"
      - "clientAge"
    merge_to_llm: true

  - name: "年龄-青年"
    patterns:
      - '{SEARCH}(青年)(?:客户)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 18
      max: 35
    priority: 5

  - name: "年龄-男孩女孩"
    patterns:
      - '{SEARCH}(\d{1,3})岁男孩女孩(?:的客户|客户|的人|人)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 1
    priority: 9
    merge_to_llm: true
    extra_conditions:
      - field: "clientSex"
        operator: "CONTAINS"
        value:
          - "男"
          - "女"

  - name: "年龄-中年"
    patterns:
      - '{SEARCH}(中年|中年人)(?:客户)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 36
      max: 55
    priority: 5

  - name: "年龄-老年"
    patterns:
      - '{SEARCH}(?:老年|老人|老年人)(?:客户)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 56
      max: 100
    priority: 5

  - name: "年龄-未成年"
    patterns:
      - '{SEARCH}(未成年|没成年|未成年人|没成年的)(?:客户)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 0
      max: 17
    priority: 5

  - name: "年龄-少儿"
    patterns:
      - '{SEARCH}(?:少儿|儿童)(?:客户|名单|的人|人)?'
      - '{SEARCH}(?:少儿|儿童)客户名单'
    field: "clientAge"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 0
      max: 17
    priority: 11
    merge_to_llm: false

  - name: "年龄-少儿范围"
    patterns:
      - '{SEARCH}(\d+)[-~到至](\d+)岁(?:少儿|儿童)客户(?:名单)?'
      - '{SEARCH}(\d+)岁[-~到至](\d+)岁(?:少儿|儿童)客户(?:名单)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "range"
    value:
      min_group: 1
      max_group: 2
      transform: "int"
    priority: 12
    merge_to_llm: false

  - name: "年龄-少儿精确"
    patterns:
      - '{SEARCH}(\d+)岁(?:少儿|儿童)客户(?:名单)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 12
    merge_to_llm: false

  - name: "年龄-精确"
    patterns:
      - '{SEARCH}(?:年龄)?(\d+)周?岁(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}(?<!子女)(?<!小孩)(?<!儿子)(?<!女儿)(?<!小朋友)(?<!孩子)(?<![-~到至])(\d+)周?岁(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 8

  - name: "年龄-孩子按客户本人年龄"
    patterns:
      - '{SEARCH}(\d{1,2})岁(?:的)?(?:孩子|小孩|子女)?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 25
    merge_to_llm: false

  - name: "关爱客户-40岁及以上女性"
    patterns:
      - '{SEARCH}关爱客户'
    field: "clientAge"
    operator: "GTE"
    value_type: "static"
    value: 40
    priority: 24
    merge_to_llm: false
    extra_conditions:
      - field: "clientSex"
        operator: "MATCH"
        value: "女"

  - name: "年龄-以上"
    # 严格大于：以上/超过/大于/高于 → 转换为GTE并+1
    patterns:
      - '{SEARCH}(?:年龄)?(?:超过|高于|大于|>)(\d+)岁?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "clientAge"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int_plus_1"
    priority: 9

  - name: "年龄-及以上"
    # 大于等于：及以上/不低于/不少于/大于等于
    patterns:
      - '{SEARCH}(?:年龄)?(?:在|为|是)?(\d+)岁?及?以上(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}(?:年龄)?(?:大于等于|不少于|不低于|>=|≥)(\d+)岁?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "clientAge"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 9
    merge_to_llm: true

  - name: "年龄-以下"
    # 严格小于：以下/低于/小于 → 转换为LTE并-1
    patterns:
      - '{SEARCH}(?:年龄)?(?:小于|低于|<)(\d+)岁?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "clientAge"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int_minus_1"
    priority: 9
    merge_to_llm: true

  - name: "年龄-及以下"
    # 小于等于：及以下/不超过
    patterns:
      - '{SEARCH}(?:年龄)?(\d+)岁?及?以下(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}(?:年龄)?(?:小于等于|不大于|<=|≤|不超过)(\d+)岁?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "clientAge"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 9
    merge_to_llm: true

  - name: "年龄-范围"
    patterns:
      - '{SEARCH}(?:年龄)?(\d+)[-~到至](\d+)周?岁(?:的客户名单|客户名单|的客户|客户|的人名单|人名单|的人|人|名单)?'
      - '{SEARCH}年龄(?:在)?(\d+)[-~到至](\d+)周?岁之间?(?:的客户名单|客户名单|的客户|客户|的人名单|人名单|的人|人|名单)?'
      - '{SEARCH}(?:年龄)?(\d+)[-~到至](\d+)周?岁这一段(?:的客户名单|客户名单|的客户|客户|的人名单|人名单|的人|人|名单)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "range"
    value:
      min_group: 1
      max_group: 2
      transform: "int"
    priority: 9
    merge_to_llm: true

  - name: "年龄-左右"
    patterns:
      - '{SEARCH}(?:年龄)?(\d+)岁左右(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}(?:年龄)?(\d+)岁左右有哪些(?:客户|人)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      range: 5
    priority: 9
    merge_to_llm: true

  - name: "年龄-中文年代左右"
    patterns:
      - '{SEARCH}(?:年龄)?([一二三四五六七八九]?十)岁左右(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}(?:年龄)?([一二三四五六七八九]?十)岁左右有哪些(?:客户|人)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "chinese_decade_plus_range"
      offset: -5
      range: 5
    priority: 10
    merge_to_llm: true

  - name: "年龄-多岁"
    patterns:
      - '{SEARCH}(?:年龄)?(\d+)多岁(?:的客户|客户)?'
      - '{SEARCH}(?:年龄)?(\d+)几岁(?:的客户|客户)?'
    field: "clientAge"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "plus_range"
      offset: 0
      range: 9
    priority: 9
    merge_to_llm: true

# ==================== clientBirthday（出生年月日） ====================
  - name: "出生年月日-精确匹配"
    patterns:
      - '{SEARCH}出生[于年月日](\d{8})(?:的客户|客户)?'
      - '{SEARCH}出生日期[为是：:](\d{8})(?:的客户|客户)?'
      - '{SEARCH}生辰(\d{8})(?:的客户|客户)?'
    field: "clientBirthday"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "yyyymmdd_to_datetime"
    priority: 9

  - name: "出生年份-范围"
    patterns:
      - '{SEARCH}(\d{4})年(?:出生|出生的|生)(?:的客户|客户)?'
      - '{SEARCH}(?:出生|出生的|生|出生于|出生在)(\d{4})年(?:的客户|客户)?'
      - '{SEARCH}有没有(?:出生|出生的|生|出生于|出生在)(\d{4})年(?:的客户|客户)?'
      - '{SEARCH}生于(\d{4})年(?:的客户|客户)?'
      - '{SEARCH}(\d{2})年(?:出生|出生的|生)(?:的客户|客户)?'
      - '{SEARCH}(\d{2})年(?:的客户|客户)'
    field: "clientBirthday"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "birth_year_to_birth_range"
    priority: 8

  - name: "出生年份-片段"
    patterns:
      - '(\d{2}|\d{4})年(?:出生|出生的|生)?'
    field: "clientBirthday"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "birth_year_to_birth_range"
    priority: 12

  - name: "出生日期-年份之后"
    patterns:
      - '{SEARCH}出生日期(?:在)?(\d{4})年之后(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年之后出生(?:的客户|客户)?'
    field: "clientBirthday"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
    priority: 9

  - name: "出生日期-年份之前"
    patterns:
      - '{SEARCH}出生日期(?:在)?(\d{4})年之前(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年之前出生(?:的客户|客户)?'
    field: "clientBirthday"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_end_datetime"
    priority: 9

  - name: "生日-月份裸表达"
    patterns:
      - '{SEARCH}((?:\d{1,2})月(?:份)?)客户(?:名单)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "month_day_cn_to_md"
    priority: 18
    merge_to_llm: false

  - name: "生日-月份区间"
    patterns:
      - '{SEARCH}((?:\d{1,2})月?[-~到至](?:\d{1,2})月)(?:份)?(?:客户|名单|的人|人)'
      - '{SEARCH}客户生日(?:在)?((?:\d{1,2})月?[-~到至](?:\d{1,2})月)(?:份)?(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}生日(?:在)?((?:\d{1,2})月?[-~到至](?:\d{1,2})月)(?:份)?(?:的客户|客户|名单|的人|人)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "month_range_to_md"
    priority: 18
    merge_to_llm: false

  - name: "生日-月日"
    patterns:
      - '{SEARCH}((?:\d{1,2})月(?:\d{1,2})[日号]?)(?:过)?生日(?:的客户|客户)?'
      - '{SEARCH}生日(?:在)?((?:\d{1,2})月(?:\d{1,2})[日号]?)(?:的客户|客户)?'
      - '{SEARCH}((?:\d{1,2})月(?:份)?)(?:过)?生日(?:的客户|客户)?'
      - '{SEARCH}生日(?:在)?((?:\d{1,2})月(?:份)?)(?:的客户|客户)?'
      - '{SEARCH}客户生日(?:在)?((?:\d{1,2})月(?:份)?)(?:的客户|客户)?'
      - '{SEARCH}((?:\d{1,2})月(?:份)?)(?:客户|名单|的人|人)'
      - '{SEARCH}(?<!年)((?:\d{1,2}|正|一|二|两|三|四|五|六|七|八|九|十|十一|十二|冬|腊)月(?:份)?)(?:出生|出生的|生)(?:的客户|客户)?'
      - '{SEARCH}(?:出生|出生在|出生于)((?:\d{1,2}|正|一|二|两|三|四|五|六|七|八|九|十|十一|十二|冬|腊)月(?:份)?)(?:的客户|客户)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "month_day_cn_to_md"
    priority: 18

  - name: "生日-本月"
    patterns:
      - '{SEARCH}本月{CW}{0,2}生日(?:的客户|客户)?'
      - '{SEARCH}这个?月{CW}{0,2}生日(?:的客户|客户)?'
      - '{SEARCH}当月{CW}{0,2}生日(?:的客户|客户)?'
      - '{SEARCH}(?:本月|这个?月|当月)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:本月|这个?月|当月)(?:过生日|生日)的?(?:客户|人)(?:有哪些|有谁|名单)?'
      - '{SEARCH}(?:哪些|哪几位)?客户(?:本月|这个?月|当月)(?:会|要|将要|过)?生日(?:吗|么|嘛)?'
      - '{SEARCH}生日{CW}{0,2}在本月(?:的客户|客户)?'
      - '{SEARCH}生日{CW}{0,2}在这个?月(?:的客户|客户)?'
      - '{SEARCH}生日{CW}{0,2}在当月(?:的客户|客户)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_month"
      format: "MM-dd"
    priority: 18

  - name: "生日-下个月"
    patterns:
      - '{SEARCH}下个?月{CW}{0,2}生日(?:的客户|客户)?'
      - '{SEARCH}下个?月(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}下个?月(?:过生日|生日)的?(?:客户|人)(?:有哪些|有谁|名单)?'
      - '{SEARCH}(?:哪些|哪几位)?客户下个?月(?:会|要|将要|过)?生日(?:吗|么|嘛)?'
      - '{SEARCH}生日{CW}{0,2}在下个?月(?:的客户|客户)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_month"
      format: "MM-dd"
    priority: 18

  # 涉及到代码改动，下个版本放开
  - name: "生日-下下个月"
    patterns:
      - '{SEARCH}下下个?月{CW}{0,2}生日(?:的客户|客户)?'
      - '{SEARCH}下下个?月(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}下下个?月(?:过生日|生日)的?(?:客户|人)(?:有哪些|有谁|名单)?'
      - '{SEARCH}(?:哪些|哪几位)?客户下下个?月(?:会|要|将要|过)?生日(?:吗|么|嘛)?'
      - '{SEARCH}生日{CW}{0,2}在下下个?月(?:的客户|客户)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "month_offset"
      offset: 2
      format: "MM-dd"
    priority: 18

  - name: "生日-未来N天"
    patterns:
      - '{SEARCH}未来{CW}{0,2}(\d+)天{CW}{0,2}生日(?:的客户|客户)?'
      - '{SEARCH}(?:近|最近){CW}{0,2}(\d+)天(?:内|里)?{CW}{0,2}(?:过)?生日(?:的客户|客户)?'
      - '{SEARCH}(\d+)天内{CW}{0,2}生日(?:的客户|客户)?'
      - '{SEARCH}(?:未来|接下来|之后){CW}{0,2}(\d+)天(?:内|里)?(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:近|最近){CW}{0,2}(\d+)天(?:内|里)?(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(\d+)天内(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}生日{CW}{0,2}在未来{CW}{0,2}(\d+)天(?:的客户|客户)?'
      - '{SEARCH}生日{CW}{0,2}在(?:近|最近){CW}{0,2}(\d+)天(?:内|里)?(?:的客户|客户)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days_group: 1
      format: "MM-dd"
    priority: 18

  - name: "生日-未来一周"
    patterns:
      - '{SEARCH}未来{CW}{0,2}一周{CW}{0,2}生日(?:的客户|客户)?'
      - '{SEARCH}(?:未来|接下来|之后){CW}{0,2}一周(?:内|里)?(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:未来|接下来|之后){CW}{0,2}一周(?:内|里)?(?:过生日|生日)的?(?:客户|人)(?:有哪些|有谁|名单)?'
      - '{SEARCH}生日{CW}{0,2}在未来{CW}{0,2}一周(?:的客户|客户)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days: 7
      format: "MM-dd"
    priority: 18

  - name: "生日-近期"
    patterns:
      - '{SEARCH}生日(?:快到了|即将到来|快到|将到)(?:的客户|客户|的人)?'
      - '{SEARCH}即将过生日(?:的客户|客户|的人)?'
      - '{SEARCH}近期生日(?:的客户|客户|的人)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days: 29
      format: "MM-dd"
    priority: 18

  - name: "生日-本周"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}生日(?:的客户|客户)?'
      - '{SEARCH}(?:本周|这周|这个星期)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:本周|这周|这个星期)(?:过生日|生日)的?(?:客户|人)(?:有哪些|有谁|名单)?'
      - '{SEARCH}(?:哪些|哪几位)?客户(?:本周|这周|这个星期)(?:会|要|将要|过)?生日(?:吗|么|嘛)?'
      - '{SEARCH}生日{CW}{0,2}在(?:本周|这周|这个星期)(?:的客户|客户)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "MM-dd"
    priority: 18

  - name: "生日-下周"
    patterns:
      - '{SEARCH}下周{CW}{0,2}生日(?:的客户|客户)?'
      - '{SEARCH}(?:下周|下星期|下个星期)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:下周|下星期|下个星期)(?:过生日|生日)的?(?:客户|人)(?:有哪些|有谁|名单)?'
      - '{SEARCH}(?:哪些|哪几位)?客户(?:下周|下星期|下个星期)(?:会|要|将要|过)?生日(?:吗|么|嘛)?'
      - '{SEARCH}生日{CW}{0,2}在下周(?:的客户|客户)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_week"
      format: "MM-dd"
    priority: 18

  - name: "生日-下下周"
    patterns:
      - '{SEARCH}下下周{CW}{0,2}生日(?:的客户|客户)?'
      - '{SEARCH}(?:下下周|下下星期|下下个星期)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:下下周|下下星期|下下个星期)(?:过生日|生日)的?(?:客户|人)(?:有哪些|有谁|名单)?'
      - '{SEARCH}(?:哪些|哪几位)?客户(?:下下周|下下星期|下下个星期)(?:会|要|将要|过)?生日(?:吗|么|嘛)?'
      - '{SEARCH}生日{CW}{0,2}在下下周(?:的客户|客户)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 2
      format: "MM-dd"
    priority: 18

  - name: "生日-今天"
    patterns:
      - '{SEARCH}今天{CW}{0,2}生日(?:的客户|客户|的人)?'
      - '{SEARCH}今日{CW}{0,2}生日(?:的客户|客户|的人)?'
      - '{SEARCH}(?:今天|今日|当天)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:今天|今日|当天)(?:过生日|生日)的?(?:客户|人)(?:有哪些|有谁|名单)?'
      - '{SEARCH}生日{CW}{0,2}在今天(?:的客户|客户|的人)?'
      - '{SEARCH}生日{CW}{0,2}是今天(?:的客户|客户|的人)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "today"
      format: "MM-dd"
    priority: 18

  - name: "生日-明天"
    patterns:
      - '{SEARCH}明天{CW}{0,2}生日(?:的客户|客户|的人)?'
      - '{SEARCH}明日{CW}{0,2}生日(?:的客户|客户|的人)?'
      - '{SEARCH}(?:明天|明日)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:明天|明日)(?:过生日|生日)的?(?:客户|人)(?:有哪些|有谁|名单)?'
      - '{SEARCH}生日{CW}{0,2}在明天(?:的客户|客户|的人)?'
      - '{SEARCH}生日{CW}{0,2}是明天(?:的客户|客户|的人)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "tomorrow"
      format: "MM-dd"
    priority: 18

  - name: "生日-后天"
    patterns:
      - '{SEARCH}后天{CW}{0,2}生日(?:的客户|客户|的人)?'
      - '{SEARCH}后天(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要|过)?生日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}后天(?:过生日|生日)的?(?:客户|人)(?:有哪些|有谁|名单)?'
      - '{SEARCH}生日{CW}{0,2}在后天(?:的客户|客户|的人)?'
      - '{SEARCH}生日{CW}{0,2}是后天(?:的客户|客户|的人)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "day_after_tomorrow"
      format: "MM-dd"
    priority: 18

  - name: "生日-以后"
    # 严格大于：以后/之后 → 转换为GTE并+1天
    patterns:
      - '{SEARCH}(\d{1,2})月(\d{1,2})日?以后(?:的客户|客户|的人)?'
      - '{SEARCH}(\d{1,2})月(\d{1,2})日?之后(?:的客户|客户|的人)?'
      - '{SEARCH}生日{CW}{0,2}(\d{1,2})月(\d{1,2})日?以后(?:的客户|客户|的人)?'
    field: "birthdayMd"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "month_day_cn_to_md_plus_1"
    priority: 18

  - name: "生日-及以后"
    # 大于等于：及以后/及之后
    patterns:
      - '{SEARCH}(\d{1,2})月(\d{1,2})日?及以后(?:的客户|客户|的人)?'
      - '{SEARCH}(\d{1,2})月(\d{1,2})日?及之后(?:的客户|客户|的人)?'
      - '{SEARCH}生日{CW}{0,2}(\d{1,2})月(\d{1,2})日?及以后(?:的客户|客户|的人)?'
    field: "birthdayMd"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "month_day_cn_to_md"
    priority: 18

  - name: "生日-之前"
    # 严格小于：之前/以前 → 转换为LTE并-1天
    patterns:
      - '{SEARCH}(\d{1,2})月(\d{1,2})日?之前(?:的客户|客户|的人)?'
      - '{SEARCH}(\d{1,2})月(\d{1,2})日?以前(?:的客户|客户|的人)?'
      - '{SEARCH}生日{CW}{0,2}(\d{1,2})月(\d{1,2})日?之前(?:的客户|客户|的人)?'
    field: "birthdayMd"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "month_day_cn_to_md_minus_1"
    priority: 18

  - name: "生日-及之前"
    # 小于等于：及之前/及以前
    patterns:
      - '{SEARCH}(\d{1,2})月(\d{1,2})日?及之前(?:的客户|客户|的人)?'
      - '{SEARCH}(\d{1,2})月(\d{1,2})日?及以前(?:的客户|客户|的人)?'
      - '{SEARCH}生日{CW}{0,2}(\d{1,2})月(\d{1,2})日?及之前(?:的客户|客户|的人)?'
    field: "birthdayMd"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "month_day_cn_to_md"
    priority: 18

  - name: "生日-农历月份"
    patterns:
      - '{SEARCH}(?:农历|阴历)(1[0-2]|[1-9]|十[一二]?|[正一二三四五六七八九冬腊两])月(?:份)?生日(?:的客户|客户)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "lunar_month_to_md_range"
    priority: 18
    merge_to_llm: true

  - name: "生日-本月农历"
    patterns:
      - '{SEARCH}(?:查看|查下|查一下)?(?:本月|这个月|当月)的?(?:过|有|要过)?(?:农历|阴历)生日(?:的客户|客户|的|的人|人)?'
      - '{SEARCH}(?:农历|阴历)生日(?:是|在)?(?:本月|这个月|当月)(?:的)?(?:的客户|客户|的|的人|人)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_month"
      format: "MM-dd"
    priority: 18
    merge_to_llm: true

  - name: "生日-上月农历"
    patterns:
      - '{SEARCH}(?:上|上个|上个月|前一个月)的?(?:农历|阴历)生日(?:的客户|客户|的|的人|人)?'
      - '{SEARCH}(?:农历|阴历)生日(?:是|在)?(?:上|上个|上个月|前一个月)(?:的)?(?:的客户|客户|的|的人|人)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_month"
      format: "MM-dd"
    priority: 18
    merge_to_llm: true

  - name: "生日-下月农历"
    patterns:
      - '{SEARCH}(?:下|下个|下个月|后一个月)的?(?:农历|阴历)生日(?:的客户|客户|的|的人|人)?'
      - '{SEARCH}(?:农历|阴历)生日(?:是|在)?(?:下|下个|下个月|后一个月)(?:的)?(?:的客户|客户|的|的人|人)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_month"
      format: "MM-dd"
    priority: 18
    merge_to_llm: true

  - name: "生日-下周农历"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期)的?(?:农历|阴历)生日(?:的客户|客户|的|的人|人)?'
      - '{SEARCH}(?:农历|阴历)生日(?:是|在)?(?:下周|下星期|下个星期)(?:的)?(?:的客户|客户|的|的人|人)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_week"
      format: "MM-dd"
    priority: 18
    merge_to_llm: true

  - name: "生日-未来N天农历"
    patterns:
      - '{SEARCH}未来(\d+)天的?(?:农历|阴历)生日(?:的客户|客户)?'
      - '{SEARCH}(?:农历|阴历)生日(?:在)?未来(\d+)天(?:的客户|客户)?'
    field: "birthdayMd"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days_group: 1
      format: "MM-dd"
    priority: 18
    merge_to_llm: true

  # ==================== 学历 (education) ====================

  - name: "学历"
    enum_ref: "education"
    patterns_template:
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及)(?:{enum}))(?:学历|毕业)?(?:的客户|客户|的人|人)?'
      - '{SEARCH}(?:学历|学位)[为是：:]{enum}(?!.*(?:、|，|,|和|或|及|与|以及)(?:{enum}))(?:的客户|客户|的人|人)?'
      - '{SEARCH}学历(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及)(?:{enum}))(?:的客户|客户|的人|人)?'
    field: "education"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 8

  - name: "学历-以上"
    enum_ref: "education"
    patterns_template:
      - '{SEARCH}?{enum}(?:学历|毕业)?(?:（不含）|\(不含\)|不含|不包含)以上(?:的客户|客户)?'
      - '{SEARCH}?(?:学历|毕业)?{CW}{0,2}{enum}(?:（不含）|\(不含\)|不含|不包含)以上(?:的客户|客户)?'
    field: "education"
    operator: "CONTAINS"
    value_type: "enum_gt"
    value:
      group: 1
    priority: 9

  - name: "学历-及以上"
    enum_ref: "education"
    patterns_template:
      - '{SEARCH}?{enum}(?:学历|毕业)?及?以上(?:的客户|客户)?'
      - '{SEARCH}?{enum}及?以上(?:学历|毕业)?(?:的客户|客户)?'
      - '{SEARCH}?{enum}及?(?:学历|毕业)?以上(?:的客户|客户)?'
      - '{SEARCH}?(?:学历|毕业)?{CW}{0,2}{enum}及?以上(?:的客户|客户)?'
      - '{SEARCH}?及?以上{CW}{0,2}{enum}(?:学历|毕业)?(?:的客户|客户)?'
    field: "education"
    operator: "CONTAINS"
    value_type: "enum_gte"
    value:
      group: 1
    priority: 9

  - name: "学历-及以下"
    enum_ref: "education"
    patterns_template:
      - '{SEARCH}?{enum}(?:学历|毕业)?及?以下(?:的客户|客户)?'
      - '{SEARCH}?(?:学历|毕业)?{CW}{0,2}{enum}及?以下(?:的客户|客户)?'
    field: "education"
    operator: "CONTAINS"
    value_type: "enum_lte"
    value:
      group: 1
    priority: 9

  # ==================== 婚姻状况 (mariSts) ====================

  - name: "婚姻状况"
    enum_ref: "mariSts"
    patterns_template:
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}(?:客户)?婚姻状态(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}(?:客户)?婚姻状况(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
    field: "mariSts"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 10

  - name: "婚姻状况-单身"
    patterns:
      - '{SEARCH}单身(?:的客户|客户|的人|人)?'
    field: "mariSts"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "未婚"
      - "离婚"
    priority: 11
    merge_to_llm: true

  # ==================== 客户号 (clientNo) ====================

  - name: "客户号-尾号"
    patterns:
      - '{SEARCH}{CLIENT_NO_FIELD_WORD}(?:的)?{SUFFIX_WORD}(?:为|是)?[：:\s]?([A-Za-z0-9]{1,11}){CUSTOMER_SUFFIX}'
      - '{SEARCH}([A-Za-z0-9]{1,11})(?:的)?{CLIENT_NO_FIELD_WORD}(?:的)?{SUFFIX_WORD}{CUSTOMER_SUFFIX}'
      - '{SEARCH}00[A-Za-z0-9]*\*{3,}([A-Za-z0-9]{4})'
      - '{SEARCH}(?:尾号|尾数|末尾|后四位|后几位)(?:为|是)?[：:\s]?([A-Za-z0-9]{1,11})(?:的)?(?:客户号|客户编号|客户代码|客户ID|客户id){CUSTOMER_SUFFIX}'
      - '{SEARCH}([A-Za-z0-9]{1,11})(?:尾号|尾数|末尾|后四位|后几位)(?:的)?(?:客户号|客户编号|客户代码|客户ID|客户id){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:客户号|客户编号|客户代码|客户ID|客户id){CW}{0,2}(?:尾号|尾数|末尾|最后四位|后四位|后几位|结尾)(?:为|是)?[：:\s]?([A-Za-z0-9]{1,11}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:客户号|客户编号|客户代码|客户ID|客户id)(?:以)?([A-Za-z0-9]{1,11})(?:结尾|为尾号|作尾号){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:客户号|客户编号|客户代码|客户ID|客户id)(?:的)?(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:是|为)?([A-Za-z0-9]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:客户号|客户编号|客户代码|客户ID|客户id)(?:的)?最?后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:客户号|客户编号|客户代码|客户ID|客户id)以([A-Za-z0-9]+)(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:客户号|客户编号|客户代码|客户ID|客户id)(?:的)?(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:是|为)?([A-Za-z0-9]+){CUSTOMER_SUFFIX}'
    field: "clientNo"
    operator: "MATCH"
    match_mode: "suffix"
    value_type: "capture"
    value:
      group: 1
    priority: 18
    merge_to_llm: false

  # 理赔案件号（LC前缀，优先于客户号匹配，避免C被误提取）
  - name: "客户号-匹配"
    patterns:
      - '{SEARCH}?(?:客户号|客户编号|客户代码|客户ID|客户id){CW}{0,2}[为是：:]\s*(?<![A-Za-z])({CUSTOMER_C_PREFIX}{BUSINESS_ALNUM}{1,12})'
      - '{SEARCH}?(?:客户号|客户编号|客户代码|客户ID|客户id)(?:匹配|等于|包含|含有|带有)?(?<![A-Za-z])({CUSTOMER_C_PREFIX}{BUSINESS_ALNUM}{1,12})(?:的客户|客户|的)?'
      - '{SEARCH}?(?<![A-Za-z])({CUSTOMER_C_PREFIX}{BUSINESS_ALNUM}{10,12}){CW}{0,2}'
      - '{SEARCH}?(?:客户号|客户编号|客户代码|客户ID|客户id){CW}{0,2}[为是：:]\s*({CUSTOMER_ZERO_PREFIX}{BUSINESS_ALNUM}{1,12})'
      - '{SEARCH}?(?:客户号|客户编号|客户代码|客户ID|客户id)(?:匹配|等于|包含|含有|带有)?(?<![A-Za-z])({CUSTOMER_ZERO_PREFIX}{BUSINESS_ALNUM}{1,12})(?:的客户|客户|的)?'
      - '{SEARCH}?(?<![A-Za-z])({CUSTOMER_ZERO_PREFIX}{BUSINESS_ALNUM}{10,12}){CW}{0,2}'
      - '{SEARCH}?(?:客户号|客户编号|客户代码|客户ID|客户id)(?:前缀|开头|以)(?:为|是)?[：:\s]?([A-Za-z0-9]{1,12})(?:开头)?(?:的客户|客户|的)?'
      - '{SEARCH}?(?:客户号|客户编号|客户代码|客户ID|客户id)([A-Za-z0-9]{1,12})(?:开头|前缀)(?:的客户|客户)?'
      - '{SEARCH}([A-Za-z0-9]{1,12})(?:开头|前缀)(?:的)?(?:客户号|客户编号|客户代码|客户ID|客户id)(?:的客户|客户|的)?'
    field: "clientNo"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "upper"
    priority: 11

#  - name: "客户号-存在排序口语"
#    patterns:
#      - '{SEARCH}(?:所有客户|全部客户|全体客户)?(?:按|按照)?客户(?:号|编号|代码|ID|id)(?:升序|降序|从小到大|从大到小|排序|排列|排一排|排排|小的在前面)(?:的客户|客户|名单|清单)?'
#      - '{SEARCH}客户(?:号|编号|代码|ID|id)(?:小的在前面|从小到大|从大到小)(?:排|排序|排列|列出来)?'
#      - '.*客户(?:号|编号|代码|ID|id).*(?:升序|降序|从小到大|从大到小|排序|排列|排一排|排排|小的在前面).*'
#    field: "clientNo"
#    operator: "EXISTS"
#    value_type: "static"
#    value: ""
#    priority: 12
#    merge_to_llm: true

  - name: "客户价值"
    enum_ref: "newValueLabel"
    patterns_template:
      - '{SEARCH}{enum}(?!{CW}{0,2}(?:以上|及以上|更高|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum})){CUSTOMER_SUFFIX}'
      - '{SEARCH}客户价值[为是：:]{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}(?:谁是|哪些是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}{enum}(?:类)?(?!{CW}{0,2}(?:以上|及以上|更高|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum})){CUSTOMER_SUFFIX}'
      - '{SEARCH}客户价值[为是：:]{enum}(?:类)?(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}(?:谁是|哪些是)?{enum}(?:类)?(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))有哪些(?:客户)?'
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))都有谁'
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))名单'
    field: "newValueLabel"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 8
    merge_to_llm: false
    ignore_case: true

  - name: "客户价值-高价值"
    patterns:
      - '{SEARCH}(?:客户)?高价值{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:优质客户|价值高的?(?:客户)?|客户价值高的?(?:客户)?)(?:在哪|有谁|有哪些|名单|清单)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:按|按照)?(?:客户)?价值(?:从大到小|从高到低|高的|高低)?(?:排|排序|排列|理一理|排排)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:优质客户|价值高|客户价值高|按价值|按照价值){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:客户)?(?:高价值|有钱){CUSTOMER_SUFFIX}'
    field: "newValueLabel"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "A1"
      - "A2"
      - "A3"
      - "A4"
      - "B"
      - "C"
    priority: 10
    ignore_case: true

  - name: "客户价值-A档裸值"
    patterns:
      - '{SEARCH}[Aa]'
    field: "newValueLabel"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "A1"
      - "A2"
      - "A3"
      - "A4"
    priority: 24
    ignore_case: true
    merge_to_llm: false

  - name: "最近半年未联系的高价值客户"
    patterns:
      - '{SEARCH}(?:最近|近|过去)半年(?:没有|没|未)(?:联系|联络)(?:过)?的?(?:有钱|高价值)客户'
    field: "clientTemperature"
    operator: "MATCH"
    value_type: "static"
    value: "冷却"
    priority: 25
    merge_to_llm: false
    extra_conditions:
      - field: "newValueLabel"
        operator: "CONTAINS"
        value: ["A1", "A2", "A3", "A4", "B", "C"]

  - name: "客户价值-A类"
    patterns:
      - '{SEARCH}?A类(?:的客户|客户|有哪些客户|名单)?'
    field: "newValueLabel"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "A1"
      - "A2"
      - "A3"
      - "A4"
    priority: 8
    ignore_case: true

  - name: "客户价值-AB类"
    patterns:
      - '{SEARCH}?AB类(?:的客户|客户|有哪些客户|名单)?'
    field: "newValueLabel"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "A1"
      - "A2"
      - "A3"
      - "A4"
      - "B"
    priority: 8
    ignore_case: true

  - name: "客户价值-紧凑等级组合"
    patterns:
      - '{SEARCH}([A-Fa-f]{2,6})(?:类|档|客户|的客户)?'
      - '{SEARCH}(?:客户价值|客价)(?:为|是|包含)?([A-Fa-f]{2,6})(?:类|档|客户|的客户)?'
    field: "newValueLabel"
    operator: "CONTAINS"
    value_type: "capture"
    value:
      group: 1
      transform: "customer_value_letters"
    priority: 24
    ignore_case: true
    merge_to_llm: false

  - name: "客户价值-及以上"
    enum_ref: "newValueLabel"
    patterns_template:
      - '{SEARCH}{enum}(?:类|类客户)?(?:以上|更高|及以上)(?:的客户|客户)?'
      - '{SEARCH}(?:客户价值|客价){CW}{0,2}{enum}(?:类|类客户)?(?:以上|更高|及以上)(?:的客户|客户)?'
    field: "newValueLabel"
    operator: "CONTAINS"
    value_type: "enum_gte"
    value:
      group: 1
    priority: 9
    ignore_case: true

  - name: "客户价值-及以下"
    enum_ref: "newValueLabel"
    patterns_template:
      - '{SEARCH}?{enum}(?:类|类客户)?(?:及)?以下(?:的客户|客户)?'
      - '{SEARCH}?客户价值{CW}{0,2}{enum}(?:类|类客户)?(?:及)?以下(?:的客户|客户)?'
    field: "newValueLabel"
    operator: "CONTAINS"
    value_type: "enum_lte"
    value:
      group: 1
    priority: 9
    ignore_case: true

  # ==================== 客户温度 (clientTemperature) ====================

  - name: "客户温度"
    enum_ref: "clientTemperature"
    patterns_template:
      - '{SEARCH}?{enum}(?:客户)?(?!{CW}{0,2}(?:以上|及以上|更高|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}?客户温度{CW}{0,2}{enum}(?:客户)?(?!{CW}{0,2}(?:以上|及以上|更高|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}?客温{CW}{0,2}{enum}(?:客户)?(?!{CW}{0,2}(?:以上|及以上|更高|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户|名单|的人|人)?'
    field: "clientTemperature"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 7
    merge_to_llm: true

  - name: "客户温度-及以上"
    enum_ref: "clientTemperature"
    patterns_template:
      - '{SEARCH}?{enum}(?:客户)?(?:以上|更高|及以上)(?:的客户|客户)?'
      - '{SEARCH}?客户温度{CW}{0,2}{enum}(?:以上|更高|及以上)(?:的客户|客户)?'
      - '{SEARCH}?客温{CW}{0,2}{enum}(?:以上|更高|及以上)(?:的客户|客户)?'
    field: "clientTemperature"
    operator: "CONTAINS"
    value_type: "enum_gte"
    value:
      group: 1
    priority: 8

  - name: "客户温度-及以下"
    enum_ref: "clientTemperature"
    patterns_template:
      - '{SEARCH}?{enum}(?:客户)?(?:及)?以下(?:的客户|客户)?'
      - '{SEARCH}?客户温度{CW}{0,2}{enum}(?:及)?以下(?:的客户|客户)?'
      - '{SEARCH}?客温{CW}{0,2}{enum}(?:及)?以下(?:的客户|客户)?'
    field: "clientTemperature"
    operator: "CONTAINS"
    value_type: "enum_lte"
    value:
      group: 1
    priority: 8

  - name: "客户温度-中高温"
    patterns:
      - '{SEARCH}?中高温(?:客户)?(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}?客户温度{CW}{0,2}中高温(?:客户)?(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}?客温{CW}{0,2}中高温(?:客户)?(?:的客户|客户|名单|的人|人)?'
    field: "clientTemperature"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "中温"
      - "高温"
    priority: 8

  # ==================== 客群标签 (clientGroupLabel) ====================

  - name: "客群标签"
    enum_ref: "clientGroupLabel"
    patterns_template:
      - '{SEARCH}客群标签{CW}{0,2}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}客户分组(?:为|是|匹配|属于)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}(?:属于|是){enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:这类)?客户'
      - '{SEARCH}有{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))标签(?:的客户|客户)?'
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
    field: "clientGroupLabel"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 7

  # ==================== 寿险VIP (vipType) ====================

  - name: "寿险VIP-存在"
    patterns:
      - '{SEARCH}(?:寿险)?VIP(?:的客户|客户|名单|的人|人)?'
    field: "vipType"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 15
    merge_to_llm: true

  - name: "寿险VIP"
    enum_ref: "vipType"
    patterns_template:
      - '{SEARCH}{enum}(?:客户)?(?!{CW}{0,2}(?:以上|及以上|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}寿险VIP{CW}{0,2}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}客户VIP等级(?:为|是|匹配)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}VIP(?:还是|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
    field: "vipType"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 8

  - name: "寿险VIP-及以上"
    enum_ref: "vipType"
    patterns_template:
      - '{SEARCH}{enum}(?:VIP|客户)?(?:以上|更高|及以上)(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}寿险VIP{CW}{0,2}{enum}(?:以上|更高|及以上)(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}客户VIP等级(?:为|是|匹配)?{enum}(?:以上|更高|及以上)(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}VIP(?:还是|是)?{enum}(?:以上|更高|及以上)(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}{enum}(?:VIP|客户)?及?{CW}{0,2}以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
    field: "vipType"
    operator: "CONTAINS"
    value_type: "enum_gte"
    value:
      group: 1
    priority: 9

  - name: "寿险VIP-白银客户"
    patterns:
      - '{SEARCH}白银(?:VIP|客户|会员)?(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
    field: "vipType"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "白银1"
      - "白银2"
      - "白银3"
    priority: 10

  - name: "寿险VIP-黄金客户"
    patterns:
      - '{SEARCH}黄金(?:VIP|客户|会员)?(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
    field: "vipType"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "黄金V1"
      - "黄金V2"
      - "黄金V3"
      - "原黄金VIP"
    priority: 10

  - name: "寿险VIP-铂金客户"
    patterns:
      - '{SEARCH}铂金(?:VIP|客户|会员)?(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
    field: "vipType"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "铂金V1"
      - "铂金V2"
      - "原铂金VIP"
    priority: 10

  - name: "寿险VIP-及以上-白银"
    patterns:
      - '{SEARCH}白银(?:VIP|客户|会员)?及?以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}白银(?:VIP|客户|会员)?及?{CW}{0,2}以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}寿险VIP{CW}{0,2}白银及?以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}客户VIP等级(?:为|是|匹配)?白银及?以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}VIP(?:还是|是)?白银及?以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
    field: "vipType"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "白银1"
      - "白银2"
      - "白银3"
      - "黄金V1"
      - "黄金V2"
      - "黄金V3"
      - "原黄金VIP"
      - "铂金V1"
      - "铂金V2"
      - "原铂金VIP"
      - "钻石VIP"
      - "金钻VIP"
      - "黑钻VIP"
    priority: 10

  - name: "寿险VIP-及以上-黄金"
    patterns:
      - '{SEARCH}黄金(?:VIP|客户|会员)?(?:及?以上|更高)(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}黄金(?:VIP|客户|会员)?及?{CW}{0,2}以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}寿险VIP{CW}{0,2}黄金及?以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}(?:客户VIP等级|客户等级|VIP|寿险VIP)(?:为|是|匹配|在|达到|达|还是)?黄金及?以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
    field: "vipType"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "黄金V1"
      - "黄金V2"
      - "黄金V3"
      - "原黄金VIP"
      - "铂金V1"
      - "铂金V2"
      - "原铂金VIP"
      - "钻石VIP"
      - "金钻VIP"
      - "黑钻VIP"
    priority: 10

  - name: "寿险VIP-及以上-铂金"
    patterns:
      - '{SEARCH}铂金(?:VIP|客户|会员)?(?:及?以上|更高)(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}铂金(?:VIP|客户|会员)?及?{CW}{0,2}以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}寿险VIP{CW}{0,2}铂金及?以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}客户VIP等级(?:为|是|匹配)?铂金及?以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}VIP(?:还是|是)?铂金及?以上(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
    field: "vipType"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "铂金V1"
      - "铂金V2"
      - "原铂金VIP"
      - "钻石VIP"
      - "金钻VIP"
      - "黑钻VIP"
    priority: 10

#  - name: "寿险VIP-等级存在"
#    patterns:
#      - '{SEARCH}(?:会员等级|会员级别|VIP等级|VIP级别)(?:高的?|从高到低|从大到小)?(?:那些|这些|的客户|客户)?(?:有谁|有哪些|名单|清单|拉个清单|看看)?'
#      - '{SEARCH}(?:按|按照)?(?:会员等级|会员级别|VIP等级|VIP级别)(?:从高到低|从大到小|高低)?(?:排|排序|排列|排排|拉个清单)?'
#      - '.*(?:会员等级|会员级别|VIP等级|VIP级别).*(?:高|从高到低|从大到小|排序|排列|清单).*'
#    field: "vipType"
#    operator: "EXISTS"
#    value_type: "static"
#    value: ""
#    priority: 12
#    merge_to_llm: true


  # ==================== 寿险VIP积分与临界会员 ====================

  - name: "VIP积分余额-大于-万"
    patterns:
      - '{SEARCH}(?:寿险)?(?:VIP)?积分(?:余额)?(?:大于|超过|高于)(\d+)万(?:积分)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP)?积分(?:余额)?(\d+)万(?:积分)?(?:以上但不含|以上\(不含|以上（不含)(?:该值|本数|\d+万)?[）)]?{CUSTOMER_SUFFIX}'
    field: "pointsBalanceAmt"
    operator: "GT"
    value_type: "capture"
    value: {group: 1, transform: "multiply", multiplier: 10000}
    priority: 18
    merge_to_llm: true

  - name: "VIP积分余额-大于-原值"
    patterns:
      - '{SEARCH}(?:寿险)?(?:VIP)?积分(?:余额)?(?:大于|超过|高于)(\d+)(?:积分)?{CUSTOMER_SUFFIX}'
    field: "pointsBalanceAmt"
    operator: "GT"
    value_type: "capture"
    value: {group: 1, transform: "int"}
    priority: 17
    merge_to_llm: true

  - name: "VIP积分余额-大于等于-万"
    patterns:
      - '{SEARCH}(?:寿险)?(?:VIP)?积分(?:余额)?(\d+)万(?:积分)?(?:及以上|以上){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP)?积分(?:余额)?(?:大于等于|不少于|不低于|至少)(\d+)万(?:积分)?{CUSTOMER_SUFFIX}'
    field: "pointsBalanceAmt"
    operator: "GTE"
    value_type: "capture"
    value: {group: 1, transform: "multiply", multiplier: 10000}
    priority: 17
    merge_to_llm: true

  - name: "VIP积分余额-小于-万"
    patterns:
      - '{SEARCH}(?:寿险)?(?:VIP)?积分(?:余额)?(?:小于|低于|不足)(\d+)万(?:积分)?{CUSTOMER_SUFFIX}'
    field: "pointsBalanceAmt"
    operator: "LT"
    value_type: "capture"
    value: {group: 1, transform: "multiply", multiplier: 10000}
    priority: 17
    merge_to_llm: true

  - name: "VIP积分余额-小于等于-万"
    patterns:
      - '{SEARCH}(?:寿险)?(?:VIP)?积分(?:余额)?(\d+)万(?:积分)?(?:以内|之内|及以下){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP)?积分(?:余额)?(?:不超过|不高于|小于等于)(\d+)万(?:积分)?{CUSTOMER_SUFFIX}'
    field: "pointsBalanceAmt"
    operator: "LTE"
    value_type: "capture"
    value: {group: 1, transform: "multiply", multiplier: 10000}
    priority: 18
    merge_to_llm: true

  - name: "VIP积分余额-范围-万"
    patterns:
      - '{SEARCH}(?:寿险)?(?:VIP)?积分(?:余额)?(?:在)?(\d+)万(?:到|至|-|~)(\d+)万(?:积分)?(?:之间|以内)?{CUSTOMER_SUFFIX}'
    field: "pointsBalanceAmt"
    operator: "RANGE"
    value_type: "range"
    value: {min_group: 1, max_group: 2, transform: "multiply", multiplier: 10000}
    priority: 19
    merge_to_llm: true

  - name: "临界会员-指定升级等级"
    enum_ref: "criticalMemberGrade"
    patterns_template:
      - '{SEARCH}(?:即将|快要|马上)(?:可以|可)?升级(?:到|至|为|成){enum}(?:VIP)?(?:等级|级别)?(?:的)?(?:会员)?{CUSTOMER_SUFFIX}'
    field: "criticalMemberFlag"
    operator: "MATCH"
    value_type: "static"
    value: "是"
    priority: 22
    merge_to_llm: false
    extra_conditions:
      - field: "criticalMemberGrade"
        operator: "MATCH"
        value_type: "capture"
        value: {group: 1}

  - name: "临界会员等级-明确值"
    enum_ref: "criticalMemberGrade"
    patterns_template:
      - '{SEARCH}(?:临界会员)(?:等级|级别|档位)(?:为|是|等于|属于)?{enum}(?:VIP)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:VIP)?(?:临界会员等级|临界会员级别){CUSTOMER_SUFFIX}'
    field: "criticalMemberGrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 22
    merge_to_llm: true

  - name: "临界会员等级-非临界VIP客户"
    patterns:
      - '{SEARCH}非临界VIP客户{CUSTOMER_SUFFIX}'
    field: "criticalMemberGrade"
    operator: "MATCH"
    value_type: "static"
    value: "非临界VIP客户"
    priority: 22
    merge_to_llm: true

  - name: "临界会员-明确否"
    patterns:
      - '{SEARCH}(?:非|不是|不属于)(?:寿险)?临界会员{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?临界会员(?:标签|标记)?(?:为|是|等于)否{CUSTOMER_SUFFIX}'
    field: "criticalMemberFlag"
    operator: "MATCH"
    value_type: "static"
    value: "否"
    priority: 23
    merge_to_llm: true

  - name: "临界会员-标签枚举"
    enum_ref: "criticalMemberFlag"
    patterns_template:
      - '{SEARCH}(?:寿险)?临界会员(?:标签|标记)(?:为|是|等于){enum}{CUSTOMER_SUFFIX}'
    field: "criticalMemberFlag"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 22
    merge_to_llm: true

  - name: "临界会员-默认是"
    patterns:
      - '{SEARCH}(?:寿险)?临界会员(?:标签|标记)?(?:为|是|等于)?(?:是)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:即将|快要|马上)(?:可以|可)升级(?:的)?(?:寿险)?(?:VIP)?会员{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP)?会员(?:即将|快要|马上)(?:可以|可)升级{CUSTOMER_SUFFIX}'
    field: "criticalMemberFlag"
    operator: "MATCH"
    value_type: "static"
    value: "是"
    priority: 20
    merge_to_llm: true

  - name: "会员积分到期-未来N天"
    patterns:
      - '{SEARCH}(?:最近|近|未来|接下来)(\d+)天(?:内|里)?(?:寿险)?(?:VIP|会员)?积分(?:即将|快要|马上|将要)?(?:到期|过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:到期|过期)(?:时间|日期)?(?:在)?(?:最近|近|未来|接下来)(\d+)天(?:内|里)?{CUSTOMER_SUFFIX}'
    field: "pointsExpiredDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_n_days", days_group: 1, format: "yyyy-MM-dd"}
    priority: 20
    merge_to_llm: true

  - name: "会员积分到期-未来一个月"
    patterns:
      - '{SEARCH}(?:最近|近|未来|接下来)(?:一个月|30天|三十天)(?:内|里)?(?:寿险)?(?:VIP|会员)?积分(?:即将|快要|马上|将要)?(?:到期|过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:到期|过期)(?:时间|日期)?(?:在)?(?:最近|近|未来|接下来)(?:一个月|30天|三十天)(?:内|里)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:即将|快要|马上|将要)(?:到期|过期){CUSTOMER_SUFFIX}'
    field: "pointsExpiredDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_n_days", days: 30, format: "yyyy-MM-dd"}
    priority: 19
    merge_to_llm: true

  - name: "会员积分到期-上上周"
    patterns:
      - '{SEARCH}(?:上上周|上上星期|上上个星期)(?:寿险)?(?:VIP|会员)?积分(?:已经|已)?(?:到期|过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:到期|过期)(?:时间|日期)?(?:在|为|是)?(?:上上周|上上星期|上上个星期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:在|为|是)?(?:上上周|上上星期|上上个星期)(?:已经|已)?(?:到期|过期){CUSTOMER_SUFFIX}'
    field: "pointsExpiredDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: -2, format: "yyyy-MM-dd"}
    priority: 20
    merge_to_llm: true

  - name: "会员积分到期-上周"
    patterns:
      - '{SEARCH}(?:上周|上星期|上个星期)(?:寿险)?(?:VIP|会员)?积分(?:已经|已)?(?:到期|过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:到期|过期)(?:时间|日期)?(?:在|为|是)?(?:上周|上星期|上个星期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:在|为|是)?(?:上周|上星期|上个星期)(?:已经|已)?(?:到期|过期){CUSTOMER_SUFFIX}'
    field: "pointsExpiredDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: -1, format: "yyyy-MM-dd"}
    priority: 20
    merge_to_llm: true

  - name: "会员积分到期-本周"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期)(?:寿险)?(?:VIP|会员)?积分(?:即将|快要|将要|已经|已)?(?:到期|过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:到期|过期)(?:时间|日期)?(?:在|为|是)?(?:本周|这周|这个星期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:在|为|是)?(?:本周|这周|这个星期)(?:即将|快要|将要|已经|已)?(?:到期|过期){CUSTOMER_SUFFIX}'
    field: "pointsExpiredDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: 0, format: "yyyy-MM-dd"}
    priority: 20
    merge_to_llm: true

  - name: "会员积分到期-下周"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期)(?:寿险)?(?:VIP|会员)?积分(?:即将|快要|将要)?(?:到期|过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:到期|过期)(?:时间|日期)?(?:在|为|是)?(?:下周|下星期|下个星期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:在|为|是)?(?:下周|下星期|下个星期)(?:即将|快要|将要)?(?:到期|过期){CUSTOMER_SUFFIX}'
    field: "pointsExpiredDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: 1, format: "yyyy-MM-dd"}
    priority: 20
    merge_to_llm: true

  - name: "会员积分到期-下下周"
    patterns:
      - '{SEARCH}(?:下下周|下下星期|下下个星期)(?:寿险)?(?:VIP|会员)?积分(?:即将|快要|将要)?(?:到期|过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:到期|过期)(?:时间|日期)?(?:在|为|是)?(?:下下周|下下星期|下下个星期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:在|为|是)?(?:下下周|下下星期|下下个星期)(?:即将|快要|将要)?(?:到期|过期){CUSTOMER_SUFFIX}'
    field: "pointsExpiredDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: 2, format: "yyyy-MM-dd"}
    # “下下周”同时可能被 SEARCH 尾部可选“下”+“下周”规则完整匹配，
    # 因此必须高于“下周”，优先采用更具体的自然周表达。
    priority: 21
    merge_to_llm: true

  - name: "会员积分到期-上个月"
    patterns:
      - '{SEARCH}(?:上个月|上月)(?:寿险)?(?:VIP|会员)?积分(?:已经|已)?(?:到期|过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:到期|过期)(?:时间|日期)?(?:在|为|是)?(?:上个月|上月){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:在|为|是)?(?:上个月|上月)(?:已经|已)?(?:到期|过期){CUSTOMER_SUFFIX}'
    field: "pointsExpiredDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_month", format: "yyyy-MM-dd"}
    priority: 20
    merge_to_llm: true

  - name: "会员积分到期-本月"
    patterns:
      - '{SEARCH}(?:本月|这个月|当月)(?:寿险)?(?:VIP|会员)?积分(?:即将|快要|将要|已经|已)?(?:到期|过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:到期|过期)(?:时间|日期)?(?:在|为|是)?(?:本月|这个月|当月){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:在|为|是)?(?:本月|这个月|当月)(?:即将|快要|将要|已经|已)?(?:到期|过期){CUSTOMER_SUFFIX}'
    field: "pointsExpiredDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_month", format: "yyyy-MM-dd"}
    priority: 20
    merge_to_llm: true

  - name: "会员积分到期-下个月"
    patterns:
      - '{SEARCH}(?:下个月|下月)(?:寿险)?(?:VIP|会员)?积分(?:即将|快要|将要)?(?:到期|过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:到期|过期)(?:时间|日期)?(?:在|为|是)?(?:下个月|下月){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:寿险)?(?:VIP|会员)?积分(?:在|为|是)?(?:下个月|下月)(?:即将|快要|将要)?(?:到期|过期){CUSTOMER_SUFFIX}'
    field: "pointsExpiredDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_month", format: "yyyy-MM-dd"}
    priority: 20
    merge_to_llm: true


  # ==================== 经营阶段 (operation_stage) ====================

  - name: "存量客户类型-全枚举匹配"
    enum_ref: "orphanType"
    patterns_template:
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}存量{CW}{0,2}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}存量客户类型{CW}{0,2}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
    field: "orphanType"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 7

  - name: "寿险产品-百万医疗"
    patterns:
      - '{SEARCH}(?:已配置|已投保|购买了|购买|配置了|配置|配置有|配有|投保了|投保过|购买过|投保|买过|买了|已有|有了|有过|持有|有)?(?:百万医疗|百万医疗产品|百万医疗保险)(?:的客户|客户|名单|的人|人)?'
    field: "polNoInfo.plancodeinfo.abbrname"
    operator: "CONTAINS"
    value_type: "enum_values"
    value:
      enum_ref: "millionMedicalProducts"
    priority: 15

  - name: "寿险产品-未持有-百万医疗"
    patterns:
      - '{SEARCH}(?:未配置|未购买|没有买|没有|未投保|没投保|缺少)(?:百万医疗|百万医疗产品|百万医疗保险)(?:的客户|客户|名单|的人|人)?'
    field: "polNoInfo.plancodeinfo.abbrname"
    operator: "NOT_CONTAINS"
    value_type: "enum_values"
    value:
      enum_ref: "millionMedicalProducts"
    priority: 16

  - name: "寿险产品-税优养老"
    patterns:
      - '{SEARCH}(?:已配置|已投保|购买了|购买|配置了|配置|配置有|配有|投保了|投保过|购买过|投保|买过|买了|已有|有了|有过|持有|有)?(?:税优产品|税优养老产品|税优养老|税优|税优保险)(?:的客户|客户|名单|的人|人)?'
    field: "polNoInfo.plancodeinfo.abbrname"
    operator: "CONTAINS"
    value_type: "enum_values"
    value:
      enum_ref: "taxPreferredPensionProducts"
    priority: 15

  - name: "寿险产品-未持有-税优养老"
    patterns:
      - '{SEARCH}(?:未配置|未购买|没有买|没有|未投保|没投保|缺少)(?:税优产品|税优养老产品|税优养老)(?:的客户|客户|名单|的人|人)?'
    field: "polNoInfo.plancodeinfo.abbrname"
    operator: "NOT_CONTAINS"
    value_type: "enum_values"
    value:
      enum_ref: "taxPreferredPensionProducts"
    priority: 15

#  - name: "寿险产品-未持有"
#    enum_ref: "planAbbrNames"
#    patterns_template:
#      - '{SEARCH}{negation}{enum}(?:的客户|客户)?'
#    field: "planAbbrNames"
#    operator: "NOT_CONTAINS"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 10

#  - name: "寿险产品-存在"
#    patterns:
#      - '{SEARCH}(?:寿险客户|寿险名单|购买过寿险的客户|买过寿险的客户|有寿险的客户|买过寿险的人|购买过寿险的人)'
#      - '{SEARCH}(?:寿险)(?:的客户|客户|有哪些人|有哪些客户|名单|的人|人)?'
#    field: "planAbbrNames"
#    operator: "EXISTS"
#    value_type: "static"
#    priority: 9
#
#  - name: "寿险产品-不存在"
#    patterns:
#      - '{SEARCH}(?:不是|非|并非|不属于)寿险客户'
#      - '{SEARCH}(?:没有|没|无)寿险(?:客户|的客户|产品)?'
#      - '{SEARCH}不是寿险(?:客户|的客户)?'
#    field: "planAbbrNames"
#    operator: "NOT_EXISTS"
#    value_type: "static"
#    priority: 10

  # ==================== 持有产品类型 (pTypes) ====================

  - name: "持有产品类型-持有"
    enum_ref: "pTypes"
    patterns_template:
      - '{SEARCH}{enum}(?:的客户|客户)?'
      - '{SEARCH}{position}?{enum}(?:产品|保险)?(?:的客户|客户)?'
      - '{SEARCH}持有产品类型[为是：:]{enum}(?:的客户|客户)?'
      - '{SEARCH}产品类型(?:为|是|包含)?{enum}(?:的客户|客户)?'
      - '{SEARCH}{enum}产品持有者'
      - '{SEARCH}(?:所有)?{position}?{enum}(?:产品|保险)?(?:的客户|客户|名单)?'
    field: "pTypes"
    operator: "CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 10
    negation_support: true

  - name: "持有产品类型-未持有"
    enum_ref: "pTypes"
    patterns_template:
      - '{SEARCH}{negation}{enum}(?:产品|保险)?(?:的客户|客户)?'
    field: "pTypes"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 11

  - name: "万能有效客户"
    patterns:
      - '{SEARCH}万能有效(?:的客户|客户)?'
      - '{SEARCH}有效的万能(?:型)?(?:产品|保险)?(?:的客户|客户)?'
    field: "pTypes"
    operator: "MATCH"
    value_type: "static"
    value: "万能型"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "polNoInfo.polStatus"
        operator: "CONTAINS"
        value:
          - "交费有效"
          - "自垫交清"
          - "交清"
          - "减额交清"
          - "免交"
          - "自垫有效"

  - name: "持有产品类型-万能型"
    patterns:
     - '{SEARCH}万能(?:型|类|类型)?(?:产品|保险)?(?:的客户|客户)?'
     - '{SEARCH}(?:购买|持有|有|买了|投了|投保了)万能(?:型|类)?(?:产品|保险)?(?:的客户|客户)?'
    field: "pTypes"
    operator: "MATCH"
    value_type: "static"
    value: "万能型"
    priority: 10
    merge_to_llm: false

  - name: "持有产品类型-分红型"
    patterns:
      - '{SEARCH}分红(?:型|类|类型)?(?:产品|保险)?(?:的客户|客户)?'
      - '{SEARCH}(?:购买|持有|有|买了|投了|投保了)分红(?:型|类)?(?:产品|保险)?(?:的客户|客户)?'
    field: "pTypes"
    operator: "MATCH"
    value_type: "static"
    value: "分红型"
    priority: 10
    merge_to_llm: false


    # ==================== 持有产品类别 (pCategorys) ====================

  - name: "险种-持有"
    enum_ref: "pCategorys"
    patterns_template:
      - '{SEARCH}{position}?{enum}(?:产品|保险)?(?:的客户|客户|名单|有哪些人|有哪些|的人|人|的)?'
      - '{SEARCH}{enum}(?:产品|保险)?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}(?:产品类别|险种)(?:包含|为|是)?{enum}(?:保险)?(?:的客户|客户)?'
      - '{SEARCH}{position}?{enum}(?:产品|保险)?名单'
      - '{SEARCH}{enum}(?:产品)?(?:名单)?'
      - '{SEARCH}{position}?{enum}(?:产品|保险)?有哪些'
      - '{SEARCH}{enum}(?:产品|保险)?有哪些'
    field: "pCategorys"
    operator: "CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 8
    negation_support: true

  - name: "险种-重大疾病口语"
    patterns:
      - '{SEARCH}(?:持有|购买了?|买了?|买过|购买过|有过?|投保了?|投保过|配置了?|已有)(?:平安)?重大疾病(?:险|保险|产品)?(?:的客户|客户|名单|有哪些人|有哪些|的人|人|的)?'
    field: "pCategorys"
    operator: "MATCH"
    value_type: "static"
    value: "疾病保险"
    priority: 10
    merge_to_llm: true

  - name: "险种-未配置"
    enum_ref: "pCategorys"
    patterns_template:
      - '{SEARCH}{negation}{enum}(?:产品|保险)?(?:的客户|客户)?'
      - '{SEARCH}{negation}{enum}(?:产品|保险)?(?:的人|人)?'
    field: "pCategorys"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 9

  - name: "年缴保费-及以上"
    patterns:
      - '{SEARCH}年交?保费{CW}{0,2}(\d+)万及?以上(?:的客户|客户)?'
      - '{SEARCH}年交?保费(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)万(?:元)?(?:的客户|客户)?'
      - '{SEARCH}年缴(?:保费)?(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)万(?:元)?(?:的客户|客户)?'
      - '{SEARCH}年缴{CW}{0,2}(\d+)万及?以上(?:的客户|客户)?'
      - '{SEARCH}年交?保费{CW}{0,2}(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)万(?:的客户|客户)?'
      - '{SEARCH}年缴{CW}{0,2}(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)万(?:的客户|客户)?'
      - '{SEARCH}客户年交?保费{CW}{0,2}(\d+)万及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:年交?|年缴)?保费{CW}{0,2}(\d+)万及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:年交?|年缴)?保费{CW}{0,2}(?:在)?(\d+)万及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:年交?|年缴)?保费{CW}{0,2}(一)万及?以上(?:的客户|客户|有哪些)?'
    field: "annPremSegNum"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "年缴保费-以上"
    patterns:
      - '{SEARCH}年交?保费(?:大于|高于|超过|>)(\d+)万(?:元)?(?:的客户|客户)?'
      - '{SEARCH}年缴(?:保费)?(?:大于|高于|超过|>)(\d+)万(?:元)?(?:的客户|客户)?'
      - '{SEARCH}年交?保费{CW}{0,2}(?:大于|高于|超过|>)(\d+)万(?:的客户|客户)?'
      - '{SEARCH}年缴{CW}{0,2}(?:大于|高于|超过|>)(\d+)万(?:的客户|客户)?'
    field: "annPremSegNum"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "年缴保费-及以上-非万"
    patterns:
      - '{SEARCH}年交?保费{CW}{0,2}(\d+)及?以上(?:的客户|客户)?'
      - '{SEARCH}年缴{CW}{0,2}(\d+)及?以上(?:的客户|客户)?'
      - '{SEARCH}年缴{CW}{0,2}(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)(?:的客户|客户)?'
      - '{SEARCH}(?:年交?|年缴)?保费{CW}{0,2}(\d{4,})及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:年交?|年缴)?保费{CW}{0,2}(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)(?:都有谁|的客户|客户)?'
    field: "annPremSegNum"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 10

  - name: "年缴保费-以上-非万"
    patterns:
      - '{SEARCH}年缴{CW}{0,2}(?:大于|高于|超过|>)(\d+)(?:的客户|客户)?'
      - '{SEARCH}(?:年交?|年缴)?保费{CW}{0,2}(?:大于|高于|超过|>)(\d+)(?:都有谁|的客户|客户)?'
    field: "annPremSegNum"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 10

  - name: "年缴保费-及以下"
    patterns:
      - '{SEARCH}年交?保费{CW}{0,2}(\d+)万及?以下(?:的客户|客户)?'
      - '{SEARCH}年缴{CW}{0,2}(\d+)万及?以下(?:的客户|客户)?'
      - '{SEARCH}年交?保费{CW}{0,2}(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)万(?:的客户|客户)?'
      - '{SEARCH}年缴{CW}{0,2}(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)万(?:的客户|客户)?'
    field: "annPremSegNum"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "年缴保费-以下"
    patterns:
      - '{SEARCH}年交?保费{CW}{0,2}(?:小于|低于|<)(\d+)万(?:的客户|客户)?'
      - '{SEARCH}年缴{CW}{0,2}(?:小于|低于|<)(\d+)万(?:的客户|客户)?'
    field: "annPremSegNum"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "年缴保费-范围"
    patterns:
      - '{SEARCH}(?:的客户|客户)?保费(\d+)[-~到](\d+)万(?:的客户|客户)?'
      - '{SEARCH}(?:的客户|客户)?年缴保费(\d+)[-~到](\d+)万(?:的客户|客户)?'
    field: "annPremSegNum"
    operator: "RANGE"
    value_type: "range"
    value:
      min_group: 1
      max_group: 2
      transform: "multiply"
      multiplier: 10000
    priority: 9

  # ==================== 年缴保费-精确值 ====================
  - name: "年缴保费-精确值-万"
    patterns:
      # 精确值匹配（万）："年交保费2万的客户"
      - '{SEARCH}年(?:交|缴)?保费(?:等于|＝|是|为)?(\d+)万(?:的客户|客户)?(?:有谁|有哪些)?'
      - '{SEARCH}年(?:交|缴)(?:等于|＝|是|为)?(\d+)万(?:元)?(?:的客户|客户|的)?(?:有谁|有哪些)?'
    field: "annPremSegNum"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 10000
    priority: 10
    merge_to_llm: true

  - name: "年缴保费-精确值-千"
    patterns:
      # 精确值匹配（千）："年缴保费5千的客户"
      - '{SEARCH}年缴?保费(?:等于|＝|是|为)?(\d+)千(?:的客户|客户)?'
    field: "annPremSegNum"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 1000
    priority: 10
    merge_to_llm: true

  - name: "年缴保费-精确值-非万"
    patterns:
      # 精确值匹配（非万）："年缴保费20000的客户"
      - '{SEARCH}年缴?保费(?:等于|＝|是|为)?(\d+)(?:元)?(?:的客户|客户)?'
    field: "annPremSegNum"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 1
    priority: 10
    merge_to_llm: true

#  - name: "年缴保费-程度口语"
#    patterns:
#      - '{SEARCH}(?:交费多|缴费多|保费多|保费高|年缴保费高|年交保费高)(?:的)?(?:这批)?(?:客户|人|名单|有哪些|在哪)?'
#      - '{SEARCH}(?:按|按照)?(?:年缴保费|年交保费|保费)(?:从大到小|从高到低|高低)?(?:排|排序|排列|排排|理一理)?'
#      - '.*(?:交费多|缴费多|保费多|保费高|按保费|按照保费|年缴保费|年交保费).*'
#    field: "annPremSegNum"
#    operator: "EXISTS"
#    value_type: "static"
#    value: ""
#    priority: 12
#    merge_to_llm: true

  - name: "保额-及以上"
    patterns:
      - '{SEARCH}(?:客户)?总?保额{CW}{0,2}(\d+)万及?以上(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}(?:客户)?总?保额{CW}{0,2}(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)万(?:元)?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}总?保额{CW}{0,2}(一)万及?以上(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "insnoSumInsSeqNum"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "保额-以上"
    patterns:
      - '{SEARCH}(?:客户)?总?保额{CW}{0,2}(?:大于|高于|超过|>)(\d+)万(?:元)?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "insnoSumInsSeqNum"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "保额-高保额"
    patterns:
      - '{SEARCH}高保额(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}(?:买得多|保额高|保障额度高|保障金额高|总保额高)(?:的)?(?:客户|人|名单|有哪些|在哪)?'
      - '{SEARCH}(?:按|按照)?(?:保额|总保额|保障额度|保障金额)(?:从大到小|从高到低|高低)?(?:排|排序|排列|排排|理一理)?'
    field: "insnoSumInsSeqNum"
    operator: "GTE"
    value_type: "static"
    value: 300000
    priority: 10

  - name: "保额-精确"
    patterns:
      - '{SEARCH}总?保额[为是：:]?(\d+)万(?:元)?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}总?保额(?:刚好|等于)(\d+)万(?:元)?(?:的客户|客户)?'
    field: "insnoSumInsSeqNum"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 10

  - name: "保额-精确-非万"
    patterns:
      - '{SEARCH}总?保额[为是：:]?(\d{4,})(?:元)?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}总?保额(?:刚好|等于)(\d{4,})(?:元)?(?:的客户|客户)?'
    field: "insnoSumInsSeqNum"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 10

  - name: "保额-及以上-非万"
    patterns:
      - '{SEARCH}总?保额{CW}{0,2}(\d{4,})及?以上(?:的客户|客户)?'
      - '{SEARCH}总?保额{CW}{0,2}(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d{4,})(?:都有谁|的客户|客户)?'
    field: "insnoSumInsSeqNum"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 10

  - name: "保额-以上-非万"
    patterns:
      - '{SEARCH}总?保额{CW}{0,2}(?:大于|高于|超过|>)(\d{4,})(?:都有谁|的客户|客户)?'
    field: "insnoSumInsSeqNum"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 10

  - name: "保额-及以下"
    patterns:
      - '{SEARCH}总?保额{CW}{0,2}(\d+)万及?以下(?:的客户|客户)?'
      - '{SEARCH}总?保额{CW}{0,2}(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)万(?:的客户|客户)?'
    field: "insnoSumInsSeqNum"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "保额-以下"
    patterns:
      - '{SEARCH}总?保额{CW}{0,2}(?:小于|低于|<)(\d+)万(?:的客户|客户)?'
    field: "insnoSumInsSeqNum"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "保额-范围"
    patterns:
      - '{SEARCH}(?:的客户|客户)?总?保额{CW}{0,2}(\d+)[-~到](\d+)万(?:的客户|客户)?'
    field: "insnoSumInsSeqNum"
    operator: "RANGE"
    value_type: "range"
    value:
      min_group: 1
      max_group: 2
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "保单周年日-精确匹配"
    patterns:
      - '{SEARCH}保单周年日[为是：:]?(\d{2}-\d{2})(?:的客户|客户)?'
      - '{SEARCH}保单周年日期(\d{2}-\d{2})(?:的客户|客户)?'
      - '{SEARCH}保单周年日期[为是：:]?(\d+)(?:的客户|客户)?'
    field: "effAnniversaryDate"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 8

  - name: "保单周年日-年月"
    patterns:
      - '{SEARCH}保单周年日(?:在)?(\d{1,2})(?:的客户|客户)?'
      - '{SEARCH}保单周年日(?:在)?((?:\d{1,2})月)(?:的客户|客户)?'
      - '{SEARCH}(?:保单)?周年(?:日)?(?:在|是|落在)?((?:\d{1,2}|[一二三四五六七八九十冬腊]+)月)(?:的客户|客户|的人|人|的)?'
      - '{SEARCH}((?:\d{1,2}|[一二三四五六七八九十冬腊]+)月)(?:是|为)?(?:保单)?周年(?:日)?(?:的客户|客户|的人|人|的)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "month_day_cn_to_md"
    priority: 9

  - name: "保单周年日-下个月"
    patterns:
      - '{SEARCH}下个?月{CW}{0,2}(?:到)?保单周年日(?:了)?(?:的客户|客户)?'
      - '{SEARCH}保单周年日{CW}{0,2}在下个?月(?:的客户|客户)?'
      - '{SEARCH}下个?月{CW}{0,2}(?:到)?周年日(?:了)?(?:的客户|客户)?'
      - '{SEARCH}下个?月(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要)?(?:到)?保单周年日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}下个?月(?:到)?保单周年日的?(?:客户|人)(?:有哪些|有谁|名单)?'
      - '哪些客户{SEARCH}下个?月{CW}{0,2}(?:到)?保单周年日(?:了)?'
      - '{SEARCH}(?:保单)?周年日?(?:马上|快要|即将)(?:到|来|来了)?[，,]?下个?月(?:是谁|有谁|有哪些)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_month"
      format: "MM-dd"
    priority: 9

  - name: "保单周年日-上个月"
    patterns:
      - '{SEARCH}(?:上个月|上月){CW}{0,3}(?:过了|过完|刚过)?(?:保单)?周年日?(?:的客户|客户|的人|人|的)?(?:[，,](?:翻翻|看看|查查).*)?'
      - '{SEARCH}(?:保单)?周年日?{CW}{0,3}(?:在)?(?:上个月|上月)(?:过了|过完)?(?:的客户|客户|的人|人)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_month"
      format: "MM-dd"
    priority: 10

  - name: "保单周年日-本月"
    patterns:
      - '{SEARCH}本月{CW}{0,2}(?:到)?保单周年日(?:的客户|客户)?'
      - '{SEARCH}保单周年日{CW}{0,2}在本月(?:的客户|客户)?'
      - '{SEARCH}这个?月{CW}{0,2}(?:到)?周年日(?:的客户|客户)?'
      - '{SEARCH}(?:本月|这个?月|当月)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要)?(?:到)?保单周年日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:本月|这个?月|当月)(?:到)?保单周年日的?(?:客户|人)(?:有哪些|有谁|名单)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_month"
      format: "MM-dd"
    priority: 9

  - name: "保单周年日-下下个月"
    patterns:
      - '{SEARCH}下下个?月{CW}{0,2}(?:到)?保单周年日(?:了)?(?:的客户|客户)?'
      - '{SEARCH}保单周年日{CW}{0,2}在下下个?月(?:的客户|客户)?'
      - '{SEARCH}下下个?月{CW}{0,2}(?:到)?周年日(?:了)?(?:的客户|客户)?'
      - '{SEARCH}下下个?月(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要)?(?:到)?保单周年日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}下下个?月(?:到)?保单周年日的?(?:客户|人)(?:有哪些|有谁|名单)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "month_offset"
      offset: 2
      format: "MM-dd"
    priority: 9

  - name: "保单周年日-本周"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:到)?保单周年日(?:的客户|客户)?'
      - '{SEARCH}保单周年日{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期)(?:的客户|客户)?'
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:到)?周年日(?:的客户|客户)?'
      - '{SEARCH}(?:本周|这周|这个星期)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要)?(?:到)?保单周年日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:本周|这周|这个星期)(?:到)?保单周年日的?(?:客户|人)(?:有哪些|有谁|名单)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "MM-dd"
    priority: 9

  - name: "保单周年日-下周"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:到)?保单周年日(?:了)?(?:的客户|客户)?'
      - '{SEARCH}保单周年日{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期)(?:的客户|客户)?'
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:到)?周年日(?:了)?(?:的客户|客户)?'
      - '{SEARCH}(?:下周|下星期|下个星期)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要)?(?:到)?保单周年日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:下周|下星期|下个星期)(?:到)?保单周年日的?(?:客户|人)(?:有哪些|有谁|名单)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 1
      format: "MM-dd"
    priority: 9

  - name: "保单周年日-下下周"
    patterns:
      - '{SEARCH}(?:下下周|下下星期|下下个星期){CW}{0,2}(?:到)?保单周年日(?:了)?(?:的客户|客户)?'
      - '{SEARCH}保单周年日{CW}{0,2}在(?:下下周|下下星期|下下个星期)(?:的客户|客户)?'
      - '{SEARCH}(?:下下周|下下星期|下下个星期){CW}{0,2}(?:到)?周年日(?:了)?(?:的客户|客户)?'
      - '{SEARCH}(?:下下周|下下星期|下下个星期)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要)?(?:到)?保单周年日(?:吗|么|嘛|的客户|客户)?'
      - '{SEARCH}(?:下下周|下下星期|下下个星期)(?:到)?保单周年日的?(?:客户|人)(?:有哪些|有谁|名单)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 2
      format: "MM-dd"
    priority: 9

  - name: "保单周年日-未来N天"
    patterns:
      - '{SEARCH}(?:未来|接下来|之后)(\d+)天(?:内|里)?{CW}{0,2}(?:到)?保单周年日(?:的客户|客户)?'
      - '{SEARCH}保单周年日{CW}{0,2}在?(?:未来|接下来|之后)(\d+)天(?:内|里)?(?:的客户|客户)?'
      - '{SEARCH}(?:未来|接下来|之后)(\d+)天(?:内|里)?{CW}{0,2}(?:到)?周年日(?:的客户|客户)?'
      - '{SEARCH}(?:未来|接下来|之后)(\d+)天(?:内|里)?(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要)?(?:到)?保单周年日(?:吗|么|嘛|的客户|客户)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days_group: 1
      format: "MM-dd"
    priority: 9

  - name: "保单周年日-今天"
    patterns:
      - '{SEARCH}(?:今天|今日|当天){CW}{0,2}(?:到)?保单周年日(?:的客户|客户)?'
      - '{SEARCH}保单周年日{CW}{0,2}在?(?:今天|今日|当天)(?:的客户|客户)?'
      - '{SEARCH}(?:今天|今日|当天){CW}{0,2}(?:到)?周年日(?:的客户|客户)?'
      - '{SEARCH}(?:今天|今日|当天)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要)?(?:到)?保单周年日(?:吗|么|嘛|的客户|客户)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "today"
      format: "MM-dd"
    priority: 9

  - name: "保单周年日-明天"
    patterns:
      - '{SEARCH}(?:明天|明日){CW}{0,2}(?:到)?保单周年日(?:的客户|客户)?'
      - '{SEARCH}保单周年日{CW}{0,2}在?(?:明天|明日)(?:的客户|客户)?'
      - '{SEARCH}(?:明天|明日){CW}{0,2}(?:到)?周年日(?:的客户|客户)?'
      - '{SEARCH}(?:明天|明日)(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要)?(?:到)?保单周年日(?:吗|么|嘛|的客户|客户)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "tomorrow"
      format: "MM-dd"
    priority: 9

  - name: "保单周年日-后天"
    patterns:
      - '{SEARCH}后天{CW}{0,2}(?:到)?保单周年日(?:的客户|客户)?'
      - '{SEARCH}保单周年日{CW}{0,2}在?后天(?:的客户|客户)?'
      - '{SEARCH}后天{CW}{0,2}(?:到)?周年日(?:的客户|客户)?'
      - '{SEARCH}后天(?:有)?(?:哪些|哪几位|多少)?客户(?:会|要|将要)?(?:到)?保单周年日(?:吗|么|嘛|的客户|客户)?'
    field: "effAnniversaryDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "day_after_tomorrow"
      format: "MM-dd"
    priority: 9

  # ==================== 证件到期时间 (idValidDate) ====================

  - name: "证件到期时间-精确"
    patterns:
      - '{SEARCH}证件(?:有效期|到期(?:日|时间)?)[为是：:](\.\d{4}-\d{2}-\d{2})(?:的客户|客户)?'
      - '{SEARCH}证件{CW}{0,2}(\d{4})年(\d{1,2})月(\d{1,2})?日?到期(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年(\d{1,2})月(\d{1,2})?日?证件到期(?:的客户|客户)?'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "year_month_day"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9

  - name: "证件到期时间-N天内"
    patterns:
      - '{SEARCH}(\d+)天内{CW}{0,2}(?:证件|身份证)(?:到期|过期)(?:的客户|客户)?'
      - '{SEARCH}(?:证件|身份证){CW}{0,2}(\d+)天内(?:到期|过期)(?:的客户|客户)?'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days_group: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9

  - name: "证件到期时间-已过期"
    patterns:
      - '{SEARCH}(?:证件)(?:有效期)?(?:已过期|已经过期|过期)(?:的客户|客户)?'
      - '{SEARCH}(?:已过期|已经过期|过期)的?(?:证件)(?:有效期)?(?:的客户|客户)?'
    field: "idValidDate"
    operator: "LTE"
    value_type: "date_range_dynamic"
    value:
      date_range: "today_plus_n_days"
      days: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10

  - name: "证件到期时间-近期"
    patterns:
      - '{SEARCH}(?:证件)(?:有效期)?(?:快到期|即将到期|快过期|将到期|即将过期|快过期|近期过期|近期过期)(?:的客户|客户)?'
      - '{SEARCH}(?:证件){CW}{0,2}(?:有效期)?{CW}{0,2}(?:快到期|即将到期|快过期|将到期|即将过期|快过期|近期过期|近期过期)(?:的客户|客户)?'
      - '{SEARCH}(?:快到期|即将到期|快过期|将到期|即将过期|快过期|近期过期|近期过期)的?(?:证件)(?:有效期)?(?:的客户|客户)?'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days: 30
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9

  - name: "证件到期时间-本月"
    patterns:
      - '{SEARCH}(?:本月|这个月|当月){CW}{0,2}(?:证件|身份证)(?:有效期)?(?:到期|过期)(?:的客户|客户)?'
      - '{SEARCH}(?:证件|身份证)(?:有效期|到期(?:日|时间)?){CW}{0,2}在?(?:本月|这个月|当月)(?:的客户|客户)?'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_month"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9

  - name: "证件到期时间-下月"
    patterns:
      - '{SEARCH}下个?月{CW}{0,2}(?:证件|身份证)(?:有效期)?(?:到期|过期)(?:的客户|客户)?'
      - '{SEARCH}(?:证件|身份证)(?:有效期|到期(?:日|时间)?){CW}{0,2}在?下个?月(?:的客户|客户)?'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_month"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9

  - name: "证件到期时间-本周"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:证件|身份证)(?:有效期)?(?:到期|过期)(?:的客户|客户)?'
      - '{SEARCH}(?:证件|身份证)(?:有效期|到期(?:日|时间)?){CW}{0,2}在?(?:本周|这周|这个星期)(?:的客户|客户)?'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9

  - name: "证件到期时间-下周"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:证件|身份证)(?:有效期)?(?:到期|过期)(?:的客户|客户)?'
      - '{SEARCH}(?:证件|身份证)(?:有效期|到期(?:日|时间)?){CW}{0,2}在?(?:下周|下星期|下个星期)(?:的客户|客户)?'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9

  - name: "身份证到期时间-下周"
    patterns:
      - '{SEARCH}身份证(?:有效期)?{CW}{0,2}(?:在)?(?:下周|下星期|下个星期){CW}{0,2}(?:即将|快|将)?(?:到期|过期)(?:的客户|客户)?'
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}身份证(?:有效期)?{CW}{0,2}(?:即将|快|将)?(?:到期|过期)(?:的客户|客户)?'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 1
      format: "yyyy-MM-dd HH:mm:ss"
    extra_conditions:
      - field: "idType"
        operator: "MATCH"
        value: "身份证"
    priority: 11

  - name: "证件到期时间-下下周"
    patterns:
      - '{SEARCH}(?:下下周|下下星期|下下个星期){CW}{0,2}(?:证件|身份证)(?:有效期)?(?:到期|过期)(?:的客户|客户)?'
      - '{SEARCH}(?:证件|身份证)(?:有效期|到期(?:日|时间)?){CW}{0,2}在?(?:下下周|下下星期|下下个星期)(?:的客户|客户)?'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 2
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9

  - name: "证件到期时间-年份之后"
    patterns:
      - '{SEARCH}证件(?:有效期|到期(?:日|时间)?)(?:在)?(\d{4})年之后(?:的客户|客户)?'
    field: "idValidDate"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
    priority: 9

  - name: "证件到期时间-年份之前"
    patterns:
      - '{SEARCH}证件(?:有效期|到期(?:日|时间)?)(?:在)?(\d{4})年之前(?:的客户|客户)?'
    field: "idValidDate"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_end_datetime"
    priority: 9

  - name: "具体证件到期时间-精确"
    patterns:
      - '{SEARCH}(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证)(?:有效期|到期(?:日|时间)?)[为是：:](\.\d{4}-\d{2}-\d{2})(?:的客户|客户)?'
      - '{SEARCH}(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证){CW}{0,2}(\d{4})年(\d{1,2})月(\d{1,2})?日?到期(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年(\d{1,2})月(\d{1,2})?日?(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证)到期(?:的客户|客户)?'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "year_month_day"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    require_paired_field: "idType"

  - name: "具体证件到期时间-N天内"
    patterns:
      - '{SEARCH}(\d+)天内{CW}{0,2}(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证)(?:到期|过期)(?:的客户|客户)?'
      - '{SEARCH}(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证){CW}{0,2}(\d+)天内(?:到期|过期)(?:的客户|客户)?'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days_group: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    require_paired_field: "idType"

  - name: "具体证件到期时间-已过期"
    patterns:
      - '{SEARCH}(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证)(?:有效期)?(?:已过期|已经过期|过期)(?:的客户|客户)?'
      - '{SEARCH}(?:已过期|已经过期|过期)的?(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证)(?:有效期)?(?:的客户|客户)?'
    field: "idValidDate"
    operator: "LTE"
    value_type: "date_range_dynamic"
    value:
      date_range: "today_plus_n_days"
      days: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    require_paired_field: "idType"

  - name: "具体证件到期时间-近期"
    patterns:
      - '{SEARCH}(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证)(?:有效期)?(?:快到期|即将到期|快过期|将到期|即将过期|快过期|近期过期|近期过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证){CW}{0,2}(?:有效期)?{CW}{0,2}(?:快到期|即将到期|快过期|将到期|即将过期|快过期|近期过期|近期过期){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:快到期|即将到期|快过期|将到期|即将过期|快过期|近期过期|近期过期)的?(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证)(?:有效期)?{CUSTOMER_SUFFIX}'
    field: "idValidDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "future_day_window"
      start_days: 1
      end_days: 30
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10

  - name: "具体证件到期时间-年份之后"
    patterns:
      - '{SEARCH}(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证)(?:有效期|到期(?:日|时间)?)(?:在)?(\d{4})年之后{CUSTOMER_SUFFIX}'
    field: "idValidDate"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
    priority: 10
    require_paired_field: "idType"

  - name: "具体证件到期时间-年份之前"
    patterns:
      - '{SEARCH}(?:出生证|身份证|户口本|港澳台居住证|军人证|港澳台证件|护照|外国人居留证)(?:有效期|到期(?:日|时间)?)(?:在)?(\d{4})年之前{CUSTOMER_SUFFIX}'
    field: "idValidDate"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_end_datetime"
    priority: 10
    require_paired_field: "idType"

  # ==================== 缴费期满 (effAppEndDate) ====================

  - name: "缴费期满-本年"
    patterns:
      - '{SEARCH}(?:今年|本年){CW}{0,2}缴费期满(?:的客户|客户)?'
      - '{SEARCH}缴费期满{CW}{0,2}在今年(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "缴费期满-本月"
    patterns:
      - '{SEARCH}本月{CW}{0,2}缴费期满(?:的客户|客户)?'
      - '{SEARCH}缴费期满{CW}{0,2}在本月(?:的客户|客户)?'
      - '{SEARCH}这个?月{CW}{0,2}缴费期满(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_month"
      format: "yyyy-MM-dd"
    priority: 9

  - name: "缴费期满-下个月"
    patterns:
      - '{SEARCH}下个?月{CW}{0,2}缴费期满(?:的客户|客户)?'
      - '{SEARCH}缴费期满{CW}{0,2}在下个?月(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_month"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "缴费期满-上个月口语"
    patterns:
      - '{SEARCH}(?:上个月|上月){CW}{0,4}(?:缴费期满|交费期满)(?:的客户|客户|的人|人|的)?(?:[，,](?:翻翻|看看|查查).*)?'
      - '{SEARCH}(?:缴费期满|交费期满){CW}{0,4}(?:在)?(?:上个月|上月)(?:的客户|客户|的人|人|的)?(?:[，,](?:翻翻|看看|查查).*)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_month"
      format: "yyyy-MM-dd"
    priority: 12
    merge_to_llm: true

  - name: "缴费期满-近期口语"
    patterns:
      - '{SEARCH}(?:快|即将|马上|快要)到期的?(?:这批)?(?:缴费|交费)客户'
      - '{SEARCH}(?:缴费|交费)客户{CW}{0,4}(?:快|即将|马上|快要)到期'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days: 30
      format: "yyyy-MM-dd"
    priority: 12
    merge_to_llm: true

  - name: "缴费期满-N天内"
    patterns:
      - '{SEARCH}(\d+)天内{CW}{0,2}缴费期满(?:的客户|客户)?'
      - '{SEARCH}缴费期满{CW}{0,2}(\d+)天内(?:的客户|客户)?'
      - '{SEARCH}即将缴费期满(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days_group: 1
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "缴费期满-下下个月"
    patterns:
      - '{SEARCH}下下个?月{CW}{0,2}缴费期满(?:的客户|客户)?'
      - '{SEARCH}缴费期满{CW}{0,2}在下下个?月(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "month_offset"
      offset: 2
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "缴费期满-本周"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}缴费期满(?:的客户|客户)?'
      - '{SEARCH}缴费期满{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期)(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "缴费期满-下周"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}缴费期满(?:的客户|客户)?'
      - '{SEARCH}缴费期满{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期)(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 1
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "缴费期满-下下周"
    patterns:
      - '{SEARCH}(?:下下周|下下星期|下下个星期){CW}{0,2}缴费期满(?:的客户|客户)?'
      - '{SEARCH}缴费期满{CW}{0,2}在(?:下下周|下下星期|下下个星期)(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 2
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "缴费期满-今天"
    patterns:
      - '{SEARCH}(?:今天|今日|当天){CW}{0,2}缴费期满(?:的客户|客户)?'
      - '{SEARCH}缴费期满{CW}{0,2}在?(?:今天|今日|当天)(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "today"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "缴费期满-明天"
    patterns:
      - '{SEARCH}(?:明天|明日){CW}{0,2}缴费期满(?:的客户|客户)?'
      - '{SEARCH}缴费期满{CW}{0,2}在?(?:明天|明日)(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "tomorrow"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "缴费期满-后天"
    patterns:
      - '{SEARCH}后天{CW}{0,2}缴费期满(?:的客户|客户)?'
      - '{SEARCH}缴费期满{CW}{0,2}在?后天(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "day_after_tomorrow"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "缴费期满-年份之后"
    patterns:
      - '{SEARCH}缴费期满日?(?:在)?(\d{4})年之后(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "缴费期满-年份之前"
    patterns:
      - '{SEARCH}缴费期满日?(?:在)?(\d{4})年之前(?:的客户|客户)?'
    field: "effAppEndDate"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_end_datetime"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

#  - name: "缴费期满-存在排序口语"
#    patterns:
#      - '{SEARCH}(?:缴费期满|交费期满|满期时间|缴费期满日)(?:从晚到早|从早到晚|升序|降序)?(?:排|排序|排列|排个序|排一排|排排)?'
#      - '.*(?:缴费期满|交费期满|满期时间|缴费期满日).*(?:从晚到早|从早到晚|升序|降序|排|排序|排列).*'
#    field: "effAppEndDate"
#    operator: "EXISTS"
#    value_type: "static"
#    value: ""
#    priority: 12
#    merge_to_llm: true

  - name: "持有综拓产品类别"
    enum_ref: "agentPerspProductType"
    patterns_template:
      - '{SEARCH}(?:综拓|综拓产品|综拓产品类别){position}?{enum}(?:产品)?(?:的客户|客户)?'
      - '{SEARCH}{position}?综拓{enum}(?:产品)?(?:的客户|客户)?'
      - '{SEARCH}综拓产品类别(?:包含|为|是)?{enum}(?:的客户|客户)?'
    field: "agentPerspProductType"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 7
    negation_support: true

  - name: "持有综拓产品类别-未持有"
    enum_ref: "agentPerspProductType"
    patterns_template:
      - '{SEARCH}{negation}{enum}产品?(?:的客户|客户)?'
    field: "agentPerspProductType"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 7

  - name: "持有综拓产品类别-存在"
    patterns:
      - '{SEARCH}(?:有|持有|买了|购买了|配置了|已有|投保了)综拓产品(?!理赔|报案|结案)(?:的客户|客户)?'
      - '{SEARCH}(?:是否|有无)?综拓产品(?!理赔|报案|结案)(?:的客户|客户)?'
    field: "agentPerspProductType"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 11
    merge_to_llm: true

  - name: "持有综拓产品类别-不存在"
    patterns:
      - '{SEARCH}(?:没有|没|未持有|没买|未买|未购买|未配置|不持有)综拓产品(?!理赔|报案|结案)(?:的客户|客户)?'
    field: "agentPerspProductType"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 11
    merge_to_llm: true

  # ==================== 综拓理赔 (occurPassPayRegst) ====================

  - name: "综拓理赔-报案"
    patterns:
      - '{SEARCH}综拓{CW}{0,2}理赔报案(?:的客户|客户)?'
      - '{SEARCH}综拓理赔报案(?:的客户|客户)?'
      - '{SEARCH}综拓理赔状态(?:为|是)?综拓理赔报案(?:的客户|客户)?'
      - '{SEARCH}有过?综拓{CW}{0,2}产品?{CW}{0,2}理赔报案(?:的客户|客户)?'
      - '{SEARCH}综拓{CW}{0,2}产品?{CW}{0,2}理赔报案(?:的客户|客户)?'
      - '{SEARCH}(?:有{CW}{0,12})?综拓(?:产品)?{CW}{0,12}(?:报过案|已报案|报案过){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:报过案|已报案|报案过)(?:的)?综拓(?:产品)?{CUSTOMER_SUFFIX}'
    field: "occurPassPayRegst"
    operator: "MATCH"
    value_type: "static"
    value: "综拓理赔报案"
    priority: 12

  - name: "综拓理赔-结案"
    patterns:
      - '{SEARCH}综拓{CW}{0,2}理赔结案(?:的客户|客户)?'
      - '{SEARCH}综拓理赔结案(?:的客户|客户)?'
      - '{SEARCH}综拓理赔状态(?:为|是)?综拓理赔结案(?:的客户|客户)?'
    field: "occurPassPayRegst"
    operator: "MATCH"
    value_type: "static"
    value: "综拓理赔结案"
    priority: 12

  - name: "综拓理赔-存在"
    patterns:
      - '{SEARCH}有(?:过)?综拓{CW}{0,2}理赔(?:记录)?(?:的客户|客户)?'
      - '{SEARCH}有(?:过)?综拓{CW}{0,2}产品?{CW}{0,2}理赔(?:记录)?(?:的客户|客户)?'
      - '{SEARCH}有综拓理赔记录(?:的客户|客户)?'
    field: "occurPassPayRegst"
    operator: "EXISTS"
    value_type: ""
    priority: 12

  # ==================== 保单到期时间 (validSinsMatuDateTime) ====================

  - name: "保单到期时间-区间天数"
    patterns:
      - '{SEARCH}(?:(\d+)[-到至](\d+)天内)到期(?:的)?(?:短期?保单|客户|保单)?'
      - '{SEARCH}到期{CW}{0,2}(?:(\d+)[-到至](\d+)天内)'
    field: "validSinsMatuDateTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "future_day_window"
      start_days_group: 1
      end_days_group: 2
      format: "yyyy-MM-dd"
    priority: 8

  - name: "保单到期时间-年份之后"
    patterns:
      - '{SEARCH}保单到期日?(?:在)?(\d{4})年之后(?:的客户|客户)?'
    field: "validSinsMatuDateTime"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
      format: "yyyy-MM-dd"
    priority: 9

  - name: "保单到期时间-年份之前"
    patterns:
      - '{SEARCH}保单到期日?(?:在)?(\d{4})年之前(?:的客户|客户)?'
    field: "validSinsMatuDateTime"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_end_datetime"
      format: "yyyy-MM-dd"
    priority: 9

  - name: "保单到期时间-年月"
    patterns:
      - '{SEARCH}保单到期(?:时间|日)?(?:在)?(\d{4}年\d{1,2}月)(?:的客户|客户|保单)?'
      - '{SEARCH}(\d{4}年\d{1,2}月){CW}{0,2}保单到期(?:的客户|客户|保单)?'
    field: "validSinsMatuDateTime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_month_cn_range"
    priority: 10
    merge_to_llm: true

  - name: "保单到期时间-N天内"
    patterns:
      - '{SEARCH}(?:未来|接下来|之后)?(\d+)天(?:内|里)?{CW}{0,2}(?:保单|寿险保单|保险)(?:即将)?到期(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单|寿险保单|保险)到期(?:时间|日)?{CW}{0,2}在?(?:未来|接下来|之后)?(\d+)天(?:内|里)?(?:的客户|客户|保单)?'
      - '{SEARCH}(?:未来|接下来|之后)?(\d+)天(?:内|里)?{CW}{0,2}到期的?(?:保单|寿险保单)(?:客户|的客户)?'
    field: "validSinsMatuDateTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days_group: 1
      format: "yyyy-MM-dd"
    priority: 10
    merge_to_llm: true

  - name: "保单到期时间-本月"
    patterns:
      - '{SEARCH}(?:本月|这个月|当月){CW}{0,2}(?:保单|寿险保单|保险)(?:即将)?到期(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单|寿险保单|保险)到期(?:时间|日)?{CW}{0,2}在?(?:本月|这个月|当月)(?:的客户|客户|保单)?'
    field: "validSinsMatuDateTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_month"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "保单到期时间-下月"
    patterns:
      - '{SEARCH}下个?月{CW}{0,2}(?:保单|寿险保单|保险)(?:即将)?到期(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单|寿险保单|保险)到期(?:时间|日)?{CW}{0,2}在?下个?月(?:的客户|客户|保单)?'
    field: "validSinsMatuDateTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_month"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "保单到期时间-近期口语"
    patterns:
      - '{SEARCH}(?:快|即将|马上|快要)到期的?(?:这批)?(?:保单|寿险保单|保险)(?:有哪些|有谁|名单)?(?:[，,](?:提前)?(?:翻翻|看看|查查).*)?'
      - '{SEARCH}(?:保单|寿险保单|保险){CW}{0,4}(?:快|即将|马上|快要)到期(?:的客户|客户|有哪些|有谁)?(?:[，,](?:提前)?(?:翻翻|看看|查查).*)?'
    field: "validSinsMatuDateTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days: 30
      format: "yyyy-MM-dd"
    priority: 12
    merge_to_llm: true

  - name: "保单到期时间-下月底"
    patterns:
      - '{SEARCH}下个?月(?:底|末){CW}{0,2}(?:保单|寿险保单|保险)(?:即将)?到期(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单|寿险保单|保险)(?:到期(?:时间|日)?)?{CW}{0,2}在?下个?月(?:底|末)(?:到期)?(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单|寿险保单|保险){CW}{0,2}下个?月(?:底|末)(?:即将)?到期(?:的客户|客户|保单)?'
    field: "validSinsMatuDateTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_month_end"
      format: "yyyy-MM-dd"
    priority: 11
    merge_to_llm: true

  - name: "保单到期时间-本周"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:保单|寿险保单|保险)(?:即将)?到期(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单|寿险保单|保险)到期(?:时间|日)?{CW}{0,2}在?(?:本周|这周|这个星期)(?:的客户|客户|保单)?'
    field: "validSinsMatuDateTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "保单到期时间-下周"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:保单|寿险保单|保险)(?:即将)?到期(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单|寿险保单|保险)到期(?:时间|日)?{CW}{0,2}在?(?:下周|下星期|下个星期)(?:的客户|客户|保单)?'
    field: "validSinsMatuDateTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 1
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "保单到期时间-下下周"
    patterns:
      - '{SEARCH}(?:下下周|下下星期|下下个星期){CW}{0,2}(?:保单|寿险保单|保险)(?:即将)?到期(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单|寿险保单|保险)到期(?:时间|日)?{CW}{0,2}在?(?:下下周|下下星期|下下个星期)(?:的客户|客户|保单)?'
    field: "validSinsMatuDateTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 2
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "保单-已到期"
    patterns:
      - '{SEARCH}(?:保单|保险)(?:已经?|已)到期(?:的客户|客户|保单)?'
      - '{SEARCH}到期(?:的客户|客户|保单)?'
    field: "validSinsMatuDateTime"
    operator: "LTE"
    value_type: "date_range_dynamic"
    value:
      date_range: "today_plus_n_days"
      days: 0
      format: "yyyy-MM-dd"
    priority: 10

  # ==================== 准客来源 (pcustSourcType) ====================

  - name: "准客来源-持有"
    enum_ref: "pcustSourcType"
    patterns_template:
      - '{SEARCH}(?<![没无非])(?<!不是){enum}(?:的客户|客户)?'
      - '{SEARCH}(?<![没无非])(?<!不是){enum}准客(?:的客户|客户)?'
      - '{SEARCH}准客来源(?:包含|为|是)?{enum}准客(?:的客户|客户)?'
      - '{SEARCH}准客来源(?:包含|为|是)?{enum}(?:的客户|客户)?'
      - '{SEARCH}{position}?{enum}(?:产品)?(?:的客户|客户)?'
    field: "pcustSourcType"
    operator: "CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 10
    negation_support: true
    merge_to_llm: true

  - name: "准客来源-未持有"
    enum_ref: "pcustSourcType"
    patterns_template:
      - '{SEARCH}(?:不包含|不为|不是|非){enum}(?:的客户|客户)?'
      - '{SEARCH}准客来源(?:不包含|不为|不是|非){enum}准客(?:的客户|客户)?'
      - '{SEARCH}准客来源(?:不包含|不为|不是|非){enum}(?:的客户|客户)?'
    field: "pcustSourcType"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 10
    negation_support: true
    merge_to_llm: true

  - name: "准客来源-简称"
    patterns:
      - '{SEARCH}准客来源(?:为|是|包含|：|:)?(综拓|O2O|o2o|意健险)(?:的客户|客户)?'
      - '{SEARCH}(综拓|O2O|o2o|意健险)(?:来源)?准客(?:的客户|客户)?'
      - '{SEARCH}来源(?:为|是|包含|：|:)?(综拓|O2O|o2o|意健险)(?:的)?准客(?:的客户|客户)?'
    field: "pcustSourcType"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "ensure_suffix"
      suffix: "准客"
    priority: 10
    merge_to_llm: true

  # ==================== 有效短险保单 (validSinsPol) ====================

  - name: "有效短险保单-持有"
    enum_ref: "validSinsPol"
    patterns_template:
      - '{SEARCH}{position}?{enum}(?:短险|有效短险保单)(?:的客户|客户)?'
      - '{SEARCH}有效短险保单(?:包含|为|是)?{enum}(?:的客户|客户)?'
      - '{SEARCH}(?<![没无非未])(?<!没有){enum}(?:客户|的客户|名单|的人|人)?'
    field: "validSinsPol"
    operator: "CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 10
    negation_support: true
    merge_to_llm: true

  - name: "有效短险保单-未持有"
    enum_ref: "validSinsPol"
    patterns_template:
      - '{SEARCH}{negation}{enum}(?:短险|有效短险保单)(?:的客户|客户)?'
      - '{SEARCH}(?:没有|无|未持有|未购买|没买|非){enum}(?:客户|的客户|名单|的人|人)'
    field: "validSinsPol"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 11
    merge_to_llm: true

#  # ==================== 居家达标客户等级 (jujiaClientGrade) ====================
#
#  - name: "居家达标客户等级"
#    enum_ref: "jujiaClientGrade"
#    patterns_template:
#      - '{SEARCH}居家{CW}{0,2}{enum}(?!{CW}{0,2}(?:以上|及以上|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#      - '{SEARCH}居家等级(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#      - '{SEARCH}(?<![没无非])(?<!不是){enum}(?!{CW}{0,2}(?:以上|及以上|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#    field: "jujiaClientGrade"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 7
#    merge_to_llm: true
#
#  - name: "居家达标客户等级-以上"
#    enum_ref: "jujiaClientGrade"
#    patterns_template:
#      - '{SEARCH}(?<![没无非])(?<!不是)居家{CW}{0,2}{enum}以上(?:的客户|客户)?'
#      - '{SEARCH}(?<![没无非])(?<!不是){enum}居家以上(?:的客户|客户)?'
#    field: "jujiaClientGrade"
#    operator: "CONTAINS"
#    value_type: "enum_gt"
#    value:
#      group: 1
#    priority: 8
#    merge_to_llm: true
#
#  - name: "居家达标客户等级-及以上"
#    enum_ref: "jujiaClientGrade"
#    patterns_template:
#      - '{SEARCH}(?<![没无非])(?<!不是)居家{CW}{0,2}{enum}及以上(?:的客户|客户)?'
#      - '{SEARCH}(?<![没无非])(?<!不是){enum}居家及以上(?:的客户|客户)?'
#    field: "jujiaClientGrade"
#    operator: "CONTAINS"
#    value_type: "enum_gte"
#    value:
#      group: 1
#    priority: 8
#    merge_to_llm: true
#
#  - name: "居家达标客户等级-以下"
#    enum_ref: "jujiaClientGrade"
#    patterns_template:
#      - '{SEARCH}(?<![没无非])(?<!不是)居家{CW}{0,2}{enum}以下(?:的客户|客户)?'
#    field: "jujiaClientGrade"
#    operator: "CONTAINS"
#    value_type: "enum_lt"
#    value:
#      group: 1
#    priority: 8
#    merge_to_llm: true
#
#  - name: "居家达标客户等级-及以下"
#    enum_ref: "jujiaClientGrade"
#    patterns_template:
#      - '{SEARCH}(?<![没无非])(?<!不是)居家{CW}{0,2}{enum}及以下(?:的客户|客户)?'
#    field: "jujiaClientGrade"
#    operator: "CONTAINS"
#    value_type: "enum_lte"
#    value:
#      group: 1
#    priority: 8
#    merge_to_llm: true
#
#  - name: "居家达标-泛称"
#    patterns:
#      - '{SEARCH}(?<![没无非])(?<!不是)(?:居家客户|居家养老客户|居家达标|居家达标客户|居家会员|居家会员客户|有居家权益的客户|居家)(?:的客户|客户|有哪些|有哪些人)?'
#      - '{SEARCH}(?<![没无非])(?<!不是)达标的居家(?:客户|会员)(?:的客户|客户|有哪些|有哪些人)?'
#    field: "jujiaClientGrade"
#    operator: "CONTAINS"
#    value_type: "static"
#    value:
#      - "v0.5"
#      - "v1"
#      - "v1.5"
#      - "v2"
#      - "v2.5"
#      - "v3"
#    priority: 9
#    merge_to_llm: true
#
#  # ==================== 康养达标客户等级 (kangyangClientGrade) ====================
#
#  - name: "康养达标-泛称"
#    patterns:
#      - '{SEARCH}(?<![没无非])(?<!不是)(?:康养客户|康养达标客户|康养会员|康养会员客户|有康养权益的客户|康养达标)(?:的客户|客户|有哪些|有哪些人)?'
#    field: "kangyangClientGrade"
#    operator: "CONTAINS"
#    value_type: "static"
#    value:
#      - "逸享会员"
#      - "逸享PLUS会员"
#      - "颐享家会员"
#      - "臻享会员V1"
#      - "臻享会员V2"
#      - "臻享会员V3"
#    priority: 9
#    merge_to_llm: true
#
#  - name: "康养达标客户等级"
#    enum_ref: "kangyangClientGrade"
#    patterns_template:
#      - '{SEARCH}康养{CW}{0,2}{enum}(?!{CW}{0,2}(?:以上|及以上|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#      - '{SEARCH}康养等级(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#      - '{SEARCH}(?<![没无非])(?<!不是){enum}(?!{CW}{0,2}(?:以上|及以上|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#    field: "kangyangClientGrade"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 7
#    merge_to_llm: true
#
#  - name: "康养达标客户等级-以上"
#    enum_ref: "kangyangClientGrade"
#    patterns_template:
#      - '{SEARCH}康养{CW}{0,2}{enum}以上(?:的客户|客户)?'
#      - '{SEARCH}{enum}以上(?:的客户|客户)?'
#    field: "kangyangClientGrade"
#    operator: "CONTAINS"
#    value_type: "enum_gt"
#    value:
#      group: 1
#    priority: 8
#    merge_to_llm: true
#
#  - name: "康养达标客户等级-及以上"
#    enum_ref: "kangyangClientGrade"
#    patterns_template:
#      - '{SEARCH}康养{CW}{0,2}{enum}及以上(?:的客户|客户)?'
#      - '{SEARCH}{enum}及以上(?:的客户|客户)?'
#    field: "kangyangClientGrade"
#    operator: "CONTAINS"
#    value_type: "enum_gte"
#    value:
#      group: 1
#    priority: 8
#    merge_to_llm: true
#
#  - name: "康养达标客户等级-以下"
#    enum_ref: "kangyangClientGrade"
#    patterns_template:
#      - '{SEARCH}康养{CW}{0,2}{enum}以下(?:的客户|客户)?'
#    field: "kangyangClientGrade"
#    operator: "CONTAINS"
#    value_type: "enum_lt"
#    value:
#      group: 1
#    priority: 8
#    merge_to_llm: true
#
#  - name: "康养达标客户等级-及以下"
#    enum_ref: "kangyangClientGrade"
#    patterns_template:
#      - '{SEARCH}康养{CW}{0,2}{enum}及以下(?:的客户|客户)?'
#      - '{SEARCH}{enum}及以下(?:的客户|客户)?'
#    field: "kangyangClientGrade"
#    operator: "CONTAINS"
#    value_type: "enum_lte"
#    value:
#      group: 1
#    priority: 8
#    merge_to_llm: true
#
#  # ==================== 安有护等级 (zhenxiangRunEquityGrade) ====================
#
#  - name: "安有护等级"
#    enum_ref: "zhenxiangRunEquityGrade"
#    patterns_template:
#      - '{SEARCH}(?<![没无非])(?<!不是)安有护{CW}{0,2}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#      - '{SEARCH}安有护权益(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#      - '{SEARCH}安有护权益等级(?:为|是)?(?:安有护)?{CW}{0,2}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#      - '{SEARCH}(?<![没无非])(?<!不是){enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))安有护'
#    field: "zhenxiangRunEquityGrade"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 7
#    merge_to_llm: true
#
#  - name: "安有护-持有"
#    patterns:
#      - '{SEARCH}(?<![没无非])(?<!不是)(?:安有护客户|安有护达标客户|安有护会员|有安有护权益的客户|安有护)(?:的客户|客户)?'
#    field: "zhenxiangRunEquityGrade"
#    operator: "CONTAINS"
#    value_type: "static"
#    value:
#      - "安有护(国际版)"
#      - "安有护(国内版)"
#    priority: 9
#    merge_to_llm: true
#
#  # ==================== 臻享家族等级 (zxjyEquityGrade) ====================
#
#  - name: "臻享家医客户-预达标和已达标"
#    patterns:
#      - '{SEARCH}(?:臻享家医|家医)(?:客户|名单|客群|人群)(?:都)?(?:有哪些|有谁|名单)?(?:的客户|客户|的人|人)?'
#      - '{SEARCH}(?:哪些|哪几位|谁是|有没有|是否有|有无)(?:臻享家医|家医)(?:客户|名单|客群|人群)(?:的客户|客户|的人|人)?'
#      - '{SEARCH}(?:臻享家医|家医)(?:达标客户|达标名单|达标客群|达标人群)(?:有哪些|有谁|名单)?(?:的客户|客户|的人|人)?'
#      - '{SEARCH}(?:哪些|哪几位|谁是|有没有|是否有|有无)(?:臻享家医|家医)(?:达标客户|达标名单|达标客群|达标人群)(?:的客户|客户|的人|人)?'
#      - '{SEARCH}(?:臻享家医|家医)(?:权益等级)?(?:为|是|包含|包括)?(?:预达标|已达标)(?:和|或|及|与|、|，|,)(?:预达标|已达标)(?:的客户|客户|名单|的人|人)?'
#      - '{SEARCH}(?:预达标|已达标)(?:和|或|及|与|、|，|,)(?:预达标|已达标)(?:的)?(?:臻享家医|家医)(?:客户|名单|客群|人群)?(?:的客户|客户|的人|人)?'
#      - '{SEARCH}(?:臻享家医|家医)(?:预达标|已达标)(?:和|或|及|与|、|，|,)(?:预达标|已达标)(?:客户|名单|客群|人群)?(?:的客户|客户|的人|人)?'
#    field: "zxjyEquityGrade"
#    operator: "CONTAINS"
#    value_type: "static"
#    value:
#      - "预达标"
#      - "已达标"
#    priority: 9
#    merge_to_llm: false
#
#  - name: "臻享家族等级"
#    enum_ref: "zxjyEquityGrade"
#    patterns_template:
#      - '{SEARCH}臻享家医?{CW}{0,2}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#      - '{SEARCH}(?:臻享家医权益|家医权益)(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#      - '{SEARCH}(?:臻享家医权益等级|家医权益等级)(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
#      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))臻享家医?(?:客户)?'
#    field: "zxjyEquityGrade"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 7
#    merge_to_llm: true

  # ==================== investable_assets（可投资产） ====================

  - name: "家庭成员关系-有"
    enum_ref: "familyInfo.familyrelation"
    patterns_template:
      - '{SEARCH}(?<![没无])(?:有|家有|家里有|家中有|育有){enum}(?:的客户|客户)?'
    field: "familyInfo.familyrelation"
    operator: "CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 10

  - name: "家庭成员关系-老人"
    patterns:
      - '{SEARCH}(?:家里有|家中有|家有|有|家里)老人(?:的客户|客户|的)?'
      - '{SEARCH}(?:家里老人|有老人|家里有老人)(?:的客户|客户|的)?'
      - '{SEARCH}(?:家里有|家中有|家有|有|家里)老人(?:的(?:客户)?|客户)?'
      - '{SEARCH}(?:家里老人|有老人|家里有老人)(?:的(?:客户)?|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "static"
    value: 55
    priority: 11

  - name: "家庭成员关系-无"
    enum_ref: "familyInfo.familyrelation"
    patterns_template:
      - '{SEARCH}(?:无|没有){enum}(?:的客户|客户)?'
    field: "familyInfo.familyrelation"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 10
    merge_to_llm: true

  - name: "家庭成员关系-显式包含"
    enum_ref: "familyInfo.familyrelation"
    patterns_template:
      - '{SEARCH}(?:家庭成员关系|成员关系)(?:包含|有|是|为)?{enum}(?:的客户|客户)?'
    field: "familyInfo.familyrelation"
    operator: "CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 11

  - name: "有儿有女-关系推断"
    patterns:
      - '{SEARCH}家里有(?:有儿有女|有儿子和女儿|既有儿子又有女儿)(?:的客户|客户)?'
    field: "familyInfo.familyclientsex"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "男"
      - "女"
    priority: 11
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "男孩-关系推断"
    patterns:
      - '{SEARCH}(?:家里有|有)(?:男孩|儿子|男娃)(?:的客户|客户)?'
    field: "familyInfo.familyclientsex"
    operator: "MATCH"
    value_type: "static"
    value: "男"
    priority: 11
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "女孩-关系推断"
    patterns:
      - '{SEARCH}(?:家里有|有)(?:女孩|女儿|女娃|闺女)(?:的客户|客户)?'
    field: "familyInfo.familyclientsex"
    operator: "MATCH"
    value_type: "static"
    value: "女"
    priority: 11
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "家有未成年女儿"
    patterns:
      - '{SEARCH}家里有未成年女儿(?:的客户|客户)?'
    field: "familyInfo.familyclientsex"
    operator: "MATCH"
    value_type: "static"
    value: "女"
    priority: 12
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientage"
        operator: "LTE"
        value: 17

  - name: "家里老人-年龄"
    patterns:
      - '{SEARCH}家里老人(\d+)周?岁以上(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: ["父母", "(外)祖父母"]

  - name: "家里老人-出生年份之前"
    patterns:
      - '{SEARCH}家里老人是(\d{4})年前出生(?:的客户|客户)?'
      - '{SEARCH}家里老人是(\d{4})年之前出生(?:的客户|客户)?'
    field: "familyInfo.familyclientbirthday"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_end_datetime"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 12
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: ["父母", "(外)祖父母"]

  - name: "子女-关系推断"
    patterns:
      - '{SEARCH}(子女|儿子|女儿|孩子|小孩|小朋友|娃|小娃)\d+[-~到]?\d*周?岁(?:的客户|客户)?'
      - '{SEARCH}(子女|儿子|女儿|孩子|小孩|小朋友|娃|小娃)(?:在[上读]?|上|读)?(?:幼儿园|学前班|小学|初中|高中|大学|本科|专科)(?:的客户|客户)?'
      - '{SEARCH}(子女|儿子|女儿|孩子|小孩|小朋友|娃|小娃)(?:未成年|没成年|已成年|成年)(?:的客户|客户)?'
    field: "familyInfo.familyrelation"
    operator: "CONTAINS"
    value_type: "static"
    value: ["子女"]
    priority: 9

  # ==================== 父母年龄 (family_members.age) ====================

  - name: "父母-关系推断"
    patterns:
      - '{SEARCH}(父母|爸妈|父亲|母亲|爸爸|妈妈)\d+[-~到]?\d*周?岁(?:的客户|客户)?'
      - '{SEARCH}(父母|爸妈|父亲|母亲|爸爸|妈妈)(?:以上|以下|大于|小于|超过|不超过)\d+岁(?:的客户|客户)?'
    field: "familyInfo.familyrelation"
    operator: "CONTAINS"
    value_type: "static"
    value: ["父母"]
    priority: 9

  # ==================== 家庭成员属性基础规则（统一引擎，供 composite_rules 引用）====================
  # 设计原则：
  #   1. value_mappings 将"孩子/老婆/妈妈"等预处理归一化为标准枚举值"子女/配偶/父母"
  #   2. 成员关系词-捕获 用 enum_ref 一条规则覆盖所有关系类型，动态捕获关系值
  #   3. 属性规则加 require_paired_field 安全锁：单独触发时丢弃，
  #      必须由 composite_rules 同时输出 relationship 才有效

  - name: "成员出生日期-年份之前-通用"
    patterns:
      - '{SEARCH}(?:家庭成员出生日期|成员出生日期)(?:在)?(\d{4})年之前(?:的客户|客户)?'
    field: "familyInfo.familyclientbirthday"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
      format: "yyyy-MM-dd HH:mm:ss"
    require_paired_field: "familyInfo.familyrelation"
    priority: 11

  - name: "家属生日-下个月"
    patterns:
      - '{SEARCH}(?:下个月|下月){CW}{0,4}(?:家属|家庭成员|家里人)(?:要|会)?(?:过)?生日(?:的客户|客户|的人|人|的)?(?:[，,](?:提前)?(?:准备|看看|查查).*)?'
      - '{SEARCH}(?:家属|家庭成员|家里人)(?:的)?生日{CW}{0,4}(?:在)?(?:下个月|下月)(?:的客户|客户|的人|人)?'
    field: "familyInfo.familyclientbirthday"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_month"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 12
    merge_to_llm: true

  - name: "家属生日-存在排序口语"
    patterns:
      - '{SEARCH}(?:家属|家庭成员|家里人)(?:的)?(?:生日|出生日期)(?:从晚到早|从早到晚|升序|降序)?(?:排|排序|排列|排一下|排排)?'
    field: "familyInfo.familyclientbirthday"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 12
    merge_to_llm: true

  - name: "成员出生日期-年份之后-通用"
    patterns:
      - '{SEARCH}(?:家庭成员出生日期|成员出生日期)(?:在)?(\d{4})年之后(?:的客户|客户)?'
    field: "familyInfo.familyclientbirthday"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
      format: "yyyy-MM-dd HH:mm:ss"
    require_paired_field: "familyInfo.familyrelation"
    priority: 11

  - name: "成员出生日期-日期之前-通用"
    patterns:
      - '{SEARCH}(?:成员出生日|成员出生日期|生日)(?:小于|早于|<|低于)(\d{4}年\d{1,2}月\d{1,2}[号日])(?:的客户|客户)?'
    field: "familyInfo.familyclientbirthday"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "chinese_date_to_datetime"
      end_of_day: false
      format: "yyyy-MM-dd"
    require_paired_field: "familyInfo.familyrelation"
    priority: 11

  - name: "成员出生日期-日期之后-通用"
    patterns:
      - '{SEARCH}(?:成员出生日|成员出生日期|生日)(?:大于|晚于|>|高于)(\d{4}年\d{1,2}月\d{1,2}[号日])(?:的客户|客户)?'
    field: "familyInfo.familyclientbirthday"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "chinese_date_to_datetime"
      end_of_day: true
      format: "yyyy-MM-dd"
    require_paired_field: "familyInfo.familyrelation"
    priority: 11

  - name: "子女出生日期-日期之前-通用"
    patterns:
      - '{SEARCH}(?:子女出生日|子女出生日期|子女生日)(?:小于|早于|<|低于)(\d{4}年\d{1,2}月\d{1,2}[号日])(?:的客户|客户)?'
    field: "familyInfo.familyclientbirthday"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "chinese_date_to_datetime"
      end_of_day: false
      format: "yyyy-MM-dd"
    priority: 11
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "子女出生日期-日期之后-通用"
    patterns:
      - '{SEARCH}(?:子女出生日|子女出生日期|子女生日)(?:大于|晚于|>|高于)(\d{4}年\d{1,2}月\d{1,2}[号日])(?:的客户|客户)?'
    field: "familyInfo.familyclientbirthday"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "chinese_date_to_datetime"
      end_of_day: true
      format: "yyyy-MM-dd"
    require_paired_field: "familyInfo.familyrelation"
    priority: 11
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  # ==================== 家庭成员年龄 (familyInfo.familyclientage) ====================
  # 注意：最终返回前会自动转换为 familyInfo.familyclientbirthday 日期范围

  - name: "成员年龄-及以上-通用"
    patterns:
      - '{SEARCH}(?:家庭成员年龄|成员年龄)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
      - '{SEARCH}(?:家庭成员年龄|成员年龄)(\d+)岁?及?以上(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    require_paired_field: "familyInfo.familyrelation"
    priority: 11
    merge_to_llm: true

  - name: "成员年龄-以上-通用"
    patterns:
      - '{SEARCH}(?:家庭成员年龄|成员年龄)(?:高于|超过|大于|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    require_paired_field: "familyInfo.familyrelation"
    priority: 11
    merge_to_llm: true

  - name: "成员年龄-及以下-通用"
    patterns:
      - '{SEARCH}(?:家庭成员年龄|成员年龄)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
      - '{SEARCH}(?:家庭成员年龄|成员年龄)(\d+)岁?及?以下(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    require_paired_field: "familyInfo.familyrelation"
    priority: 11
    merge_to_llm: true

  - name: "成员年龄-以下-通用"
    patterns:
      - '{SEARCH}(?:家庭成员年龄|成员年龄)(?:小于|低于|<)(\d+)岁?(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    require_paired_field: "familyInfo.familyrelation"
    priority: 11
    merge_to_llm: true

  - name: "成员年龄-范围-通用"
    patterns:
      - '{SEARCH}(?:家庭成员年龄|成员年龄)(?:在)?(\d+)[-~到至](\d+)周?岁之间?(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "range"
    value:
      min_group: 1
      max_group: 2
      transform: "int"
    require_paired_field: "familyInfo.familyrelation"
    priority: 11
    merge_to_llm: true

  - name: "子女年龄-范围"
    patterns:
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)(?:在)?(\d+)[-~到至](\d+)周?岁(?:之间)?(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "range"
    value:
      min_group: 1
      max_group: 2
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

#  - name: "子女年龄-存在排序口语"
#    patterns:
#      - '{SEARCH}(?:家中|家里|家有|有)?(?:子女|孩子|小孩|小朋友|娃|小娃)(?:大|大的|年龄大|年龄高)(?:的)?(?:那些|这些|客户|人)?(?:从大到小|从高到低|降序|升序)?(?:看|看看|排|排序|排列|排排)?'
#      - '{SEARCH}(?:子女年龄|孩子年龄|小孩年龄|家属年龄)(?:从大到小|从高到低|降序|升序)?(?:排|排序|排列|排排)?'
#      - '.*(?:子女|孩子|小孩|小朋友|娃|小娃).*(?:大|年龄大|年龄高|从大到小|从高到低|降序|升序).*'
#      - '.*(?:子女年龄|孩子年龄|小孩年龄|家属年龄).*(?:从大到小|从高到低|降序|升序|排|排序|排列).*'
#    field: "familyInfo.familyclientage"
#    operator: "EXISTS"
#    value_type: "static"
#    value: ""
#    priority: 12
#    merge_to_llm: true
#    extra_conditions:
#      - field: "familyInfo.familyrelation"
#        operator: "CONTAINS"
#        value: "子女"

  - name: "女儿年龄-范围"
    patterns:
      - '{SEARCH}(?:女儿|闺女|女娃|女娃娃|女宝)(\d+)[-~到至](\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "range"
    value:
      min_group: 1
      max_group: 2
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "儿子年龄-范围"
    patterns:
      - '{SEARCH}(?:儿子|男娃|男宝|男娃|男娃娃)(\d+)[-~到至](\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "range"
    value:
      min_group: 1
      max_group: 2
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "子女年龄-及以上"
    patterns:
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "子女年龄-以上"
    patterns:
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "女儿年龄-及以上"
    patterns:
      - '{SEARCH}(?:女儿|闺女|女娃|女娃娃|女宝)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:女儿|闺女|女娃|女娃娃|女宝)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "女儿年龄-以上"
    patterns:
      - '{SEARCH}(?:女儿|闺女|女娃|女娃娃|女宝)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "儿子年龄-及以上"
    patterns:
      - '{SEARCH}(?:儿子|男娃|男宝|男娃|男娃娃)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:儿子|男娃|男宝|男娃|男娃娃)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "儿子年龄-以上"
    patterns:
      - '{SEARCH}(?:儿子|男娃|男宝|男娃|男娃娃)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "父母年龄-及以上"
    patterns:
      - '{SEARCH}(?:父母|双亲|爸妈)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:父母|双亲|爸妈)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"

  - name: "父母年龄-以上"
    patterns:
      - '{SEARCH}(?:父母|双亲|爸妈)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"

  - name: "父亲年龄-及以上"
    patterns:
      - '{SEARCH}(?:爸爸|父亲)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:爸爸|父亲)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "父亲年龄-以上"
    patterns:
      - '{SEARCH}(?:爸爸|父亲)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "母亲年龄-及以上"
    patterns:
      - '{SEARCH}(?:母亲|妈妈)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:母亲|妈妈)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "母亲年龄-以上"
    patterns:
      - '{SEARCH}(?:母亲|妈妈)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "配偶年龄-及以上"
    patterns:
      - '{SEARCH}(?:配偶)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:配偶)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"

  - name: "配偶年龄-以上"
    patterns:
      - '{SEARCH}(?:配偶)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"

  - name: "妻子年龄-及以上"
    patterns:
      - '{SEARCH}(?:老婆|妻子|夫人)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:老婆|妻子|夫人)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "妻子年龄-以上"
    patterns:
      - '{SEARCH}(?:老婆|妻子|夫人)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "丈夫年龄-及以上"
    patterns:
      - '{SEARCH}(?:老公|丈夫)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:老公|丈夫)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "丈夫年龄-以上"
    patterns:
      - '{SEARCH}(?:老公|丈夫)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "兄弟姐妹年龄-及以上"
    patterns:
      - '{SEARCH}(?:兄弟|姐妹)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:兄弟|姐妹)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"

  - name: "兄弟姐妹年龄-以上"
    patterns:
      - '{SEARCH}(?:兄弟|姐妹)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"

  - name: "兄弟年龄-及以上"
    patterns:
      - '{SEARCH}(?:兄弟|哥哥|弟弟)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:兄弟|哥哥|弟弟)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "兄弟年龄-以上"
    patterns:
      - '{SEARCH}(?:兄弟|哥哥|弟弟)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "姐妹年龄-及以上"
    patterns:
      - '{SEARCH}(?:姐妹|姐姐|妹妹)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:姐妹|姐姐|妹妹)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "姐妹年龄-以上"
    patterns:
      - '{SEARCH}(?:姐妹|姐姐|妹妹)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "外祖父母年龄-及以上"
    patterns:
      - '{SEARCH}(?:祖父母|外祖父母)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:祖父母|外祖父母)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"

  - name: "外祖父母年龄-以上"
    patterns:
      - '{SEARCH}(?:祖父母|外祖父母)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"

  - name: "外祖母年龄-及以上"
    patterns:
      - '{SEARCH}(?:外祖母|祖母|奶奶|外婆)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:外祖母|祖母|奶奶|外婆)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "外祖母年龄-以上"
    patterns:
      - '{SEARCH}(?:外祖母|祖母|奶奶|外婆)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "外祖父年龄-及以上"
    patterns:
      - '{SEARCH}(?:外祖父|祖父|爷爷|外公)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:外祖父|祖父|爷爷|外公)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "外祖父年龄-以上"
    patterns:
      - '{SEARCH}(?:外祖父|祖父|爷爷|外公)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "外孙子女年龄-及以上"
    patterns:
      - '{SEARCH}(?:孙子孙女|外孙子外孙女|外孙子女|孙子女)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:孙子孙女|外孙子外孙女|外孙子女|孙子女)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"

  - name: "外孙子女年龄-以上"
    patterns:
      - '{SEARCH}(?:孙子孙女|外孙子外孙女|外孙子女|孙子女)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"

  - name: "外孙女年龄-及以上"
    patterns:
      - '{SEARCH}(?:孙女|外孙女)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:孙女|外孙女)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "外孙女年龄-以上"
    patterns:
      - '{SEARCH}(?:孙女|外孙女)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "外孙子年龄-及以上"
    patterns:
      - '{SEARCH}(?:孙子|外孙)(\d+)周?岁及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:孙子|外孙)(?:大于等于|大于或等于|不少于|不低于|>=|≥)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "外孙子年龄-以上"
    patterns:
      - '{SEARCH}(?:孙子|外孙)(?:大于|高于|超过|>)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "子女年龄-及以下"
    patterns:
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "子女年龄-以下"
    patterns:
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "女儿年龄-及以下"
    patterns:
      - '{SEARCH}(?:女儿|闺女|女娃|女娃娃|女宝)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:女儿|闺女|女娃|女娃娃|女宝)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "女儿年龄-以下"
    patterns:
      - '{SEARCH}(?:女儿|闺女|女娃|女娃娃|女宝)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "儿子年龄-及以下"
    patterns:
      - '{SEARCH}(?:儿子|男娃|男宝|男娃|男娃娃)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:儿子|男娃|男宝|男娃|男娃娃)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "儿子年龄-以下"
    patterns:
      - '{SEARCH}(?:儿子|男娃|男宝|男娃|男娃娃)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "父母年龄-及以下"
    patterns:
      - '{SEARCH}(?:父母|爸妈|双亲)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:父母|爸妈|双亲)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"

  - name: "父母年龄-以下"
    patterns:
      - '{SEARCH}(?:父母|爸妈|双亲)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"

  - name: "父亲年龄-及以下"
    patterns:
      - '{SEARCH}(?:爸爸|父亲)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:爸爸|父亲)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "父亲年龄-以下"
    patterns:
      - '{SEARCH}(?:爸爸|父亲)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "母亲年龄-及以下"
    patterns:
      - '{SEARCH}(?:母亲|妈妈)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:母亲|妈妈)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "母亲年龄-以下"
    patterns:
      - '{SEARCH}(?:母亲|妈妈)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "配偶年龄-及以下"
    patterns:
      - '{SEARCH}(?:配偶)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:配偶)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"

  - name: "配偶年龄-以下"
    patterns:
      - '{SEARCH}(?:配偶)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"

  - name: "妻子年龄-及以下"
    patterns:
      - '{SEARCH}(?:老婆|妻子|夫人)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:老婆|妻子|夫人)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "妻子年龄-以下"
    patterns:
      - '{SEARCH}(?:老婆|妻子|夫人)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "丈夫年龄-及以下"
    patterns:
      - '{SEARCH}(?:老公|丈夫)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:老公|丈夫)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "丈夫年龄-以下"
    patterns:
      - '{SEARCH}(?:老公|丈夫)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "兄弟姐妹年龄-及以下"
    patterns:
      - '{SEARCH}(?:兄弟|姐妹|兄弟姐妹)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:兄弟|姐妹|兄弟姐妹)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"

  - name: "兄弟姐妹年龄-以下"
    patterns:
      - '{SEARCH}(?:兄弟|姐妹|兄弟姐妹)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"

  - name: "兄弟年龄-及以下"
    patterns:
      - '{SEARCH}(?:兄弟|哥哥|弟弟)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:兄弟|哥哥|弟弟)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "兄弟年龄-以下"
    patterns:
      - '{SEARCH}(?:兄弟|哥哥|弟弟)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "姐妹年龄-及以下"
    patterns:
      - '{SEARCH}(?:姐妹|姐姐|妹妹)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:姐妹|姐姐|妹妹)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "姐妹年龄-以下"
    patterns:
      - '{SEARCH}(?:姐妹|姐姐|妹妹)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "外祖父母年龄-及以下"
    patterns:
      - '{SEARCH}(?:祖父母|外祖父母)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:祖父母|外祖父母)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"

  - name: "外祖父母年龄-以下"
    patterns:
      - '{SEARCH}(?:祖父母|外祖父母)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"

  - name: "外祖父年龄-及以下"
    patterns:
      - '{SEARCH}(?:外祖父|祖父|爷爷|外公)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:外祖父|祖父|爷爷|外公)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "外祖父年龄-以下"
    patterns:
      - '{SEARCH}(?:外祖父|祖父|爷爷|外公)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "外祖母年龄-及以下"
    patterns:
      - '{SEARCH}(?:外祖母|祖母|奶奶|外婆)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:外祖母|祖母|奶奶|外婆)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "外祖母年龄-以下"
    patterns:
      - '{SEARCH}(?:外祖母|祖母|奶奶|外婆)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "外孙子女年龄-及以下"
    patterns:
      - '{SEARCH}(?:孙子女|孙子孙女|外孙子女|外孙外孙女)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:孙子女|孙子孙女|外孙子女|外孙外孙女)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"

  - name: "外孙子女年龄-以下"
    patterns:
      - '{SEARCH}(?:孙子女|孙子孙女|外孙子女|外孙外孙女)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"

  - name: "外孙子年龄-及以下"
    patterns:
      - '{SEARCH}(?:孙子|外孙)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:孙子|外孙)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "外孙子年龄-以下"
    patterns:
      - '{SEARCH}(?:孙子|外孙)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "外孙女年龄-及以下"
    patterns:
      - '{SEARCH}(?:孙女|外孙女)(\d+)周?岁及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:孙女|外孙女)(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "外孙女年龄-以下"
    patterns:
      - '{SEARCH}(?:孙女|外孙女)(?:小于|低于|<)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "子女年龄-精确"
    patterns:
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "儿子年龄-精确"
    patterns:
      - '{SEARCH}(?:儿子|男娃|男宝|男娃|男娃娃)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "女儿年龄-精确"
    patterns:
      - '{SEARCH}(?:女儿|闺女|女娃|女娃娃|女宝)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "父母年龄-精确"
    patterns:
      - '{SEARCH}(?:父母|爸妈|双亲)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"

  - name: "父亲年龄-精确"
    patterns:
      - '{SEARCH}(?:爸爸|父亲)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "母亲年龄-精确"
    patterns:
      - '{SEARCH}(?:母亲|妈妈)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "配偶年龄-精确"
    patterns:
      - '{SEARCH}(?:配偶)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"

  - name: "丈夫年龄-精确"
    patterns:
      - '{SEARCH}(?:老公|丈夫)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "妻子年龄-精确"
    patterns:
      - '{SEARCH}(?:老婆|妻子|夫人)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "配偶"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "兄弟姐妹年龄-精确"
    patterns:
      - '{SEARCH}(?:兄弟|姐妹|兄弟姐妹)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"

  - name: "姐妹年龄-精确"
    patterns:
      - '{SEARCH}(?:姐妹|姐姐|妹妹)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "兄弟年龄-精确"
    patterns:
      - '{SEARCH}(?:兄弟|哥哥|弟弟)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "外祖父母年龄-精确"
    patterns:
      - '{SEARCH}(?:祖父母|外祖父母|爷爷奶奶|外公外婆)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"

  - name: "外祖母年龄-精确"
    patterns:
      - '{SEARCH}(?:外祖母|祖母|奶奶|外婆)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "外祖父年龄-精确"
    patterns:
      - '{SEARCH}(?:外祖父|祖父|爷爷|外公)(\d+)周?岁(?:的客户|客户)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)祖父母"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "外孙子女年龄-精确"
    patterns:
      - '{SEARCH}(?:孙子女|外孙子女|孙子孙女|外孙子外孙女)(\d+)周?岁(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"

  - name: "孙女年龄-精确"
    patterns:
      - '{SEARCH}(?:孙女|外孙女)(\d+)周?岁(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "孙子年龄-精确"
    patterns:
      - '{SEARCH}(?:孙子|外孙)(\d+)周?岁(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "exact_range"
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "(外)孙子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "子女年龄-未成年"
    patterns:
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)(?:未成年|没成年|未成年人)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 0
      max: 17
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "女儿年龄-未成年"
    patterns:
      - '{SEARCH}(?:女儿|女娃娃|女娃|闺女)(?:未成年|没成年|未成年人)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 0
      max: 17
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "儿子年龄-未成年"
    patterns:
      - '{SEARCH}(?:儿子|男娃娃|男娃)(?:未成年|没成年|未成年人)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 0
      max: 17
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "子女年龄-青年"
    patterns:
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)(?:已成年|成年了|成年)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 18
      max: 35
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "女儿年龄-青年"
    patterns:
      - '{SEARCH}(?:女儿|女娃娃|女娃|闺女)(?:已成年|成年了|成年)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 18
      max: 35
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "儿子年龄-青年"
    patterns:
      - '{SEARCH}(?:儿子|男娃娃|男娃)(?:已成年|成年了|成年)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 18
      max: 35
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "子女教育阶段-幼儿园"
    patterns:
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)在?(?:上|读)?(?:幼儿园|学前班)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 3
      max: 6
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "女儿教育阶段-幼儿园"
    patterns:
      - '{SEARCH}(?:女儿|女娃娃|女娃|闺女)在?(?:上|读)?(?:幼儿园|学前班)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 3
      max: 6
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "儿子教育阶段-幼儿园"
    patterns:
      - '{SEARCH}(?:儿子|男娃娃|男娃)在?(?:上|读)?(?:幼儿园|学前班)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 3
      max: 6
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "子女教育阶段-小学"
    patterns:
      - '{SEARCH}(?:子女|孩子|小孩|小朋友|娃|小娃)在?(?:上|读)?小学(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 6
      max: 12
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "女儿教育阶段-小学"
    patterns:
      - '{SEARCH}(?:女儿|女娃娃|女娃|闺女)在?(?:上|读)?小学(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 6
      max: 12
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "儿子教育阶段-小学"
    patterns:
      - '{SEARCH}(?:儿子|男娃娃|男娃)在?(?:上|读)?小学(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 6
      max: 12
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "子女教育阶段-初中"
    patterns:
      - '{SEARCH}有?(?:子女|孩子|小孩|小朋友|娃|小娃)(?:在[上读]?|上|读)?初中(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 12
      max: 15
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "女儿教育阶段-初中"
    patterns:
      - '{SEARCH}有?(?:女儿|女娃娃|女娃|闺女)(?:在[上读]?|上|读)?初中(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 12
      max: 15
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "儿子教育阶段-初中"
    patterns:
      - '{SEARCH}有?(?:儿子|男娃娃|男娃)(?:在[上读]?|上|读)?初中(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 12
      max: 15
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "子女教育阶段-高中"
    patterns:
      - '{SEARCH}有?(?:子女|孩子|小孩|小朋友|娃|小娃)(?:在[上读]?|上|读)?高中(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 15
      max: 18
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "儿子教育阶段-高中"
    patterns:
      - '{SEARCH}有?(?:儿子|男娃娃|男娃)(?:在[上读]?|上|读)?高中(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 15
      max: 18
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "女儿教育阶段-高中"
    patterns:
      - '{SEARCH}有?(?:女儿|女娃娃|女娃|闺女)(?:在[上读]?|上|读)?高中(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 15
      max: 18
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "子女教育阶段-初高中"
    patterns:
      - '{SEARCH}有?(?:子女|孩子|小孩|小朋友|娃|小娃)(?:在[上读]?|上|读)?(?:初高中|初中或高中)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 12
      max: 18
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "女儿教育阶段-初高中"
    patterns:
      - '{SEARCH}有?(?:女儿|女娃娃|女娃|闺女)(?:在[上读]?|上|读)?(?:初高中|初中或高中)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 12
      max: 18
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "儿子教育阶段-初高中"
    patterns:
      - '{SEARCH}有?(?:儿子|男娃娃|男娃)(?:在[上读]?|上|读)?(?:初高中|初中或高中)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 12
      max: 18
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "子女教育阶段-大学"
    patterns:
      - '{SEARCH}有?(?:子女|孩子|小孩|小朋友|娃|小娃)(?:在[上读]?|上|读)?(?:大学|本科|专科|大专)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 18
      max: 22
    priority: 12
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "女儿教育阶段-大学"
    patterns:
      - '{SEARCH}有?(?:女儿|女娃娃|女娃|闺女)(?:在[上读]?|上|读)?(?:大学|本科|专科|大专)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 18
      max: 22
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "儿子教育阶段-大学"
    patterns:
      - '{SEARCH}有?(?:儿子|男娃娃|男娃)(?:在[上读]?|上|读)?(?:大学|本科|专科|大专)(?:的客户|客户|的)?'
    field: "familyInfo.familyclientage"
    operator: "RANGE"
    value_type: "static"
    value:
      min: 18
      max: 22
    priority: 13
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  # ==================== 证件类型 (idType) ====================
  - name: "证件类型"
    enum_ref: "idType"
    patterns_template:
      - '{SEARCH}{enum}(?:的客户|客户)?'
      - '{SEARCH}证件{CW}{0,2}{enum}(?:的客户|客户)?'
      - '{SEARCH}证件类型(?:为|是)?{enum}(?:的客户|客户)?'
    field: "idType"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 7
#    require_paired_field: "idNo"

  # ==================== 承保日期 (latelyUndwrtSegTime) ====================

  - name: "承保日期-近N年"
    patterns:
      - '{SEARCH}(?:近|最近|过去|这)([0-9一二两三四五六七八九十百]+)年(?:内|里|之内)?{CW}{0,2}承保{CUSTOMER_SUFFIX}'
      - '{SEARCH}承保(?:时间|日期)?(?:在|为|是)?(?:近|最近|过去|这)([0-9一二两三四五六七八九十百]+)年(?:内|里|之内)?{CUSTOMER_SUFFIX}'
    field: "latelyUndwrtSegTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "past_n_years_to_today"
      years_group: 1
      format: "yyyy-MM-dd"
    priority: 16
    merge_to_llm: true

  - name: "承保日期-今年"
    patterns:
      - '{SEARCH}(?:今年|本年){CW}{0,2}承保(?:的客户|客户)?'
      - '{SEARCH}承保{CW}{0,2}在今年(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "承保日期-本月"
    patterns:
      - '{SEARCH}本月{CW}{0,2}承保(?:的客户|客户)?'
      - '{SEARCH}承保{CW}{0,2}在本月(?:的客户|客户)?'
      - '{SEARCH}这个?月{CW}{0,2}承保(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_month"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "承保日期-近期"
    patterns:
      - '{SEARCH}(?:最近|近)(\d+)天{CW}{0,2}承保(?:的客户|客户)?'
      - '{SEARCH}(?:最近|近)(?:一个月|30天){CW}{0,2}承保(?:的客户|客户)?'
      - '{SEARCH}最近承保(?:的客户|客户)?'
      - '{SEARCH}最近承保时间(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days: 29
      days_group: 1
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "承保日期-本周"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}承保(?:的客户|客户)?'
      - '{SEARCH}承保(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期)(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "承保日期-上周"
    patterns:
      - '{SEARCH}(?:上周|上星期|上个星期){CW}{0,2}承保(?:的客户|客户)?'
      - '{SEARCH}承保(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期)(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: -1
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "承保日期-近一周"
    patterns:
      - '{SEARCH}(?:近|最近|过去)一周(?:内|里)?{CW}{0,2}承保(?:的客户|客户)?'
      - '{SEARCH}承保(?:时间|日期)?{CW}{0,2}在(?:近|最近|过去)一周(?:内|里)?(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days: 7
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "承保日期-大于指定年份"
    patterns:
      - '{SEARCH}承保(?:时间|日期){CW}{0,2}大于(\d{4})年(?:的客户|客户)?'
      - '{SEARCH}承保(?:时间|日期){CW}{0,2}超过(\d{4})年(?:的客户|客户)?'
      - '{SEARCH}承保(?:时间|日期){CW}{0,2}大于等于(\d{4})年(?:的客户|客户)?'
      - '{SEARCH}最近承保(?:时间|日期){CW}{0,2}大于(\d{4})年(?:的客户|客户)?'
      - '{SEARCH}最近承保(?:时间|日期){CW}{0,2}超过(\d{4})年(?:的客户|客户)?'
      - '{SEARCH}最近承保(?:时间|日期){CW}{0,2}大于等于(\d{4})年(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "year_end_datetime"
      format: "yyyy-MM-dd
      "
    priority: 9
    merge_to_llm: true

  - name: "承保日期-年份之后"
    patterns:
      - '{SEARCH}承保日期(?:在)?(\d{4})年之后(?:的客户|客户)?'
      - '{SEARCH}承保时间(?:在)?(\d{4})年之后(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "承保日期-年份之前"
    patterns:
      - '{SEARCH}承保日期(?:在)?(\d{4})年之前(?:的客户|客户)?'
      - '{SEARCH}承保时间(?:在)?(\d{4})年之前(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_end_datetime"
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  - name: "承保日期-年份之后（含该年）-简化"
    patterns:
      - '{SEARCH}(\d{4})年及之后承保(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年以后承保(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年起承保(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
      format: "yyyy-MM-dd"
    priority: 8
    merge_to_llm: true

  - name: "承保日期-年份之前（含该年）-简化"
    patterns:
      - '{SEARCH}(\d{4})年及之前承保(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年以前承保(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年前承保(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_end_datetime"
      format: "yyyy-MM-dd"
    priority: 8
    merge_to_llm: true

  - name: "承保日期-年份范围"
    patterns:
      - '{SEARCH}承保日期(?:在)?(\d{4})年到(\d{4})年(?:的客户|客户)?'
      - '{SEARCH}承保时间(?:在)?(\d{4})年到(\d{4})年(?:的客户|客户)?'
      - '{SEARCH}(\d{4})至(\d{4})年承保(?:的客户|客户)?'
      - '{SEARCH}(\d{4})到(\d{4})年之间承保(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
      format: "yyyy-MM-dd"
      min_group: 1
      max_group: 2
      max_transform: "year_end_datetime"
    priority: 9
    merge_to_llm: true

  - name: "承保日期-年份范围简化"
    patterns:
      - '{SEARCH}(\d{4})到(\d{4})承保(?:的客户|客户)?'
    field: "latelyUndwrtSegTime"
    operator: "RANGE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
      format: "yyyy-MM-dd"
      min_group: 1
      max_group: 2
      max_transform: "year_end_datetime"
    priority: 8
    merge_to_llm: true

#  - name: "承保日期-存在排序口语"
#    patterns:
#      - '{SEARCH}(?:承保日期|承保时间|承保客户|承保的这批)(?:从晚到早|从早到晚|升序|降序)?(?:排|排序|排列|排个序|排一排|排排|看看)?'
#      - '.*(?:承保日期|承保时间|承保客户|承保的这批).*(?:从晚到早|从早到晚|升序|降序|排|排序|排列|看看).*'
#    field: "latelyUndwrtSegTime"
#    operator: "EXISTS"
#    value_type: "static"
#    value: ""
#    priority: 12
#    merge_to_llm: true

  # ==================== 证件号码 (idNo) ====================

  - name: "身份证-匹配"
    ignore_case: true
    patterns:
      - '{SEARCH}(\d{17}[\dXx])(?:的客户|客户)?'
      - '{SEARCH}身份证{CW}{0,2}(\d{17}[\dXx]|\d{15})(?:的客户|客户)?'
      - '{SEARCH}(?:身份证|身份证号|身份证号码|证件号|证件号码|出生证号|户口本号|港澳台居住证号|军人证号|港澳台证件|护照号|护照号码|外国人居留证号)(?:为|是|匹配|等于|包含|含有|带有)?{CW}{0,2}([A-Za-z0-9]{1,32})(?:的客户|客户)?'
      - '{SEARCH}(?:身份证|身份证号|身份证号码|证件号|证件号码|出生证号|户口本号|港澳台居住证号|军人证号|港澳台证件|护照号|护照号码|外国人居留证号)(?:前缀|开头|以)(?:为|是)?[：:\s]?([A-Za-z0-9]{1,32})(?:开头)?(?:的客户|客户)?'
      - '{SEARCH}(?:身份证|身份证号|身份证号码|证件号|证件号码|出生证号|户口本号|港澳台居住证号|军人证号|港澳台证件|护照号|护照号码|外国人居留证号){CW}{0,2}([A-Za-z0-9]{1,32})(?:开头|前缀)(?:的客户|客户)?'
      - '{SEARCH}(?:身份证|身份证号|身份证号码|证件号|证件号码|出生证号|户口本号|港澳台居住证号|军人证号|港澳台证件|护照号|护照号码|外国人居留证号){CW}{0,2}(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:为|是)?[：:\s]?([A-Za-z0-9]{1,32})(?:的客户|客户)?'
      - '{SEARCH}(?:身份证|身份证号|身份证号码|证件号|证件号码|出生证号|户口本号|港澳台居住证号|军人证号|港澳台证件|护照号|护照号码|外国人居留证号){CW}{0,2}([A-Za-z0-9]{1,32})(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:的客户|客户)?'
      - '{SEARCH}(?:尾号|尾数|末尾|后四位|后几位)(?:为|是)?[：:\s]?([A-Za-z0-9]{1,32})(?:的)?(?:身份证|身份证号|身份证号码|证件号|证件号码|护照号|护照号码)(?:的客户|客户)?'
      - '{SEARCH}([A-Za-z0-9]{1,32})(?:尾号|尾数|末尾|后四位|后几位)(?:的)?(?:身份证|身份证号|身份证号码|证件号|证件号码|护照号|护照号码)(?:的客户|客户)?'
      - '{SEARCH}([A-Za-z0-9]{1,32})(?:开头|前缀)(?:的)?(?:身份证|身份证号|身份证号码|证件号|证件号码|护照号|护照号码)(?:的客户|客户)?'
    field: "idNo"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 9

  - name: "证件号码-数字"
    patterns:
      - '((?![A-Za-z]{0,2}1[3-9]\d{9})[A-Za-z]{1,2}\d{5,12})'
      - '(?:(?<!\d)(?!1[3-9]\d{9})(\d{4,10})(?!\d))'
    field: "idNo"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 1
    require_paired_field: "idType"

  - name: "保单到期时间-近期"
    patterns:
      - '{SEARCH}(?:未来|接下来)?(?:一个月|30天|三十天)(?:内|里)?(?:即将到期|快到期|近期到期|到期|过期)(?:的客户|客户|保单)?'
      - '{SEARCH}(?:即将到期|快到期|近期到期|到期|过期)(?:的)?(?:保单|寿险)?(?:客户|的客户|保单)?(?:在)?(?:未来|接下来)?(?:一个月|30天|三十天)(?:内|里)?'
      - '{SEARCH}(?:保单|寿险)(?:即将到期|快到期|即将过期|快过期|近期过期|近期过期)(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单|寿险){CW}{0,2}(?:即将到期|快到期|近期到期|即将过期|快过期|近期过期|近期过期)(?:的客户|客户|保单)?'
      - '{SEARCH}(?:即将到期|快到期|近期到期|即将过期|快过期|近期过期|近期过期)的?(?:保单|寿险)(?:的客户|客户|保单)?'
      - '{SEARCH}续保提醒(?:的客户|客户)?'
    field: "validSinsMatuDateTime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days: 29
      format: "yyyy-MM-dd"
    priority: 9
    merge_to_llm: true

  # ==================== 保单号 (polNo) ====================

  - name: "保单号-匹配"
    patterns:
      - '{SEARCH}({POLICY_GP_PREFIX}{BUSINESS_ALNUM}{3,20})(?:的客户|客户)?'
      - '{SEARCH}({POLICY_PA_PREFIX}{BUSINESS_ALNUM}{3,20})(?:的客户|客户)?'
      - '{SEARCH}(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id){CW}{0,2}[为是：:]?\s*({POLICY_GP_PREFIX}{BUSINESS_ALNUM}{1,20})(?:的客户|客户)?'
      - '{SEARCH}(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id){CW}{0,2}[为是：:]?\s*({POLICY_PA_PREFIX}{BUSINESS_ALNUM}{1,20}|{POLICY_GP_PREFIX}{BUSINESS_ALNUM}{14}|{BUSINESS_DIGIT}{15,17})(?:的客户|客户)?'
      - '{SEARCH}(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id)(?:匹配|等于|包含|含有|带有)?\s*({POLICY_PA_PREFIX}{BUSINESS_ALNUM}{1,20}|{POLICY_GP_PREFIX}{BUSINESS_ALNUM}{1,20}|{BUSINESS_DIGIT}{1,20})(?:的客户|客户)?'
      - '{SEARCH}(?:保单)(?:号|号码|编号|代码|ID|id)?(?:为|是|匹配|等于)?\s*({BUSINESS_DIGIT}{1,20})(?:的客户|客户)?'
      - '{SEARCH}(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id)(?:前缀|开头|以)(?:为|是)?[：:\s]?([A-Za-z0-9]{1,20})(?:开头)?(?:的客户|客户)?'
      - '{SEARCH}(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id){CW}{0,2}([A-Za-z0-9]{1,20})(?:开头|前缀)(?:的客户|客户)?'
      - '{SEARCH}([A-Za-z0-9]{1,20})(?:开头|前缀)(?:的)?(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id)(?:的客户|客户)?'
    field: "polNo"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "upper"
    priority: 10

  - name: "保单号-尾号"
    patterns:
      - '{SEARCH}{POLICY_NO_FIELD_WORD}(?:的)?{SUFFIX_WORD}(?:为|是)?[：:\s]?([A-Za-z0-9]{1,20}){CUSTOMER_SUFFIX}'
      - '{SEARCH}([A-Za-z0-9]{1,20})(?:的)?{POLICY_NO_FIELD_WORD}(?:的)?{SUFFIX_WORD}{CUSTOMER_SUFFIX}'
      - '{SEARCH}[Pp][A-Za-z0-9]*\*{3,}([A-Za-z0-9]{4})'
      - '{SEARCH}(?:尾号|尾数|末尾|后四位|后几位)(?:为|是)?[：:\s]?([A-Za-z0-9]{1,20})(?:的)?(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id){CUSTOMER_SUFFIX}'
      - '{SEARCH}([A-Za-z0-9]{1,20})(?:尾号|尾数|末尾|后四位|后几位)(?:的)?(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id){CW}{0,2}(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:为|是)?[：:\s]?([A-Za-z0-9]{1,20}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id){CW}{0,2}([A-Za-z0-9]{1,20})(?:尾号|尾数|末尾|后四位|后几位|结尾){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id)(?:的)?(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:是|为)?([A-Za-z0-9\-]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id)(?:的)?最?后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9\-]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:保单号|保单号码|保单编号|保单代码|保单ID|保单id)以([A-Za-z0-9\-]+)(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:的)?{CUSTOMER_SUFFIX}'
    field: "polNo"
    operator: "MATCH"
    match_mode: "suffix"
    value_type: "capture"
    value:
      group: 1
      transform: "strip_non_digits"
    priority: 18
    merge_to_llm: false


  # ==================== 车牌号 (licensePlateNo) ====================

  - name: "车牌号-匹配"
    is_supported: false
    ignore_case: true
    patterns:
      - '{SEARCH}(?:车牌号|车牌号码|车辆牌照号|汽车牌照号)(?:为|是|等于|匹配)?[：:\s]*([京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-HJ-NP-Z][A-HJ-NP-Z0-9]{5,6})(?:的客户|客户)?'
      - '{SEARCH}(?:按)?车牌号[：:\s]*([京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-HJ-NP-Z][A-HJ-NP-Z0-9]{5,6})(?:查询|查找|查)?(?:的客户|客户)?'
      - '{SEARCH}([京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-HJ-NP-Z][A-HJ-NP-Z0-9]{5,6})(?:的客户|客户)?'
    field: "licensePlateNo"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "upper"
    priority: 20
    merge_to_llm: false

  # ==================== 职业 (profName) ====================

  - name: "职业"
    enum_ref: "profName"
    patterns_template:
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))职业(?:的客户|客户)?'
      - '{SEARCH}职业(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户)?'
      - '{SEARCH}做{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户|客户|的人|人|名单|有哪些人|有哪些|的)?'
    field: "profName"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 7

  # ==================== 资产状况 (assetsCondition) ====================

  - name: "资产状况-有房有车"
    patterns:
      - '{SEARCH}(?:有房有车|有车有房)(?:的客户|客户)?'
      - '{SEARCH}(?:名下)(?:有房有车|有车有房)(?:的客户|客户)?'
      - '{SEARCH}客户资产状况(?:包含|为|是)?(?:有房有车|有车有房)(?:的客户|客户)?'
    field: "assetsCondition"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "有房有车"
    priority: 12
    merge_to_llm: true

  - name: "资产状况-无房无车"
    patterns:
      - '{SEARCH}(?:无房无车|无车无房)(?:的客户|客户)?'
      - '{SEARCH}(?:名下)(?:无房无车|无车无房)(?:的客户|客户)?'
      - '{SEARCH}客户资产状况(?:包含|为|是)?(?:无房无车|无车无房)(?:的客户|客户)?'
    field: "assetsCondition"
    operator: "CONTAINS"
    value_type: "static"
    value: [ "无房无车" ]
    priority: 12
    merge_to_llm: true

  - name: "资产状况-有车无房"
    patterns:
      - '{SEARCH}有车无房(?:的客户|客户)?'
      - '{SEARCH}(?:只有车没有房|只有车没房|有车但没房|有车但是没房|有车但是没有房)(?:的客户|客户)?'
      - '{SEARCH}(?:名下有车|家里有车|自己有车)(?:但没房|但是没房|无房|没有房)(?:的客户|客户)?'
      - '{SEARCH}(?:名下)(?:有车无房|有车但是没有房|有车没房)(?:的客户|客户)?'
      - '{SEARCH}客户资产状况(?:包含|为|是)?有车无房(?:的客户|客户)?'
    field: "assetsCondition"
    operator: "CONTAINS"
    value_type: "static"
    value: [ "有车" ]
    priority: 12
    merge_to_llm: true

  - name: "资产状况-无车有房"
    patterns:
      - '{SEARCH}无车有房(?:的客户|客户)?'
      - '{SEARCH}(?:名下)(?:无车有房)(?:的客户|客户)?'
      - '{SEARCH}客户资产状况(?:包含|为|是)?无车有房(?:的客户|客户)?'
      - '{SEARCH}(?:有房无车|只有房没有车|只有房没车|有房但没车|有房但是没车)(?:的客户|客户)?'
      - '{SEARCH}(?:名下有房|家里有房|自己有房)(?:但没车|但是没车|无车|没有车)(?:的客户|客户)?'
    field: "assetsCondition"
    operator: "CONTAINS"
    value_type: "static"
    value: [ "有房" ]
    priority: 12
    merge_to_llm: true

  - name: "资产状况-有车"
    patterns:
      - '{SEARCH}(?:有车|买了车)(?!有房|无房|没房|没有房|但没房|但是没房|但是没有房)(?:的客户|客户|的)?'
      - '{SEARCH}客户资产状况(?:包含|为|是)?有车(?:的客户|客户)?'
    field: "assetsCondition"
    operator: "CONTAINS"
    value_type: "static"
    value: [ "有车", "有房有车" ]
    priority: 10
    merge_to_llm: true

  - name: "资产状况-有房"
    patterns:
      - '{SEARCH}有房(?!无车|没车|没有车|但没车|但是没车)(?:的客户|客户|的)?'
      - '{SEARCH}(?:名下有房|家里有房|自己有房|还有房)(?!无车|没车|没有车|但没车|但是没车)(?:的客户|客户|的)?'
      - '{SEARCH}客户资产状况(?:包含|为|是)?有房(?:的客户|客户)?'
    field: "assetsCondition"
    operator: "CONTAINS"
    value_type: "static"
    value: [ "有房", "有房有车" ]
    priority: 10
    merge_to_llm: true

  # ==================== 产险产品 (isBuyInsuranceCar) ====================
  - name: "产险产品-车险"
    patterns:
      - '{SEARCH}(?:购买了|购买|有|持有|配置|配置了)车险(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}(?<!非)(?<!无)(?<!没)(?<!有)车险(?:客户|的客户|名单|有哪些人|的人|人)?'
    field: "isBuyInsuranceCar"
    operator: "MATCH"
    value_type: "static"
    value: "车险"
    priority: 10
    merge_to_llm: true

  - name: "产险产品-非车险"
    patterns:
      - '{SEARCH}(?:购买了?|有|持有|配置了?)非车险(?:的客户|客户)?'
      - '{SEARCH}(?:没购买了?|没有|未持有|没配置了|未持有|没配置了|未配置|未购买|未购买了|未购买?)车险(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}非车险(?:客户|的客户)?'
      - '{SEARCH}不是车险(?:的客户|客户)?'
      - '{SEARCH}(?:没有|没|无)车险(?:的客户|客户)?'
    field: "isBuyInsuranceCar"
    operator: "MATCH"
    value_type: "static"
    value: "非车险"
    priority: 10
    merge_to_llm: true

  # ==================== 保单托管 (trusteeshipFlag) ====================

  - name: "保单托管-是"
    patterns:
      - '{SEARCH}(?:已|有)?托管(?:保单)?(?:的客户|客户)?'
      - '{SEARCH}保单托管(?:的客户|客户)?'
      - '{SEARCH}托管标志(?:为|是)?是(?:的客户|客户)?'
    field: "trusteeshipFlag"
    operator: "MATCH"
    value_type: "static"
    value: "是"
    priority: 10
    merge_to_llm: true

  - name: "保单托管-否"
    patterns:
      - '{SEARCH}(?:哪些客户|哪些人)?没有保单托管'
      - '{SEARCH}(?:未|没有?|不)托管(?:的客户|客户|名单|有哪些人|的人|人)?'
      - '{SEARCH}未托管保单(?:的客户|客户|名单|有哪些人|的人|人)?'
      - '{SEARCH}托管标志(?:为|是)?否(?:的客户|客户)?'
    field: "trusteeshipFlag"
    operator: "MATCH"
    value_type: "static"
    value: "否"
    priority: 10
    merge_to_llm: true

  # ==================== 共享给我的客户 (onlyShareClientFlag) ====================

  - name: "共享给我的客户"
    is_supported: false
    patterns:
      # “共享客户”是“授权成功且30天未面访回收”的业务简称。
      - '{SEARCH}(?:成功)?(?:共享|分享)(?:给我|给我的|给当前用户|给当前用户的)?(?:的)?客户(?:名单)?'
      - '{SEARCH}(?:别人|他人|其他人)?(?:共享|分享)(?:给我|给我的|给当前用户|给当前用户的)?(?:的)?客户(?:名单)?'
      - '{SEARCH}(?:别人|他人|其他人)?(?:给我|向我|给当前用户|向当前用户)(?:共享|分享)(?:的)?客户(?:名单)?'
      - '{SEARCH}(?:我|当前用户)?收到(?:的)?(?:共享|分享)(?:的)?客户(?:名单)?'
      # 显式描述必须同时具备授权成功、30天未面访和回收三个业务要素。
      - '{SEARCH}(?:客户)?(?:已|已经)?(?:成功授权|授权成功|完成(?:了)?授权|授权)(?:给我|给当前用户)?(?:后)?(?:[，,、\s]*(?:且|并且|同时|但)?[，,、\s]*)?(?:连续)?(?:满|超过|达到)?30(?:天|日)(?:内)?(?:未|没有|无)(?:完成)?(?:面访|拜访)(?:而|后)?(?:被|已)?(?:系统)?回收(?:的)?客户(?:名单)?'
      - '{SEARCH}(?:满|超过|达到)?30(?:天|日)(?:内)?(?:未|没有|无)(?:完成)?(?:面访|拜访)(?:而|后)?(?:被|已)?(?:系统)?回收(?:的)?(?:已|已经)?(?:成功授权|授权成功|完成(?:了)?授权|授权)(?:的)?客户(?:名单)?'
    field: "onlyShareClientFlag"
    operator: "MATCH"
    value_type: "static"
    value: "Y"
    priority: 90
    confidence_level: "STRONG"
    merge_to_llm: false

  # ==================== 生存金未领取金额 (policies_survival_unclaimed_amount) ====================

  - name: "生存金未领取金额是否大于0-等于0"
    patterns:
      - '{SEARCH}(?:生存金未领取金额|未领取生存金|生存金待领|生存金未领)(?:是否)?(?:等于|为|是|=)0(?:元)?(?:的客户|客户)?'
      - '{SEARCH}(?:没有|无|不存在|未有)(?:未领取生存金|生存金未领取金额|生存金待领)(?:的客户|客户)?'
      - '{SEARCH}生存金(?:都)?领完了(?:的客户|客户)?'
    field: "polNoInfo.payamountdue"
    operator: "MATCH"
    value_type: "static"
    value: "否"
    priority: 11
    merge_to_llm: true

  - name: "生存金未领取金额是否大于0-大于0"
    patterns:
      - '{SEARCH}(?:生存金未领取金额|未领取生存金|生存金待领|生存金未领)(?:是否)?(?:大于|超过|高于|>|＞)0(?:元)?(?:的客户|客户)?'
      - '{SEARCH}(?:生存金未领取金额|未领取生存金金额|未领取生存金)(?:是否)?(?:大于|超过|高于|>|＞)0(?:为|是)?是(?:的客户|客户)?'
      - '{SEARCH}(?:有|存在)(?:未领取生存金|生存金未领取金额|生存金待领)(?:的客户|客户)?'
      - '{SEARCH}(?:有|存在)?未领取生存金(?:的客户|客户)?'
      - '{SEARCH}(?:生存金未领取|未领取生存金|有未领生存金)(?:的客户|客户)?'
      - '{SEARCH}生存金(?:还有)?余额未领取(?:的客户|客户)?'
      - '{SEARCH}(?:还有)?生存金没领(?:的客户|客户)?'
      - '{SEARCH}(?:生存金未领取金额|未领取生存金)(?:超过|大于|高于|不少于|不低于|>=|≥)(\d+)万(?:元)?(?:的客户|客户)?'
      - '{SEARCH}(?:生存金未领取金额|未领取生存金)(\d+)万以上(?:的客户|客户)?'
      - '{SEARCH}生存金(?:的客户|客户|名单|的人|人)'
    field: "polNoInfo.payamountdue"
    operator: "MATCH"
    value_type: "static"
    value: "是"
    priority: 11
    merge_to_llm: true


  # ==================== 家庭成员手机号 (familyInfo.familyclientmobile) ====================
  - name: "成员手机号-匹配"
    patterns:
      - '{SEARCH}?(?:家庭成员|家属|成员|子女|父母|儿子|女儿|小孩|娃|小朋友|爸爸|父亲|妈妈|母亲|外祖母|祖母|爷爷|奶奶|外公|外婆){CW}{0,2}(1[3-9]\d{9})'
      - '{SEARCH}?(?:家庭成员|家属|成员|子女|父母|儿子|女儿|小孩|娃|小朋友|爸爸|父亲|妈妈|母亲|外祖母|祖母|爷爷|奶奶|外公|外婆){CW}{0,2}手机号?(\d{1,10})(?:的客户|客户)?'
      - '{SEARCH}?(?:家庭成员|家属|成员|子女|父母|儿子|女儿|小孩|娃|小朋友|爸爸|父亲|妈妈|母亲|外祖母|祖母|爷爷|奶奶|外公|外婆){CW}{0,2}(?:手机号|手机号码)(?:为|是|匹配)[：、\s]?(1[3-9]\d{9})(?:的客户|客户)?'
      - '{SEARCH}?(?:家庭成员|家属|成员|子女|父母|儿子|女儿|小孩|娃|小朋友|爸爸|父亲|妈妈|母亲|外祖母|祖母|爷爷|奶奶|外公|外婆){CW}{0,2}?手机号(?:为|是)：\s?(1[3-9]\d{9})(?:的客户|客户)?'
      - '{SEARCH}?(?:家庭成员|家属|成员|子女|父母|儿子|女儿|小孩|娃|小朋友|爸爸|父亲|妈妈|母亲|外祖母|祖母|爷爷|奶奶|外公|外婆){CW}{0,2}手机号?(\d{1,11})开头(?:的客户|客户)?'
      - '{SEARCH}?(?:家庭成员|家属|成员|子女|父母|儿子|女儿|小孩|娃|小朋友|爸爸|父亲|妈妈|母亲|外祖母|祖母|爷爷|奶奶|外公|外婆){CW}{0,2}手机{CW}{0,2}(\d{1,11})开头(?:的客户|客户)?'
      - '{SEARCH}?(?:家庭成员|家属|成员|子女|父母|儿子|女儿|小孩|娃|小朋友|爸爸|父亲|妈妈|母亲|外祖母|祖母|爷爷|奶奶|外公|外婆){CW}{0,2}手机{CW}{0,2}尾号(\d{1,11})(?:的客户|客户)?'
      - '{SEARCH}?(?:家庭成员|家属|成员|子女|父母|儿子|女儿|小孩|娃|小朋友|爸爸|父亲|妈妈|母亲|外祖母|祖母|爷爷|奶奶|外公|外婆){CW}{0,2}手机?段(\d{1,11})(?:的客户|客户)?'
      - '{SEARCH}?(?:家庭成员|家属|成员|子女|父母|儿子|女儿|小孩|娃|小朋友|爸爸|父亲|妈妈|母亲|外祖母|祖母|爷爷|奶奶|外公|外婆){CW}{0,2}手机{CW}{0,2}号段(\d{1,11})(?:的客户|客户)?'
    field: "familyInfo.familyclientmobile"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    require_paired_field: "familyInfo.familyrelation"
    priority: 10

  # ==================== 家庭成员性别 (familyInfo.familyclientsex) ====================

  - name: "家庭成员性别"
    enum_ref: "familyInfo.familyclientsex"
    patterns_template:
      - '{SEARCH}(?:家庭成员|家属|成员|子女|父母|儿子|女儿|小孩|娃|小朋友|爸爸|父亲|妈妈|母亲|外祖母|祖母|爷爷|奶奶|外公|外婆){CW}{0,2}性别[为是：:]{0,1}{enum}(?:的客户|客户)?'
      - '{SEARCH}(?:家庭成员|家属|成员)(?:性别)?(?:匹配|为|是)?{enum}(?:的客户|客户)?'
      - '{SEARCH}{enum}性?(?:家庭成员|家属|成员|子女|父母|儿子|女儿|小孩|娃|小朋友|爸爸|父亲|妈妈|母亲|外祖母|祖母|爷爷|奶奶|外公|外婆)(?:的客户|客户)?'
    field: "familyInfo.familyclientsex"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    require_paired_field: "familyInfo.familyrelation"
    priority: 10

  - name: "家庭成员姓名-显式"
    patterns:
      - '{SEARCH}(?:家庭成员|家属|成员)(?:姓名|名字)(?:匹配|为|是)?([\u4e00-\u9fa5]{2,4}?)(?:的客户|客户)?'
    field: "familyInfo.familyclientname"
    operator: "MATCH"
    value_type: "capture"
    merge_to_llm: true
    value:
      group: 1
    require_paired_field: "familyInfo.familyrelation"
    priority: 11

  - name: "兄弟姓名-弟弟口语"
    patterns:
      - '{SEARCH}(?!(?:客户|本人|我的))([\u4e00-\u9fa5]{2,4}?)(?:的)?弟弟(?:的客户|客户)?'
    field: "familyInfo.familyclientname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "兄弟姐妹"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"
    priority: 29

  - name: "子女姓名-父亲口语"
    patterns:
      - '{SEARCH}(?!(?:客户|本人|我的))([\u4e00-\u9fa5]{2,4}?)(?:的)?(?=爸爸|父亲)(?:爸爸|父亲)(?:的)?(?:保单|客户)?'
    field: "familyInfo.familyclientname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "MATCH"
        value: "子女"
    priority: 28

  - name: "子女姓名-父母保单反向推断"
    patterns:
      - '{SEARCH}(?!(?:客户|本人|我的))([\u4e00-\u9fa5]{2,4}?)(?:的)?(?=爸爸|父亲|父母|妈妈|母亲)(?:爸爸|父亲|父母|妈妈|母亲)(?:的)?(?:保单)?(?:的客户|客户)?'
    field: "familyInfo.familyclientname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 27
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "家庭成员手机号-显式"
    patterns:
      - '{SEARCH}(?:家庭成员|家属|成员)(?:手机号|电话|手机)(?:匹配|为|是)?(1[3-9]\d{9})(?:的客户|客户)?'
    field: "familyInfo.familyclientmobile"
    operator: "MATCH"
    value_type: "capture"
    merge_to_llm: true
    value:
      group: 1
    require_paired_field: "familyInfo.familyrelation"
    priority: 11

  - name: "子女手机号-显式"
    patterns:
      - '{SEARCH}(?:子女|孩子|小孩|娃娃)(?:手机号|电话|手机)(?:匹配|为|是)?(1[3-9]\d{9})(?:的客户|客户)?'
    field: "familyInfo.familyclientmobile"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "女儿手机号-显式"
    patterns:
      - '{SEARCH}(?:女儿|闺女|女娃|女宝宝)(?:手机号|电话|手机)(?:匹配|为|是)?(1[3-9]\d{9})(?:的客户|客户)?'
    field: "familyInfo.familyclientmobile"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  - name: "儿子手机号-显式"
    patterns:
      - '{SEARCH}(?:儿子|男娃|男宝宝)(?:手机号|电话|手机)(?:匹配|为|是)?(1[3-9]\d{9})(?:的客户|客户)?'
    field: "familyInfo.familyclientmobile"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "父母手机号-显式"
    patterns:
      - '{SEARCH}(?:父母|双亲|爸妈)(?:手机号|电话|手机)(?:匹配|为|是)?(1[3-9]\d{9})(?:的客户|客户)?'
    field: "familyInfo.familyclientmobile"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"

  - name: "父亲手机号-显式"
    patterns:
      - '{SEARCH}(?:父亲|爸爸)(?:手机号|电话|手机)(?:匹配|为|是)?(1[3-9]\d{9})(?:的客户|客户)?'
    field: "familyInfo.familyclientmobile"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "男"

  - name: "母亲手机号-显式"
    patterns:
      - '{SEARCH}(?:母亲|妈妈)(?:手机号|电话|手机)(?:匹配|为|是)?(1[3-9]\d{9})(?:的客户|客户)?'
    field: "familyInfo.familyclientmobile"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 11
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "CONTAINS"
        value: "女"

  # ==================== 保单状态 (polNoInfo.polStatus) ====================

  - name: "保单状态"
    is_supported: true
    enum_ref: "polNoInfo.polStatus"
    patterns_template:
      - '{SEARCH}(?:保单状态|状态)(?:为|是|包含)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:的客户有哪些|客户有哪些|有哪些客户|有哪些|的保单客户|保单客户|的客户名单|客户名单|的客户|客户|名单)?'
      - '{SEARCH}(?:保单已经|已经|已)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:状态的保单客户|状态的客户|的保单客户|保单客户|保单的客户|的客户有哪些|客户有哪些|的客户名单|客户名单|的客户|客户|保单状态|状态|保单|名单|有哪些客户|有哪些)?'
      - '{SEARCH}(?:买过保单|购买过保单|有保单)(?:且|并且|，|,)?状态(?:为|是)?{enum}(?:的客户|客户)?'
      - '{SEARCH}(?:保单还在|保单仍是|保单还是){enum}(?:的客户|客户)?'
      - '哪些客户的保单还在{enum}'
    field: "polNoInfo.polStatus"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 10
    merge_to_llm: true

  - name: "保单状态-口语退保"
    patterns:
      - '{SEARCH}保单已经退掉的客户'
    field: "polNoInfo.polStatus"
    operator: "MATCH"
    value_type: "static"
    value: "退保"
    priority: 9
    merge_to_llm: true

  - name: "保单状态-口语停效"
    patterns:
      - '{SEARCH}保单停了的客户'
    field: "polNoInfo.polStatus"
    operator: "MATCH"
    value_type: "static"
    value: "停效"
    priority: 9
    merge_to_llm: true

  - name: "保单状态-口语终止"
    patterns:
      - '{SEARCH}保单终止了的客户'
    field: "polNoInfo.polStatus"
    operator: "MATCH"
    value_type: "static"
    value: "效力终止"
    priority: 9
    merge_to_llm: true

  - name: "保单状态-续保"
    patterns:
      - '{SEARCH}续保{CUSTOMER_SUFFIX}'
    field: "polNoInfo.polStatus"
    operator: "MATCH"
    value_type: "static"
    value: "等待续保"
    priority: 22
    merge_to_llm: false

  - name: "保单状态-有效汇总"
    # 有效保单 / 保单有效中 / 保单状态有效 → 所有有效状态的并集
    patterns:
      - '{SEARCH}有?有效的?保单(?:的客户|客户)?'
      - '{SEARCH}保单有效(?:中|的)?(?:客户|的客户)?'
      - '{SEARCH}保单状态有效(?:的客户|客户)?'
      - '{SEARCH}保单(?:是|为)有效(?:状态)?(?:的客户|客户)?'
      - '{SEARCH}(?:保单)?状态为有效(?:的客户|客户)?'
      - '{SEARCH}生效中的保单(?:的客户|客户)?'
      - '{SEARCH}(?:生效|生效中|有效)(?:的)?(?:客户|的客户|保单客户|名单)?'
      - '{SEARCH}(?:保单)?(?:未失效|没失效|没有失效|还没失效|尚未失效|非失效)(?:状态)?(?:的客户|客户|保单客户|名单|的人|人)?'
      - '{SEARCH}(?:未失效|没失效|没有失效|还没失效|尚未失效|非失效)(?:的)?(?:保单|客户|的客户|保单客户|名单|的人|人)?'
      - '{SEARCH}(?:保单)?(?:不是|不为)失效(?:状态)?(?:的客户|客户|保单客户|名单|的人|人)?'
    field: "polNoInfo.polStatus"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "交费有效"
      - "自垫交清"
      - "交清"
      - "减额交清"
      - "免交"
      - "自垫有效"
    priority: 10
    merge_to_llm: true

  - name: "保单状态-未有效汇总"
    # 未生效客户沿用“生效客户=保单状态有效汇总”的口径，取有效状态集合的反向包含。
    patterns:
      - '{SEARCH}(?:保单)?(?:未生效|还未生效|尚未生效)(?:状态)?(?:的客户|客户|保单客户|名单)?'
      - '{SEARCH}(?:未生效|还未生效|尚未生效)(?:的)?(?:保单|客户|的客户|保单客户|名单)?'
    field: "polNoInfo.polStatus"
    operator: "NOT_CONTAINS"
    value_type: "static"
    value:
      - "交费有效"
      - "自垫交清"
      - "交清"
      - "减额交清"
      - "免交"
      - "自垫有效"
    priority: 10
    merge_to_llm: true

  - name: "e生保未生效"
    patterns:
      - '{SEARCH}e生保(?:保单)?(?:未生效|还未生效|尚未生效|没生效)(?:的客户|客户|保单客户)?'
      - '{SEARCH}(?:未生效|还未生效|尚未生效|没生效)(?:的)?e生保(?:保单)?(?:的客户|客户)?'
      - '{SEARCH}e生保(?:还?没有生效|还没生效)(?:的客户|客户)?'
    field: "polNoInfo.plancodeinfo.abbrname"
    operator: "MATCH"
    value_type: "static"
    value: "e生保"
    extra_conditions:
      - field: "polNoInfo.polStatus"
        operator: "NOT_CONTAINS"
        value:
          - "交费有效"
          - "自垫交清"
          - "交清"
          - "减额交清"
          - "免交"
          - "自垫有效"
    priority: 10
    merge_to_llm: true

  # ==================== 应缴日 (policies_pay_date) ====================

  - name: "应缴日-七月"
    is_supported: true
    patterns:
      - '{SEARCH}(?:7|七)月(?:份)?{CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?(?:7|七)月(?:份)?(?:的客户|客户|名单|的人|人)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "static"
    value:
      min: "2026-07-01 00:00:00"
      max: "2026-07-31 23:59:59"
    priority: 10
    merge_to_llm: true

  - name: "应缴日-精确"
    is_supported: true
    patterns:
      - '{SEARCH}(?:保单)?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日)(?:为|是|在|：|:)?(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?)(?:的保单客户|保单客户|的客户|客户)?'
      - '{SEARCH}(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?)(?:应缴|缴费)(?:的客户|客户)?'
      - '{SEARCH}(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日)(?:在)?(\d{4})年(\d{1,2})月(\d{1,2})?日?(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年(\d{1,2})月(\d{1,2})[号日]?(?:要|需要|该|应)?(?:交|缴)(?:保费|费)(?:的保单客户|保单客户|的客户|客户|名单|的人|人)?'
      - '{SEARCH}(?:要|需要|该|应)?(?:交|缴)(?:保费|费)(?:的)?(?:客户)?(?:在|是|为)?(\d{4})年(\d{1,2})月(\d{1,2})[号日]?(?:的保单客户|保单客户|的客户|客户|名单|的人|人)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "year_month_day"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    merge_to_llm: true

  - name: "应缴日-月日精确"
    is_supported: true
    patterns:
      - '{SEARCH}(\d{1,2})月(\d{1,2})[号日]?(?:要|需要|该|应)?(?:交|缴)(?:保费|费)(?:的保单客户|保单客户|的客户|客户|名单|的人|人)?'
      - '{SEARCH}(?:要|需要|该|应)?(?:交|缴)(?:保费|费)(?:的)?(?:客户)?(?:在|是|为)?(\d{1,2})月(\d{1,2})[号日]?(?:的保单客户|保单客户|的客户|客户|名单|的人|人)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "year_month_day"
      current_year_if_missing: true
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    merge_to_llm: true

  - name: "应缴日-存在"
    is_supported: true
    patterns:
      - '{SEARCH}(?:要|需要|该|应)(?:交|缴)(?:保费|费)(?:的保单客户|保单客户|的客户|客户|名单|的人|人)?'
      - '{SEARCH}(?:待|需)(?:交|缴)(?:保费|费)(?:的保单客户|保单客户|的客户|客户|名单|的人|人)?'
    field: "polNoInfo.paytodate"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 6
    merge_to_llm: true

  - name: "应缴日-即将交费"
    is_supported: true
    patterns:
      - '{SEARCH}(?:即将|快要|快|近期)(?:应缴|缴费|应交|交费)(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}(?:即将|快要|快|近期)(?:要|需要|该|应)?(?:交|缴)(?:保费|费)?(?:的客户|客户|名单|的人|人)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days: 30
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 11
    merge_to_llm: true

  - name: "应缴日-本月"
    is_supported: true
    patterns:
      - '{SEARCH}本月{CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}本月{CW}{0,2}(?:要|需要|该|应)(?:交|缴)(?:保费|费)(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在本月(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?本月(?:的客户|客户)?'
      - '{SEARCH}这个?月{CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}这个?月{CW}{0,2}(?:要|需要|该|应)(?:交|缴)(?:保费|费)(?:的客户|客户|名单|的人|人)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_month"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "应缴日-下月"
    is_supported: true
    patterns:
      - '{SEARCH}下个?月{CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在下个?月(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?下个?月(?:的客户|客户)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_month"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "应缴日-今天"
    is_supported: true
    patterns:
      - '{SEARCH}(?:今天|今日|当天){CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?(?:今天|今日|当天)(?:的客户|客户)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "today"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "应缴日-明天"
    is_supported: true
    patterns:
      - '{SEARCH}(?:明天|明日){CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?(?:明天|明日)(?:的客户|客户)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "tomorrow"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "应缴日-后天"
    is_supported: true
    patterns:
      - '{SEARCH}(?:后天){CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?后天(?:的客户|客户)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "day_after_tomorrow"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "应缴日-本周"
    is_supported: true
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?(?:本周|这周|这个星期)(?:的客户|客户)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "应缴日-下周"
    is_supported: true
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?(?:下周|下星期|下个星期)(?:的客户|客户)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "应缴日-下下周"
    is_supported: true
    patterns:
      - '{SEARCH}(?:下下周|下下星期|下下个星期){CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?(?:下下周|下下星期|下下个星期)(?:的客户|客户)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 2
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    merge_to_llm: true

  - name: "应缴日-未来N天"
    is_supported: true
    patterns:
      - '{SEARCH}(?:未来|接下来|之后)(\d+)天(?:内|里)?{CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?(?:未来|接下来|之后)(\d+)天(?:内|里)?(?:的客户|客户)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days_group: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "应缴日-近N天"
    is_supported: true
    patterns:
      - '{SEARCH}(?:近|最近|过去)(\d+)天(?:内|里)?{CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?(?:近|最近|过去)(\d+)天(?:内|里)?(?:的客户|客户)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days_group: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "应缴日-上月"
    is_supported: true
    patterns:
      - '{SEARCH}上个?月{CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?上个?月(?:的客户|客户)?'
      - '{SEARCH}(?:上个月|上月){CW}{0,4}(?:刚)?(?:缴完费|交完费|缴过费|交过费)(?:的客户|客户|的人|人|的)?(?:[，,](?:翻翻|看看|查查|查查有没有漏|看看漏了没).*)?'
      - '{SEARCH}(?:刚)?(?:缴完费|交完费|缴过费|交过费){CW}{0,4}(?:在)?(?:上个月|上月)(?:的客户|客户|的人|人|的)?(?:[，,](?:翻翻|看看|查查|查查有没有漏|看看漏了没).*)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_month"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "应缴日-今年"
    is_supported: true
    patterns:
      - '{SEARCH}今年{CW}{0,2}(?:应缴|缴费|应交|交费)(?:的客户|客户)?'
      - '{SEARCH}有?(?:应缴日|缴费日|应缴时间|下次缴费时间|交费时间|交费日|应交时间|下次交费时间|应交日){CW}{0,2}在?今年(?:的客户|客户)?'
    field: "polNoInfo.paytodate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  # ==================== 核保结论 (policies_whole_decision) ====================

#  - name: "核保结论"
#    is_supported: false
#    patterns:
#      - '{SEARCH}(?:核保结论|核保结果|人工核保结论|人核结论|智核结论)(?:为|是|包含)?([\u4e00-\u9fa5A-Za-z0-9]{2,20})(?:的客户|客户)?'
#    field: "polNoInfo.wholeDecision"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 9

  # ==================== 投保险种名称 (policies_plan_fullname) ====================

  - name: "投保险种名称"
    is_supported: true
    ignore_case: true
    enum_ref: "polNoInfo.plancodeinfo.planfullname"
    patterns_template:
      - '{SEARCH}(?:投保险种全称|投保险种名称|险种全称|保险险种名称)(?:为|是|包含)?{enum}(?:的客户|客户)?'
      - '{SEARCH}{enum}(?:险种全称|投保险种名称)(?:的客户|客户)?'
      - '{SEARCH}(?:投保了|买了|购买了|买过|投保过|购买过)?{enum}(?:产品|险种)?(?:的客户|客户|的)?'
    field: "polNoInfo.plancodeinfo.planfullname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 10
    merge_to_llm: true

  - name: "未持有-投保险种名称"
    is_supported: true
    ignore_case: true
    enum_ref: "polNoInfo.plancodeinfo.planfullname"
    patterns_template:
      - '{SEARCH}(?:投保险种全称|险种全称|保险险种名称)(?:不为|不是|不包含|没包含|没有){enum}(?:的客户|客户)?'
    field: "polNoInfo.plancodeinfo.planfullname"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 11
    merge_to_llm: true

  # ==================== 投保险种简称 (policies_plan_abbr_name) ====================

  - name: "投保险种简称"
    is_supported: true
    ignore_case: true
    enum_ref: "polNoInfo.plancodeinfo.abbrname"
    patterns_template:
      - '{SEARCH}(?:投保险种名|投保险种简称|险种简称)(?:为|是|包含)?{enum}(?:的客户|客户)?'
      - '{SEARCH}(?:已投保|已购买|已买|投保了|买了|购买了|买过|投保过|购买过|配置了|有|有配置){enum}(?:产品|险种|服务)?(?:的客户|客户|的)?'
      - '{SEARCH}(?<!无)(?<!没有){enum}(?:产品|险种|服务)?(?:的客户|客户|的)?'
      - '{SEARCH}(?:已投保|已购买|已买|投保了|买了|购买了|买过|投保过|购买过|配置了|有|有配置){enum}(?:产品|险种|服务)?(?:的)?'
    field: "polNoInfo.plancodeinfo.abbrname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 10
    merge_to_llm: false

  - name: "未持有-投保险种简称"
    is_supported: true
    ignore_case: true
    enum_ref: "polNoInfo.plancodeinfo.abbrname"
    patterns_template:
      - '{SEARCH}(?:投保险种名|投保险种简称|险种简称)(?:不为|不是|不包含|没包含|没有){enum}(?:的客户|客户)?'
      - '{SEARCH}(?:未投保了|没购买了|没买过|没投保过|没购买|没买过|没买|未买|未投保|缺失|缺少|没有|不包含|未包含){enum}(?:产品|险种)?(?:的客户|客户|的)?'
      - '哪些客户(?:未投保了|没购买了|没买过|没投保过|没购买|没买过|没买|未买|未投保|缺失|缺少|没有|不包含|未包含){enum}(?:产品|险种)?(?:的)?'
    field: "polNoInfo.plancodeinfo.abbrname"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 11
    merge_to_llm: true

  # ==================== 投保险种类型 (policies_plan_type) ====================

  - name: "投保险种类型"
    is_supported: true
    enum_ref: "polNoInfo.plancodeinfo.plantypedesc"
    patterns_template:
      - '{SEARCH}(?:投保险种类型|投保险种|险种类型)(?:为|是|包含)?{enum}(?:的客户|客户)?'
      - '{SEARCH}{enum}(?:险种|投保险种)(?:的客户|客户)?'
      - '{SEARCH}(?:买了|购买了|买过|购买过|持有)?{enum}(?:产品|保单)?(?:的客户|客户)?'
      - '哪些客户持有{enum}保单'
    field: "polNoInfo.plancodeinfo.plantypedesc"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 9
    merge_to_llm: false

  # ==================== 受益人姓名 (policies_beneficiary_name) ====================

  - name: "受益人姓名"
    is_supported: true
    patterns:
      - '{SEARCH}(?:保单)?(?:受益人姓名|受益人名字)(?:为|是)?([\u4e00-\u9fa5]{2,4}?)(?:的保单客户|保单客户|的客户|客户)?'
      - '{SEARCH}(?:保单)?(?:受益人叫|受益人是|受益人为)([\u4e00-\u9fa5]{2,4}?)(?:的保单客户|保单客户|的客户|客户)?'
      - '哪些客户的受益人叫([\u4e00-\u9fa5]{2,4})'
    field: "polNoInfo.benefinfo.benefname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 9
    merge_to_llm: true

  # ==================== 理赔时间 (polNoInfo.claimdatainfo.claimdate) ====================

  - name: "理赔时间-精确"
    is_supported: true
    patterns:
      - '{SEARCH}(?:理赔时间|理赔日期)[为是：:]?(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?)(?:的客户|客户)?'
      - '{SEARCH}(?:理赔时间|理赔日期)(?:在)?(\d{4})年(\d{1,2})月(\d{1,2})?日?(?:发生)?理赔?(?:的客户|客户)?'
      - '{SEARCH}(?:在)?(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?)(?:发生)?理赔(?:过)?(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "year_month_day"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    merge_to_llm: true

  - name: "理赔时间-今年"
    is_supported: true
    patterns:
      - '{SEARCH}(?:今年|本年){CW}{0,2}理赔(?:的客户|客户)?'
      - '{SEARCH}理赔时间{CW}{0,2}在今年(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    merge_to_llm: true

  - name: "理赔记录-存在"
    is_supported: true
    patterns:
      - '{SEARCH}(?:有|存在|发生过|有过)(?:理赔|理赔记录)(?:的客户|客户|的人|人)?'
      - '{SEARCH}(?:理赔客户|有理赔客户|有理赔记录的客户)(?:有哪些|有谁|名单)?'
      - '{SEARCH}(?:出过险|理赔过)(?:的客户|客户|的人|人)?'
      - '{SEARCH}(?:这批|这些|那些)?理赔的?(?:客户|人|这批|这些|那些)?'
      - '{SEARCH}(?:理赔时间|理赔日期|理赔客户|理赔记录|有理赔记录|出过险)(?:从晚到早|从早到晚|升序|降序)?(?:排|排序|排列|排个序|排一排|排排|看看|出单子)?'
      - '.*(?:理赔时间|理赔日期|理赔客户|理赔记录|有理赔记录|出过险).*(?:从晚到早|从早到晚|升序|降序|排|排序|排列|看看|出单子).*'
    field: "polNoInfo.claimdatainfo.claimplancodename"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 12
    merge_to_llm: true

  - name: "理赔时间-去年"
    is_supported: true
    patterns:
      - '{SEARCH}(?:去年|上一年){CW}{0,2}理赔(?:的客户|客户)?'
      - '{SEARCH}理赔时间{CW}{0,2}在(?:去年|上一年)(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_year"
      format: "yyyy-MM-dd"
    priority: 10
    merge_to_llm: true

  - name: "理赔时间-本月"
    is_supported: true
    patterns:
      - '{SEARCH}(?:本月|这个月){CW}{0,2}理赔(?:的客户|客户)?'
      - '{SEARCH}理赔时间{CW}{0,2}(?:在|为|是)(?:本月|这个月)(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_month"
      format: "yyyy-MM-dd"
    priority: 10
    merge_to_llm: true

  - name: "理赔时间-N天内"
    is_supported: true
    patterns:
      - '{SEARCH}(?:近|最近)(\d+)天{CW}{0,2}理赔(?:的客户|客户)?'
      - '{SEARCH}理赔时间{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里)?(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days_group: 1
      format: "yyyy-MM-dd"
    priority: 10
    merge_to_llm: true

  - name: "理赔时间-最近一个月"
    is_supported: true
    patterns:
      - '{SEARCH}(?:近|最近)一个月{CW}{0,2}理赔(?:的客户|客户)?'
      - '{SEARCH}(?:近期|最近)有?理赔过?(?:的客户|客户)?'
      - '{SEARCH}理赔时间{CW}{0,2}在(?:近|最近)一个月(?:内|里)?(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days: 30
      format: "yyyy-MM-dd"
    priority: 10
    merge_to_llm: true

  - name: "理赔时间-今天"
    is_supported: true
    patterns:
      - '{SEARCH}(?:今天|今日|当天){CW}{0,2}理赔(?:过)?(?:的客户|客户)?'
      - '{SEARCH}理赔时间{CW}{0,2}在?(?:今天|今日|当天)(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "today"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    merge_to_llm: true

  - name: "理赔时间-本周"
    is_supported: true
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}理赔(?:过)?(?:的客户|客户)?'
      - '{SEARCH}理赔时间{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期)(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    merge_to_llm: true

  - name: "理赔时间-上周"
    is_supported: true
    patterns:
      - '{SEARCH}(?:上周|上星期|上个星期){CW}{0,2}理赔(?:过)?(?:的客户|客户)?'
      - '{SEARCH}理赔时间{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期)(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: -1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    merge_to_llm: true

  - name: "理赔时间-近一周"
    is_supported: true
    patterns:
      - '{SEARCH}(?:近|最近|过去)一周(?:内|里)?{CW}{0,2}理赔(?:过)?(?:的客户|客户)?'
      - '{SEARCH}理赔时间{CW}{0,2}在(?:近|最近|过去)一周(?:内|里)?(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days: 7
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    merge_to_llm: true

  - name: "理赔时间-近半年"
    is_supported: true
    patterns:
      - '{SEARCH}(?:近|最近|过去)半年(?:内|里)?{CW}{0,2}(?:有)?理赔(?:过|记录)?(?:的客户|客户)?'
      - '{SEARCH}(?:近|最近|过去)半年(?:内|里)?{CW}{0,2}有理赔(?:记录)?(?:的客户|客户)?'
      - '{SEARCH}理赔时间{CW}{0,2}在(?:近|最近|过去)半年(?:内|里)?(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "past_n_months_to_today"
      months: 6
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 11
    merge_to_llm: true

  - name: "理赔时间-年份"
    is_supported: true
    patterns:
      - '{SEARCH}理赔时间{CW}{0,2}在?(\d{4})年(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年{CW}{0,2}理赔(?:过)?(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 8
    merge_to_llm: true

  - name: "理赔时间-年月"
    is_supported: true
    patterns:
      - '{SEARCH}理赔时间{CW}{0,2}在?(\d{4}年\d{1,2}月)(?:的客户|客户)?'
      - '{SEARCH}(\d{4}年\d{1,2}月){CW}{0,2}理赔(?:过)?(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimdate"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_month_cn_range"
    priority: 10
    merge_to_llm: true

  # ==================== 理赔险种 (policies_claim_records_coverage) ====================

  - name: "指定理赔险种-有理赔"
    is_supported: true
    enum_ref: "polNoInfo.claimdatainfo.claimplancodename"
    patterns_template:
      - '{SEARCH}(?:理赔险种|获赔险种)(?:为|是|包含)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<!没)(?<!未)(?<!无)(?:曾经|曾|之前)?(?:有过|发生过|出现过)?(?<!没有过)(?<!没发生)(?<!未发生)(?<!从未有过){enum}(?:的)?(?:理赔|获赔|赔付)(?:过|记录)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<!没有)(?<!没)(?<!未)(?:曾经|曾|之前)?(?:理赔过|获赔过|赔付过){enum}{CUSTOMER_SUFFIX}'
    field: "polNoInfo.claimdatainfo.claimplancodename"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 9
    merge_to_llm: true

  - name: "指定理赔险种-无理赔"
    is_supported: true
    enum_ref: "polNoInfo.claimdatainfo.claimplancodename"
    patterns_template:
      - '{SEARCH}(?:没有过|没发生过?|未发生过?|从未有过){enum}(?:的)?(?:理赔|获赔|赔付)(?:记录)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:没有|没|未|从未)(?:发生过?)?(?:理赔|获赔|赔付)(?:过|记录)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:未理赔过|没有理赔过|没理赔过|未获赔过){enum}{CUSTOMER_SUFFIX}'
    field: "polNoInfo.claimdatainfo.claimplancodename"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value:
      group: 1
    priority: 10
    merge_to_llm: true

  # ==================== 人群 ====================

  - name: "宝妈"
    patterns:
      - '{SEARCH}宝妈(?:的客户|客户)?'
    field: "clientSex"
    operator: "MATCH"
    value_type: "static"
    value: "女"
    priority: 9
    merge_to_llm: true
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientage"
        operator: "RANGE"
        value:
          min: 0
          max: 6

  - name: "单亲"
    patterns:
      - '{SEARCH}(?:单亲|单亲家庭)(?:的客户|客户)?'
    field: "familyInfo.familyrelation"
    operator: "MATCH"
    value_type: "static"
    value: "子女"
    priority: 9
    extra_conditions:
      - field: "mariSts"
        operator: "CONTAINS"
        value: [ "离婚", "丧偶", "未婚" ]
    merge_to_llm: true

  # ==================== 客户类型 (isBuyInsurance) ====================

  - name: "客户类型-全部客户"
    patterns:
      - '{SEARCH}(?:全部|所有|全量|全体|我名下|我|我下面｜我负责)(?:的)?客户(?:名单)?'
    field: "isBuyInsurance"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "客户"
      - "准客"
      - "用户"
    query_logic: "OR"
    priority: 30
    merge_to_llm: false

  - name: "客户类型-客户"
    patterns:
      - '{SEARCH}客户'
      - '{SEARCH}客户类型(?:为|是)?客户(?:的客户|客户)?'
    field: "isBuyInsurance"
    operator: "MATCH"
    value_type: "static"
    value: "客户"
    priority: 22
    merge_to_llm: false

  - name: "盘客-暂不支持"
    patterns:
      - '{SEARCH}(?:(?:\d{1,2}|一|二|两|三|四|五|六|七|八|九|十|十一|十二)月(?:份)?)?(?:客户)?(?:去|做|进行)?盘客(?:的客户|客户|名单)?'
      - '{SEARCH}(?:去|做|进行)盘客(?:的客户|客户|名单)?'
    field: "customerReview"
    operator: "MATCH"
    value_type: "static"
    value: "盘客"
    priority: 25
    merge_to_llm: false

#  - name: "客户活动-暂不支持"
#    patterns:
#      - '{SEARCH}([\u4e00-\u9fa5A-Za-z0-9·]{2,30}(?:活动|活动季|守护季))(?:的客户|客户|名单)?'
#    field: "customerActivity"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 25
#    merge_to_llm: false

  - name: "客户未兑换积分下限-万-暂不支持"
    patterns:
      - '{SEARCH}(\d+)万积分(?:及?以上|不少于|不低于|大于等于|≥|>=)(?:尚未|还未|未)(?:兑换|兑)(?:的客户|客户|名单)?'
      - '{SEARCH}积分(?:余额)?(?:不少于|不低于|大于等于|达到|达|≥|>=)(\d+)万(?:且|并且|并|同时)?(?:尚未|还未|未)(?:兑换|兑)(?:的客户|客户|名单)?'
      - '{SEARCH}(?:尚未|还未|未)(?:兑换|兑)(?:的)?积分(?:余额)?(?:不少于|不低于|大于等于|达到|达|≥|>=)(\d+)万(?:的客户|客户|名单)?'
      - '{SEARCH}(?:尚未|还未|未)(?:兑换|兑)(?:的)?积分(?:余额)?(\d+)万及?以上(?:的客户|客户|名单)?'
    field: "customerUnredeemedPoints"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 25
    merge_to_llm: false

  - name: "客户未兑换积分下限-暂不支持"
    patterns:
      - '{SEARCH}(\d+)积分(?:及?以上|不少于|不低于|大于等于|≥|>=)(?:尚未|还未|未)(?:兑换|兑)(?:的客户|客户|名单)?'
      - '{SEARCH}积分(?:余额)?(?:不少于|不低于|大于等于|达到|达|≥|>=)(\d+)(?:且|并且|并|同时)?(?:尚未|还未|未)(?:兑换|兑)(?:的客户|客户|名单)?'
      - '{SEARCH}(?:尚未|还未|未)(?:兑换|兑)(?:的)?积分(?:余额)?(?:不少于|不低于|大于等于|达到|达|≥|>=)(\d+)(?:的客户|客户|名单)?'
      - '{SEARCH}(?:尚未|还未|未)(?:兑换|兑)(?:的)?积分(?:余额)?(\d+)及?以上(?:的客户|客户|名单)?'
    field: "customerUnredeemedPoints"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 25
    merge_to_llm: false

  - name: "客户类型-买过保险"
    patterns:
      - '{SEARCH}(?:已配置|已投保|购买了|购买|配置了|配置|配置有|配有|投保了|投保过|购买过|投保|买过|买了|已有|有了|有过|持有|有买|有购买|有)保险(?:的客户|客户|的)?'
    field: "isBuyInsurance"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "客户"
      - "准客"
    priority: 9
    merge_to_llm: true

  - name: "客户类型-没买过保险"
    patterns:
      - '{SEARCH}(?:没有配置|未配置|没配置|未购买|没买|未买|缺少|缺失|没有|没|未|不是|缺|非|未投保|没投保)保险(?:的客户|客户|的)?'
    field: "isBuyInsurance"
    operator: "MATCH"
    value_type: "static"
    value: "用户"
    priority: 9
    merge_to_llm: true

  - name: "已签过单老客户-保单生效"
    patterns:
      - '{SEARCH}(?:自己｜我｜代理人)?名下已签过单的老客户'
    field: "polNoInfo.poleffdate"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 23
    merge_to_llm: false

  # ==================== 产险/养老/健康险 (isBuy*) ====================

  - name: "有产险"
    patterns:
      - '{SEARCH}(?:已配置|已投保|购买了|购买|配置了|配置|配置有|配有|投保了|投保过|购买过|投保|买过|买了|已有|有了|有过|持有|有买|有购买|有)产险(?:的客户|客户|的)?'
    field: "isBuyProperty"
    operator: "MATCH"
    value_type: "static"
    value: "有购买"
    priority: 9
    merge_to_llm: true

  - name: "没有产险"
    patterns:
      - '{SEARCH}(?:没有配置|未配置|没配置|未购买|没买|未买|缺少|缺失|没有|没|未|不是|缺|非|没有买)产险(?:的客户|客户|的)?'
    field: "isBuyProperty"
    operator: "MATCH"
    value_type: "static"
    value: "没有购买"
    priority: 9
    merge_to_llm: true

  - name: "有养老险"
    patterns:
      - '{SEARCH}(?:已配置|已投保|已购买|购买了|购买|配置了|配置|配置有|配有|投保了|投保过|购买过|投保|买过|买了|已有|有了|有过|持有|有买|有购买|有|是)养老险(?:的客户|客户|的)?'
      - '{SEARCH}(?<![没无非])(?<!不是)养老险(?:的)?客户(?:名单|有哪些人|有哪些|的人|人|的客户|客户|的)?'
    field: "isBuyPension"
    operator: "MATCH"
    value_type: "static"
    value: "有购买"
    priority: 9
    merge_to_llm: true

  - name: "没有养老险"
    patterns:
      - '{SEARCH}(?:没有配置|未配置|没配置|未购买|没买|未买|缺少|缺失|没有|没|未|不是|缺|非|没有买)养老险(?:的客户|客户|的)?'
    field: "isBuyPension"
    operator: "MATCH"
    value_type: "static"
    value: "没有购买"
    priority: 9
    merge_to_llm: true

  - name: "有健康险"
    patterns:
      - '{SEARCH}(?:已配置|已投保|购买了|购买|配置了|配置|配置有|配有|投保了|投保过|购买过|投保|买过|买了|已有|有了|有过|持有|有买|有购买|有|是)健康险(?:的客户|客户|的)?'
    field: "isBuyHealth"
    operator: "MATCH"
    value_type: "static"
    value: "有购买"
    priority: 9
    merge_to_llm: true

  - name: "没有健康险"
    patterns:
      - '{SEARCH}(?:没有配置|未配置|没配置|未购买|没买|未买|缺少|缺失|没有|没|未|不是|缺|非|没购买|没有买)健康险(?:的客户|客户|的)?'
    field: "isBuyHealth"
    operator: "MATCH"
    value_type: "static"
    value: "没有购买"
    priority: 9
    merge_to_llm: true

  # ==================== 保单生效日 (polNoInfo.poleffdate) ====================

  - name: "保单生效日-签单业务近N年"
    patterns:
      - '{SEARCH}(?:近|最近|过去|这)([0-9一二两三四五六七八九十百]+)年(?:内|里|之内)?(?:成交|签约|签单){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:成交|签约|签单)(?:时间|日期)?(?:在|为|是)?(?:近|最近|过去|这)([0-9一二两三四五六七八九十百]+)年(?:内|里|之内)?{CUSTOMER_SUFFIX}'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "past_n_years_to_today"
      years_group: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "保单生效日-精确"
    patterns:
      - '{SEARCH}(?:保单)?生效日(?:为|是|在|：)?(\d{4}-\d{2}-\d{2})(?:的客户|客户)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "year_month_day"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-近N天"
    patterns:
      - '{SEARCH}(?:近|最近|过去){CW}{0,2}(\d+)天(?:内|里)?(?:保单)?生效的?(?:的客户|客户)?'
      - '{SEARCH}(?:保单)?生效(?:日)?{CW}{0,2}(?:近|最近|过去){CW}{0,2}(\d+)天(?:内|里)?的?(?:的客户|客户)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days_group: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-近一周"
    patterns:
      - '{SEARCH}(?:近|最近|过去)一周(?:内|里)?(?:保单)?生效的?(?:的客户|客户)?'
      - '{SEARCH}(?:保单)?生效(?:日)?{CW}{0,2}(?:近|最近|过去)一周(?:内|里)?的?(?:的客户|客户)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days: 7
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-近一个月"
    patterns:
      - '{SEARCH}(?:近|最近|过去)一个?月(?:内|里)?(?:保单)?生效的?(?:的客户|客户)?'
      - '{SEARCH}(?:保单)?生效(?:日)?{CW}{0,2}(?:近|最近|过去)一个?月(?:内|里)?的?(?:的客户|客户)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "past_month_to_today"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-新生效口语"
    patterns:
      - '{SEARCH}(?:新生效|刚生效|最近生效)(?:的)?(?:这些|这批|那些)?(?:保单|客户)(?:有哪些|有谁)?'
      - '{SEARCH}(?:这些|这批|那些)?(?:保单|客户)(?:新生效|刚生效|最近生效)'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days: 30
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 11
    merge_to_llm: true

  - name: "保单生效日-即将生效"
    patterns:
      - '{SEARCH}(?:保单)?(?:即将生效|近期生效)的?(?:的客户|客户|保单)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_n_days"
      days: 30
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10
    merge_to_llm: true

  - name: "保单生效日-本月"
    patterns:
      - '{SEARCH}(?:本月|这个月|当月){CW}{0,2}(?:保单)?生效(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单)?生效(?:日|时间|日期)?{CW}{0,2}在?(?:本月|这个月|当月)(?:的客户|客户|保单)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_month"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-下月"
    patterns:
      - '{SEARCH}下个?月{CW}{0,2}(?:保单)?生效(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单)?生效(?:日|时间|日期)?{CW}{0,2}在?下个?月(?:的客户|客户|保单)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "next_month"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-本周"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:保单)?生效(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单)?生效(?:日|时间|日期)?{CW}{0,2}在?(?:本周|这周|这个星期)(?:的客户|客户|保单)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-下周"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:保单)?生效(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单)?生效(?:日|时间|日期)?{CW}{0,2}在?(?:下周|下星期|下个星期)(?:的客户|客户|保单)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-下下周"
    patterns:
      - '{SEARCH}(?:下下周|下下星期|下下个星期){CW}{0,2}(?:保单)?生效(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单)?生效(?:日|时间|日期)?{CW}{0,2}在?(?:下下周|下下星期|下下个星期)(?:的客户|客户|保单)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 2
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-今天"
    patterns:
      - '{SEARCH}(?:今天|今日|当天){CW}{0,2}(?:保单)?生效(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单)?生效(?:日|时间|日期)?{CW}{0,2}在?(?:今天|今日|当天)(?:的客户|客户|保单)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "today"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-明天"
    patterns:
      - '{SEARCH}(?:明天|明日){CW}{0,2}(?:保单)?生效(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单)?生效(?:日|时间|日期)?{CW}{0,2}在?(?:明天|明日)(?:的客户|客户|保单)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "tomorrow"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-后天"
    patterns:
      - '{SEARCH}后天{CW}{0,2}(?:保单)?生效(?:的客户|客户|保单)?'
      - '{SEARCH}(?:保单)?生效(?:日|时间|日期)?{CW}{0,2}在?后天(?:的客户|客户|保单)?'
    field: "polNoInfo.poleffdate"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "day_after_tomorrow"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-某年之后"
    patterns:
      - '{SEARCH}(?:保单)?生效(?:日|时间)?(?:在)?(\d{4})年之后(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年之后(?:保单)?生效(?:的客户|客户)?'
    field: "polNoInfo.poleffdate"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-某年及之后"
    patterns:
      - '{SEARCH}(?:保单)?生效(?:日|时间)?(?:在)?(\d{4})年及之后(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年及之后(?:保单)?生效(?:的客户|客户)?'
      - '{SEARCH}(?:保单)?生效(?:日|时间)?(?:不低于|不少于|大于等于|>=|≥)(\d{4})年(?:的客户|客户)?'
    field: "polNoInfo.poleffdate"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_start_datetime"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-某年之前"
    patterns:
      - '{SEARCH}(?:保单)?生效(?:日|时间)?(?:在)?(\d{4})年之前(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年之前(?:保单)?生效(?:的客户|客户)?'
    field: "polNoInfo.poleffdate"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "year_end_datetime"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-某年及之前"
    patterns:
      - '{SEARCH}(?:保单)?生效(?:日|时间)?(?:在)?(\d{4})年及之前(?:的客户|客户)?'
      - '{SEARCH}(\d{4})年及之前(?:保单)?生效(?:的客户|客户)?'
      - '{SEARCH}(?:保单)?生效(?:日|时间)?(?:不超过|不大于|小于等于|<=|≤)(\d{4})年(?:的客户|客户)?'
    field: "polNoInfo.poleffdate"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "year_end_datetime"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "保单生效时间-已生效"
    patterns:
      - '{SEARCH}(?:保单)(?:已生效|已经生效|生效了)(?:的客户|客户)?'
      - '{SEARCH}(?:已生效|已经生效|生效了)的?(?:保单)(?:的客户|客户)?'
    field: "polNoInfo.poleffdate"
    operator: "LTE"
    value_type: "date_range_dynamic"
    value:
      date_range: "today_plus_n_days"
      days: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 10

  - name: "保单生效日-存在"
    patterns:
      - '{SEARCH}有(?:保单)?生效(?:日|时间|日期)(?:的客户|客户)?'
      - '{SEARCH}(?:保单)?生效(?:日|时间|日期)?(?:保单)?(?:从晚到早|从早到晚|升序|降序)?(?:排|排序|排列|排个序|排一排|排排|看看)?'
      - '{SEARCH}(?:新生效|刚生效|生效保单)(?:这些|这批)?(?:保单|客户)?(?:从晚到早|从早到晚|升序|降序)?(?:排|排序|排列|排个序|排一排|排排|看看)?'
      - '.*(?:生效日|生效时间|生效日期|新生效|刚生效|生效保单).*(?:从晚到早|从早到晚|升序|降序|排|排序|排列|看看).*'
    field: "polNoInfo.poleffdate"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 9
    merge_to_llm: true

  - name: "保单生效日-不存在"
    patterns:
      - '{SEARCH}(?:没有|无|未)有?(?:保单)?生效(?:日|时间|日期)(?:的客户|客户)?'
    field: "polNoInfo.poleffdate"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 9
    merge_to_llm: true

  # ==================== 客户添加日 (dateCreated) ====================

  - name: "客户添加日-近N年"
    patterns:
      - '{SEARCH}(?:最近|近|过去|这)?([0-9一二两三四五六七八九十百]+)年(?:内|以内|之内)?(?:的)?(?:客户名单|客户|名单)'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "past_n_years_to_today"
      years_group: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 18
    merge_to_llm: false

  - name: "客户添加日-明确年月区间名单"
    patterns:
      - '{SEARCH}(\d{4})年(\d{1,2})月?[-~到至](\d{1,2})月(?:份)?(?:新增|添加|录入|建档|创建)?(?:客户)?(?:名单|客户)'
      - '{SEARCH}(?:新增|添加|录入|建档|创建)(?:日期|时间|日)?(?:在)?(\d{4})年(\d{1,2})月?[-~到至](\d{1,2})月(?:份)?(?:的客户|客户|名单)?'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "explicit_year_month_range"
      year_group: 1
      start_month_group: 2
      end_month_group: 3
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 18
    merge_to_llm: false

  - name: "客户添加日-近N天"
    patterns:
      - '{SEARCH}(?:近|最近|过去){CW}{0,2}(\d+)天(?:内|里)?(?:新增|添加|录入|建档|创建)的?(?:的客户|客户)?'
      - '{SEARCH}(?:新增|添加|录入|建档|创建){CW}{0,2}(?:近|最近|过去){CW}{0,2}(\d+)天(?:内|里)?的?(?:的客户|客户)?'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days_group: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "客户添加日-近一周"
    patterns:
      - '{SEARCH}(?:近|最近|过去)一周(?:内|里)?(?:新增|添加|录入|建档|创建)的?(?:的客户|客户)?'
      - '{SEARCH}(?:新增|添加|录入|建档|创建){CW}{0,2}(?:近|最近|过去)一周(?:内|里)?的?(?:的客户|客户)?'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days: 7
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "客户添加日-近一个月"
    patterns:
      - '{SEARCH}(?:新客户|新客)(?:名单)?'
      - '{SEARCH}(?:近|最近|过去)一个?月(?:内|里)?(?:新增|添加|录入|建档|创建)的?(?:的客户|客户)?'
      - '{SEARCH}(?:新增|添加|录入|建档|创建){CW}{0,2}(?:近|最近|过去)一个?月(?:内|里)?的?(?:的客户|客户)?'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "past_month_to_today"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "客户添加日-本月"
    patterns:
      - '{SEARCH}(?:本月|这个月|当月){CW}{0,2}(?:新增|添加|录入|建档|创建)的?(?:的客户|客户)?'
      - '{SEARCH}(?:新增|添加|录入|建档|创建)(?:日期|时间|日)?{CW}{0,2}在?(?:本月|这个月|当月)(?:的客户|客户)?'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_month"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "客户添加日-上个月口语"
    patterns:
      - '{SEARCH}(?:最近发生.{0,3})?(?:上个月|上月){CW}{0,4}(?:新增|新加|添加|录入|建档|创建)(?:的)?(?:人|客户|新客)(?:跟进没|跟进了吗|有哪些|有谁|名单)?'
      - '{SEARCH}(?:上个月|上月)(?:新增|新加|添加|录入|建档|创建)(?:了)?(?:哪些|哪批)?(?:人|客户|新客)'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_month"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 12
    merge_to_llm: true

  - name: "客户添加日-本周"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:新增|添加|录入|建档|创建)的?(?:的客户|客户)?'
      - '{SEARCH}(?:新增|添加|录入|建档|创建)(?:日期|时间|日)?{CW}{0,2}在?(?:本周|这周|这个星期)(?:的客户|客户)?'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "客户添加日-上周"
    patterns:
      - '{SEARCH}(?:上周|上星期|上个星期){CW}{0,2}(?:新增|添加|录入|建档|创建)的?(?:的客户|客户)?'
      - '{SEARCH}(?:新增|添加|录入|建档|创建)(?:日期|时间|日)?{CW}{0,2}在?(?:上周|上星期|上个星期)(?:的客户|客户)?'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: -1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "客户添加日-今天"
    patterns:
      - '{SEARCH}(?:今天|今日|当天){CW}{0,2}(?:新增|添加|录入|建档|创建)的?(?:的客户|客户)?'
      - '{SEARCH}(?:新增|添加|录入|建档|创建)(?:日期|时间|日)?{CW}{0,2}在?(?:今天|今日|当天)(?:的客户|客户)?'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "today"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9
    merge_to_llm: true

  - name: "客户添加日-近期"
    patterns:
      - '{SEARCH}(?:最近|近期|新)(?:新增|添加|录入|建档|创建)的?(?:的客户|客户)?'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days: 30
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9

  - name: "客户添加日-存在"
    patterns:
      - '{SEARCH}有(?:添加|录入|建档|创建)(?:日期|时间|日)(?:的客户|客户|的)?'
    field: "dateCreated"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 9
    merge_to_llm: true

  - name: "客户添加日-不存在"
    patterns:
      - '{SEARCH}(?:没有|无|未)(?:添加|录入|建档|创建)(?:日期|时间|日)(?:的客户|客户|的)?'
    field: "dateCreated"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 9
    merge_to_llm: true

  - name: "客户添加日-精确"
    patterns:
      - '{SEARCH}(?:客户)?(?:新增|添加|录入|建档|创建)(?:日期|时间|日)(?:为|是|在|：)?(\d{4}-\d{2}-\d{2})(?:的客户|客户)?'
    field: "dateCreated"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "year_month_day"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 9

  # ==================== 期交保费 (polNoInfo.totmodalpremsum) ====================

  - name: "期交保费-以上"
    patterns:
      - '{SEARCH}每期(?:交|缴)(?:保费)?(?:超过|大于|>|高于)(\d+)万(?:的客户|客户|的)?'
      - '{SEARCH}(?:每个月|每月|每期)(?:交|缴)(?:保费)?(?:超过|大于|>|高于)(\d+)万(?:的客户|客户|的)?'
    field: "polNoInfo.totmodalpremsum"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9
    merge_to_llm: true

  - name: "期交保费-及以上"
    patterns:
      - '{SEARCH}期交?保费{CW}{0,2}(\d+)万及?以上(?:的客户|客户|的)?'
      - '{SEARCH}期交?保费(?:大于等于|大于或等于|不少于|不低于|>=|≥|及以上|以上)(\d+)万(?:的客户|客户|的)?'
      - '{SEARCH}(?:每个月|每月|每期)(?:交|缴)(?:保费)?(?:大于等于|大于或等于|不少于|不低于|>=|≥|及以上|以上)(\d+)万(?:的客户|客户|的)?'
    field: "polNoInfo.totmodalpremsum"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9
    merge_to_llm: true

  - name: "期交保费-以下"
    patterns:
      - '{SEARCH}期交?保费(?:小于|低于|<)(\d+)万(?:的客户|客户|的)?'
      - '{SEARCH}(?:每个月|每月|每期)(?:交|缴)(?:保费)?(?:小于|低于|<)(\d+)万(?:的客户|客户|的)?'
    field: "polNoInfo.totmodalpremsum"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9
    merge_to_llm: true

  - name: "期交保费-及以下"
    patterns:
      # 带"万"单位的
      - '{SEARCH}期交?保费{CW}{0,2}(\d+)万及?以下(?:的客户|客户|的)?'
      - '{SEARCH}期交?保费(?:小于等于|小于或等于|不超过|至多|<=|≤)(\d+)万(?:的客户|客户|的)?'
      - '{SEARCH}(?:每个月|每月|每期)(?:交|缴)(?:保费)?(?:小于等于|小于或等于|不超过|至多|<=|≤){CW}{0,2}(\d+)万(?:的客户|客户|的)?'
    field: "polNoInfo.totmodalpremsum"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9
    merge_to_llm: true

  - name: "期交保费-及以下-精确值"
    patterns:
      # 不带单位的精确值："期交保费不超过5000块的客户"
      - '{SEARCH}(?:期交?保费|每期(?:交|缴)(?:保费)?)(?:不超过|不大于|至多|<=|≤)(\d+)(?:块|元)?(?:的客户|客户|的)?'
      - '{SEARCH}(?:每个月|每月|每期)(?:交|缴)(?:保费)?(?:不超过|不大于|至多|<=|≤){CW}{0,2}(\d+)(?:块|元)?(?:的客户|客户|的)?'
    field: "polNoInfo.totmodalpremsum"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 10
    merge_to_llm: true

  - name: "期交保费-存在"
    patterns:
      - '{SEARCH}有期交?保费(?:的客户|客户)?'
      - '{SEARCH}(?:每期交得多|每期缴得多|每期保费高|期交保费高|期缴保费高)(?:的)?(?:客户|人|名单|有哪些|在哪)?'
      - '{SEARCH}(?:按|按照)?(?:每期保费|期交保费|期缴保费)(?:从大到小|从高到低|高低)?(?:排|排序|排列|排排|理一理)?'
      - '.*(?:每期交得多|每期缴得多|每期保费高|期交保费高|期缴保费高|按每期保费|按期交保费|按照期交保费).*'
    field: "polNoInfo.totmodalpremsum"
    operator: "GT"
    value_type: "static"
    value: 0
    priority: 9
    merge_to_llm: true

  # ==================== 期交保费-精确值 ====================
  - name: "期交保费-精确值"
    patterns:
      # 精确值匹配（不带"以上"/"以下"）："期交保费5000块的客户"、"期交保费500元的客户"、"每期交保费500元"
      - '{SEARCH}(?:期交?保费|每期(?:交|缴)(?:保费)?|每个月|每月|每期)(?:交|缴)?(?:等于|＝|是|为)?(\d+)(?:块|元)(?:的客户|客户|的)?'
    field: "polNoInfo.totmodalpremsum"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 1
    priority: 10
    merge_to_llm: true

  - name: "期交保费-精确值-万"
    patterns:
      # 精确值匹配（万）："期交保费2万的客户"
      - '{SEARCH}(?:期交?保费|每期(?:交|缴)(?:保费)?)(?:等于|＝|是|为)?(\d+)万(?:的客户|客户|的)?'
    field: "polNoInfo.totmodalpremsum"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 10000
    priority: 10
    merge_to_llm: true

  - name: "期交保费-精确值-千"
    patterns:
      # 精确值匹配（千）："期交保费5千的客户"
      - '{SEARCH}(?:期交?保费|每期(?:交|缴)(?:保费)?)(?:等于|＝|是|为)?(\d+)千(?:的客户|客户|的)?'
    field: "polNoInfo.totmodalpremsum"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 1000
    priority: 10
    merge_to_llm: true

#  # ==================== 犹豫期时间 (cooling_off_period_date) ====================
#
#  - name: "犹豫期-近N天到期"
#    patterns:
#      - '{SEARCH}(?:近|最近|未来){CW}{0,2}(\d+)天(?:内|里)?(?:犹豫期)?到期(?:的客户|客户)?'
#      - '{SEARCH}犹豫期{CW}{0,2}(?:近|最近|未来){CW}{0,2}(\d+)天(?:内|里)?(?:到期)?(?:的客户|客户)?'
#    field: "policies_cooling_off"
#    operator: "RANGE"
#    value_type: "date_range_dynamic"
#    value:
#      date_range: "next_n_days"
#      days_group: 1
#      format: "yyyy-MM-dd HH:mm:ss"
#    priority: 9
#
#  - name: "犹豫期-近一周到期"
#    patterns:
#      - '{SEARCH}(?:近|最近|未来)一周(?:内|里)?(?:犹豫期)?到期(?:的客户|客户)?'
#      - '{SEARCH}犹豫期{CW}{0,2}(?:近|最近|未来)一周(?:内|里)?(?:到期)?(?:的客户|客户)?'
#    field: "policies_cooling_off"
#    operator: "RANGE"
#    value_type: "date_range_dynamic"
#    value:
#      date_range: "next_n_days"
#      days: 7
#      format: "yyyy-MM-dd HH:mm:ss"
#    priority: 9
#
#  - name: "犹豫期-近一个月到期"
#    patterns:
#      - '{SEARCH}(?:近|最近|未来)一个?月(?:内|里)?(?:犹豫期)?到期(?:的客户|客户)?'
#      - '{SEARCH}犹豫期{CW}{0,2}(?:近|最近|未来)一个?月(?:内|里)?(?:到期)?(?:的客户|客户)?'
#    field: "policies_cooling_off"
#    operator: "RANGE"
#    value_type: "date_range_dynamic"
#    value:
#      date_range: "next_n_days"
#      days: 30
#      format: "yyyy-MM-dd HH:mm:ss"
#    priority: 9
#
#  - name: "犹豫期-已过期"
#    patterns:
#      - '{SEARCH}(?:犹豫期)?(?:已经?|已)(?:过|过了|到期)(?:的)?犹豫期?(?:的客户|客户)?'
#      - '{SEARCH}犹豫期(?:已经?|已)(?:过|过了|到期)(?:的客户|客户)?'
#    field: "policies_cooling_off"
#    operator: "LTE"
#    value_type: "date_range_dynamic"
#    value:
#      date_range: "today_plus_n_days"
#      days: 0
#      format: "yyyy-MM-dd HH:mm:ss"
#    priority: 10
#
#  - name: "犹豫期-存在"
#    patterns:
#      - '{SEARCH}有犹豫期(?:的客户|客户)?'
#      - '{SEARCH}犹豫期(?:不为空|有值)(?:的客户|客户)?'
#    field: "policies_cooling_off"
#    operator: "EXISTS"
#    value_type: "static"
#    value: ""
#    priority: 9
#
#  - name: "犹豫期-不存在"
#    patterns:
#      - '{SEARCH}(?:没有|无|未)(?:有)?犹豫期(?:的客户|客户)?'
#      - '{SEARCH}犹豫期(?:为空|没有值)(?:的客户|客户)?'
#    field: "policies_cooling_off"
#    operator: "NOT_EXISTS"
#    value_type: "static"
#    value: ""
#    priority: 9

  # ==================== 生存金利息总额 (policies_total_survival_benefit_interest) ====================

#  - name: "生存金利息总额-及以上"
#    patterns:
#      - '{SEARCH}生存金利息(?:总额?|总金额|总额度){CW}{0,2}(\d+)万及?以上(?:的客户|客户)?'
#      - '{SEARCH}生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:大于等于|不少于|不低于|>=|≥)(\d+)万(?:元)?(?:的客户|客户)?'
#    field: "policies_total_survival_benefit_interest"
#    operator: "GTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "生存金利息总额-以上"
#    patterns:
#      - '{SEARCH}生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:大于|高于|超过|>)(\d+)万(?:元)?(?:的客户|客户)?'
#    field: "policies_total_survival_benefit_interest"
#    operator: "GT"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "生存金利息总额-及以下"
#    patterns:
#      - '{SEARCH}生存金利息(?:总额?|总金额|总额度){CW}{0,2}(\d+)万及?以下(?:的客户|客户)?'
#      - '{SEARCH}生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:小于等于|不超过|<=|≤)(\d+)万(?:元)?(?:的客户|客户)?'
#    field: "policies_total_survival_benefit_interest"
#    operator: "LTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "生存金利息总额-以下"
#    patterns:
#      - '{SEARCH}生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:小于|低于|<)(\d+)万(?:元)?(?:的客户|客户)?'
#    field: "policies_total_survival_benefit_interest"
#    operator: "LT"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9

  # ==================== 生存金利息已领取总额 (policies_total_survival_benefit_interest_received) ====================

#  - name: "生存金利息已领取总额-及以上"
#    patterns:
#      - '{SEARCH}(?:已|已领取|已领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(\d+)万及?以上(?:的客户|客户)?'
#      - '{SEARCH}(?:已|已领取|已领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:大于等于|不少于|不低于|>=|≥)(\d+)万(?:元)?(?:的客户|客户)?'
#    field: "policies_total_survival_benefit_interest_received"
#    operator: "GTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "生存金利息已领取总额-以上"
#    patterns:
#      - '{SEARCH}(?:已|已领取|已领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:大于|高于|超过|>)(\d+)万(?:元)?(?:的客户|客户)?'
#    field: "policies_total_survival_benefit_interest_received"
#    operator: "GT"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "生存金利息已领取总额-及以下"
#    patterns:
#      - '{SEARCH}(?:已|已领取|已领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(\d+)万及?以下(?:的客户|客户)?'
#      - '{SEARCH}(?:已|已领取|已领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:小于等于|不超过|<=|≤)(\d+)万(?:元)?(?:的客户|客户)?'
#    field: "policies_total_survival_benefit_interest_received"
#    operator: "LTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "生存金利息已领取总额-以下"
#    patterns:
#      - '{SEARCH}(?:已|已领取|已领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:小于|低于|<)(\d+)万(?:元)?(?:的客户|客户)?'
#    field: "policies_total_survival_benefit_interest_received"
#    operator: "LT"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9

  # ==================== 生存金利息未领取总额 (polNoInfo.survivalinterestunpaidamt) ====================

  - name: "有生存金利息没领"
    patterns:
      - '{SEARCH}(?:有|存在|持有)生存金利息(?:未领取|没领|未领)?(?:的客户|客户|的)?'
      - '{SEARCH}(?:有未领取生存金利息|生存金利息还没领完|利息还没领完|利息未领完|有生存金利息|利息没领完)(?:的客户|客户|的)?(?:有哪些|有谁)?'
    field: "polNoInfo.survivalinterestunpaidamt"
    operator: "GT"
    value_type: "static"
    value: 0
    priority: 10
    merge_to_llm: true

  - name: "没有生存金利息没领"
    patterns:
      - '{SEARCH}(?:没有|不存在|未持有)生存金利息(?:未领取|没领|未领)?(?:的客户|客户|的)?(?:有哪些|有谁)?'
      - '{SEARCH}(?:没有领取生存金利息|生存金利息领完|利息领完|没有有生存金利息|利息已领完|生存金利息已全部领完|利息为0|没有利息)(?:的客户|客户|的)?(?:有哪些|有谁)?'
      - '{SEARCH}生存金利息(?:领完|领取完)(?:的客户|客户|的)?(?:有哪些|有谁)?'
      - '{SEARCH}利息(?:已|已经)领完(?:的客户|客户|的)?(?:有哪些|有谁)?'
    field: "polNoInfo.survivalinterestunpaidamt"
    operator: "LTE"
    value_type: "static"
    value: 0
    priority: 10
    merge_to_llm: true

  - name: "生存金利息未领取总额-及以上"
    patterns:
      - '{SEARCH}(?:未|未领取|未领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(\d+)万及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:未|未领取|未领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:大于等于|不少于|不低于|>=|≥)(\d+)万(?:元)?(?:的客户|客户)?'
    field: "polNoInfo.survivalinterestunpaidamt"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9
    merge_to_llm: true

  - name: "生存金利息未领取总额-以上"
    patterns:
      - '{SEARCH}(?:未|未领取|未领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:大于|高于|超过|>)(\d+)万(?:元)?(?:的客户|客户)?'
    field: "polNoInfo.survivalinterestunpaidamt"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9
    merge_to_llm: true

  - name: "生存金利息未领取总额-及以下"
    patterns:
      - '{SEARCH}(?:未|未领取|未领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(\d+)万及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:未|未领取|未领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:小于等于|不超过|<=|≤)(\d+)万(?:元)?(?:的客户|客户)?'
    field: "polNoInfo.survivalinterestunpaidamt"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9
    merge_to_llm: true

  - name: "生存金利息未领取总额-以下"
    patterns:
      - '{SEARCH}(?:未|未领取|未领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(?:小于|低于|<)(\d+)万(?:元)?(?:的客户|客户)?'
    field: "polNoInfo.survivalinterestunpaidamt"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9
    merge_to_llm: true

  - name: "生存金利息未领取总额-精确值-万"
    patterns:
      - '{SEARCH}(?:生存金)?利息(?:还有|还有|未领)?(\d+)万(?:没领|未领|领取)?(?:的客户|客户)?'
      - '{SEARCH}(?:生存金)?利息还有(\d+)万(?:没领|未领)?(?:的客户|客户)?'
      - '{SEARCH}利息未领取总额(\d+)万(?:的客户|客户)?'
      - '{SEARCH}(?:未|未领取|未领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(\d+)万(?:的客户|客户)?'
    field: "polNoInfo.survivalinterestunpaidamt"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 10000
    priority: 10
    merge_to_llm: true

  - name: "生存金利息未领取总额-精确值-千"
    patterns:
      - '{SEARCH}(?:生存金)?利息(?:还有|还有|未领)?(\d+)千(?:没领|未领|领取)?(?:的客户|客户)?'
      - '{SEARCH}(?:生存金)?利息还有(\d+)千(?:没领|未领)?(?:的客户|客户)?'
      - '{SEARCH}利息未领取总额(\d+)千(?:的客户|客户)?'
      - '{SEARCH}(?:未|未领取|未领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(\d+)千(?:的客户|客户)?'
    field: "polNoInfo.survivalinterestunpaidamt"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 1000
    priority: 10
    merge_to_llm: true

  - name: "生存金利息未领取总额-精确值-非万"
    patterns:
      - '{SEARCH}(?:生存金)?利息(?:还有|还有|未领)?(\d+)(?:块|元)(?:没领|未领|领取)?(?:的客户|客户)?'
      - '{SEARCH}(?:生存金)?利息还有(\d+)(?:没领|未领)?(?:的客户|客户)?'
      - '{SEARCH}利息未领取总额(\d+)(?:块|元)?(?:的客户|客户)?'
      - '{SEARCH}(?:未|未领取|未领)生存金利息(?:总额?|总金额|总额度){CW}{0,2}(\d{4,})(?:元|块)?(?:的客户|客户)?'
    field: "polNoInfo.survivalinterestunpaidamt"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 1
    priority: 10
    merge_to_llm: true

  # ==================== 生存金转入万能账户 ====================

#  - name: "生存金转入万能-存在"
#    patterns:
#      - '{SEARCH}有?生存金转入万能(?:账户)?(?:的客户|客户)?'
#    field: "policies_universal_acct_transfer"
#    operator: "EXISTS"
#    value_type: "static"
#    value: ""
#    priority: 9

  # ==================== 年收入/家庭收入/资产规模 ====================

#  - name: "年收入-以上"
#    is_supported: false
#    patterns:
#      - '{SEARCH}(?:年收入|年薪|年入)(?:超过|大于|高于|不少于|不低于|>=|≥)(\d+)万(?:元)?(?:的客户|客户)?'
#      - '{SEARCH}(?:年收入|年薪|年入)(\d+)万以上(?:的客户|客户)?'
#    field: "annual_income"
#    operator: "GTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "年收入-以下"
#    is_supported: false
#    patterns:
#      - '{SEARCH}(?:年收入|年薪|年入)(?:低于|小于|不超过|至多|<=|≤)(\d+)万(?:元)?(?:的客户|客户)?'
#      - '{SEARCH}(?:年收入|年薪|年入)(\d+)万以下(?:的客户|客户)?'
#    field: "annual_income"
#    operator: "LTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "家庭收入-以上"
#    is_supported: false
#    patterns:
#      - '{SEARCH}(?:家庭收入|家庭年收入|家庭年入)(?:超过|大于|高于|不少于|不低于|>=|≥)(\d+)万(?:元)?(?:的客户|客户)?'
#      - '{SEARCH}(?:家庭收入|家庭年收入|家庭年入)(\d+)万以上(?:的客户|客户)?'
#    field: "household_income"
#    operator: "GTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "家庭收入-以下"
#    is_supported: false
#    patterns:
#      - '{SEARCH}(?:家庭收入|家庭年收入|家庭年入)(?:低于|小于|不超过|至多|<=|≤)(\d+)万(?:元)?(?:的客户|客户)?'
#      - '{SEARCH}(?:家庭收入|家庭年收入|家庭年入)(\d+)万以下(?:的客户|客户)?'
#    field: "household_income"
#    operator: "LTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "资产规模-以上"
#    is_supported: false
#    patterns:
#      - '{SEARCH}(?:资产规模|资产|净资产)(?:超过|大于|高于|不少于|不低于|>=|≥)(\d+)万(?:元)?(?:的客户|客户)?'
#      - '{SEARCH}(?:资产规模|资产|净资产)(\d+)万以上(?:的客户|客户)?'
#    field: "asset_scale"
#    operator: "GTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "资产规模-以下"
#    is_supported: false
#    patterns:
#      - '{SEARCH}(?:资产规模|资产|净资产)(?:低于|小于|不超过|至多|<=|≤)(\d+)万(?:元)?(?:的客户|客户)?'
#      - '{SEARCH}(?:资产规模|资产|净资产)(\d+)万以下(?:的客户|客户)?'
#    field: "asset_scale"
#    operator: "LTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9

  # ==================== 投保日期 ====================

  # 投保日期暂不支持实际搜索，但需要生成条件，供意图摘要输出不支持提示。
  - name: "投保日期-今年"
    is_supported: false
    patterns:
      - '{SEARCH}(?:今年|本年){CW}{0,2}(?:投保(?:了|过)?|购买了?|买了?|买过)(?:保险)?(?:的客户)?(?:有哪些)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:今年|本年)(?:有哪些客户|哪些客户){CW}{0,2}(?:投保(?:了|过)?|购买了?|买了?|买过)(?:保险)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:投保(?:了|过)?|购买了?|买了?|买过)(?:保险)?{CW}{0,2}(?:在)?(?:今年|本年){CUSTOMER_SUFFIX}'
    field: "policies_insure_date"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 18
    merge_to_llm: true

  - name: "投保日期-近半年"
    is_supported: false
    patterns:
      - '{SEARCH}(?:近|最近|过去)半年(?:内|里)?{CW}{0,2}(?:投保(?:了|过)?|购买了?|买了?|买过)(?:保险)?(?:的客户)?(?:有哪些)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:近|最近|过去)半年(?:内|里)?(?:有哪些客户|哪些客户){CW}{0,2}(?:投保(?:了|过)?|购买了?|买了?|买过)(?:保险)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:投保(?:了|过)?|购买了?|买了?|买过)(?:保险)?{CW}{0,2}(?:在)?(?:近|最近|过去)半年(?:内|里)?{CUSTOMER_SUFFIX}'
    field: "policies_insure_date"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "past_n_months_to_today"
      months: 6
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 18
    merge_to_llm: true

  - name: "投保日期-去年片段"
    is_supported: false
    patterns:
      - '(?:去年|上一年)'
    field: "policies_insure_date"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_year"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 18
    merge_to_llm: true

  - name: "投保日期-去年"
    is_supported: false
    patterns:
      - '(?:我想)?{SEARCH}(?:去年|上一年){CW}{0,2}(?:投保|购买了?|买了?|买过)(?:保险)?(?:的客户|客户|名单|的人|人)?'
      - '(?:我想)?{SEARCH}(?:投保|购买了?|买了?|买过)(?:保险)?{CW}{0,2}(?:在)?(?:去年|上一年)(?:的客户|客户|名单|的人|人)?'
    field: "policies_insure_date"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_year"
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 18
    merge_to_llm: true

#  - name: "投保日期-今年"
#    is_supported: false
#    patterns:
#      - '{SEARCH}(?:今年|本年){CW}{0,2}投保(?:的客户|客户)?'
#      - '{SEARCH}投保{CW}{0,2}在今年(?:的客户|客户)?'
#    field: "policies_insure_date"
#    operator: "RANGE"
#    value_type: "date_range_dynamic"
#    value:
#      date_range: "current_year"
#      format: "yyyy-MM-dd"
#    priority: 9
#
#  - name: "投保日期-去年"
#    is_supported: false
#    patterns:
#      - '{SEARCH}(?:去年|上一年){CW}{0,2}投保(?:的客户|客户)?'
#      - '{SEARCH}投保{CW}{0,2}在去年(?:的客户|客户)?'
#    field: "policies_insure_date"
#    operator: "RANGE"
#    value_type: "date_range_dynamic"
#    value:
#      date_range: "last_year"
#      format: "yyyy-MM-dd"
#    priority: 9

#   ==================== 投保人/被保人/受益人 ====================

  - name: "投保人姓名"
    is_supported: false
    patterns:
      - '{SEARCH}(?:投保人姓名|投保人名字)(?:为|是)?([\u4e00-\u9fa5]{2,4}?)(?=的客户|客户|$)(?:的客户|客户)?'
      - '{SEARCH}(?:投保人叫|投保人是)([\u4e00-\u9fa5]{2,4}?)(?=的客户|客户|$)(?:的客户|客户)?'
    field: "polNoInfo.applicantname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 9

  - name: "投保人手机号"
    is_supported: false
    patterns:
      - '{SEARCH}(?:投保人手机号|投保人电话|投保人手机)(?:为|是)?(1[3-9]\d{1,9})(?:的客户|客户)?'
    field: "polNoInfo.applicantphoneno"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 9

  - name: "被保人姓名"
    is_supported: false
    patterns:
      - '{SEARCH}(?:被保人姓名|被保险人姓名|被保人名字)(?:为|是)?([\u4e00-\u9fa5]{2,4})(?:的客户|客户)?'
      - '{SEARCH}(?:被保人叫|被保人是|被保险人叫)([\u4e00-\u9fa5]{2,4})(?:的客户|客户)?'
    field: "polNoInfo.plancodeinfo.insname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 9

  - name: "被保人手机号"
    is_supported: false
    patterns:
      - '{SEARCH}(?:被保人手机号|被保险人手机号|被保人电话|被保人手机)(?:为|是)?(1[3-9]\d{1,9})(?:的客户|客户)?'
    field: "polNoInfo.plancodeinfo.insphoneno"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 9
#
#  - name: "受益人手机号"
#    is_supported: false
#    patterns:
#      - '{SEARCH}(?:受益人手机号|受益人电话|受益人手机)(?:为|是)?(1[3-9]\d{9})(?:的客户|客户)?'
#    field: "policies_beneficiary_mobile"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 9

  # ==================== 生存金/理赔金额 ====================

#  - name: "生存金总金额-以上"
#    patterns:
#      - '{SEARCH}生存金(?:总额?|总金额|总额度){CW}{0,2}(\d+)万以上(?:的客户|客户)?'
#    field: "policies_survival_total_amount"
#    operator: "GT"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "生存金总金额-及以上"
#    patterns:
#      - '{SEARCH}生存金(?:总额?|总金额|总额度){CW}{0,2}(\d+)万及以上(?:的客户|客户)?'
#      - '{SEARCH}生存金(?:总额?|总金额|总额度)(?:不低于|不少于|大于等于|>=|≥)(\d+)万(?:的客户|客户)?'
#    field: "policies_survival_total_amount"
#    operator: "GTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "生存金总金额-以下"
#    patterns:
#      - '{SEARCH}生存金(?:总额?|总金额|总额度){CW}{0,2}(\d+)万以下(?:的客户|客户)?'
#      - '{SEARCH}生存金(?:总额?|总金额|总额度)(?:低于|小于)(\d+)万(?:的客户|客户)?'
#    field: "policies_survival_total_amount"
#    operator: "LT"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "生存金总金额-及以下"
#    patterns:
#      - '{SEARCH}生存金(?:总额?|总金额|总额度){CW}{0,2}(\d+)万及以下(?:的客户|客户)?'
#      - '{SEARCH}生存金(?:总额?|总金额|总额度)(?:不超过|不大于|小于等于|<=|≤)(\d+)万(?:的客户|客户)?'
#    field: "policies_survival_total_amount"
#    operator: "LTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9

#  - name: "生存金已领取-以上"
#    patterns:
#      - '{SEARCH}已(?:领|领取)生存金{CW}{0,2}(\d+)万以上(?:的客户|客户)?'
#    field: "policies_survival_claimed_amount"
#    operator: "GT"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9
#
#  - name: "生存金已领取-及以上"
#    patterns:
#      - '{SEARCH}已(?:领|领取)生存金{CW}{0,2}(\d+)万及以上(?:的客户|客户)?'
#      - '{SEARCH}已(?:领|领取)生存金(?:不低于|不少于|大于等于|>=|≥)(\d+)万(?:的客户|客户)?'
#    field: "policies_survival_claimed_amount"
#    operator: "GTE"
#    value_type: "capture"
#    value:
#      group: 1
#      transform: "multiply"
#      multiplier: 10000
#    priority: 9

  - name: "理赔金额-及以上"
    patterns:
      - '{SEARCH}(?:理赔金额|获赔金额|赔付金额){CW}{0,2}(\d+)万及?以上(?:的客户|客户)?'
      - '{SEARCH}(?:理赔金额|获赔金额|赔付金额)(?:不低于|不少于|大于等于|>=|≥)(\d+)万(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimamt"
    operator: "GTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "理赔金额-以下"
    patterns:
#      - '{SEARCH}(?:理赔金额|获赔金额|赔付金额){CW}{0,2}(\d+)万以下(?:的客户|客户)?'
      - '{SEARCH}(?:理赔金额|获赔金额|赔付金额)(?:低于|小于)(\d+)万(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimamt"
    operator: "LT"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "理赔金额-及以下"
    patterns:
      # 明确带"万"单位的
      - '{SEARCH}(?:理赔金额|获赔金额|赔付金额){CW}{0,2}(\d+)万及?以下(?:的客户|客户)?'
      - '{SEARCH}(?:理赔金额|获赔金额|赔付金额)(?:不超过|不大于|小于等于|<=|≤)(\d+)万(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimamt"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 10000
    priority: 9

  - name: "理赔金额-及以下-精确值"
    patterns:
      # 精确值匹配（块/元）："理赔金额不超过5000的客户"
      - '{SEARCH}(?:理赔金额|获赔金额|赔付金额){CW}{0,2}(?:不超过|不大于|至多|<=|≤)(\d+)(?:元)?(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimamt"
    operator: "LTE"
    value_type: "capture"
    value:
      group: 1
      transform: "multiply"
      multiplier: 1
    priority: 10
    merge_to_llm: true

  # ==================== 理赔金额-精确值 ====================
  - name: "理赔金额-精确值-万"
    patterns:
      # 精确值匹配（万）："理赔金额2万的客户"
      - '{SEARCH}(?:理赔金额|获赔金额|赔付金额)(?:等于|＝|是|为)?(\d+)万(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimamt"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 10000
    priority: 10
    merge_to_llm: true

  - name: "理赔金额-精确值-千"
    patterns:
      # 精确值匹配（千）："理赔金额5千的客户"
      - '{SEARCH}(?:理赔金额|获赔金额|赔付金额)(?:等于|＝|是|为)?(\d+)千(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimamt"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 1000
    priority: 10
    merge_to_llm: true

  - name: "理赔金额-精确值-非万"
    patterns:
      # 精确值匹配（非万）："理赔金额5000的客户"
      - '{SEARCH}(?:理赔金额|获赔金额|赔付金额)(?:等于|＝|是|为)?(\d{4,})(?:元|块)?(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimamt"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "exact_range"
      multiplier: 1
    priority: 10
    merge_to_llm: true

  - name: "理赔金额-口语超过-非万"
    patterns:
      - '{SEARCH}(?:理赔|获赔|赔付){CW}{0,2}(?:超|超过|大于|高于|多于)(\d{3,})(?:元|块)?(?:的客户|客户|的人|人|名单|有哪些|的)?'
      - '{SEARCH}(?:理赔|获赔|赔付)(\d{3,})(?:元|块)?(?:以上|及以上)(?:的客户|客户|的人|人|名单|有哪些|的)?'
      - '{SEARCH}(?:理赔|获赔|赔付).*(?:超|超过|大于|高于|多于)(\d{3,}){CUSTOMER_SUFFIX}'
    field: "polNoInfo.claimdatainfo.claimamt"
    operator: "GT"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 12
    merge_to_llm: true

  - name: "理赔案件号-MC格式"
    patterns:
      - '{SEARCH}(?<![A-Za-z0-9])([Mm][Cc]\d{14})(?![A-Za-z0-9])(?:的客户|客户)?'
      - '{SEARCH}(?:理赔)?(?:案件号|案号|案件编号|理赔案件号|理赔案号|理赔编号|赔案号|报案号){CW}{0,2}(?:为|是|匹配|等于|包含|含有|带有)?[：:\s]?(?<![A-Za-z0-9])([Mm][Cc]\d{1,14})(?![A-Za-z0-9])(?:的客户|客户)?'
      - '{SEARCH}(?:理赔)?(?:案件号|案号|案件编号|理赔案件号|理赔案号|理赔编号|赔案号|报案号)(?:前缀|开头|以)(?:为|是)?[：:\s]?([Mm][Cc]\d{1,14})(?:开头)?(?:的客户|客户)?'
      - '{SEARCH}(?:理赔)?(?:案件号|案号|案件编号|理赔案件号|理赔案号|理赔编号|赔案号|报案号){CW}{0,2}([Mm][Cc]\d{1,14})(?:开头|前缀)(?:的客户|客户)?'
      - '{SEARCH}(?:理赔)?(?:案件号|案号|案件编号|理赔案件号|理赔案号|理赔编号|赔案号|报案号){CW}{0,2}(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:为|是)?[：:\s]?(\d{1,14})(?:的客户|客户)?'
      - '{SEARCH}(?:理赔)?(?:案件号|案号|案件编号|理赔案件号|理赔案号|理赔编号|赔案号|报案号){CW}{0,2}(\d{1,14})(?:尾号|尾数|末尾|后四位|后几位|结尾)(?:的客户|客户)?'
      - '{SEARCH}(?:尾号|尾数|末尾|后四位|后几位)(?:为|是)?[：:\s]?(\d{1,14})(?:的)?(?:理赔)?(?:案件号|案号|案件编号|理赔案件号|理赔案号|理赔编号|赔案号|报案号)(?:的客户|客户)?'
      - '{SEARCH}(\d{1,14})(?:尾号|尾数|末尾|后四位|后几位)(?:的)?(?:理赔)?(?:案件号|案号|案件编号|理赔案件号|理赔案号|理赔编号|赔案号|报案号)(?:的客户|客户)?'
      - '{SEARCH}([Mm][Cc]\d{1,14})(?:开头|前缀)(?:的)?(?:理赔)?(?:案件号|案号|案件编号|理赔案件号|理赔案号|理赔编号|赔案号|报案号)(?:的客户|客户)?'
    field: "polNoInfo.claimdatainfo.claimno"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 11
    merge_to_llm: true



  # ==================== 0610 新增客户分类及会员等级字段 ====================

  - name: "濒临失效高客-默认是"
    patterns:
      - '{SEARCH}(?:哪些客户|哪些人|谁|有人)?(?:已经|是不是|是否为|是否)?(?:算|属于|是)?(?:顶级|濒临)?失效高客(?:了|的)?(?:标签|标记)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:可投资资产|可投资产)(?:达到|达|不少于|不低于|大于等于|≥|>=)?50万(?:元)?(?:以上|及以上)?(?:且|并且|并|同时|，|,)(?:有|存在|具有)?(?:保单)?(?:失效风险|可能失效|濒临失效|失效可能性){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:有|存在|具有)?(?:保单)?(?:失效风险|可能失效|濒临失效|失效可能性)(?:且|并且|并|同时|，|,)(?:可投资资产|可投资产)(?:达到|达|不少于|不低于|大于等于|≥|>=)?50万(?:元)?(?:以上|及以上)?{CUSTOMER_SUFFIX}'
    field: "clientChurnTag"
    operator: "MATCH"
    value_type: "static"
    value: "是"
    priority: 10
    merge_to_llm: true

  - name: "濒临失效高客-标签为空"
    patterns:
      - '{SEARCH}(?:濒临失效高客|高客失效)(?:标签|标记)?(?:还没打|没打|未打|没有|为空|没标|未标){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:标签|标记)(?:还没打|没打|未打|没有|为空|没标|未标)(?:的)?(?:濒临失效高客|高客失效){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:不是|排除|去掉|不要|把)(?:顶级|濒临)?失效高客(?:排除掉)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "clientChurnTag"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 14
    merge_to_llm: true

  # “有/没有某权益”判断对应服务线字段是否存在，不携带具体枚举值。
  - name: "安有医-权益存在"
    patterns:
      - '{SEARCH}(?<![没无非未])(?<!没有)(?:有|拥有|持有|享有)(?:安有医)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:安有医)(?:会员)?权益(?:存在|不为空|有值){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:安有医)(?:客户|会员|的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?(?:安有医)(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymemberproductname"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 15
    merge_to_llm: true

  - name: "安有医-权益不存在"
    patterns:
      - '{SEARCH}(?:没有|没|无|未有|不存在|未持有)(?:安有医)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:安有医)(?:会员)?权益(?:为空|没值|不存在|没有记录){CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymemberproductname"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "安有护-权益存在"
    patterns:
      - '{SEARCH}(?<![没无非未])(?<!没有)(?:有|拥有|持有|享有)(?:安有护)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:安有护)(?:会员)?权益(?:存在|不为空|有值){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:安有护)(?:客户|会员|的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?(?:安有护)(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhmemberproductname"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 15
    merge_to_llm: true

  - name: "安有护-权益不存在"
    patterns:
      - '{SEARCH}(?:没有|没|无|未有|不存在|未持有)(?:安有护)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:安有护)(?:会员)?权益(?:为空|没值|不存在|没有记录){CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhmemberproductname"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-权益不存在"
    patterns:
      - '{SEARCH}(?:没有|没|无|未有|不存在|未持有)(?:臻享家医|臻享家庭|家医)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|臻享家庭|家医)(?:会员)?权益(?:为空|没值|不存在|没有记录){CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymemberproductname"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-权益存在"
    patterns:
      - '{SEARCH}(?<![没无非未])(?<!没有)(?:有|拥有|持有|享有)(?:臻享家医|臻享家庭|家医)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|臻享家庭|家医)(?:会员)?权益(?:存在|不为空|有值){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|臻享家庭|家医)(?:客户|会员|的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?(?:臻享家医|臻享家庭|家医)(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymemberproductname"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 15
    merge_to_llm: true

  - name: "平安居家-权益不存在"
    patterns:
      - '{SEARCH}(?:没有|没|无|未有|不存在|未持有)(?:平安居家|居家养老|居家)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?权益(?:为空|没值|不存在|没有记录){CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmemberproductname"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "平安居家-权益存在"
    patterns:
      - '{SEARCH}(?<![没无非未])(?<!没有)(?:有|拥有|持有|享有)(?:平安居家|居家养老|居家)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?权益(?:存在|不为空|有值){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:客户|会员|的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?(?:平安居家|居家养老|居家)(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmemberproductname"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 15
    merge_to_llm: true

  - name: "添平安-任一会员权益存在"
    patterns:
      - '{SEARCH}添平安(?:权益|会员)?的?客户'
      - '{SEARCH}平安(?:权益|会员)的?客户'
      - '{SEARCH}(?:有|拥有|持有|享有)?客户权益(?:会员|单)?'
    field: "ayyMemberGradeInfo.ayymemberproductname"
    operator: "EXISTS"
    query_logic: "OR"
    value_type: "static"
    value: ""
    priority: 25
    merge_to_llm: false
    extra_conditions:
      - field: "ayhMemberGradeInfo.ayhmemberproductname"
        operator: "EXISTS"
        value: ""
      - field: "zxjyMemberGradeInfo.zxjymemberproductname"
        operator: "EXISTS"
        value: ""
      - field: "pajjMemberGradeInfo.pajjmemberproductname"
        operator: "EXISTS"
        value: ""
      - field: "yxgyMemberGradeInfo.yxgymemberproductname"
        operator: "EXISTS"
        value: ""
      - field: "sdbjyMemberGradeInfo.sdbjymemberproductname"
        operator: "EXISTS"
        value: ""
      - field: "gdkyMemberGradeInfo.gdkymemberproductname"
        operator: "EXISTS"
        value: ""

  - name: "保单数量-精确"
    is_supported: false
    patterns:
      - '{SEARCH}(?:保单数量|保单个数|保单数|保单张数)(?:为|是|等于|=)?(\d+)'
    field: "polNum"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
      transform: "int"
    priority: 18
    merge_to_llm: false

  - name: "御享国医-权益不存在"
    patterns:
      - '{SEARCH}(?:没有|没|无|未有|不存在|未持有)(?:御享国医|国医)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:御享国医|国医)(?:会员)?权益(?:为空|没值|不存在|没有记录){CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgymemberproductname"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "御享国医-权益存在"
    patterns:
      - '{SEARCH}(?<![没无非未])(?<!没有)(?:有|拥有|持有|享有)(?:御享国医|国医)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:御享国医|国医)(?:会员)?权益(?:存在|不为空|有值){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:御享国医|国医)(?:客户|会员|的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?(?:御享国医|国医)(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgymemberproductname"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 15
    merge_to_llm: true

  - name: "私董保健医-权益不存在"
    patterns:
      - '{SEARCH}(?:没有|没|无|未有|不存在|未持有)(?:私董保健医|私董)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董)(?:会员)?权益(?:为空|没值|不存在|没有记录){CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjymemberproductname"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "私董保健医-权益存在"
    patterns:
      - '{SEARCH}(?<![没无非未])(?<!没有)(?:有|拥有|持有|享有)(?:私董保健医|私董|保健医)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:会员)?权益(?:存在|不为空|有值){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:客户|会员|的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?(?:私董保健医|私董|保健医)(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjymemberproductname"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 15
    merge_to_llm: true

  - name: "高端康养-权益不存在"
    patterns:
      - '{SEARCH}(?:没有|没|无|未有|不存在|未持有)(?:高端康养|康养)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:会员)?权益(?:为空|没值|不存在|没有记录){CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymemberproductname"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "高端康养-权益存在"
    patterns:
      - '{SEARCH}(?<![没无非未])(?<!没有)(?:有|拥有|持有|享有)(?:高端康养|康养)(?:会员)?权益{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:会员)?权益(?:存在|不为空|有值){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:客户|会员|的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?(?:高端康养|康养)(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymemberproductname"
    operator: "EXISTS"
    value_type: "static"
    value: ""
    priority: 15
    merge_to_llm: true

  - name: "安有医-服务线"
    enum_ref: "ayyMemberGradeInfo.ayymemberproductname"
    patterns_template:
      - '{SEARCH}安有医(?:服务线|服务线名称|产品线)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){position}{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?{enum}(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymemberproductname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "安有医-会员等级"
    enum_ref: "ayyMemberGradeInfo.ayymembergradesearch"
    patterns_template:
      - '{SEARCH}安有医(?:会员)?(?:等级|版本)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymembergradesearch"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 13
    merge_to_llm: true

  - name: "安有医-会员类型"
    enum_ref: "ayyMemberGradeInfo.ayymemberstatus"
    patterns_template:
      - '{SEARCH}安有医(?:会员)?(?:类型|状态)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医{enum}(?:会员)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymemberstatus"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "安有医-会员期次"
    patterns:
      - '{SEARCH}安有医(?:会员)?(?:期次|年度)(?:为|是)?(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:会员)?(?:包含|含有|有|包括)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:会员)?(?:不包含|不含|没有|无)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymemberperiod"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "安有护-服务线"
    enum_ref: "ayhMemberGradeInfo.ayhmemberproductname"
    patterns_template:
      - '{SEARCH}安有护(?:服务线|服务线名称|产品线)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){position}{enum}(?:的客户|客户)?'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?{enum}(?:服务|会员服务|权益)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:客户|会员|的客户|权益|权益的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:有|拥有|享有|已有)?{enum}(?:会员)?(?:权益)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}'
    field: "ayhMemberGradeInfo.ayhmemberproductname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "安有护-会员等级"
    enum_ref: "ayhMemberGradeInfo.ayhmembergradesearch"
    patterns_template:
      - '{SEARCH}安有护(?:会员|权益)?(?:等级|版本)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:的)?安有护(?:会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是)安有护{CW}{0,2}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum})){CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护权益(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum})){CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护权益等级(?:为|是)?(?:安有护)?{CW}{0,2}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum})){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))安有护{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhmembergradesearch"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 13
    merge_to_llm: true

  - name: "安有护-会员类型"
    enum_ref: "ayhMemberGradeInfo.ayhmemberstatus"
    patterns_template:
      - '{SEARCH}安有护(?:会员)?(?:类型|状态)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护{enum}(?:会员)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhmemberstatus"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "安有护-会员期次"
    patterns:
      - '{SEARCH}安有护(?:会员)?(?:期次|年度)(?:为|是)?(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:会员)?(?:包含|含有|有|包括)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:会员)?(?:不包含|不含|没有|无)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhmemberperiod"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "臻享家医-服务线"
    enum_ref: "zxjyMemberGradeInfo.zxjymemberproductname"
    patterns_template:
      - '{SEARCH}(?:臻享家庭|臻享家医|家医|臻享)(?:服务线|服务线名称|产品线)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){position}{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?{enum}(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:客户|会员|的客户|权益|权益的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:有|拥有|享有|已有)?{enum}(?:会员)?(?:权益)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymemberproductname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "臻享家医-会员等级"
    enum_ref: "zxjyMemberGradeInfo.zxjymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:臻享家医|家医)(?:会员|权益)?(?:等级)?{CW}{0,2}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum})){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:会员|权益)?(?:等级)?(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum})){CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum}))(?:臻享家医|家医)(?:会员|权益)?(?:等级)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:会员|权益)?(?:等级)?(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymembergradesearch"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 13
    merge_to_llm: true

  - name: "臻享家医-等级高于"
    enum_ref: "zxjyMemberGradeInfo.zxjymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:高于|大于|超过)(?:了)?{enum}(?:的)?(?:臻享家医|臻享)(?:会员|权益)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_gt"
    value:
      group: 1
    priority: 15
    merge_to_llm: true

  - name: "臻享家医-等级及以上"
    enum_ref: "zxjyMemberGradeInfo.zxjymembergradesearch"
    patterns_template:
      - '{SEARCH}{enum}及?以上{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医|臻享)(?:会员|权益)?(?:等级)?(?:为|是)?{enum}及?以上{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:不低于|不小于|大于等于|>=|≥){enum}(?:的)?(?:臻享家医|臻享)(?:会员|权益)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_gte"
    value:
      group: 1
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-等级低于"
    enum_ref: "zxjyMemberGradeInfo.zxjymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:低于|小于|不足|不到){enum}(?:的)?(?:臻享家医|臻享)(?:会员|权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:还没到|未到|没到)(?:臻享家医|家医)?{enum}(?:的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_lt"
    value:
      group: 1
    priority: 15
    merge_to_llm: true

  - name: "臻享家医-等级及以下"
    enum_ref: "zxjyMemberGradeInfo.zxjymembergradesearch"
    patterns_template:
      - '{SEARCH}{enum}(?:及)?以下{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医|臻享)(?:会员|权益)?(?:等级)?(?:为|是)?{enum}(?:及)?以下{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:不大于|不小于等于|小于等于|<=|≤){enum}(?:的)?(?:臻享家医|臻享)(?:会员|权益)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_lte"
    value:
      group: 1
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-会员类型"
    enum_ref: "zxjyMemberGradeInfo.zxjymemberstatus"
    patterns_template:
      - '{SEARCH}(?:臻享家医|家医|臻享)(?:会员|权益)?(?:类型|状态)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医|臻享){enum}(?:会员|权益)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymemberstatus"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "臻享家医-会员期次"
    patterns:
      - '{SEARCH}(?:臻享家医|家医|臻享)(?:会员)?(?:期次|年度)(?:为|是)?(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医|臻享)(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|臻享)(?:会员)?(?:包含|含有|有|包括)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|臻享)(?:会员)?(?:不包含|不含|没有|无)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymemberperiod"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "平安居家-服务线"
    enum_ref: "pajjMemberGradeInfo.pajjmemberproductname"
    patterns_template:
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:服务线|服务线名称|产品线)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){position}{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?{enum}(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:客户|会员|的客户|权益|权益的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:有|拥有|享有|已有)?{enum}(?:会员)?(?:权益)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmemberproductname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "平安居家-会员等级"
    enum_ref: "pajjMemberGradeInfo.pajjmembergradesearch"
    patterns_template:
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?(?:等级)?{CW}{0,2}{enum}(?!{CW}{0,2}(?:以上|及以上|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum})){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?(?:等级)?(?:为|是)?{enum}(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum})){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){enum}(?!{CW}{0,2}(?:以上|及以上|以下|及以下))(?!.*(?:、|，|,|和|或|及|与|以及).*(?:{enum})){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?(?:等级)?(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){enum}{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmembergradesearch"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 13
    merge_to_llm: true

  - name: "平安居家-等级高于"
    enum_ref: "pajjMemberGradeInfo.pajjmembergradesearch"
    patterns_template:
      - '{SEARCH}(?:高于|大于|超过)(?:了)?{enum}(?:的)?(?:平安居家|居家养老|居家)(?:会员)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_gt"
    value:
      group: 1
    priority: 15
    merge_to_llm: true

  - name: "平安居家-等级及以上"
    enum_ref: "pajjMemberGradeInfo.pajjmembergradesearch"
    patterns_template:
      - '{SEARCH}{enum}及?以上{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?(?:等级)?(?:为|是)?{enum}及?以上{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是)(?:平安居家|居家养老|居家){CW}{0,2}{enum}及?以上{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){enum}(?:平安居家|居家养老|居家)及?以上{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:不低于|不小于|大于等于|>=|≥){enum}(?:的)?(?:平安居家|居家养老|居家)(?:会员)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_gte"
    value:
      group: 1
    priority: 16
    merge_to_llm: true

  - name: "平安居家-等级低于"
    enum_ref: "pajjMemberGradeInfo.pajjmembergradesearch"
    patterns_template:
      - '{SEARCH}(?:低于|小于|不足|不到){enum}(?:的)?(?:平安居家|居家养老|居家)(?:会员)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_lt"
    value:
      group: 1
    priority: 15
    merge_to_llm: true

  - name: "平安居家-等级及以下"
    enum_ref: "pajjMemberGradeInfo.pajjmembergradesearch"
    patterns_template:
      - '{SEARCH}{enum}(?:及)?以下{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?(?:等级)?(?:为|是)?{enum}(?:及)?以下{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是)(?:平安居家|居家养老|居家){CW}{0,2}{enum}(?:及)?以下{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){enum}(?:平安居家|居家养老|居家)(?:及)?以下{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:不大于|不大于等于|小于等于|<=|≤){enum}(?:的)?(?:平安居家|居家养老|居家)(?:会员)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_lte"
    value:
      group: 1
    priority: 16
    merge_to_llm: true

  - name: "平安居家-会员类型"
    enum_ref: "pajjMemberGradeInfo.pajjmemberstatus"
    patterns_template:
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?(?:类型|状态)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家){enum}(?:会员)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmemberstatus"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "平安居家-会员期次"
    patterns:
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?(?:期次|年度)(?:为|是)?(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?(?:包含|含有|有|包括)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?(?:不包含|不含|没有|无)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmemberperiod"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "御享国医-服务线"
    enum_ref: "yxgyMemberGradeInfo.yxgymemberproductname"
    patterns_template:
      - '{SEARCH}御享国医(?:服务线|服务线名称|产品线)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){position}{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?{enum}(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:客户|会员|的客户|权益|权益的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:有|拥有|享有|已有)?{enum}(?:会员)?(?:权益)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgymemberproductname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "御享国医-会员等级"
    enum_ref: "yxgyMemberGradeInfo.yxgymembergradesearch"
    patterns_template:
      - '{SEARCH}御享国医(?:会员)?(?:等级)?(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgymembergradesearch"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 13
    merge_to_llm: true

  - name: "御享国医-会员类型"
    enum_ref: "yxgyMemberGradeInfo.yxgymemberstatus"
    patterns_template:
      - '{SEARCH}御享国医(?:会员)?(?:类型|状态)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医{enum}(?:会员)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgymemberstatus"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "御享国医-会员期次"
    patterns:
      - '{SEARCH}御享国医(?:会员)?(?:期次|年度)(?:为|是)?(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:会员)?(?:包含|含有|有|包括)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:会员)?(?:不包含|不含|没有|无)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgymemberperiod"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "私董保健医-服务线"
    enum_ref: "sdbjyMemberGradeInfo.sdbjymemberproductname"
    patterns_template:
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:服务线|服务线名称|产品线)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){position}{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?{enum}(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:客户|会员|的客户|权益|权益的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:有|拥有|享有|已有)?{enum}(?:会员)?(?:权益)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjymemberproductname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "私董保健医-会员等级"
    enum_ref: "sdbjyMemberGradeInfo.sdbjymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:会员)?(?:等级|版本)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医){enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjymembergradesearch"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 13
    merge_to_llm: true

  - name: "私董保健医-会员类型"
    enum_ref: "sdbjyMemberGradeInfo.sdbjymemberstatus"
    patterns_template:
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:会员)?(?:类型|状态)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医){enum}(?:会员)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjymemberstatus"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "私董保健医-会员期次"
    patterns:
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:会员)?(?:期次|年度)(?:为|是)?(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董)(?:会员)?(?:包含|含有|有|包括)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董)(?:会员)?(?:不包含|不含|没有|无)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjymemberperiod"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "高端康养-服务线"
    enum_ref: "gdkyMemberGradeInfo.gdkymemberproductname"
    patterns_template:
      - '{SEARCH}(?:康养|平安康养|康养服务|高端康养)(?:服务线|服务线名称|产品线)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?<![没无非])(?<!不是){position}{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:开通了?|购买了?|享有?|已有|买过|买了)(?:的)?{enum}(?:服务|会员服务)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:客户|会员|的客户|权益|权益的客户){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:有|拥有|享有|已有)?{enum}(?:会员)?(?:权益)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymemberproductname"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "高端康养-会员等级"
    enum_ref: "gdkyMemberGradeInfo.gdkymembergradesearch"
    patterns_template:
      - '{SEARCH}高端康养(?:会员)?等级(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:的)?高端康养(?:会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymembergradesearch"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 13
    merge_to_llm: true

  - name: "高端康养-等级高于"
    enum_ref: "gdkyMemberGradeInfo.gdkymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:高于|大于|超过)(?:了)?{enum}(?:的)?高端康养(?:会员)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_gt"
    value:
      group: 1
    priority: 15
    merge_to_llm: true

  - name: "高端康养-等级及以上"
    enum_ref: "gdkyMemberGradeInfo.gdkymembergradesearch"
    patterns_template:
      - '{SEARCH}{enum}及?以上{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}及?以上(?:的)?(?:高端)?康养(?:客户|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}高端康养{enum}及?以上{CUSTOMER_SUFFIX}'
      - '{SEARCH}高端康养(?:会员)?等级(?:为|是)?{enum}及?以上{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:不低于|不小于|大于等于|>=|≥){enum}(?:的)?高端康养(?:会员)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_gte"
    value:
      group: 1
    priority: 16
    merge_to_llm: true

  - name: "高端康养-等级低于"
    enum_ref: "gdkyMemberGradeInfo.gdkymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:低于|小于|不足|不到){enum}(?:的)?高端康养(?:会员)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_lt"
    value:
      group: 1
    priority: 15
    merge_to_llm: true

  - name: "高端康养-等级及以下"
    enum_ref: "gdkyMemberGradeInfo.gdkymembergradesearch"
    patterns_template:
      - '{SEARCH}{enum}(?:及)?以下{CUSTOMER_SUFFIX}'
      - '{SEARCH}高端康养(?:会员)?等级(?:为|是)?{enum}(?:及)?以下{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:不大于|不大于等于|小于等于|<=|≤){enum}(?:的)?高端康养(?:会员)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_lte"
    value:
      group: 1
    priority: 16
    merge_to_llm: true

  - name: "高端康养-会员类型"
    enum_ref: "gdkyMemberGradeInfo.gdkymemberstatus"
    patterns_template:
      - '{SEARCH}高端康养(?:会员)?(?:类型|状态)(?:为|是)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}高端康养{enum}(?:会员)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymemberstatus"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  - name: "高端康养-会员期次"
    patterns:
      - '{SEARCH}高端康养(?:会员)?(?:期次|年度)(?:为|是)?(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}高端康养(\d{4}){CUSTOMER_SUFFIX}'
      - '{SEARCH}高端康养(?:会员)?(?:包含|含有|有|包括)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}高端康养(?:会员)?(?:不包含|不含|没有|无)(\d{4})(?:年)?(?:的)?(?:期|期次|年度)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymemberperiod"
    operator: "MATCH"
    value_type: "capture"
    value:
      group: 1
    priority: 12
    merge_to_llm: true

  # ==================== 0610 会员权益通用口语模板 ====================

  - name: "安有医-等级排除"
    enum_ref: "ayyMemberGradeInfo.ayymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:安有医)?(?:不要|不是|排除|去掉|不含|不包含|没有){enum}(?:的)?(?:安有医)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymembergradesearch"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value: {group: 1}
    priority: 17
    merge_to_llm: true

  - name: "安有医-等级反向表达"
    enum_ref: "ayyMemberGradeInfo.ayymembergradesearch"
    patterns_template:
      - '{SEARCH}{enum}(?:的)?安有医(?:客户|会员|权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:有|拥有|享有){enum}(?:安有医)?权益{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymembergradesearch"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 14
    merge_to_llm: true

  - name: "安有医-等级为空"
    patterns:
      - '{SEARCH}(?:安有医)(?:会员)?(?:等级|版本)(?:还)?(?:没定|未定|没有|为空|没填|未填|没登记|未登记)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:没有|无)(?:安有医)(?:会员)?(?:等级|版本){CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymembergradesearch"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "安有医-期次为空"
    patterns:
      - '{SEARCH}安有医(?:是)?哪一期(?:还)?(?:没|未)(?:登记|填写|填){CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:会员)?(?:期次|年度)(?:没有|为空|没填|未填|没登记|未登记){CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymemberperiod"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "安有医-2023期次"
    patterns:
      - '{SEARCH}(?:23|2023)年(?:那)?(?:一)?期(?:的)?安有医{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:是)?(?:23|2023)年(?:那)?(?:一)?期{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymemberperiod"
    operator: "MATCH"
    value_type: "static"
    value: "2023"
    priority: 14
    merge_to_llm: true

  - name: "安有护-等级排除"
    enum_ref: "ayhMemberGradeInfo.ayhmembergradesearch"
    patterns_template:
      - '{SEARCH}(?:安有护)?(?:不要|不是|排除|去掉|不含|不包含|没有){enum}(?:的)?(?:安有护)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:不要|不是|排除|去掉|不含|不包含){enum}(?:的)?安有护{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhmembergradesearch"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value: {group: 1}
    priority: 17
    merge_to_llm: true

  - name: "安有护-国内版排除口语"
    patterns:
      - '{SEARCH}(?:不是|不要|排除|去掉)安有护\(国内版\)(?:的)?安有护{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhmembergradesearch"
    operator: "NOT_CONTAINS"
    value_type: "static"
    value: ["安有护(国内版)"]
    priority: 18
    merge_to_llm: true

  - name: "安有护-等级反向表达"
    enum_ref: "ayhMemberGradeInfo.ayhmembergradesearch"
    patterns_template:
      - '{SEARCH}{enum}(?:的)?安有护?(?:客户|会员|权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:有|拥有|享有){enum}(?:权益)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhmembergradesearch"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 14
    merge_to_llm: true

  - name: "安有护-期次为空"
    patterns:
      - '{SEARCH}安有护(?:哪年|哪一期)(?:获得的)?(?:还)?(?:没填|未填|没登记|未登记){CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:会员)?(?:期次|年度)(?:没有|为空|没填|未填|没登记|未登记){CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhmemberperiod"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-等级排除"
    enum_ref: "zxjyMemberGradeInfo.zxjymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:臻享家医|家医)?(?:不要|不是|排除|去掉|不含|不包含|没有){enum}{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymembergradesearch"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value: {group: 1}
    priority: 17
    merge_to_llm: true

  - name: "臻享家医-等级为空"
    patterns:
      - '{SEARCH}(?:臻享家医|家医)(?:会员)?(?:等级|版本)(?:没有|为空|没填|未填|没定|未定){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:没有|无)(?:臻享家医|家医)(?:会员)?(?:等级|版本){CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymembergradesearch"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-状态排除"
    enum_ref: "zxjyMemberGradeInfo.zxjymemberstatus"
    patterns_template:
      - '{SEARCH}(?:臻享家医|家医)(?:不要|不是|排除|去掉|不含|不包含){enum}(?:客户|会员)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymemberstatus"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value: {group: 1}
    priority: 17
    merge_to_llm: true

  - name: "臻享家医-状态为空"
    patterns:
      - '{SEARCH}(?:臻享家医|家医)(?:会员)?(?:状态|类型)(?:没标|未标|没有|为空|没填|未填)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:没有|无)(?:臻享家医|家医)(?:会员)?(?:状态|类型){CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymemberstatus"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "平安居家-等级排除"
    enum_ref: "pajjMemberGradeInfo.pajjmembergradesearch"
    patterns_template:
      - '{SEARCH}(?:平安居家|居家养老|居家)?(?:不要|不是|排除|去掉|不含|不包含){enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}{enum}(?:不要|排除|去掉){CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmembergradesearch"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value: {group: 1}
    priority: 17
    merge_to_llm: true

  - name: "平安居家-期次为空"
    patterns:
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:权益)?(?:期次|年度)(?:没有|为空|没填|未填|没登记|未登记)(?:的)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmemberperiod"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "平安居家-2024期次"
    patterns:
      - '{SEARCH}(?:24|2024)年(?:那)?(?:一)?期(?:的)?(?:平安居家|居家养老|居家){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:是)?(?:24|2024)年(?:那)?(?:一)?期{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmemberperiod"
    operator: "MATCH"
    value_type: "static"
    value: "2024"
    priority: 14
    merge_to_llm: true

  - name: "御享国医-状态排除"
    enum_ref: "yxgyMemberGradeInfo.yxgymemberstatus"
    patterns_template:
      - '{SEARCH}御享国医(?:不要|不是|排除|去掉|不含|不包含){enum}(?:客户|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:不要|不是|排除|去掉|不含|不包含)御享国医{enum}(?:客户|会员)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgymemberstatus"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value: {group: 1}
    priority: 17
    merge_to_llm: true

  - name: "御享国医-状态为空"
    patterns:
      - '{SEARCH}御享国医(?:会员)?(?:状态|类型)(?:没标|未标|没有|为空|没填|未填)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:没有|无)御享国医(?:会员)?(?:状态|类型){CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgymemberstatus"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "私董保健医-等级排除"
    enum_ref: "sdbjyMemberGradeInfo.sdbjymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:私董保健医|私董|保健医)?(?:不要|不是|排除|去掉|不含|不包含){enum}{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjymembergradesearch"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value: {group: 1}
    priority: 17
    merge_to_llm: true

  - name: "私董保健医-期次为空"
    patterns:
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:是)?哪一期(?:还)?(?:没|未)(?:登记|填写|填){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:会员)?(?:期次|年度)(?:没有|为空|没填|未填|没登记|未登记){CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjymemberperiod"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "高端康养-等级排除"
    enum_ref: "gdkyMemberGradeInfo.gdkymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:高端康养|康养)?(?:不要|不是|排除|去掉|不含|不包含){enum}{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymembergradesearch"
    operator: "NOT_CONTAINS"
    value_type: "capture"
    value: {group: 1}
    priority: 17
    merge_to_llm: true

  - name: "高端康养-期次为空"
    patterns:
      - '{SEARCH}(?:高端康养|康养)(?:权益)?(?:期次|年度)(?:没有|为空|没填|未填|没登记|未登记)(?:的)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymemberperiod"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "高端康养-2025期次"
    patterns:
      - '{SEARCH}(?:25|2025)年(?:那)?(?:一)?期(?:的)?(?:高端康养|康养){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:是)?(?:25|2025)年(?:那)?(?:一)?期{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymemberperiod"
    operator: "MATCH"
    value_type: "static"
    value: "2025"
    priority: 14
    merge_to_llm: true

  # “临界客户”统一表示仍处于可转化阶段：潜客或意向，不包含已达标/维持。
  - name: "安有医-临界客户"
    patterns:
      - '{SEARCH}安有医(?:权益)?临界(?:的客户|客户|会员)?'
    field: "ayyMemberGradeInfo.ayymemberstatus"
    operator: "CONTAINS"
    value_type: "static"
    value: ["潜客", "意向"]
    priority: 20
    merge_to_llm: true

  - name: "安有护-临界客户"
    patterns:
      - '{SEARCH}安有护(?:权益)?临界(?:的客户|客户|会员)?'
    field: "ayhMemberGradeInfo.ayhmemberstatus"
    operator: "CONTAINS"
    value_type: "static"
    value: ["潜客", "意向"]
    priority: 20
    merge_to_llm: true

  - name: "臻享家医-临界客户"
    patterns:
      - '{SEARCH}(?:臻享家医|家医)(?:权益)?临界(?:的客户|客户|会员)?'
    field: "zxjyMemberGradeInfo.zxjymemberstatus"
    operator: "CONTAINS"
    value_type: "static"
    value: ["潜客", "意向"]
    priority: 20
    merge_to_llm: true

  - name: "平安居家-临界客户"
    patterns:
      - '{SEARCH}(?:平安居家|居家养老|居家|居养)(?:权益)?临界(?:的客户|客户|会员)?'
    field: "pajjMemberGradeInfo.pajjmemberstatus"
    operator: "CONTAINS"
    value_type: "static"
    value: ["潜客", "意向"]
    priority: 20
    merge_to_llm: true

  - name: "御享国医-临界客户"
    patterns:
      - '{SEARCH}御享国医(?:权益)?临界(?:的客户|客户|会员)?'
    field: "yxgyMemberGradeInfo.yxgymemberstatus"
    operator: "CONTAINS"
    value_type: "static"
    value: ["潜客", "意向"]
    priority: 20
    merge_to_llm: true

  - name: "私董保健医-临界客户"
    patterns:
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:权益)?临界(?:的客户|客户|会员)?'
    field: "sdbjyMemberGradeInfo.sdbjymemberstatus"
    operator: "CONTAINS"
    value_type: "static"
    value: ["潜客", "意向"]
    priority: 20
    merge_to_llm: true

  - name: "高端康养-临界客户"
    patterns:
      - '{SEARCH}(?:高端康养|康养)(?:权益)?临界(?:的客户|客户|会员)?'
    field: "gdkyMemberGradeInfo.gdkymemberstatus"
    operator: "CONTAINS"
    value_type: "static"
    value: ["潜客", "意向"]
    priority: 20
    merge_to_llm: true

  - name: "臻享家医-状态口语"
    enum_ref: "zxjyMemberGradeInfo.zxjymemberstatus"
    patterns_template:
      - '{SEARCH}(?:全部的)?(?:臻享家医|家医)(?:已经是?|已是?|现在是?)?{enum}(?:客户|会员)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:全部的)?(?:已经是?|已是?|现在是?)?{enum}(?:的)?(?:臻享家医|家医)(?:客户|会员)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymemberstatus"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 14
    merge_to_llm: true

  - name: "臻享家医-适合促成"
    patterns:
      - '{SEARCH}(?:适合|可以|能够)(?:促成|转化|跟进|开发)(?:的)?(?:臻享家医|家医|臻享)(?:客户|会员)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医|臻享)(?:的)?(?:适合|可)(?:促成|转化|跟进|开发)(?:客户|会员)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymemberstatus"
    operator: "CONTAINS"
    value_type: "static"
    value:
      - "潜客"
    priority: 17
    merge_to_llm: true

  - name: "平安居家-状态口语"
    enum_ref: "pajjMemberGradeInfo.pajjmemberstatus"
    patterns_template:
      - '{SEARCH}(?:全部的)?(?:平安居家|居家养老|居家){enum}(?:客户|会员)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:全部的)?{enum}(?:的)?(?:平安居家|居家养老|居家)(?:客户|会员)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmemberstatus"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 14
    merge_to_llm: true

  - name: "御享国医-状态口语"
    enum_ref: "yxgyMemberGradeInfo.yxgymemberstatus"
    patterns_template:
      - '{SEARCH}(?:全部的)?御享国医{enum}(?:客户|会员)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:全部的)?{enum}(?:的)?御享国医(?:客户|会员)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgymemberstatus"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 14
    merge_to_llm: true

  - name: "私董保健医-状态口语"
    enum_ref: "sdbjyMemberGradeInfo.sdbjymemberstatus"
    patterns_template:
      - '{SEARCH}(?:全部的)?(?:私董保健医|私董|保健医)(?:的)?{enum}(?:客户|会员)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:全部的)?{enum}(?:的)?(?:私董保健医|私董|保健医)(?:客户|会员)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjymemberstatus"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 14
    merge_to_llm: true

  # 达标时间在业务问法中也常被称为“获得/拿到权益时间”。
  - name: "安有医-近期获得"
    patterns:
      - '{SEARCH}(?:最近一个月|近一个月|近期)(?:新)?(?:获得|拿到|有了?)?(?:颐享版|尊享版)?安有医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:颐享版|尊享版)?安有医(?:权益)?(?:在)?(?:最近一个月|近一个月|近期)(?:获得|拿到|新增)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "安有医-近期获得颐享版"
    patterns:
      - '{SEARCH}(?:最近一个月|近一个月|近期)(?:新)?(?:获得|拿到|有了?)颐享版安有医(?:权益)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 18
    merge_to_llm: true
    extra_conditions:
      - field: "ayyMemberGradeInfo.ayymembergradesearch"
        operator: "MATCH"
        value: "颐享版"

  - name: "安有医-近期获得尊享版"
    patterns:
      - '{SEARCH}(?:最近一个月|近一个月|近期)(?:新)?(?:获得|拿到|有了?)尊享版安有医(?:权益)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 18
    merge_to_llm: true
    extra_conditions:
      - field: "ayyMemberGradeInfo.ayymembergradesearch"
        operator: "MATCH"
        value: "尊享版"

  - name: "安有医-今年获得"
    patterns:
      - '{SEARCH}(?:今年|本年)(?:新)?(?:获得|拿到|有了?)安有医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:今年|本年)安有医(?:权益|会员)?(?:达标|获得|拿到)(?:了|的)?(?:这批|这些|那些|客户|人|这群人)?'
      - '{SEARCH}安有医(?:权益)?(?:在)?(?:今年|本年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "安有医-去年获得"
    patterns:
      - '{SEARCH}(?:去年|上一年)(?:是|成为|新)?(?:获得|拿到|有了?)?安有医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:权益)?(?:在)?(?:去年|上一年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "安有医-今天获得"
    patterns:
      - '{SEARCH}(?:今天|今日)(?:新)?(?:获得|拿到|有了?)安有医(?:权益)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "today", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "安有医-达标时间为空"
    patterns:
      - '{SEARCH}安有医(?:达标|获得|拿到)(?:时间|日期)?(?:还)?(?:没记录|未记录|没填|未填|为空|空着)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:没有|无)安有医(?:达标|获得)(?:时间|日期){CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "安有医-上周达标"
    patterns:
      - '{SEARCH}(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:权益)?{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: -1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "安有医-本周达标"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "安有医-下周达标"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:权益)?{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "安有医-上个月达标"
    patterns:
      - '{SEARCH}(?:最近发生.{0,3})?(?:上个月|上月)(?:今年|本年)?{CW}{0,2}安有医(?:权益|会员)?(?:达标|获得|拿到)(?:了)?(?:的)?(?:客户|人|有谁|有哪些)?'
      - '{SEARCH}(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上个月|上月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:权益)?{CW}{0,2}(?:在|为|是)(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "安有医-本月达标"
    patterns:
      - '{SEARCH}(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本月|这个月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:权益)?{CW}{0,2}(?:在|为|是)(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "安有医-下个月达标"
    patterns:
      - '{SEARCH}(?:下个月|下月)(?:今年|本年)?{CW}{0,2}安有医(?:权益|会员)?(?:达标|获得|拿到)(?:了)?(?:的)?(?:客户|人|有谁|有哪些)?'
      - '{SEARCH}(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下个月|下月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:权益)?{CW}{0,2}(?:在|为|是)(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "安有医-即将达标"
    patterns:
      - '{SEARCH}(?:即将|快要|马上)(?:今年|本年)?安有医(?:权益|会员)?(?:达标|获得|拿到)(?:的客户|客户|的人|人)?'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 17
    merge_to_llm: true

  - name: "安有医-近N天达标"
    patterns:
      - '{SEARCH}(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:权益)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days_group: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "安有护-近期获得"
    patterns:
      - '{SEARCH}(?:最近一个月|近一个月|近期)(?:新)?(?:获得|拿到|有了?)?(?:安有护\(国际版\)|安有护\(国内版\)|安有护)(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:安有护\(国际版\)|安有护\(国内版\)|安有护)(?:权益)?(?:在)?(?:最近一个月|近一个月|近期)(?:获得|拿到|新增)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "安有护-近期获得国际版"
    patterns:
      - '{SEARCH}(?:最近一个月|近一个月|近期)(?:新)?(?:获得|拿到|有了?)安有护\(国际版\)(?:权益)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 18
    merge_to_llm: true
    extra_conditions:
      - field: "ayhMemberGradeInfo.ayhmembergradesearch"
        operator: "MATCH"
        value: "安有护(国际版)"

  - name: "安有护-近期获得国内版"
    patterns:
      - '{SEARCH}(?:最近一个月|近一个月|近期)(?:新)?(?:获得|拿到|有了?)安有护\(国内版\)(?:权益)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 18
    merge_to_llm: true
    extra_conditions:
      - field: "ayhMemberGradeInfo.ayhmembergradesearch"
        operator: "MATCH"
        value: "安有护(国内版)"

  - name: "安有护-今年获得"
    patterns:
      - '{SEARCH}(?:今年|本年)(?:新)?(?:获得|拿到|有了?)安有护(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:今年|本年)安有护(?:权益|会员)?(?:达标|获得|拿到)(?:了|的)?(?:这批|这些|那些|客户|人|这群人)?'
      - '{SEARCH}安有护(?:权益)?(?:在)?(?:今年|本年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "安有护-去年获得"
    patterns:
      - '{SEARCH}(?:去年|上一年)(?:是|成为|新)?(?:获得|拿到|有了?)?安有护(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:权益)?(?:在)?(?:去年|上一年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "安有护-达标时间为空"
    patterns:
      - '{SEARCH}安有护(?:达标|获得|拿到)(?:时间|日期)?(?:还)?(?:没记录|未记录|没填|未填|为空|空着){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:没有|无)安有护(?:达标|获得)(?:时间|日期){CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "安有护-上周达标"
    patterns:
      - '{SEARCH}(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有护(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: -1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "安有护-本周达标"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有护(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "安有护-下周达标"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有护(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "安有护-上个月达标"
    patterns:
      - '{SEARCH}(?:最近发生.{0,3})?(?:上个月|上月)(?:今年|本年)?{CW}{0,2}安有护(?:权益|会员)?(?:达标|获得|拿到)(?:了)?(?:的)?(?:客户|人|有谁|有哪些)?'
      - '{SEARCH}(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有护(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上个月|上月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "安有护-本月达标"
    patterns:
      - '{SEARCH}(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有护(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本月|这个月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "安有护-下个月达标"
    patterns:
      - '{SEARCH}(?:下个月|下月)(?:今年|本年)?{CW}{0,2}安有护(?:权益|会员)?(?:达标|获得|拿到)(?:了)?(?:的)?(?:客户|人|有谁|有哪些)?'
      - '{SEARCH}(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有护(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下个月|下月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "安有护-即将达标"
    patterns:
      - '{SEARCH}(?:即将|快要|马上)(?:今年|本年)?安有护(?:权益|会员)?(?:达标|获得|拿到)(?:的客户|客户|的人|人)?'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 17
    merge_to_llm: true

  - name: "安有护-近N天达标"
    patterns:
      - '{SEARCH}(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?安有护(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "last_n_days"
      days_group: 1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-近期获得"
    patterns:
      - '{SEARCH}(?:最近一个月|近一个月|近期)(?:新)?(?:获得|拿到|有了?)?(?:臻享家医|家医)(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:权益)?(?:在)?(?:最近一个月|近一个月|近期)(?:获得|拿到|新增)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "臻享家医-今年获得"
    patterns:
      - '{SEARCH}(?:今年|本年)(?:是|新)?(?:获得|拿到|有了?)?(?:臻享家医|家医)(?:权益)?(?:臻享家医V[123])?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:今年|本年)(?:臻享家医|家医)(?:权益|会员)?(?:达标|获得|拿到)(?:的)?(?:这批|客户|人|名单)?'
      - '{SEARCH}(?:臻享家医|家医)(?:权益)?(?:在)?(?:今年|本年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "臻享家医-去年获得"
    patterns:
      - '{SEARCH}(?:去年|上一年)(?:是|新)?(?:获得|拿到|有了?)?(?:臻享家医|家医)(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:去年|上一年)(?:是|成为)?(?:臻享家医|家医){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:权益)?(?:在)?(?:去年|上一年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "臻享家医-2023到2025获得"
    patterns:
      - '{SEARCH}(?:23|2023)年?(?:到|至|-)(?:25|2025)年(?:获得|拿到|达标)?(?:臻享家医|家医)(?:权益)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:权益)?(?:在)?(?:23|2023)年?(?:到|至|-)(?:25|2025)年(?:获得|拿到|达标)?(?:的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "range"
    value:
      min: "2023-01-01 00:00:00"
      max: "2025-12-31 00:00:00"
    priority: 17
    merge_to_llm: true

  - name: "臻享家医-达标时间为空"
    patterns:
      - '{SEARCH}(?:臻享家医|家医)(?:达标|获得|拿到)(?:时间|日期)?(?:还)?(?:没记录|未记录|没填|未填|为空|空着){CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-上周达标"
    patterns:
      - '{SEARCH}(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:臻享家医|家医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医){CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: -1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-本周达标"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:臻享家医|家医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医){CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-下周达标"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:臻享家医|家医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-上个月达标"
    patterns:
      - '{SEARCH}(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:臻享家医|家医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上个月|上月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-本月达标"
    patterns:
      - '{SEARCH}(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:臻享家医|家医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本月|这个月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-下个月达标"
    patterns:
      - '{SEARCH}(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:臻享家医|家医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下个月|下月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "臻享家医-近N天达标"
    patterns:
      - '{SEARCH}(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:臻享家医|家医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|家医)(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days_group: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "平安居家-近期获得"
    patterns:
      - '{SEARCH}(?:最近一个月|近一个月|近期)(?:新)?(?:获得|拿到|新增|有了?)?(?:平安居家|居家养老|居家)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:权益)?(?:在)?(?:最近一个月|近一个月|近期)(?:获得|拿到|新增)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "平安居家-月份区间达标"
    patterns:
      - '{SEARCH}(\d{1,2})月?[-~到至](\d{1,2})月份?(?:平安居家|居家养老|居养老|居养)客户'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year_month_range"
      start_month_group: 1
      end_month_group: 2
      format: "yyyy-MM-dd"
    priority: 24
    merge_to_llm: false

  - name: "安有医-月份区间达标"
    patterns:
      - '{SEARCH}(\d{1,2})月?[-~到至](\d{1,2})月份?安有医(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year_month_range"
      start_month_group: 1
      end_month_group: 2
      format: "yyyy-MM-dd"
    priority: 24
    merge_to_llm: false

  - name: "安有护-月份区间达标"
    patterns:
      - '{SEARCH}(\d{1,2})月?[-~到至](\d{1,2})月份?安有护(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year_month_range"
      start_month_group: 1
      end_month_group: 2
      format: "yyyy-MM-dd"
    priority: 24
    merge_to_llm: false

  - name: "臻享家医-月份区间达标"
    patterns:
      - '{SEARCH}(\d{1,2})月?[-~到至](\d{1,2})月份?(?:臻享家医|臻享|家医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year_month_range"
      start_month_group: 1
      end_month_group: 2
      format: "yyyy-MM-dd"
    priority: 24
    merge_to_llm: false

  - name: "御享国医-月份区间达标"
    patterns:
      - '{SEARCH}(\d{1,2})月?[-~到至](\d{1,2})月份?御享国医(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year_month_range"
      start_month_group: 1
      end_month_group: 2
      format: "yyyy-MM-dd"
    priority: 24
    merge_to_llm: false

  - name: "私董保健医-月份区间达标"
    patterns:
      - '{SEARCH}(\d{1,2})月?[-~到至](\d{1,2})月份?(?:私董保健医|私董|保健医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year_month_range"
      start_month_group: 1
      end_month_group: 2
      format: "yyyy-MM-dd"
    priority: 24
    merge_to_llm: false

  - name: "高端康养-月份区间达标"
    patterns:
      - '{SEARCH}(\d{1,2})月?[-~到至](\d{1,2})月份?(?:高端康养|康养)(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "current_year_month_range"
      start_month_group: 1
      end_month_group: 2
      format: "yyyy-MM-dd"
    priority: 24
    merge_to_llm: false

  - name: "安有医-年份前置达标"
    patterns:
      - '{SEARCH}(\d{4})年安有医(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 24
    merge_to_llm: false

  - name: "安有护-年份前置达标"
    patterns:
      - '{SEARCH}(\d{4})年安有护(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 24
    merge_to_llm: false

  - name: "臻享家医-年份前置达标"
    patterns:
      - '{SEARCH}(\d{4})年(?:臻享家医|臻享|家医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 24
    merge_to_llm: false

  - name: "御享国医-年份前置达标"
    patterns:
      - '{SEARCH}(\d{4})年御享国医(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 24
    merge_to_llm: false

  - name: "私董保健医-年份前置达标"
    patterns:
      - '{SEARCH}(\d{4})年(?:私董保健医|私董|保健医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 24
    merge_to_llm: false

  - name: "高端康养-年份前置达标"
    patterns:
      - '{SEARCH}(\d{4})年(?:高端康养|康养)(?:权益|会员)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 24
    merge_to_llm: false

  - name: "平安居家-年份前置达标"
    patterns:
      - '{SEARCH}(\d{4})年(?:平安居家|居家养老|居养老|居养)客户'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 24
    merge_to_llm: false

  - name: "平安居家-老客户升级潜客"
    patterns:
      - '{SEARCH}老客户这个月可以增加保费升级到(?:平安居家|居家养老|居养老|居养)的客户'
    field: "pajjMemberGradeInfo.pajjmemberstatus"
    operator: "MATCH"
    value_type: "static"
    value: "潜客"
    priority: 25
    merge_to_llm: false

  - name: "平安福年交保费超一万"
    patterns:
      - '{SEARCH}平安福年(?:交|缴)保费(?:超|超过|大于|高于)1万(?:元)?的客户'
    field: "polNoInfo.plancodeinfo.abbrname"
    operator: "MATCH"
    value_type: "static"
    value: "平安福"
    priority: 25
    merge_to_llm: false
    extra_conditions:
      - field: "annPremSegNum"
        operator: "GT"
        value: 10000

  - name: "平安居家-上个月达标"
    patterns:
      - '{SEARCH}(?:上个月|上月)(?:新)?(?:获得|拿到|新增|达标)?(?:的)?(?:平安居家|居家养老|居家)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:权益|会员)?(?:在)?(?:上个月|上月)(?:获得|拿到|新增|达标)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上个月|上月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家){CW}{0,2}(?:在|为|是)(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 17
    merge_to_llm: true

  - name: "平安居家-今年获得"
    patterns:
      - '{SEARCH}(?:今年|本年)(?:新)?(?:获得|拿到|有了?)?(?:平安居家|居家养老|居家)(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:权益)?(?:在)?(?:今年|本年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "平安居家-去年获得"
    patterns:
      - '{SEARCH}(?:去年|上一年)(?:是|成为|新)?(?:获得|拿到|有了?)?(?:平安居家|居家养老|居家)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:权益)?(?:在)?(?:去年|上一年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "平安居家-达标时间为空"
    patterns:
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:什么时候)?(?:达标|获得|拿到)(?:的)?(?:时间|日期)?(?:还)?(?:没记|未记|没记录|未记录|没填|未填|为空|空着){CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "平安居家-上周达标"
    patterns:
      - '{SEARCH}(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:平安居家|居家养老|居家)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家){CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: -1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "平安居家-本周达标"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:平安居家|居家养老|居家)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家){CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "平安居家-下周达标"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:平安居家|居家养老|居家)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家){CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "平安居家-本月达标"
    patterns:
      - '{SEARCH}(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:平安居家|居家养老|居家)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本月|这个月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家){CW}{0,2}(?:在|为|是)(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "平安居家-下个月达标"
    patterns:
      - '{SEARCH}(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:平安居家|居家养老|居家)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下个月|下月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家){CW}{0,2}(?:在|为|是)(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "平安居家-近N天达标"
    patterns:
      - '{SEARCH}(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:平安居家|居家养老|居家)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days_group: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "御享国医-近期获得"
    patterns:
      - '{SEARCH}(?:最近一个月|近一个月|近期)(?:新)?(?:获得|拿到|有了?)?御享国医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:权益)?(?:在)?(?:最近一个月|近一个月|近期)(?:获得|拿到|新增)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "御享国医-今年获得"
    patterns:
      - '{SEARCH}(?:今年|本年)(?:是|新)?(?:获得|拿到|有了?)?御享国医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:权益)?(?:在)?(?:今年|本年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "御享国医-去年获得"
    patterns:
      - '{SEARCH}(?:去年|上一年)(?:是|成为|新)?(?:获得|拿到|有了?)?御享国医(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:权益)?(?:在)?(?:去年|上一年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "御享国医-达标时间为空"
    patterns:
      - '{SEARCH}御享国医(?:达标|获得|拿到)(?:时间|日期)?(?:还)?(?:没记录|未记录|没填|未填|为空|空着){CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "御享国医-上周达标"
    patterns:
      - '{SEARCH}(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?御享国医(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: -1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "御享国医-本周达标"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?御享国医(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "御享国医-下周达标"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?御享国医(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "御享国医-上个月达标"
    patterns:
      - '{SEARCH}(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?御享国医(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上个月|上月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医{CW}{0,2}(?:在|为|是)(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "御享国医-本月达标"
    patterns:
      - '{SEARCH}(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?御享国医(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本月|这个月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医{CW}{0,2}(?:在|为|是)(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "御享国医-下个月达标"
    patterns:
      - '{SEARCH}(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?御享国医(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下个月|下月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医{CW}{0,2}(?:在|为|是)(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "御享国医-近N天达标"
    patterns:
      - '{SEARCH}(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?御享国医(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days_group: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "私董保健医-近期获得"
    patterns:
      - '{SEARCH}(?:最近一个月|近一个月|近期)(?:新)?(?:获得|拿到|有了?)?(?:私董保健医|私董|保健医)(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:权益)?(?:在)?(?:最近一个月|近一个月|近期)(?:获得|拿到|新增)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "私董保健医-今年获得"
    patterns:
      - '{SEARCH}(?:今年|本年)(?:是|新)?(?:获得|拿到|有了?)?(?:私董保健医|私董|保健医)(?:权益)?(?:京华版|繁花版)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:权益)?(?:在)?(?:今年|本年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "私董保健医-今年京华版"
    patterns:
      - '{SEARCH}(?:今年|本年)(?:是|新)?(?:获得|拿到|有了?)?(?:私董保健医|私董|保健医)京华版{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 18
    merge_to_llm: true
    extra_conditions:
      - field: "sdbjyMemberGradeInfo.sdbjymembergradesearch"
        operator: "MATCH"
        value: "京华版"

  - name: "私董保健医-去年获得"
    patterns:
      - '{SEARCH}(?:去年|上一年)(?:是|成为|新)?(?:获得|拿到|有了?)?(?:(?:私董保健医|私董|保健医)(?:京华版|繁花版)?|(?:京华版|繁花版)(?:私董保健医|私董|保健医))(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:权益)?(?:在)?(?:去年|上一年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "私董保健医-去年京华版"
    patterns:
      - '{SEARCH}(?:去年|上一年)(?:是|新)?(?:获得|拿到|有了?)?(?:私董保健医|私董|保健医)京华版{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 18
    merge_to_llm: true
    extra_conditions:
      - field: "sdbjyMemberGradeInfo.sdbjymembergradesearch"
        operator: "MATCH"
        value: "京华版"

  - name: "私董保健医-达标时间为空"
    patterns:
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:达标|获得|拿到)(?:时间|日期)?(?:还)?(?:没记录|未记录|没填|未填|为空|空着){CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "私董保健医-上周达标"
    patterns:
      - '{SEARCH}(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:私董保健医|私董|保健医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医){CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: -1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "私董保健医-本周达标"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:私董保健医|私董|保健医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医){CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "私董保健医-下周达标"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:私董保健医|私董|保健医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医){CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "私董保健医-上个月达标"
    patterns:
      - '{SEARCH}(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:私董保健医|私董|保健医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上个月|上月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医){CW}{0,2}(?:在|为|是)(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "私董保健医-本月达标"
    patterns:
      - '{SEARCH}(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:私董保健医|私董|保健医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本月|这个月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医){CW}{0,2}(?:在|为|是)(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "私董保健医-下个月达标"
    patterns:
      - '{SEARCH}(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:私董保健医|私董|保健医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下个月|下月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医){CW}{0,2}(?:在|为|是)(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "私董保健医-近N天达标"
    patterns:
      - '{SEARCH}(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:私董保健医|私董|保健医)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days_group: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "高端康养-近期获得"
    patterns:
      - '{SEARCH}(?:最近一个月|近一个月|近期)(?:新)?(?:获得|拿到|有了?)?(?:高端康养|康养)(?:权益)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:权益)?(?:在)?(?:最近一个月|近一个月|近期)(?:获得|拿到|新增)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "高端康养-今年获得"
    patterns:
      - '{SEARCH}(?:今年|本年)(?:新)?(?:获得|拿到|有了?)?(?:高端康养|康养)(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:权益)?(?:在)?(?:今年|本年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "高端康养-今年逸享会员"
    patterns:
      - '{SEARCH}(?:今年|本年)(?:新)?(?:获得|拿到|有了?)?(?:高端康养|康养)逸享会员{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 18
    merge_to_llm: true
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkymembergradesearch"
        operator: "MATCH"
        value: "逸享会员"

  - name: "高端康养-去年获得"
    patterns:
      - '{SEARCH}(?:去年|上一年)(?:是|成为|新)?(?:获得|拿到|有了?)?(?:高端康养|康养)(?:权益)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:去年|上一年)(?:是|成为)?(?:的)?(?:高端康养|康养)(?:客户|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:权益)?(?:在)?(?:去年|上一年)(?:获得|拿到|达标)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 15
    merge_to_llm: true

  - name: "高端康养-去年逸享会员"
    patterns:
      - '{SEARCH}(?:去年|上一年)(?:新)?(?:获得|拿到|有了?)?(?:高端康养|康养)逸享会员{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_year", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 18
    merge_to_llm: true
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkymembergradesearch"
        operator: "MATCH"
        value: "逸享会员"

  - name: "高端康养-达标时间为空"
    patterns:
      - '{SEARCH}(?:高端康养|康养)(?:达标|获得|拿到)(?:时间|日期)?(?:还)?(?:没记录|未记录|没填|未填|为空|空着){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:没有|无)(?:高端康养|康养)(?:达标|获得)(?:时间|日期){CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "NOT_EXISTS"
    value_type: "static"
    value: ""
    priority: 16
    merge_to_llm: true

  - name: "高端康养-上周达标"
    patterns:
      - '{SEARCH}(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:高端康养|康养)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养){CW}{0,2}(?:在|为|是)(?:上周|上星期|上个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: -1
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "高端康养-本周达标"
    patterns:
      - '{SEARCH}(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:高端康养|康养)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养){CW}{0,2}(?:在|为|是)(?:本周|这周|这个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"
    priority: 16
    merge_to_llm: true

  - name: "高端康养-下周达标"
    patterns:
      - '{SEARCH}(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:高端康养|康养)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养){CW}{0,2}(?:在|为|是)(?:下周|下星期|下个星期){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "week_offset", offset: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "高端康养-上个月达标"
    patterns:
      - '{SEARCH}(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:高端康养|康养)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:上个月|上月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养){CW}{0,2}(?:在|为|是)(?:上个月|上月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "高端康养-本月达标"
    patterns:
      - '{SEARCH}(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:高端康养|康养)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:本月|这个月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养){CW}{0,2}(?:在|为|是)(?:本月|这个月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "current_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "高端康养-下个月达标"
    patterns:
      - '{SEARCH}(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:高端康养|康养)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:下个月|下月)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养){CW}{0,2}(?:在|为|是)(?:下个月|下月){CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "next_month", format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "高端康养-近N天达标"
    patterns:
      - '{SEARCH}(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?(?:高端康养|康养)(?:权益|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:的)?(?:达标|获得|拿到)(?:时间|日期)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)(?:权益|会员)?{CW}{0,2}(?:在|为|是)(?:近|最近)(\d+)天(?:内|里|之?内)?{CW}{0,2}(?:达标|获得|拿到)(?:了|的)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days_group: 1, format: "yyyy-MM-dd HH:mm:ss"}
    priority: 16
    merge_to_llm: true

  - name: "安有医-达标年份"
    patterns:
      - '{SEARCH}安有医(?:会员)?(?:在)?(\d{4})年达标{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:会员)?达标(?:时间|日期)?(?:为|是|在)?(\d{4})年{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有医(?:会员)?(?:从|自)?(\d{4})年(?:达标)?(?:以来|至今|到现在)(?:的)?{CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayyqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 13
    merge_to_llm: true

  - name: "安有护-达标年份"
    patterns:
      - '{SEARCH}安有护(?:会员)?(?:在)?(\d{4})年达标{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:会员)?达标(?:时间|日期)?(?:为|是|在)?(\d{4})年{CUSTOMER_SUFFIX}'
      - '{SEARCH}安有护(?:会员)?(?:从|自)?(\d{4})年(?:达标)?(?:以来|至今|到现在)(?:的)?{CUSTOMER_SUFFIX}'
    field: "ayhMemberGradeInfo.ayhqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 13
    merge_to_llm: true

  - name: "臻享家医-达标年份"
    patterns:
      - '{SEARCH}(?:臻享家医|臻享)(?:会员)?(?:在)?(\d{4})年达标{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|臻享)(?:会员)?达标(?:时间|日期)?(?:为|是|在)?(\d{4})年{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:臻享家医|臻享)(?:会员)?(?:从|自)?(\d{4})年(?:达标)?(?:以来|至今|到现在)(?:的)?{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjyqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 13
    merge_to_llm: true

  - name: "平安居家-达标年份"
    patterns:
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?(?:在)?(\d{4})年达标{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?达标(?:时间|日期)?(?:为|是|在)?(\d{4})年{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)(?:会员)?(?:从|自)?(\d{4})年(?:达标)?(?:以来|至今|到现在)(?:的)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 13
    merge_to_llm: true

  - name: "御享国医-达标年份"
    patterns:
      - '{SEARCH}御享国医(?:会员)?(?:在)?(\d{4})年达标{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:会员)?达标(?:时间|日期)?(?:为|是|在)?(\d{4})年{CUSTOMER_SUFFIX}'
      - '{SEARCH}御享国医(?:会员)?(?:从|自)?(\d{4})年(?:达标)?(?:以来|至今|到现在)(?:的)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 13
    merge_to_llm: true

  - name: "私董保健医-达标年份"
    patterns:
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:会员)?(?:在)?(\d{4})年达标{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董|保健医)(?:会员)?达标(?:时间|日期)?(?:为|是|在)?(\d{4})年{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董)(?:会员)?(?:从|自)?(\d{4})年(?:达标)?(?:以来|至今|到现在)(?:的)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 13
    merge_to_llm: true

  - name: "高端康养-达标年份"
    patterns:
      - '{SEARCH}高端康养(?:会员)?(?:在)?(\d{4})年达标{CUSTOMER_SUFFIX}'
      - '{SEARCH}高端康养(?:会员)?达标(?:时间|日期)?(?:为|是|在)?(\d{4})年{CUSTOMER_SUFFIX}'
      - '{SEARCH}高端康养(?:会员)?(?:从|自)?(\d{4})年(?:达标)?(?:以来|至今|到现在)(?:的)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
    operator: "RANGE"
    value_type: "exact_range"
    value:
      group: 1
      transform: "year_to_birth_range"
    priority: 13
    merge_to_llm: true

  - name: "臻享家医等级以上+高端康养已达标"
    enum_ref: "zxjyMemberGradeInfo.zxjymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:臻享家医|家医)?{enum}及?以上(?:并且|且|同时|又是|，|,){CW}{0,4}(?:高端康养|康养)(?:已)?达标{CUSTOMER_SUFFIX}'
    field: "zxjyMemberGradeInfo.zxjymembergradesearch"
    operator: "CONTAINS"
    value_type: "enum_gte"
    value: {group: 1}
    priority: 20
    merge_to_llm: true
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkymemberstatus"
        operator: "MATCH"
        value: "达标"

  - name: "所有会员权益都没标"
    patterns:
      - '{SEARCH}(?:所有|全部)(?:的)?会员权益(?:都)?(?:没标|未标|没有标|没达标){CUSTOMER_SUFFIX}'
      - '{SEARCH}会员权益(?:全部|都)(?:没标|未标|没有标|没达标){CUSTOMER_SUFFIX}'
    field: "ayyMemberGradeInfo.ayymemberstatus"
    operator: "NOT_CONTAINS"
    value_type: "static"
    value: ["达标"]
    priority: 20
    merge_to_llm: true
    extra_conditions:
      - field: "ayhMemberGradeInfo.ayhmemberstatus"
        operator: "NOT_CONTAINS"
        value: ["达标"]
      - field: "zxjyMemberGradeInfo.zxjymemberstatus"
        operator: "NOT_CONTAINS"
        value: ["达标"]
      - field: "pajjMemberGradeInfo.pajjmemberstatus"
        operator: "NOT_CONTAINS"
        value: ["达标"]
      - field: "yxgyMemberGradeInfo.yxgymemberstatus"
        operator: "NOT_CONTAINS"
        value: ["达标"]
      - field: "sdbjyMemberGradeInfo.sdbjymemberstatus"
        operator: "NOT_CONTAINS"
        value: "达标"
      - field: "gdkyMemberGradeInfo.gdkymemberstatus"
        operator: "NOT_CONTAINS"
        value: "达标"

  # ==================== 潜客、下一等级与保费缺口 ====================

  - name: "是否潜客-是"
    patterns:
      - '{SEARCH}(?:潜客|潜在客户|准潜客|全部潜客|所有潜客|名下所有潜客|名下全部潜客)(?:有哪些|有谁|名单)?{CUSTOMER_SUFFIX}'
    field: "qkflag"
    operator: "MATCH"
    value_type: "static"
    value: "是"
    priority: 24
    merge_to_llm: true

  - name: "是否潜客-否"
    patterns:
      - '{SEARCH}(?:非潜客|不是潜客|不属于潜客)(?:有哪些|有谁|名单)?{CUSTOMER_SUFFIX}'
    field: "qkflag"
    operator: "MATCH"
    value_type: "static"
    value: "否"
    priority: 25
    merge_to_llm: true

  - name: "御享国医-潜客"
    patterns:
      - '{SEARCH}(?:(?:全部|所有|全量)(?:的)?)?(?:御享国医|国医)(?:的)?(?:(?:全部|所有)(?:的)?)?(?:潜客|潜在客户|准潜客)(?:中|里|里面|当中|范围内)?(?:有哪些|有谁|名单)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgymemberstatus"
    operator: "MATCH"
    value_type: "static"
    value: "潜客"
    priority: 30
    merge_to_llm: true

  - name: "私董保健医-潜客"
    patterns:
      - '{SEARCH}(?:(?:全部|所有|全量)(?:的)?)?(?:私董保健医|私董保健康|私董)(?:的)?(?:(?:全部|所有)(?:的)?)?(?:潜客|潜在客户|准潜客)(?:中|里|里面|当中|范围内)?(?:有哪些|有谁|名单)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjymemberstatus"
    operator: "MATCH"
    value_type: "static"
    value: "潜客"
    priority: 30
    merge_to_llm: true

  - name: "平安居家-潜客"
    patterns:
      - '{SEARCH}(?:(?:全部|所有|全量)(?:的)?)?(?:平安居家|居家养老|居家)(?:的)?(?:(?:全部|所有)(?:的)?)?(?:潜客|潜在客户|准潜客)(?:中|里|里面|当中|范围内)?(?:有哪些|有谁|名单)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjmemberstatus"
    operator: "MATCH"
    value_type: "static"
    value: "潜客"
    priority: 30
    merge_to_llm: true

  - name: "高端康养-潜客"
    patterns:
      - '{SEARCH}(?:(?:全部|所有|全量)(?:的)?)?(?:高端康养|康养)(?:的)?(?:(?:全部|所有)(?:的)?)?(?:潜客|潜在客户|准潜客)(?:中|里|里面|当中|范围内)?(?:有哪些|有谁|名单)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymemberstatus"
    operator: "MATCH"
    value_type: "static"
    value: "潜客"
    priority: 30
    merge_to_llm: true

  - name: "高端康养-指定等级潜客"
    enum_ref: "gdkyMemberGradeInfo.gdkymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:高端康养|康养)?{enum}(?:的)?潜客(?:有哪些|有谁|名单)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymemberstatus"
    operator: "MATCH"
    value_type: "static"
    value: "潜客"
    priority: 32
    merge_to_llm: true
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkymembergradesearch"
        operator: "MATCH"
        value_type: "capture"
        value: {group: 1}

  - name: "御享国医-总保费缺口精确值"
    patterns:
      - '{SEARCH}(?:御享国医|国医)(?:的)?(?:总)?保费缺口(?:为|是|等于)?(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgytotalpremgap"
    operator: "RANGE"
    value_type: "capture"
    value: {group: 1, transform: "exact_range"}
    priority: 35
    merge_to_llm: true

  - name: "御享国医-总保费缺口大于"
    patterns:
      - '{SEARCH}(?:御享国医|国医)(?:的)?(?:总)?保费缺口(?:为|是)?(?:大于|超过|高于|多于)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:御享国医|国医)(?:还|仍)?(?:差|缺)(?:大于|超过|高于|多于)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgytotalpremgap"
    operator: "GT"
    value_type: "capture"
    value: {group: 1, transform: "number"}
    priority: 36
    merge_to_llm: true

  - name: "御享国医-总保费缺口大于等于"
    patterns:
      - '{SEARCH}(?:御享国医|国医)(?:的)?(?:总)?保费缺口(?:为|是)?(?:大于等于|不少于|不低于|至少|起码)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:御享国医|国医)(?:的)?(?:总)?保费缺口(?:为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:及以上|以上){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:御享国医|国医)(?:还|仍)?(?:差|缺)(?:大于等于|不少于|不低于|至少|起码)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:御享国医|国医)(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:及以上|以上)(?:保费)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgytotalpremgap"
    operator: "GTE"
    value_type: "capture"
    value: {group: 1, transform: "number"}
    priority: 37
    merge_to_llm: true

  - name: "御享国医-总保费缺口小于"
    patterns:
      - '{SEARCH}(?:御享国医|国医)(?:的)?(?:总)?保费缺口(?:为|是)?(?:小于|低于|少于|不足|不到)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:御享国医|国医)(?:还|仍)?(?:差|缺)(?:小于|低于|少于|不足|不到)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgytotalpremgap"
    operator: "LT"
    value_type: "capture"
    value: {group: 1, transform: "number"}
    priority: 36
    merge_to_llm: true

  - name: "御享国医-总保费缺口小于等于"
    patterns:
      - '{SEARCH}(?:距离|离)?(?:御享国医|国医)(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:御享国医|国医)(?:的)?(?:总)?保费缺口(?:为|是)?(?:小于等于|不超过|不高于|至多|最多)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:御享国医|国医)(?:的)?(?:总)?保费缺口(?:为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:以内|及以下|以下){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:御享国医|国医)(?:还|仍)?(?:差|缺)(?:小于等于|不超过|不高于|至多|最多)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:御享国医|国医)(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:以内|及以下|以下)(?:保费)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgytotalpremgap"
    operator: "LTE"
    value_type: "capture"
    value: {group: 1, transform: "number"}
    priority: 37
    merge_to_llm: true

  - name: "御享国医-总保费缺口区间"
    patterns:
      - '{SEARCH}(?:御享国医|国医)(?:的)?(?:总)?保费缺口(?:在|为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:到|至|~|～|-)(\d+(?:\.\d+)?)万(?:元)?(?:之间)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:御享国医|国医)(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:到|至|~|～|-)(\d+(?:\.\d+)?)万(?:元)?(?:之间)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgytotalpremgap"
    operator: "RANGE"
    value_type: "range"
    value: {min_group: 1, max_group: 2, transform: "number"}
    priority: 38
    merge_to_llm: true

  - name: "私董保健康-指定下一等级保费缺口精确值"
    enum_ref: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:的)?(?:总)?保费缺口(?:为|是|等于)?(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 35
    merge_to_llm: true
    extra_conditions:
      - field: "sdbjyMemberGradeInfo.sdbjytotalpremgap"
        operator: "RANGE"
        value_type: "capture"
        value: {group: 2, transform: "exact_range"}

  - name: "私董保健康-指定下一等级保费缺口大于"
    enum_ref: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:的)?(?:总)?保费缺口(?:为|是)?(?:大于|超过|高于|多于)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:大于|超过|高于|多于)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 36
    merge_to_llm: true
    extra_conditions:
      - field: "sdbjyMemberGradeInfo.sdbjytotalpremgap"
        operator: "GT"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "私董保健康-指定下一等级保费缺口大于等于"
    enum_ref: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:的)?(?:总)?保费缺口(?:为|是)?(?:大于等于|不少于|不低于|至少|起码)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:的)?(?:总)?保费缺口(?:为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:及以上|以上){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:大于等于|不少于|不低于|至少|起码)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:及以上|以上)(?:保费)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 37
    merge_to_llm: true
    extra_conditions:
      - field: "sdbjyMemberGradeInfo.sdbjytotalpremgap"
        operator: "GTE"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "私董保健康-指定下一等级保费缺口小于"
    enum_ref: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:的)?(?:总)?保费缺口(?:为|是)?(?:小于|低于|少于|不足|不到)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:小于|低于|少于|不足|不到)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 36
    merge_to_llm: true
    extra_conditions:
      - field: "sdbjyMemberGradeInfo.sdbjytotalpremgap"
        operator: "LT"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "私董保健康-指定下一等级保费缺口小于等于"
    enum_ref: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:距离|离)?(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:的)?(?:总)?保费缺口(?:为|是)?(?:小于等于|不超过|不高于|至多|最多)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:的)?(?:总)?保费缺口(?:为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:以内|及以下|以下){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:小于等于|不超过|不高于|至多|最多)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:以内|及以下|以下)(?:保费)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 37
    merge_to_llm: true
    extra_conditions:
      - field: "sdbjyMemberGradeInfo.sdbjytotalpremgap"
        operator: "LTE"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "私董保健康-指定下一等级保费缺口区间"
    enum_ref: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:的)?(?:总)?保费缺口(?:在|为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:到|至|~|～|-)(\d+(?:\.\d+)?)万(?:元)?(?:之间)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:私董保健医|私董保健康|私董)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:到|至|~|～|-)(\d+(?:\.\d+)?)万(?:元)?(?:之间)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 38
    merge_to_llm: true
    extra_conditions:
      - field: "sdbjyMemberGradeInfo.sdbjytotalpremgap"
        operator: "RANGE"
        value_type: "range"
        value: {min_group: 2, max_group: 3, transform: "number"}

  - name: "平安居家-指定下一等级保费缺口精确值"
    enum_ref: "pajjMemberGradeInfo.pajjnextmembergrade"
    patterns_template:
      - '{SEARCH}(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:的)?(?:1\+N)?保费缺口(?:为|是|等于)?(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjnextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 35
    merge_to_llm: true
    extra_conditions:
      - field: "pajjMemberGradeInfo.pajjtotalpremgap"
        operator: "RANGE"
        value_type: "capture"
        value: {group: 2, transform: "exact_range"}

  - name: "平安居家-指定下一等级保费缺口大于"
    enum_ref: "pajjMemberGradeInfo.pajjnextmembergrade"
    patterns_template:
      - '{SEARCH}(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:的)?(?:1\+N)?保费缺口(?:为|是)?(?:大于|超过|高于|多于)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:大于|超过|高于|多于)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjnextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 36
    merge_to_llm: true
    extra_conditions:
      - field: "pajjMemberGradeInfo.pajjtotalpremgap"
        operator: "GT"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "平安居家-指定下一等级保费缺口大于等于"
    enum_ref: "pajjMemberGradeInfo.pajjnextmembergrade"
    patterns_template:
      - '{SEARCH}(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:的)?(?:1\+N)?保费缺口(?:为|是)?(?:大于等于|不少于|不低于|至少|起码)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:的)?(?:1\+N)?保费缺口(?:为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:及以上|以上){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:大于等于|不少于|不低于|至少|起码)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:及以上|以上)(?:保费)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjnextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 37
    merge_to_llm: true
    extra_conditions:
      - field: "pajjMemberGradeInfo.pajjtotalpremgap"
        operator: "GTE"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "平安居家-指定下一等级保费缺口小于"
    enum_ref: "pajjMemberGradeInfo.pajjnextmembergrade"
    patterns_template:
      - '{SEARCH}(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:的)?(?:1\+N)?保费缺口(?:为|是)?(?:小于|低于|少于|不足|不到)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:小于|低于|少于|不足|不到)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjnextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 36
    merge_to_llm: true
    extra_conditions:
      - field: "pajjMemberGradeInfo.pajjtotalpremgap"
        operator: "LT"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "平安居家-指定下一等级保费缺口小于等于"
    enum_ref: "pajjMemberGradeInfo.pajjnextmembergrade"
    patterns_template:
      - '{SEARCH}(?:距离|离)?(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:的)?(?:1\+N)?保费缺口(?:为|是)?(?:小于等于|不超过|不高于|至多|最多)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:的)?(?:1\+N)?保费缺口(?:为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:以内|及以下|以下){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:小于等于|不超过|不高于|至多|最多)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:以内|及以下|以下)(?:保费)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjnextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 37
    merge_to_llm: true
    extra_conditions:
      - field: "pajjMemberGradeInfo.pajjtotalpremgap"
        operator: "LTE"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "平安居家-指定下一等级保费缺口区间"
    enum_ref: "pajjMemberGradeInfo.pajjnextmembergrade"
    patterns_template:
      - '{SEARCH}(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:的)?(?:1\+N)?保费缺口(?:在|为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:到|至|~|～|-)(\d+(?:\.\d+)?)万(?:元)?(?:之间)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:到|至|~|～|-)(\d+(?:\.\d+)?)万(?:元)?(?:之间)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjnextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 38
    merge_to_llm: true
    extra_conditions:
      - field: "pajjMemberGradeInfo.pajjtotalpremgap"
        operator: "RANGE"
        value_type: "range"
        value: {min_group: 2, max_group: 3, transform: "number"}

  - name: "高端康养-指定下一等级保费缺口精确值"
    enum_ref: "gdkyMemberGradeInfo.gdkynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:高端康养|康养)?{enum}(?:等级|会员)?(?:的)?(?:新老保单)?保费缺口(?:为|是|等于)?(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 35
    merge_to_llm: true
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkytotalpremgap"
        operator: "RANGE"
        value_type: "capture"
        value: {group: 2, transform: "exact_range"}

  - name: "高端康养-指定下一等级保费缺口大于"
    enum_ref: "gdkyMemberGradeInfo.gdkynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:高端康养|康养)?{enum}(?:等级|会员)?(?:的)?(?:新老保单)?保费缺口(?:为|是)?(?:大于|超过|高于|多于)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:高端康养|康养)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:大于|超过|高于|多于)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 36
    merge_to_llm: true
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkytotalpremgap"
        operator: "GT"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "高端康养-指定下一等级保费缺口大于等于"
    enum_ref: "gdkyMemberGradeInfo.gdkynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:高端康养|康养)?{enum}(?:等级|会员)?(?:的)?(?:新老保单)?保费缺口(?:为|是)?(?:大于等于|不少于|不低于|至少|起码)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)?{enum}(?:等级|会员)?(?:的)?(?:新老保单)?保费缺口(?:为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:及以上|以上){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:高端康养|康养)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:大于等于|不少于|不低于|至少|起码)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:高端康养|康养)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:及以上|以上)(?:保费)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 37
    merge_to_llm: true
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkytotalpremgap"
        operator: "GTE"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "高端康养-指定下一等级保费缺口小于"
    enum_ref: "gdkyMemberGradeInfo.gdkynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:高端康养|康养)?{enum}(?:等级|会员)?(?:的)?(?:新老保单)?保费缺口(?:为|是)?(?:小于|低于|少于|不足|不到)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:高端康养|康养)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:小于|低于|少于|不足|不到)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 36
    merge_to_llm: true
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkytotalpremgap"
        operator: "LT"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "高端康养-指定下一等级保费缺口小于等于"
    enum_ref: "gdkyMemberGradeInfo.gdkynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:距离|离)?(?:高端康养|康养)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)?{enum}(?:等级|会员)?(?:的)?(?:新老保单)?保费缺口(?:为|是)?(?:小于等于|不超过|不高于|至多|最多)(\d+(?:\.\d+)?)万(?:元)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)?{enum}(?:等级|会员)?(?:的)?(?:新老保单)?保费缺口(?:为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:以内|及以下|以下){CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:高端康养|康养)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(?:小于等于|不超过|不高于|至多|最多)(\d+(?:\.\d+)?)万(?:元)?(?:保费)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:高端康养|康养)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:以内|及以下|以下)(?:保费)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 37
    merge_to_llm: true
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkytotalpremgap"
        operator: "LTE"
        value_type: "capture"
        value: {group: 2, transform: "number"}

  - name: "高端康养-指定下一等级保费缺口区间"
    enum_ref: "gdkyMemberGradeInfo.gdkynextmembergrade"
    patterns_template:
      - '{SEARCH}(?:高端康养|康养)?{enum}(?:等级|会员)?(?:的)?(?:新老保单)?保费缺口(?:在|为|是)?(\d+(?:\.\d+)?)万(?:元)?(?:到|至|~|～|-)(\d+(?:\.\d+)?)万(?:元)?(?:之间)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:距离|离)?(?:高端康养|康养)?{enum}(?:等级|会员)?(?:还|仍)?(?:差|缺)(\d+(?:\.\d+)?)万(?:元)?(?:到|至|~|～|-)(\d+(?:\.\d+)?)万(?:元)?(?:之间)?(?:保费)?{CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkynextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 38
    merge_to_llm: true
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkytotalpremgap"
        operator: "RANGE"
        value_type: "range"
        value: {min_group: 2, max_group: 3, transform: "number"}

  - name: "御享国医-近期达标含状态"
    patterns:
      - '{SEARCH}(?:近期|最近一个月|近一个月)(?:内)?(?:达标|获得|拿到)(?:了|的)?(?:御享国医|国医)(?:会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:御享国医|国医)(?:会员)?(?:在)?(?:近期|最近一个月|近一个月)(?:内)?(?:达标|获得|拿到){CUSTOMER_SUFFIX}'
    field: "yxgyMemberGradeInfo.yxgyqualifiedtime"
    operator: "RANGE"
    value_type: "date_range_dynamic"
    value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd"}
    priority: 30
    merge_to_llm: true
    extra_conditions:
      - {field: "yxgyMemberGradeInfo.yxgymemberstatus", operator: "MATCH", value: "达标"}

  - name: "私董保健医-指定等级近期达标含状态"
    enum_ref: "sdbjyMemberGradeInfo.sdbjymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:近期|最近一个月|近一个月)(?:内)?(?:达标|获得|拿到)(?:了|的)?(?:私董保健医|私董保健康|私董)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:私董保健医|私董保健康|私董)?{enum}(?:在)?(?:近期|最近一个月|近一个月)(?:内)?(?:达标|获得|拿到){CUSTOMER_SUFFIX}'
    field: "sdbjyMemberGradeInfo.sdbjymembergradesearch"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 32
    merge_to_llm: true
    extra_conditions:
      - field: "sdbjyMemberGradeInfo.sdbjyqualifiedtime"
        operator: "RANGE"
        value_type: "date_range_dynamic"
        value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd"}
      - {field: "sdbjyMemberGradeInfo.sdbjymemberstatus", operator: "MATCH", value: "达标"}

  - name: "平安居家-指定下一等级近期达标含状态"
    enum_ref: "pajjMemberGradeInfo.pajjnextmembergrade"
    patterns_template:
      - '{SEARCH}(?:近期|最近一个月|近一个月)(?:内)?(?:达标|获得|拿到)(?:了|的)?(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:平安居家|居家养老|居家)?{enum}(?:等级|会员)?(?:在)?(?:近期|最近一个月|近一个月)(?:内)?(?:达标|获得|拿到){CUSTOMER_SUFFIX}'
    field: "pajjMemberGradeInfo.pajjnextmembergrade"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 32
    merge_to_llm: true
    extra_conditions:
      - field: "pajjMemberGradeInfo.pajjqualifiedtime"
        operator: "RANGE"
        value_type: "date_range_dynamic"
        value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd"}
      - {field: "pajjMemberGradeInfo.pajjmemberstatus", operator: "MATCH", value: "达标"}

  - name: "高端康养-指定等级近期达标含状态"
    enum_ref: "gdkyMemberGradeInfo.gdkymembergradesearch"
    patterns_template:
      - '{SEARCH}(?:近期|最近一个月|近一个月)(?:内)?(?:达标|获得|拿到)(?:了|的)?(?:高端康养|康养)?{enum}{CUSTOMER_SUFFIX}'
      - '{SEARCH}(?:高端康养|康养)?{enum}(?:在)?(?:近期|最近一个月|近一个月)(?:内)?(?:达标|获得|拿到){CUSTOMER_SUFFIX}'
    field: "gdkyMemberGradeInfo.gdkymembergradesearch"
    operator: "MATCH"
    value_type: "capture"
    value: {group: 1}
    priority: 32
    merge_to_llm: true
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkyqualifiedtime"
        operator: "RANGE"
        value_type: "date_range_dynamic"
        value: {date_range: "last_n_days", days: 30, format: "yyyy-MM-dd"}
      - {field: "gdkyMemberGradeInfo.gdkymemberstatus", operator: "MATCH", value: "达标"}

  # ==================== 位置匹配规则 (match_mode) ====================

  # -- 姓氏 (prefix) --
  - name: "客户姓氏"
    field: "searchClientName"
    operator: "MATCH"
    match_mode: "prefix"
    value_type: "capture"
    value_as_string: true
    priority: 90
    patterns:
      - '{SEARCH}姓([\u4e00-\u9fa5]{1,2})(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:客户)?姓氏(?:是|为)?([\u4e00-\u9fa5]{1,2}){CUSTOMER_SUFFIX}'
      - '{SEARCH}([\u4e00-\u9fa5]{1,2})姓(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}客户姓([\u4e00-\u9fa5]{1,2})(?:的)?'
      - '{SEARCH}姓([\u4e00-\u9fa5]{1,2})(?:的人|人员|代理人)'
      - '(?:查|找|帮我查|帮我找)([\u4e00-\u9fa5]{1,2})姓(?:客户|的客户)'

  # -- 姓名包含 (contains) --
  - name: "客户姓名包含"
    field: "searchClientName"
    operator: "MATCH"
    match_mode: "contains"
    value_type: "capture"
    value_as_string: true
    priority: 80
    patterns:
      - '(?:姓名|名字)(?:中|里|里面)?(?:包含|含有|有)([\u4e00-\u9fa5]{1,10})'
      - '(?:姓名|名字)(?:中|里|里面)?带([\u4e00-\u9fa5]{1,10})(?:字|的)'
      - '(?:姓名|名字)(?:中|里|里面)?带(?:个)?([\u4e00-\u9fa5]{1,10})(?:字)(?:的)?'
      - '(?:姓名|名字)(?:中|里|里面)?有个([\u4e00-\u9fa5])(?:字)(?:的)?'
      - '(?:客户(?:的)?)?(?:姓名|名字)(?:中|里|里面)?有([\u4e00-\u9fa5]{1,4})'

  # -- 手机号尾号 (suffix) --
  - name: "客户手机号尾号"
    field: "clientMobile"
    operator: "MATCH"
    match_mode: "suffix"
    value_type: "capture"
    value_as_string: true
    priority: 80
    patterns:
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?尾号(?:是|为)?(\d{1,11})'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?尾号(?:为|是)?(\d{1,11})(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?(\d+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:手机号|手机号码|电话号码|手机)以(\d+)结尾'
      - '(?:手机号|手机号码|电话号码|手机)以(\d+)结尾(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?末尾(?:是|为)?(\d{1,11})'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?最后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?末(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?结尾(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?结尾(?:是|为)?(\d+)(?:的)?{CUSTOMER_SUFFIX}'
      - '{SEARCH}尾号(?:为|是)?(\d{1,11})(?:的)?(?:手机号|手机号码|电话号码|手机)'

  # -- 手机号前缀 (prefix) --
  - name: "客户手机号前缀"
    field: "clientMobile"
    operator: "MATCH"
    match_mode: "prefix"
    value_type: "capture"
    value_as_string: true
    priority: 80
    patterns:
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?前(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?前(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?(\d+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:手机号|手机号码|电话号码|手机)以(\d+)开头'
      - '(?:手机号|手机号码|电话号码|手机)以(\d+)开头(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:手机号|手机号码|电话号码|手机)前缀(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?开头(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?开头(?:是|为)?(\d+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?起始(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?最前(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?(\d+)'
      - '{SEARCH}开头(?:为|是)?(\d+)(?:的)?(?:手机号|手机号码|电话号码|手机)'

  # -- 客户号前缀 --
  - name: "客户号前缀"
    field: "clientNo"
    operator: "MATCH"
    match_mode: "prefix"
    value_type: "capture"
    value_as_string: true
    priority: 80
    patterns:
      - '(?:客户号|客户编号)以([A-Za-z0-9]+)开头'
      - '(?:客户号|客户编号)以([A-Za-z0-9]+)开头(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:客户号|客户编号)前缀(?:是|为)?([A-Za-z0-9]+)'
      - '(?:客户号|客户编号)(?:的)?前(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9]+)'
      - '(?:客户号|客户编号)(?:的)?前(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:客户号|客户编号)(?:的)?开头(?:是|为)?([A-Za-z0-9]+)'
      - '(?:客户号|客户编号)(?:的)?起始(?:是|为)?([A-Za-z0-9]+)'

  # -- 客户号尾号 --
  - name: "客户号尾号"
    field: "clientNo"
    operator: "MATCH"
    match_mode: "suffix"
    value_type: "capture"
    value_as_string: true
    priority: 80
    patterns:
      - '(?:客户号|客户编号)(?:的)?尾号(?:是|为)?([A-Za-z0-9]+)'
      - '(?:客户号|客户编号)(?:的)?尾号(?:是|为)?([A-Za-z0-9]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:客户号|客户编号)(?:的)?后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9]+)'
      - '(?:客户号|客户编号)(?:的)?后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:客户号|客户编号)以([A-Za-z0-9]+)结尾'
      - '(?:客户号|客户编号)以([A-Za-z0-9]+)结尾(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:客户号|客户编号)(?:的)?末尾(?:是|为)?([A-Za-z0-9]+)'
      - '(?:客户号|客户编号)(?:的)?最后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9]+)'
      - '(?:客户号|客户编号)(?:的)?结尾(?:是|为)?([A-Za-z0-9]+)'

  # -- 客户号包含 --
  - name: "客户号包含"
    field: "clientNo"
    operator: "MATCH"
    match_mode: "contains"
    value_type: "capture"
    value_as_string: true
    priority: 70
    patterns:
      - '(?:客户号|客户编号)(?:中|里)?(?:包含|含有)([A-Za-z0-9]+)'
      - '(?:客户号|客户编号)(?:中|里)?(?:包含|含有)([A-Za-z0-9]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:客户号|客户编号)(?:中|里|里面)?有([A-Za-z0-9]+)'
      - '(?:客户号|客户编号)(?:中|里)?带([A-Za-z0-9]+)(?:的)?'

  # -- 保单号前缀 --
  - name: "保单号前缀"
    field: "polNo"
    operator: "MATCH"
    match_mode: "prefix"
    value_type: "capture"
    value_as_string: true
    priority: 80
    patterns:
      - '(?:保单号|保单编号)以([A-Za-z0-9\-]+)开头'
      - '(?:保单号|保单编号)以([A-Za-z0-9\-]+)开头(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:保单号|保单编号)前缀(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:保单号|保单编号)(?:的)?前(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:保单号|保单编号)(?:的)?前(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9\-]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:保单号|保单编号)(?:的)?开头(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:保单号|保单编号)(?:的)?起始(?:是|为)?([A-Za-z0-9\-]+)'

  # -- 保单号尾号 --
  - name: "保单号尾号"
    field: "polNo"
    operator: "MATCH"
    match_mode: "suffix"
    value_type: "capture"
    value_as_string: true
    priority: 80
    patterns:
      - '(?:保单号|保单编号)(?:的)?尾号(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:保单号|保单编号)(?:的)?尾号(?:是|为)?([A-Za-z0-9\-]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:保单号|保单编号)(?:的)?后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:保单号|保单编号)(?:的)?后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9\-]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:保单号|保单编号)以([A-Za-z0-9\-]+)结尾'
      - '(?:保单号|保单编号)以([A-Za-z0-9\-]+)结尾(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:保单号|保单编号)(?:的)?末尾(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:保单号|保单编号)(?:的)?最后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:保单号|保单编号)(?:的)?结尾(?:是|为)?([A-Za-z0-9\-]+)'

  # -- 保单号包含 --
  - name: "保单号包含"
    field: "polNo"
    operator: "MATCH"
    match_mode: "contains"
    value_type: "capture"
    value_as_string: true
    priority: 70
    patterns:
      - '(?:保单号|保单编号)(?:中|里)?(?:包含|含有)([A-Za-z0-9\-]+)'
      - '(?:保单号|保单编号)(?:中|里)?(?:包含|含有)([A-Za-z0-9\-]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:保单号|保单编号)(?:中|里|里面)?有([A-Za-z0-9\-]+)'
      - '(?:保单号|保单编号)(?:中|里)?带([A-Za-z0-9\-]+)(?:的)?'

  # -- 理赔案件号前缀 --
  - name: "理赔案件号前缀"
    field: "polNoInfo.claimdatainfo.claimno"
    operator: "MATCH"
    match_mode: "prefix"
    value_type: "capture"
    value_as_string: true
    priority: 80
    patterns:
      - '(?:理赔案件号|理赔号|案件号)以([A-Za-z0-9\-]+)开头'
      - '(?:理赔案件号|理赔号|案件号)以([A-Za-z0-9\-]+)开头(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:理赔案件号|理赔号|案件号)前缀(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:理赔案件号|理赔号|案件号)(?:的)?前(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:理赔案件号|理赔号|案件号)(?:的)?开头(?:是|为)?([A-Za-z0-9\-]+)'

  # -- 理赔案件号尾号 --
  - name: "理赔案件号尾号"
    field: "polNoInfo.claimdatainfo.claimno"
    operator: "MATCH"
    match_mode: "suffix"
    value_type: "capture"
    value_as_string: true
    priority: 80
    patterns:
      - '(?:理赔案件号|理赔号|案件号)(?:的)?尾号(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:理赔案件号|理赔号|案件号)(?:的)?尾号(?:是|为)?([A-Za-z0-9\-]+)(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:理赔案件号|理赔号|案件号)以([A-Za-z0-9\-]+)结尾'
      - '(?:理赔案件号|理赔号|案件号)以([A-Za-z0-9\-]+)结尾(?:的)?{CUSTOMER_SUFFIX}'
      - '(?:理赔案件号|理赔号|案件号)(?:的)?后(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:理赔案件号|理赔号|案件号)(?:的)?末尾(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:理赔案件号|理赔号|案件号)(?:的)?结尾(?:是|为)?([A-Za-z0-9\-]+)'

  # -- 否定位置规则 --
  - name: "手机号不以某值开头"
    field: "clientMobile"
    operator: "NOT_CONTAINS"
    match_mode: "prefix"
    value_type: "capture"
    value_as_string: true
    priority: 100
    patterns:
      - '(?:手机号|手机号码|电话号码|手机)不(?:是)?以(\d+)开头'
      - '(?:手机号|手机号码|电话号码|手机)前缀不(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?开头不(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?前(?:一|两|二|三|四|五|六|七|八|九|十|\d+)位不(?:是|为)?(\d+)'

  - name: "手机号尾号不为某值"
    field: "clientMobile"
    operator: "NOT_CONTAINS"
    match_mode: "suffix"
    value_type: "capture"
    value_as_string: true
    priority: 100
    patterns:
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?尾号不(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)不(?:是)?以(\d+)结尾'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?末尾不(?:是|为)?(\d+)'
      - '(?:手机号|手机号码|电话号码|手机)(?:的)?结尾不(?:是|为)?(\d+)'

  - name: "客户号不以某值开头"
    field: "clientNo"
    operator: "NOT_CONTAINS"
    match_mode: "prefix"
    value_type: "capture"
    value_as_string: true
    priority: 100
    patterns:
      - '(?:客户号|客户编号)不(?:是)?以([A-Za-z0-9]+)开头'
      - '(?:客户号|客户编号)(?:的)?开头不(?:是|为)?([A-Za-z0-9]+)'

  - name: "客户号尾号不为某值"
    field: "clientNo"
    operator: "NOT_CONTAINS"
    match_mode: "suffix"
    value_type: "capture"
    value_as_string: true
    priority: 100
    patterns:
      - '(?:客户号|客户编号)(?:的)?尾号不(?:是|为)?([A-Za-z0-9]+)'
      - '(?:客户号|客户编号)不(?:是)?以([A-Za-z0-9]+)结尾'

  - name: "客户号不包含某值"
    field: "clientNo"
    operator: "NOT_CONTAINS"
    match_mode: "contains"
    value_type: "capture"
    value_as_string: true
    priority: 100
    patterns:
      - '(?:客户号|客户编号)(?:中|里)?不(?:包含|含有)([A-Za-z0-9]+)'
      - '(?:客户号|客户编号)(?:中|里|里面)?没有([A-Za-z0-9]+)'

  - name: "保单号不以某值开头"
    field: "polNo"
    operator: "NOT_CONTAINS"
    match_mode: "prefix"
    value_type: "capture"
    value_as_string: true
    priority: 100
    patterns:
      - '(?:保单号|保单编号)不(?:是)?以([A-Za-z0-9\-]+)开头'
      - '(?:保单号|保单编号)(?:的)?开头不(?:是|为)?([A-Za-z0-9\-]+)'

  - name: "保单号尾号不为某值"
    field: "polNo"
    operator: "NOT_CONTAINS"
    match_mode: "suffix"
    value_type: "capture"
    value_as_string: true
    priority: 100
    patterns:
      - '(?:保单号|保单编号)(?:的)?尾号不(?:是|为)?([A-Za-z0-9\-]+)'
      - '(?:保单号|保单编号)不(?:是)?以([A-Za-z0-9\-]+)结尾'
      - '(?:保单号|保单编号)(?:的)?末尾不(?:是|为)?([A-Za-z0-9\-]+)'

  - name: "保单号不包含某值"
    field: "polNo"
    operator: "NOT_CONTAINS"
    match_mode: "contains"
    value_type: "capture"
    value_as_string: true
    priority: 100
    patterns:
      - '(?:保单号|保单编号)(?:中|里)?不(?:包含|含有)([A-Za-z0-9\-]+)'
      - '(?:保单号|保单编号)(?:中|里|里面)?没有([A-Za-z0-9\-]+)'

# ==================== 地址查询规则 ====================

#  - name: "联系地址精确匹配"
#    patterns:
#      - '{ADDRESS_SEARCH}{ADDRESS_CONTACT_SCOPE}(?:是|为|在|位于)?{ADDRESS_TEXT_GUARD}(?!包含|含|有|带|空白|为空|空白的|不为空|没有|没填|未填)({ADDRESS_VALUE}){ADDRESS_CUSTOMER_SUFFIX}$'
#    field: "CONTACT_ADDRESS_FIELD"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 90
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "未指定地址类型的居住地匹配"
#    patterns:
#      - '{ADDRESS_SEARCH}{ADDRESS_RESIDENCE_CUE}{ADDRESS_TEXT_GUARD}({ADDRESS_VALUE}){ADDRESS_DEICTIC_SUFFIX}{ADDRESS_CUSTOMER_SUFFIX}{ADDRESS_POST_SEARCH}$'
#    field: "ANY_ADDRESS_FIELD"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 90
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "裸地址高置信匹配"
#    patterns:
#      - '{ADDRESS_ROLE_EXCLUSION}({ADDRESS_ENTITY})$'
#      - '{ADDRESS_SEARCH}{ADDRESS_ROLE_EXCLUSION}(?:地址(?:是|为|在|位于)?)?({ADDRESS_ENTITY}){ADDRESS_DEICTIC_SUFFIX}{ADDRESS_CUSTOMER_SUFFIX}{ADDRESS_POST_SEARCH}$'
#      - '(京津冀|江浙沪|长三角|珠三角|粤港澳|成渝|东北|华北|华东|华南|华中|西北|西南|中关村|望京|国贸|亦庄|燕郊|通州|回龙观|天通苑|陆家嘴|张江)$'
#    field: "ANY_ADDRESS_FIELD"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 88
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "地址相对位置匹配"
#    patterns:
#      - '{ADDRESS_SEARCH}{ADDRESS_ROLE_EXCLUSION}([a-zA-Z0-9\u4e00-\u9fa5·•\-\#\(\)（）]{1,60}?{ADDRESS_RELATIVE_LOCATION}){ADDRESS_DEICTIC_SUFFIX}{ADDRESS_CUSTOMER_SUFFIX}{ADDRESS_POST_SEARCH}$'
#    field: "ANY_ADDRESS_FIELD"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 89
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "联系地址模糊匹配"
#    patterns:
#      - '{ADDRESS_SEARCH}{ADDRESS_CONTACT_SCOPE}{ADDRESS_CONTAINS_CUE}({ADDRESS_VALUE}){ADDRESS_CUSTOMER_SUFFIX}$'
#    field: "CONTACT_ADDRESS_FIELD"
#    operator: "CONTAINS"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 89
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "家庭地址精确匹配"
#    patterns:
#      - '{ADDRESS_SEARCH}{ADDRESS_FAMILY_SCOPE}(?:是|为|在|位于)?{ADDRESS_TEXT_GUARD}(?!包含|含|有|带|空白|为空|空白的|不为空|没有|没填|未填)({ADDRESS_VALUE}){ADDRESS_CUSTOMER_SUFFIX}$'
#    field: "FAMILY_ADDRESS_FIELD"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 90
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "家庭地址模糊匹配"
#    patterns:
#      - '{ADDRESS_SEARCH}{ADDRESS_FAMILY_SCOPE}{ADDRESS_CONTAINS_CUE}({ADDRESS_VALUE}){ADDRESS_CUSTOMER_SUFFIX}$'
#    field: "FAMILY_ADDRESS_FIELD"
#    operator: "CONTAINS"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 89
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "未指定地址类型的机构名称匹配"
#    patterns:
#      - '{ADDRESS_SEARCH}(?:公司|单位|机构|企业)(?:名称|名字|名)?(?:是|为|叫)?({ADDRESS_VALUE}){ADDRESS_CUSTOMER_SUFFIX}{ADDRESS_POST_SEARCH}$'
#    field: "ANY_ADDRESS_FIELD"
#    operator: "MATCH"
#    value_type: "capture"
#    value:
#      group: 1
#    priority: 89
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "地点距离范围内"
#    patterns:
#      - '{ADDRESS_SEARCH}(?:(?:{ADDRESS_CONTACT_SCOPE}|{ADDRESS_FAMILY_SCOPE})(?:是|为|在|位于)?)?(?:距离|离)?({ADDRESS_VALUE})(?:的)?{ADDRESS_PLACE_RELATION}(\d+(?:\.\d+)?)\s*(?:公里|千米|km){ADDRESS_INSIDE_BOUNDARY}?(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#      - '{ADDRESS_SEARCH}(?:(?:{ADDRESS_CONTACT_SCOPE}|{ADDRESS_FAMILY_SCOPE})(?:是|为|在|位于)?)?(?:距离|离)?({ADDRESS_VALUE})(?:的)?{ADDRESS_PLACE_RELATION}(\d+)\s*米{ADDRESS_INSIDE_BOUNDARY}?(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#      - '{ADDRESS_SEARCH}(?:(?:{ADDRESS_CONTACT_SCOPE}|{ADDRESS_FAMILY_SCOPE})(?:是|为|在|位于)?)?(?:距离|离)?({ADDRESS_VALUE})(?:的)?{ADDRESS_PLACE_RELATION}?(\d+(?:\.\d+)?)\s*(?:公里|千米|km){ADDRESS_INSIDE_BOUNDARY}(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#      - '{ADDRESS_SEARCH}(?:(?:{ADDRESS_CONTACT_SCOPE}|{ADDRESS_FAMILY_SCOPE})(?:是|为|在|位于)?)?(?:距离|离)?({ADDRESS_VALUE})(?:的)?{ADDRESS_PLACE_RELATION}?(\d+)\s*米{ADDRESS_INSIDE_BOUNDARY}(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#    field: "ANY_ADDRESS_FIELD"
#    operator: "GEO_RADIUS"
#    value_type: "geo_radius"
#    value:
#      place_group: 1
#      distance_group: 2
#      unit_default: "km"
#    priority: 90
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "地点距离范围外"
#    patterns:
#      - '{ADDRESS_SEARCH}(?:(?:{ADDRESS_CONTACT_SCOPE}|{ADDRESS_FAMILY_SCOPE})(?:是|为|在|位于)?)?(?:距离|离)?({ADDRESS_VALUE})(?:的)?{ADDRESS_PLACE_RELATION}?(\d+(?:\.\d+)?)\s*(?:公里|千米|km){ADDRESS_OUTSIDE_BOUNDARY}(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#      - '{ADDRESS_SEARCH}(?:(?:{ADDRESS_CONTACT_SCOPE}|{ADDRESS_FAMILY_SCOPE})(?:是|为|在|位于)?)?(?:距离|离)?({ADDRESS_VALUE})(?:的)?{ADDRESS_PLACE_RELATION}?(?:超过|大于|至少)(\d+(?:\.\d+)?)\s*(?:公里|千米|km)(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#      - '{ADDRESS_SEARCH}(?:(?:{ADDRESS_CONTACT_SCOPE}|{ADDRESS_FAMILY_SCOPE})(?:是|为|在|位于)?)?(?:距离|离)?({ADDRESS_VALUE})(?:的)?{ADDRESS_PLACE_RELATION}?(\d+(?:\.\d+)?)\s*米{ADDRESS_OUTSIDE_BOUNDARY}(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#      - '{ADDRESS_SEARCH}(?:(?:{ADDRESS_CONTACT_SCOPE}|{ADDRESS_FAMILY_SCOPE})(?:是|为|在|位于)?)?(?:距离|离)?({ADDRESS_VALUE})(?:的)?{ADDRESS_PLACE_RELATION}?(?:超过|大于|至少)(\d+(?:\.\d+)?)\s*米(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#    field: "ANY_ADDRESS_FIELD"
#    operator: "NOT_GEO_RADIUS"
#    value_type: "geo_radius"
#    value:
#      place_group: 1
#      distance_group: 2
#      unit_default: "km"
#    priority: 90
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "地点附近默认范围"
#    patterns:
#      - '{ADDRESS_SEARCH}(?:(?:{ADDRESS_CONTACT_SCOPE}|{ADDRESS_FAMILY_SCOPE})(?:是|为|在|位于)?|{ADDRESS_RESIDENCE_CUE})?({ADDRESS_VALUE})(?:的)?{ADDRESS_PLACE_RELATION}(?:的)?{ADDRESS_CUSTOMER_SUFFIX}{ADDRESS_POST_SEARCH}'
#    field: "ANY_ADDRESS_FIELD"
#    operator: "GEO_RADIUS"
#    value_type: "geo_radius"
#    value:
#      place_group: 1
#      default_distance: 1
#      unit_default: "km"
#    priority: 90
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "当前位置距离范围内"
#    patterns:
#      - '{ADDRESS_SEARCH}{ADDRESS_CURRENT_LOCATION}(?:的)?(?:方圆|周边)?(\d+(?:\.\d+)?)\s*(?:公里|千米|km){ADDRESS_INSIDE_BOUNDARY}(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#      - '{ADDRESS_SEARCH}{ADDRESS_CURRENT_LOCATION}(?:的)?(?:方圆|周边)?(\d+)\s*米{ADDRESS_INSIDE_BOUNDARY}(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#    field: "ANY_ADDRESS_FIELD"
#    operator: "GEO_RADIUS"
#    value_type: "geo_radius"
#    value:
#      is_current_location: true
#      distance_group: 1
#      unit_default: "km"
#    priority: 95
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "当前位置距离范围外"
#    patterns:
#      - '{ADDRESS_SEARCH}{ADDRESS_CURRENT_LOCATION}(?:的)?(?:方圆|周边)?(\d+(?:\.\d+)?)\s*(?:公里|千米|km){ADDRESS_OUTSIDE_BOUNDARY}(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#      - '{ADDRESS_SEARCH}{ADDRESS_CURRENT_LOCATION}(?:的)?(?:方圆|周边)?(\d+)\s*米{ADDRESS_OUTSIDE_BOUNDARY}(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#    field: "ANY_ADDRESS_FIELD"
#    operator: "NOT_GEO_RADIUS"
#    value_type: "geo_radius"
#    value:
#      is_current_location: true
#      distance_group: 1
#      unit_default: "km"
#    priority: 95
#    confidence_level: "STRONG"
#    full_match_required: true
#
#  - name: "当前位置附近默认范围"
#    patterns:
#      - '{ADDRESS_SEARCH}{ADDRESS_CURRENT_LOCATION}(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#      - '{ADDRESS_SEARCH}我附件(?:的)?{ADDRESS_CUSTOMER_SUFFIX}'
#    field: "ANY_ADDRESS_FIELD"
#    operator: "GEO_RADIUS"
#    value_type: "geo_radius"
#    value:
#      is_current_location: true
#      default_distance: 1
#      unit_default: "km"
#    priority: 95
#    confidence_level: "STRONG"
#    full_match_required: true

composite_rules:

  # ==================== 既有条件 + 保费缺口 ====================

  - name: "年龄及以上+御享国医保费缺口大于"
    patterns:
      - '{SEARCH}【年龄-及以上】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与)[，,、 ]*)【御享国医-总保费缺口大于】'
    priority: 45

  - name: "性别+私董下一等级保费缺口大于等于"
    patterns:
      - '{SEARCH}【性别-简单】(?:性)?(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与)[，,、 ]*)【私董保健康-指定下一等级保费缺口大于等于】'
    priority: 45
    extra_conditions:
      - field: "sdbjyMemberGradeInfo.sdbjytotalpremgap"
        operator: "GTE"
        value_type: "capture"
        value: {group: 3, transform: "number"}

  - name: "寿险VIP+平安居家下一等级保费缺口小于"
    patterns:
      - '{SEARCH}【寿险VIP】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与)[，,、 ]*)【平安居家-指定下一等级保费缺口小于】'
    priority: 45
    extra_conditions:
      - field: "pajjMemberGradeInfo.pajjtotalpremgap"
        operator: "LT"
        value_type: "capture"
        value: {group: 4, transform: "number"}

  - name: "客户温度+高端康养下一等级保费缺口小于等于"
    patterns:
      - '{SEARCH}【客户温度】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与)[，,、 ]*)【高端康养-指定下一等级保费缺口小于等于】'
    priority: 45
    extra_conditions:
      - field: "gdkyMemberGradeInfo.gdkytotalpremgap"
        operator: "LTE"
        value_type: "capture"
        value: {group: 4, transform: "number"}

  - name: "添平安权益+保单数量"
    patterns:
      - '【添平安-任一会员权益存在】(?:[，,、 ]*(?:是|并且|且|同时|以及|和|及|与|但|但是|不过)[，,、 ]*)【保单数量-精确】(?:的客户|客户)?'
      - '【保单数量-精确】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与|但|但是|不过)[，,、 ]*)【添平安-任一会员权益存在】(?:的客户|客户)?'
    priority: 50
    query_logic: "OR"
    extra_conditions:
      - field: "ayhMemberGradeInfo.ayhmemberproductname"
        operator: "EXISTS"
        value: ""
      - field: "zxjyMemberGradeInfo.zxjymemberproductname"
        operator: "EXISTS"
        value: ""
      - field: "pajjMemberGradeInfo.pajjmemberproductname"
        operator: "EXISTS"
        value: ""
      - field: "yxgyMemberGradeInfo.yxgymemberproductname"
        operator: "EXISTS"
        value: ""
      - field: "sdbjyMemberGradeInfo.sdbjymemberproductname"
        operator: "EXISTS"
        value: ""
      - field: "gdkyMemberGradeInfo.gdkymemberproductname"
        operator: "EXISTS"
        value: ""

  - name: "孩子按客户本人年龄"
    patterns:
      - '【年龄-孩子按客户本人年龄】'
    priority: 45

  - name: "客户为母亲投保并查询母亲"
    patterns:
      - '【母亲投保-客户姓名片段】【母亲投保-母亲姓名片段】'
    priority: 45
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "父母"

#  - name: "姓名+出生年份"
#    patterns:
#      - '{SEARCH}【姓名-模糊匹配】【出生年份-片段】(?:的客户|客户)?'
#    priority: 40

  - name: "姓名+平安居家增保测算潜客"
    patterns:
      - '{SEARCH}【姓名-模糊匹配】(?:本月|这个月|当月)(?:还要|需要|需|要)?(?:增加|新增|加)(?:多少|几多)(?:保费|保障)(?:才|就)?(?:可以|可|能)?(?:享受|获得|达到)(?:平安居家|居家养老|居家)'
    priority: 40
    extra_conditions:
      - field: "pajjMemberGradeInfo.pajjmemberstatus"
        operator: "MATCH"
        value: "潜客"

  - name: "投保险种类别+保单号"
    patterns:
      - '{SEARCH}【投保险种类型】【保单号-匹配】(?:的客户|客户)?'
    priority: 35

  - name: "未持有产品类别+投保险种类别"
    patterns:
      - '{SEARCH}【险种-未配置】(?:的)?【投保险种类型】(?:的客户|客户)?'
      - '{SEARCH}【投保险种类型】(?:的客户)?(?:且|但|同时|又)?【险种-未配置】(?:的客户|客户)?'
    priority: 35

  - name: "持有险种类别+权益存在"
    patterns:
      - '{SEARCH}【险种-持有】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与|又)[，,、 ]*)【臻享家医-权益存在】(?:的客户|客户|名单|有哪些人|有哪些)?'
      - '{SEARCH}【臻享家医-权益存在】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与|又)[，,、 ]*)【险种-持有】(?:的客户|客户|名单|有哪些人|有哪些)?'
      - '{SEARCH}【险种-重大疾病口语】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与|又)[，,、 ]*)【臻享家医-权益存在】(?:的客户|客户|名单|有哪些人|有哪些)?'
      - '{SEARCH}【臻享家医-权益存在】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与|又)[，,、 ]*)【险种-重大疾病口语】(?:的客户|客户|名单|有哪些人|有哪些)?'
    priority: 35

  - name: "持有险种类别+投保险种简称"
    patterns:
      - '{SEARCH}【险种-持有】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与|又)[，,、 ]*)【投保险种简称】(?:的客户|客户|名单|有哪些人|有哪些)?'
      - '{SEARCH}【投保险种简称】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与|又)[，,、 ]*)【险种-持有】(?:的客户|客户|名单|有哪些人|有哪些)?'
      - '{SEARCH}【险种-重大疾病口语】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与|又)[，,、 ]*)【投保险种简称】(?:的客户|客户|名单|有哪些人|有哪些)?'
      - '{SEARCH}【投保险种简称】(?:[，,、 ]*(?:并且|且|同时|以及|和|及|与|又)[，,、 ]*)【险种-重大疾病口语】(?:的客户|客户|名单|有哪些人|有哪些)?'
    priority: 35

  - name: "去年投保+投保险种简称"
    ignore_case: true
    patterns:
      - '(?:我想)?{SEARCH}【投保日期-去年片段】【投保险种简称】(?:名单)?'
    priority: 30

  - name: "去年投保+投保险种名称"
    ignore_case: true
    patterns:
      - '(?:我想)?{SEARCH}【投保日期-去年片段】【投保险种名称】(?:名单)?'
    priority: 30

  - name: "投保险种名称+投保险种类型"
    patterns:
      - '【投保险种名称】(?:[的、，, 和及与且]{0,2})【投保险种类型】(?:的客户|客户|名单|的人|人)?'
      - '【投保险种类型】(?:[的、，, 和及与且]{0,2})【投保险种名称】(?:的客户|客户|名单|的人|人)?'
    priority: 24

  - name: "投保险种简称+投保险种类型"
    ignore_case: true
    patterns:
      - '【投保险种简称】(?:[的、，, 和及与且]{0,2})【投保险种类型】(?:的客户|客户|名单|的人|人)?'
      - '【投保险种类型】(?:[的、，, 和及与且]{0,2})【投保险种简称】(?:的客户|客户|名单|的人|人)?'
    priority: 24

  - name: "投保险种简称+保单状态"
    # 产品名和保单状态同时出现时，产品名默认按投保险种简称解析
    ignore_case: true
    patterns:
      - '【投保险种简称】(?:[的、，, 和及与且]{0,2})?【保单状态】(?:的客户|客户|名单|的人|人)?'
      - '【保单状态】(?:[的、，, 和及与且]{0,2})?【投保险种简称】(?:的客户|客户|名单|的人|人)?'
      - '【投保险种简称】(?:[的、，, 和及与且]{0,2})?【保单状态-有效汇总】'
      - '【保单状态-有效汇总】(?:[的、，, 和及与且]{0,2})?【投保险种简称】(?:的客户|客户|名单|的人|人)?'
      - '【投保险种简称】(?:[的、，, 和及与且]{0,2})?【保单状态-未有效汇总】'
      - '【保单状态-未有效汇总】(?:[的、，, 和及与且]{0,2})?【投保险种简称】(?:的客户|客户|名单|的人|人)?'
    priority: 24

  - name: "投保险种简称+保单到期时间"
    # 未明确“综拓”的产品名默认按投保险种简称解析，再叠加保单到期时间
    patterns:
      - '【投保险种简称】(?:[的、，, 和及与且]{0,4})?【保单到期时间-近期】(?:的客户|客户|名单|的人|人)?'
      - '【保单到期时间-近期】(?:[的、，, 和及与且]{0,4})?【投保险种简称】(?:的客户|客户|名单|的人|人)?'
    priority: 24

  - name: "投保险种名称+保单状态"
    ignore_case: true
    patterns:
      - '【投保险种名称】(?:[的、，, 和及与且]{0,2})?【保单状态】(?:的客户|客户|名单|的人|人)?'
      - '【保单状态】(?:[的、，, 和及与且]{0,2})?【投保险种名称】(?:的客户|客户|名单|的人|人)?'
      - '【投保险种名称】(?:[的、，, 和及与且]{0,2})?【保单状态-有效汇总】'
      - '【投保险种名称】(?:[的、，, 和及与且]{0,2})?【保单状态-未有效汇总】'
      - '【保单状态-未有效汇总】(?:[的、，, 和及与且]{0,2})?【投保险种名称】(?:的客户|客户|名单|的人|人)?'
    priority: 24

  - name: "险种到期"
    patterns:
      - '{SEARCH}【险种-持有】(?:[的、，, 和及与且]{0,2})?【保单-已到期】(?:的客户|客户)?'
    priority: 15

  - name: "险种类型到期"
    patterns:
      - '{SEARCH}【投保险种类型】(?:[的、，, 和及与且]{0,2})?【保单-已到期】(?:的客户|客户)?'
    priority: 15

  - name: "产品类型到期"
    patterns:
      - '{SEARCH}【持有产品类型-持有】(?:[的、，, 和及与且]{0,2})?【保单-已到期】(?:的客户|客户)?'
    priority: 15

  # ==============================
  # 4 条件
  # ==============================

  - name: "年龄GTE+婚姻+有子女+未配置险种"
    # 35岁已婚有小朋友未配置医疗险的客户
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的、，, ]{0,3})?【家庭成员关系-有】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的、，, ]{0,3})?【家庭成员关系-有】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 35

  # ==============================
  # 3 条件
  # ==============================

  - name: "年龄GTE+婚姻+性别"
    # 45岁以上已婚女性客户
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的、，, ]{0,3})?【性别-枚举】(?:性)?(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【性别-枚举】(?:性)?(?:[的、，, ]{0,3})?【婚姻状况】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的、，, ]{0,3})?【性别-枚举】(?:性)?(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【性别-枚举】(?:性)?(?:[的、，, ]{0,3})?【婚姻状况】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 30

  - name: "年龄GTE+婚姻+未配置险种"
    # 45岁以上已婚未配置医疗险的客户
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 30

  - name: "年龄GTE+有子女+未配置险种"
    # 35岁有孩子未配置医疗险的客户
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【家庭成员关系-有】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【家庭成员关系-有】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 30

  - name: "年龄精确+有子女+未配置险种"
    # 35岁有小朋友还没配置医疗险的客户（精确年龄）
    patterns:
      - '{SEARCH}【年龄-精确】(?:[的、，, 还就也]{0,4})?【家庭成员关系-有】(?:[的、，, 还就也]{0,4})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 30

  # ==================== 客户本人是父母 ====================
  # "X岁的父母" → 客户本人是父母（有子女），不是客户有父母
  # 必须优先于 "年龄精确+有子女" / "年龄GTE+有子女" 匹配

  - name: "年龄以上+客户是父母"
    # 30岁以上的父母 → 客户≥30岁，有子女
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?父母(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?父母(?:的客户|客户)?'
    priority: 24
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "年龄精确+客户是父母"
    # 30岁父母 → 客户30岁，有子女
    patterns:
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?父母(?:的客户|客户)?'
    priority: 24
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "年龄范围+客户是父母"
    # 30-40岁的父母 → 客户30-40岁，有子女
    patterns:
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?父母(?:的客户|客户)?'
    priority: 24
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  # ---------- 年龄 + 宝妈 ----------
  - name: "年龄以上+宝妈"
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【宝妈】(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【宝妈】(?:的客户|客户)?'
    priority: 24
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientage"
        operator: "RANGE"
        value:
          min: 0
          max: 6

  - name: "年龄精确+宝妈"
    patterns:
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【宝妈】(?:的客户|客户)?'
    priority: 24
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientage"
        operator: "RANGE"
        value:
          min: 0
          max: 6

  - name: "年龄范围+宝妈"
    patterns:
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【宝妈】(?:的客户|客户)?'
    priority: 24
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientage"
        operator: "RANGE"
        value:
          min: 0
          max: 6

  - name: "年龄中文以上+宝妈"
    patterns:
      - '{SEARCH}【年龄-中文以上】(?:[的、，, ]{0,3})?【宝妈】(?:的客户|客户)?'
    priority: 24
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientage"
        operator: "RANGE"
        value:
          min: 0
          max: 6

  - name: "年龄中文精确+宝妈"
    patterns:
      - '{SEARCH}【年龄-中文精确】(?:[的、，, ]{0,3})?【宝妈】(?:的客户|客户)?'
    priority: 24
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientage"
        operator: "RANGE"
        value:
          min: 0
          max: 6


  - name: "年龄精确+有子女"
    # 35岁有小朋友的客户（无险种条件）
    patterns:
      - '{SEARCH}【年龄-精确】(?:[的、，, 还就也]{0,4})?【家庭成员关系-有】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 22

  - name: "年龄GTE+有子女"
    # 35岁以上有孩子的客户（无险种条件）
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【家庭成员关系-有】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【家庭成员关系-有】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 22

  - name: "婚姻+有子女+未配置险种"
    # 已婚有小朋友未配置医疗险的客户
    patterns:
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【家庭成员关系-有】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 30

  - name: "婚姻+有车+未配置险种"
    # 已婚有车没买百万医疗的客户
    patterns:
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【资产状况-有房有车】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【资产状况-无房无车】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【资产状况-有车无房】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【资产状况-无车有房】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【资产状况-有车】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【资产状况-有房】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【资产状况-有车】(?:[的、，, ]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 30

  # ==============================
  # 2 条件
  # ==============================

  - name: "年龄+未来一个月积分到期"
    patterns:
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?(?:并且|且|同时|以及|和|及|与)?(?:[的、，, ]{0,3})?【会员积分到期-未来一个月】'
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?(?:并且|且|同时|以及|和|及|与)?(?:[的、，, ]{0,3})?【会员积分到期-未来一个月】'
      - '{SEARCH}【会员积分到期-未来一个月】(?:[的、，, ]{0,3})?(?:并且|且|同时|以及|和|及|与)?(?:[的、，, ]{0,3})?【年龄-及以上】(?:的客户|客户)?'
      - '{SEARCH}【会员积分到期-未来一个月】(?:[的、，, ]{0,3})?(?:并且|且|同时|以及|和|及|与)?(?:[的、，, ]{0,3})?【年龄-以上】(?:的客户|客户)?'
    priority: 30

  # ---------- 年龄 + 客群标签 ----------
  # "10岁以下的社会中坚" → 客户年龄≤10 + 客群标签=社会中坚

  - name: "年龄以下+客群标签"
    patterns:
      - '{SEARCH}【年龄-以下】(?:[的、，, ]{0,3})?【客群标签】(?:的客户|客户)?'
      - '{SEARCH}【客群标签】(?:[的、，, ]{0,3})?【年龄-以下】(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以下】(?:[的、，, ]{0,3})?【客群标签】(?:的客户|客户)?'
      - '{SEARCH}【客群标签】(?:[的、，, ]{0,3})?【年龄-及以下】(?:的客户|客户)?'
    priority: 18

  - name: "年龄以上+客群标签"
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【客群标签】(?:的客户|客户)?'
      - '{SEARCH}【客群标签】(?:[的、，, ]{0,3})?【年龄-以上】(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【客群标签】(?:的客户|客户)?'
      - '{SEARCH}【客群标签】(?:[的、，, ]{0,3})?【年龄-及以上】(?:的客户|客户)?'
    priority: 18

  - name: "年龄范围+客群标签"
    patterns:
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【客群标签】(?:的客户|客户)?'
      - '{SEARCH}【客群标签】(?:[的、，, ]{0,3})?【年龄-范围】(?:的客户|客户)?'
    priority: 18

  - name: "成员关系+成员年龄-以上-显式"
    patterns:
      - '{SEARCH}【家庭成员关系-显式包含】(?:[的、，, ]{0,3})?(?:并且|且|，|,|、)?(?:[的、，, ]{0,3})?【成员年龄-以上-通用】'
      - '{SEARCH}【成员年龄-以上-通用】(?:[的、，, ]{0,3})?(?:并且|且|，|,|、)?(?:[的、，, ]{0,3})?【家庭成员关系-显式包含】'
    priority: 15

  - name: "成员关系+成员年龄+婚姻状况-显式"
    patterns:
      - '{SEARCH}【家庭成员关系-显式包含】(?:[的、，, ]{0,3})?(?:并且|且|，|,|、)?(?:[的、，, ]{0,3})?【成员年龄-以上-通用】(?:[的、，, ]{0,3})?(?:并且|且|，|,|、)?(?:[的、，, ]{0,3})?【婚姻状况】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【家庭成员关系-显式包含】(?:[的、，, ]{0,3})?(?:并且|且|，|,|、)?(?:[的、，, ]{0,3})?【婚姻状况】(?:[的、，, ]{0,3})?(?:并且|且|，|,|、)?(?:[的、，, ]{0,3})?【成员年龄-以上-通用】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?(?:并且|且|，|,|、)?(?:[的、，, ]{0,3})?【家庭成员关系-显式包含】(?:[的、，, ]{0,3})?(?:并且|且|，|,|、)?(?:[的、，, ]{0,3})?【成员年龄-以上-通用】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 16

  - name: "年龄GTE+婚姻"
    # 45岁以上已婚的客户
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的青年家庭]{0,4})?(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【年龄-以上】(?:[的青年]{0,3})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的青年家庭]{0,4})?(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【年龄-及以上】(?:[的青年]{0,3})?(?:的客户|客户)?'
    priority: 20

  - name: "年龄范围+婚姻"
    # 20-30岁已婚（刚结婚 preprocess→已婚）的客户
    patterns:
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的青年]{0,3})?(?:的客户|客户)?'
    priority: 20

  - name: "年龄多岁+婚姻"
    # 二十多岁已婚的客户
    patterns:
      - '{SEARCH}【年龄-多岁】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的青年]{0,3})?(?:的客户|客户)?'
    priority: 20

  - name: "年龄中文多岁+婚姻"
    # 二十多岁已婚的客户（中文数字）
    patterns:
      - '{SEARCH}【年龄-中文年代几岁】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的青年家庭]{0,5})?(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【年龄-中文年代几岁】(?:[的青年家庭]{0,5})?(?:的客户|客户)?'
    priority: 20

  - name: "年龄GTE+性别"
    # 45岁以上女性客户
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【性别-枚举】(?:性)?(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【性别-枚举】(?:性)?(?:的客户|客户)?'
    priority: 20

  - name: "年龄GTE+未配置险种"
    # 45岁以上未配置医疗险的客户
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【险种-未配置】(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【险种-未配置】(?:的客户|客户)?'
    priority: 20

  - name: "年龄GTE+无保险"
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,4})?【持有产品类型-为空】(?:的客户|客户|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}【持有产品类型-为空】(?:[的、，, ]{0,4})?【年龄-以上】(?:的客户|客户|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,4})?【持有产品类型-为空】(?:的客户|客户|名单|有哪些人|有哪些|的)?'
      - '{SEARCH}【持有产品类型-为空】(?:[的、，, ]{0,4})?【年龄-及以上】(?:的客户|客户|名单|有哪些人|有哪些|的)?'
    priority: 20

  - name: "婚姻+未配置险种"
    # 已婚未配置医疗险的客户
    patterns:
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【险种-未配置】(?:的客户|客户)?'
    priority: 20

  - name: "有子女+未配置险种"
    # 家里有孩子没买医疗险的客户
    patterns:
      - '{SEARCH}(?:家里)?【家庭成员关系-有】(?:[的、，, 但]{0,3})?【险种-未配置】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 20

  - name: "年龄LTE+未配置险种"
    # 55岁以下没有配置医疗险的客户
    patterns:
      - '{SEARCH}【年龄-以下】(?:[的、，, ]{0,3})?【险种-未配置】(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以下】(?:[的、，, ]{0,3})?【险种-未配置】(?:的客户|客户)?'
    priority: 20

  - name: "年龄LTE+婚姻"
    # 55岁以下已婚的客户
    patterns:
      - '{SEARCH}【年龄-以下】(?:[的、，, ]{0,3})?【婚姻状况】(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【年龄-以下】(?:的客户|客户)?'
      - '{SEARCH}【年龄-及以下】(?:[的、，, ]{0,3})?【婚姻状况】(?:的客户|客户)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【年龄-及以下】(?:的客户|客户)?'
    priority: 20

  - name: "年龄范围+未配置险种"
    # 30-40岁没有配置医疗险的客户
    patterns:
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【险种-未配置】(?:的客户|客户)?'
    priority: 20

  - name: "年龄多岁+未配置险种"
    # 二十多岁没有配置医疗险的客户
    patterns:
      - '{SEARCH}【年龄-多岁】(?:[的、，, ]{0,3})?【险种-未配置】(?:的客户|客户)?'
    priority: 20

  - name: "年龄精确+未配置险种"
    # 35岁没有配置医疗险的客户
    patterns:
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【险种-未配置】(?:的客户|客户)?'
    priority: 20

#  - name: "持有寿险产品+未持有寿险产品"
#    # 买了金瑞人生20，但是没有配置盛世金越的客户
#    patterns:
#      - '{SEARCH}【寿险产品-持有】(?:[的、，, ]{0,4})?(?:但是?|可是)?【寿险产品-未持有】(?:[的]{0,2})?(?:的客户|客户)?'
#      - '{SEARCH}{position}【寿险产品-持有】(?:[的、，, ]{0,4})?(?:但是?没有?|未){position}?【寿险产品-未持有】(?:[的]{0,2})?(?:的客户|客户)?'
#    priority: 22

  - name: "持有产品类型+未持有产品类型"
    # 买了医疗险，但是没有配置养老险
    patterns:
      - '{SEARCH}【持有产品类型-持有】(?:[的、，, ]{0,4})?(?:但是?|可是)?【持有产品类型-未持有】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【持有产品类型-持有】(?:[的、，, ]{0,4})?(?:但是?没有?|未){position}?【持有产品类型-未持有】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}有哪些客户【持有产品类型-持有】(?:[的、，, ]{0,4})?(?:但是?没有?|未){position}?【持有产品类型-未持有】(?:[的]{0,2})?(?:的客户|客户)?'
    priority: 22

  - name: "年龄范围+未持有综拓产品"
    # 青年客户没有e生保的客户
    patterns:
      - '{SEARCH}【年龄-青年】(?:[的、，, ]{0,3})?(?:没有?|未持有|没买)【持有综拓产品类别】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-青年】(?:[的、，, ]{0,3})?【持有综拓产品类别】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-中年】(?:[的、，, ]{0,3})?(?:没有?|未持有|没买)【持有综拓产品类别】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-中年】(?:[的、，, ]{0,3})?【持有综拓产品类别】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-老年】(?:[的、，, ]{0,3})?(?:没有?|未持有|没买)【持有综拓产品类别】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-老年】(?:[的、，, ]{0,3})?【持有综拓产品类别】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,4})?【持有综拓产品类别】(?:有哪些人|有哪些|名单|的客户|客户|的人|人|的)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,4})?【持有综拓产品类别】(?:有哪些人|有哪些|名单|的客户|客户|的人|人|的)?'
    priority: 22

  - name: "年龄范围+未持有投保险种"
    # 40岁左右黄金VIP有哪些人
    patterns:
      - '{SEARCH}【年龄-青年】(?:[的、，, ]{0,3})?(?:没有?|未持有|没买)【未持有-投保险种简称】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-青年】(?:[的、，, ]{0,3})?【未持有-投保险种简称】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-中年】(?:[的、，, ]{0,3})?(?:没有?|未持有|没买)【未持有-投保险种简称】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-中年】(?:[的、，, ]{0,3})?【未持有-投保险种简称】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-老年】(?:[的、，, ]{0,3})?(?:没有?|未持有|没买)【未持有-投保险种简称】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-老年】(?:[的、，, ]{0,3})?【未持有-投保险种简称】(?:[的]{0,2})?(?:的客户|客户)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,4})?【未持有-投保险种简称】(?:有哪些人|有哪些|名单|的客户|客户|的人|人|的)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,4})?【未持有-投保险种简称】(?:有哪些人|有哪些|名单|的客户|客户|的人|人|的)?'
    priority: 25

  - name: "年龄范围+保额-以上"
    # 40岁左右黄金VIP有哪些人
    patterns:
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,3})?【保额-以上】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,3})?【保额-以上-非万】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【保额-以上】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【保额-以上-非万】(?:有哪些人|的客户|客户)?'
    priority: 20

  - name: "年龄+产险产品"
    patterns:
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,3})?【产险产品-车险】(?:的客户|客户)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【产险产品-车险】(?:的客户|客户)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,3})?【产险产品-非车险】(?:的客户|客户)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【产险产品-非车险】(?:的客户|客户)?'
    priority: 20

  - name: "性别+年缴保费"
    patterns:
      - '{SEARCH}【性别-简单】(?:性)?(?:[的、，, ]{0,3})?【年缴保费-以上】(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【性别-简单】(?:性)?(?:[的、，, ]{0,3})?【年缴保费-以上-非万】(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【年缴保费-以上】(?:[的、，, ]{0,3})?【性别-简单】(?:性)?(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【年缴保费-以上-非万】(?:[的、，, ]{0,3})?【性别-简单】(?:性)?(?:的客户|客户|名单|的人|人)?'
    priority: 20

  - name: "寿险VIP+险种"
    patterns:
      - '{SEARCH}【寿险VIP】(?:[的、，, ]{0,4})?【险种-持有】(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}【险种-持有】(?:[的、，, ]{0,4})?【寿险VIP】(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
    priority: 20

  - name: "年龄+寿险VIP+寿险产品"
    patterns:
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,4})?【寿险VIP】(?:[的、，, ]{0,4})?【寿险产品-存在】'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,4})?【寿险VIP】(?:[的、，, ]{0,4})?【寿险产品-存在】'
      - '{SEARCH}【寿险VIP】(?:[的、，, ]{0,4})?【年龄-精确】(?:[的、，, ]{0,4})?【寿险产品-存在】'
      - '{SEARCH}【寿险VIP】(?:[的、，, ]{0,4})?【年龄-左右】(?:[的、，, ]{0,4})?【寿险产品-存在】'
    priority: 22

  - name: "年龄+黄金及以上+养老险"
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,5})?【寿险VIP-及以上-黄金】(?:[、，, ]{0,4})?(?:的)?(?:[、，, ]{0,4})?【有养老险】(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,5})?【寿险VIP-及以上-黄金】(?:[、，, ]{0,4})?(?:的)?(?:[、，, ]{0,4})?【有养老险】(?:的客户|客户|名单|的人|人)?'
    priority: 25

  - name: "客户价值+险种"
    patterns:
      - '{SEARCH}【客户价值】(?:[的、，, ]{0,3})?【险种-持有】(?:的客户|客户)?'
      - '{SEARCH}【险种-持有】(?:[的、，, ]{0,3})?【客户价值】(?:的客户|客户)?'
      - '{SEARCH}【客户价值-A类】(?:[的、，, ]{0,3})?【险种-持有】(?:的客户|客户)?'
      - '{SEARCH}【险种-持有】(?:[的、，, ]{0,3})?【客户价值-A类】(?:的客户|客户)?'
    priority: 20

#  - name: "共享给我的客户+客户价值"
#    patterns:
#      - '{SEARCH}(?:成功)?(?:共享|分享)(?:给我|给我的|给当前用户|给当前用户的)?(?:的)?【客户价值-A类】'
#      - '{SEARCH}(?:成功)?(?:共享|分享)(?:给我|给我的|给当前用户|给当前用户的)?(?:的)?【客户价值-AB类】'
#      - '{SEARCH}(?:成功)?(?:共享|分享)(?:给我|给我的|给当前用户|给当前用户的)?(?:的)?【客户价值-紧凑等级组合】'
#      - '{SEARCH}(?:成功)?(?:共享|分享)(?:给我|给我的|给当前用户|给当前用户的)?(?:的)?【客户价值】'
#      - '{SEARCH}(?:成功)?(?:共享|分享)(?:给我|给我的|给当前用户|给当前用户的)?(?:的)?【客户价值-高价值】'
#      - '{SEARCH}(?:成功)?(?:共享|分享)(?:给我|给我的|给当前用户|给当前用户的)?(?:的)?【客户价值-及以上】'
#      - '{SEARCH}(?:成功)?(?:共享|分享)(?:给我|给我的|给当前用户|给当前用户的)?(?:的)?【客户价值-及以下】'
#    priority: 95
#    extra_conditions:
#      - field: "onlyShareClientFlag"
#        operator: "MATCH"
#        value: "Y"

  - name: "年龄+客户价值+险种"
    patterns:
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【客户价值】(?:[的、，, ]{0,3})?【险种-持有】(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【客户价值-A类】(?:[的、，, ]{0,3})?【险种-持有】(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,3})?【客户价值】(?:[的、，, ]{0,3})?【险种-持有】(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,3})?【客户价值-A类】(?:[的、，, ]{0,3})?【险种-持有】(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
    priority: 22

  - name: "年龄+客户温度+持有产品类型"
    patterns:
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【客户温度】(?:[的、，, ]{0,3})?【持有产品类型-持有】(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,3})?【客户温度】(?:[的、，, ]{0,3})?【持有产品类型-持有】(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【客户温度】(?:[的、，, ]{0,3})?【年龄-精确】(?:[的、，, ]{0,3})?【持有产品类型-持有】(?:的客户|客户|名单|的人|人)?'
    priority: 22

  - name: "年龄+客户温度+寿险产品"
    patterns:
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,4})?【客户温度】(?:[的、，, ]{0,4})?【寿险产品-存在】'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,4})?【客户温度】(?:[的、，, ]{0,4})?【寿险产品-存在】'
      - '{SEARCH}【客户温度】(?:[的、，, ]{0,4})?【年龄-精确】(?:[的、，, ]{0,4})?【寿险产品-存在】'
      - '{SEARCH}【客户温度】(?:[的、，, ]{0,4})?【年龄-左右】(?:[的、，, ]{0,4})?【寿险产品-存在】'
    priority: 22

  - name: "年龄范围+婚姻+有子女+性别"
    patterns:
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的、，, ]{0,3})?【家庭成员关系-有】(?:[的、，, ]{0,3})?【性别-枚举】(?:性)?(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的、，, ]{0,3})?【家庭成员关系-有】(?:[的、，, ]{0,3})?【性别-枚举】(?:性)?(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的、，, ]{0,3})?【家庭成员关系-有】(?:[的、，, ]{0,3})?姓?【性别-枚举】(?:性)?(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的、，, ]{0,3})?【家庭成员关系-有】(?:[的、，, ]{0,3})?姓?【性别-枚举】(?:性)?(?:的客户|客户|名单|的人|人)?'
    priority: 24

#  - name: "姓名+寿险产品"
#    patterns:
#      - '{SEARCH}【姓名-匹配】(?:[的、，, ]{0,3})?【寿险产品-持有】(?:的客户|客户|名单|的人|人)?'
#      - '{SEARCH}【寿险产品-持有】(?:[的、，, ]{0,3})?【姓名-匹配】(?:的客户|客户|名单|的人|人)?'
#      - '{SEARCH}【姓名-匹配】(?:[的、，, ]{0,3})?【寿险产品-存在】(?:的客户|客户|名单|的人|人)?'
#    priority: 22

  - name: "年龄GTE+学历"
    # 45岁以上的博士
    patterns:
      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,3})?【学历】'
      - '{SEARCH}【年龄-及以上】(?:[的、，, ]{0,3})?【学历】'
    priority: 20

  - name: "婚姻+学历以上"
    patterns:
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【学历-以上】(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【学历-以上】(?:[的、，, ]{0,3})?【婚姻状况】(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【学历-及以上】(?:的客户|客户|名单|的人|人)?'
      - '{SEARCH}【学历-及以上】(?:[的、，, ]{0,3})?【婚姻状况】(?:的客户|客户|名单|的人|人)?'
    priority: 22

  - name: "客户价值+客户温度"
    # A类冷却客户 / A类中温客户 / A类低温名单
    patterns:
      - '{SEARCH}【客户价值】(?:[的、，, ]{0,3})?【客户温度】(?:的客户|客户|名单)?'
      - '{SEARCH}【客户价值-A类】(?:[的、，, ]{0,3})?【客户温度】(?:的客户|客户|名单)?'
      - '{SEARCH}【客户温度】(?:[的、，, ]{0,3})?【客户价值】(?:的客户|客户|名单)?'
      - '{SEARCH}【客户温度】(?:[的、，, ]{0,3})?【客户价值-A类】(?:的客户|客户|名单)?'
      - '{SEARCH}【客户价值】(?:[的、，, ]{0,3})?【客户温度-中高温】(?:的客户|客户|名单)?'
      - '{SEARCH}【客户价值-A类】(?:[的、，, ]{0,3})?【客户温度-中高温】(?:的客户|客户|名单)?'
      - '{SEARCH}【客户温度-中高温】(?:[的、，, ]{0,3})?【客户价值】(?:的客户|客户|名单)?'
      - '{SEARCH}【客户温度-中高温】(?:[的、，, ]{0,3})?【客户价值-A类】(?:的客户|客户|名单)?'
    priority: 20

  - name: "寿险VIP+客户温度"
    # 黄金VIP低温客户
    patterns:
      - '{SEARCH}【寿险VIP】(?:[的、，, ]{0,3})?【客户温度】(?:的客户|客户|名单)?'
      - '{SEARCH}【客户温度】(?:[的、，, ]{0,3})?【寿险VIP】(?:的客户|客户|名单)?'
    priority: 20

  - name: "客户价值+客户温度+寿险产品"
    # 黄金VIP低温e生保有哪些人
    patterns:
      - '{SEARCH}【寿险VIP】(?:[的、，, ]{0,3})?【客户温度】(?:[的、，, ]{0,3})?【投保险种简称】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【客户价值】(?:[的、，, ]{0,3})?【客户温度】(?:[的、，, ]{0,3})?【投保险种简称】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【客户价值-A类】(?:[的、，, ]{0,3})?【客户温度】(?:[的、，, ]{0,3})?【投保险种简称】(?:有哪些人|的客户|客户)?'
    priority: 25

  - name: "年龄+客户价值+客户温度"
    # 40岁左右高价值低温有哪些人
    patterns:
      - '{SEARCH}【年龄-多岁】(?:[的、，, ]{0,3})?【客户价值】(?:[的、，, ]{0,3})?【客户温度】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【客户价值】(?:[的、，, ]{0,3})?【客户温度】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【年龄-多岁】(?:[的、，, ]{0,3})?【客户温度】(?:[的、，, ]{0,3})?【客户价值】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【客户温度】(?:[的、，, ]{0,3})?【客户价值】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【年龄-多岁】(?:[的、，, ]{0,3})?【客户价值-A类】(?:[的、，, ]{0,3})?【客户温度】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【客户价值-A类】(?:[的、，, ]{0,3})?【客户温度】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【年龄-多岁】(?:[的、，, ]{0,3})?【客户温度】(?:[的、，, ]{0,3})?【客户价值-A类】(?:有哪些人|的客户|客户)?'
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【客户温度】(?:[的、，, ]{0,3})?【客户价值-A类】(?:有哪些人|的客户|客户)?'
    priority: 25

  - name: "寿险VIP+年缴保费"
    # 帮我找VIP保费一万以上名单
    patterns:
      - '{SEARCH}【寿险VIP】(?:[的、，, ]{0,3})?【年缴保费-以上】(?:名单|的客户|客户)?'
    priority: 20

  - name: "年龄+年缴保费"
    # 查30多岁保费超过5000都有谁 / 45岁保费10万以上
    patterns:
      - '{SEARCH}【年龄-多岁】(?:[的、，, ]{0,3})?【年缴保费-以上】(?:都有谁|的客户|客户)?'
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【年缴保费-以上】(?:都有谁|的客户|客户)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【年缴保费-以上】(?:都有谁|的客户|客户)?'
      - '{SEARCH}【年龄-多岁】(?:[的、，, ]{0,3})?【年缴保费-以上-非万】(?:都有谁|的客户|客户)?'
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【年缴保费-以上-非万】(?:都有谁|的客户|客户)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【年缴保费-以上-非万】(?:都有谁|的客户|客户)?'
    priority: 20

  - name: "年龄+性别+年缴保费"
    # 45岁女性投保保费在30万以上的客户 / 45岁女性保费10万以上
    patterns:
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【性别-简单】(?:性)?(?:[的、，, ]{0,3})?(?:投保)?【年缴保费-以上】(?:的客户|客户)?'
      - '{SEARCH}【年龄-多岁】(?:[的、，, ]{0,3})?【性别-简单】(?:性)?(?:[的、，, ]{0,3})?(?:投保)?【年缴保费-以上】(?:的客户|客户)?'
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【性别-简单】(?:性)?(?:[的、，, ]{0,3})?(?:投保)?【年缴保费-以上】(?:的客户|客户)?'
      - '{SEARCH}【年龄-精确】(?:[的、，, ]{0,3})?【性别-简单】(?:性)?(?:[的、，, ]{0,3})?(?:投保)?【年缴保费-以上-非万】(?:的客户|客户)?'
      - '{SEARCH}【年龄-多岁】(?:[的、，, ]{0,3})?【性别-简单】(?:性)?(?:[的、，, ]{0,3})?(?:投保)?【年缴保费-以上-非万】(?:的客户|客户)?'
      - '{SEARCH}【年龄-范围】(?:[的、，, ]{0,3})?【性别-简单】(?:性)?(?:[的、，, ]{0,3})?(?:投保)?【年缴保费-以上-非万】(?:的客户|客户)?'
    priority: 25

  # ---------- 证件类型 + 证件号码 ----------
  - name: "证件类型+证件号码"
    patterns:
      - '{SEARCH}【证件类型】{CW}{0,2}(?:为|是|：|:)?{CW}{0,2}【证件号码-数字】(?:的客户|客户)?'
      - '{SEARCH}【证件类型】{CW}{0,2}(?:号码?|号|No\.?)?{CW}{0,2}(?:为|是|：|:)?{CW}{0,2}【证件号码-数字】(?:的客户|客户)?'
    priority: 15

  - name: "年龄左右+子女教育"
    patterns:
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,5})?(?:有|的)?【子女教育阶段-初中】(?:的客户|客户)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,5})?(?:有|的)?【子女教育阶段-高中】(?:的客户|客户)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,5})?(?:有|的)?【子女教育阶段-大学】(?:的客户|客户)?'
    priority: 22
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"

  - name: "年龄左右+女儿教育"
    patterns:
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,5})?(?:有|的)?【女儿教育阶段-初中】(?:的客户|客户)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,5})?(?:有|的)?【女儿教育阶段-高中】(?:的客户|客户)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,5})?(?:有|的)?【女儿教育阶段-大学】(?:的客户|客户)?'
    priority: 22
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "女"

  - name: "年龄左右+儿子教育"
    patterns:
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,5})?(?:有|的)?【儿子教育阶段-初中】(?:的客户|客户)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,5})?(?:有|的)?【儿子教育阶段-高中】(?:的客户|客户)?'
      - '{SEARCH}【年龄-左右】(?:[的、，, ]{0,5})?(?:有|的)?【儿子教育阶段-大学】(?:的客户|客户)?'
    priority: 22
    extra_conditions:
      - field: "familyInfo.familyrelation"
        operator: "CONTAINS"
        value: "子女"
      - field: "familyInfo.familyclientsex"
        operator: "MATCH"
        value: "男"

  - name: "客户价值+家里老人"
    patterns:
      - '{SEARCH}【客户价值】(?:[的、，, ]{0,4})?【家庭成员关系-老人】(?:的(?:客户)?|客户)?'
      - '{SEARCH}【家庭成员关系-老人】(?:[的、，, ]{0,4})?【客户价值】(?:的(?:客户)?|客户)?'
      - '{SEARCH}【客户价值-A类】(?:[的、，, ]{0,4})?【家庭成员关系-老人】(?:的(?:客户)?|客户)?'
      - '{SEARCH}【家庭成员关系-老人】(?:[的、，, ]{0,4})?【客户价值-A类】(?:的(?:客户)?|客户)?'
    priority: 22

#  - name: "年龄GTE+寿险产品+寿险客户"
#    patterns:
#      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,4})?【寿险产品-持有】(?:[的、，, ]{0,4})?(?:寿险客户|寿险名单|有寿险的客户|买过寿险的客户|购买过寿险的客户)(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
#      - '{SEARCH}【年龄-以上】(?:[的、，, ]{0,4})?(?:寿险客户|寿险名单|有寿险的客户|买过寿险的客户|购买过寿险的客户)(?:[的、，, ]{0,4})?【寿险产品-持有】(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
#      - '{SEARCH}【寿险产品-持有】(?:[的、，, ]{0,4})?【年龄-以上】(?:[的、，, ]{0,4})?(?:寿险客户|寿险名单|有寿险的客户|买过寿险的客户|购买过寿险的客户)(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
#      - '{SEARCH}(?:寿险客户|寿险名单|有寿险的客户|买过寿险的客户|购买过寿险的客户)(?:[的、，, ]{0,4})?【年龄-以上】(?:[的、，, ]{0,4})?【寿险产品-持有】(?:的客户|客户|名单|的人|人|有哪些人|有哪些|的)?'
#    priority: 22

# ==================== 否定词列表 ====================

negation_words:
  - "没有配置"
  - "未配置"
  - "没配置"
  - "未购买"
  - "没有"
  - "没买"
  - "未买"
  - "缺少"
  - "缺失"
  - "没"
  - "无"
  - "不"
  - "缺"
  - "未"
  - "非"

# ==================== 持有词列表（{position} 变量）====================
# 按长度降序排列，确保较长词优先匹配

position_words:
  - "已配置"
  - "已投保"
  - "购买了"
  - "购买"
  - "配置了"
  - "配置"
  - "配置有"
  - "投保了"
  - "投保"
  - "购买过"
  - "买过"
  - "买了"
  - "已有"
  - "有了"
  - "有过"
  - "持有"
  - "有"
