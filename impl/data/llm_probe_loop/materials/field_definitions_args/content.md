# ============================================================
# RAG 知识库 - 字段查询意图定义
# ============================================================
# 结构说明：
#   id            : 唯一标识
#   retrieval_text: 用于向量检索的自然语言表达（覆盖用户的各种说法）
#   field         : 目标字段名（使用Excel英文名）
#   operator      : 操作符 MATCH/GTE/LTE/RANGE/CONTAINS/NOT_CONTAINS/EXISTS/NOT_EXISTS
#   value_type    :
#     extract     - 从查询文本直接提取（产品名、姓名、地址等开放域）
#     enum        - 从枚举列表中选取（枚举值在 enum 字段中）
#     numeric     - 数值提取，需按 unit 换算
#     date        - 日期提取，需按 format 格式化
#     static      - 固定值（在 value 字段中）
#     infer       - 需要 LLM 根据 enum 推断（口语→标准值）
#     exists      - 无需值，仅判断字段是否存在
#   enum          : 枚举值列表（value_type=enum/infer 时使用）
#   unit          : 数值换算规则
#   show_enum_in_prompt           : 是否展开全量枚举值（false 时不展开全量枚举值）
#   enum_candidate_limit_in_prompt: 当不展开全量枚举时，最多展示多少个候选枚举
#   format        : 日期格式
#   examples      : 示例查询及输出（用于 few-shot）
#   description   : 字段语义定义（明确是什么）
#   negative_examples: 禁止映射的反例（明确不是什么）
#   notes         : 补充说明
# ============================================================

intents:

  # ==================== 姓名 ====================

  - id: name_exact
    retrieval_text: >
      客户姓名 姓名是 姓名为 名字是 名叫 叫做 名字叫 全名
      姓氏 姓什么 姓张 姓李 姓王 姓陈 单独输入姓氏 按姓名查客户 查询姓名
    field: searchClientName
    operator: MATCH
    value_type: extract
    description: "仅表示客户本人的人名；不表示客户集合、公司/机构名称、地址、产品名，也不表示家庭成员、被保人或投保人姓名"
    notes: '只有满足以下任一条件才输出本字段：1）查询用“姓名/名字/名叫/叫做/姓氏”等人名指示词明确引出姓名；2）整条查询去掉“查询/查找/的客户/本人”等外壳后，仅剩一个符合中文人名结构的2至4字姓名（单姓+1至2字名，或复姓+1至2字名）；3）整条查询仅为百家姓中的单姓或复姓时，按姓氏前缀查询并设置match_mode=prefix。提取值只能是人名本身，不能包含“客户/本人/全部/所有/公司/有限公司/集团”等词。公司、机构、门店、地区或其他业务名词即使是连续中文也绝不能当作姓名；无法确认是自然人人名时宁可不输出。完整姓名必须原样保留，如“陈成”“李保”“张无”“金美”“王小明”。'
    examples:
      - query: "陈成"
        output: {field: searchClientName, operator: MATCH, value: "陈成"}
      - query: "李保本人"
        output: {field: searchClientName, operator: MATCH, value: "李保"}
      - query: "姓张的客户"
        output: { field: searchClientName, operator: MATCH, value: "张", match_mode: "prefix" }
      - query: "张中波保单号"
        output: {field: searchClientName, operator: MATCH, value: "张中波"}
      - query: "郑依林身份证号"
        output: {field: searchClientName, operator: MATCH, value: "郑依林"}
      - query: "高"
        output: { field: searchClientName, operator: MATCH, value: "高", match_mode: "prefix" }
      - query: "名字带伟的客户"
        output: {field: searchClientName, operator: MATCH, value: "伟", match_mode: "contains"}
      - query: "姓zhang的客户"
        output: { field: searchClientName, operator: MATCH, value: "zhang", match_mode: "prefix" }
    negative_examples:
      - query: "子女叫张三的客户"
        reason: "这是家庭成员姓名，应映射到 familyInfo.familyclientname 并组合 familyInfo.familyrelation"
      - query: "全部客户"
        reason: "“全部”是范围词，“客户”是查询对象，查询中没有任何自然人人名"
      - query: "所有客户"
        reason: "这是无姓名筛选条件的客户集合查询，不能把“所有”或“所有客户”提取为姓名"
      - query: "泉州旭粉体有限公司"
        reason: "带“有限公司”的文本是企业名称，不是自然人人名"
      - query: "平安银行的客户"
        reason: "“平安银行”是机构名称，不是客户本人姓名"

  - id: name_contains
    retrieval_text: >
      多个客户姓名 多个姓名 姓名列表 姓名分别是 姓名包括
      名字带 名字含 名字包含 名字里有 名字中有
    field: searchClientName
    operator: CONTAINS
    value_type: extract
    description: "表示客户本人自然人姓名中的包含/多候选姓名匹配，不表示公司、机构、地区、地址或泛指客户集合"
    notes: '仅当用户明确表达客户本人姓名包含某字/多个自然人姓名候选时输出。禁止把"全部客户/所有客户/客户列表"等集合词当姓名候选；禁止把包含"公司/有限公司/集团/工厂/粉体/科技/商贸/医院/学校/银行/门店"等组织机构后缀的文本当姓名候选；禁止把明显地区、地址、商圈或道路小区名称当客户姓名。'
    examples:
      - query: "查找叫张三和李四的客户"
        output: { field: searchClientName, operator: CONTAINS, value: ["张三", "李四"] }
    negative_examples:
      - query: "子女叫张三的客户"
        reason: "这是家庭成员姓名，应映射到 familyInfo.familyclientname 并组合 familyInfo.familyrelation"
      - query: "全部客户"
        reason: "这是客户集合查询，不是多个姓名或姓名包含查询"
      - query: "泉州旭粉体有限公司"
        reason: "这是企业名称，不是自然人人名列表"

  # ==================== 暂不支持的业务动作 ====================

  - id: customer_review_unsupported
    is_supported: false
    retrieval_text: >
      盘客 客户盘客 去盘客 做盘客 进行盘客 本月盘客
      7月盘客 七月客户盘客 5月盘客客户
    field: customerReview
    operator: MATCH
    value_type: static
    description: "表示代理人的盘客业务动作或盘客月份，不表示客户添加日、联系日期或保单日期；当前暂不支持作为客户搜索条件"
    examples:
      - query: "七月客户盘客"
        output: { field: customerReview, operator: MATCH, value: "盘客" }
      - query: "去盘客"
        output: { field: customerReview, operator: MATCH, value: "盘客" }

  - id: customer_activity_unsupported
    is_supported: false
    retrieval_text: >
      客户活动 活动名称 活动季 守护季 营销活动 参加活动
      平安伴你行守护季
    field: customerActivity
    operator: MATCH
    value_type: extract
    description: "表示营销活动或活动季名称，不表示投保险种名称、险种简称或会员权益；当前暂不支持作为客户搜索条件"
    examples:
      - query: "平安伴你行守护季"
        output: { field: customerActivity, operator: MATCH, value: "平安伴你行守护季" }
      - query: "参加春季营销活动的客户"
        output: { field: customerActivity, operator: MATCH, value: "春季营销活动" }

  - id: customer_unredeemed_points_unsupported
    is_supported: false
    retrieval_text: >
      客户积分 未兑换积分 未兑积分 积分余额 积分未兑换
      积分以上未兑换 未兑换积分以上 积分不少于 积分不低于
    field: customerUnredeemedPoints
    operator: GTE
    value_type: numeric
    unit: "积分，万=×10000；数值表示客户当前未兑换积分余额"
    description: "表示客户尚未兑换的积分余额下限，不表示客户价值、保费、保额或现金金额；当前暂不支持作为客户搜索条件"
    examples:
      - query: "60万积分以上未兑换客户"
        output: { field: customerUnredeemedPoints, operator: GTE, value: 600000 }
      - query: "未兑换积分不少于50万的客户"
        output: { field: customerUnredeemedPoints, operator: GTE, value: 500000 }
      - query: "未兑换积分达到600000的客户"
        output: { field: customerUnredeemedPoints, operator: GTE, value: 600000 }

  # ==================== 手机号 ====================

  - id: mobile_phone
    retrieval_text: >
      客户手机号 客户手机 客户电话 客户联系方式 手机号 手机 电话 联系方式 号码 手机尾号 手机开头 11位手机号 直接输入手机号 1234567890 手机号后四位 手机末尾
    field: clientMobile
    operator: MATCH
    value_type: extract
    description: "仅表示客户本人手机号，不表示被保人、投保人、联系人、家庭成员手机号；当查询客户手机尾号|尾数|末尾|后x位|后几位|结尾时，必须设置match_mode=suffix"
    notes: "手机号字段名必须是 clientMobile；只有查询对象明确是客户本人，或未指明对象仅说手机号/电话时，才可映射到该字段。手机号一定是由1-11为的数字组成的。"
    examples:
      - query: "客户手机号为133"
        output: {field: clientMobile, operator: MATCH, value: "133"}
      - query: "手机号138开头的客户"
        output: {field: clientMobile, operator: MATCH, value: "138", match_mode: "prefix"}
      - query: "手机尾号8888的客户"
        output: {field: clientMobile, operator: MATCH, value: "8888", match_mode: "suffix"}
      - query: "158****5078"
        output: {field: clientMobile, operator: MATCH, value: "5078", match_mode: "suffix"}
      - query: "15817760299"
        output: {field: clientMobile, operator: MATCH, value: "15817760299"}
    negative_examples:
      - query: "被保人手机号为133XXXXXXxxx"
        reason: "当前没有被保人手机号字段，不能映射到 clientMobile"
      - query: "投保人手机号为133XXXXXXxxx"
        reason: "投保人不是客户本人，语义不一致，不能映射到 clientMobile"
      - query: "联系人手机号为133XXXXXXxxx"
        reason: "联系人手机号与客户手机号不是同一字段，不能误映射"

  # ==================== 性别 ====================

  - id: gender
    retrieval_text: >
      性别 男 女 男性 女性 男客户 女客户 男的 女的 先生 女士
    field: clientSex
    operator: MATCH
    value_type: enum
    enum_ref: clientSex
    description: "表示客户本人性别，不表示家庭成员、被保人、投保人性别"
    examples:
      - query: "男性客户"
        output: {field: clientSex, operator: MATCH, value: "男"}
      - query: "女客户"
        output: {field: clientSex, operator: MATCH, value: "女"}
    negative_examples:
      - query: "子女是男性的客户"
        reason: "这是家庭成员性别，应映射到 familyInfo.familyclientsex 并组合 familyInfo.familyrelation"

  - id: gender_exists
    retrieval_text: >
      有性别信息 性别不为空 有客户性别标签 有性别字段
    field: clientSex
    operator: EXISTS
    value_type: exists
    description: "表示客户存在性别信息，不要求具体是男或女"
    examples:
      - query: "有性别信息的客户"
        output: { field: clientSex, operator: EXISTS, value: "" }
      - query: "性别不为空的客户"
        output: { field: clientSex, operator: EXISTS, value: "" }

  - id: gender_not_exists
    retrieval_text: >
      没有性别信息 性别为空 无客户性别标签 无性别字段
    field: clientSex
    operator: NOT_EXISTS
    value_type: not_exists
    description: "表示客户不存在性别信息，不要求具体枚举值"
    examples:
      - query: "没有性别信息的客户"
        output: { field: clientSex, operator: NOT_EXISTS, value: "" }
      - query: "性别为空的客户"
        output: { field: clientSex, operator: NOT_EXISTS, value: "" }


  # ==================== 属相 ====================

  - id: zodiac_exact
    is_supported: false
    retrieval_text: >
      客户属相 属相 生肖 十二生肖 属什么 属鼠 属牛 属虎 属兔 属龙 属蛇
      属马 属羊 属猴 属鸡 属狗 属猪 鼠年 牛年 虎年 兔年 龙年 蛇年
      马年 羊年 猴年 鸡年 狗年 猪年
    field: clientZodiac
    operator: MATCH
    value_type: enum
    enum_ref: clientZodiac
    description: "表示客户本人的十二生肖属相，不表示姓名、出生年份或家庭成员属相"
    notes: "标准值仅限鼠、牛、虎、兔、龙、蛇、马、羊、猴、鸡、狗、猪。整条查询仅为一个生肖字时按客户属相查询；明确使用“姓马、姓牛”等姓名语境时仍按客户姓氏查询。"
    examples:
      - query: "属相是马的客户"
        output: { field: clientZodiac, operator: MATCH, value: "马" }
      - query: "属牛的客户"
        output: { field: clientZodiac, operator: MATCH, value: "牛" }
      - query: "生肖为羊的客户"
        output: { field: clientZodiac, operator: MATCH, value: "羊" }
      - query: "马"
        output: { field: clientZodiac, operator: MATCH, value: "马" }
    negative_examples:
      - query: "姓马的客户"
        reason: "这是客户姓氏，应映射到 searchClientName 并设置 match_mode=prefix"
      - query: "马明的客户"
        reason: "这是客户完整姓名，不是客户属相"

  # ==================== 年龄 ====================

  - id: age_gte
    retrieval_text: >
      年龄 大于 高于 超过 大于等于 年龄大于等于 不少于 不低于 及以上
      岁以上 岁及以上 以上VIP 年龄以上VIP
    field: clientAge
    operator: GTE
    value_type: numeric
    unit: "岁，直接取数字，无需换算"
    description: "表示客户本人年龄，不表示家庭成员年龄"
    notes: "此字段仅支持GTE操作符。边界词必须按原文区分：‘N岁以上/及以上’包含N，始终输出GTE N，不能加1；只有‘大于/超过/高于N岁’不包含N，才转换为GTE N+1。该规则在年龄与VIP、保单、投保时间等其他条件组合时仍不改变。"
    examples:
      - query: "45岁以上的客户"
        output: {field: clientAge, operator: GTE, value: 45}
      - query: "45岁及以上的客户"
        output: {field: clientAge, operator: GTE, value: 45}
      - query: "大于60岁的客户"
        output: {field: clientAge, operator: GTE, value: 61}
      - query: "年龄超过50岁的客户"
        output: { field: clientAge, operator: GTE, value: 51 }
      - query: "我附近5公里内且客户年龄大于50岁"
        output: { field: clientAge, operator: GTE, value: 51 }
      - query: "60或50岁及以上的客户"
        query_logic: OR
        conditions: [{ field: clientAge, operator: GTE, value: 60 }, { field: clientAge, operator: GTE, value: 50 }]
    negative_examples:
      - query: "子女10岁及以上的客户"
        reason: "这是家庭成员年龄，应映射到 familyInfo.familyclientage 并组合 familyInfo.familyrelation"

  - id: age_lte
    retrieval_text: >
      年龄小于等于 不超过 至多 及以下 岁以下 岁及以下
    field: clientAge
    operator: LTE
    value_type: numeric
    unit: "岁，直接取数字"
    description: "表示客户本人年龄，不表示家庭成员年龄"
    notes: "只处理包含边界的年龄上限：‘N岁以下/及以下/不超过/至多N岁’均输出LTE N，禁止减1。‘小于/低于/不满N岁’由age_lt_normalized处理。"
    examples:
      - query: "35岁以下的客户"
        output: {field: clientAge, operator: LTE, value: 35}
      - query: "35岁及以下的客户"
        output: {field: clientAge, operator: LTE, value: 35}
      - query: "30或40岁及以下"
        query_logic: OR
        conditions: [{ field: clientAge, operator: LTE, value: 30 }, { field: clientAge, operator: LTE, value: 40 }]
    negative_examples:
      - query: "未成年子女的客户"
        reason: "这是家庭成员年龄语义，应映射到 familyInfo.familyclientage 并组合 familyInfo.familyrelation"

  - id: age_lt_normalized
    retrieval_text: >
      年龄小于 年龄低于 小于x岁 低于x岁 不满x岁 未满x岁
    field: clientAge
    operator: LTE
    value_type: numeric
    unit: "岁，直接取数字"
    description: "表示客户本人严格小于某年龄；查询协议使用LTE，因此边界值减1"
    notes: "只处理不包含边界的‘小于/低于/不满/未满N岁’，统一输出LTE N-1。例如小于50岁→LTE 49。不得用于‘N岁以下/及以下’，后者包含N并由age_lte处理。"
    examples:
      - query: "小于35岁的客户"
        output: { field: clientAge, operator: LTE, value: 34 }
      - query: "低于50岁的客户"
        output: { field: clientAge, operator: LTE, value: 49 }
    negative_examples:
      - query: "50岁以下的客户"
        reason: "‘以下’包含50岁，应使用age_lte输出LTE 50，不能减1"

  - id: age_range
    retrieval_text: >
      年龄范围 到岁之间 岁到岁 年龄区间 x岁到x岁
      30到40岁 中年 青年 老年 年龄段 20多岁 30多岁 40多岁 五十多岁
      精确年龄 年龄等于 年龄为 正好x岁 x岁客户 30岁 35岁 40岁 45岁 50岁 60岁
      年龄左右 岁左右 年龄约 年龄大约 大概x岁 约x岁 40岁左右 50岁上下
    field: clientAge
    operator: RANGE
    value_type: numeric
    unit: "岁，直接取数字"
    description: "表示客户本人的精确年龄、近似年龄、年龄区间或语义年龄段，不表示家庭成员年龄"
    notes: "统一处理精确年龄、近似年龄、明确起止区间和语义年龄段。原文年龄片段只有‘N岁’且该数字后没有以上、以下、大于、小于、左右、约、大概或起止区间时，输出RANGE {min:N,max:N}；数字相邻位置明示‘左右/上下/大约/约/大概’时，输出RANGE {min:N-5,max:N+5}，不得改成上下2岁或十年年龄段。其他字段片段中的比较词不得作用于年龄。青年=18~35，中年=36~55，老年=56~100，未成年=0~17；‘N0多岁’表示N0~N9，例如30多岁→30~39。以上、以下、大于、小于等边界表达仍由对应的GTE/LTE知识处理。"
    examples:
      - query: "30到40岁的客户"
        output: {field: clientAge, operator: RANGE, value: {min: 30, max: 40}}
      - query: "中年客户"
        output: {field: clientAge, operator: RANGE, value: {min: 36, max: 55}}
      - query: "30多岁的客户"
        output: {field: clientAge, operator: RANGE, value: {min: 30, max: 39}}
      - query: "40岁的客户"
        output: {field: clientAge, operator: RANGE, value: {min: 40, max: 40}}
      - query: "45岁左右的客户"
        output: {field: clientAge, operator: RANGE, value: {min: 40, max: 50}}
      - query: "大约50岁的客户"
        output: {field: clientAge, operator: RANGE, value: {min: 45, max: 55}}
    negative_examples:
      - query: "配偶30到40岁的客户"
        reason: "这是家庭成员年龄范围，应映射到 familyInfo.familyclientage 并组合 familyInfo.familyrelation"

  - id: age_exists
    retrieval_text: >
      有年龄 年龄信息完整 知道年龄 录入年龄 年龄不为空
    field: clientAge
    operator: EXISTS
    value_type: exists
    description: "表示客户存在年龄信息，不要求具体年龄值"
    examples:
      - query: "有年龄信息的客户"
        output: { field: clientAge, operator: EXISTS, value: "" }
      - query: "年龄信息完整的客户"
        output: { field: clientAge, operator: EXISTS, value: "" }
    negative_examples:
      - query: "有子女年龄信息的客户"
        reason: "这是家庭成员年龄信息，应映射到 familyInfo.familyclientage 并组合 familyInfo.familyrelation"

  - id: age_not_exists
    retrieval_text: >
      没有年龄 年龄缺失 年龄未知 未录入年龄 年龄为空
    field: clientAge
    operator: NOT_EXISTS
    value_type: exists
    description: "表示客户不存在年龄信息，不要求具体年龄值"
    examples:
      - query: "没有年龄信息的客户"
        output: { field: clientAge, operator: NOT_EXISTS, value: "" }
      - query: "年龄未知的客户"
        output: { field: clientAge, operator: NOT_EXISTS, value: "" }
    negative_examples:
      - query: "没有子女年龄信息的客户"
        reason: "这是家庭成员年龄信息，应映射到 familyInfo.familyclientage 并组合 familyInfo.familyrelation"


   # ==================== 生日 ====================

  - id: birthday_exact
    retrieval_text: >
      生日 出生日期 出生年月日 生日是 出生于 哪年哪月出生 90后 00后 80后 01后 66年出生 83年客户
    field: clientBirthday
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示客户本人出生日期，不表示家庭成员出生日期"
    examples:
      - query: "1990年出生的客户"
        output: {field: clientBirthday, operator: RANGE, value: {min: "1990-01-01 00:00:00", max: "1990-12-31 00:00:00"}}
      - query: "1985年5月出生的客户"
        output: {field: clientBirthday, operator: RANGE, value: {min: "1985-05-01 00:00:00", max: "1985-05-31 00:00:00"}}
      - query: "90后客户"
        output: {field: clientBirthday, operator: RANGE, value: {min: "1990-00-01 00:00:00", max: "1999-12-31 00:00:00"}}
    negative_examples:
      - query: "父母1956年出生的客户"
        reason: "这是家庭成员出生日期，应映射到 familyInfo.familyclientbirthday 并组合 familyInfo.familyrelation"

  - id: birthday_gt
    retrieval_text: >
      生日 出生日期 出生年月日 出生于 哪年之后出生 某年之后出生
    field: clientBirthday
    operator: GT
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示客户本人出生日期晚于某个日期（不含等于）"
    examples:
      - query: "1990年之后出生的客户（不含1990年）"
        output: {field: clientBirthday, operator: GT, value: "1990-12-31 23:59:59"}
    negative_examples:
      - query: "父母1956年之后出生的客户"
        reason: "这是家庭成员出生日期，应映射到 familyInfo.familyclientbirthday 并组合 familyInfo.familyrelation"

  - id: birthday_gte
    retrieval_text: >
      生日 出生日期 出生年月日 出生于 哪年及之后出生 某年及之后出生
    field: clientBirthday
    operator: GTE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示客户本人出生日期晚于或等于某个日期"
    examples:
      - query: "1990年及之后出生的客户"
        output: {field: clientBirthday, operator: GTE, value: "1990-01-01 00:00:00"}
      - query: "1990年之后出生的客户"
        output: {field: clientBirthday, operator: GTE, value: "1990-01-01 00:00:00"}
    negative_examples:
      - query: "父母1956年之后出生的客户"
        reason: "这是家庭成员出生日期，应映射到 familyInfo.familyclientbirthday 并组合 familyInfo.familyrelation"

  - id: birthday_lt
    retrieval_text: >
      生日 出生日期 出生年月日 出生于 哪年之前出生 某年之前出生
    field: clientBirthday
    operator: LT
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示客户本人出生日期早于某个日期（不含等于）"
    examples:
      - query: "1990年之前出生的客户（不含1990年）"
        output: {field: clientBirthday, operator: LT, value: "1990-01-01 00:00:00"}
    negative_examples:
      - query: "父母1956年之前出生的客户"
        reason: "这是家庭成员出生日期，应映射到 familyInfo.familyclientbirthday 并组合 familyInfo.familyrelation"

  - id: birthday_lte
    retrieval_text: >
      生日 出生日期 出生年月日 出生于 哪年及之前出生 某年及之前出生
    field: clientBirthday
    operator: LTE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示客户本人出生日期早于或等于某个日期"
    examples:
      - query: "1990年及之前出生的客户"
        output: {field: clientBirthday, operator: LTE, value: "1990-12-31 23:59:59"}
      - query: "1990年之前出生的客户"
        output: {field: clientBirthday, operator: LTE, value: "1990-12-31 23:59:59"}
    negative_examples:
      - query: "父母1956年之前出生的客户"
        reason: "这是家庭成员出生日期，应映射到 familyInfo.familyclientbirthday 并组合 familyInfo.familyrelation"

  - id: birthday_exists
    retrieval_text: >
      有生日 有出生日期 生日信息完整 出生日期不为空 录入生日
    field: clientBirthday
    operator: EXISTS
    value_type: exists
    description: "表示客户存在出生日期信息，不要求具体日期值"
    examples:
      - query: "有生日信息的客户"
        output: { field: clientBirthday, operator: EXISTS, value: "" }
      - query: "有出生日期的客户"
        output: { field: clientBirthday, operator: EXISTS, value: "" }
    negative_examples:
      - query: "有父母生日信息的客户"
        reason: "这是家庭成员出生日期，应映射到 familyInfo.familyclientbirthday 并组合 familyInfo.familyrelation"

  - id: birthday_not_exists
    retrieval_text: >
      没有生日 没有出生日期 生日缺失 出生日期未知 生日为空
    field: clientBirthday
    operator: NOT_EXISTS
    value_type: exists
    description: "表示客户不存在出生日期信息，不要求具体日期值"
    examples:
      - query: "没有生日信息的客户"
        output: { field: clientBirthday, operator: NOT_EXISTS, value: "" }
      - query: "出生日期未知的客户"
        output: { field: clientBirthday, operator: NOT_EXISTS, value: "" }
    negative_examples:
      - query: "没有父母生日信息的客户"
        reason: "这是家庭成员出生日期，应映射到 familyInfo.familyclientbirthday 并组合 familyInfo.familyrelation"


  - id: birthday_month_day
    retrieval_text: >
      生日月日 月日生日 几月几号生日 生日月份 本月生日 下月生日 生日快到了 过生日
      下周有客户过生日吗 下周有哪些客户过生日 哪些客户下周过生日
      农历生日 阴历生日 农历几月 阴历几月
    field: birthdayMd
    operator: RANGE
    value_type: date
    format: "MM-dd"
    notes: "只含月日（不含年），格式MM-dd；本月生日取当月1日至月末；下月生日取下个月1日至月末；下周/下星期/下个星期生日必须取下一个自然周周一至周天，不能理解为从今天开始的未来7天；未来一周/未来7天/接下来一周才取今天至往后顺延6天；未来一个月生日取今天至往后延顺29天；农历/阴历N月生日需将农历月份换算为当前公历年份对应的公历日期范围（农历正月初一为春节，各农历月对应公历日期每年不同，可依据常识估算近似范围，取该农历月初一至月末对应的公历日期）"
    examples:
      - query: "3月15日生日的客户"
        output: {field: birthdayMd, operator: RANGE, value: {min: "03-15", max: "03-15"}}
      - query: "本月生日的客户（当前2026年3月）"
        output: {field: birthdayMd, operator: RANGE, value: {min: "03-01", max: "03-31"}}
      - query: "下个月生日的客户（当前2026年3月）"
        output: {field: birthdayMd, operator: RANGE, value: {min: "04-01", max: "04-30"}}
      - query: "下周有哪些客户过生日（当前2026年3月25号）"
        output: { field: birthdayMd, operator: RANGE, value: { min: "03-30", max: "04-05" } }
      - query: "下周生日的客户张宇（当前2026年3月25号）"
        conditions:
          - { field: birthdayMd, operator: RANGE, value: { min: "03-30", max: "04-05" } }
          - { field: searchClientName, operator: MATCH, value: "张宇" }
      - query: "未来一周的客户（当前2026年4月1号）"
        output: { field: birthdayMd, operator: RANGE, value:  { min: "04-01", max: "04-07" } }
      - query: "未来一个月的客户（当前2026年3月25号）"
        output: { field: birthdayMd, operator: RANGE, value: { min: "03-25", max: "04-25" } }
      - query: "四、五月客户"
        output: { field: birthdayMd, operator: RANGE, value: { min: "04-01", max: "05-31" } }
      - query: "农历五月生日的客户"
        output: { field: birthdayMd, operator: RANGE, value: { min: "06-15", max: "07-14" } }

  - id: birthday_md_gte
    retrieval_text: >
      生日月日 大于 超过 大于等于 及之后 在某日之后生日 在某日及之后生日 以后生日 之后生日
    field: birthdayMd
    operator: GTE
    value_type: date
    format: "MM-dd"
    description: "表示客户生日月日"
    notes: "此字段仅支持GTE操作符，GT语义会被自动转换为GTE并对日期+1天后查询（例如：4月3日以后→GTE 4月4日，4月3日及之后→GTE 4月3日）"
    examples:
      - query: "4月3日以后生日的客户"
        output: {field: birthdayMd, operator: GTE, value: "04-04"}
      - query: "4月3日及之后生日的客户"
        output: {field: birthdayMd, operator: GTE, value: "04-03"}

  - id: birthday_md_lte
    retrieval_text: >
      生日月日 小于 小于等于 及之前 在某日之前生日 在某日及之前生日 之前生日 以前生日
    field: birthdayMd
    operator: LTE
    value_type: date
    format: "MM-dd"
    description: "表示客户生日月日"
    notes: "此字段仅支持LTE操作符，LT语义会被自动转换为LTE并对日期-1天后查询（例如：4月3日之前→LTE 4月2日，4月3日及之前→LTE 4月3日）"
    examples:
      - query: "4月3日之前生日的客户"
        output: {field: birthdayMd, operator: LTE, value: "04-02"}
      - query: "4月3日及之前生日的客户"
        output: {field: birthdayMd, operator: LTE, value: "04-03"}

  # ==================== 客户号 ====================

  - id: customer_id
    retrieval_text: >
      客户号 客户编号 客户ID 客户代码 客户号升序 客户号从小到大 客户号排序 按客户号排列
      客户号 客户编号 客户ID 客户代码 客户号尾号 客户编号后四位
    field: clientNo
    operator: MATCH
    value_type: extract
    description: "表示客户编号：以C开头，或以00开头；前缀之后为11至12位数字或字母。英文字母统一转为大写"
    notes: "本条只处理单个客户号，使用MATCH。完整客户号应先统一转为大写；当查询客户号尾号|尾数|末尾|后x位|后几位|结尾时，必须设置match_mode=suffix。客户号只能是数字或字母，不可能是中文。多个完整客户号应使用customer_id_list知识的CONTAINS。"
    examples:
      - query: "客户号尾号0088（查询客户号尾号必须配置match_mode=suffix）"
        output: {field: clientNo, operator: MATCH, value: "0088", match_mode: suffix}
      - query: "0019***0090"
        output: {field: clientNo, operator: MATCH, value: "0090", match_mode: suffix}
      - query: "大学字母C 数字0101549972"
        output: { field: clientNo, operator: MATCH, value: "C0101549972" }
      - query: "客户号以C开头的客户"
        output: { field: clientNo, operator: MATCH, value: "C", match_mode: "prefix" }
      - query: "客户号后四位0088的客户"
        output: { field: clientNo, operator: MATCH, value: "0088", match_mode: "suffix" }

  - id: customer_id_list
    retrieval_text: >
      多个客户号 批量客户号 一批客户号 客户号列表 客户号清单 查询以下客户号 客户编号逗号分隔清单 请通过如下客户号，客户号找出相对应的客户信息
      多个客户编号 批量客户编号 多个客户ID 多个客户代码 请将以下客户号转化为姓名 请通过如下客户号找出对应客户名字 请通过如下客户号找出对应客户姓名
      客户号逗号分隔 客户号换行分隔 客户号批量查询 搜索以下客户的客户清单 通过客户的编号找出客户姓名 请把以下编号转换为姓名
      找出如下客户号对应姓名 找出客户号对应姓名 通过编号导出
    field: clientNo
    operator: CONTAINS
    value_type: extract
    description: "表示按多个完整客户号批量查询；多个客户号属于同一候选集合"
    notes: "仅当查询中包含至少两个完整客户号时使用CONTAINS，value必须是去重后的客户号数组，并将英文字母统一转为大写。客户号可由英文逗号、中文逗号、顿号、分号、竖线、换行或Tab分隔。不得把多个客户号拆成多个AND条件；单个完整客户号仍使用customer_id的MATCH。"
    examples:
      - query: "C00909900,C080080,C080080808822"
        output: { field: clientNo, operator: CONTAINS, value: ["C00909900", "C080080", "C080080808822"] }
      - query: "找出如下客户号对应的姓名：C00909900,C080080,C080080808822,0056526767, 0012131231"
        output: { field: clientNo, operator: CONTAINS, value: ["C00909900", "C080080", "C080080808822", "0056526767", "0012131231"] }
      - query: "通过如下客户号，找出对应的客户姓名：C00909900\nC080080\n0056526767\n0056526767"
        output: { field: clientNo, operator: CONTAINS, value: ["C00909900", "C080080", "0056526767"] }

  # ==================== 客户价值 ====================

  - id: customer_value_exact
    retrieval_text: >
      客户价值等级 A1 A2 A3 A4 B C D E F A1类客户 A2类客户 A3类客户 A4类客户
      B类客户 C类客户 D类客户 E类客户 F类客户 客户价值为A1 客户价值为A2 客户价值为A3
      客户价值为A4 客户价值为B 客户价值为C 客户价值为D 客户价值为E 客户价值为F
    field: newValueLabel
    operator: MATCH
    value_type: enum
    enum_ref: newValueLabel
    description: "表示用户明确指定的单个客户价值等级；只有原文出现具体等级值时使用。"
    notes: "A1、A2、A3、A4、B、C、D、E、F是单一等级，使用MATCH；裸A、A类、AB类、高价值、多个候选或带以上/以下的等级范围不属于本意图。"
    examples:
      - query: "A2类客户"
        output: { field: newValueLabel, operator: MATCH, value: "A2" }
      - query: "客户价值为B的客户"
        output: { field: newValueLabel, operator: MATCH, value: "B" }
      - query: "B类客户"
        output: { field: newValueLabel, operator: MATCH, value: "B" }
    negative_examples:
      - query: "A类客户"
        reason: "裸A代表A1、A2、A3、A4业务集合，应使用customer_value_group"
      - query: "B类及以上客户"
        reason: "等级范围应使用customer_value_group"

  - id: customer_value_group
    retrieval_text: >
      客户价值 A A类客户 AB类客户 A和B类客户 A类和B类客户 B以上客户 高价值客户 有钱客户 客户高价值 AB类客户 价值a或b 客户价值以上 客户价值及以上 A类以上 A类及以上 B类以上 B类及以上 高价值及以上
      客户价值以下 客户价值及以下 A类以下 A类及以下 B类以下 B类及以下 高价值及以下 A2以下
      优质客户 价值高 高价值客户 按价值 价值从高到低 价值从大到小 客户价值高 价值等级高
    field: newValueLabel
    operator: CONTAINS
    value_type: enum
    show_enum_in_prompt: true
    enum_ordered: true
    description: "表示客户价值等级范围，不表示金额区间；“以上”、“及以上”、“以下”、“及以下”含边界"
    notes: "只处理业务集合、多个候选和等级范围：裸A/A类=A1/A2/A3/A4，A或B/AB类=A1/A2/A3/A4/B；紧凑连续等级（如ABCD）按各字母等级并集解析；高价值/有钱客户=A1/A2/A3/A4/B/C；以上/以下按F<E<D<C<B<A4<A3<A2<A1展开并包含边界。明确的单个完整等级值（如A2、B、B类）使用customer_value_exact的MATCH。"
    examples:
      - query: "A"
        output: { field: newValueLabel, operator: CONTAINS, value: ["A1", "A2", "A3", "A4"] }
      - query: "A类客户"
        output: { field: newValueLabel, operator: CONTAINS, value: ["A1", "A2", "A3", "A4"] }
      - query: "购物中心6公里以内的A类客户"
        output: { field: newValueLabel, operator: CONTAINS, value: ["A1", "A2", "A3", "A4"] }
      - query: "有钱客户"
        output: { field: newValueLabel, operator: CONTAINS, value: ["A1", "A2", "A3", "A4", "B", "C"] }
      - query: "AB类客户"
        output: { field: newValueLabel, operator: CONTAINS, value: ["A1", "A2", "A3", "A4", "B"] }
      - query: "高价值客户"
        output: { field: newValueLabel, operator: CONTAINS, value: [ "A1", "A2", "A3", "A4", "B", "C" ] }
      - query: "B以上的客户"
        output: { field: newValueLabel, operator: CONTAINS, value: ["A1", "A2", "A3", "A4", "B"] }
      - query: "B及以上的客户"
        output: { field: newValueLabel, operator: CONTAINS, value: [ "A1", "A2", "A3", "A4", "B" ] }
      - query: "B类以下客户"
        output: { field: newValueLabel, operator: CONTAINS, value: [ "F", "E", "D", "C", "B" ] }
      - query: "B类及以下客户"
        output: { field: newValueLabel, operator: CONTAINS, value: [ "F", "E", "D", "C", "B" ] }
      - query: "优质客户"
        output: { field: newValueLabel, operator: CONTAINS, value: [ "A1", "A2", "A3", "A4", "B", "C" ] }
    negative_examples:
      - query: "会员等级高的客户"
        reason: "这是寿险VIP等级语义，应映射到 vipType，不是客户价值 newValueLabel"

  # ==================== 客户温度 ====================

  - id: customer_temperature_exact
    retrieval_text: >
      客户温度 高温客户 中温客户 低温客户 冷却客户
      温度 活跃度 客户活跃 意向度 没有联系 联系频繁
    field: clientTemperature
    operator: MATCH
    value_type: enum
    enum_ref: clientTemperature
    description: "表示客户活跃度分层标签，不表示最近联系时间、最后联系日期、联系次数等具体联系记录"
    notes: "根据客户活跃度分类，温度从低到高：冷却<低温<中温<高温；最近半年没有联系→冷却，一般联系频次低或近期没联系→低温，联系频繁或最近有联系→高温。该字段表示活跃度分层，不是最近联系时间/最后联系日期；除“最近半年没有联系”这一明确业务口径外，若查询明确要求联系时间而系统无对应字段，不应映射到此字段"
    examples:
      - query: "高温客户"
        output: { field: clientTemperature, operator: MATCH, value: "高温" }
      - query: "最近没联系的客户"
        output: { field: clientTemperature, operator: MATCH, value: "低温" }
      - query: "最近半年没有联系的客户"
        output: { field: clientTemperature, operator: MATCH, value: "冷却" }
      - query: "最近联系频繁的客户"
        output: { field: clientTemperature, operator: MATCH, value: "高温" }
    negative_examples:
      - query: "最近30天联系过的客户"
        reason: "这是联系时间范围，不是活跃度标签；当前无明确联系时间字段时不能映射到 clientTemperature"
      - query: "最后联系时间是上周的客户"
        reason: "这是最后联系日期，不是客户温度"

  - id: customer_temperature_group
    retrieval_text: >
      中高温客户 中温或高温客户 中高温人群 低温或者中温 中温或者高温 温度以上 温度及以上 中温以上 中温及以上 低温以上 低温及以上 高温及以上
    field: clientTemperature
    operator: CONTAINS
    value_type: enum
    enum_ref: clientTemperature
    enum_ordered: true
    description: "表示客户温度等级范围，不表示联系时间范围；“以上”、“及以上”、“以下”、“及以下”含边界"
    notes: "根据客户活跃度分类，温度从低到高：冷却<低温<中温<高温；“中温以上”和“中温及以上”均包含中温和高温"
    examples:
      - query: "中高温客户"
        output: { field: clientTemperature, operator: CONTAINS, value: ["中温", "高温"] }
      - query: "中温以上客户"
        output: {field: clientTemperature, operator: CONTAINS, value: ["中温", "高温"]}
      - query: "中温及以上客户"
        output: {field: clientTemperature, operator: CONTAINS, value: ["中温", "高温"]}
    negative_examples:
      - query: "最近一个月联系频繁的客户"
        reason: "这是最近联系时间范围，不是客户温度等级范围"

  # ==================== 客群标签 ====================

  - id: customer_segment_tag
    retrieval_text: >
      客群标签 客群 人群标签 客户画像 人群分类
      奋斗青年 都市白领 而立一族 社会中坚 邻退天命 慈爱祖辈 创业新贵 创富一代 荣耀高堂 承富二代 已退小康
    field: clientGroupLabel
    operator: CONTAINS
    value_type: enum
    enum_ref: clientGroupLabel
    description: "表示客户画像分群标签。年龄、资产等组合定义用于增强召回理解，不作为默认自动映射规则。"
    notes: "例如：奋斗青年≈16-30岁且资产较低，创业新贵≈36-50岁且高净值；这些定义仅用于辅助理解，不应在缺少标签语境时直接替代为客群标签。"
    examples:
      - query: "都市白领客户"
        output: {field: clientGroupLabel, operator: CONTAINS, value: ["都市白领"]}
      - query: "创业新贵客户"
        output: {field: clientGroupLabel, operator: CONTAINS, value: ["创业新贵"]}

  # ==================== 寿险VIP ====================

  - id: life_insurance_vip_exact
    retrieval_text: >
      寿险VIP具体等级 黄金V1 黄金V2 黄金V3 铂金V1 铂金V2 原黄金VIP 原铂金VIP
      白银1 白银2 白银3 钻石VIP 金钻VIP 黑钻VIP 客户VIP等级为
    field: vipType
    operator: MATCH
    value_type: enum
    enum_ref: vipType
    description: "表示寿险VIP等级标签，不表示是否持有会员权益的开通时间或其他权益体系等级"
    notes: "只处理明确的单个完整VIP等级，使用MATCH。黄金会员、铂金会员、白银会员是业务等级组，多个候选或带以上/以下的等级范围使用life_insurance_vip_group；裸VIP使用life_insurance_vip_exists。当问句明确出现客户价值、价值等级等语境时，应优先考虑newValueLabel。"
    examples:
      - query: "黑钻VIP客户"
        output: {field: vipType, operator: MATCH, value: "黑钻VIP"}
      - query: "客户VIP等级为黄金V2"
        output: {field: vipType, operator: MATCH, value: "黄金V2"}
    negative_examples:
      - query: "黄金VIP客户"
        reason: "黄金是业务等级组，应使用life_insurance_vip_group"
      - query: "VIP客户"
        reason: "未指定VIP等级，应使用life_insurance_vip_exists"

  - id: life_insurance_vip_group
    retrieval_text: >
      黄金VIP 黄金客户 黄金会员 铂金VIP 铂金客户 铂金会员 白银VIP 白银客户 白银会员
      VIP等级以上 VIP等级及以上 黄金及以上 铂金及以上 白银及以上 多个VIP等级 VIP等级范围
    field: vipType
    operator: CONTAINS
    value_type: enum
    show_enum_in_prompt: true
    enum_ordered: true
    description: "表示寿险VIP业务等级组、多个候选或等级范围。"
    notes: "黄金=黄金V1、黄金V2、黄金V3、原黄金VIP；铂金=铂金V1、铂金V2、原铂金VIP；白银=白银1、白银2、白银3。等级从低到高为白银1<白银2<白银3<黄金V1<黄金V2<黄金V3<原黄金VIP<铂金V1<铂金V2<原铂金VIP<钻石VIP<金钻VIP<黑钻VIP；以上/以下包含边界。"
    examples:
      - query: "黄金VIP客户"
        output: {field: vipType, operator: CONTAINS, value: ["黄金V1", "黄金V2", "黄金V3", "原黄金VIP"]}
      - query: "铂金客户"
        output: {field: vipType, operator: CONTAINS, value: ["铂金V1", "铂金V2", "原铂金VIP"]}
      - query: "客户等级在黄金及以上"
        output: {field: vipType, operator: CONTAINS, value: ["黄金V1", "黄金V2", "黄金V3", "原黄金VIP", "铂金V1", "铂金V2", "原铂金VIP", "钻石VIP", "金钻VIP", "黑钻VIP"]}
    negative_examples:
      - query: "VIP开通时间在2024年的客户"
        reason: "这是开通时间，不是 VIP 等级"
      - query: "客户价值黄金档客户"
        reason: "这里是客户价值语境，应优先映射到 newValueLabel，而不是 vipType"
      - query: "高端康养会员等级高"
        reason: "如果明确是高端康养、臻享家医等权益体系，应优先映射到对应权益字段；但单独说会员等级高通常是 vipType"

  - id: life_insurance_vip_exists
    retrieval_text: >
      寿险VIP客户 寿险VIP 会员客户 VIP客户 VIP
    field: vipType
    operator: EXISTS
    value_type: exists
    description: "表示客户属于任意寿险VIP等级，不要求具体VIP档位"
    examples:
      - query: "VIP"
        output: { field: vipType, operator: EXISTS, value: "" }
      - query: "寿险VIP客户"
        output: { field: vipType, operator: EXISTS, value: "" }

  # ==================== 寿险VIP积分与临界会员 ====================

  - id: pointsBalanceAmt_gt
    retrieval_text: >
      寿险VIP积分余额大于 VIP积分余额超过 会员积分余额高于
      积分大于 积分超过 积分高于
    field: pointsBalanceAmt
    operator: GT
    value_type: numeric
    unit: "积分，万=×10000；未明确单位时按积分原值处理"
    description: "表示寿险VIP积分余额严格大于指定值，不表示保费、现金或其他活动积分"
    notes: "超过/大于/高于使用GT；数值必须换算成积分整数，1万积分=10000。"
    examples:
      - query: "搜积分大于20万的客户"
        output: { field: pointsBalanceAmt, operator: GT, value: 200000 }

  - id: pointsBalanceAmt_gte
    retrieval_text: >
      寿险VIP积分余额以上 VIP积分余额及以上 会员积分余额不少于
      积分以上 积分及以上 积分不低于 积分至少
    field: pointsBalanceAmt
    operator: GTE
    value_type: numeric
    unit: "积分，万=×10000；未明确单位时按积分原值处理"
    description: "表示寿险VIP积分余额大于等于指定值"
    notes: "以上/及以上/不少于/不低于/至少使用GTE。"
    examples:
      - query: "VIP积分余额10万以上的客户"
        output: { field: pointsBalanceAmt, operator: GTE, value: 100000 }

  - id: pointsBalanceAmt_lt
    retrieval_text: >
      寿险VIP积分余额小于 VIP积分余额低于 会员积分余额不足
      积分小于 积分低于 积分不足
    field: pointsBalanceAmt
    operator: LT
    value_type: numeric
    unit: "积分，万=×10000；未明确单位时按积分原值处理"
    description: "表示寿险VIP积分余额严格小于指定值"
    notes: "小于/低于/不足使用LT；以内/不超过/及以下使用LTE。"
    examples:
      - query: "VIP积分余额低于5万的客户"
        output: { field: pointsBalanceAmt, operator: LT, value: 50000 }

  - id: pointsBalanceAmt_lte
    retrieval_text: >
      寿险VIP积分余额以内 VIP积分余额不超过 会员积分余额及以下
      积分以内 积分不超过 积分及以下 积分小于等于
    field: pointsBalanceAmt
    operator: LTE
    value_type: numeric
    unit: "积分，万=×10000；未明确单位时按积分原值处理"
    description: "表示寿险VIP积分余额小于等于指定值"
    notes: "以内/不超过/及以下/小于等于使用LTE。"
    examples:
      - query: "搜索积分30万以内的客户"
        output: { field: pointsBalanceAmt, operator: LTE, value: 300000 }

  - id: pointsBalanceAmt_range
    retrieval_text: >
      寿险VIP积分余额 VIP积分余额 会员积分余额 积分余额
      积分区间 积分范围 积分从多少到多少 积分等于
    field: pointsBalanceAmt
    operator: RANGE
    value_type: numeric
    unit: "积分，万=×10000；未明确单位时按积分原值处理"
    description: "表示寿险VIP积分余额区间或精确积分值"
    examples:
      - query: "VIP积分余额10万到20万的客户"
        output: { field: pointsBalanceAmt, operator: RANGE, value: { min: 100000, max: 200000 } }

  - id: critical_member_exact
    retrieval_text: >
      临界会员 临界会员标签 即将可升级会员 即将升级会员
      快要升级会员 马上可以升级会员 即将升级到某VIP等级
    field: criticalMemberFlag
    operator: MATCH
    value_type: enum
    enum_ref: criticalMemberFlag
    description: "表示客户是否为寿险临界会员，即是否已满足或接近下一VIP等级升级条件"
    notes: "临界会员、即将可升级会员输出是；非临界会员、不是临界会员或标签为否输出否。若原文明确升级目标等级，还必须同时输出criticalMemberGrade对应等级。"
    examples:
      - query: "搜临界会员"
        output: { field: criticalMemberFlag, operator: MATCH, value: "是" }
      - query: "搜即将可升级的会员"
        output: { field: criticalMemberFlag, operator: MATCH, value: "是" }
      - query: "搜非临界会员"
        output: { field: criticalMemberFlag, operator: MATCH, value: "否" }
      - query: "搜即将升级到黄金V2等级的客户"
        output:
          - { field: criticalMemberFlag, operator: MATCH, value: "是" }
          - { field: criticalMemberGrade, operator: MATCH, value: "黄金V2" }

  - id: critical_member_grade_exact
    retrieval_text: >
      临界会员等级 临界会员级别 临界会员档位 即将升级到的等级
      黑钻 钻石 黄金V1 黄金V2 黄金V3 非临界VIP客户
      铂金V1 铂金V2 金钻 白银V2 白银V3
    field: criticalMemberGrade
    operator: MATCH
    value_type: enum
    enum_ref: criticalMemberGrade
    description: "表示寿险临界会员等级或即将升级到的目标等级，不等同于客户当前VIP等级vipType"
    notes: "明确说临界会员等级时使用该字段；即将升级到某等级时与criticalMemberFlag=是组合。黑钻VIP/钻石VIP/金钻VIP口语需归一化为黑钻/钻石/金钻。"
    examples:
      - query: "临界会员等级为黄金V2的客户"
        output: { field: criticalMemberGrade, operator: MATCH, value: "黄金V2" }
      - query: "即将升级到钻石VIP的客户"
        output:
          - { field: criticalMemberFlag, operator: MATCH, value: "是" }
          - { field: criticalMemberGrade, operator: MATCH, value: "钻石" }

  - id: pointsExpiredDate_range
    retrieval_text: >
      会员积分到期时间 寿险VIP积分到期 积分即将过期 积分快过期
      最近一个月积分即将过期 最近多少天积分即将过期 积分下周到期
      最近一周积分即将过期 最近半年积分即将过期 最近一年积分即将过期
      近一周积分将要过期 近半年积分将要过期 近一年积分将要过期
      未来一周积分到期 未来半年积分到期 未来一年积分到期
      积分上周到期 积分上上周到期 积分本周到期 积分下下周到期
      积分上个月到期 积分本月到期 积分下个月到期
      未来多少天积分到期 积分过期日期
    field: pointsExpiredDate
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示寿险会员积分的到期时间范围，不表示积分余额或保单到期时间"
    notes: "时间方向必须结合事件状态判断，不得只按‘最近/近’判断为过去：凡‘最近/近/未来/接下来+时间长度’与‘即将过期/将要过期/快要过期/即将到期’共同描述会员积分时，一律表示从今天开始的未来尚未过期窗口，min=今天，禁止输出今天之前的日期；最近一周=未来连续7天（今天至今天+6天），最近一个月=未来连续30天（今天至今天+29天），最近半年=未来连续180天（今天至今天+179天），最近一年=未来连续365天（今天至今天+364天），最近N天内=未来连续N天。该规则只适用于积分即将到期；‘最近一年买保险、最近半年投保、最近一年有理赔’属于其他已发生事件的过去时间知识，不得迁移到积分即将过期。上上周/上周/本周/下周/下下周按对应自然周周一至周日；上月/本月/下月按对应自然月首日至月末。"
    examples:
      - query: "最近一个月积分即将过期的客户（当前2026-08-20）"
        output: { field: pointsExpiredDate, operator: RANGE, value: { min: "2026-08-20", max: "2026-09-18" } }
      - query: "最近45天天内积分即将过期的客户（当前2026-08-24）"
        output: { field: pointsExpiredDate, operator: RANGE, value: { min: "2026-08-24", max: "2026-10-08" } }
      - query: "最近半年积分即将过期的客户（当前2026-08-24）"
        output: { field: pointsExpiredDate, operator: RANGE, value: { min: "2026-08-24", max: "2027-02-19" } }
      - query: "最近一年积分即将过期的客户（当前2026-08-24）"
        output: { field: pointsExpiredDate, operator: RANGE, value: { min: "2026-08-24", max: "2027-08-23" } }
      - query: "本月会员积分到期的客户（当前2026-08-20）"
        output: { field: pointsExpiredDate, operator: RANGE, value: { min: "2026-08-01", max: "2026-08-31" } }
    negative_examples:
      - query: "最近一年买保险的客户"
        reason: "这是已经发生的投保时间，不是会员积分即将过期，不输出pointsExpiredDate"
      - query: "最近半年有理赔记录的客户"
        reason: "这是已经发生的理赔时间，不是会员积分即将过期，不输出pointsExpiredDate"

  # ==================== 潜客、下一等级与保费缺口 ====================

  - id: qkflag_match
    retrieval_text: >
      潜客 是否潜客 潜在客户 准潜客 非潜客 不是潜客
      全部的平安居家的潜客 所有居家潜客 国医潜在客户 私董准潜客 康养潜客
    field: qkflag
    operator: MATCH
    value_type: enum
    enum_ref: qkflag
    description: "表示未指明具体权益时，客户是否为全局潜客"
    notes: "未指明权益的潜客输出qkflag=是；非潜客、不是潜客输出否。若指明平安居家、御享国医、私董保健医或高端康养，则解析阶段使用对应memberstatus MATCH 潜客，再由系统后处理改写为对应权益存在且qkflag=是。"
    examples:
      - query: "潜客有哪些"
        output: { field: qkflag, operator: MATCH, value: "是" }
      - query: "全部的平安居家的潜客"
        output: { field: pajjMemberGradeInfo.pajjmemberstatus, operator: MATCH, value: "潜客" }
      - query: "全部的国医潜客"
        output: { field: yxgyMemberGradeInfo.yxgymemberstatus, operator: MATCH, value: "潜客" }
      - query: "全部的私董潜客"
        output: { field: sdbjyMemberGradeInfo.sdbjymemberstatus, operator: MATCH, value: "潜客" }
      - query: "全部的康养潜客"
        output: { field: gdkyMemberGradeInfo.gdkymemberstatus, operator: MATCH, value: "潜客" }
     
  - id: pajj_next_member_grade_match
    retrieval_text: >
      平安居家下一等级 居家下一等级
      距离居家V0 V1 V1优享 V2 V2优享还差多少保费
    field: pajjMemberGradeInfo.pajjnextmembergrade
    operator: MATCH
    value_type: enum
    enum_ref: pajjMemberGradeInfo.pajjnextmembergrade
    description: "表示平安居家预计升级或达标的下一会员等级"
    examples:
      - query: "居家V1优享等级还差10万保费的客户"
        output:
          query_logic: AND
          conditions:
            - {field: pajjMemberGradeInfo.pajjnextmembergrade, operator: MATCH, value: "平安居家V1优享"}
            - {field: pajjMemberGradeInfo.pajjtotalpremgap, operator: LTE, value: 10}

  - id: yxgy_next_member_grade_match
    retrieval_text: >
      御享国医下一等级 国医下一等级 距离御享国医还差多少保费
    field: yxgyMemberGradeInfo.yxgynextmembergrade
    operator: MATCH
    value_type: enum
    enum_ref: yxgyMemberGradeInfo.yxgynextmembergrade
    description: "表示御享国医预计升级或达标的下一等级"
    notes: "仅在用户明确查询御享国医下一等级时输出；仅说‘距离御享国医还差N万保费’时只输出总保费缺口，不额外输出下一等级。"
    examples:
      - query: "下一等级是御享国医的客户"
        output: { field: yxgyMemberGradeInfo.yxgynextmembergrade, operator: MATCH, value: "御享国医" }

  - id: sdbyj_next_member_grade_match
    retrieval_text: >
      私董保健康下一等级 私董保健医京华版 繁花版还差多少保费
    field: sdbjyMemberGradeInfo.sdbjynextmembergrade
    operator: MATCH
    value_type: enum
    enum_ref: sdbjyMemberGradeInfo.sdbjynextmembergrade
    description: "表示私董保健康预计升级或达标的下一等级"
    examples:
      - query: "距离私董保健医京华版还差10万保费的客户"
        output:
          query_logic: AND
          conditions:
            - {field: sdbjyMemberGradeInfo.sdbjynextmembergrade, operator: MATCH, value: "京华版"}
            - {field: sdbjyMemberGradeInfo.sdbjytotalpremgap, operator: LTE, value: 10}

  - id: gdky_next_member_grade_match
    retrieval_text: >
      高端康养下一等级
      康养逸享 逸享PLUS 颐享家 臻享V1 臻享V2还差多少保费
    field: gdkyMemberGradeInfo.gdkynextmembergrade
    operator: MATCH
    value_type: enum
    enum_ref: gdkyMemberGradeInfo.gdkynextmembergrade
    description: "表示高端康养预计升级或达标的下一会员等级"
    examples:
      - query: "距离康养逸享PLUS会员还差10万保费的客户"
        output:
          query_logic: AND
          conditions:
            - {field: gdkyMemberGradeInfo.gdkynextmembergrade, operator: MATCH, value: "逸享PLUS会员"}
            - {field: gdkyMemberGradeInfo.gdkytotalpremgap, operator: LTE, value: 10}

  # 保费缺口RAG知识按operator拆分，避免单条知识混合多个边界语义。
  - id: pajj_total_premium_gap_range
    retrieval_text: >
      平安居家1+N保费缺口精确值 等于 正好
      平安居家1+N保费缺口区间 到 至 之间
    field: pajjMemberGradeInfo.pajjtotalpremgap
    operator: RANGE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "平安居家1+N保费缺口精确值或闭区间"
    notes: "仅‘保费缺口为/等于/正好X万’使用精确值min=max；裸‘还差X万’不属于精确值，应使用LTE；指定居家等级时同时输出pajjnextmembergrade。"
    examples:
      - query: "居家V1保费缺口为10万的客户"
        output:
          query_logic: AND
          conditions:
            - {field: pajjMemberGradeInfo.pajjnextmembergrade, operator: MATCH, value: "平安居家V1"}
            - {field: pajjMemberGradeInfo.pajjtotalpremgap, operator: RANGE, value: {min: 10, max: 10}}
      - query: "居家V1保费缺口在5万到10万之间"
        output:
          query_logic: AND
          conditions:
            - {field: pajjMemberGradeInfo.pajjnextmembergrade, operator: MATCH, value: "平安居家V1"}
            - {field: pajjMemberGradeInfo.pajjtotalpremgap, operator: RANGE, value: {min: 5, max: 10}}

  - id: pajj_total_premium_gap_gt
    retrieval_text: >
      平安居家保费缺口大于 超过 高于 多于
    field: pajjMemberGradeInfo.pajjtotalpremgap
    operator: GT
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "平安居家1+N保费缺口严格大于指定值"
    notes: "仅用于不包含边界的大于语义；指定等级时同时输出pajjnextmembergrade。"
    examples:
      - query: "居家V1优享保费缺口超过10万"
        output:
          query_logic: AND
          conditions:
            - {field: pajjMemberGradeInfo.pajjnextmembergrade, operator: MATCH, value: "平安居家V1优享"}
            - {field: pajjMemberGradeInfo.pajjtotalpremgap, operator: GT, value: 10}

  - id: pajj_total_premium_gap_gte
    retrieval_text: >
      平安居家保费缺口大于等于 不少于 不低于 至少 起码 以上
    field: pajjMemberGradeInfo.pajjtotalpremgap
    operator: GTE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "平安居家1+N保费缺口大于等于指定值"
    notes: "包含边界；指定等级时同时输出pajjnextmembergrade。"
    examples:
      - query: "居家V2保费缺口至少10万"
        output:
          query_logic: AND
          conditions:
            - {field: pajjMemberGradeInfo.pajjnextmembergrade, operator: MATCH, value: "平安居家V2"}
            - {field: pajjMemberGradeInfo.pajjtotalpremgap, operator: GTE, value: 10}

  - id: pajj_total_premium_gap_lt
    retrieval_text: >
      平安居家保费缺口小于 低于 少于 不足 不到
    field: pajjMemberGradeInfo.pajjtotalpremgap
    operator: LT
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "平安居家1+N保费缺口严格小于指定值"
    notes: "不包含边界；指定等级时同时输出pajjnextmembergrade。"
    examples:
      - query: "居家V2优享保费缺口不到10万"
        output:
          query_logic: AND
          conditions:
            - {field: pajjMemberGradeInfo.pajjnextmembergrade, operator: MATCH, value: "平安居家V2优享"}
            - {field: pajjMemberGradeInfo.pajjtotalpremgap, operator: LT, value: 10}

  - id: pajj_total_premium_gap_lte
    retrieval_text: >
      平安居家保费缺口小于等于 不超过 不高于 至多 最多 以内 以下
      距离平安居家还差 居家等级还差 仍差 还缺
    field: pajjMemberGradeInfo.pajjtotalpremgap
    operator: LTE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "平安居家1+N保费缺口小于等于指定值"
    notes: "包含边界；裸‘还差/仍差/还缺X万’统一表示保费缺口≤X万；指定等级时同时输出pajjnextmembergrade。"
    examples:
      - query: "居家V0保费缺口10万以内"
        output:
          query_logic: AND
          conditions:
            - {field: pajjMemberGradeInfo.pajjnextmembergrade, operator: MATCH, value: "平安居家V0"}
            - {field: pajjMemberGradeInfo.pajjtotalpremgap, operator: LTE, value: 10}
      - query: "居家V1还差10万保费的客户"
        output:
          query_logic: AND
          conditions:
            - {field: pajjMemberGradeInfo.pajjnextmembergrade, operator: MATCH, value: "平安居家V1"}
            - {field: pajjMemberGradeInfo.pajjtotalpremgap, operator: LTE, value: 10}

  - id: yxgy_total_premium_gap_range
    retrieval_text: >
      御享国医总保费缺口精确值 等于 正好
      御享国医总保费缺口区间 到 至 之间
    field: yxgyMemberGradeInfo.yxgytotalpremgap
    operator: RANGE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "御享国医总保费缺口精确值或闭区间"
    notes: "仅‘保费缺口为/等于/正好X万’使用精确值min=max；裸‘还差X万’不属于精确值，应使用LTE；不额外输出yxgynextmembergrade。"
    examples:
      - query: "御享国医总保费缺口为10万"
        output: { field: yxgyMemberGradeInfo.yxgytotalpremgap, operator: RANGE, value: { min: 10, max: 10 } }
      - query: "御享国医保费缺口在5万至10万之间"
        output: { field: yxgyMemberGradeInfo.yxgytotalpremgap, operator: RANGE, value: { min: 5, max: 10 } }

  - id: yxgy_total_premium_gap_gt
    retrieval_text: >
      御享国医总保费缺口大于 超过 高于 多于
    field: yxgyMemberGradeInfo.yxgytotalpremgap
    operator: GT
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "御享国医总保费缺口严格大于指定值"
    notes: "仅用于不包含边界的大于语义；不额外输出下一等级。"
    examples:
      - query: "御享国医总保费缺口超过10万"
        output: { field: yxgyMemberGradeInfo.yxgytotalpremgap, operator: GT, value: 10 }

  - id: yxgy_total_premium_gap_gte
    retrieval_text: >
      御享国医保费缺口大于等于 不少于 不低于 至少 起码 以上
    field: yxgyMemberGradeInfo.yxgytotalpremgap
    operator: GTE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "御享国医总保费缺口大于等于指定值"
    notes: "包含边界；不额外输出下一等级。"
    examples:
      - query: "御享国医保费缺口不少于10万"
        output: { field: yxgyMemberGradeInfo.yxgytotalpremgap, operator: GTE, value: 10 }

  - id: yxgy_total_premium_gap_lt
    retrieval_text: >
      御享国医保费缺口小于 低于 少于 不足 不到
    field: yxgyMemberGradeInfo.yxgytotalpremgap
    operator: LT
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "御享国医总保费缺口严格小于指定值"
    notes: "不包含边界；不额外输出下一等级。"
    examples:
      - query: "距离御享国医还差不到10万保费"
        output: { field: yxgyMemberGradeInfo.yxgytotalpremgap, operator: LT, value: 10 }

  - id: yxgy_total_premium_gap_lte
    retrieval_text: >
      御享国医保费缺口小于等于 不超过 不高于 至多 最多 以内 以下
      距离御享国医还差 国医仍差 国医还缺
    field: yxgyMemberGradeInfo.yxgytotalpremgap
    operator: LTE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "御享国医总保费缺口小于等于指定值"
    notes: "包含边界；裸‘还差/仍差/还缺X万’统一表示保费缺口≤X万；不额外输出下一等级。"
    examples:
      - query: "御享国医保费缺口10万以内"
        output: { field: yxgyMemberGradeInfo.yxgytotalpremgap, operator: LTE, value: 10 }
      - query: "距离御享国医还差10万保费"
        output: { field: yxgyMemberGradeInfo.yxgytotalpremgap, operator: LTE, value: 10 }

  - id: sdbyj_total_premium_gap_range
    retrieval_text: >
      私董保健康保费缺口精确值 京华版 繁花版 等于 正好
      私董保健康保费缺口区间 到 至 之间
    field: sdbjyMemberGradeInfo.sdbjytotalpremgap
    operator: RANGE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "私董保健康总保费缺口精确值或闭区间"
    notes: "仅‘保费缺口为/等于/正好X万’使用精确值min=max；裸‘还差X万’不属于精确值，应使用LTE；同时输出sdbyjnextmembergrade。"
    examples:
      - query: "私董繁花版保费缺口为10万"
        output:
          query_logic: AND
          conditions:
            - {field: sdbjyMemberGradeInfo.sdbjynextmembergrade, operator: MATCH, value: "繁花版"}
            - {field: sdbjyMemberGradeInfo.sdbjytotalpremgap, operator: RANGE, value: {min: 10, max: 10}}
      - query: "私董京华版保费缺口在5万至10万之间"
        output:
          query_logic: AND
          conditions:
            - {field: sdbjyMemberGradeInfo.sdbjynextmembergrade, operator: MATCH, value: "京华版"}
            - {field: sdbjyMemberGradeInfo.sdbjytotalpremgap, operator: RANGE, value: {min: 5, max: 10}}

  - id: sdbyj_total_premium_gap_gt
    retrieval_text: >
      私董保健康 京华版 繁花版 保费缺口大于 超过 高于 多于
    field: sdbjyMemberGradeInfo.sdbjytotalpremgap
    operator: GT
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "私董保健康总保费缺口严格大于指定值"
    notes: "不包含边界；同时输出sdbyjnextmembergrade。"
    examples:
      - query: "私董京华版保费缺口超过10万"
        output:
          query_logic: AND
          conditions:
            - {field: sdbjyMemberGradeInfo.sdbjynextmembergrade, operator: MATCH, value: "京华版"}
            - {field: sdbjyMemberGradeInfo.sdbjytotalpremgap, operator: GT, value: 10}

  - id: sdbyj_total_premium_gap_gte
    retrieval_text: >
      私董保健康 京华版 繁花版 保费缺口大于等于 不少于 不低于 至少 以上
    field: sdbjyMemberGradeInfo.sdbjytotalpremgap
    operator: GTE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "私董保健康总保费缺口大于等于指定值"
    notes: "包含边界；同时输出sdbyjnextmembergrade。"
    examples:
      - query: "私董繁花版保费缺口至少10万"
        output:
          query_logic: AND
          conditions:
            - {field: sdbjyMemberGradeInfo.sdbjynextmembergrade, operator: MATCH, value: "繁花版"}
            - {field: sdbjyMemberGradeInfo.sdbjytotalpremgap, operator: GTE, value: 10}

  - id: sdbyj_total_premium_gap_lt
    retrieval_text: >
      私董保健康 京华版 繁花版 保费缺口小于 低于 少于 不足 不到
    field: sdbjyMemberGradeInfo.sdbjytotalpremgap
    operator: LT
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "私董保健康总保费缺口严格小于指定值"
    notes: "不包含边界；同时输出sdbyjnextmembergrade。"
    examples:
      - query: "私董京华版保费缺口不到10万"
        output:
          query_logic: AND
          conditions:
            - {field: sdbjyMemberGradeInfo.sdbjynextmembergrade, operator: MATCH, value: "京华版"}
            - {field: sdbjyMemberGradeInfo.sdbjytotalpremgap, operator: LT, value: 10}

  - id: sdbyj_total_premium_gap_lte
    retrieval_text: >
      私董保健康 京华版 繁花版 保费缺口小于等于 不超过 不高于 至多 最多 以内 以下
      距离私董保健医还差 私董仍差 私董还缺
    field: sdbjyMemberGradeInfo.sdbjytotalpremgap
    operator: LTE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "私董保健康总保费缺口小于等于指定值"
    notes: "包含边界；裸‘还差/仍差/还缺X万’统一表示保费缺口≤X万；同时输出sdbyjnextmembergrade。"
    examples:
      - query: "私董繁花版保费缺口不超过10万"
        output:
          query_logic: AND
          conditions:
            - {field: sdbjyMemberGradeInfo.sdbjynextmembergrade, operator: MATCH, value: "繁花版"}
            - {field: sdbjyMemberGradeInfo.sdbjytotalpremgap, operator: LTE, value: 10}
      - query: "私董京华版还差10万保费"
        output:
          query_logic: AND
          conditions:
            - {field: sdbjyMemberGradeInfo.sdbjynextmembergrade, operator: MATCH, value: "京华版"}
            - {field: sdbjyMemberGradeInfo.sdbjytotalpremgap, operator: LTE, value: 10}

  - id: gdky_total_premium_gap_range
    retrieval_text: >
      高端康养新老保单保费缺口精确值 等于 正好
      高端康养新老保单保费缺口区间 到 至 之间
    field: gdkyMemberGradeInfo.gdkytotalpremgap
    operator: RANGE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "高端康养新老保单保费缺口精确值或闭区间"
    notes: "仅‘保费缺口为/等于/正好X万’使用精确值min=max；裸‘还差X万’不属于精确值，应使用LTE；指定等级时同时输出gdkynextmembergrade。"
    examples:
      - query: "康养臻享V2保费缺口为10万"
        output:
          query_logic: AND
          conditions:
            - {field: gdkyMemberGradeInfo.gdkynextmembergrade, operator: MATCH, value: "臻享V2会员"}
            - {field: gdkyMemberGradeInfo.gdkytotalpremgap, operator: RANGE, value: {min: 10, max: 10}}
      - query: "康养逸享保费缺口在5万到10万之间"
        output:
          query_logic: AND
          conditions:
            - {field: gdkyMemberGradeInfo.gdkynextmembergrade, operator: MATCH, value: "逸享会员"}
            - {field: gdkyMemberGradeInfo.gdkytotalpremgap, operator: RANGE, value: {min: 5, max: 10}}

  - id: gdky_total_premium_gap_gt
    retrieval_text: >
      高端康养保费缺口大于 超过 高于 多于
    field: gdkyMemberGradeInfo.gdkytotalpremgap
    operator: GT
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "高端康养新老保单保费缺口严格大于指定值"
    notes: "不包含边界；指定等级时同时输出gdkynextmembergrade。"
    examples:
      - query: "康养逸享PLUS保费缺口超过10万"
        output:
          query_logic: AND
          conditions:
            - {field: gdkyMemberGradeInfo.gdkynextmembergrade, operator: MATCH, value: "逸享PLUS会员"}
            - {field: gdkyMemberGradeInfo.gdkytotalpremgap, operator: GT, value: 10}

  - id: gdky_total_premium_gap_gte
    retrieval_text: >
      高端康养保费缺口大于等于 不少于 不低于 至少 以上
    field: gdkyMemberGradeInfo.gdkytotalpremgap
    operator: GTE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "高端康养新老保单保费缺口大于等于指定值"
    notes: "包含边界；指定等级时同时输出gdkynextmembergrade。"
    examples:
      - query: "康养颐享家保费缺口至少10万"
        output:
          query_logic: AND
          conditions:
            - {field: gdkyMemberGradeInfo.gdkynextmembergrade, operator: MATCH, value: "颐享家会员"}
            - {field: gdkyMemberGradeInfo.gdkytotalpremgap, operator: GTE, value: 10}

  - id: gdky_total_premium_gap_lt
    retrieval_text: >
      高端康养保费缺口小于 低于 少于 不足 不到
    field: gdkyMemberGradeInfo.gdkytotalpremgap
    operator: LT
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "高端康养新老保单保费缺口严格小于指定值"
    notes: "不包含边界；指定等级时同时输出gdkynextmembergrade。"
    examples:
      - query: "康养臻享V1保费缺口不到10万"
        output:
          query_logic: AND
          conditions:
            - {field: gdkyMemberGradeInfo.gdkynextmembergrade, operator: MATCH, value: "臻享V1会员"}
            - {field: gdkyMemberGradeInfo.gdkytotalpremgap, operator: LT, value: 10}

  - id: gdky_total_premium_gap_lte
    retrieval_text: >
      高端康养保费缺口小于等于 不超过 不高于 至多 最多 以内 以下
      距离高端康养还差 康养会员还差 仍差 还缺
    field: gdkyMemberGradeInfo.gdkytotalpremgap
    operator: LTE
    value_type: numeric
    unit: "万；10万输出10，不乘10000"
    description: "高端康养新老保单保费缺口小于等于指定值"
    notes: "包含边界；裸‘还差/仍差/还缺X万’统一表示保费缺口≤X万；指定等级时同时输出gdkynextmembergrade。"
    examples:
      - query: "康养臻享V2保费缺口10万以内"
        output:
          query_logic: AND
          conditions:
            - {field: gdkyMemberGradeInfo.gdkynextmembergrade, operator: MATCH, value: "臻享V2会员"}
            - {field: gdkyMemberGradeInfo.gdkytotalpremgap, operator: LTE, value: 10}
      - query: "康养臻享V2还差10万保费"
        output:
          query_logic: AND
          conditions:
            - {field: gdkyMemberGradeInfo.gdkynextmembergrade, operator: MATCH, value: "臻享V2会员"}
            - {field: gdkyMemberGradeInfo.gdkytotalpremgap, operator: LTE, value: 10}

  # ==================== 孤儿单类型 ====================

  - id: stock_customer_type
    retrieval_text: >
      孤儿单 存续单 在职客户 存续单客户 孤儿客户 非纯存续单客户 非纯存续单 非纯孤儿单
    field: orphanType
    operator: MATCH
    value_type: enum
    enum_ref: orphanType
    notes: "当前口径：孤儿单=在职有效客户；有存续单=纯存续单客户；非存续单=非纯存续单客户；非纯孤儿单=非纯存续单客户。"
    examples:
      - query: "孤儿单客户"
        output: {field: orphanType, operator: MATCH, value: ["在职有效客户"]}
      - query: "在职有效客户"
        output: {field: orphanType, operator: MATCH, value: ["在职有效客户"]}
      - query: "有存续单的客户"
        output: { field: orphanType, operator: MATCH, value: [ "纯存续单客户" ] }
      - query: "非纯孤儿单"
        output: { field: orphanType, operator: MATCH, value: [ "非纯存续单客户" ] }

  # ==================== 保单托管 ====================

  - id: trusteeship_flag
    retrieval_text: >
      保单托管 是否托管 已托管 未托管 托管客户
    field: trusteeshipFlag
    operator: CONTAINS
    value_type: enum
    enum_ref: trusteeshipFlag
    description: "表示保单是否有托管，是-有托管、否-未托管"
    examples:
      - query: "有保单托管的客户"
        output: {field: trusteeshipFlag, operator: CONTAINS, value: ["是"]}
      - query: "未托管的客户"
        output: {field: trusteeshipFlag, operator: CONTAINS, value: ["否"]}
      - query: "还没有保单托管的客户"
        output: {field: trusteeshipFlag, operator: CONTAINS, value: ["否"]}

  # ==================== 共享给我的客户 ====================

  - id: only_share_client_flag
    is_supported: false
    retrieval_text: >
      成功共享给我的客户 共享给我的客户 共享客户 分享给我的客户 分享客户 共享给我的  分享给我的 共享  分享
      客户成功授权且30天未面访回收 授权成功后30天没有面访被回收
      完成授权后满30天未面访的回收客户 30天未面访回收的已授权客户
      授权共享客户 面访超期回收客户
    field: onlyShareClientFlag
    operator: MATCH
    value_type: enum
    enum_ref: onlyShareClientFlag
    description: "表示客户已成功授权，并在授权后30天内未完成面访而触发回收、共享给当前用户；该字段是后端组合业务标签，只有 Y，没有 N。"
    notes: "“共享客户”“成功共享给我的客户”是该组合口径的业务简称。显式自然语言必须同时包含授权成功和30天未面访回收语义；仅授权成功、仅30天未面访、保单托管授权、未共享以及当前用户分享给别人的客户均不映射为该字段。"
    examples:
      - query: "成功共享给我的客户"
        output: {field: onlyShareClientFlag, operator: MATCH, value: "Y"}
      - query: "分享客户"
        output: {field: onlyShareClientFlag, operator: MATCH, value: "Y"}
      - query: "客户成功授权且30天未面访回收的客户"
        output: {field: onlyShareClientFlag, operator: MATCH, value: "Y"}
      - query: "完成授权后满30天没有面访被回收的客户"
        output: {field: onlyShareClientFlag, operator: MATCH, value: "Y"}
    negative_examples:
      - "仅查询授权成功的客户"
      - "30天没有面访的客户"
      - "完成保单托管授权的客户"
      - "我分享给其他人的客户"

  # ==================== 婚姻状况 ====================

  - id: marital_status
    retrieval_text: >
      婚姻状况 婚姻 已婚 未婚 离婚 丧偶 结婚 已结婚
    field: mariSts
    operator: MATCH
    value_type: enum
    enum_ref: mariSts
    notes: "表示用户明确指定的单个婚姻状态；结婚/已结婚归一为已婚。单身、单亲、多个候选不属于本意图。"
    examples:
      - query: "已婚客户"
        output: {field: mariSts, operator: MATCH, value: "已婚"}
      - query: "离婚客户"
        output: {field: mariSts, operator: MATCH, value: "离婚"}

  - id: marital_status_group
    retrieval_text: >
      单身客户 单身人士 单亲家庭 多个婚姻状态 婚姻状态包含 未婚或离婚
    field: mariSts
    operator: CONTAINS
    value_type: enum
    show_enum_in_prompt: true
    notes: "只处理业务状态组或多个候选：单身=未婚、离婚；单亲=离婚、丧偶、未婚。明确的已婚、未婚、离婚、丧偶使用marital_status的MATCH。"
    examples:
      - query: "单身客户"
        output: {field: mariSts, operator: CONTAINS, value: ["未婚", "离婚"]}
      - query: "单亲家庭"
        output:
          query_logic: AND
          conditions:
            - { field: mariSts, operator: CONTAINS, value: ["离婚", "丧偶", "未婚"] }
            - { field: familyInfo.familyrelation, operator: MATCH, value: "子女" }


  # ==================== 职业 ====================

  - id: occupation
    retrieval_text: >
      职业 从事 做什么工作 工作性质 行业 干什么的
      老师 医生 护士 律师 程序员 企业家 工程师
      公务员 个体户 会计 销售 教授 金融 自由职业
      做生意 上班族 体制内 医疗行业 教育行业
    field: profName
    operator: CONTAINS
    value_type: infer
    enum_ref: profName
    show_enum_in_prompt: false
    enum_candidate_limit_in_prompt: 5
    description: "表示客户本人的职业或从业类型枚举，不表示任职单位、公司、企业、机构或地址名称。"
    notes: "只有原文出现职业、从事、工作类型，或老师、医生、工程师等明确职业语义时才使用本字段。单位名称/公司名称/企业名称/机构名称后的专有名称不能映射为 profName。口语推断：做生意→个体户，体制内→公务员，金融→金融从业者，自由职业→自由职业者。"
    examples:
      - query: "做生意的客户"
        output: {field: profName, operator: CONTAINS, value: ["个体户"]}
      - query: "体制内客户"
        output: {field: profName, operator: CONTAINS, value: ["公务员"]}
      - query: "老师或医生的客户"
        output: { field: profName, operator: CONTAINS, value: [ "老师", "医生" ] }
    negative_examples:
      - query: "单位名称为远山工程咨询院的客户"
        reason: "远山工程咨询院是单位或机构名称，不是客户职业，不能映射到 profName"
      - query: "公司名称为启航教育集团的客户"
        reason: "启航教育集团是公司名称，不是职业枚举"
      - query: "企业名字叫星海工程设计院的客户"
        reason: "企业专有名称不是客户职业"

  # ==================== 证件信息 ====================

  - id: id_type
    retrieval_text: >
      证件类型 身份证 护照 军人证 户口本 出生证 港澳台证 外国人居留证
    field: idType
    operator: CONTAINS
    value_type: enum
    enum_ref: idType
    description: "表示客户证件类型枚举，如身份证、护照、户口本等，不表示证件号码或证件有效期。"
    examples:
      - query: "持有护照的客户"
        output: {field: idType, operator: CONTAINS, value: ["护照"]}
      - query: "证件为身份证或户口本的客户"
        output: { field: idType, operator: CONTAINS, value: [ "身份证", "户口本" ] }

  - id: id_number
    retrieval_text: >
      证件号 身份证号 证件号码 身份证号码
    field: idNo
    operator: MATCH
    value_type: extract
    description: "表示客户证件号码或身份证号文本匹配，不表示证件类型、证件有效期或出生日期。"
    notes: "裸证件号可使用 MATCH；如果用户问证件类型，应映射到 idType；问证件到期/有效期，应映射到 idValidDate。"
    examples:
      - query: "身份证号以320开头的客户"
        output: {field: idNo, operator: MATCH, value: "320", match_mode: "prefix"}
      - query: "身份证号后四位0088的客户"
        output: {field: idNo, operator: MATCH, value: "0088", match_mode: "suffix"}

  - id: id_valid_date_range
    retrieval_text: >
      证件到期 证件有效期 证件即将到期 证件到期时间 身份证到期 证件一周内到期 证件x天内到期 还有x天证件才到期
    field: idValidDate
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示证件有效期截止时间，不表示证件签发日期、办证日期、出生日期"
    notes: "无具体年月时按自然时间范围展开；即将到期、近期到期可理解为从当前日期到未来若干天"
    examples:
      - query: "证件2025年到期的客户"
        output: {field: idValidDate, operator: RANGE, value: {min: "2025-01-01 00:00:00", max: "2025-12-31 00:00:00"}}
      - query: "身份证有效期快到期的客户（当前2026-03-23）"
        output: {field: idValidDate, operator: RANGE, value: {min: "2026-03-24 00:00:00", max: "2026-04-24 00:00:00"}}
      - query: "身份证下周即将过期的客户（当前时间2026-05-12）"
        conditions:
          - { field: idType, operator: MATCH, value: "身份证" }
          - { field: idValidDate, operator: RANGE, value: {min: "2026-05-18 00:00:00", max: "2026-05-24 00:00:00"} }
    negative_examples:
      - query: "身份证是2020年办理的客户"
        reason: "这是办证日期，不是证件有效期截止时间"
      - query: "身份证签发日期在2021年的客户"
        reason: "签发日期与 idValidDate 不是同一字段"

  - id: id_valid_date_gt
    retrieval_text: >
      证件到期 证件到期日在某日之后 证件有效期大于 证件有效期晚于
    field: idValidDate
    operator: GT
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示证件有效期截止时间晚于某个日期（不含等于）"
    examples:
      - query: "证件有效期在2026年之后（不含2026年）的客户"
        output: {field: idValidDate, operator: GT, value: "2026-12-31 23:59:59"}

  - id: id_valid_date_gte
    retrieval_text: >
      证件到期 证件到期日在某日及之后 证件有效期大于等于 证件有效期晚于或等于 身份证到期
    field: idValidDate
    operator: GTE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示证件有效期截止时间晚于或等于某个日期"
    examples:
      - query: "证件有效期在2026年及之后的客户"
        output: {field: idValidDate, operator: GTE, value: "2026-01-01 00:00:00"}
      - query: "证件有效期在2026年之后的客户"
        output: {field: idValidDate, operator: GTE, value: "2026-01-01 00:00:00"}

  - id: id_valid_date_lt
    retrieval_text: >
      证件到期 证件到期日在某日之前 证件有效期小于 证件有效期早于
    field: idValidDate
    operator: LT
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示证件有效期截止时间早于某个日期（不含等于）"
    examples:
      - query: "证件在2025年底前到期（不含2025年底）的客户"
        output: {field: idValidDate, operator: LT, value: "2026-01-01 00:00:00"}

  - id: id_valid_date_lte
    retrieval_text: >
      证件到期 证件到期日在某日及之前 证件有效期小于等于 证件有效期早于或等于 身份证过期 证件过期
    field: idValidDate
    operator: LTE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示证件有效期截止时间早于或等于某个日期"
    examples:
      - query: "证件在2025年底及之前到期的客户"
        output: {field: idValidDate, operator: LTE, value: "2025-12-31 00:00:00"}
      - query: "证件在2025年底前到期的客户"
        output: {field: idValidDate, operator: LTE, value: "2025-12-31 00:00:00"}
      - query: "身份证过期的客户（当前时间为2026-04-27）"
        output: { field: idValidDate, operator: LTE, value: "2026-04-26 00:00:00" }

  - id: asset_status_exact
    retrieval_text: >
      资产状况为有房有车 资产状况为无房无车 有车无房 无车有房
      同时有房有车 既有房又有车 明确房车组合
    field: assetsCondition
    operator: MATCH
    value_type: enum
    description: "表示用户明确指定的单个完整资产组合状态。"
    notes: "有车无房归一为有车；无车有房归一为有房；有车有房归一为有房有车；无车无房归一为无房无车。泛化只说有车或有房时不是精确组合，应使用asset_status业务集合。"
    examples:
      - query: "有车有房的客户"
        output: {field: assetsCondition, operator: MATCH, value: "有房有车"}
      - query: "无车无房的客户"
        output: {field: assetsCondition, operator: MATCH, value: "无房无车"}
      - query: "有车无房的客户"
        output: {field: assetsCondition, operator: MATCH, value: "有车"}

  - id: asset_status
    retrieval_text: >
      资产状况 房车情况 有房 有车 泛化有房 泛化有车
    field: assetsCondition
    operator: CONTAINS
    value_type: enum
    enum_ref: assetsCondition
    show_enum_in_prompt: true
    description: "表示客户资产状况标签。"
    notes: "只处理未排除另一类资产的泛化查询：有车=有车、有房有车；有房=有房、有房有车。明确有车有房、无房无车、有车无房、无车有房属于单一完整组合，使用asset_status_exact的MATCH。"
    examples:
      - query: "有车的客户"
        output: {field: assetsCondition, operator: CONTAINS, value: ["有车", "有房有车"]}
      - query: "有房的客户"
        output: {field: assetsCondition, operator: CONTAINS, value: ["有房", "有房有车"]}

  # ==================== 寿险产品 ====================

  - id: life_insurance_product_million_medical
    retrieval_text: >
      百万医疗 百万医疗产品 百万任我行 倍享百万 百万随行
      百万任我行17 百万任我行18 百万任我行22 百万任我行23 百万任我行25
    field: polNoInfo.plancodeinfo.abbrname
    operator: CONTAINS
    value_type: enum
    enum_ref: millionMedicalProducts
    show_enum_in_prompt: true
    description: "表示百万医疗业务词对应的一组固定产品简称；输出值应限制在 millionMedicalProducts 枚举配置内。"
    examples:
      - query: "百万医疗的客户"
        output: {field: polNoInfo.plancodeinfo.abbrname, operator: CONTAINS, value: ["百万任我行", "百万任我行17", "百万任我行18", "百万任我行22", "百万任我行23", "百万任我行25", "倍享百万", "百万随行"]}
    negative_examples:
      - query: "医疗险的客户"
        reason: "这是险种大类语义，应优先映射到 pCategorys=医疗保险，不是百万医疗产品集合"

  - id: life_insurance_product_million_medical_not_contains
    retrieval_text: >
      未配置百万医疗 未买百万医疗产品 没买百万任我行 没有倍享百万 没买百万随行
      没有百万任我行17 没配置百万任我行18 未配置百万任我行22 未买百万任我行23 未有百万任我行25
    field: polNoInfo.plancodeinfo.abbrname
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: millionMedicalProducts
    show_enum_in_prompt: true
    description: "表示百万医疗业务词对应的一组固定产品简称；输出值应限制在 millionMedicalProducts 枚举配置内。"
    examples:
      - query: "未配置百万医疗的客户"
        output: { field: polNoInfo.plancodeinfo.abbrname, operator: NOT_CONTAINS, value: [ "百万任我行", "百万任我行17", "百万任我行18", "百万任我行22", "百万任我行23", "百万任我行25", "倍享百万", "百万随行" ] }
    negative_examples:
      - query: "医疗险的客户"
        reason: "这是险种大类语义，应优先映射到 pCategorys=医疗保险，不是百万医疗产品集合"

  - id: life_insurance_product_tax_preferred
    retrieval_text: >
      税优产品 税优养老产品 税优养老 智盈倍护 盛世优享 盛世优享分红 安颐尊享 颐享延年 颐享延年分红 金越养老年金分红
      智盈倍护23 盛世优享24 税优养老25
    field: polNoInfo.plancodeinfo.abbrname
    operator: CONTAINS
    value_type: enum
    enum_ref: taxPreferredPensionProducts
    show_enum_in_prompt: true
    description: "表示税优产品/税优养老产品业务词对应的一组固定产品简称；输出值应限制在 taxPreferredPensionProducts 枚举配置内。不表示是否配置养老保险。"
    examples:
      - query: "买了税优产品的客户"
        output: {field: polNoInfo.plancodeinfo.abbrname, operator: CONTAINS, value: ["税优养老", "智盈倍护", "智盈倍护25", "智盈倍护26", "盛世优享", "盛世优享传统", "盛世优享红26", "盛世优享26", "安颐尊享", "颐享延年", "颐享延年23", "颐享延年24", "颐享延年25", "颐享延年26", "颐享延年分红", "颐享延年加护", "金越养老年金（分红）"]}

  - id: life_insurance_product_tax_preferred_not_contains
    retrieval_text: >
      未配置税优产品 没有税优养老产品 没买税优养老 没配置智盈倍护 未有盛世优享 没有盛世优享分红 没买安颐尊享 没有颐享延年 未配置颐享延年分红 未买金越养老年金分红
      未配置智盈倍护23 未买盛世优享24 没有税优养老25
    field: polNoInfo.plancodeinfo.abbrname
    operator: NOT_CONTAINS
    value_type: enum
    show_enum_in_prompt: false
    description: "表示税优产品/税优养老产品业务词对应的一组固定产品简称；输出值应限制在 taxPreferredPensionProducts 枚举配置内。"
    examples:
      - query: "没买税优产品的客户"
        output: { field: polNoInfo.plancodeinfo.abbrname, operator: NOT_CONTAINS, value: [ "税优养老", "智盈倍护", "智盈倍护25", "智盈倍护26", "盛世优享", "盛世优享传统", "盛世优享红26", "盛世优享26", "安颐尊享", "颐享延年", "颐享延年23", "颐享延年24", "颐享延年25", "颐享延年26", "颐享延年分红", "颐享延年加护", "金越养老年金（分红）" ] }

#  - id: life_insurance_product
#    retrieval_text: >
#      寿险产品 持有寿险 寿险产品代码 生财宝 智能星 金利多 平安永福 平安康泰 盛世金越
#    field: planAbbrNames
#    operator: CONTAINS
#    value_type: enum
#    enum_ref: planAbbrNames
#    show_enum_in_prompt: false
#    enum_candidate_limit_in_prompt: 2
#    examples:
#      - query: "买了e生保的客户"
#        output: {field: planAbbrNames, operator: CONTAINS, value: ["e生保"]}

#  - id: life_insurance_product_exists
#    retrieval_text: >
#      寿险客户 有寿险的客户 买过寿险的客户 购买过寿险的客户
#      持有寿险产品 寿险保单客户 寿险名单
#    field: planAbbrNames
#    operator: EXISTS
#    value_type: exists
#    description: "表示客户持有任意寿险产品，不要求具体寿险产品名，仅表示寿险保单存在，不能表示持有某一款寿险产品"
#    show_enum_in_prompt: false
#    enum_candidate_limit_in_prompt: 5
#    examples:
#      - query: "寿险客户"
#        output: {field: planAbbrNames, operator: EXISTS, value: ""}
#      - query: "买过寿险的客户"
#        output: {field: planAbbrNames, operator: EXISTS, value: ""}
#    negative_examples:
#      - query: "买了保险的客户"
#        output: "是否有买保险需要映射到isBuyInsurance，该字段仅表示是否有买“寿险”产品"

#  - id: life_insurance_product_not_exists
#    retrieval_text: >
#      没买寿险 没有寿险 没买寿险产品 没有寿险产品
#      不是寿险客户 无寿险客户 没有寿险保单
#    field: planAbbrNames
#    operator: NOT_EXISTS
#    value_type: exists
#    description: "表示客户未持有任何寿险产品，不表示车险/非车险，不表示寿险保单到期时间为空，仅表示寿险保单不存在，不能表示没有买某一款寿险产品"
#    show_enum_in_prompt: false
#    enum_candidate_limit_in_prompt: 2
#    examples:
#      - query: "不是寿险客户"
#        output: {field: planAbbrNames, operator: NOT_EXISTS, value: ""}
#      - query: "没有寿险保单的客户"
#        output: {field: planAbbrNames, operator: NOT_EXISTS, value: ""}
#    negative_examples:
#      - query: "没买保险的客户"
#        output: "是否有买保险需要映射到isBuyInsurance，该字段仅表示是否有买“寿险”产品"

  # ==================== 持有险种类型 ====================

  - id: held_product_type
    retrieval_text: >
      险种类型 分红型 普通型 投连型 万能型 持有险种
      投资连结 投资型保险
    field: pTypes
    operator: MATCH
    value_type: enum
    enum_ref: pTypes
    description: "表示客户持有的保险类型枚举值，不表示是否存在任意保险"
    examples:
      - query: "持有分红型保险的客户"
        output: {field: pTypes, operator: MATCH, value: "分红型"}

  - id: held_product_type_group
    retrieval_text: >
      多个险种类型 多种险种类型 分红型或普通型 分红型和普通型 投连型或万能型
      险种类型包含 险种类型多个候选
    field: pTypes
    operator: CONTAINS
    value_type: enum
    description: "表示用户明确指定多个持有险种类型候选，不表示单一险种类型或是否存在任意保险"
    examples:
      - query: "买了分红险或普通险的客户"
        output: { field: pTypes, operator: CONTAINS, value: ["分红型", "普通型"] }

  - id: held_product_type_not_contains
    retrieval_text: >
      没有分红型保险 没有万能型保险 不含投连型保险 未持有普通型保险
    field: pTypes
    operator: NOT_CONTAINS
    value_type: enum
    description: "表示客户未持有某类保险类型，不表示字段为空"
    examples:
      - query: "没有分红型保险的客户"
        output: { field: pTypes, operator: NOT_CONTAINS, value: [ "分红型" ] }
      - query: "未持有万能型保险的客户"
        output: { field: pTypes, operator: NOT_CONTAINS, value: [ "万能型" ] }

  # ==================== 持有险种大类 ====================

  - id: held_product_category
    retrieval_text: >
      险种大类 保险大类 定期寿险 护理保险 疾病保险
      医疗保险 意外伤害保险 终身寿险
      医疗险 重疾险 重大疾病 平安重大疾病 意外险 医疗产品
      买过重大疾病 购买过平安重大疾病 投保过重大疾病
    field: pCategorys
    operator: MATCH
    value_type: enum
    enum_ref: pCategorys
    description: "表示客户持有一个明确的险种类别，如医疗保险、疾病保险、意外伤害保险、定期寿险、终身寿险等，不表示具体产品名称。定期寿险、终身寿险不等于寿险。"
    notes: "单一险种大类使用MATCH；医疗险/重疾险等口语应归到险种大类。购买/持有/投保语境中的泛化‘重大疾病’或‘平安重大疾病’，未出现具体产品型号、版本或完整产品名称时，表示疾病保险大类；不得仅因‘重大疾病’也存在于产品简称或理赔险种枚举中就改用其他字段。只有明确具体产品简称或产品全称时才映射到 polNoInfo.plancodeinfo.abbrname 或 polNoInfo.plancodeinfo.planfullname。原文没有理赔、获赔、赔付等动作时不得使用理赔险种字段。末尾无法解释的字母、数字或乱码视为噪声，不得据此改变已明确的业务语义。‘医疗意向/意向医疗/医疗潜客’是尚未持有医疗保险的业务缺口口径，不表示已持有医疗保险，也不表示任一权益服务线会员状态。"
    examples:
      - query: "购买了医疗产品的客户"
        output: {field: pCategorys, operator: MATCH, value: "医疗保险"}
      - query: "购买了定寿的客户"
        output: { field: pCategorys, operator: MATCH, value: "定期寿险" }
      - query: "购买过平安重大疾病的客户"
        output: {field: pCategorys, operator: MATCH, value: "疾病保险"}
      - query: "买过重大疾病的客户"
        output: {field: pCategorys, operator: MATCH, value: "疾病保险"}
    negative_examples:
      - query: "购买过寿险的客户"
        reason: "定期寿险或终身寿险均不等于寿险，应映射到 polNoInfo.plancodeinfo.plantypedesc"
      - query: "购买过少儿重大疾病的客户"
        reason: "少儿重大疾病带有产品限定词，应继续识别具体投保产品，不能把其中的子串‘重大疾病’泛化为疾病保险大类"

  - id: held_product_category_group
    retrieval_text: >
      多个险种大类 多种保险大类 重疾险和医疗险 疾病保险和医疗保险
      医疗险或意外险 疾病保险或医疗保险 买过多种寿险险种
    field: pCategorys
    operator: CONTAINS
    value_type: enum
    enum_ref: pCategorys
    description: "表示客户持有原文明示的多个寿险险种大类。"
    notes: "只有原文明示两个及以上险种大类候选时使用CONTAINS；单一险种大类operator必须使用的MATCH。"
    examples:
      - query: "购买过医疗险或意外险的客户"
        output: {field: pCategorys, operator: CONTAINS, value: ["医疗保险", "意外伤害保险"]}

   # ==================== 未持有险种大类 ====================

  - id: held_product_category_gap
    retrieval_text: >
      未购买意外险 买了车险但没买意外险 车险但没有购买意外险
      没买医疗险 未购买医疗险 没有医疗保险 不含医疗保险
      医疗意向 意向医疗 有意向医疗 医疗潜客 意向医疗客户
      没买护理险 没有护理保险 没买重疾险 没有疾病保险
      没买定期寿险 没有定期寿险 没买终身寿险 没有终身寿险
    field: pCategorys
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: pCategorys
    description: "表示客户未持有某个险种大类，不表示未持有具体产品名称，也不表示字段为空。"
    notes: "只召回明确的未购买、不包含或医疗意向缺口表达。车险但没有购买意外险等查询中，未购买意外险应映射为 pCategorys NOT_CONTAINS 意外伤害保险；车险本身不是该字段。医疗意向表示医疗保险缺口，不是六条权益服务线的会员状态。"
    examples:
      - query: "没有买意外险的客户"
        output: { field: pCategorys, operator: NOT_CONTAINS, value: ["意外伤害保险"] }
      - query: "买了车险，但没有购买意外险的客户"
        output: { field: pCategorys, operator: NOT_CONTAINS, value: ["意外伤害保险"] }
      - query: "有意向医疗客户"
        output: { field: pCategorys, operator: NOT_CONTAINS, value: ["医疗保险"] }
      - query: "没买终身寿险的客户"
        output: { field: pCategorys, operator: NOT_CONTAINS, value: ["终身寿险"] }
      - query: "没有定期寿险的客户"
        output: { field: pCategorys, operator: NOT_CONTAINS, value: ["定期寿险"] }

  # ==================== 年缴保费 ====================

  - id: annual_premium_gt
    retrieval_text: >
      年缴保费超过 年交保费超过 年缴超过 年交超过
      年缴保费大于 年交保费大于 年缴保费高于 年交保费高于
    field: annPremSegNum
    operator: GT
    value_type: numeric
    unit: "元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元"
    description: "表示年缴保费金额（大于），不表示总保费、产品总保额"
    notes: "仅包含大于关系，不包含等于。‘超过/大于/高于’必须使用GT；不得因为其他年缴保费知识中出现GTE就改成GTE。"
    examples:
      - query: "年缴保费1万以上（不含1万）的客户"
        output: {field: annPremSegNum, operator: GT, value: 10000}
      - query: "保费超过5万的客户"
        output: {field: annPremSegNum, operator: GT, value: 50000}
    negative_examples:
      - query: "总保费为50万的客户"
        reason: "这是总保费语义，不是年缴保费；当前不能映射到 annPremSegNum"
      - query: "上个月刚缴完费的客户"
        reason: "这是应缴日/缴费日完成语义，应映射到 polNoInfo.paytodate，不是年缴保费金额"

  - id: annual_premium_gte
    retrieval_text: >
      年缴保费以上 年交保费以上 年缴保费及以上 年交保费及以上
      年缴保费大于等于 年交保费大于等于 年交以上 年缴以上
      年缴保费不低于 年交保费不低于 年缴保费不少于 年交保费不少于 年缴保费达到 年交保费达到
    field: annPremSegNum
    operator: GTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元"
    description: "表示年缴保费金额（大于等于），不表示总保费、产品总保额"
    notes: "‘以上/及以上/大于等于/不低于/不少于’使用GTE；‘超过/大于/高于’属于严格大于，必须改用annual_premium_gt的GT。‘年交/年缴’明确表示年缴保费，绝不能解释为年收入。"
    examples:
      - query: "年缴保费1万及以上的客户"
        output: {field: annPremSegNum, operator: GTE, value: 10000}
      - query: "年缴保费1万以上的客户"
        output: {field: annPremSegNum, operator: GTE, value: 10000}
      - query: "年交3万以上的客户"
        output: {field: annPremSegNum, operator: GTE, value: 30000}
    negative_examples:
      - query: "总保费为50万的客户"
        reason: "这是总保费语义，不是年缴保费；当前不能映射到 annPremSegNum"
      - query: "总保费90万以上"
        reason: "这是总保费语义，不是年缴保费；当前不能映射到 annPremSegNum"
      - query: "上个月刚缴完费的客户"
        reason: "这是应缴日/缴费日完成语义，应映射到 polNoInfo.paytodate，不是年缴保费金额"

  - id: annual_premium_range
    retrieval_text: >
      年缴保费 年交保费 年缴金额 年交金额 年缴保费区间 年交保费区间
      年缴保费范围 年交保费范围 年缴保费在多少到多少之间 年交保费在多少到多少之间
      年缴保费等于 年交保费等于 年交1万 年交5万 年缴1万 年缴5万
    field: annPremSegNum
    operator: RANGE
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "表示年缴保费区间，或精确值（不带'以上'/'以下'等范围词时）"
    examples:
      - query: "年缴保费1万到5万的客户"
        output: {field: annPremSegNum, operator: RANGE, value: {min: 10000, max: 50000}}
      - query: "年交保费2万的客户"
        output: {field: annPremSegNum, operator: RANGE, value: {min: 20000, max: 20000}}
      - query: "年交保费5千的客户"
        output: {field: annPremSegNum, operator: RANGE, value: {min: 5000, max: 5000}}
      - query: "年缴保费20000的客户"
        output: {field: annPremSegNum, operator: RANGE, value: {min: 20000, max: 20000}}
      - query: "年交5万的客户"
        output: {field: annPremSegNum, operator: RANGE, value: {min: 50000, max: 50000}}

  - id: annual_premium_lt
    retrieval_text: >
      年缴保费低于 年交保费低于 年保费小于 年交保费不足 年缴保费不足
      年缴保费以下 年交保费以下
    field: annPremSegNum
    operator: LT
    value_type: numeric
    unit: "元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元"
    description: "表示年缴保费金额（小于），不表示总保费、产品总保额"
    notes: "仅包含小于关系，不包含等于。当前业务口径中不带‘及’的‘N以下’按严格小于处理，使用LT；‘N及以下/不超过/小于等于’才使用LTE。"
    examples:
      - query: "年缴保费1万以下（不含1万）的客户"
        output: {field: annPremSegNum, operator: LT, value: 10000}
      - query: "保费低于5000的客户"
        output: {field: annPremSegNum, operator: LT, value: 5000}

  - id: annual_premium_lte
    retrieval_text: >
      年缴保费不超过 年交保费不超过 年缴保费及以下 年交保费及以下
      年缴保费不高于 年交保费不高于 年保费小于等于 年交保费小于等于
    field: annPremSegNum
    operator: LTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元"
    description: "表示年缴保费上限（小于等于），不表示总保费上限、产品总保额上限"
    notes: "仅‘及以下/不超过/不高于/小于等于’使用LTE；‘以下/低于/小于/不足’不包含边界，使用LT。"
    examples:
      - query: "年缴保费不超过1万的客户"
        output: {field: annPremSegNum, operator: LTE, value: 10000}
      - query: "年缴保费1万及以下的客户"
        output: {field: annPremSegNum, operator: LTE, value: 10000}
    negative_examples:
      - query: "总保费不超过50万的客户"
        reason: "这是总保费语义，不是年缴保费；当前不能映射到 annPremSegNum"

  # ==================== 期交保费 ====================

  - id: polNoInfo.totmodalpremsum_gte
    is_supported: true
    retrieval_text: >
      期交保费 期缴保费 每期保费 每期缴费金额 每期交多少 每期交得多 每期缴得多 每期保费高 期交金额高 及以上 不低于 大于等于 不少于
    field: polNoInfo.totmodalpremsum
    operator: GTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000，如果没有明确单位，则默认是元，不用做运算"
    description: "期交保费金额，≥ 达到或超过；区别于年交保费"
    notes: "期交保费按每期计算，年交保费按年计算；两者单位不同，不能混淆"
    examples:
      - query: "期交保费1万及以上的客户"
        output: { field: polNoInfo.totmodalpremsum, operator: GTE, value: 10000 }

  - id: polNoInfo.totmodalpremsum_gt
    is_supported: true
    retrieval_text: >
      期交保费 期缴保费 每期保费 每期交得多 每期缴得多 每期保费高 期交金额高 超过 大于 高于
    field: polNoInfo.totmodalpremsum
    operator: GT
    value_type: numeric
    unit: "元，万=×10000，千=×1000，如果没有明确单位，则默认是元，不用做运算"
    description: "期交保费金额，＞ 严格超过；区别于年交保费"
    examples:
      - query: "期交保费大于1万的客户"
        output: { field: polNoInfo.totmodalpremsum, operator: GT, value: 10000 }

  - id: polNoInfo.totmodalpremsum_lte
    is_supported: true
    retrieval_text: >
      期交保费 期缴保费 每期保费 以下 不超过 不大于 及以下 小于等于
    field: polNoInfo.totmodalpremsum
    operator: LTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000，如果没有明确单位，则默认是元，不用做运算"
    description: "期交保费金额，≤ 不超过；区别于年交保费"
    examples:
      - query: "期交保费1万及以下的客户"
        output: { field: polNoInfo.totmodalpremsum, operator: LTE, value: 10000 }

  - id: polNoInfo.totmodalpremsum_lt
    is_supported: true
    retrieval_text: >
      期交保费 期缴保费 每期保费 以下 低于 小于
    field: polNoInfo.totmodalpremsum
    operator: LT
    value_type: numeric
    unit: "元，万=×10000，千=×1000，如果没有明确单位，则默认是元，不用做运算"
    description: "期交保费金额，＜ 严格低于；区别于年交保费"
    examples:
      - query: "期交保费低于1万的客户"
        output: { field: polNoInfo.totmodalpremsum, operator: LT, value: 10000 }

  - id: polNoInfo.totmodalpremsum_range
    is_supported: true
    retrieval_text: >
      期交保费 期缴保费 每期保费 精确值 等于 正好 刚好 块 元
    field: polNoInfo.totmodalpremsum
    operator: RANGE
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "期交保费精确值（等于），不带'以上'/'以下'等范围词时使用"
    examples:
      - query: "期交保费2万的客户"
        output: { field: polNoInfo.totmodalpremsum, operator: RANGE, value: {min: 20000, max: 20000} }
      - query: "期交保费5千的客户"
        output: { field: polNoInfo.totmodalpremsum, operator: RANGE, value: {min: 5000, max: 5000} }
      - query: "每期交保费500元的客户"
        output: { field: polNoInfo.totmodalpremsum, operator: RANGE, value: {min: 500, max: 500} }


  # ==================== 产品总保额 ====================

  - id: total_coverage_gt
    retrieval_text: >
      保额超过 总保额超过 产品总保额超过 保额大于 总保额大于
      保额高于 总保额高于
    field: insnoSumInsSeqNum
    operator: GT
    value_type: numeric
    unit: "元，万=×10000、千=×1000，若未明确标注万或元的单位，则默认为元，不需要转换"
    description: "表示产品总保额（大于），不表示总保费、年缴保费"
    notes: "仅包含大于关系，不包含等于"
    examples:
      - query: "总保额超过50万的客户"
        output: {field: insnoSumInsSeqNum, operator: GT, value: 500000}
    negative_examples:
      - query: "总保费90万以上"
        reason: "这是总保费语义，不是产品总保额，不能映射到 insnoSumInsSeqNum"

  - id: total_coverage_gte
    retrieval_text: >
      保额以上 总保额以上 产品总保额以上 保额及以上 保额大于等于
      高保额 保额多少 保障额度 保障金额 买得多 保障多 保额高 总保额高 按保额
    field: insnoSumInsSeqNum
    operator: GTE
    value_type: numeric
    unit: "元，万=×10000、千=×1000，若未明确标注万或元的单位，则默认为元，不需要转换"
    description: "表示产品总保额（大于等于），不表示总保费、年缴保费，高保额表示产品总保额≥300000"
    examples:
      - query: "总保额50万及以上的客户"
        output: {field: insnoSumInsSeqNum, operator: GTE, value: 500000}
      - query: "总保额50万以上的客户"
        output: {field: insnoSumInsSeqNum, operator: GTE, value: 500000}
      - query: "高保额客户"
        output: {field: insnoSumInsSeqNum, operator: GTE, value: 300000}
      - query: "保额大于1的客户"
        output: { field: insnoSumInsSeqNum, operator: GTE, value: 1 }
    negative_examples:
      - query: "总保费90万以上"
        reason: "这是总保费语义，不是产品总保额，不能映射到 insnoSumInsSeqNum"

  - id: total_coverage_lt
    retrieval_text: >
      保额不足 保额低 保额较低 保额以下 保额低于
    field: insnoSumInsSeqNum
    operator: LT
    value_type: numeric
    unit: "元，万=×10000元，千=×1000，若未明确标注万或元的单位，则默认为元，不需要转换"
    description: "表示产品总保额（小于），不表示总保费上限"
    notes: "仅包含小于关系，不包含等于"
    examples:
      - query: "保额不足50万（不含50万）的客户"
        output: {field: insnoSumInsSeqNum, operator: LT, value: 500000}

  - id: total_coverage_lte
    retrieval_text: >
      保额不足 保额低 保额较低 保额及以下 保额小于等于
    field: insnoSumInsSeqNum
    operator: LTE
    value_type: numeric
    unit: "元，万=×10000元，千=×1000，若未明确标注万或元的单位，则默认为元，不需要转换"
    description: "表示产品总保额上限（小于等于），不表示总保费上限"
    examples:
      - query: "保额不足50万的客户"
        output: {field: insnoSumInsSeqNum, operator: LTE, value: 500000}
      - query: "保额50万及以下的客户"
        output: {field: insnoSumInsSeqNum, operator: LTE, value: 500000}
      - query: "保额低于10的客户"
        output: { field: insnoSumInsSeqNum, operator: LTE, value: 10 }

  - id: total_coverage_range
    retrieval_text: >
      总保额在 保额区间 保额范围 产品总保额在多少到多少之间
      保障额度在 保障金额范围
    field: insnoSumInsSeqNum
    operator: RANGE
    value_type: numeric
    unit: "元，万=×10000、千=×1000，若未明确标注万或元的单位，则默认为元，不需要转换"
    description: "表示产品总保额区间，不表示总保费区间、年缴保费区间"
    examples:
      - query: "总保额50万到100万的客户"
        output: { field: insnoSumInsSeqNum, operator: RANGE, value: { min: 500000, max: 1000000 } }
      - query: "保障额度在300000到800000之间的客户"
        output: { field: insnoSumInsSeqNum, operator: RANGE, value: { min: 300000, max: 800000 } }
    negative_examples:
      - query: "总保费50万到100万的客户"
        reason: "这是总保费区间，不是产品总保额区间，不能映射到 insnoSumInsSeqNum"
      - query: "年缴保费1万到5万的客户"
        reason: "这是年缴保费区间，不是产品总保额区间，不能映射到 insnoSumInsSeqNum"

  # ==================== 保单周年日 ====================

  - id: policy_anniversary
    retrieval_text: >
      保单周年日 保单周年 保单纪念日 周年日 保单生效周年
      过周年日 到周年日 本月过周年日 今年过周年日 指定月份过周年日
      9月过周年日 今年9月过周年日 2026年9月过周年日
    field: effAnniversaryDate
    operator: RANGE
    value_type: date
    format: "MM-dd"
    description: "表示保单周年日，不表示投保时间、投保日期、签单日期"
    notes: "该字段表示保单周年日的月日信息，按每年循环语义处理。原文出现‘周年日/过周年日/到周年日’时必须使用本字段，不得改成保单生效日 polNoInfo.poleffdate；即使原文带年份，年份也只用于定位语境，输出仍去掉年份并保留MM-dd月日范围。若查询明确要求投保时间/投保日期，而系统无对应字段，不应映射到此字段。"
    examples:
      - query: "保单周年日在01-01的客户"
        output: {field: effAnniversaryDate, operator: RANGE, value: {min: "01-01", max: "01-01"}}
      - query: "保单周年日为2023-06-26的客户"
        output: { field: effAnniversaryDate, operator: RANGE, value: { min: "06-26", max: "06-26" } }
      - query: "2018年7月保单周年日的客户"
        output: {field: effAnniversaryDate, operator: RANGE, value: {min: "07-01", max: "07-31"}}
      - query: "2026年9月过周年日的客户"
        output: {field: effAnniversaryDate, operator: RANGE, value: {min: "09-01", max: "09-30"}}
    negative_examples:
      - query: "最近投保的人"
        reason: "最近投保是投保时间语义，当前不能映射到保单周年日"
      - query: "2020年签单的客户"
        reason: "签单日期不是保单周年日"

  # ==================== 持有综拓产品类别 ====================

  - id: held_cross_sell_category
    retrieval_text: >
      综拓产品 综拓类别 中高端医疗 家财险 学平险
      车辆交强险 车辆商业险 合家欢 财富 健康 生活
      综拓产品类别带 综拓产品类别包含 e生保综拓产品 e生保这类综拓产品
    field: agentPerspProductType
    operator: MATCH
    value_type: enum
    enum_ref: agentPerspProductType
    enum_requires_anchor: true
    description: "表示客户持有某个明确的综拓产品类别，如中高端医疗、家财险、学平险、合家欢等。"
    notes: "必须明确是综拓产品/综拓类别时才映射到本字段。指定一个明确类别值时使用MATCH；只有明确多个候选时才使用CONTAINS。若只是购买了某个寿险产品名（如 e生保）且未说明综拓，应默认映射到投保险种字段。是否有任意综拓产品且没有指定类别值时使用 agentPerspProductType EXISTS。"
    examples:
      - query: "持有综拓e生保的客户"
        output: {field: agentPerspProductType, operator: MATCH, value: "e生保"}
      - query: "综拓产品类别带车辆商业险的客户"
        output: {field: agentPerspProductType, operator: MATCH, value: "车辆商业险"}
    negative_examples:
      - query: "购买了e生保的客户"
        reason: "若没有明确是购买了综拓的e生保，默认查询 polNoInfo.plancodeinfo.abbrname 字段"

  - id: not_held_cross_sell_category
    retrieval_text: >
      未持有综拓产品 未买综拓类别 没有中高端医疗 没买家财险 没买学平险
      没有车辆交强险 没有车辆商业险 没买合家欢 没买财富 没买健康 没买生活
    field: agentPerspProductType
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: agentPerspProductType
    enum_requires_anchor: true
    description: "表示客户未持有某个明确的综拓产品类别，不表示完全没有综拓产品。"
    notes: "未持有任意综拓产品应使用 agentPerspProductType NOT_EXISTS；未持有某一类综拓产品才使用 NOT_CONTAINS。"
    examples:
      - query: "没买学平险的客户"
        output: { field: agentPerspProductType, operator: NOT_CONTAINS, value: [ "学平险" ] }
      - query: "没有e生保综拓产品的客户"
        output: { field: agentPerspProductType, operator: NOT_CONTAINS, value: [ "e生保" ] }
      - query: "未持有家财险综拓产品的客户"
        output: { field: agentPerspProductType, operator: NOT_CONTAINS, value: [ "家财险" ] }

  - id: held_cross_sell_category_exists
    retrieval_text: >
      持有任意综拓产品 买了任意综拓产品 是否有综拓产品 有无综拓产品 综拓产品是否存在
    field: agentPerspProductType
    operator: EXISTS
    value_type: exists
    description: "表示客户持有任意综拓产品类别。"
    notes: "有综拓产品、是否有综拓产品、有无综拓产品、买了综拓产品均映射到 agentPerspProductType EXISTS；不要映射到 validSinsPol，validSinsPol 仅表示有效短险保单。"
    examples:
      - query: "持有综拓产品的客户"
        output: { field: agentPerspProductType, operator: EXISTS, value: "" }
      - query: "买了综拓产品的客户"
        output: { field: agentPerspProductType, operator: EXISTS, value: "" }

  - id: held_cross_sell_category_not_exists
    retrieval_text: >
      未持有综拓产品 没有买了综拓产品 没买综拓产品
    field: agentPerspProductType
    operator: NOT_EXISTS
    value_type: exists
    description: "表示客户没有任意综拓产品类别。"
    notes: "没有综拓产品、没买综拓产品、未持有综拓产品均映射到 agentPerspProductType NOT_EXISTS；不要映射到 validSinsPol。"
    examples:
      - query: "未持有综拓产品的客户"
        output: { field: agentPerspProductType, operator: NOT_EXISTS, value: "" }
      - query: "没有买综拓产品的客户"
        output: { field: agentPerspProductType, operator: NOT_EXISTS, value: "" }


  # ==================== 综拓理赔 ====================

  - id: cross_sell_claim
    retrieval_text: >
      综拓理赔报案 综拓理赔结案 综拓产品理赔报案
      综拓产品理赔结案 综拓出险报案 综拓理赔状态 报过案的综拓产品
    field: occurPassPayRegst
    operator: MATCH
    value_type: enum
    enum_ref: occurPassPayRegst
    description: "表示综拓理赔状态，只有报案/结案等状态语义，不表示理赔时间、理赔金额、理赔次数"
    notes: "该字段表示综拓理赔状态（报案/结案），不是理赔时间；涉及最近半年、近30天等时间约束的理赔查询，如无理赔时间字段，不应映射到此字段"
    examples:
      - query: "有综拓产品理赔报案的客户"
        output: {field: occurPassPayRegst, operator: MATCH, value: "综拓理赔报案"}
      - query: "有e生保这类综拓产品而且报过案的客户"
        output: {field: occurPassPayRegst, operator: MATCH, value: "综拓理赔报案"}
    negative_examples:
      - query: "近期有过综拓理赔的客户"
        reason: "这是理赔时间范围查询，不是理赔状态"
      - query: "去年理赔的客户"
        reason: "这是理赔时间查询，不是理赔状态"
      - query: "最近一个月有过重疾险理赔的客户"
        reason: "这是理赔时间和险种组合查询，不是综拓理赔状态"
      - query: "综拓理赔金额大于1万的客户"
        reason: "理赔金额与理赔状态不是同一字段"

  - id: cross_sell_claim_exists
    retrieval_text: >
      有综拓理赔记录 有过综拓理赔 有过综拓产品理赔
    field: occurPassPayRegst
    operator: EXISTS
    value_type: exists
    show_enum_in_prompt: false
    description: "表示有过综拓理赔，但原文没有指定报案或结案状态；不表示理赔时间、理赔金额、理赔次数"
    notes: "仅在原文泛化表达有综拓理赔记录、且未说明报案/结案状态时使用EXISTS。报案、报过案、已报案应使用MATCH‘综拓理赔报案’；结案、已结案应使用MATCH‘综拓理赔结案’。"
    examples:
      - query: "有过综拓理赔记录的客户"
        output: { field: occurPassPayRegst, operator: EXISTS, value: "" }
      - query: "有综拓理赔过的客户"
        output: { field: occurPassPayRegst, operator: EXISTS, value: "" }

  # ==================== 有效寿险到期时间 ====================
  - id: policy_expiry_date_gt
    retrieval_text: >
      保单到期时间大于 保单到期时间超过 保单之后才到期
    field: validSinsMatuDateTime
    operator: GT
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示寿险保单到期时间晚于某个日期（不含等于），不表示缴费期满、证件到期"
    notes: "相对时间按当前日期展开为具体日期时间，不输出占位符"
    examples:
      - query: "保单到期时间还有一个月以上(当前时间为2026-04-28)"
        output: { field: validSinsMatuDateTime, operator: GT, value: "2026-5-28" }
    negative_examples:
      - query: "近30天需要缴费的客户"
        reason: "这是缴费期满时间，应映射到 effAppEndDate，不是保单到期时间"

  - id: policy_expiry_date_gte
    retrieval_text: >
      保单到期时间大于等于 保单到期时间及之后 保单之后才到期
    field: validSinsMatuDateTime
    operator: GTE
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示寿险保单到期时间晚于或等于某个日期，不表示缴费期满、证件到期"
    notes: "相对时间按当前日期展开为具体日期时间，不输出占位符"
    examples:
      - query: "保单到期时间还有一个月及以上(当前时间为2026-04-28)"
        output: { field: validSinsMatuDateTime, operator: GTE, value: "2026-5-28" }
      - query: "还未到保单到期时间(当前时间为2026-04-28)"
        output: { field: validSinsMatuDateTime, operator: GTE, value: "2026-4-29" }
    negative_examples:
      - query: "近30天需要缴费的客户"
        reason: "这是缴费期满时间，应映射到 effAppEndDate，不是保单到期时间"

  - id: policy_expiry_date_lt
    retrieval_text: >
      保单已到期 保单到期了
    field: validSinsMatuDateTime
    operator: LT
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示寿险保单到期时间早于某个日期（不含等于），不表示缴费期满、证件到期"
    notes: "相对时间按当前日期展开为具体日期时间，不输出占位符"
    examples:
      - query: "保单已经到期（不含当天）的客户（当前2026-03-23）"
        output: {field: validSinsMatuDateTime, operator: LT, value: "2026-03-24"}

  - id: policy_expiry_date_lte
    retrieval_text: >
      保单已到期 保单到期了 保单到期时间小于等于
    field: validSinsMatuDateTime
    operator: LTE
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示寿险保单到期时间早于或等于某个日期，不表示缴费期满、证件到期"
    notes: "相对时间按当前日期展开为具体日期时间，不输出占位符"
    examples:
      - query: "保单已经到期的客户（当前2026-03-23）"
        output: {field: validSinsMatuDateTime, operator: LTE, value: "2026-03-23"}
    negative_examples:
      - query: "近30天需要缴费的客户"
        reason: "这是缴费期满时间，应映射到 effAppEndDate，不是保单到期时间"

  - id: policy_expiry_date_range_relative
    retrieval_text: >
      未来一个月即将到期 未来30天即将到期 下个月即将到期 保单即将到期 即将到期 保单快到期 续保提醒 到期前
      一个⽉内到期 未来一个月到期 未来30天到期 3天内到期 10天内到期 30天内到期 60天内到期 近期到期
    field: validSinsMatuDateTime
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示从当前时间起未来一段时间内的寿险保单到期区间，不使用单边 LTE 代替完整区间"
    examples:
      - query: "3天内保单到期的客户（当前2026-03-23）"
        output: { field: validSinsMatuDateTime, operator: RANGE, value: {min: "2026-03-24", max: "2026-03-27"} }
      - query: "未来一个月即将到期的客户（当前2026-03-25）"
        output: {field: validSinsMatuDateTime, operator: RANGE, value: {min: "2026-03-25", max: "2026-04-25"}}

  # ==================== 有效短险保单 ====================

  - id: valid_short_term_policy_contains
    retrieval_text: >
      意健险短险 综拓短险 O2O短险 短期意健险保单 意健险短险
    field: validSinsPol
    operator: CONTAINS
    value_type: enum
    enum_ref: validSinsPol
    notes: "该字段仅表示是否有效短险保单，不表示准客来源，若需要查询准客来源，应映射到pcustSourcType；不表示是否有综拓产品/持有综拓产品，这类查询应映射到agentPerspProductType"
    examples:
      - query: "有综拓短险的客户"
        output: {field: validSinsPol, operator: CONTAINS, value: ["综拓"]}
      - query: "购买了意健险的客户"
        output: {field: validSinsPol, operator: CONTAINS, value: ["意健险"]}
      - query: "意健险保单"
        output: {field: validSinsPol, operator: CONTAINS, value: ["意健险"]}

  - id: valid_short_term_policy_not_contains
    retrieval_text: >
      没买意健险短险 没有综拓短险 未投保O2O短险 没有短期意健险保单 没有买意健险短险
    field: validSinsPol
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: validSinsPol
    notes: "该字段仅表示是否有效短险保单，不表示准客来源，若需要查询准客来源，应映射到pcustSourcType"
    examples:
      - query: "没有综拓短险的客户"
        output: { field: validSinsPol, operator: NOT_CONTAINS, value: [ "综拓" ] }
      - query: "未购买了意健险的客户"
        output: { field: validSinsPol, operator: NOT_CONTAINS, value: [ "意健险" ] }

  - id: pcust_source_type_contains
    retrieval_text: >
      意健险准客 综拓准客 O2O准客 综拓客户 O2O客户
    field: pcustSourcType
    operator: CONTAINS
    value_type: enum
    enum_ref: pcustSourcType
    notes: "该字段表示准客来源，不表示有效短险保单；必须有“准客/准客来源”等来源语义。裸“意健险客户”表示有效短险保单，应映射到validSinsPol"
    examples:
      - query: "综拓准客"
        output: { field: pcustSourcType, operator: CONTAINS, value: [ "综拓" ] }
      - query: "综拓或意健险准客"
        output: { field: pcustSourcType, operator: CONTAINS, value: [ "综拓", "意健险" ] }

  - id: pcust_source_type_not_contains
    retrieval_text: >
      不是意健险准客 不是综拓准客 不是O2O准客 非综拓客户 非O2O客户
    field: pcustSourcType
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: pcustSourcType
    notes: "该字段表示准客来源，不表示有效短险保单，若需要查询有效短险保单，应映射到validSinsPol"
    examples:
      - query: "非综拓准客"
        output: { field: pcustSourcType, operator: NOT_CONTAINS, value: [ "综拓" ] }
      - query: "不是意健险准客"
        output: { field: pcustSourcType, operator: NOT_CONTAINS, value: [ "意健险" ] }

  # ==================== 居家达标客户等级 ====================

#  - id: jujia_client_grade_exact
#    retrieval_text: >
#      居家达标等级 居家客户等级 居家V1 居家V2 居家V3 居家潜客
#      居家v1 居家v2 居家v3 居家V1优享 居家V2优享 居家意向客户
#      居家V1.5 居家V2.5 居家v1.5 居家v2.5 居家等级 居家达标为V2 居家达标等级为V3
#    field: jujiaClientGrade
#    operator: MATCH
#    value_type: enum
#    enum_ref: jujiaClientGrade
#    description: "表示居家客户的单个等级标签，不表示会员范围，也不表示开通时间"
#    notes: "居家潜客不属于居家会员客户；居家客户包括v0.5、v1、v1.5、v2、v2.5、v3；等级排序：居家潜客<v0.5<v1<v1.5<v2<v2.5<v3。用户说“居家达标为/居家达标等级为/居家等级为+具体等级”时是单个等级，输出 MATCH，不要输出范围。预达标/已达标属于泛状态词，不能脱离居家语境单独映射到本字段。居家意向=居家潜客"
#    examples:
#      - query: "居家v1等级的客户"
#        output: {field: jujiaClientGrade, operator: MATCH, value: "v1"}
#      - query: "居家潜客"
#        output: {field: jujiaClientGrade, operator: MATCH, value: "居家潜客"}
#      - query: "居家V1优享客户"
#        output: {field: jujiaClientGrade, operator: MATCH, value: "v1.5"}
#      - query: "居家意向客户"
#        output: {field: jujiaClientGrade, operator: MATCH, value: "居家潜客"}
#      - query: "居家达标为V2的客户"
#        output: { field: searchJujiaClientGrade, operator: MATCH, value: "v2" }
#      - query: "居家达标等级为V2的客户"
#        output: { field: searchJujiaClientGrade, operator: MATCH, value: "v2" }
#    negative_examples:
#      - query: "居家权益开通时间在今年的客户"
#        reason: "这是开通时间，不是居家等级"
#
#  - id: jujia_client_grade_range
#    retrieval_text: >
#      居家会员 居家会员客户 居家达标客户 居家v2以上 居家v2及以上
#      居家等级以上 居家等级及以上 居家等级以下 居家等级及以下
#    field: jujiaClientGrade
#    operator: CONTAINS
#    value_type: enum
#    enum_ref: jujiaClientGrade
#    description: "表示居家等级范围；“以上/以下”不含当前值，“及以上/及以下”含边界"
#    notes: "居家潜客不属于居家会员客户；等级排序：居家潜客<v0.5<v1<v1.5<v2<v2.5<v3"
#    examples:
#      - query: "居家达标客户"
#        output: { field: jujiaClientGrade, operator: CONTAINS, value: ["v0.5", "v1", "v1.5", "v2", "v2.5", "v3"] }
#      - query: "居家会员客户"
#        output: { field: jujiaClientGrade, operator: CONTAINS, value: ["v0.5", "v1", "v1.5", "v2", "v2.5", "v3"] }
#      - query: "居家v2以上的客户"
#        output: { field: jujiaClientGrade, operator: CONTAINS, value: ["v2.5", "v3"] }
#      - query: "居家v2及以上的客户"
#        output: { field: jujiaClientGrade, operator: CONTAINS, value: ["v2", "v2.5", "v3"] }
#    negative_examples:
#      - query: "居家权益开通时间在今年的客户"
#        reason: "这是开通时间，不是居家等级范围"

  # ==================== 康养达标客户等级 ====================

#  - id: kangyang_client_grade_exact
#    retrieval_text: >
#      康养等级 康养达标 逸享会员 逸享PLUS 颐享家会员 臻享会员
#      康养预达标 康养会员等级 逸享 颐享
#      康养逸享达标客户 康养逸享PLUS达标客户 康养颐享家达标客户
#      康养臻享V1达标客户 康养臻享V2达标客户 康养臻享V3达标客户
#    field: kangyangClientGrade
#    operator: MATCH
#    value_type: enum
#    enum_ref: kangyangClientGrade
#    description: "表示康养单个等级标签，不表示会员范围，也不表示开通时间"
#    notes: "康养预达标会员是本字段的合法单个等级值；当用户完整表达“康养预达标会员/康养预达标”时，输出 MATCH=康养预达标会员。康养客户/康养达标客户这类范围表达不包含康养预达标会员；康养客户包括逸享会员、逸享PLUS会员、颐享家会员、臻享会员V1、臻享会员V2、臻享会员V3。等级排序：康养预达标会员<逸享会员<逸享PLUS会员<颐享家会员<臻享会员V1<臻享会员V2<臻享会员V3。单独的预达标/已达标属于泛状态词，不能脱离康养语境单独映射到本字段。"
#    examples:
#      - query: "康养预达标会员"
#        output: {field: kangyangClientGrade, operator: MATCH, value: "康养预达标会员"}
#      - query: "康养预达标客户"
#        output: {field: kangyangClientGrade, operator: MATCH, value: "康养预达标会员"}
#      - query: "逸享会员客户"
#        output: {field: kangyangClientGrade, operator: MATCH, value: "逸享会员"}
#      - query: "康养臻享V1的客户"
#        output: {field: kangyangClientGrade, operator: MATCH, value: "臻享会员V1"}
#      - query: "康养逸享PLUS达标客户"
#        output: {field: kangyangClientGrade, operator: MATCH, value: "逸享PLUS会员"}
#      - query: "康养达标为臻享会员V1的客户"
#        output: { field: kangyangClientGrade, operator: MATCH, value: "臻享会员V1" }
#    negative_examples:
#      - query: "康养权益开通时间在今年的客户"
#        reason: "这是开通时间，不是康养等级"
#
#  - id: kangyang_client_grade_range
#    retrieval_text: >
#      康养会员 康养会员客户 康养达标客户 逸享PLUS以上 逸享PLUS及以上
#      康养等级以上 康养等级及以上 康养等级以下 康养等级及以下
#    field: kangyangClientGrade
#    operator: CONTAINS
#    value_type: enum
#    enum_ref: kangyangClientGrade
#    description: "表示康养等级范围；“以上/以下”不含边界，“及以上/及以下”含边界"
#    notes: "康养预达标会员不属于康养客户；康养客户包括逸享会员、逸享PLUS会员、颐享家会员、臻享会员V1、臻享会员V2、臻享会员V3；等级排序：康养预达标会员<逸享会员<逸享PLUS会员<颐享家会员<臻享会员V1<臻享会员V2<臻享会员V3"
#    examples:
#      - query: "逸享PLUS以上康养等级客户"
#        output: { field: kangyangClientGrade, operator: CONTAINS, value: ["颐享家会员", "臻享会员V1", "臻享会员V2", "臻享会员V3"]}
#      - query: "逸享PLUS及以上康养等级客户"
#        output: { field: kangyangClientGrade, operator: CONTAINS, value: ["逸享PLUS会员", "颐享家会员", "臻享会员V1", "臻享会员V2", "臻享会员V3"]}
#      - query: "康养会员客户"
#        output: { field: kangyangClientGrade, operator: CONTAINS, value: ["逸享会员", "逸享PLUS会员", "颐享家会员", "臻享会员V1", "臻享会员V2", "臻享会员V3" ] }
#      - query: "康养达标客户"
#        output: { field: kangyangClientGrade, operator: CONTAINS, value: [ "逸享会员", "逸享PLUS会员", "颐享家会员", "臻享会员V1", "臻享会员V2", "臻享会员V3" ] }
#    negative_examples:
#      - query: "康养权益开通时间在今年的客户"
#        reason: "这是开通时间，不是康养等级范围"


  # ==================== 安有护权益等级 ====================

#  - id: zhenxiang_run_equity_grade
#    retrieval_text: >
#      安有护 安有护权益 安有护国内版 安有护国际版 安有护等级
#      安有护国内版达标 安有护国际版达标 安有护(国内版)达标 安有护(国际版)达标
#    field: zhenxiangRunEquityGrade
#    operator: MATCH
#    value_type: enum
#    enum_ref: zhenxiangRunEquityGrade
#    description: "表示安有护权益等级版本，如安有护(国内版)/安有护(国际版)；也可用 EXISTS 表示是否持有该权益"
#    examples:
#      - query: "有安有护国际版的客户"
#        output: {field: zhenxiangRunEquityGrade, operator: MATCH, value: "安有护(国际版)"}
#      - query: "安有护国际版达标客户"
#        output: {field: zhenxiangRunEquityGrade, operator: MATCH, value: "安有护(国际版)"}
#      - query: "安有护权益等级为安有护(国内版)的客户"
#        output: {field: zhenxiangRunEquityGrade, operator: MATCH, value: "安有护(国内版)"}
#    negative_examples:
#      - query: "安有护开通时间在2024年的客户"
#        reason: "这是开通时间，不是权益等级"
#      - query: "高价值客户"
#        reason: "这是客户价值标签，不是安有护权益"
#
#  - id: zhenxiang_run_equity_not_contains
#    retrieval_text: >
#      没有安有护国际版 没有安有护国内版 未持有安有护国际版 不属于安有护国内版客户
#    field: zhenxiangRunEquityGrade
#    operator: NOT_CONTAINS
#    value_type: enum
#    enum_ref: zhenxiangRunEquityGrade
#    description: "表示客户不属于某个安有护权益版本，不表示完全没有安有护权益"
#    examples:
#      - query: "没有安有护国际版的客户"
#        output: { field: zhenxiangRunEquityGrade, operator: NOT_CONTAINS, value: [ "安有护(国际版)" ] }
#      - query: "不是安有护国内版的客户"
#        output: { field: zhenxiangRunEquityGrade, operator: NOT_CONTAINS, value: [ "安有护(国内版)" ] }
#
#
#  - id: zhenxiang_run_equity_exists
#    retrieval_text: >
#      持有安有护权益 有安有护权益 安有护客户 安有护会员
#    field: zhenxiangRunEquityGrade
#    operator: EXISTS
#    value_type: exists
#    description: "表示客户持有安有护权益，不要求具体国内版/国际版"
#    examples:
#      - query: "持有安有护权益的客户"
#        output: {field: zhenxiangRunEquityGrade, operator: EXISTS, value: ""}
#
#  - id: zhenxiang_run_equity_not_exists
#    retrieval_text: >
#      未持有安有护权益 没有安有护权益 不是安有护客户 不是安有护会员
#    field: zhenxiangRunEquityGrade
#    operator: NOT_EXISTS
#    value_type: not_exists
#    description: "表示客户未持有安有护权益，值为空"
#    examples:
#      - query: "不是安有护的客户"
#        output: { field: zhenxiangRunEquityGrade, operator: NOT_EXISTS, value: "" }

  # ==================== 臻享家医权益等级 ====================

#  - id: zxjy_equity_grade
#    retrieval_text: >
#      臻享家医 臻享家医等级 臻享家医预达标 臻享家医已达标 家医权益
#      家医意向客户 家医V1达标客户 家医V2达标客户 家医v1达标客户 家医v2达标客户
#    field: zxjyEquityGrade
#    operator: MATCH
#    value_type: enum
#    enum_ref: zxjyEquityGrade
#    description: "表示臻享家医达标状态，如预达标/已达标；不表示开通时间、使用次数"
#    notes: "该字段只接受预达标/已达标两个标准值。家医V1达标客户、家医V2达标客户等说法都统一归一到已达标；“持有家医权益”不等于已达标。"
#    examples:
#      - query: "臻享家医已达标的客户"
#        output: {field: zxjyEquityGrade, operator: MATCH, value: "已达标"}
#      - query: "家医意向客户"
#        output: { field: zxjyEquityGrade, operator: MATCH, value: "预达标" }
#      - query: "家医V1达标客户"
#        output: { field: zxjyEquityGrade, operator: MATCH, value: "已达标" }
#    negative_examples:
#      - query: "臻享家医开通时间在今年的客户"
#        reason: "这是开通时间，不是家医达标状态"
#      - query: "使用过臻享家医服务的客户"
#        reason: "服务使用记录不等于达标状态"
#      - query: "持有臻享家医权益的客户"
#        reason: "这更接近权益是否存在语义；当前字段仅表达达标状态，不能凭空扩展为开通/持有关系"
#
#  - id: zxjy_equity_grade_customer
#    retrieval_text: >
#      臻享家医客户 家医客户 臻享家医名单 家医名单 臻享家医达标客户 家医达标客户 臻享客户
#      哪些是臻享家医客户 有没有家医客户 臻享家医预达标或已达标客户 预达标和已达标的家医客户
#    field: zxjyEquityGrade
#    operator: CONTAINS
#    value_type: enum
#    enum_ref: zxjyEquityGrade
#    description: "表示臻享家医客户范围，包括预达标和已达标两类客户"
#    notes: "当用户直接输入“臻享家医客户/家医客户”时，输出 CONTAINS=[预达标, 已达标]，不要只输出已达标。"
#    examples:
#      - query: "臻享家医客户"
#        output: { field: zxjyEquityGrade, operator: CONTAINS, value: [ "预达标", "已达标" ] }
#      - query: "家医客户"
#        output: { field: zxjyEquityGrade, operator: CONTAINS, value: [ "预达标", "已达标" ] }
#      - query: "臻享客户"
#        output: { field: zxjyEquityGrade, operator: CONTAINS, value: [ "预达标", "已达标" ] }

  # ==================== 产险产品 ====================

  - id: is_buy_pregnancy_car
    retrieval_text: >
      车险 非车险 是否有车险 购买车险 持有车险
    field: isBuyInsuranceCar
    operator: MATCH
    value_type: enum
    enum_ref: isBuyInsuranceCar
    enum_ordered: false
    description: "仅表示客户是车险还是非车险，不能判断是否有买产险；不表示购买时间、保单状态"
    examples:
      - query: "持有车险的客户"
        output: {field: isBuyInsuranceCar, operator: MATCH, value: "车险"}
      - query: "非车险的客户"
        output: {field: isBuyInsuranceCar, operator: MATCH, value: "非车险"}
    negative_examples:
      - query: "车险即将到期"
        reason: "这里主要是查询车险到期的时间，并不是单纯的看是否有车险"

  - id: car_insurance_expiry_date
    is_supported: false
    retrieval_text: >
      车险到期 车险到期时间 车险到期日 车险快到期 车险即将到期
      车险续保时间 车险哪天到期 车险什么时候到期
    field: carInsuranceMatuDateTime
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示车险保单到期时间，不表示是否持有车险，也不表示寿险保单到期时间"
    examples:
      - query: "今年车险到期的客户"
        output: {field: carInsuranceMatuDateTime, operator: RANGE, value: {min: "2026-01-01", max: "2026-12-31"}}
      - query: "车险即将到期的客户（当前2026-04-20）"
        output: {field: carInsuranceMatuDateTime, operator: RANGE, value: {min: "2026-04-20", max: "2026-05-20"}}
    negative_examples:
      - query: "持有车险的客户"
        reason: "这是是否持有车险，应映射到 isBuyInsuranceCar，不是车险到期时间"
      - query: "30天内寿险到期的客户"
        reason: "这是寿险保单到期时间，应映射到 validSinsMatuDateTime，不是 carInsuranceMatuDateTime"

  # ==================== 客户类型 ====================

  - id: is_buy_insurance
    is_supported: true
    retrieval_text: >
      客户类型 客户还是准客 买过保险 没有买过保险 是否投保 有没有买过保险 有保险 没有保险 没买保险 未配置保险 买了保险 投保了 已投保 有保险 配置了保险 全部客户 所有客户 全量客户
    field: isBuyInsurance
    operator: CONTAINS
    value_type: enum
    enum_ref: isBuyInsurance
    description: "客户类型；客户/准客=买过保险，用户=没有买过保险"
    notes: "客户=已签约，准客=潜在客户已接触，用户=未购买；买过保险→客户或准客，没有买过保险→用户。重要：只有查询明确包含‘有保险/没有保险/没保险/买过保险/未投保/是否投保/全部客户/所有客户/全量客户’等保险状态关键词时才输出此字段。‘客户’作为普通名词后缀（如‘姓X的客户’‘XX岁的客户’‘购买过XX产品的客户’）不表示保险状态，严禁输出此字段"
    examples:
      - query: "全部客户"
        output: { field: isBuyInsurance, operator: CONTAINS, value: [ "客户", "准客", "用户" ] }
      - query: "有保险的客户"
        output: { field: isBuyInsurance, operator: CONTAINS, value: [ "客户", "准客" ] }
      - query: "没有保险的客户"
        output: { field: isBuyInsurance, operator: CONTAINS, value: ["用户"] }
    negative_examples:
      - query: "5月盘客客户"
        reason: "“盘客”是业务动作，不表示买过保险或没买保险，不能映射到客户类型"
      - query: "姓张的客户"
        reason: "‘客户’在这里只是普通名词后缀，查询意图是找姓张的人，不是在问保险购买状态"
      - query: "购买过盛世金越的客户"
        reason: "‘客户’只是普通名词后缀，查询意图是限定产品而非保险类型；已通过产品字段限定时不额外输出客户类型"
      - query: "45岁以上的客户"
        reason: "‘客户’只是普通名词后缀，查询意图是年龄筛选，不是在问保险购买状态"

  # ==================== 是否产险客户 ====================

  - id: is_buy_pregnancy
    is_supported: true
    retrieval_text: >
      有无产险 是否有产险 有产险 无产险 是否持有产险 持有产险 未持有产险 没有产险
    field: isBuyProperty
    operator: MATCH
    value_type: enum
    enum_ref: isBuyProperty
    description: "是否产险客户"
    examples:
      - query: "有产险的客户"
        output: { field: isBuyProperty, operator: MATCH, value: "有购买" }
      - query: "没有买产险的客户"
        output: { field: isBuyProperty, operator: MATCH, value: "没有购买" }

  # ==================== 是否养老险客户 ====================

  - id: is_buy_pension
    is_supported: true
    retrieval_text: >
      是否养老险客户 买了养老险 没有买养老险 有养老险 无养老险 养老险投保 养老险客户
    field: isBuyPension
    operator: MATCH
    value_type: enum
    enum_ref: isBuyPension
    description: "是否养老险客户"
    examples:
      - query: "有养老险的客户"
        output: { field: isBuyPension, operator: MATCH, value: "有购买" }
      - query: "没有买养老险的客户"
        output: { field: isBuyPension, operator: MATCH, value: "没有购买" }

  # ==================== 是否健康险客户 ====================

  - id: is_buy_health
    is_supported: true
    retrieval_text: >
      是否健康险客户 买了健康险 没有买健康险 有健康险 无健康险 健康险投保
    field: isBuyHealth
    operator: MATCH
    value_type: enum
    enum_ref: isBuyHealth
    description: "是否健康险客户"
    examples:
      - query: "有健康险的客户"
        output: { field: isBuyHealth, operator: MATCH, value: "有购买" }
      - query: "没有买健康险的客户"
        output: { field: isBuyHealth, operator: MATCH, value: "没有购买" }

  # ==================== 家庭成员性别 ====================

  - id: family_client_sex
    retrieval_text: >
      家庭成员性别 成员性别 家属性别 家庭成员男 家庭成员女 有儿子 有女儿 儿子 女儿
    field: familyInfo.familyclientsex
    operator: MATCH
    value_type: enum
    enum_ref: familyInfo.familyclientsex
    description: "表示家庭成员性别，不表示客户本人性别；出现关系词时应与 familyInfo.familyrelation 组合"
    notes: "出现子女/父母/配偶等关系词时应同时输出familyInfo.familyrelation条件"
    examples:
      - query: "有儿子的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientsex, operator: MATCH, value: "男"}
      - query: "有女儿的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientsex, operator: MATCH, value: "女"}
    negative_examples:
      - query: "男性客户"
        reason: "这是客户本人性别，应映射到 clientSex，不是 familyInfo.familyclientsex"
      - query: "女性客户"
        reason: "这是客户本人性别，应映射到 clientSex，不是 familyInfo.familyclientsex"

  # ==================== 缴费期满 ====================

  - id: eff_app_end_date
    retrieval_text: >
      缴费期满 保费缴清 缴费结束 缴费到期 保单缴费期满
      本月缴费期满 下月缴费期满 今年缴费期满 即将缴费期满
    field: effAppEndDate
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示缴费期满时间，不表示保单到期时间、证件有效期"
    notes: "该字段表示缴费期满时间，不等于应缴日/应缴时间；若查询明确要求应缴日、缴费日而系统无对应字段，不应映射到此字段。无具体年份时默认当年；按日期粒度输出 yyyy-MM-dd；本月/下月按月初到月末展开，近30天按当前日期到未来30天展开"
    examples:
      - query: "本月缴费期满的客户（当前2026年3月）"
        output: {field: effAppEndDate, operator: RANGE, value: {min: "2026-03-01", max: "2026-03-31"}}
      - query: "下个月缴费期满的客户（当前2026年3月）"
        output: {field: effAppEndDate, operator: RANGE, value: {min: "2026-04-01", max: "2026-04-30"}}
      - query: "近30天需要缴费的客户（当前2026-03-23）"
        output: {field: effAppEndDate, operator: RANGE, value: {min: "2026-03-24", max: "2026-04-22"}}
      - query: "今年缴费期满的客户（当前2026年）"
        output: {field: effAppEndDate, operator: RANGE, value: {min: "2026-01-01", max: "2026-12-31"}}
    negative_examples:
      - query: "30天内寿险到期的客户"
        reason: "这是保单到期时间，应映射到 validSinsMatuDateTime，不是 effAppEndDate"
      - query: "证件即将到期的客户"
        reason: "这是证件有效期，应映射到 idValidDate，不是 effAppEndDate"
      - query: "近30天需要缴费的客户"
        reason: "这是应缴日，应映射到 polNoInfo.paytodate，不是 effAppEndDate"
      - query: "上个月刚缴完费的客户"
        reason: "这是上个月应缴/交费日期语义，应映射到 polNoInfo.paytodate，不是缴费期满 effAppEndDate"

  - id: eff_app_end_date_gt
    retrieval_text: >
      缴费期未满 尚未缴费期满 还没缴费期满 缴费未结束 保费未缴清
    field: effAppEndDate
    operator: GT
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示缴费期满时间晚于当前日期（不含等于）"
    notes: "‘缴费期未满/还没满/尚未期满’统一表示期满日晚于当前日期，使用GT；无明确日期时以当前日期为阈值。"
    examples:
      - query: "缴费期未满（不含当天）的客户（当前2026-04-12）"
        output: { field: effAppEndDate, operator: GT, value: "2026-04-13" }

  - id: eff_app_end_date_gte
    retrieval_text: >
      缴费期满日不早于 缴费期满日大于等于 缴费期满日在某日及以后
    field: effAppEndDate
    operator: GTE
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示缴费期满时间晚于或等于当前日期"
    notes: "仅在原文明确表达‘不早于/大于等于/及以后’时使用GTE；‘缴费期未满/还没满’属于GT，不使用本意图。"
    examples:
      - query: "缴费期满日不早于2026-04-12的客户"
        output: { field: effAppEndDate, operator: GTE, value: "2026-04-12" }
    negative_examples:
      - query: "30天内寿险到期的客户"
        reason: "这是保单到期时间，应映射到 validSinsMatuDateTime，不是 effAppEndDate"
      - query: "证件即将到期的客户"
        reason: "这是证件有效期，应映射到 idValidDate，不是 effAppEndDate"

  - id: eff_app_end_date_lt
    retrieval_text: >
      缴费期已满 已缴清 缴费已经结束
    field: effAppEndDate
    operator: LT
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示缴费期满时间早于当前日期（不含等于）"
    examples:
      - query: "客户缴费期已满（不含当天，当前2026-03-25）"
        output: {field: effAppEndDate, operator: LT, value: "2026-03-25"}

  - id: eff_app_end_date_lte
    retrieval_text: >
      缴费期已满 已缴清 缴费已经结束 缴费期结束
      缴费期满了 保费已缴清 缴费期满 完成缴费
    field: effAppEndDate
    operator: LTE
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示缴费期满时间早于或等于当前日期，不表示今天当天的精确日期匹配"
    examples:
      - query: "客户缴费期已满（当前2026-03-25）"
        output: {field: effAppEndDate, operator: LTE, value: "2026-03-25"}

  # ==================== 成员出生日期 ====================

  - id: family_client_birthday
    retrieval_text: >
      成员出生日期 家庭成员生日 家属出生日期 成员出生年份 出生日期 妻子出生日 丈夫出生日
      家庭成员出生 成员生日 子女生日 父母生日 妻子生日 丈夫生日 子女出生日期 父母出生日期 配偶出生日期
    field: familyInfo.familyclientbirthday
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示家庭成员出生日期，不表示客户本人出生日期；出现关系词时应与 familyInfo.familyrelation 组合"
    notes: "无具体年份时默认当年"
    examples:
      - query: "子女1990年出生的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientbirthday, operator: RANGE, value: {min: "1990-01-01 00:00:00", max: "1990-12-31 23:59:59"}}
    negative_examples:
      - query: "1990年出生的客户"
        reason: "这是客户本人出生日期，应映射到 clientBirthday，不是 familyInfo.familyclientbirthday"

  - id: family_client_birthday_gte
    retrieval_text: >
      家庭成员出生日期及以后 家庭成员出生日期不早于 家庭成员出生日期大于等于
      子女出生日期及以后 父母出生日期及以后 配偶出生日期及以后
    field: familyInfo.familyclientbirthday
    operator: GTE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示家庭成员出生日期晚于或等于指定日期；关系词应同时生成家庭关系条件"
    examples:
      - query: "父母在1954年及以后出生的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["父母"]}
            - {field: familyInfo.familyclientbirthday, operator: GTE, value: "1954-01-01 00:00:00"}

  - id: family_client_birthday_gt
    retrieval_text: >
      家庭成员出生日期之后 家庭成员出生日期大于 家庭成员出生日期晚于
      子女出生日期之后 父母出生日期之后 配偶出生日期之后
    field: familyInfo.familyclientbirthday
    operator: GT
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示家庭成员出生日期严格晚于指定日期；关系词应同时生成家庭关系条件"
    examples:
      - query: "子女出生日大于2025年5月1日"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientbirthday, operator: GT, value: "2025-05-01 23:59:59"}

  - id: family_client_birthday_lt
    retrieval_text: >
      家庭成员出生日期之前 家庭成员出生日期小于 家庭成员出生日期早于
      子女出生日期之前 父母出生日期之前 配偶出生日期之前
    field: familyInfo.familyclientbirthday
    operator: LT
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "表示家庭成员出生日期严格早于指定日期；关系词应同时生成家庭关系条件"
    examples:
      - query: "爱人在1991年之前出生的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["配偶"]}
            - {field: familyInfo.familyclientbirthday, operator: LT, value: "1991-01-01 00:00:00"}

  - id: family_client_age
    retrieval_text: >
      家庭成员年龄 成员年龄 子女年龄 子女几岁 孩子几岁 儿子年龄 女儿年龄 家里有70岁老人
      父母年龄 配偶年龄 成员多少岁 子女多大 孩子多大 年龄  年纪大 老年 中老年
      子女5岁 孩子10岁 成员年龄范围 未成年子女 成年子女 家中小孩大的 家里孩子大的 孩子大的 小孩大的 家属年龄
    field: familyInfo.familyclientage
    operator: RANGE
    value_type: numeric
    unit: "岁，直接取数字；系统会自动将年龄转换为 familyInfo.familyclientbirthday 日期范围"
    description: "表示家庭成员年龄，不表示客户本人年龄；出现关系词时应与 familyInfo.familyrelation 组合"
    notes: "年龄会自动转换为出生日期范围（familyInfo.familyclientbirthday），语义年龄：未成年0-17，青年18-35；出现子女/父母/配偶等关系词时应同时输出familyInfo.familyrelation条件。‘未成年子女/未成年孩子’是不可拆分的复合语义，必须同时输出familyInfo.familyrelation=子女与familyInfo.familyclientage RANGE 0~17，禁止只输出子女关系。即使同句还有客户价值、温度、险种、保单等多个条件，也不得遗漏家庭成员年龄。"
    examples:
      - query: "子女5到10岁的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientage, operator: RANGE, value: {min: 5, max: 10}}
      - query: "子女未成年的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientage, operator: RANGE, value: {min: 0, max: 17}}
      - query: "家里有70岁老人"
        output: {field: familyInfo.familyclientage, operator: RANGE, value: {min: 70, max: 70}}
    negative_examples:
      - query: "45岁以上的客户"
        reason: "这是客户本人年龄，应映射到 clientAge，不是 familyInfo.familyclientage"

  - id: family_client_age_gt
    retrieval_text: >
      家庭成员年龄 成员年龄 子女年龄 父母年龄 配偶年龄
      孩子10岁以上 子女10岁以上 父母70岁以上 成员年龄大于 成员年龄超过
    field: familyInfo.familyclientage
    operator: GT
    value_type: numeric
    unit: "岁，直接取数字；系统会自动将年龄转换为 familyInfo.familyclientbirthday 日期范围"
    description: "表示家庭成员年龄（大于），不表示客户本人年龄；出现关系词时应与 familyInfo.familyrelation 组合"
    notes: "年龄会自动转换为出生日期范围（familyInfo.familyclientbirthday）；出现子女/父母/配偶等关系词时应同时输出familyInfo.familyrelation条件"
    examples:
      - query: "孩子10岁以上（不含10岁）的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientage, operator: GT, value: 10}

  - id: family_client_age_gte
    retrieval_text: >
      家庭成员年龄 成员年龄 子女年龄 父母年龄 配偶年龄 有老人 家里有老人
      孩子10岁及以上 子女10岁及以上 父母70岁及以上 成员年龄大于等于
    field: familyInfo.familyclientage
    operator: GTE
    value_type: numeric
    unit: "岁，直接取数字；系统会自动将年龄转换为 familyInfo.familyclientbirthday 日期范围"
    description: "表示家庭成员年龄（大于等于），不表示客户本人年龄；出现关系词时应与 familyInfo.familyrelation 组合"
    notes: "年龄会自动转换为出生日期范围（familyInfo.familyclientbirthday）；出现子女/父母/配偶等关系词时应同时输出familyInfo.familyrelation条件"
    examples:
      - query: "孩子10岁及以上的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientage, operator: GTE, value: 10}
      - query: "孩子10岁以上的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientage, operator: GTE, value: 10}
      - query: "父母70岁及以上的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["父母"]}
            - {field: familyInfo.familyclientage, operator: GTE, value: 70}
      - query: "家里有孩子10岁及以上的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientage, operator: GTE, value: 10}
      - query: "有老人的客户"
        output:
          query_logic: AND
          conditions:
            - { field: familyInfo.familyclientage, operator: GTE, value: 55 }
    negative_examples:
      - query: "45岁及以上的客户"
        reason: "这是客户本人年龄，应映射到 clientAge，不是 familyInfo.familyclientage"

  - id: family_client_age_lt
    retrieval_text: >
      家庭成员年龄以下 子女年龄小于 父母年龄低于 配偶年龄不高于
      孩子10岁以下 子女10岁以下 父母60岁以下
    field: familyInfo.familyclientage
    operator: LT
    value_type: numeric
    unit: "岁，直接取数字；系统会自动将年龄转换为 familyInfo.familyclientbirthday 日期范围"
    description: "表示家庭成员年龄（小于），不表示客户本人年龄；出现关系词时应与 familyInfo.familyrelation 组合"
    notes: "年龄会自动转换为出生日期范围（familyInfo.familyclientbirthday）"
    examples:
      - query: "孩子10岁以下（不含10岁）的客户"
        output:
          query_logic: AND
          conditions:
            - { field: familyInfo.familyrelation, operator: CONTAINS, value: [ "子女" ] }
            - { field: familyInfo.familyclientage, operator: LT, value: 10 }

  - id: family_client_age_lte
    retrieval_text: >
      家庭成员年龄不超过 成员年龄及以下 子女年龄小于等于 父母年龄低于或等于 配偶年龄不高于
      孩子10岁及以下 子女10岁及以下 父母60岁及以下
    field: familyInfo.familyclientage
    operator: LTE
    value_type: numeric
    unit: "岁，直接取数字；系统会自动将年龄转换为 familyInfo.familyclientbirthday 日期范围"
    description: "表示家庭成员年龄（小于等于），不表示客户本人年龄；出现关系词时应与 familyInfo.familyrelation 组合"
    notes: "年龄会自动转换为出生日期范围（familyInfo.familyclientbirthday）；出现子女/父母/配偶等关系词时应同时输出 familyInfo.familyrelation 条件"
    examples:
      - query: "孩子10岁及以下的客户"
        output:
          query_logic: AND
          conditions:
            - { field: familyInfo.familyrelation, operator: CONTAINS, value: [ "子女" ] }
            - { field: familyInfo.familyclientage, operator: LTE, value: 10 }
      - query: "孩子10岁以下的客户"
        output:
          query_logic: AND
          conditions:
            - { field: familyInfo.familyrelation, operator: CONTAINS, value: [ "子女" ] }
            - { field: familyInfo.familyclientage, operator: LTE, value: 10 }
      - query: "父母60岁及以下的客户"
        output:
          query_logic: AND
          conditions:
            - { field: familyInfo.familyrelation, operator: CONTAINS, value: [ "父母" ] }
            - { field: familyInfo.familyclientage, operator: LTE, value: 60 }
      - query: "配偶年龄不超过40岁的客户"
        output:
          query_logic: AND
          conditions:
            - { field: familyInfo.familyrelation, operator: CONTAINS, value: [ "配偶" ] }
            - { field: familyInfo.familyclientage, operator: LTE, value: 40 }
    negative_examples:
      - query: "45岁以下的客户"
        reason: "这是客户本人年龄，应映射到 clientAge，不是 familyInfo.familyclientage"

  # ==================== 学历 ====================

  - id: education_exact
    retrieval_text: >
      学历 文凭 毕业 大专 本科 研究生 硕士 博士 高中 中专 初中 小学
      学历等级 受教育程度
    field: education
    operator: MATCH
    value_type: enum
    enum_ref: education
    description: "表示客户本人学历的精确枚举匹配。"
    notes: "小学/初中/高中/本科等若描述的是客户本人学历，映射到 education；若描述孩子或家庭成员上学阶段，不应映射到客户本人学历。"
    examples:
      - query: "大学本科学历的客户"
        output: {field: education, operator: MATCH, value: "大学本科生"}
      - query: "硕士研究生的客户"
        output: {field: education, operator: MATCH, value: "硕士研究生"}
    negative_examples:
      - query: "孩子在上小学的客户"
        reason: "这里的小学是孩子，不是客户本人"
      - query: "南昌大学"
        reason: "这里的大学是机构地址名称，不是客户学历；应只输出联系地址条件"
      - query: "联系地址为北京大学的客户"
        reason: "北京大学整体是地址值，不能因包含大学而输出大学本科生学历"

  - id: education_gte
    retrieval_text: >
      本科学历以上 学历及以上 学历及以上 本科及以上 研究生及以上 高学历 高学历客户 本科或硕士 高中或专科 本科（包含）以上 本科以上学历
    field: education
    operator: CONTAINS
    value_type: enum
    show_enum_in_prompt: true
    enum_ordered: true
    description: "表示学历等级范围；“以上”和“及以上”含当前值，例如：本科以上和本科及以上均包含大学本科生"
    notes: "学历从低到高：小学以下<小学<初中<中专<高中<大学专科<大学本科生<硕士研究生<博士研究生<博士后"
    examples:
      - query: "本科学历及以上客户"
        output: {field: education, operator: CONTAINS, value: ["大学本科生", "硕士研究生", "博士研究生", "博士后"]}
      - query: "本科学历以上客户"
        output: { field: education, operator: CONTAINS, value: ["大学本科生", "硕士研究生", "博士研究生", "博士后"] }
      - query: "硕士（不含）以上客户"
        output: { field: education, operator: CONTAINS, value: [ "博士研究生", "博士后" ] }
    negative_examples:
      - query: "孩子在上小学的客户"
        reason: "这里的小学是孩子，不是客户本人"

  - id: education_not_contains
    retrieval_text: >
      不是本科学历 不是硕士学历 没有博士学历 不属于高学历客户
    field: education
    operator: NOT_CONTAINS
    value_type: enum
    show_enum_in_prompt: true
    description: "表示客户不属于某个学历或某组学历，不表示学历字段为空"
    examples:
      - query: "不s是本科学历的客户"
        output: { field: education, operator: NOT_CONTAINS, value: [ "大学本科生" ] }
      - query: "不属于高学历客户"
        output: { field: education, operator: NOT_CONTAINS, value: [ "大学本科生", "硕士研究生", "博士研究生", "博士后" ] }

  # ==================== 成员关系 ====================

  - id: family_relation
    retrieval_text: >
      成员关系 家庭关系 家庭成员关系 配偶 父母 子女 兄弟姐妹
      祖父母 孙子女 法定关系 家庭成员
    field: familyInfo.familyrelation
    operator: CONTAINS
    value_type: enum
    enum_ref: familyInfo.familyrelation
    description: "表示客户家庭中存在的成员关系。关系词前出现的客户姓名仍是客户本人姓名，不得因此映射为家庭成员姓名。"
    notes: "涉及家庭成员属性时，familyInfo.familyrelation可与年龄、出生日期、性别、姓名等条件组合输出；但只有关系词直接引出家庭成员姓名时才组合 familyInfo.familyclientname。‘X有子女/父母/配偶’只输出关系条件，X由开放字段模型解析为客户本人姓名；但‘未成年子女/未成年孩子’明确带有年龄属性，必须同时输出familyInfo.familyclientage RANGE 0~17，不能只输出关系条件。"
    examples:
      - query: "有子女的客户"
        output: {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
      - query: "家里有爸妈的客户"
        output: { field: familyInfo.familyrelation, operator: CONTAINS, value: [ "父母" ] }
      - query: "顾清禾有子女的客户"
        output: {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
      - query: "家里有未成年子女的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientage, operator: RANGE, value: {min: 0, max: 17}}
      - query: "有女儿"
        output:
          query_logic: AND
          conditions:
            - { field: familyInfo.familyrelation, operator: CONTAINS, value: [ "子女" ] }
            - { field: familyInfo.familyclientsex, operator: MATCH, value: '女' }
      - query: "有儿子"
        output:
          query_logic: AND
          conditions:
            - { field: familyInfo.familyrelation, operator: CONTAINS, value: [ "子女" ] }
            - { field: familyInfo.familyclientsex, operator: MATCH, value: '男' }

  # ==================== 家庭成员姓名 ====================

  - id: family_client_name
    retrieval_text: >
      家庭成员姓名 成员叫 家属叫 家庭成员名字 成员名字
      子女叫 女儿叫 儿子叫 父母叫 爸爸叫 妈妈叫 配偶叫 爱人叫
    field: familyInfo.familyclientname
    operator: MATCH
    value_type: extract
    description: "表示家庭成员姓名，不表示客户本人姓名。仅当家庭成员、家属、女儿、儿子、父母、配偶等角色词直接引出或修饰姓名时使用。"
    notes: "角色归属必须有直接语法证据，例如“女儿叫X”“家属姓名为X”。仅出现“X有子女/父母/配偶”时，X是客户本人姓名，只输出 familyInfo.familyrelation，不输出 familyInfo.familyclientname。关系词用于明确成员身份时，优先输出关系+姓名；除非原文独立查询性别，否则不要再从‘女儿/儿子’推导冗余性别条件。"
    examples:
      - query: "家庭成员叫张三的客户"
        output: {field: familyInfo.familyclientname, operator: MATCH, value: "张三"}
      - query: "子女叫张三的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["子女"]}
            - {field: familyInfo.familyclientname, operator: MATCH, value: "张三"}
      - query: "爱人叫李四的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: CONTAINS, value: ["配偶"]}
            - {field: familyInfo.familyclientname, operator: MATCH, value: "李四"}
      - query: "女儿叫顾清禾的客户"
        output:
          query_logic: AND
          conditions:
            - {field: familyInfo.familyrelation, operator: MATCH, value: "子女"}
            - {field: familyInfo.familyclientname, operator: MATCH, value: "顾清禾"}
    negative_examples:
      - query: "叫张三的客户"
        reason: "这是客户本人姓名，应映射到 searchClientName，不是 familyInfo.familyclientname"
      - query: "顾清禾有子女的客户"
        reason: "顾清禾是客户本人；有子女只产生 familyInfo.familyrelation，不产生家庭成员姓名"
      - query: "客户姓名为顾清禾且有女儿"
        reason: "顾清禾由客户姓名字段处理，女儿只表示家庭关系"

  # ==================== 家庭成员手机号 ====================

  - id: family_client_mobile
    retrieval_text: >
      家庭成员手机号 成员手机号 家属手机号 家庭成员电话 成员电话 家属电话
      子女手机号 父母手机号 配偶手机号 家里人手机号
    field: familyInfo.familyclientmobile
    operator: MATCH
    value_type: extract
    description: "表示家庭成员手机号，不表示客户本人手机号；出现关系词时应与 familyInfo.familyrelation 组合"
    notes: "出现子女/父母/配偶等关系词时应同时输出familyInfo.familyrelation条件。手机号一定是由1-11为数字组成的。"
    examples:
      - query: "家庭成员手机号是13800138000的客户"
        output: { field: familyInfo.familyclientmobile, operator: MATCH, value: "13800138000" }
      - query: "子女手机号是13800138000的客户"
        output:
          query_logic: AND
          conditions:
            - { field: familyInfo.familyrelation, operator: CONTAINS, value: [ "子女" ] }
            - { field: familyInfo.familyclientmobile, operator: MATCH, value: "13800138000" }
      - query: "父母手机号是13900139000的客户"
        output:
          query_logic: AND
          conditions:
            - { field: familyInfo.familyrelation, operator: CONTAINS, value: [ "父母" ] }
            - { field: familyInfo.familyclientmobile, operator: MATCH, value: "13900139000" }
    negative_examples:
      - query: "手机号是13800138000的客户"
        reason: "这是客户本人手机号，应映射到 clientMobile，不是 familyInfo.familyclientmobile"

  # ==================== 保单号 ====================

  - id: policy_no
    retrieval_text: >
      保单号 保单编号 保险单号 保险单编号
      保单号匹配 保单号等于 保单号为 按保单号查询
      按保单号查客户 保单号码 保险单号码 GP保单 GP开头保单号
    field: polNo
    operator: MATCH
    value_type: extract
    description: "表示保单号，不表示客户编号。标准格式包括：P或A开头后跟15至17位数字或字母（兼容历史数据中的14位）；GP开头后跟14位数字或字母；在明确写出“保单号”时也支持15至17位纯数字。字母统一转为大写"
    notes: "本条只处理单个保单号，使用MATCH。保单号一定由数字或字母组成，不可能为中文；多个完整保单号应使用policy_no_list知识的CONTAINS。"
    examples:
      - query: "保单号以P2026开头的客户"
        output: {field: polNo, operator: MATCH, value: "P2026", match_mode: "prefix"}
      - query: "保单号后四位0088的客户"
        output: {field: polNo, operator: MATCH, value: "0088", match_mode: "suffix"}
      - query: "客户保单尾号0899"
        output: {field: polNo, operator: MATCH, value: "0899", "match_mode": "suffix"}
      - query: "P008*****0080"
        output: {field: polNo, operator: MATCH, value: "0080", "match_mode": "suffix"}
      - query: "PC9000CC08000000"
        output: {field: polNo, operator: MATCH, value: "PC9000CC08000000"}
    negative_examples:
      - query: "杨傲雪保单号"
        reason: "保单号必须是由数字+字母组成的，不能是中文"

  - id: policy_no_list
    retrieval_text: >
      多个保单号 批量保单号 一批保单号 保单号列表 保单号清单 查询以下保单号
      多个保单编号 批量保单编号 多个保险单号 批量保险单号
      保单号逗号分隔 保单号换行分隔 保单号批量查询
    field: polNo
    operator: CONTAINS
    value_type: extract
    description: "表示按多个完整保单号批量查询；多个保单号属于同一候选集合"
    notes: "仅当查询中包含至少两个完整保单号时使用CONTAINS，value必须是去重后的保单号数组，并将英文字母统一转为大写。保单号可由英文逗号、中文逗号、顿号、分号、竖线、换行或Tab分隔。纯数字保单号必须有明确的保单号字段词。单个完整保单号仍使用policy_no的MATCH。"
    examples:
      - query: "P12345678901234,A123456789012345,GP12345678901234"
        output: {field: polNo, operator: CONTAINS, value: ["P12345678901234", "A123456789012345", "GP12345678901234"]}
      - query: "查询以下保单号：123456789012345，9876543210987654"
        output: {field: polNo, operator: CONTAINS, value: ["123456789012345", "9876543210987654"]}
    negative_examples:
      - query: "保单号P12345678901234"
        reason: "只有一个完整保单号，应使用policy_no的MATCH"
      - query: "123456789012345,9876543210987654"
        reason: "纯数字列表没有明确说明是保单号，不能仅凭格式映射到polNo"

  # ==================== 车牌号 ====================

  - id: license_plate_no
    is_supported: false
    retrieval_text: >
      车牌号 车牌号码 车辆牌照号 汽车牌照号 按车牌号查询
      车牌号匹配 车牌号等于 车牌号为
    field: licensePlateNo
    operator: MATCH
    value_type: extract
    description: "表示车辆号牌号码，非枚举字段；不表示车架号、发动机号或车险保单号。字母统一转为大写，如苏A80789、贵J00990"
    examples:
      - query: "车牌号为苏A80789的客户"
        output: { field: licensePlateNo, operator: MATCH, value: "苏A80789" }
      - query: "按车牌号贵J00990查客户"
        output: { field: licensePlateNo, operator: MATCH, value: "贵J00990" }
    negative_examples:
      - query: "车架号为LSV12345678901234的客户"
        reason: "这是车架号，不是车牌号，不能映射到 licensePlateNo"

  # ==================== 年收入 ====================

  - id: annual_income_gte
    is_supported: false
    retrieval_text: >
      年收入 年薪 年入 年收入以上 年薪超过 年收入大于
    field: annual_income
    operator: GTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元，不需要换算"
    description: "客户个人年收入，数值型，单位元"
    examples:
      - query: "年收入20万以上的客户"
        output: {field: annual_income, operator: GTE, value: 200000}
      - query: "年薪超过50万的客户"
        output: {field: annual_income, operator: GTE, value: 500000}
      - query: "年薪超过50的客户"
        output: { field: annual_income, operator: GTE, value: 50 }

  - id: annual_income_lte
    is_supported: false
    retrieval_text: >
      年收入以下 年薪不超过 年收入小于 年入低于
    field: annual_income
    operator: LTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元，不需要换算"
    description: "客户个人年收入上限筛选"
    examples:
      - query: "年收入10万以下的客户"
        output: {field: annual_income, operator: LTE, value: 100000}
      - query: "年收入100000以下的客户"
        output: { field: annual_income, operator: LTE, value: 100000 }

  - id: annual_income_range
    is_supported: false
    retrieval_text: >
      年收入区间 年薪范围 年收入在XX到XX之间
    field: annual_income
    operator: RANGE
    value_type: numeric
    unit: "元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元"
    description: "客户个人年收入区间筛选"
    examples:
      - query: "年收入10到30万的客户"
        output: {field: annual_income, operator: RANGE, value: {min: 100000, max: 300000}}
      - query: "年收入100000到300000的客户"
        output: { field: annual_income, operator: RANGE, value: { min: 100000, max: 300000 } }

  # ==================== 家庭收入 ====================

  - id: household_income_gte
    is_supported: false
    retrieval_text: >
      家庭收入 家庭年收入 家庭年入 家庭收入以上 家庭年收入超过
    field: household_income
    operator: GTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元"
    description: "家庭年收入，数值型，单位元"
    examples:
      - query: "家庭年收入30万以上的客户"
        output: {field: household_income, operator: GTE, value: 300000}
      - query: "家庭年收入100000以上的客户"
        output: { field: household_income, operator: GTE, value: 100000 }

  - id: household_income_lte
    is_supported: false
    retrieval_text: >
      家庭收入以下 家庭年收入不超过 家庭收入低于
    field: household_income
    operator: LTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元"
    description: "家庭年收入上限筛选，数值型，单位元。"
    notes: "家庭收入不同于客户个人年收入；个人年收入应映射到 annual_income。"
    examples:
      - query: "家庭收入20万以下的客户"
        output: {field: household_income, operator: LTE, value: 200000}
      - query: "家庭收入200000以下的客户"
        output: { field: household_income, operator: LTE, value: 200000 }

  # ==================== 资产规模 ====================

  - id: asset_scale_gte
    is_supported: false
    retrieval_text: >
      资产规模 资产超过 资产大于 资产以上 净资产 资产量
    field: asset_scale
    operator: GTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元"
    description: "客户资产规模，数值型，单位元"
    examples:
      - query: "资产规模100万以上的客户"
        output: {field: asset_scale, operator: GTE, value: 1000000}
      - query: "资产规模1000000以上的客户"
        output: { field: asset_scale, operator: GTE, value: 1000000 }

  - id: asset_scale_lte
    is_supported: false
    retrieval_text: >
      资产规模以下 资产不超过 资产低于
    field: asset_scale
    operator: LTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元"
    description: "客户资产规模上限筛选，数值型，单位元。"
    notes: "资产规模不同于年收入或家庭收入；金额单位按 unit 说明换算。"
    examples:
      - query: "资产规模50万以下的客户"
        output: {field: asset_scale, operator: LTE, value: 500000}
      - query: "资产规模500000以下的客户"
        output: { field: asset_scale, operator: LTE, value: 500000 }

  # ==================== 保单生效日 ====================

  - id: policies_effective_date_range
    is_supported: true
    retrieval_text: >
      保单生效日 保单生效时间 保单什么时候生效 保单生效日期 本月生效保单 今年生效 近N天生效 近一周生效 近一个月生效
      新生效保单 刚生效保单 生效保单 生效日期排序 保单生效日从早到晚 保单生效日从晚到早 签单时间 签约时间 成交时间 成交日期 签单客户 签约客户 成交客户
      近N年签单 最近N年签约 过去N年成交 这N年签单 N年内成交
    field: polNoInfo.poleffdate
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "业务口径中的签单、签约和成交时间统一映射为保单生效日期范围，不表示投保申请日期或承保日期"
    notes: "时间年数由 L2 通用模板动态提取，支持阿拉伯数字及中文数字表达；承保时间应映射到 latelyUndwrtSegTime，不映射到本字段。"
    examples:
      - query: "本月保单生效的客户"
        output: { field: polNoInfo.poleffdate, operator: RANGE, value: { min: "2026-05-01 00:00:00", max: "2026-05-31 23:59:59" } }
      - query: "今年新生效保单的客户"
        output: { field: polNoInfo.poleffdate, operator: RANGE, value: { min: "2026-01-01 00:00:00", max: "2026-12-31 23:59:59" } }
      - query: "近7天生效的保单"
        output: { field: polNoInfo.poleffdate, operator: RANGE, value: { min: "2026-05-02 00:00:00", max: "2026-05-09 23:59:59" } }
    negative_examples:
      - query: "2026年9月过周年日的客户"
        reason: "原文明确是周年日，应映射到 effAnniversaryDate 并输出MM-dd，不是保单生效日"
      - query: "近两年承保的客户"
        reason: "这是承保日期，应映射到 latelyUndwrtSegTime"
      - query: "近两年投保的客户"
        reason: "这是投保日期，应映射到 policies_insure_date"
  
  - id: policies_effective_date_gte
    is_supported: true
    retrieval_text: >
      保单生效日 及以上 不低于 大于等于 之后 不小于
    field: polNoInfo.poleffdate
    operator: GTE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "保单生效日期，≥ 某时间及之后"
    examples:
      - query: "2025年及之后生效的保单"
        output: { field: polNoInfo.poleffdate, operator: GTE, value: "2025-01-01 00:00:00" }

  - id: policies_effective_date_gt
    is_supported: true
    retrieval_text: >
      保单生效日 之后 以上 超过 大于 晚于 保单还未生效 还未生效的保单 未生效的保单
    field: polNoInfo.poleffdate
    operator: GT
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "保单生效日期，＞ 严格晚于某时间"
    examples:
      - query: "2025年之后生效的保单"
        output: { field: polNoInfo.poleffdate, operator: GT, value: "2025-01-01 00:00:00" }
      - query: "保单还未生效的客户（当前时间为2026-05-11）"
        output: { field: polNoInfo.poleffdate, operator: GT, value: "2026-05-11 00:00:00" }

  - id: policies_effective_date_lte
    is_supported: true
    retrieval_text: >
      保单生效日 及以下 不超过 不大于 之前 小于等于 保单已生效
    field: polNoInfo.poleffdate
    operator: LTE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "保单生效日期，≤ 某时间及之前"
    examples:
      - query: "2025年及之前生效的保单"
        output: { field: polNoInfo.poleffdate, operator: LTE, value: "2025-12-31 23:59:59" }
      - query: "保单已生效的客户（当前时间为2026-05-11）"
        output: { field: polNoInfo.poleffdate, operator: LTE, value: "2026-05-11 23:59:59" }

  - id: policies_effective_date_lt
    is_supported: true
    retrieval_text: >
      保单生效日 之前 以下 早于 小于 低于
    field: polNoInfo.poleffdate
    operator: LT
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "保单生效日期，＜ 严格早于某时间"
    examples:
      - query: "2025年之前生效的保单"
        output: { field: polNoInfo.poleffdate, operator: LT, value: "2025-01-01 00:00:00" }

  - id: policies_effective_date_exists
    is_supported: true
    retrieval_text: >
      保单生效日 有生效日期 生效日不为空 存在生效日 生效保单 新生效保单 生效日期排序
    field: polNoInfo.poleffdate
    operator: EXISTS
    value_type: exists
    description: "保单生效日期，判断是否存在"
    examples:
      - query: "有生效日期的保单"
        output: { field: polNoInfo.poleffdate, operator: EXISTS, value: "" }
      - query: "自己名下已签过单的老客户"
        output: { field: polNoInfo.poleffdate, operator: EXISTS, value: "" }

  # ==================== 客户添加日 ====================

  - id: dateCreated
    is_supported: true
    retrieval_text: >
      客户添加日 客户添加时间 添加日期 建档日期 客户录入时间 客户创建时间 新添加的客户 新增客户 最近新增的客户 新客户 新客
      某年后添加 某年前添加 有添加日期 没有添加日期 添加时间不为空 添加时间为空 新加的客户
    field: dateCreated
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "客户添加到系统中的日期时间；未指定其他时间范围时，‘新客户/新客’指客户添加日在近1个月内"
    examples:
      - query: "本月添加的客户"
        output: { field: dateCreated, operator: RANGE, value: { min: "2026-03-01 00:00:00", max: "2026-03-31 23:59:59" } }
      - query: "2026年新添加的客户"
        output: { field: dateCreated, operator: RANGE, value: { min: "2026-01-01 00:00:00", max: "2026-12-31 23:59:59" } }
      - query: "新客户（当前时间为2026-07-17）"
        output: { field: dateCreated, operator: RANGE, value: { min: "2026-06-17 00:00:00", max: "2026-07-17 23:59:59" } }
      - query: "今年新加的客户名单（当前时间为2026-05-11）"
        output: { field: dateCreated, operator: RANGE, value: { min: "2026-01-01 00:00:00", max: "2026-12-31 23:59:59" } }
      - query: "2026年6-9月客户名单"
        output: { field: dateCreated, operator: RANGE, value: { min: "2026-06-01 00:00:00", max: "2026-09-30 23:59:59" } }

  - id: date_created_gte
    is_supported: true
    retrieval_text: >
      客户添加日在某日及以后 客户添加时间不早于 某年及以后添加 某年之后添加
    field: dateCreated
    operator: GTE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "客户添加时间晚于或等于给定时间"
    examples:
      - query: "2025年及以后添加的客户"
        output: {field: dateCreated, operator: GTE, value: "2025-01-01 00:00:00"}

  # ==================== 保单状态 ====================

  - id: policies_status_exact
    is_supported: true
    retrieval_text: >
      保单状态为 保单状态是 明确保单状态 缴费有效 交费有效 退保 停效 犹豫期退保 到期终止
      展期 交清 减额交清 转换终止 失效 死亡理赔 等待续保 自垫有效 自垫交清 免交
    field: polNoInfo.polStatus
    operator: MATCH
    value_type: enum
    enum_ref: polNoInfo.polStatus
    show_enum_in_prompt: true
    enum_ordered: false
    description: "表示用户明确指定的单个保单状态。"
    notes: "明确的单个状态使用MATCH；缴费有效与交费有效归一为交费有效。多个候选状态或泛化有效保单不属于本意图。"
    examples:
      - query: "缴费有效保单客户"
        output: { field: polNoInfo.polStatus, operator: MATCH, value: "交费有效" }
      - query: "等待续保的客户"
        output: { field: polNoInfo.polStatus, operator: MATCH, value: "等待续保" }
      - query: "犹豫期退保的客户"
        output: { field: polNoInfo.polStatus, operator: MATCH, value: "犹豫期退保" }
    negative_examples:
      - query: "有效保单客户"
        reason: "有效保单是六个状态组成的固定业务集合，应使用policies_status_contains"

  - id: policies_status_contains
    is_supported: true
    retrieval_text: >
      有效保单 有有效保单 有效保单客户 生效保单 保单生效中 保单状态有效
      多个保单状态 保单状态包含 保单状态为多个 退保或犹豫期退保
    field: polNoInfo.polStatus
    operator: CONTAINS
    value_type: enum
    show_enum_in_prompt: true
    description: "表示多个保单状态候选，或由多个状态组成的固定业务集合。"
    notes: "泛化有效保单、保单生效、保单状态有效属于固定业务集合，展开为交费有效、自垫交清、交清、减额交清、免交、自垫有效六个状态并使用CONTAINS。只有原文表达多个候选时，其他状态才使用CONTAINS；明确单个状态使用policies_status_exact的MATCH。"
    examples:
      - query: "有效保单"
        output: { field: polNoInfo.polStatus, operator: CONTAINS, value: [ "交费有效", "自垫交清", "交清", "减额交清", "免交", "自垫有效" ] }
      - query: "退保或犹豫期退保的客户"
        output: { field: polNoInfo.polStatus, operator: CONTAINS, value: ["退保", "犹豫期退保"] }

  - id: policies_status_not_contains
    is_supported: true
    retrieval_text: >
      没有退保保单 没有停效保单 不包含缴费有效保单 不是失效保单客户
    field: polNoInfo.polStatus
    operator: NOT_CONTAINS
    value_type: enum
    show_enum_in_prompt: true
    description: "表示客户保单状态中不包含某类状态；有效保单=保单生效=保单状态有效=保单状态包括：交费有效、自垫交清、交清、减额交清、免交、自垫有效；缴费有效保单=交费有效保单=交费有效"
    examples:
      - query: "没有退保保单的客户"
        output: { field: polNoInfo.polStatus, operator: NOT_CONTAINS, value: [ "退保" ] }
      - query: "没有停效保单的客户"
        output: { field: polNoInfo.polStatus, operator: NOT_CONTAINS, value: [ "停效" ] }


  # ==================== 投保日期 ====================

  - id: policies_insure_date
    is_supported: false
    retrieval_text: >
      投保日期 投保时间 什么时候投保 投保年份 今年投保 去年投保 本月投保
      最近半年投保 近半年投保 最近一年投保 近一年投保 过去半年投保 过去一年投保
      买保险日期 今年买保险 今年买过保险 今年购买保险 近一年买保险 近半年买保险
      最近半年买保险 半年内购买保险 买保险时间 什么时候买保险 买保险年份
      去年买保险 去年购买保险 去年购买险种 去年购买某保险 本月买保险
    field: policies_insure_date
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "保单投保日期，嵌套字段；‘去年购买/买了/买过/投保某险种’中的‘去年’也是投保日期条件。该字段当前不支持搜索，但必须解析以便给出不支持提示"
    notes: "投保日期与承保日期、生效日期不同，任何‘时间范围+投保/买保险/购买保险’都必须识别为本不支持字段，不能改写为 latelyUndwrtSegTime 或 polNoInfo.poleffdate。若原文同时表达已经投保/买过保险，购买状态可另外输出 isBuyInsurance，时间条件仍由本字段产生不支持提示。‘最近一年买保险、最近半年投保’之所以表示过去，是因为投保/买过是已经发生的事件；该方向规则只属于投保日期，不得用于‘积分即将过期、保单将要到期、证件快要失效’等未来事件。本月取当月1日至月末；下月取下月1日至月末；下周取下周一至周天；未来一周取今天至往后顺延6天；未来一个月取今天至往后延顺29天。"
    examples:
      - query: "今年投保的客户（当前时间为2026-04-29）"
        output: {field: policies_insure_date, operator: RANGE, value: {min: "2026-01-01 00:00:00", max: "2026-12-31 23:59:59"}}
      - query: "今年买过保险的客户（当前时间为2026-08-12）"
        output: {field: policies_insure_date, operator: RANGE, value: {min: "2026-01-01 00:00:00", max: "2026-12-31 23:59:59"}}
      - query: "去年投保的客户（当前时间为2026-04-29）"
        output: {field: policies_insure_date, operator: RANGE, value: {min: "2025-01-01 00:00:00", max: "2025-12-31 23:59:59"}}
      - query: "去年购买了保险的客户名单（当前时间为2026-04-29）"
        output: {field: policies_insure_date, operator: RANGE, value: {min: "2025-01-01 00:00:00", max: "2025-12-31 23:59:59"}}
      - query: "最近一年买保险的人（当前时间为2026-04-29）"
        output: { field: policies_insure_date, operator: RANGE, value: {min: "2025-04-29 00:00:00", max: "2026-04-29 00:00:00" }}
      - query: "最近半年投保了的客户（当前时间为2026-08-10）"
        output: { field: policies_insure_date, operator: RANGE, value: {min: "2026-02-10 00:00:00", max: "2026-08-10 00:00:00" }}

  # ==================== 承保日期 ====================

  - id: latelyUndwrtSegTime
    is_supported: true
    retrieval_text: >
      承保日期 承保时间 何时承保 承保年份 今年承保 本月承保 最近承保 最近承保时间
      承保客户 承保的这批 承保日期排序 承保时间排序 承保日期从早到晚 承保日期从晚到早 近N年承保 过去N年承保
    field: latelyUndwrtSegTime
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd"
    notes: "本月取当月1日至月末；下月取下月1日至月末；下周取下周一至周天；未来一周取今天至往后顺延6天；未来一个月取今天至往后延顺29天；承保时间不等于投保时间或退保时间"
    description: "保单承保日期，嵌套字段"
    examples:
      - query: "本月承保的客户（当前时间为2026-04-20）"
        output: {field: latelyUndwrtSegTime, operator: RANGE, value: {min: "2026-04-01", max: "2026-04-30"}}
      - query: "今年承保的客户（当前时间为2026-04-20）"
        output: {field: latelyUndwrtSegTime, operator: RANGE, value: {min: "2026-01-01", max: "2026-12-31"}}
      - query: "最近承保的客户（当前时间为2026-04-21）"
        output: {field: latelyUndwrtSegTime, operator: RANGE, value: {min: "2026-04-21", max: "2026-05-20"}}
    negative_examples:
      - query: "最近投保的客户"
        reason: "投保不等于承保；投保日期属于 policies_insure_date，不得改写为 latelyUndwrtSegTime"
      - query: "曾经加费承保的客户"
        reason: "加费承保 不是承保时间"

  # ==================== 应缴日 ====================

  - id: policies_pay_date
    is_supported: true
    retrieval_text: >
      应缴日 缴费日 应缴时间 缴费到期 本月应缴 下个月缴费 即将缴费
      要交保费 需要交保费 交保费 缴保费 5月18号交保费
      指定月份缴费 指定月份交费 7月交费客户 七月份缴费客户
      刚缴完费 刚交完费 缴完费 交完费 上个月刚缴完费 上月刚交完费
    field: polNoInfo.paytodate
    operator: RANGE
    value_type: date
    notes: "本月取当月1日至月末；下月取下月1日至月末；下周取下周一至周天；未来一周取今天至往后顺延6天；未来一个月取今天至往后延顺29天；未来30天=未来一个月"
    format: "yyyy-MM-dd HH:mm:ss"
    description: "保单应缴费日期，嵌套字段"
    examples:
      - query: "本月应缴费的客户（当前时间为2026-04-27）"
        output: {field: polNoInfo.paytodate, operator: RANGE, value: {min: "2026-04-01 00:00:00", max: "2026-04-30 23:59:59"}}
      - query: "下个月缴费日的客户（当前时间为2026-04-27）"
        output: {field: polNoInfo.paytodate, operator: RANGE, value: {min: "2026-05-01 00:00:00", max: "2026-05-31 23:59:59"}}
      - query: "近30天需要缴费的客户（当前时间为2026-04-27）"
        output: { field: polNoInfo.paytodate, operator: RANGE, value: { min: "2026-04-27 00:00:00", max: "2026-05-26 23:59:59" } }
      - query: "5月18号交保费的客户（当前时间为2026年）"
        output: { field: polNoInfo.paytodate, operator: RANGE, value: { min: "2026-05-18 00:00:00", max: "2026-05-18 00:00:00" } }
      - query: "7月交费客户（当前时间为2026年）"
        output: { field: polNoInfo.paytodate, operator: RANGE, value: { min: "2026-07-01 00:00:00", max: "2026-07-31 23:59:59" } }
      - query: "七月份缴费客户（当前时间为2026年）"
        output: { field: polNoInfo.paytodate, operator: RANGE, value: { min: "2026-07-01 00:00:00", max: "2026-07-31 23:59:59" } }
      - query: "上个月刚缴完费的客户"
        output: { field: polNoInfo.paytodate, operator: RANGE, value: { min: "2026-06-01 00:00:00", max: "2026-06-30 23:59:59" } }

  - id: policies_pay_date_exists
    is_supported: true
    retrieval_text: >
      有应缴日 存在缴费日 应缴日不为空 要交保费 需要交保费
    field: polNoInfo.paytodate
    operator: EXISTS
    value_type: exists
    description: "表示存在应缴费日期，但原文没有指定时间范围"
    examples:
      - query: "要交保费的客户"
        output: {field: polNoInfo.paytodate, operator: EXISTS, value: ""}

  # ==================== 核保结论 ====================

  - id: policies_whole_decision
    is_supported: false
    retrieval_text: >
      核保结论 核保结果 人核结论 人工核保结论 智核结论 核保意见
    field: polNoInfo.wholeDecision
    operator: MATCH
    value_type: extract
    description: "保单核保结论，嵌套字段，开放域文本"
    examples:
      - query: "核保结论为标准体的客户"
        output: {field: polNoInfo.wholeDecision, operator: MATCH, value: "标准体"}

  # ==================== 犹豫期时间 ====================

  - id: policies_cooling_off_range
    is_supported: false
    retrieval_text: >
      犹豫期 犹豫期到期 犹豫期退保 即将过犹豫期 犹豫期内 犹豫期时间
    field: policies_cooling_off
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "保单犹豫期截止时间，嵌套字段"
    examples:
      - query: "本月犹豫期到期的客户（当前时间为2026-04-29）"
        output: {field: policies_cooling_off, operator: RANGE, value: {min: "2026-04-01 00:00:00", max: "2026-04-31 23:59:59"}}

  - id: policies_cooling_off_lte
    is_supported: false
    retrieval_text: >
      犹豫期 犹豫期到期 即将过犹豫期 7天内犹豫期到期
    field: policies_cooling_off
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "保单犹豫期截止时间早于或等于给定时间，嵌套字段"
    examples:
      - query: "7天内犹豫期到期的客户(当前时间为2026-04-29)"
        output: {field: policies_cooling_off, operator: RANGE, value: {min: "2026-04-29 00:00:00", max: "2026-05-05 23:59:59"}}

  # ==================== 投保险种名称 ====================

  - id: policies_plan_fullname
    is_supported: true
    retrieval_text: >
      投保险种名称 险种全称 保险险种名称 险种叫什么
    field: polNoInfo.plancodeinfo.planfullname
    operator: MATCH
    value_type: enum
    enum_ref: polNoInfo.plancodeinfo.planfullname
    show_enum_in_prompt: false
    enum_candidate_limit_in_prompt: 5
    description: "保单投保险种全称，嵌套字段，枚举值通过独立配置文件维护；活动、活动季、守护季名称不属于投保险种"
    examples:
      - query: "险种名称为平安e生保医疗保险的客户"
        output: {field: polNoInfo.plancodeinfo.planfullname, operator: MATCH, value: "平安e生保医疗保险"}
    negative_examples:
      - query: "平安伴你行守护季"
        reason: "这是活动季名称，不是投保险种名称；应识别为当前不支持的客户活动"

  # ==================== 投保险种简称 ====================

  - id: policies_plan_abbr_name
    is_supported: true
    retrieval_text: >
      投保险种简称 险种简称 保单产品 投保保单  e生保 买了e生保
    field: polNoInfo.plancodeinfo.abbrname
    operator: MATCH
    value_type: enum
    enum_ref: polNoInfo.plancodeinfo.abbrname
    show_enum_in_prompt: false
    enum_candidate_limit_in_prompt: 5
    description: "保单投保险种简称，嵌套字段，枚举值通过独立配置文件维护"
    notes: "只在原文明确表达具体产品简称时使用。口语可能在标准产品简称后额外添加‘险’，如‘智盈重疾险’应先去掉泛化后缀并匹配标准枚举‘智盈重疾’；只允许在完整枚举值之后忽略一个‘险’，不能对任意文本模糊截断。购买语境中的泛化‘重大疾病/平安重大疾病’表示 pCategorys=疾病保险，不得因为简称枚举中存在‘重大疾病’就输出本字段；‘平安’不能与枚举子串‘重大疾病’拼接成产品简称。活动、活动季、守护季名称不属于产品简称。"
    examples:
      - query: "我的哪些客户投保了智盈重疾险的？"
        output: {field: polNoInfo.plancodeinfo.abbrname, operator: MATCH, value: "智盈重疾"}
      - query: "买了e生保的客户"
        output: {field: polNoInfo.plancodeinfo.abbrname, operator: MATCH, value: "e生保"}
    negative_examples:
      - query: "购买过平安重大疾病的客户"
        reason: "这是泛化险种类别语义，应使用 pCategorys MATCH 疾病保险；没有明确具体产品简称"

  - id: policies_plan_abbr_name_not_contains
    is_supported: true
    retrieval_text: >
      投保险种简称 险种简称 保单产品 投保保单 没买e生保
    field: polNoInfo.plancodeinfo.abbrname
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: polNoInfo.plancodeinfo.abbrname
    show_enum_in_prompt: false
    enum_candidate_limit_in_prompt: 5
    description: "保单投保险种简称，嵌套字段，枚举值通过独立配置文件维护"
    examples:
      - query: "没买e生保的客户"
        output: { field: polNoInfo.plancodeinfo.abbrname, operator: NOT_CONTAINS, value: ["e生保"] }


  # ==================== 投保险种类型 ====================

  - id: policies_plan_type
    is_supported: true
    retrieval_text: >
      投保险种类别 险种类别 年金 年金险 年金保险 两全险 健康险 寿险 定期险
    field: polNoInfo.plancodeinfo.plantypedesc
    operator: MATCH
    value_type: enum
    enum_ref: polNoInfo.plancodeinfo.plantypedesc
    show_enum_in_prompt: true
    description: "保单投保险种类别，明确指定单一险种类别时使用MATCH"
    notes: "年金险/年金保险映射为年金。明确一个完整类别值时使用MATCH；只有原文明示多个候选时才使用CONTAINS。"
    examples:
      - query: "寿险的客户"
        output: {field: polNoInfo.plancodeinfo.plantypedesc, operator: MATCH, value: "寿险"}
      - query: "购买过寿险的客户"
        output: { field: polNoInfo.plancodeinfo.plantypedesc, operator: MATCH, value: "寿险" }

  - id: policies_plan_type_not_contains
    is_supported: true
    retrieval_text: >
      没有年金险种 没有健康险种 不包含寿险类别 没有定期险保单 没买寿险产品的客户
    field: polNoInfo.plancodeinfo.plantypedesc
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: polNoInfo.plancodeinfo.plantypedesc
    show_enum_in_prompt: true
    description: "表示客户保单险种类别中不包含某类险种，不表示没有任何保单"
    examples:
      - query: "没有年金险种的客户"
        output: { field: polNoInfo.plancodeinfo.plantypedesc, operator: NOT_CONTAINS, value: [ "年金" ] }
      - query: "没有健康险种的客户"
        output: { field: polNoInfo.plancodeinfo.plantypedesc, operator: NOT_CONTAINS, value: [ "健康险" ] }
      - query: "没买寿险的客户"
        output: { field: polNoInfo.plancodeinfo.plantypedesc, operator: NOT_CONTAINS, value: [ "寿险" ] }

  # ==================== 投保人姓名 ====================

  - id: policies_applicant_name
    is_supported: true
    retrieval_text: >
      投保人姓名 投保人叫 投保人名字 谁投保的 投保人是谁
    field: polNoInfo.applicantname
    operator: MATCH
    value_type: extract
    description: "保单投保人姓名。只有投保人角色直接修饰姓名，或明确说明某人作为投保人时才使用。"
    notes: "必须存在“投保人X”“投保人姓名为X”“X作为投保人”等直接角色归属证据；裸姓名、客户姓名或“X有保单”不能映射到本字段。"
    examples:
      - query: "投保人叫张三的客户"
        output: { field: polNoInfo.applicantname, operator: MATCH, value: "张三" }
      - query: "姚礼芳7月到12月作为投保人，累计还有几份保单缴费"
        output: { field: polNoInfo.applicantname, operator: MATCH, value: "姚礼芳" }
    negative_examples:
      - query: "顾清禾"
        reason: "裸姓名表示客户本人，不是投保人姓名"
      - query: "把叫顾清禾的客户列出来"
        reason: "这是客户本人姓名，没有投保人角色证据"
      - query: "顾清禾有保单的客户"
        reason: "有保单不等于顾清禾是投保人"

  # ==================== 投保人手机号 ====================

  - id: policies_applicant_mobile
    is_supported: true
    retrieval_text: >
      投保人手机号 投保人电话 投保人手机
    field: polNoInfo.applicantphoneno
    operator: MATCH
    value_type: extract
    description: "保单投保人手机号，嵌套字段"
    notes: "必须说明是查询投保人的手机号，且手机号一定是由1-11为数字组成，不可能为中文或字母"
    examples:
      - query: "投保人手机号13800138000的客户"
        output: { field: polNoInfo.applicantphoneno, operator: MATCH, value: "13800138000" }

  # ==================== 被保人姓名 ====================

  - id: policies_insured_name
    is_supported: true
    retrieval_text: >
      被保人姓名 被保人叫 被保险人姓名 被保人名字 谁是被保人
    field: polNoInfo.plancodeinfo.insname
    operator: MATCH
    value_type: extract
    description: "保单被保人姓名。只有被保人或被保险人角色直接修饰姓名，或明确说明某人作为被保人时才使用。"
    notes: "必须存在“被保人X”“被保人姓名为X”“X作为被保人”等直接角色归属证据；裸姓名和客户姓名不能映射到本字段。"
    examples:
      - query: "被保人叫李四的客户"
        output: { field: polNoInfo.plancodeinfo.insname, operator: MATCH, value: "李四" }
      - query: "江知遥作为被保人的保单客户"
        output: { field: polNoInfo.plancodeinfo.insname, operator: MATCH, value: "江知遥" }
    negative_examples:
      - query: "江知遥"
        reason: "裸姓名表示客户本人，不是被保人姓名"
      - query: "客户姓名为江知遥"
        reason: "客户姓名没有被保人角色证据"

  # ==================== 被保人手机号 ====================

  - id: policies_insured_mobile
    is_supported: true
    retrieval_text: >
      被保人手机号 被保人电话 被保险人手机
    field: polNoInfo.plancodeinfo.insphoneno
    operator: MATCH
    value_type: extract
    description: "保单被保人手机号，嵌套字段"
    notes: "必须说明是查询被保人（被保险人）的手机号，且手机号一定是由1-11为数字组成，不可能为中文或字母"
    examples:
      - query: "被保人手机号13900139000的客户"
        output: { field: polNoInfo.plancodeinfo.insphoneno, operator: MATCH, value: "13900139000" }

  # ==================== 受益人姓名 ====================

  - id: policies_beneficiary_name
    is_supported: true
    retrieval_text: >
      受益人姓名 受益人叫 受益人名字 谁是受益人
    field: polNoInfo.benefinfo.benefname
    operator: MATCH
    value_type: extract
    description: "保单受益人姓名。只有受益人角色直接修饰姓名，或明确说明某人作为受益人时才使用。"
    notes: "必须存在“受益人X”“受益人姓名为X”“X作为受益人”等直接角色归属证据；裸姓名和客户姓名不能映射到本字段。"
    examples:
      - query: "受益人叫王五的客户"
        output: {field: polNoInfo.benefinfo.benefname, operator: MATCH, value: "王五"}
    negative_examples:
      - query: "沈知夏"
        reason: "裸姓名表示客户本人，不是受益人姓名"
      - query: "把叫沈知夏的客户列出来"
        reason: "没有受益人角色归属证据"

  - id: policies_beneficiary_names
    is_supported: true
    retrieval_text: >
      多个受益人姓名 受益人叫某人或某人 受益人姓名包含多个
    field: polNoInfo.benefinfo.benefname
    operator: CONTAINS
    value_type: extract
    description: "保单存在原文明示的多个受益人姓名"
    examples:
      - query: "受益人叫张三或王五的客户"
        output: {field: polNoInfo.benefinfo.benefname, operator: CONTAINS, value: ["张三", "王五"]}

  # ==================== 受益人手机号 ====================

  - id: policies_beneficiary_mobile
    is_supported: false
    retrieval_text: >
      受益人手机号 受益人电话 受益人手机
    field: policies_beneficiary_mobile
    operator: MATCH
    value_type: extract
    description: "保单受益人手机号，嵌套字段"
    notes: "必须说明是查询受益人的手机号，且手机号一定是由1-11为数字组成，不可能为中文或字母"
    examples:
      - query: "受益人手机号13700137000的客户"
        output: {field: policies_beneficiary_mobile, operator: MATCH, value: "13700137000"}

  # ==================== 生存金总金额 ====================

#  - id: policies_survival_total_amount_gte
#    is_supported: false
#    retrieval_text: >
#      生存金总金额 生存金总额 生存金以上 生存金不低于 生存金大于等于 生存金不少于
#    field: policies_survival_total_amount
#    operator: GTE
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金总金额（本金总额），区别于生存金利息、已领取金额、未领取金额"
#    negative_examples:
#      - query: "生存金利息超过1万的客户"
#        reason: "这是生存金利息，应映射到 policies_total_survival_benefit_interest，不是生存金总金额"
#      - query: "已领取生存金超过5万的客户"
#        reason: "这是已领取金额，应映射到 policies_survival_claimed_amount，不是生存金总金额"
#    examples:
#      - query: "生存金总金额10万及以上的客户"
#        output: { field: policies_survival_total_amount, operator: GTE, value: 100000 }
#      - query: "生存金不低于10万的客户"
#        output: { field: policies_survival_total_amount, operator: GTE, value: 100000 }
#
#  - id: policies_survival_total_amount_gt
#    is_supported: true
#    retrieval_text: >
#      生存金总金额 生存金总额 生存金超过 生存金大于 生存金高于 生存金以上
#    field: policies_survival_total_amount
#    operator: GT
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金总金额，用 ＞ 表示严格超过某金额"
#    examples:
#      - query: "生存金总金额10万以上的客户"
#        output: { field: policies_survival_total_amount, operator: GT, value: 100000 }
#      - query: "生存金超过10万的客户"
#        output: { field: policies_survival_total_amount, operator: GT, value: 100000 }
#
#  - id: policies_survival_total_amount_lte
#    is_supported: true
#    retrieval_text: >
#      生存金总金额 生存金总额 生存金以下 生存金不超过 生存金小于等于 生存金不大于
#    field: policies_survival_total_amount
#    operator: LTE
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金总金额，用 ≤ 表示不超过某金额"
#    examples:
#      - query: "生存金总金额10万及以下的客户"
#        output: { field: policies_survival_total_amount, operator: LTE, value: 100000 }
#      - query: "生存金不超过10万的客户"
#        output: { field: policies_survival_total_amount, operator: LTE, value: 100000 }
#
#  - id: policies_survival_total_amount_lt
#    is_supported: true
#    retrieval_text: >
#      生存金总金额 生存金总额 生存金低于 生存金小于 生存金以下
#    field: policies_survival_total_amount
#    operator: LT
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金总金额，用 ＜ 表示严格低于某金额"
#    examples:
#      - query: "生存金总金额10万以下的客户"
#        output: { field: policies_survival_total_amount, operator: LT, value: 100000 }
#      - query: "生存金低于10万的客户"
#        output: { field: policies_survival_total_amount, operator: LT, value: 100000 }

  # ==================== 生存金已领取金额 ====================

#  - id: policies_survival_claimed_gte
#    is_supported: false
#    retrieval_text: >
#      生存金已领取 已领取生存金 已领生存金 领取了生存金 以上 不低于 大于等于 不少于
#    field: policies_survival_claimed_amount
#    operator: GTE
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金已领取金额（已领取本金），区别于生存金总金额、生存金利息、利息已领取"
#    examples:
#      - query: "已领取生存金5万及以上的客户"
#        output: { field: policies_survival_claimed_amount, operator: GTE, value: 50000 }
#
#  - id: policies_survival_claimed_gt
#    is_supported: false
#    retrieval_text: >
#      生存金已领取 已领取生存金 已领生存金 超过 大于 高于 以上
#    field: policies_survival_claimed_amount
#    operator: GT
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "保单已领取生存金金额，＞ 表示严格超过"
#    examples:
#      - query: "已领取生存金超过5万的客户"
#        output: { field: policies_survival_claimed_amount, operator: GT, value: 50000 }
#
#  - id: policies_survival_claimed_lte
#    is_supported: false
#    retrieval_text: >
#      生存金已领取 已领取生存金 已领生存金 以下 不超过 小于等于 不大于 及以下
#    field: policies_survival_claimed_amount
#    operator: LTE
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "保单已领取生存金金额，≤ 不超过"
#    examples:
#      - query: "已领取生存金5万及以下的客户"
#        output: { field: policies_survival_claimed_amount, operator: LTE, value: 50000 }
#
#  - id: policies_survival_claimed_lt
#    is_supported: false
#    retrieval_text: >
#      生存金已领取 已领取生存金 已领生存金 以下 低于 小于
#    field: policies_survival_claimed_amount
#    operator: LT
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "保单已领取生存金金额，＜ 严格低于"
#    examples:
#      - query: "已领取生存金低于5万的客户"
#        output: { field: policies_survival_claimed_amount, operator: LT, value: 50000 }


  # ==================== 生存金未领取金额 ====================

  - id: pol_no_info_payamountdue_flag
    is_supported: true
    retrieval_text: >
      生存金未领取金额是否大于0 未领取生存金是否大于0 生存金未领取金额大于0 生存金未领取金额等于0
      有未领取生存金 无未领取生存金 生存金待领 生存金未领 有生存金未领取 有未领生存金 生存金待领 生存金未领
    field: polNoInfo.payamountdue
    operator: MATCH
    value_type: enum
    enum_ref: polNoInfo.payamountdue
    enum:
      - "是"
      - "否"
    description: "生存金未领取金额是否大于0；是表示生存金领取金额等于0，否表示生存金领取金大于0；该字段不表述生存金利息相关字段查询"
    examples:
      - query: "生存金未领取金额等于0的客户"
        output: {field: polNoInfo.payamountdue, operator: MATCH, value: "否"}
      - query: "有未领生存金的"
        output: {field: polNoInfo.payamountdue, operator: MATCH, value: "是"}
      - query: "有生存金未领取的客户"
        output: { field: polNoInfo.payamountdue, operator: MATCH, value: "是" }
      - query: "生存金客户"
        output: { field: polNoInfo.payamountdue, operator: MATCH, value: "是" }
    negative_examples:
      - query: "生存金利息超过1000块而且还没领完的客户"
        reason: "问题是生存金利息的查询，不是生存金未领取金额的查询"
      - query: "利息已经领了一部分但还有剩余没领的保单有哪些"
        reason: "问题是生存金利息的查询，不是生存金未领取金额的查询"

  # ==================== 生存金已转入万能账户金额 ====================

  - id: policies_universal_acct_transfer_gte
    is_supported: false
    retrieval_text: >
      生存金转入万能账户及以上 万能账户转入及以上 生存金转万能及以上
      生存金转入万能账户不低于 生存金转入万能账户大于等于
    field: policies_universal_acct_transfer
    operator: GTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "生存金已转入万能账户金额（转入万能账户的本金），区别于生存金总金额、生存金利息"
    examples:
      - query: "生存金转入万能账户2万及以上的客户"
        output: { field: policies_universal_acct_transfer, operator: GTE, value: 20000 }

  - id: policies_universal_acct_transfer_gt
    is_supported: false
    retrieval_text: >
      生存金转入万能账户超过 万能账户转入超过 生存金转万能超过
      生存金转入万能账户大于 生存金转入万能账户高于
    field: policies_universal_acct_transfer
    operator: GT
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "生存金已转入万能账户金额，＞ 严格超过"
    examples:
      - query: "生存金转入万能账户超过2万的客户"
        output: { field: policies_universal_acct_transfer, operator: GT, value: 20000 }

  - id: policies_universal_acct_transfer_lte
    is_supported: false
    retrieval_text: >
      生存金转入万能账户 万能账户转入 以下 不超过 不大于 及以下
    field: policies_universal_acct_transfer
    operator: LTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "生存金已转入万能账户金额，≤ 不超过"
    examples:
      - query: "生存金转入万能账户不超过2万的客户"
        output: { field: policies_universal_acct_transfer, operator: LTE, value: 20000 }

  - id: policies_universal_acct_transfer_lt
    is_supported: false
    retrieval_text: >
      生存金转入万能账户 万能账户转入 以下 低于 小于
    field: policies_universal_acct_transfer
    operator: LT
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "生存金已转入万能账户金额，＜ 严格低于"
    examples:
      - query: "生存金转入万能账户低于2万的客户"
        output: { field: policies_universal_acct_transfer, operator: LT, value: 20000 }

  - id: policies_universal_acct_transfer_exists
    is_supported: false
    retrieval_text: >
      生存金转入万能账户 万能账户转入 生存金转万能 万能账户生存金
    field: policies_universal_acct_transfer
    operator: EXISTS
    value_type: none
    description: "存在生存金已转入万能账户金额，嵌套字段"
    examples:
      - query: "有生存金转入万能账户的客户"
        output: { field: policies_universal_acct_transfer, operator: EXISTS }

  # ==================== 生存金利息总额 ====================

#  - id: policies_survival_benefit_interest_gte
#    is_supported: false
#    retrieval_text: >
#      生存金利息总额 生存金利息总计 生存金利息 所有利息总额 及以上 不低于 大于等于
#    field: policies_total_survival_benefit_interest
#    operator: GTE
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金利息总额（利息总收入），区别于生存金总金额（本金）、已领取利息、未领取利息"
#    examples:
#      - query: "生存金利息总额超过1万的客户"
#        output: { field: policies_total_survival_benefit_interest, operator: GTE, value: 10000 }
#
#  - id: policies_survival_benefit_interest_gt
#    is_supported: false
#    retrieval_text: >
#      生存金利息总额 生存金利息 超过 大于 高于 以上
#    field: policies_total_survival_benefit_interest
#    operator: GT
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金利息总额，＞ 严格超过"
#    examples:
#      - query: "生存金利息总额超过1万的客户"
#        output: { field: policies_total_survival_benefit_interest, operator: GT, value: 10000 }
#
#  - id: policies_survival_benefit_interest_lte
#    is_supported: false
#    retrieval_text: >
#      生存金利息总额 生存金利息 以下 不超过 不大于 及以下
#    field: policies_total_survival_benefit_interest
#    operator: LTE
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金利息总额，≤ 不超过"
#    examples:
#      - query: "生存金利息总额不超过1万的客户"
#        output: { field: policies_total_survival_benefit_interest, operator: LTE, value: 10000 }
#
#  - id: policies_survival_benefit_interest_lt
#    is_supported: false
#    retrieval_text: >
#      生存金利息总额 生存金利息 以下 低于 小于
#    field: policies_total_survival_benefit_interest
#    operator: LT
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金利息总额，＜ 严格低于"
#    examples:
#      - query: "生存金利息总额低于1万的客户"
#        output: { field: policies_total_survival_benefit_interest, operator: LT, value: 10000 }

  # ==================== 生存金利息已领取 ====================

#  - id: policies_survival_benefit_interest_received_gte
#    is_supported: false
#    retrieval_text: >
#      生存金利息已领取 已领取生存金利息 已领利息 及以上 不低于 大于等于 超过
#    field: policies_total_survival_benefit_interest_received
#    operator: GTE
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金利息已领取总额（已领到的利息），区别于生存金已领取金额（本金）、利息未领取"
#    examples:
#      - query: "已领取生存金利息超过1万的客户"
#        output: { field: policies_total_survival_benefit_interest_received, operator: GTE, value: 10000 }
#
#  - id: policies_survival_benefit_interest_received_gt
#    is_supported: false
#    retrieval_text: >
#      生存金利息已领取 已领取生存金利息 已领利息 超过 大于 高于 以上 利息已经领了 生存金利息已领取
#    field: policies_total_survival_benefit_interest_received
#    operator: GT
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金利息已领取总额，＞ 严格超过"
#    examples:
#      - query: "已领取生存金利息超过1万的客户"
#        output: { field: policies_total_survival_benefit_interest_received, operator: GT, value: 10000 }
#
#  - id: policies_survival_benefit_interest_received_lte
#    is_supported: false
#    retrieval_text: >
#      生存金利息已领取 已领取生存金利息 以下 不超过 不大于 及以下
#    field: policies_total_survival_benefit_interest_received
#    operator: LTE
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金利息已领取总额，≤ 不超过"
#    examples:
#      - query: "已领取生存金利息不超过1万的客户"
#        output: { field: policies_total_survival_benefit_interest_received, operator: LTE, value: 10000 }
#
#  - id: policies_survival_benefit_interest_received_lt
#    is_supported: false
#    retrieval_text: >
#      生存金利息已领取 已领取生存金利息 以下 低于 小于
#    field: policies_total_survival_benefit_interest_received
#    operator: LT
#    value_type: numeric
#    unit: "元，万=×10000，千=×1000"
#    description: "生存金利息已领取总额，＜ 严格低于"
#    examples:
#      - query: "已领取生存金利息低于1万的客户"
#        output: { field: policies_total_survival_benefit_interest_received, operator: LT, value: 10000 }

  # ==================== 生存金利息未领取 ====================
  - id: policies_survival_benefit_interest_unclaimed_range
    is_supported: true
    retrieval_text: >
      生存金利息未领取 未领取利息 利息未领 精确值 具体金额 还有 仍有 尚有 还剩 剩余
    field: polNoInfo.survivalinterestunpaidamt
    operator: RANGE
    value_type: range
    unit: "元，万=×10000，千=×1000，若没明确单位，默认为元"
    description: "生存金利息未领取精确金额或区间金额查询"
    examples:
      - query: "还有2000到5000元生存金利息未领取的客户"
        output: { field: polNoInfo.survivalinterestunpaidamt, operator: RANGE, value: { min: 2000, max: 5000 } }
      - query: "利息还有2000没领的客户"
        output: { field: polNoInfo.survivalinterestunpaidamt, operator: RANGE, value: { min: 2000, max: 2000 } }

  - id: policies_survival_benefit_interest_unclaimed_gte
    is_supported: true
    retrieval_text: >
      生存金利息未领取及以上 未领取利息及以上 利息未领及以上
      生存金利息未领取不低于 生存金利息未领取大于等于
    field: polNoInfo.survivalinterestunpaidamt
    operator: GTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "生存金利息未领取总额（还没领的利息），区别于生存金未领取金额（本金）、利息已领取"
    examples:
      - query: "生存金利息未领取5千及以上的客户"
        output: { field: polNoInfo.survivalinterestunpaidamt, operator: GTE, value: 5000 }

  - id: policies_survival_benefit_interest_unclaimed_gt
    is_supported: true
    retrieval_text: >
      生存金利息未领取超过 未领取利息超过 利息未领超过
      生存金利息未领取大于 生存金利息未领取高于 利息还没领完
    field: polNoInfo.survivalinterestunpaidamt
    operator: GT
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "生存金利息未领取总额，＞ 严格超过"
    examples:
      - query: "生存金利息未领取超过5千的客户"
        output: { field: polNoInfo.survivalinterestunpaidamt, operator: GT, value: 5000 }
      - query: "利息还没领完的客户"
        output: { field: polNoInfo.survivalinterestunpaidamt, operator: GT, value: 0 }
      - query: "生存金利息超过1000块而且还没领完的客户"
        output: { field: polNoInfo.survivalinterestunpaidamt, operator: GT, value: 1000 }

  - id: policies_survival_benefit_interest_unclaimed_lte
    is_supported: true
    retrieval_text: >
      生存金利息未领取 未领取利息 以下 不超过 不大于 及以下
    field: polNoInfo.survivalinterestunpaidamt
    operator: LTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "生存金利息未领取总额，≤ 不超过"
    examples:
      - query: "生存金利息未领取不超过5千的客户"
        output: { field: polNoInfo.survivalinterestunpaidamt, operator: LTE, value: 5000 }

  - id: policies_survival_benefit_interest_unclaimed_lt
    is_supported: true
    retrieval_text: >
      生存金利息未领取 未领取利息 以下 低于 小于
    field: polNoInfo.survivalinterestunpaidamt
    operator: LT
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "生存金利息未领取总额，＜ 严格低于"
    examples:
      - query: "生存金利息未领取低于5千的客户"
        output: { field: polNoInfo.survivalinterestunpaidamt, operator: LT, value: 5000 }

  # ==================== 理赔时间 ====================

  - id: policies_claim_time
    is_supported: true
    retrieval_text: >
      理赔时间 理赔日期 何时理赔 本月理赔 今年理赔 近期理赔 最近一年有理赔记录 最近理赔
      有理赔记录 理赔客户 出过险 理赔过 理赔日期排序 理赔时间排序
    field: polNoInfo.claimdatainfo.claimdate
    operator: RANGE
    value_type: date
    format: "yyyy-MM-dd HH:mm:ss"
    description: "理赔记录中的理赔时间，嵌套字段；若仅判断是否有理赔记录，用 EXISTS"
    notes: "‘最近/近+时间长度+理赔过/有理赔记录’表示已经发生的理赔，按过去时间解析；该方向规则只属于理赔事件，不得迁移到‘积分即将过期、保单将要到期、证件快要失效’等未来事件。"
    examples:
      - query: "今年有理赔的客户（当前时间为2026-04-26）"
        output: {field: polNoInfo.claimdatainfo.claimdate, operator: RANGE, value: {min: "2026-01-01 00:00:00", max: "2026-12-31 23:59:59"}}
      - query: "近30天理赔的客户（当前时间为2026-04-26）"
        output: {field: polNoInfo.claimdatainfo.claimdate, operator: RANGE, value: {min: "2026-03-28 00:00:00", max: "2026-04-26 23:59:59"}}
      - query: "有没有最近理赔过的客户（当前时间为2026-05-06）"
        output: { field: polNoInfo.claimdatainfo.claimdate, operator: RANGE, value: { min: "2026-04-06 00:00:00", max: "2026-05-06 23:59:59" } }
      - query: "最近一年有理赔记录的客户（当前时间为2026-05-11）"
        output: { field: polNoInfo.claimdatainfo.claimdate, operator: RANGE, value: { min: "2025-05-11 00:00:00", max: "2026-05-11 23:59:59" } }

  # ==================== 理赔案件号 ====================

  - id: policies_claim_case_id
    is_supported: true
    retrieval_text: >
      理赔案件号 理赔案号 理赔编号 案件号 MC开头 MC+14位
    field: polNoInfo.claimdatainfo.claimno
    operator: MATCH
    value_type: extract
    description: "理赔案件号，格式为MC+14位数字，例如：MC20240509000001"
    format: "MC+14位数字（MC后跟14位数字）"
    examples:
      - query: "理赔案件号为MC20240509000001的客户"
        output: {field: polNoInfo.claimdatainfo.claimno, operator: MATCH, value: "MC20240509000001"}
      - query: "查找理赔案件号MC20240509000002的客户"
        output: {field: polNoInfo.claimdatainfo.claimno, operator: MATCH, value: "MC20240509000002"}

  # ==================== 理赔金额 ====================

  - id: policies_claim_amount_gte
    is_supported: true
    retrieval_text: >
      理赔金额以上 理赔金额及以上 理赔5000以上 获赔金额以上 赔付金额以上
      理赔金额不低于 理赔金额大于等于 理赔金额不少于
    field: polNoInfo.claimdatainfo.claimamt
    operator: GTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "理赔金额，≥ 达到或超过"
    examples:
      - query: "理赔金额10万以上的客户"
        output: { field: polNoInfo.claimdatainfo.claimamt, operator: GTE, value: 100000 }

  - id: policies_claim_amount_gt
    is_supported: true
    retrieval_text: >
      理赔金额超过 理赔超过 理赔超 理赔金额大于 理赔大于
      获赔金额超过 赔付金额超过 理赔金额高于
    field: polNoInfo.claimdatainfo.claimamt
    operator: GT
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "理赔金额，＞ 严格超过"
    examples:
      - query: "理赔金额超过10万的客户"
        output: { field: polNoInfo.claimdatainfo.claimamt, operator: GT, value: 100000 }

  - id: policies_claim_amount_lte
    is_supported: true
    retrieval_text: >
      理赔金额 理赔了多少钱 以下 不超过 小于等于 不大于 及以下 以下
    field: polNoInfo.claimdatainfo.claimamt
    operator: LTE
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "理赔金额，≤ 不超过"
    examples:
      - query: "理赔金额10万以下的客户"
        output: { field: polNoInfo.claimdatainfo.claimamt, operator: LTE, value: 100000 }

  - id: policies_claim_amount_lt
    is_supported: true
    retrieval_text: >
      理赔金额 理赔了多少钱 低于 小于
    field: polNoInfo.claimdatainfo.claimamt
    operator: LT
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "理赔金额，＜ 严格低于"
    examples:
      - query: "理赔小于5万的客户"
        output: { field: polNoInfo.claimdatainfo.claimamt, operator: LT, value: 50000 }

  - id: policies_claim_amount_range
    is_supported: true
    retrieval_text: >
      理赔金额 获赔金额 赔付金额 精确值 等于 正好 刚好 万 千
    field: polNoInfo.claimdatainfo.claimamt
    operator: RANGE
    value_type: numeric
    unit: "元，万=×10000，千=×1000"
    description: "理赔金额区间或精确值（等于）"
    examples:
      - query: "理赔金额5000的客户"
        output: { field: polNoInfo.claimdatainfo.claimamt, operator: RANGE, value: {min: 5000, max: 5000} }
      - query: "获赔金额5千的客户"
        output: { field: polNoInfo.claimdatainfo.claimamt, operator: RANGE, value: {min: 5000, max: 5000} }
      - query: "赔付金额1万的客户"
        output: { field: polNoInfo.claimdatainfo.claimamt, operator: RANGE, value: {min: 10000, max: 10000} }

  # ==================== 理赔险种 ====================

  - id: policies_claim_coverage_match
    is_supported: true
    retrieval_text: >
      理赔险种 理赔了什么险 理赔险种是 获赔险种 某险种理赔过
      有过某险种理赔 某险种发生过理赔 理赔过某险种 获赔过某险种
    field: polNoInfo.claimdatainfo.claimplancodename
    operator: MATCH
    value_type: extract
    enum_ref: polNoInfo.claimdatainfo.claimplancodename
    show_enum_in_prompt: false
    enum_candidate_limit_in_prompt: 5
    description: "指定明确发生过理赔的单一险种名称；必须同时存在理赔动作和具体险种，使用MATCH"
    notes: "本字段以明确理赔语义为必要条件：原文必须出现理赔、获赔、赔付、出险理赔等动作，只有购买、投保、持有、有某权益时绝不能使用本字段。用户原文出现具体理赔险种或产品名时，必须保留该名称并使用 MATCH；‘有过/发生过/理赔过’表示该具体险种发生理赔，不能将其泛化为 EXISTS。只有原文完全没有指定险种名称、仅表达有理赔记录时，才使用 EXISTS。枚举召回只提供候选值，不能替代理赔动作证据。"
    examples:
      - query: "有过e生保理赔的客户"
        output: {field: polNoInfo.claimdatainfo.claimplancodename, operator: MATCH, value: "e生保"}
      - query: "有哪些客户理赔过平安福重疾"
        output: { field: polNoInfo.claimdatainfo.claimplancodename, operator: MATCH, value: "平安福重疾" }
      - query: "获赔过e生保的客户"
        output: { field: polNoInfo.claimdatainfo.claimplancodename, operator: MATCH, value: "e生保" }
    negative_examples:
      - query: "有过理赔的客户"
        reason: "未指定具体险种，应使用 EXISTS。"
      - query: "买过e生保的客户"
        reason: "这是投保险种，不是理赔险种。"
      - query: "购买过平安重大疾病并且有家医权益的客户"
        reason: "原文只有购买和权益语义，没有理赔动作；重大疾病应解析为险种类别，家医应解析为权益服务"

  - id: policies_claim_coverage_not_contains
    is_supported: true
    retrieval_text: >
      没有理赔xx险种 xx险没有理赔过 未理赔险种是 未获赔险种
    field: polNoInfo.claimdatainfo.claimplancodename
    operator: NOT_CONTAINS
    value_type: extract
    enum_ref: polNoInfo.claimdatainfo.claimplancodename
    show_enum_in_prompt: false
    enum_candidate_limit_in_prompt: 5
    description: "指定未发生理赔的险种名称，嵌套字段，开放域文本"
    notes: "用户原文出现具体险种或产品名并明确该险种没有理赔时，保留具体名称并使用 NOT_CONTAINS；不能泛化为 NOT_EXISTS。只有完全未指定险种名称时才使用 NOT_EXISTS。"
    examples:
      - query: "没有过e生保理赔的客户"
        output: { field: polNoInfo.claimdatainfo.claimplancodename, operator: NOT_CONTAINS, value: [ "e生保" ] }
      - query: "有哪些客户未理赔过平安福重疾"
        output: { field: polNoInfo.claimdatainfo.claimplancodename, operator: NOT_CONTAINS, value: [ "平安福重疾" ] }
    negative_examples:
      - query: "从未理赔过的客户"
        reason: "未指定具体险种，应使用 NOT_EXISTS。"

  - id: policies_claim_coverage_exists
    is_supported: true
    retrieval_text: >
      理赔记录 理赔过 有理赔记录 存在理赔记录
    field: polNoInfo.claimdatainfo.claimplancodename
    operator: EXISTS
    value_type: none
    show_enum_in_prompt: false
    description: "存在任意理赔记录，且用户没有指定具体理赔险种"
    notes: "EXISTS 只用于原文没有出现具体险种或产品名称的泛化理赔查询。若出现 e生保、平安福重疾等具体名称，必须使用该名称生成 MATCH，不能因“有过”而丢弃具体值。"
    examples:
      - query: "有理赔记录的客户"
        output: { field: polNoInfo.claimdatainfo.claimplancodename, operator: EXISTS, value: "" }
      - query: "有哪些客户理赔过"
        output: { field: polNoInfo.claimdatainfo.claimplancodename, operator: EXISTS, value: ""}
    negative_examples:
      - query: "有过e生保理赔的客户"
        reason: "已指定理赔险种，应使用 MATCH e生保。"

  - id: policies_claim_coverage_not_exists
    is_supported: true
    retrieval_text: >
      没有理赔记录 未理赔过 不存在理赔记录 未获赔过
    field: polNoInfo.claimdatainfo.claimplancodename
    operator: NOT_EXISTS
    value_type: none
    show_enum_in_prompt: false
    description: "不存在任意理赔记录，且用户没有指定具体理赔险种"
    notes: "NOT_EXISTS 只用于原文没有出现具体险种或产品名称的泛化无理赔查询。若指定某个险种未理赔，应使用 NOT_CONTAINS 并保留该险种名称。"
    examples:
      - query: "从未理赔过的客户有哪些"
        output: { field: polNoInfo.claimdatainfo.claimplancodename, operator: NOT_EXISTS, value: "" }
      - query: "有哪些客户没有发生过理赔"
        output: { field: polNoInfo.claimdatainfo.claimplancodename, operator: NOT_EXISTS, value: "" }
    negative_examples:
      - query: "没有过e生保理赔的客户"
        reason: "已指定理赔险种，应使用 NOT_CONTAINS e生保。"

  - id: is_life_insured
    is_supported: false
    retrieval_text: >
      投保被保人 仅投保人 仅被保人 投被保人 是否既是投保人又是被保人
    field: is_life_insured
    operator: MATCH
    value_type: enum
    enum: [ "仅投保人", "仅被保人", "投被保人" ]
    description: "表示客户在寿险保单中的投保人/被保人身份关系。"
    notes: "仅投保人、仅被保人、投被保人是身份关系枚举，不表示客户是否购买寿险或是否为寿险客户。"
    examples:
      - query: "仅仅是投保人的客户"
        output: { field: is_life_insured, operator: MATCH, value: "仅投保人" }
      - query: "仅仅是被保人的客户"
        output: { field: is_life_insured, operator: MATCH, value: "投被保人" }

  - id: policy_count_gte
    is_supported: false
    retrieval_text: >
      保单数量 保单个数 保单数 保单张数 几张保单 多少张保单 保单有几张 多张寿险保单
    field: polNum
    operator: GTE
    type: int
    description: "客户持有的保单总数量；张以上/张及以上表示 ≥N，张以下表示 ≤N"
    examples:
      - query: "保单数量超过3张的客户"
        output: { field: polNum, operator: GTE, value: 3 }
      - query: "持有多张寿险保单的客户"
        output: { field: polNum, operator: GTE, value: 1 }

  # ==================== 退保时间 ====================

  - id: surrender_date_time
    is_supported: false
    retrieval_text: >
      退保时间 退保日期 保单退保时间 什么时候退保的 退保年月日
    field: polNoInfo.surrenderDateTime
    operator: RANGE
    type: datetime
    format: "yyyy-MM-dd HH:mm:ss"
    description: "保单退保时间，嵌套字段，格式 yyyy-MM-dd HH:mm:ss"
    examples:
      - query: "2025年退保的客户"
        output: { field: polNoInfo.surrenderDateTime, operator: RANGE, value: { min: "2025-01-01 00:00:00", max: "2025-12-31 23:59:59" } }
      - query: "最近一个月退保的客户（当前时间为2026-05-06）"
        output: { field: polNoInfo.surrenderDateTime, operator: RANGE, value: { min: "2026-05-06 00:00:00", max: "2026-06-06 23:59:59" } }

  # ==================== 承保时间 ====================

  - id: lately_undwrt_seg_time_gte
    retrieval_text: >
      承保时间 承保日期 承保年月日 及之后承保 及以上承保
      年及以后承保 年以上承保 ≥ 大于等于（包含等于） 不少于 不低于 以上 及以上
    field: latelyUndwrtSegTime
    operator: GTE
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示保单承保时间（保险公司正式承保的日期，非投保申请时间）晚于或等于某个日期"
    examples:
      - query: "2020年及之后承保的客户"
        output: { field: latelyUndwrtSegTime, operator: GTE, value: "2020-01-01" }
      - query: "2020年之后承保的客户"
        output: { field: latelyUndwrtSegTime, operator: GTE, value: "2020-01-01" }
      - query: "承保时间大于等于2025年5月6号的客户"
        output: { field: latelyUndwrtSegTime, operator: GTE, value: "2025-05-06" }
      - query: "承保时间不少于2025年的客户"
        output: { field: latelyUndwrtSegTime, operator: GTE, value: "2025-01-01" }
    negative_examples:
      - query: "2020年投保的客户"
        reason: "投保时间不等于承保时间"

  - id: lately_undwrt_seg_time_gt
    retrieval_text: >
      承保时间 承保日期 承保年月日 之后承保（不含 以后承保（不含
      仅之后承保 大于 超过 高于 不含等于 承保时间大于年月号 最近承保时间大于
    field: latelyUndwrtSegTime
    operator: GT
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示保单承保时间（保险公司正式承保的日期，非投保申请时间）晚于某个日期（不含等于）"
    examples:
      - query: "2020年之后承保的客户（不含2020年）"
        output: { field: latelyUndwrtSegTime, operator: GT, value: "2019-12-31" }
      - query: "承保时间大于2025年5月6号的客户"
        output: { field: latelyUndwrtSegTime, operator: GT, value: "2025-05-05" }
      - query: "承保时间超过2025年的客户"
        output: { field: latelyUndwrtSegTime, operator: GT, value: "2024-12-31" }

  - id: lately_undwrt_seg_time_lte
    retrieval_text: >
      承保时间 承保日期 承保年月日 之前承保 及之前承保
      年及以前承保 年以前承保 小于等于 不超过 至多 以下 及以下 最近承保时间大于等于
    field: latelyUndwrtSegTime
    operator: LTE
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示保单承保时间（保险公司正式承保的日期，非投保申请时间）早于或等于某个日期"
    examples:
      - query: "2020年及之前承保的客户"
        output: { field: latelyUndwrtSegTime, operator: LTE, value: "2020-12-31" }
      - query: "2020年之前承保的客户"
        output: { field: latelyUndwrtSegTime, operator: LTE, value: "2020-12-31" }
      - query: "承保时间小于等于2025年5月6号的客户"
        output: { field: latelyUndwrtSegTime, operator: LTE, value: "2025-05-06" }

  - id: lately_undwrt_seg_time_lt
    retrieval_text: >
      承保时间 承保日期 承保年月日 之前承保（不含 以前承保（不含
      仅之前承保 小于 低于 少于 不含等于 承保时间小于年月号 最近承保时间小于
    field: latelyUndwrtSegTime
    operator: LT
    value_type: date
    format: "yyyy-MM-dd"
    description: "表示保单承保时间（保险公司正式承保的日期，非投保申请时间）早于某个日期（不含等于）"
    examples:
      - query: "2020年之前承保的客户（不含2020年）"
        output: { field: latelyUndwrtSegTime, operator: LT, value: "2020-01-01" }
      - query: "承保时间小于2025年5月6号的客户"
        output: { field: latelyUndwrtSegTime, operator: LT, value: "2025-05-06" }
      - query: "承保时间低于2025年的客户"
        output: { field: latelyUndwrtSegTime, operator: LT, value: "2025-01-01" }
  # ==================== 0610 新增客户分类及会员等级字段 ====================
  # 每个 field + operator 单独一条知识，便于按操作符精确召回。
  # 基于 Excel 规格（客户搜索字段说明最新版0610.xlsx）与真实用户查询构建。

  - id: client_churn_tag_0610_match
    retrieval_text: |-
        濒临失效高客 顶级失效高客 高客濒临失效 濒临失效高客标签 高客失效标记 是否濒临失效高客 可投资资产50万以上且有保单失效风险 哪些客户是顶级失效高客 已经是濒临失效高客 哪些客户已经算顶级失效高客了 为 是 等于 精确匹配
    field: clientChurnTag
    operator: MATCH
    value_type: enum
    enum_ref: clientChurnTag
    description: "客户是否属于濒临失效高客；定义为可投资资产达到或超过50万元，且存在保单失效风险"
    notes: "该字段是业务侧已计算的组合标签，不要拆成资产规模与保单状态。"
    examples:
      - query: "濒临失效高客"
        output: {field: clientChurnTag, operator: MATCH, value: 是}
      - query: "可投资资产50万以上且有保单失效风险的客户"
        output: {field: clientChurnTag, operator: MATCH, value: 是}
    negative_examples:
      - query: "可投资资产50万以上的客户"
        reason: "缺少保单失效风险条件，不能判定为濒临失效高客"
      - query: "有失效保单的客户"
        reason: "保单已经失效不等同于存在失效风险"

  - id: client_churn_tag_0610_not_exists
    retrieval_text: |-
        排除顶级失效高客 把顶级失效高客排除掉 不是顶级失效高客的 顶级失效高客标签还没打 标签为空 没有标签
    field: clientChurnTag
    operator: NOT_EXISTS
    value_type: none
    description: "表示客户没有濒临失效高客标签"
    examples:
      - query: "不是濒临失效高客的客户"
        output: {field: clientChurnTag, operator: NOT_EXISTS, value: ""}

  - id: ayy_member_product_match
    retrieval_text: |-
        安有医 服务线 服务线名称 产品线 会员服务 权益 开通了安有医 购买了安有医 买了安有医 享有安有医 已有安有医 有安有医权益的 安有医客户 安有医会员 安有医的客户 开通安有医服务的 有安有医权益 包含安有医
        有安有医服务线 有安有医的 获得安有医的客户 拿到安有医的 有安有医吗 是不是安有医 怎么查安有医 有安有医权益的客户
    field: ayyMemberGradeInfo.ayymemberproductname
    operator: MATCH
    value_type: enum
    enum_ref: ayyMemberGradeInfo.ayymemberproductname
    description: "安有医会员服务线名称，不表示其他服务线"
    notes: "枚举值「安有医」；有该服务线即表示客户开通了安有医会员服务"
    examples:
      - query: "服务线为安有医的客户"
        output: {field: ayyMemberGradeInfo.ayymemberproductname, operator: MATCH, value: 安有医}
    negative_examples:
      - query: "安有医达标的客户"
        reason: "达标是会员状态(status)，不是服务线"

  - id: ayy_member_product_contains
    retrieval_text: |-
        安有医 服务线 会员服务 权益 也开通了 同时有 还有 既有 也有 和 或 或者 包含安有医 有安有医和 安有医都有 安有医以及 多种权益 多个服务线
    field: ayyMemberGradeInfo.ayymemberproductname
    operator: CONTAINS
    value_type: enum
    enum_ref: ayyMemberGradeInfo.ayymemberproductname
    description: "安有医会员服务线名称，用于多服务线组合查询"
    notes: "查询同时拥有多个服务线的客户时使用CONTAINS"
    examples:
      - query: "有安有医也有安有护的客户"
        output: {field: ayyMemberGradeInfo.ayymemberproductname, operator: CONTAINS, value: [安有医,
    安有护]}
    negative_examples:
      - query: "只有安有医的客户"
        reason: "单一服务线查询应为MATCH"

  - id: ayy_member_product_not_contains
    retrieval_text: |-
        安有医 服务线 会员服务 权益 没有安有医 不是安有医 不包含安有医 不含安有医 排除安有医 不要安有医 无安有医 没安有医 非安有医 除了安有医之外 安有医除外 去掉安有医 但没有安有医
    field: ayyMemberGradeInfo.ayymemberproductname
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: ayyMemberGradeInfo.ayymemberproductname
    description: "安有医会员服务线名称，用于排除查询"
    notes: "排除安有医服务线的客户时使用NOT_CONTAINS"
    examples:
      - query: "没有安有医服务线的客户"
        output: {field: ayyMemberGradeInfo.ayymemberproductname, operator: NOT_CONTAINS, value: 安有医}
      - query: "有安有护但没有安有医的客户"
        output: {field: ayyMemberGradeInfo.ayymemberproductname, operator: NOT_CONTAINS, value: 安有医}
    negative_examples:
      - query: "有安有医的客户"
        reason: "正向匹配应使用MATCH"

  - id: ayy_member_product_exists
    retrieval_text: |-
      有安有医权益的 包含安有医 是不是安有医 享有安有医 有安有医服务线 安有医 开通了安有医 有安有医吗 有安有医的 开通安有医服务的 有安有医权益的客户 会员服务 权益 怎么查安有员 安有医客户 安有医会员 有没有安有医服务线 获得安有医的客户
    field: ayyMemberGradeInfo.ayymemberproductname
    operator: EXISTS
    value_type: exists
    description: "安有医会员服务线是否有值"
    notes: "仅判断安有医服务线是否有记录，不关心具体值"
    examples:
      - query: "有安有医权益的客户"
        output: {field: ayyMemberGradeInfo.ayymemberproductname, operator: EXISTS, value: ''}
      - query: "开通了安有医的客户"
        output: { field: ayyMemberGradeInfo.ayymemberproductname, operator: EXISTS, value: '' }
    negative_examples:
      - query: "安有医客户"
        reason: "指定了具体服务线值，应使用MATCH"

  - id: ayy_member_product_not_exists
    retrieval_text: |-
        安有医 服务线 会员服务 权益 安有医服务线为空 安有医权益为空 安有医服务线没值 安有医没有记录 没有安有医服务线 没有安有医权益 没有安有医会员 还没开通安有医 没拿到安有医 无安有医服务线 无安有医权益 安有医为空
        所有会员权益都没标的 权益都没标
    field: ayyMemberGradeInfo.ayymemberproductname
    operator: NOT_EXISTS
    value_type: exists
    description: "安有医会员服务线是否为空"
    notes: "查询没有安有医服务线记录的客户"
    examples:
      - query: "没有安有医权益的客户"
        output: {field: ayyMemberGradeInfo.ayymemberproductname, operator: NOT_EXISTS, value: ''}
      - query: "安有医权益为空的客户"
        output: {field: ayyMemberGradeInfo.ayymemberproductname, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不是安有医的客户"
        reason: "可能是排除特定值而非判断字段是否存在"

  - id: ayy_member_grade_match
    retrieval_text: |-
        安有医 会员等级 等级 版本 级别 档次 易核版 惠享版 悦享版 尊享版 颐享版 加享1 加享2 加享3 加享4 加享5 安有医等级 安有医版本 安有医什么等级 安有医哪个版本 安有医是什么级别 包含 不包含 有等级 无等级
        等级为空 等级不为空 安有医有等级吗
    field: ayyMemberGradeInfo.ayymembergradesearch
    operator: MATCH
    value_type: enum
    enum_ref: ayyMemberGradeInfo.ayymembergradesearch
    description: "安有医会员等级或版本，不表示安有医达标状态"
    notes: "枚举值共10个：易核版、惠享版、悦享版、尊享版、颐享版、加享1、加享2、加享3、加享4、加享5；各版本为并列关系，无固定高低排序"
    examples:
      - query: "安有医易核版的客户"
        output: {field: ayyMemberGradeInfo.ayymembergradesearch, operator: MATCH, value: 易核版}
      - query: "安有医等级是易核版的客户"
        output: {field: ayyMemberGradeInfo.ayymembergradesearch, operator: MATCH, value: 易核版}
    negative_examples:
      - query: "安有医达标的客户"
        reason: "达标是会员状态(status)，不是等级(grade)"

  - id: ayy_member_grade_contains
    retrieval_text: |-
        安有医 会员等级 等级 版本 易核版 惠享版 悦享版 尊享版 颐享版 加享1 加享2 加享3 加享4 加享5 或者 或 和 及 与 都要 都查 都查一下 都可以 安有医或者 安有医和 安有医以及 包含 含有 多个等级
        多个版本
    field: ayyMemberGradeInfo.ayymembergradesearch
    operator: CONTAINS
    value_type: enum
    enum_ref: ayyMemberGradeInfo.ayymembergradesearch
    description: "安有医会员等级多值查询"
    notes: "查询多个安有医等级时使用CONTAINS"
    examples:
      - query: "安有医易核版或者易核版都查一下"
        output: {field: ayyMemberGradeInfo.ayymembergradesearch, operator: CONTAINS, value: [易核版,
    易核版]}
    negative_examples:
      - query: "安有医易核版的客户"
        reason: "单一等级查询应为MATCH"

  - id: ayy_member_grade_not_contains
    retrieval_text: |-
        安有医 会员等级 等级 版本 易核版 惠享版 悦享版 尊享版 颐享版 加享1 加享2 加享3 加享4 加享5 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 安有医不要 安有医排除 安有医不是
        安有医不包含
    field: ayyMemberGradeInfo.ayymembergradesearch
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: ayyMemberGradeInfo.ayymembergradesearch
    description: "安有医会员等级排除查询"
    notes: "排除某个安有医等级时使用NOT_CONTAINS"
    examples:
      - query: "不要易核版的安有医客户"
        output: {field: ayyMemberGradeInfo.ayymembergradesearch, operator: NOT_CONTAINS, value: 易核版}
    negative_examples:
      - query: "安有医易核版的客户"
        reason: "正向匹配应使用MATCH"

  - id: ayy_member_grade_exists
    retrieval_text: |-
        安有医 会员等级 等级 版本 有等级 有版本 有等级吗 有没有等级 是否有等级 等级不为空 等级已定 等级已填 已定级 安有医有等级 安有医有版本 安有医已定级 安有医等级不为空
    field: ayyMemberGradeInfo.ayymembergradesearch
    operator: EXISTS
    value_type: exists
    description: "安有医会员等级是否有值"
    notes: "仅判断安有医是否有等级记录，不关心具体等级值"
    examples:
      - query: "有安有医等级的客户"
        output: {field: ayyMemberGradeInfo.ayymembergradesearch, operator: EXISTS, value: ''}
    negative_examples:
      - query: "安有医易核版的客户"
        reason: "指定了具体等级值，应使用MATCH"

  - id: ayy_member_grade_not_exists
    retrieval_text: |-
        安有医 会员等级 等级 版本 等级为空 等级没值 等级没填 等级没定 还没定级 没有等级 无等级 等级没登记 等级还没定的 没等级 安有医等级为空 安有医没等级 安有医等级还没定的 安有医等级没登记的
    field: ayyMemberGradeInfo.ayymembergradesearch
    operator: NOT_EXISTS
    value_type: exists
    description: "安有医会员等级是否为空"
    notes: "查询安有医等级未登记或未填写的客户"
    examples:
      - query: "安有医等级还没定的客户"
        output: {field: ayyMemberGradeInfo.ayymembergradesearch, operator: NOT_EXISTS, value: ''}
      - query: "没有安有医等级的客户"
        output: {field: ayyMemberGradeInfo.ayymembergradesearch, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要安有医易核版的客户"
        reason: "排除特定等级值使用NOT_CONTAINS"

  - id: ayy_member_status_match
    enum_requires_anchor: true
    retrieval_text: |-
        安有医 会员类型 会员状态 类型 状态 是什么状态 什么状态 什么类型 哪种状态 达标 安有医状态 安有医类型 安有医会员类型 安有医的状态 安有医是什么状态 安有医会员状态 包含 不包含 有状态 无状态 状态为空
        状态不为空
    field: ayyMemberGradeInfo.ayymemberstatus
    operator: MATCH
    value_type: enum
    enum_ref: ayyMemberGradeInfo.ayymemberstatus
    description: "安有医会员类型或状态，不表示安有医等级版本"
    notes: "枚举值共1个：达标；状态互斥，一个客户同一时间只能属于一种状态"
    examples:
      - query: "安有医达标的客户"
        output: {field: ayyMemberGradeInfo.ayymemberstatus, operator: MATCH, value: 达标}
      - query: "安有医是达标客户"
        output: {field: ayyMemberGradeInfo.ayymemberstatus, operator: MATCH, value: 达标}
    negative_examples:
      - query: "安有医易核版的客户"
        reason: "易核版是等级(grade)，不是状态(status)"

  - id: ayy_member_status_contains
    enum_requires_anchor: true
    retrieval_text: |-
        安有医 会员类型 会员状态 类型 状态 达标 潜客 意向 临界 临界客户 包含 含有 或者 或 和 都要 都查 安有医或者 安有医或 安有医以及 安有医和
    field: ayyMemberGradeInfo.ayymemberstatus
    operator: CONTAINS
    value_type: enum
    enum_ref: ayyMemberGradeInfo.ayymemberstatus
    description: "安有医会员类型多值查询"
    notes: "查询多种安有医状态时使用CONTAINS；临界客户=潜客或意向"
    examples:
      - query: "安有医达标或者达标客户"
        output: {field: ayyMemberGradeInfo.ayymemberstatus, operator: CONTAINS, value: [达标, 达标]}
    negative_examples:
      - query: "安有医达标客户"
        reason: "单一状态查询应为MATCH"

  - id: ayy_member_status_not_contains
    enum_requires_anchor: true
    retrieval_text: |-
        安有医 会员类型 会员状态 类型 状态 达标 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 安有医不要 安有医排除 安有医不包含
    field: ayyMemberGradeInfo.ayymemberstatus
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: ayyMemberGradeInfo.ayymemberstatus
    description: "安有医会员类型排除查询"
    notes: "排除某种安有医状态时使用NOT_CONTAINS"
    examples:
      - query: "安有医不要达标客户"
        output: {field: ayyMemberGradeInfo.ayymemberstatus, operator: NOT_CONTAINS, value: 达标}
    negative_examples:
      - query: "安有医达标客户"
        reason: "正向匹配应使用MATCH"

  - id: ayy_member_status_exists
    retrieval_text: |-
        安有医 会员类型 会员状态 类型 状态 有状态 有类型 有会员状态 有会员类型 状态不为空 类型不为空 状态已标 状态已登记 已有状态 安有医有状态 安有医状态不为空 安有医状态已填
    field: ayyMemberGradeInfo.ayymemberstatus
    operator: EXISTS
    value_type: exists
    description: "安有医会员类型是否有值"
    notes: "仅判断安有医是否有状态记录，不关心具体状态值"
    examples:
      - query: "有安有医状态的客户"
        output: {field: ayyMemberGradeInfo.ayymemberstatus, operator: EXISTS, value: ''}
    negative_examples:
      - query: "安有医达标客户"
        reason: "指定了具体状态值，应使用MATCH"

  - id: ayy_member_status_not_exists
    retrieval_text: |-
        安有医 会员类型 会员状态 类型 状态 状态为空 类型为空 没有状态 无状态 状态没标 状态没填 会员状态没标的 状态还没登记 状态没值 安有医状态为空 安有医状态没标的 安有医没状态 安有医状态还没登记的
    field: ayyMemberGradeInfo.ayymemberstatus
    operator: NOT_EXISTS
    value_type: exists
    description: "安有医会员类型是否为空"
    notes: "查询安有医状态未登记的客户"
    examples:
      - query: "安有医会员状态没标的客户"
        output: {field: ayyMemberGradeInfo.ayymemberstatus, operator: NOT_EXISTS, value: ''}
      - query: "没有安有医状态的客户"
        output: {field: ayyMemberGradeInfo.ayymemberstatus, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要安有医达标客户"
        reason: "排除特定状态值使用NOT_CONTAINS"

  - id: ayy_member_period_match
    retrieval_text: |-
        安有医 会员期次 期次 会员年度 年度 哪一期 什么期次 哪个年度 M2023 M2024 M2025 M年份 包含2023年期 包含2024年期的 包含2025年期的 2023年那期 2024年那期 23年那期 24年那期
        安有医2023年 安有医2024年 安有医2025年 安有医期次 安有医年度 安有医哪一期 安有医哪个年度 是哪一期 哪年那期 2024年那一期 2025年那一期 有期次 无期次 期次为空 期次不为空
    field: ayyMemberGradeInfo.ayymemberperiod
    operator: MATCH
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "安有医会员期次（年度），不表示安有医达标时间"
    notes: "期次为年份格式YYYY，如2023、2024、2025；一个客户可能拥有多个年度的期次记录"
    examples:
      - query: "安有医2024年期的客户"
        output: {field: ayyMemberGradeInfo.ayymemberperiod, operator: MATCH, value: '2024'}
      - query: "23年那期安有医"
        output: {field: ayyMemberGradeInfo.ayymemberperiod, operator: MATCH, value: '2023'}
    negative_examples:
      - query: "2024年达标的安有医客户"
        reason: "2024年是达标时间(qualifiedtime)，不是期次(period)"

  - id: ayy_member_period_contains
    retrieval_text: |-
        安有医 会员期次 期次 年度 包含 含有 包括 有 都有 和 及 与 以及 包含2023年期 包含2024年期的 包含2025年期的 安有医2023到2025 安有医2023至2025 2023和2024年期 多个期次
        几个年度
    field: ayyMemberGradeInfo.ayymemberperiod
    operator: CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "安有医会员期次多值查询"
    notes: "查询包含多个期次时使用CONTAINS"
    examples:
      - query: "安有医包含2023年期和2024年期的客户"
        output: {field: ayyMemberGradeInfo.ayymemberperiod, operator: CONTAINS, value: ['2023', '2024']}
    negative_examples:
      - query: "安有医2024年期的客户"
        reason: "单一年份应使用MATCH"

  - id: ayy_member_period_not_contains
    retrieval_text: |-
        安有医 会员期次 期次 年度 不包含 不含 不要 排除 去除 没有 不包含2023年期 不包含2024年期 不包含2025年期 安有医不包含 安有医不含 安有医不要
    field: ayyMemberGradeInfo.ayymemberperiod
    operator: NOT_CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "安有医会员期次排除查询"
    notes: "排除某些期次时使用NOT_CONTAINS"
    examples:
      - query: "安有医不包含2023年期的客户"
        output: {field: ayyMemberGradeInfo.ayymemberperiod, operator: NOT_CONTAINS, value: '2023'}
    negative_examples:
      - query: "安有医包含2023年期的客户"
        reason: "正向匹配应使用MATCH或CONTAINS"

  - id: ayy_member_period_exists
    retrieval_text: |-
        安有医 会员期次 期次 年度 有期次 有年度 有期次吗 有没有期次 是否有期次 期次不为空 期次已登记 期次已填 已登记期次 安有医有期次 安有医期次不为空 安有医期次已填
    field: ayyMemberGradeInfo.ayymemberperiod
    operator: EXISTS
    value_type: exists
    description: "安有医会员期次是否有值"
    notes: "仅判断安有医是否有期次记录，不关心具体年份"
    examples:
      - query: "有安有医期次的客户"
        output: {field: ayyMemberGradeInfo.ayymemberperiod, operator: EXISTS, value: ''}
    negative_examples:
      - query: "安有医2024年期的客户"
        reason: "指定了具体年份值，应使用MATCH"

  - id: ayy_member_period_not_exists
    retrieval_text: |-
        安有医 会员期次 期次 年度 期次为空 期次没值 期次没填 没有期次 无期次 期次没登记 期次还没登记 没填期次 哪一期没登记 哪一期还没登记 权益期次没有的 期次没填的 安有医期次为空 安有医期次没填的 安有医没有期次
        安有医哪一期没登记 安有医期次没登记
    field: ayyMemberGradeInfo.ayymemberperiod
    operator: NOT_EXISTS
    value_type: exists
    description: "安有医会员期次是否为空"
    notes: "查询安有医期次未登记的客户"
    examples:
      - query: "安有医期次没填的客户"
        output: {field: ayyMemberGradeInfo.ayymemberperiod, operator: NOT_EXISTS, value: ''}
      - query: "安有医是哪一期还没登记的客户"
        output: {field: ayyMemberGradeInfo.ayymemberperiod, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "安有医不包含2023年期的客户"
        reason: "排除特定期次值使用NOT_CONTAINS"

  - id: ayy_qualified_time_range
    retrieval_text: |-
        安有医 达标时间 达标日期 获得时间 获得日期 拿到时间 什么时候达标 何时达标 哪年达标 什么时候获得 安有医达标 安有医获得 安有医拿到 安有医达标时间 安有医获得时间 安有医什么时候达标 时间范围 从到 之间 去年
        今年 2023年 2024年 2025年 近一周 近一个月 近一年 近期 最近 最近一个月 本季度 去年 前年 去年二季度 去年下半年 上半年 下半年 大于 小于 之后 之前 以来 至今 一个月内 一年内 一周内 半年内
        三个月内 去年6月以后 达标时间 安有医达标时间
    field: ayyMemberGradeInfo.ayyqualifiedtime
    operator: RANGE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "安有医会员达标时间（达标日期），不表示安有医期次"
    notes: "达标时间指客户满足会员资格条件的日期，格式yyyy-MM-dd"
    examples:
      - query: "2024年安有医达标的客户"
        output: {field: ayyMemberGradeInfo.ayyqualifiedtime, operator: RANGE, value: {max: '2024-12-31',
    min: '2024-01-01'}}
      - query: "安有医近一年达标的客户"
        output: {field: ayyMemberGradeInfo.ayyqualifiedtime, operator: RANGE, value: {max: '2026-06-11',
    min: '2025-06-11'}}
      - query: "安有医去年二季度达标的客户"
        output: {field: ayyMemberGradeInfo.ayyqualifiedtime, operator: RANGE, value: {max: '2025-06-30',
    min: '2025-04-01'}}
    negative_examples:
      - query: "安有医2024年期的客户"
        reason: "2024年期是期次(period)，不是达标时间"

  - id: ayy_qualified_time_gt
    retrieval_text: |-
        安有医 达标时间 获得时间 达标日期 大于 之后 以后 之后达标 以后获得 安有医之后达标 安有医以后获得 2023年以后 2024年以后 2025年以后 去年以后 去年6月以后
    field: ayyMemberGradeInfo.ayyqualifiedtime
    operator: GT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "安有医会员达标时间大于某日期"
    notes: "查询在某日期之后达标的客户"
    examples:
      - query: "2023年以后拿到安有医权益的"
        output: {field: ayyMemberGradeInfo.ayyqualifiedtime, operator: GT, value: '2023-12-31'}
    negative_examples:
      - query: "2024年安有医达标的客户"
        reason: "指定年份范围应使用RANGE"

  - id: ayy_qualified_time_gte
    retrieval_text: |-
        安有医 达标时间 获得时间 达标日期 大于等于 不小于 及之后 及以上 及以后 至少 安有医及之后达标 安有医及以上 安有医大于等于 2023年及之后 2024年及以后
    field: ayyMemberGradeInfo.ayyqualifiedtime
    operator: GTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "安有医会员达标时间大于等于某日期"
    notes: "查询在某日期及之后达标的客户"
    examples:
      - query: "2024年及之后安有医达标的客户"
        output: {field: ayyMemberGradeInfo.ayyqualifiedtime, operator: GTE, value: '2024-01-01'}
    negative_examples:
      - query: "2024年安有医达标的客户"
        reason: "精确年份范围应使用RANGE"

  - id: ayy_qualified_time_lt
    retrieval_text: |-
        安有医 达标时间 获得时间 达标日期 小于 之前 以前 之前达标 以前获得 安有医之前达标 安有医以前获得 2025年以前 25年以前 2024年之前 2023年之前
    field: ayyMemberGradeInfo.ayyqualifiedtime
    operator: LT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "安有医会员达标时间小于某日期"
    notes: "查询在某日期之前达标的客户"
    examples:
      - query: "25年以前获得安有医的"
        output: {field: ayyMemberGradeInfo.ayyqualifiedtime, operator: LT, value: '2025-01-01'}
    negative_examples:
      - query: "2024年之前安有医期次"
        reason: "期次使用memberperiod字段，不是qualifiedtime"

  - id: ayy_qualified_time_lte
    retrieval_text: |-
        安有医 达标时间 获得时间 达标日期 小于等于 不大于 及之前 及以前 至多 最晚 安有医及之前达标 安有医不大于 安有医小于等于 去年年底前 2024年底前 2023年底前
    field: ayyMemberGradeInfo.ayyqualifiedtime
    operator: LTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "安有医会员达标时间小于等于某日期"
    notes: "查询在某日期及之前达标的客户"
    examples:
      - query: "去年年底前获得安有医的客户"
        output: {field: ayyMemberGradeInfo.ayyqualifiedtime, operator: LTE, value: '2025-12-31'}
    negative_examples:
      - query: "安有医去年达标的客户"
        reason: "整年范围应使用RANGE"

  - id: ayy_qualified_time_exists
    retrieval_text: |-
        安有医 达标时间 获得时间 达标日期 拿到时间 有达标时间 有获得时间 有时间 达标时间不为空 获得时间不为空 已达标 已拿到 已获得 已登记达标时间 安有医有达标时间 安有医获得时间不为空 安有医已达标
    field: ayyMemberGradeInfo.ayyqualifiedtime
    operator: EXISTS
    value_type: exists
    description: "安有医会员达标时间是否有值"
    notes: "仅判断安有医是否有达标时间记录"
    examples:
      - query: "有安有医达标时间的客户"
        output: {field: ayyMemberGradeInfo.ayyqualifiedtime, operator: EXISTS, value: ''}
    negative_examples:
      - query: "2024年安有医达标的客户"
        reason: "指定了具体达标时间，应使用RANGE"

  - id: ayy_qualified_time_not_exists
    retrieval_text: |-
        安有医 达标时间 达标日期 获得时间 获得日期 达标时间为空 获得时间为空 达标时间没值 达标时间没填 没有达标时间 达标时间没记录 达标日期为空 获得时间没记录的 达标时间空着 达标时间还空着 没有获得时间 无达标时间
        无获得时间 获得日期为空 什么时候达标的没记 获得时间没记录的 安有医达标时间为空 安有医获得时间没记录的 安有医达标时间还空着 安有医没有达标时间
    field: ayyMemberGradeInfo.ayyqualifiedtime
    operator: NOT_EXISTS
    value_type: exists
    description: "安有医会员达标时间是否为空"
    notes: "查询安有医达标时间未记录的客户"
    examples:
      - query: "安有医达标时间为空的客户"
        output: {field: ayyMemberGradeInfo.ayyqualifiedtime, operator: NOT_EXISTS, value: ''}
      - query: "安有医获得时间没记录的"
        output: {field: ayyMemberGradeInfo.ayyqualifiedtime, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "安有医还没有达标的客户"
        reason: "可能是查询达标状态(status)而非达标时间"

  - id: ayh_member_product_match
    retrieval_text: |-
        安有护 服务线 服务线名称 产品线 会员服务 权益 开通了安有护 购买了安有护 买了安有护 享有安有护 已有安有护 有安有护权益的 安有护客户 安有护会员 安有护的客户 开通安有护服务的 有安有护权益 包含安有护
        有安有护服务线 有安有护的 获得安有护的客户 拿到安有护的 有安有护吗 是不是安有护 怎么查安有护 有安有护权益的客户
    field: ayhMemberGradeInfo.ayhmemberproductname
    operator: MATCH
    value_type: enum
    enum_ref: ayhMemberGradeInfo.ayhmemberproductname
    description: "安有护会员服务线名称，不表示其他服务线"
    notes: "枚举值「安有护」；有该服务线即表示客户开通了安有护会员服务"
    examples:
      - query: "服务线为安有护的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberproductname, operator: MATCH, value: 安有护}
    negative_examples:
      - query: "安有护达标的客户"
        reason: "达标是会员状态(status)，不是服务线"

  - id: ayh_member_product_contains
    retrieval_text: |-
        安有护 服务线 会员服务 权益 也开通了 同时有 还有 既有 也有 和 或 或者 包含安有护 有安有护和 安有护都有 安有护以及 多种权益 多个服务线
    field: ayhMemberGradeInfo.ayhmemberproductname
    operator: CONTAINS
    value_type: enum
    enum_ref: ayhMemberGradeInfo.ayhmemberproductname
    description: "安有护会员服务线名称，用于多服务线组合查询"
    notes: "查询同时拥有多个服务线的客户时使用CONTAINS"
    examples:
      - query: "有安有护也有安有护的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberproductname, operator: CONTAINS, value: [安有护,
    安有护]}
    negative_examples:
      - query: "只有安有护的客户"
        reason: "单一服务线查询应为MATCH"

  - id: ayh_member_product_not_contains
    retrieval_text: |-
        安有护 服务线 会员服务 权益 没有安有护 不是安有护 不包含安有护 不含安有护 排除安有护 不要安有护 无安有护 没安有护 非安有护 除了安有护之外 安有护除外 去掉安有护 但没有安有护
    field: ayhMemberGradeInfo.ayhmemberproductname
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: ayhMemberGradeInfo.ayhmemberproductname
    description: "安有护会员服务线名称，用于排除查询"
    notes: "排除安有护服务线的客户时使用NOT_CONTAINS"
    examples:
      - query: "没有安有护服务线的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberproductname, operator: NOT_CONTAINS, value: 安有护}
      - query: "有安有护但没有安有护的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberproductname, operator: NOT_CONTAINS, value: 安有护}
    negative_examples:
      - query: "有安有护的客户"
        reason: "正向匹配应使用MATCH"

  - id: ayh_member_product_exists
    retrieval_text: |-
        安有护 服务线 会员服务 权益 开通安有护了吗 是否有安有护 有没有安有护服务线 获得安有护的客户 拿到安有护的 有安有护会员 安有护服务线不为空 有安有护服务线 有安有护权益
    field: ayhMemberGradeInfo.ayhmemberproductname
    operator: EXISTS
    value_type: exists
    description: "安有护会员服务线是否有值"
    notes: "仅判断安有护服务线是否有记录，不关心具体值"
    examples:
      - query: "有安有护权益的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberproductname, operator: EXISTS, value: ''}
      - query: "开通了安有护的客户"
        output: { field: ayhMemberGradeInfo.ayhmemberproductname, operator: EXISTS, value: ''}
    negative_examples:
      - query: "安有护客户"
        reason: "指定了具体服务线值，应使用MATCH"

  - id: ayh_member_product_not_exists
    retrieval_text: |-
        安有护 服务线 会员服务 权益 安有护服务线为空 安有护权益为空 安有护服务线没值 安有护没有记录 没有安有护服务线 没有安有护权益 没有安有护会员 还没开通安有护 没拿到安有护 无安有护服务线 无安有护权益 安有护为空
        所有会员权益都没标的 权益都没标
    field: ayhMemberGradeInfo.ayhmemberproductname
    operator: NOT_EXISTS
    value_type: exists
    description: "安有护会员服务线是否为空"
    notes: "查询没有安有护服务线记录的客户"
    examples:
      - query: "没有安有护权益的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberproductname, operator: NOT_EXISTS, value: ''}
      - query: "安有护权益为空的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberproductname, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不是安有护的客户"
        reason: "可能是排除特定值而非判断字段是否存在"

  - id: ayh_member_grade_match
    retrieval_text: |-
        安有护 会员等级 等级 版本 级别 档次 安有护(国内版) 安有护(国际版) 安有护等级 安有护版本 安有护什么等级 安有护哪个版本 安有护是什么级别 包含 不包含 有等级 无等级 等级为空 等级不为空 安有护有等级吗
    field: ayhMemberGradeInfo.ayhmembergradesearch
    operator: MATCH
    value_type: enum
    enum_ref: ayhMemberGradeInfo.ayhmembergradesearch
    description: "安有护会员等级或版本，不表示安有护达标状态"
    notes: "枚举值共2个：安有护(国内版)、安有护(国际版)；各版本为并列关系，无固定高低排序"
    examples:
      - query: "安有护安有护(国内版)的客户"
        output: {field: ayhMemberGradeInfo.ayhmembergradesearch, operator: MATCH, value: 安有护(国内版)}
      - query: "安有护等级是安有护(国内版)的客户"
        output: {field: ayhMemberGradeInfo.ayhmembergradesearch, operator: MATCH, value: 安有护(国内版)}
    negative_examples:
      - query: "安有护达标的客户"
        reason: "达标是会员状态(status)，不是等级(grade)"

  - id: ayh_member_grade_contains
    retrieval_text: |-
        安有护 会员等级 等级 版本 安有护(国内版) 安有护(国际版) 或者 或 和 及 与 都要 都查 都查一下 都可以 安有护或者 安有护和 安有护以及 包含 含有 多个等级 多个版本
    field: ayhMemberGradeInfo.ayhmembergradesearch
    operator: CONTAINS
    value_type: enum
    enum_ref: ayhMemberGradeInfo.ayhmembergradesearch
    description: "安有护会员等级多值查询"
    notes: "查询多个安有护等级时使用CONTAINS"
    examples:
      - query: "安有护安有护(国内版)或者安有护(国内版)都查一下"
        output: {field: ayhMemberGradeInfo.ayhmembergradesearch, operator: CONTAINS, value: [安有护(国内版),
    安有护(国内版)]}
    negative_examples:
      - query: "安有护安有护(国内版)的客户"
        reason: "单一等级查询应为MATCH"

  - id: ayh_member_grade_not_contains
    retrieval_text: |-
        安有护 会员等级 等级 版本 安有护(国内版) 安有护(国际版) 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 安有护不要 安有护排除 安有护不是 安有护不包含
    field: ayhMemberGradeInfo.ayhmembergradesearch
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: ayhMemberGradeInfo.ayhmembergradesearch
    description: "安有护会员等级排除查询"
    notes: "排除某个安有护等级时使用NOT_CONTAINS"
    examples:
      - query: "不要安有护(国内版)的安有护客户"
        output: {field: ayhMemberGradeInfo.ayhmembergradesearch, operator: NOT_CONTAINS, value: 安有护(国内版)}
    negative_examples:
      - query: "安有护安有护(国内版)的客户"
        reason: "正向匹配应使用MATCH"

  - id: ayh_member_grade_exists
    retrieval_text: |-
        安有护 会员等级 等级 版本 有等级 有版本 有等级吗 有没有等级 是否有等级 等级不为空 等级已定 等级已填 已定级 安有护有等级 安有护有版本 安有护已定级 安有护等级不为空
    field: ayhMemberGradeInfo.ayhmembergradesearch
    operator: EXISTS
    value_type: exists
    description: "安有护会员等级是否有值"
    notes: "仅判断安有护是否有等级记录，不关心具体等级值"
    examples:
      - query: "有安有护等级的客户"
        output: {field: ayhMemberGradeInfo.ayhmembergradesearch, operator: EXISTS, value: ''}
    negative_examples:
      - query: "安有护安有护(国内版)的客户"
        reason: "指定了具体等级值，应使用MATCH"

  - id: ayh_member_grade_not_exists
    retrieval_text: |-
        安有护 会员等级 等级 版本 等级为空 等级没值 等级没填 等级没定 还没定级 没有等级 无等级 等级没登记 等级还没定的 没等级 安有护等级为空 安有护没等级 安有护等级还没定的 安有护等级没登记的
    field: ayhMemberGradeInfo.ayhmembergradesearch
    operator: NOT_EXISTS
    value_type: exists
    description: "安有护会员等级是否为空"
    notes: "查询安有护等级未登记或未填写的客户"
    examples:
      - query: "安有护等级还没定的客户"
        output: {field: ayhMemberGradeInfo.ayhmembergradesearch, operator: NOT_EXISTS, value: ''}
      - query: "没有安有护等级的客户"
        output: {field: ayhMemberGradeInfo.ayhmembergradesearch, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要安有护安有护(国内版)的客户"
        reason: "排除特定等级值使用NOT_CONTAINS"

  - id: ayh_member_status_match
    enum_requires_anchor: true
    retrieval_text: |-
        安有护 会员类型 会员状态 类型 状态 是什么状态 什么状态 什么类型 哪种状态 达标 安有护状态 安有护类型 安有护会员类型 安有护的状态 安有护是什么状态 安有护会员状态 包含 不包含 有状态 无状态 状态为空
        状态不为空
    field: ayhMemberGradeInfo.ayhmemberstatus
    operator: MATCH
    value_type: enum
    enum_ref: ayhMemberGradeInfo.ayhmemberstatus
    description: "安有护会员类型或状态，不表示安有护等级版本"
    notes: "枚举值共1个：达标；状态互斥，一个客户同一时间只能属于一种状态"
    examples:
      - query: "安有护达标的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberstatus, operator: MATCH, value: 达标}
      - query: "安有护是达标客户"
        output: {field: ayhMemberGradeInfo.ayhmemberstatus, operator: MATCH, value: 达标}
    negative_examples:
      - query: "安有护安有护(国内版)的客户"
        reason: "安有护(国内版)是等级(grade)，不是状态(status)"

  - id: ayh_member_status_contains
    enum_requires_anchor: true
    retrieval_text: |-
        安有护 会员类型 会员状态 类型 状态 达标 潜客 意向 临界 临界客户 包含 含有 或者 或 和 都要 都查 安有护或者 安有护或 安有护以及 安有护和
    field: ayhMemberGradeInfo.ayhmemberstatus
    operator: CONTAINS
    value_type: enum
    enum_ref: ayhMemberGradeInfo.ayhmemberstatus
    description: "安有护会员类型多值查询"
    notes: "查询多种安有护状态时使用CONTAINS；临界客户=潜客或意向"
    examples:
      - query: "安有护达标或者达标客户"
        output: {field: ayhMemberGradeInfo.ayhmemberstatus, operator: CONTAINS, value: [达标, 达标]}
    negative_examples:
      - query: "安有护达标客户"
        reason: "单一状态查询应为MATCH"

  - id: ayh_member_status_not_contains
    enum_requires_anchor: true
    retrieval_text: |-
        安有护 会员类型 会员状态 类型 状态 达标 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 安有护不要 安有护排除 安有护不包含
    field: ayhMemberGradeInfo.ayhmemberstatus
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: ayhMemberGradeInfo.ayhmemberstatus
    description: "安有护会员类型排除查询"
    notes: "排除某种安有护状态时使用NOT_CONTAINS"
    examples:
      - query: "安有护不要达标客户"
        output: {field: ayhMemberGradeInfo.ayhmemberstatus, operator: NOT_CONTAINS, value: 达标}
    negative_examples:
      - query: "安有护达标客户"
        reason: "正向匹配应使用MATCH"

  - id: ayh_member_status_exists
    retrieval_text: |-
        安有护 会员类型 会员状态 类型 状态 有状态 有类型 有会员状态 有会员类型 状态不为空 类型不为空 状态已标 状态已登记 已有状态 安有护有状态 安有护状态不为空 安有护状态已填
    field: ayhMemberGradeInfo.ayhmemberstatus
    operator: EXISTS
    value_type: exists
    description: "安有护会员类型是否有值"
    notes: "仅判断安有护是否有状态记录，不关心具体状态值"
    examples:
      - query: "有安有护状态的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberstatus, operator: EXISTS, value: ''}
    negative_examples:
      - query: "安有护达标客户"
        reason: "指定了具体状态值，应使用MATCH"

  - id: ayh_member_status_not_exists
    retrieval_text: |-
        安有护 会员类型 会员状态 类型 状态 状态为空 类型为空 没有状态 无状态 状态没标 状态没填 会员状态没标的 状态还没登记 状态没值 安有护状态为空 安有护状态没标的 安有护没状态 安有护状态还没登记的
    field: ayhMemberGradeInfo.ayhmemberstatus
    operator: NOT_EXISTS
    value_type: exists
    description: "安有护会员类型是否为空"
    notes: "查询安有护状态未登记的客户"
    examples:
      - query: "安有护会员状态没标的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberstatus, operator: NOT_EXISTS, value: ''}
      - query: "没有安有护状态的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberstatus, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要安有护达标客户"
        reason: "排除特定状态值使用NOT_CONTAINS"

  - id: ayh_member_period_match
    retrieval_text: |-
        安有护 会员期次 期次 会员年度 年度 哪一期 什么期次 哪个年度 M2023 M2024 M2025 M年份 包含2023年期 包含2024年期的 包含2025年期的 2023年那期 2024年那期 23年那期 24年那期
        安有护2023年 安有护2024年 安有护2025年 安有护期次 安有护年度 安有护哪一期 安有护哪个年度 是哪一期 哪年那期 2024年那一期 2025年那一期 有期次 无期次 期次为空 期次不为空
    field: ayhMemberGradeInfo.ayhmemberperiod
    operator: MATCH
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "安有护会员期次（年度），不表示安有护达标时间"
    notes: "期次为年份格式YYYY，如2023、2024、2025；一个客户可能拥有多个年度的期次记录"
    examples:
      - query: "安有护2024年期的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberperiod, operator: MATCH, value: '2024'}
      - query: "23年那期安有护"
        output: {field: ayhMemberGradeInfo.ayhmemberperiod, operator: MATCH, value: '2023'}
    negative_examples:
      - query: "2024年达标的安有护客户"
        reason: "2024年是达标时间(qualifiedtime)，不是期次(period)"

  - id: ayh_member_period_contains
    retrieval_text: |-
        安有护 会员期次 期次 年度 包含 含有 包括 有 都有 和 及 与 以及 包含2023年期 包含2024年期的 包含2025年期的 安有护2023到2025 安有护2023至2025 2023和2024年期 多个期次
        几个年度
    field: ayhMemberGradeInfo.ayhmemberperiod
    operator: CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "安有护会员期次多值查询"
    notes: "查询包含多个期次时使用CONTAINS"
    examples:
      - query: "安有护包含2023年期和2024年期的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberperiod, operator: CONTAINS, value: ['2023', '2024']}
    negative_examples:
      - query: "安有护2024年期的客户"
        reason: "单一年份应使用MATCH"

  - id: ayh_member_period_not_contains
    retrieval_text: |-
        安有护 会员期次 期次 年度 不包含 不含 不要 排除 去除 没有 不包含2023年期 不包含2024年期 不包含2025年期 安有护不包含 安有护不含 安有护不要
    field: ayhMemberGradeInfo.ayhmemberperiod
    operator: NOT_CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "安有护会员期次排除查询"
    notes: "排除某些期次时使用NOT_CONTAINS"
    examples:
      - query: "安有护不包含2023年期的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberperiod, operator: NOT_CONTAINS, value: '2023'}
    negative_examples:
      - query: "安有护包含2023年期的客户"
        reason: "正向匹配应使用MATCH或CONTAINS"

  - id: ayh_member_period_exists
    retrieval_text: |-
        安有护 会员期次 期次 年度 有期次 有年度 有期次吗 有没有期次 是否有期次 期次不为空 期次已登记 期次已填 已登记期次 安有护有期次 安有护期次不为空 安有护期次已填
    field: ayhMemberGradeInfo.ayhmemberperiod
    operator: EXISTS
    value_type: exists
    description: "安有护会员期次是否有值"
    notes: "仅判断安有护是否有期次记录，不关心具体年份"
    examples:
      - query: "有安有护期次的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberperiod, operator: EXISTS, value: ''}
    negative_examples:
      - query: "安有护2024年期的客户"
        reason: "指定了具体年份值，应使用MATCH"

  - id: ayh_member_period_not_exists
    retrieval_text: |-
        安有护 会员期次 期次 年度 期次为空 期次没值 期次没填 没有期次 无期次 期次没登记 期次还没登记 没填期次 哪一期没登记 哪一期还没登记 权益期次没有的 期次没填的 安有护期次为空 安有护期次没填的 安有护没有期次
        安有护哪一期没登记 安有护期次没登记
    field: ayhMemberGradeInfo.ayhmemberperiod
    operator: NOT_EXISTS
    value_type: exists
    description: "安有护会员期次是否为空"
    notes: "查询安有护期次未登记的客户"
    examples:
      - query: "安有护期次没填的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberperiod, operator: NOT_EXISTS, value: ''}
      - query: "安有护是哪一期还没登记的客户"
        output: {field: ayhMemberGradeInfo.ayhmemberperiod, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "安有护不包含2023年期的客户"
        reason: "排除特定期次值使用NOT_CONTAINS"

  - id: ayh_qualified_time_range
    retrieval_text: |-
        安有护 达标时间 达标日期 获得时间 获得日期 拿到时间 什么时候达标 何时达标 哪年达标 什么时候获得 安有护达标 安有护获得 安有护拿到 安有护达标时间 安有护获得时间 安有护什么时候达标 时间范围 从到 之间 去年
        今年 2023年 2024年 2025年 近一周 近一个月 近一年 近期 最近 最近一个月 本季度 去年 前年 去年二季度 去年下半年 上半年 下半年 大于 小于 之后 之前 以来 至今 一个月内 一年内 一周内 半年内
        三个月内 去年6月以后 达标时间 安有护达标时间
    field: ayhMemberGradeInfo.ayhqualifiedtime
    operator: RANGE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "安有护会员达标时间（达标日期），不表示安有护期次"
    notes: "达标时间指客户满足会员资格条件的日期，格式yyyy-MM-dd"
    examples:
      - query: "2024年安有护达标的客户"
        output: {field: ayhMemberGradeInfo.ayhqualifiedtime, operator: RANGE, value: {max: '2024-12-31',
    min: '2024-01-01'}}
      - query: "安有护近一年达标的客户"
        output: {field: ayhMemberGradeInfo.ayhqualifiedtime, operator: RANGE, value: {max: '2026-06-11',
    min: '2025-06-11'}}
      - query: "安有护去年二季度达标的客户"
        output: {field: ayhMemberGradeInfo.ayhqualifiedtime, operator: RANGE, value: {max: '2025-06-30',
    min: '2025-04-01'}}
    negative_examples:
      - query: "安有护2024年期的客户"
        reason: "2024年期是期次(period)，不是达标时间"

  - id: ayh_qualified_time_gt
    retrieval_text: |-
        安有护 达标时间 获得时间 达标日期 大于 之后 以后 之后达标 以后获得 安有护之后达标 安有护以后获得 2023年以后 2024年以后 2025年以后 去年以后 去年6月以后
    field: ayhMemberGradeInfo.ayhqualifiedtime
    operator: GT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "安有护会员达标时间大于某日期"
    notes: "查询在某日期之后达标的客户"
    examples:
      - query: "2023年以后拿到安有护权益的"
        output: {field: ayhMemberGradeInfo.ayhqualifiedtime, operator: GT, value: '2023-12-31'}
    negative_examples:
      - query: "2024年安有护达标的客户"
        reason: "指定年份范围应使用RANGE"

  - id: ayh_qualified_time_gte
    retrieval_text: |-
        安有护 达标时间 获得时间 达标日期 大于等于 不小于 及之后 及以上 及以后 至少 安有护及之后达标 安有护及以上 安有护大于等于 2023年及之后 2024年及以后
    field: ayhMemberGradeInfo.ayhqualifiedtime
    operator: GTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "安有护会员达标时间大于等于某日期"
    notes: "查询在某日期及之后达标的客户"
    examples:
      - query: "2024年及之后安有护达标的客户"
        output: {field: ayhMemberGradeInfo.ayhqualifiedtime, operator: GTE, value: '2024-01-01'}
    negative_examples:
      - query: "2024年安有护达标的客户"
        reason: "精确年份范围应使用RANGE"

  - id: ayh_qualified_time_lt
    retrieval_text: |-
        安有护 达标时间 获得时间 达标日期 小于 之前 以前 之前达标 以前获得 安有护之前达标 安有护以前获得 2025年以前 25年以前 2024年之前 2023年之前
    field: ayhMemberGradeInfo.ayhqualifiedtime
    operator: LT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "安有护会员达标时间小于某日期"
    notes: "查询在某日期之前达标的客户"
    examples:
      - query: "25年以前获得安有护的"
        output: {field: ayhMemberGradeInfo.ayhqualifiedtime, operator: LT, value: '2025-01-01'}
    negative_examples:
      - query: "2024年之前安有护期次"
        reason: "期次使用memberperiod字段，不是qualifiedtime"

  - id: ayh_qualified_time_lte
    retrieval_text: |-
        安有护 达标时间 获得时间 达标日期 小于等于 不大于 及之前 及以前 至多 最晚 安有护及之前达标 安有护不大于 安有护小于等于 去年年底前 2024年底前 2023年底前
    field: ayhMemberGradeInfo.ayhqualifiedtime
    operator: LTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "安有护会员达标时间小于等于某日期"
    notes: "查询在某日期及之前达标的客户"
    examples:
      - query: "去年年底前获得安有护的客户"
        output: {field: ayhMemberGradeInfo.ayhqualifiedtime, operator: LTE, value: '2025-12-31'}
    negative_examples:
      - query: "安有护去年达标的客户"
        reason: "整年范围应使用RANGE"

  - id: ayh_qualified_time_exists
    retrieval_text: |-
        安有护 达标时间 获得时间 达标日期 拿到时间 有达标时间 有获得时间 有时间 达标时间不为空 获得时间不为空 已达标 已拿到 已获得 已登记达标时间 安有护有达标时间 安有护获得时间不为空 安有护已达标
    field: ayhMemberGradeInfo.ayhqualifiedtime
    operator: EXISTS
    value_type: exists
    description: "安有护会员达标时间是否有值"
    notes: "仅判断安有护是否有达标时间记录"
    examples:
      - query: "有安有护达标时间的客户"
        output: {field: ayhMemberGradeInfo.ayhqualifiedtime, operator: EXISTS, value: ''}
    negative_examples:
      - query: "2024年安有护达标的客户"
        reason: "指定了具体达标时间，应使用RANGE"

  - id: ayh_qualified_time_not_exists
    retrieval_text: |-
        安有护 达标时间 达标日期 获得时间 获得日期 达标时间为空 获得时间为空 达标时间没值 达标时间没填 没有达标时间 达标时间没记录 达标日期为空 获得时间没记录的 达标时间空着 达标时间还空着 没有获得时间 无达标时间
        无获得时间 获得日期为空 什么时候达标的没记 获得时间没记录的 安有护达标时间为空 安有护获得时间没记录的 安有护达标时间还空着 安有护没有达标时间
    field: ayhMemberGradeInfo.ayhqualifiedtime
    operator: NOT_EXISTS
    value_type: exists
    description: "安有护会员达标时间是否为空"
    notes: "查询安有护达标时间未记录的客户"
    examples:
      - query: "安有护达标时间为空的客户"
        output: {field: ayhMemberGradeInfo.ayhqualifiedtime, operator: NOT_EXISTS, value: ''}
      - query: "安有护获得时间没记录的"
        output: {field: ayhMemberGradeInfo.ayhqualifiedtime, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "安有护还没有达标的客户"
        reason: "可能是查询达标状态(status)而非达标时间"

  - id: zxjy_member_product_match
    retrieval_text: |-
        臻享家医 家医 臻享 服务线 服务线名称 产品线
        服务线为臻享家医 服务线名称是臻享家医 指定臻享家医服务线
        臻享家医客户 臻享家医会员 臻享家医的客户
    field: zxjyMemberGradeInfo.zxjymemberproductname
    operator: MATCH
    value_type: enum
    enum_ref: zxjyMemberGradeInfo.zxjymemberproductname
    description: "臻享家医会员服务线名称，不表示其他服务线"
    notes: "枚举值为‘臻享家医’。仅在用户明确按具体服务线名称取值时使用 MATCH；‘有/拥有/开通/享有家医或平安家医’表达权益是否存在，必须使用 zxjyMemberGradeInfo.zxjymemberproductname EXISTS。"
    examples:
      - query: "服务线为臻享家医的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberproductname, operator: MATCH, value: 臻享家医}
    negative_examples:
      - query: "臻享家医达标的客户"
        reason: "达标是会员状态(status)，不是服务线"
      - query: "有平安家医的客户"
        reason: "‘有’表达家医权益存在，应使用同字段 EXISTS，而不是 MATCH"

  - id: zxjy_member_product_contains
    retrieval_text: |-
        臻享家医 服务线名称包含臻享家医 明确包含多个臻享家医服务线枚举值
    field: zxjyMemberGradeInfo.zxjymemberproductname
    operator: CONTAINS
    value_type: enum
    enum_ref: zxjyMemberGradeInfo.zxjymemberproductname
    description: "臻享家医会员服务线名称，用于多服务线组合查询"
    notes: "仅当原文明确要求本字段的多个枚举候选时使用 CONTAINS；本字段当前只有单一服务线枚举值‘臻享家医’，普通‘有家医/有平安家医’不能使用 CONTAINS，应使用 EXISTS。"
    examples:
      - query: "服务线名称包含臻享家医的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberproductname, operator: CONTAINS, value: ["臻享家医"]}
    negative_examples:
      - query: "只有臻享家医的客户"
        reason: "单一服务线查询应为MATCH"

  - id: zxjy_member_product_not_contains
    retrieval_text: |-
        臻享家医 家医 臻享 服务线 会员服务 权益 没有臻享家医|家医|臻享 不是臻享家医|家医|臻享 不包含臻享家医|臻享家医|家医|臻享 不含臻享家医|臻享家医|家医|臻享
        排除臻享家医|臻享家医|家医|臻享 不要臻享家医|家医|臻享 无臻享家医|臻享家医|家医|臻享 没臻享家医|臻享家医|家医|臻享 非臻享家医|臻享家医|家医|臻享 除了臻享家医|臻享家医|家医|臻享之外
        臻享家医|臻享家医|家医|臻享除外 去掉臻享家医|家医|臻享 但没有臻享家医|臻享家医|家医|臻享
    field: zxjyMemberGradeInfo.zxjymemberproductname
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: zxjyMemberGradeInfo.zxjymemberproductname
    description: "臻享家医会员服务线名称，用于排除查询"
    notes: "排除臻享家医服务线的客户时使用NOT_CONTAINS"
    examples:
      - query: "没有臻享家医服务线的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberproductname, operator: NOT_CONTAINS, value: ["臻享家医"]}
      - query: "没有臻享家医的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberproductname, operator: NOT_CONTAINS, value: ["臻享家医"]}
    negative_examples:
      - query: "有臻享家医的客户"
        reason: "正向匹配应使用MATCH"

  - id: zxjy_member_product_exists
    retrieval_text: |-
        臻享家医 平安家医 家医 臻享 服务线 会员服务 权益 开通臻享家医|平安家医|家医|臻享了吗 是否有臻享家医|平安家医|家医|臻享 有没有臻享家医|平安家医|家医|臻享服务线 获得臻享家医|平安家医|家医|臻享的客户
        拿到臻享家医|臻享家医|家医|臻享的 有臻享家医|臻享家医|家医|臻享会员 臻享家医|臻享家医|家医|臻享服务线不为空 有臻享家医|臻享家医|家医|臻享服务线 有臻享家医|臻享家医|家医|臻享权益
    field: zxjyMemberGradeInfo.zxjymemberproductname
    operator: EXISTS
    value_type: exists
    description: "臻享家医会员服务线是否有值"
    notes: "仅判断臻享家医权益服务线是否有记录，不关心具体值。‘平安家医’是‘臻享家医’的业务别称；有/拥有/开通/享有平安家医或家医时统一输出 EXISTS。末尾无法解释的字母、数字或乱码视为噪声，不改变权益语义。"
    examples:
      - query: "有臻享家医权益的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberproductname, operator: EXISTS, value: ''}
      - query: "开通了臻享家医的客户"
        output: { field: zxjyMemberGradeInfo.zxjymemberproductname, operator: EXISTS, value: '' }
      - query: "有平安家医的客户"
        output: { field: zxjyMemberGradeInfo.zxjymemberproductname, operator: EXISTS, value: '' }
    negative_examples:
      - query: "臻享家医客户"
        reason: "指定了具体服务线值，应使用MATCH"

  - id: zxjy_member_product_not_exists
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 服务线 会员服务 权益 臻享家医|臻享家医|家医|臻享服务线为空 臻享家医|臻享家医|家医|臻享权益为空 臻享家医|臻享家医|家医|臻享服务线没值 臻享家医|臻享家医|家医|臻享没有记录
        没有臻享家医|臻享家医|家医|臻享服务线 没有臻享家医|臻享家医|家医|臻享权益 没有臻享家医|臻享家医|家医|臻享会员 还没开通臻享家医|臻享家医|家医|臻享 没拿到臻享家医|臻享家医|家医|臻享
        无臻享家医|臻享家医|家医|臻享服务线 无臻享家医|臻享家医|家医|臻享权益 臻享家医|臻享家医|家医|臻享为空 所有会员权益都没标的 权益都没标
    field: zxjyMemberGradeInfo.zxjymemberproductname
    operator: NOT_EXISTS
    value_type: exists
    description: "臻享家医会员服务线是否为空"
    notes: "查询没有臻享家医服务线记录的客户"
    examples:
      - query: "没有臻享家医权益的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberproductname, operator: NOT_EXISTS, value: ''}
      - query: "臻享家医权益为空的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberproductname, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不是臻享家医的客户"
        reason: "可能是排除特定值而非判断字段是否存在"

  - id: zxjy_member_grade_match
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员等级 等级 版本 级别 档次 臻享家医V1 臻享家医V2 臻享家医V3 臻享家医V1 臻享家医V1 家医V1 臻享V1 臻享家医V2 臻享家医V2 家医V2 臻享V2 臻享家医V3
        臻享家医V3 家医V3 臻享V3 家医v1 家医v2 家医v3 臻享家医v1 臻享家医v2 最高等级 最高版本 最好等级 最好版本 顶级 最低等级 最低版本 臻享家医|臻享家医|家医|臻享等级
        臻享家医|臻享家医|家医|臻享版本 臻享家医|臻享家医|家医|臻享什么等级 臻享家医|臻享家医|家医|臻享哪个版本 臻享家医|臻享家医|家医|臻享是什么级别 包含 不包含 有等级 无等级 等级为空 等级不为空
        臻享家医|臻享家医|家医|臻享有等级吗
    field: zxjyMemberGradeInfo.zxjymembergradesearch
    operator: MATCH
    value_type: enum
    enum_ref: zxjyMemberGradeInfo.zxjymembergradesearch
    enum_ordered: true
    description: "臻享家医会员等级或版本，不表示臻享家医达标状态"
    notes: "枚举值共3个：臻享家医V1、臻享家医V2、臻享家医V3；排序：臻享家医V1 < 臻享家医V2 < 臻享家医V3；"
    examples:
      - query: "臻享家医臻享家医V1的客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: MATCH, value: 臻享家医V1}
      - query: "臻享家医等级是臻享家医V3的客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: MATCH, value: 臻享家医V3}
      - query: "臻享家医最高等级的客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: MATCH, value: 臻享家医V3}
    negative_examples:
      - query: "臻享家医达标的客户"
        reason: "达标是会员状态(status)，不是等级(grade)"

  - id: zxjy_member_grade_contains
    retrieval_text: >
      臻享家医 臻享家医 家医 臻享 会员等级 等级 版本 级别
      臻享家医V1 臻享家医V2 臻享家医V3 家医V1 家医V2 家医V3
      或者 或 和 及 与 都要 都查 都查一下 都可以 多个等级 多个版本
      以上 及以上 以下 及以下 高于 大于 超过 低于 小于 不足 不到 还没到
      家医V1以上 家医V2及以上 家医V2以下 家医V2及以下 家医V1以上 家医V1+
      臻享家医V2以上的客户 臻享家医V2及以上的 还没到臻享家医V2的 家医V1以上的
    field: zxjyMemberGradeInfo.zxjymembergradesearch
    operator: CONTAINS
    value_type: enum
    enum_ref: zxjyMemberGradeInfo.zxjymembergradesearch
    enum_ordered: true
    description: "臻享家医会员等级多值查询与范围比较；“以上”、”及以上”、”以下”、”及以下”含边界"
    notes: "排序：臻享家医V1<臻享家医V2<臻享家医V3。臻享家医V2以上和及以上=含臻享家医V2即臻享家医V2和臻享家医V3；臻享家医V2以下和及以下=含臻享家医V2即臻享家医V1和臻享家医V2"
    examples:
      - query: "臻享家医V1或者V3的客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: CONTAINS, value: [臻享家医V1, 臻享家医V3]}
      - query: "臻享家医V2以上的客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: CONTAINS, value: [臻享家医V2, 臻享家医V3]}
      - query: "家医V2及以上的客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: CONTAINS, value: [臻享家医V2, 臻享家医V3]}
      - query: "家医V2以下的客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: CONTAINS, value: [臻享家医V1, 臻享家医V2]}
      - query: "家医V2及以下的客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: CONTAINS, value: [臻享家医V1, 臻享家医V2]}
    negative_examples:
      - query: "家医V3的客户"
        reason: "单一等级精确匹配应使用MATCH"

  - id: zxjy_member_grade_not_contains
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员等级 等级 版本 臻享家医V1 臻享家医V2 臻享家医V3 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 臻享家医|臻享家医|家医|臻享不要
        臻享家医|臻享家医|家医|臻享排除 臻享家医|臻享家医|家医|臻享不是 臻享家医|臻享家医|家医|臻享不包含
    field: zxjyMemberGradeInfo.zxjymembergradesearch
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: zxjyMemberGradeInfo.zxjymembergradesearch
    description: "臻享家医会员等级排除查询"
    notes: "排除某个臻享家医等级时使用NOT_CONTAINS"
    examples:
      - query: "不要臻享家医V1的臻享家医客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: NOT_CONTAINS, value: 臻享家医V1}
    negative_examples:
      - query: "臻享家医臻享家医V1的客户"
        reason: "正向匹配应使用MATCH"

  - id: zxjy_member_grade_exists
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员等级 等级 版本 有等级 有版本 有等级吗 有没有等级 是否有等级 等级不为空 等级已定 等级已填 已定级 臻享家医|臻享家医|家医|臻享有等级 臻享家医|臻享家医|家医|臻享有版本
        臻享家医|臻享家医|家医|臻享已定级 臻享家医|臻享家医|家医|臻享等级不为空
    field: zxjyMemberGradeInfo.zxjymembergradesearch
    operator: EXISTS
    value_type: exists
    description: "臻享家医会员等级是否有值"
    notes: "仅判断臻享家医是否有等级记录，不关心具体等级值"
    examples:
      - query: "有臻享家医等级的客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: EXISTS, value: ''}
    negative_examples:
      - query: "臻享家医臻享家医V1的客户"
        reason: "指定了具体等级值，应使用MATCH"

  - id: zxjy_member_grade_not_exists
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员等级 等级 版本 等级为空 等级没值 等级没填 等级没定 还没定级 没有等级 无等级 等级没登记 等级还没定的 没等级 臻享家医|臻享家医|家医|臻享等级为空
        臻享家医|臻享家医|家医|臻享没等级 臻享家医|臻享家医|家医|臻享等级还没定的 臻享家医|臻享家医|家医|臻享等级没登记的
    field: zxjyMemberGradeInfo.zxjymembergradesearch
    operator: NOT_EXISTS
    value_type: exists
    description: "臻享家医会员等级是否为空"
    notes: "查询臻享家医等级未登记或未填写的客户"
    examples:
      - query: "臻享家医等级还没定的客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: NOT_EXISTS, value: ''}
      - query: "没有臻享家医等级的客户"
        output: {field: zxjyMemberGradeInfo.zxjymembergradesearch, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要臻享家医臻享家医V1的客户"
        reason: "排除特定等级值使用NOT_CONTAINS"

  - id: zxjy_member_status_match
    enum_requires_anchor: true
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员类型 会员状态 类型 状态 是什么状态 什么状态 什么类型 哪种状态 预达标 达标 意向 臻享状态 臻享类型
        臻享会员类型 臻享的状态 臻享是什么状态 臻享会员状态
    field: zxjyMemberGradeInfo.zxjymemberstatus
    operator: MATCH
    value_type: enum
    enum_ref: zxjyMemberGradeInfo.zxjymemberstatus
    description: "臻享家医会员类型或状态，不表示臻享家医等级版本"
    notes: "枚举值共3个：预达标、达标、意向；状态互斥，一个客户同一时间只能属于一种状态"
    examples:
      - query: "臻享家医预达标的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberstatus, operator: MATCH, value: 预达标}
      - query: "臻享家医是意向客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberstatus, operator: MATCH, value: 意向}
    negative_examples:
      - query: "臻享家医臻享家医V1的客户"
        reason: "臻享家医V1是等级(grade)，不是状态(status)"

  - id: zxjy_member_status_contains
    enum_requires_anchor: true
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员类型 会员状态 类型 状态 预达标 达标 潜客 意向 临界 临界客户 臻享家医|臻享家医|家医|臻享或者 臻享家医|臻享家医|家医|臻享或
        臻享家医|臻享家医|家医|臻享以及 臻享家医|臻享家医|家医|臻享和
    field: zxjyMemberGradeInfo.zxjymemberstatus
    operator: CONTAINS
    value_type: enum
    enum_ref: zxjyMemberGradeInfo.zxjymemberstatus
    description: "臻享家医会员类型多值查询"
    notes: "查询多种臻享家医状态时使用CONTAINS；临界客户=潜客或意向"
    examples:
      - query: "臻享家医预达标或者意向客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberstatus, operator: CONTAINS, value: [预达标, 意向]}
    negative_examples:
      - query: "臻享家医预达标客户"
        reason: "单一状态查询应为MATCH"

  - id: zxjy_member_status_not_contains
    enum_requires_anchor: true
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员类型 会员状态 类型 状态 预达标 达标 意向 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 臻享不要 臻享排除
        臻享不包含
    field: zxjyMemberGradeInfo.zxjymemberstatus
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: zxjyMemberGradeInfo.zxjymemberstatus
    description: "臻享家医会员类型排除查询"
    notes: "排除某种臻享家医状态时使用NOT_CONTAINS"
    examples:
      - query: "臻享家医不要预达标客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberstatus, operator: NOT_CONTAINS, value: 预达标}
    negative_examples:
      - query: "臻享家医预达标客户"
        reason: "正向匹配应使用MATCH"

  - id: zxjy_member_status_exists
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员类型 会员状态 类型 状态 有状态 有类型 有会员状态 有会员类型 状态不为空 类型不为空 状态已标 状态已登记 已有状态 臻享家医|臻享家医|家医|臻享有状态
        臻享家医|臻享家医|家医|臻享状态不为空 臻享家医|臻享家医|家医|臻享状态已填
    field: zxjyMemberGradeInfo.zxjymemberstatus
    operator: EXISTS
    value_type: exists
    description: "臻享家医会员类型是否有值"
    notes: "仅判断臻享家医是否有状态记录，不关心具体状态值"
    examples:
      - query: "有臻享家医状态的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberstatus, operator: EXISTS, value: ''}
    negative_examples:
      - query: "臻享家医预达标客户"
        reason: "指定了具体状态值，应使用MATCH"

  - id: zxjy_member_status_not_exists
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员类型 会员状态 类型 状态 状态为空 类型为空 没有状态 无状态 状态没标 状态没填 会员状态没标的 状态还没登记 状态没值 臻享家医|臻享家医|家医|臻享状态为空
        臻享家医|臻享家医|家医|臻享状态没标的 臻享家医|臻享家医|家医|臻享没状态 臻享家医|臻享家医|家医|臻享状态还没登记的
    field: zxjyMemberGradeInfo.zxjymemberstatus
    operator: NOT_EXISTS
    value_type: exists
    description: "臻享家医会员类型是否为空"
    notes: "查询臻享家医状态未登记的客户"
    examples:
      - query: "臻享家医会员状态没标的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberstatus, operator: NOT_EXISTS, value: ''}
      - query: "没有臻享家医状态的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberstatus, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要臻享家医预达标客户"
        reason: "排除特定状态值使用NOT_CONTAINS"

  - id: zxjy_member_period_match
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员期次 期次 会员年度 年度 哪一期 什么期次 哪个年度 M2023 M2024 M2025 M年份 包含2023年期 包含2024年期的 包含2025年期的 2023年那期 2024年那期
        23年那期 24年那期 臻享家医|臻享家医|家医|臻享2023年 臻享家医|臻享家医|家医|臻享2024年 臻享家医|臻享家医|家医|臻享2025年 臻享家医|臻享家医|家医|臻享期次 臻享家医|臻享家医|家医|臻享年度
        臻享家医|臻享家医|家医|臻享哪一期 臻享家医|臻享家医|家医|臻享哪个年度 是哪一期 哪年那期 2024年那一期 2025年那一期 有期次 无期次 期次为空 期次不为空
    field: zxjyMemberGradeInfo.zxjymemberperiod
    operator: MATCH
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "臻享家医会员期次（年度），不表示臻享家医达标时间"
    notes: "期次为年份格式YYYY，如2023、2024、2025；一个客户可能拥有多个年度的期次记录"
    examples:
      - query: "臻享家医2024年期的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberperiod, operator: MATCH, value: '2024'}
      - query: "23年那期臻享家医"
        output: {field: zxjyMemberGradeInfo.zxjymemberperiod, operator: MATCH, value: '2023'}
    negative_examples:
      - query: "2024年达标的臻享家医客户"
        reason: "2024年是达标时间(qualifiedtime)，不是期次(period)"

  - id: zxjy_member_period_contains
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员期次 期次 年度 包含 含有 包括 有 都有 和 及 与 以及 包含2023年期 包含2024年期的 包含2025年期的 臻享家医|臻享家医|家医|臻享2023到2025
        臻享家医|臻享家医|家医|臻享2023至2025 2023和2024年期 多个期次 几个年度
    field: zxjyMemberGradeInfo.zxjymemberperiod
    operator: CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "臻享家医会员期次多值查询"
    notes: "查询包含多个期次时使用CONTAINS"
    examples:
      - query: "臻享家医包含2023年期和2024年期的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberperiod, operator: CONTAINS, value: ['2023',
    '2024']}
    negative_examples:
      - query: "臻享家医2024年期的客户"
        reason: "单一年份应使用MATCH"

  - id: zxjy_member_period_not_contains
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员期次 期次 年度 不包含 不含 不要 排除 去除 没有 不包含2023年期 不包含2024年期 不包含2025年期 臻享家医|臻享家医|家医|臻享不包含 臻享家医|臻享家医|家医|臻享不含
        臻享家医|臻享家医|家医|臻享不要
    field: zxjyMemberGradeInfo.zxjymemberperiod
    operator: NOT_CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "臻享家医会员期次排除查询"
    notes: "排除某些期次时使用NOT_CONTAINS"
    examples:
      - query: "臻享家医不包含2023年期的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberperiod, operator: NOT_CONTAINS, value: '2023'}
    negative_examples:
      - query: "臻享家医包含2023年期的客户"
        reason: "正向匹配应使用MATCH或CONTAINS"

  - id: zxjy_member_period_exists
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员期次 期次 年度 有期次 有年度 有期次吗 有没有期次 是否有期次 期次不为空 期次已登记 期次已填 已登记期次 臻享家医|臻享家医|家医|臻享有期次
        臻享家医|臻享家医|家医|臻享期次不为空 臻享家医|臻享家医|家医|臻享期次已填
    field: zxjyMemberGradeInfo.zxjymemberperiod
    operator: EXISTS
    value_type: exists
    description: "臻享家医会员期次是否有值"
    notes: "仅判断臻享家医是否有期次记录，不关心具体年份"
    examples:
      - query: "有臻享家医期次的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberperiod, operator: EXISTS, value: ''}
    negative_examples:
      - query: "臻享家医2024年期的客户"
        reason: "指定了具体年份值，应使用MATCH"

  - id: zxjy_member_period_not_exists
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 会员期次 期次 年度 期次为空 期次没值 期次没填 没有期次 无期次 期次没登记 期次还没登记 没填期次 哪一期没登记 哪一期还没登记 权益期次没有的 期次没填的
        臻享家医|臻享家医|家医|臻享期次为空 臻享家医|臻享家医|家医|臻享期次没填的 臻享家医|臻享家医|家医|臻享没有期次 臻享家医|臻享家医|家医|臻享哪一期没登记 臻享家医|臻享家医|家医|臻享期次没登记
    field: zxjyMemberGradeInfo.zxjymemberperiod
    operator: NOT_EXISTS
    value_type: exists
    description: "臻享家医会员期次是否为空"
    notes: "查询臻享家医期次未登记的客户"
    examples:
      - query: "臻享家医期次没填的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberperiod, operator: NOT_EXISTS, value: ''}
      - query: "臻享家医是哪一期还没登记的客户"
        output: {field: zxjyMemberGradeInfo.zxjymemberperiod, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "臻享家医不包含2023年期的客户"
        reason: "排除特定期次值使用NOT_CONTAINS"

  - id: zxjy_qualified_time_range
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 达标时间 达标日期 获得时间 获得日期 拿到时间 什么时候达标 何时达标 哪年达标 什么时候获得 臻享家医|臻享家医|家医|臻享达标 臻享家医|臻享家医|家医|臻享获得
        臻享拿到 臻享达标时间 臻享获得时间 臻享什么时候达标 时间范围 从到 之间 去年 今年 2023年 2024年 臻享家医达标时间
        2025年 近一周 近一个月 近一年 近期 最近 最近一个月 本季度 去年 前年 去年二季度 去年下半年 上半年 下半年 大于 小于 之后 之前 以来 至今 一个月内 一年内 一周内 半年内 三个月内 去年6月以后
    field: zxjyMemberGradeInfo.zxjyqualifiedtime
    operator: RANGE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "臻享家医会员达标时间（达标日期），不表示臻享家医期次"
    notes: "达标时间指客户满足会员资格条件的日期，格式yyyy-MM-dd"
    examples:
      - query: "去年是臻享家医的客户"
        output: {field: zxjyMemberGradeInfo.zxjyqualifiedtime, operator: RANGE, value: {max: '2025-12-31',
    min: '2025-01-01'}}
      - query: "臻享家医近一年达标的客户"
        output: {field: zxjyMemberGradeInfo.zxjyqualifiedtime, operator: RANGE, value: {max: '2026-06-11',
    min: '2025-06-11'}}
      - query: "臻享家医去年二季度达标的客户"
        output: {field: zxjyMemberGradeInfo.zxjyqualifiedtime, operator: RANGE, value: {max: '2025-06-30',
    min: '2025-04-01'}}
    negative_examples:
      - query: "臻享家医2024年期的客户"
        reason: "2024年期是期次(period)，不是达标时间"

  - id: zxjy_qualified_time_gt
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 达标时间 获得时间 达标日期 大于 之后 以后 之后达标 以后获得 臻享家医|臻享家医|家医|臻享之后达标 臻享家医|臻享家医|家医|臻享以后获得 2023年以后 2024年以后
        2025年以后 去年以后 去年6月以后
    field: zxjyMemberGradeInfo.zxjyqualifiedtime
    operator: GT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "臻享家医会员达标时间大于某日期"
    notes: "查询在某日期之后达标的客户"
    examples:
      - query: "2023年以后拿到臻享家医权益的"
        output: {field: zxjyMemberGradeInfo.zxjyqualifiedtime, operator: GT, value: '2023-12-31'}
    negative_examples:
      - query: "2024年臻享家医达标的客户"
        reason: "指定年份范围应使用RANGE"

  - id: zxjy_qualified_time_gte
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 达标时间 获得时间 达标日期 大于等于 不小于 及之后 及以上 及以后 至少 臻享家医|臻享家医|家医|臻享及之后达标 臻享家医|臻享家医|家医|臻享及以上
        臻享家医|臻享家医|家医|臻享大于等于 2023年及之后 2024年及以后
    field: zxjyMemberGradeInfo.zxjyqualifiedtime
    operator: GTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "臻享家医会员达标时间大于等于某日期"
    notes: "查询在某日期及之后达标的客户"
    examples:
      - query: "2024年及之后臻享家医达标的客户"
        output: {field: zxjyMemberGradeInfo.zxjyqualifiedtime, operator: GTE, value: '2024-01-01'}
    negative_examples:
      - query: "2024年臻享家医达标的客户"
        reason: "精确年份范围应使用RANGE"

  - id: zxjy_qualified_time_lt
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 达标时间 获得时间 达标日期 小于 之前 以前 之前达标 以前获得 臻享家医|臻享家医|家医|臻享之前达标 臻享家医|臻享家医|家医|臻享以前获得 2025年以前 25年以前 2024年之前
        2023年之前
    field: zxjyMemberGradeInfo.zxjyqualifiedtime
    operator: LT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "臻享家医会员达标时间小于某日期"
    notes: "查询在某日期之前达标的客户"
    examples:
      - query: "25年以前获得臻享家医的"
        output: {field: zxjyMemberGradeInfo.zxjyqualifiedtime, operator: LT, value: '2025-01-01'}
    negative_examples:
      - query: "2024年之前臻享家医期次"
        reason: "期次使用memberperiod字段，不是qualifiedtime"

  - id: zxjy_qualified_time_lte
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 达标时间 获得时间 达标日期 小于等于 不大于 及之前 及以前 至多 最晚 臻享家医|臻享家医|家医|臻享及之前达标 臻享家医|臻享家医|家医|臻享不大于
        臻享家医|臻享家医|家医|臻享小于等于 去年年底前 2024年底前 2023年底前
    field: zxjyMemberGradeInfo.zxjyqualifiedtime
    operator: LTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "臻享家医会员达标时间小于等于某日期"
    notes: "查询在某日期及之前达标的客户"
    examples:
      - query: "去年年底前获得臻享家医的客户"
        output: {field: zxjyMemberGradeInfo.zxjyqualifiedtime, operator: LTE, value: '2025-12-31'}
    negative_examples:
      - query: "臻享家医去年达标的客户"
        reason: "整年范围应使用RANGE"

  - id: zxjy_qualified_time_exists
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 达标时间 获得时间 达标日期 拿到时间 有达标时间 有获得时间 有时间 达标时间不为空 获得时间不为空 已达标 已拿到 已获得 已登记达标时间 臻享家医|臻享家医|家医|臻享有达标时间
        臻享家医|臻享家医|家医|臻享获得时间不为空 臻享家医|臻享家医|家医|臻享已达标
    field: zxjyMemberGradeInfo.zxjyqualifiedtime
    operator: EXISTS
    value_type: exists
    description: "臻享家医会员达标时间是否有值"
    notes: "仅判断臻享家医是否有达标时间记录"
    examples:
      - query: "有臻享家医达标时间的客户"
        output: {field: zxjyMemberGradeInfo.zxjyqualifiedtime, operator: EXISTS, value: ''}
    negative_examples:
      - query: "2024年臻享家医达标的客户"
        reason: "指定了具体达标时间，应使用RANGE"

  - id: zxjy_qualified_time_not_exists
    retrieval_text: |-
        臻享家医 臻享家医 家医 臻享 达标时间 达标日期 获得时间 获得日期 达标时间为空 获得时间为空 达标时间没值 达标时间没填 没有达标时间 达标时间没记录 达标日期为空 获得时间没记录的 达标时间空着 达标时间还空着
        没有获得时间 无达标时间 无获得时间 获得日期为空 什么时候达标的没记 获得时间没记录的 臻享家医|臻享家医|家医|臻享达标时间为空 臻享家医|臻享家医|家医|臻享获得时间没记录的
        臻享家医|臻享家医|家医|臻享达标时间还空着 臻享家医|臻享家医|家医|臻享没有达标时间
    field: zxjyMemberGradeInfo.zxjyqualifiedtime
    operator: NOT_EXISTS
    value_type: exists
    description: "臻享家医会员达标时间是否为空"
    notes: "查询臻享家医达标时间未记录的客户"
    examples:
      - query: "臻享家医达标时间为空的客户"
        output: {field: zxjyMemberGradeInfo.zxjyqualifiedtime, operator: NOT_EXISTS, value: ''}
      - query: "臻享家医获得时间没记录的"
        output: {field: zxjyMemberGradeInfo.zxjyqualifiedtime, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "臻享家医还没有达标的客户"
        reason: "可能是查询达标状态(status)而非达标时间"

  - id: pajj_member_product_match
    retrieval_text: |-
        平安居家 居家养老 居家 服务线 服务线名称 产品线 会员服务 权益 开通了平安居家|居家养老|居家 购买了平安居家|居家养老|居家 买了平安居家|居家养老|居家 享有平安居家|居家养老|居家 已有平安居家|居家养老|居家
        有平安居家|居家养老|居家权益的 平安居家|居家养老|居家客户 平安居家|居家养老|居家会员 平安居家|居家养老|居家的客户 开通平安居家|居家养老|居家服务的 有平安居家|居家养老|居家权益 包含平安居家|居家养老|居家
        有平安居家|居家养老|居家服务线 有平安居家|居家养老|居家的 获得平安居家|居家养老|居家的客户 拿到平安居家|居家养老|居家的 有平安居家|居家养老|居家吗 是不是平安居家|居家养老|居家 怎么查平安居家|居家养老|居家
        有平安居家|居家养老|居家权益的客户
    field: pajjMemberGradeInfo.pajjmemberproductname
    operator: MATCH
    value_type: enum
    enum_ref: pajjMemberGradeInfo.pajjmemberproductname
    description: "平安居家会员服务线名称，不表示其他服务线"
    notes: "枚举值「平安居家」；有该服务线即表示客户开通了平安居家会员服务"
    examples:
      - query: "服务线名为平安居家的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberproductname, operator: MATCH, value: 平安居家}
    negative_examples:
      - query: "平安居家达标的客户"
        reason: "达标是会员状态(status)，不是服务线"

  - id: pajj_member_product_contains
    retrieval_text: |-
        平安居家 居家养老 居家 服务线 会员服务 权益 也开通了 同时有 还有 既有 也有 和 或 或者 包含平安居家|居家养老|居家 有平安居家|居家养老|居家和 平安居家|居家养老|居家都有 平安居家|居家养老|居家以及
        多种权益 多个服务线
    field: pajjMemberGradeInfo.pajjmemberproductname
    operator: CONTAINS
    value_type: enum
    enum_ref: pajjMemberGradeInfo.pajjmemberproductname
    description: "平安居家会员服务线名称，用于多服务线组合查询"
    notes: "查询同时拥有多个服务线的客户时使用CONTAINS"
    examples:
      - query: "有平安居家也有安有护的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberproductname, operator: CONTAINS, value: [平安居家,
    安有护]}
    negative_examples:
      - query: "只有平安居家的客户"
        reason: "单一服务线查询应为MATCH"

  - id: pajj_member_product_not_contains
    retrieval_text: |-
        平安居家 居家养老 居家 服务线 会员服务 权益 没有平安居家|居家养老|居家 不是平安居家|居家养老|居家 不包含平安居家|居家养老|居家 不含平安居家|居家养老|居家 排除平安居家|居家养老|居家
        不要平安居家|居家养老|居家 无平安居家|居家养老|居家 没平安居家|居家养老|居家 非平安居家|居家养老|居家 除了平安居家|居家养老|居家之外 平安居家|居家养老|居家除外 去掉平安居家|居家养老|居家
        但没有平安居家|居家养老|居家
    field: pajjMemberGradeInfo.pajjmemberproductname
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: pajjMemberGradeInfo.pajjmemberproductname
    description: "平安居家会员服务线名称，用于排除查询"
    notes: "排除平安居家服务线的客户时使用NOT_CONTAINS"
    examples:
      - query: "没有平安居家服务线的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberproductname, operator: NOT_CONTAINS, value: 平安居家}
      - query: "有安有护但没有平安居家的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberproductname, operator: NOT_CONTAINS, value: 平安居家}
    negative_examples:
      - query: "有平安居家的客户"
        reason: "正向匹配应使用MATCH"

  - id: pajj_member_product_exists
    retrieval_text: |-
        平安居家 居家养老 居家 服务线 会员服务 权益 开通平安居家|居家养老|居家了吗 是否有平安居家|居家养老|居家 有没有平安居家|居家养老|居家服务线 获得平安居家|居家养老|居家的客户 拿到平安居家|居家养老|居家的
        有平安居家|居家养老|居家会员 平安居家|居家养老|居家服务线不为空 有平安居家|居家养老|居家服务线 有平安居家|居家养老|居家权益
    field: pajjMemberGradeInfo.pajjmemberproductname
    operator: EXISTS
    value_type: exists
    description: "平安居家会员服务线是否有值"
    notes: "仅判断平安居家服务线是否有记录，不关心具体值；权益潜客在解析阶段使用memberstatus，最终由系统后处理生成本条件。"
    examples:
      - query: "开通了平安居家的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberproductname, operator: EXISTS, value: ''}
      - query: "有平安居家权益的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberproductname, operator: EXISTS, value: ''}
    negative_examples:
      - query: "平安居家客户"
        reason: "指定了具体服务线值，应使用MATCH"

  - id: pajj_member_product_not_exists
    retrieval_text: |-
        平安居家 居家养老 居家 服务线 会员服务 权益 平安居家|居家养老|居家服务线为空 平安居家|居家养老|居家权益为空 平安居家|居家养老|居家服务线没值 平安居家|居家养老|居家没有记录 没有平安居家|居家养老|居家服务线
        没有平安居家|居家养老|居家权益 没有平安居家|居家养老|居家会员 还没开通平安居家|居家养老|居家 没拿到平安居家|居家养老|居家 无平安居家|居家养老|居家服务线 无平安居家|居家养老|居家权益
        平安居家|居家养老|居家为空 所有会员权益都没标的 权益都没标
    field: pajjMemberGradeInfo.pajjmemberproductname
    operator: NOT_EXISTS
    value_type: exists
    description: "平安居家会员服务线是否为空"
    notes: "查询没有平安居家服务线记录的客户"
    examples:
      - query: "没有平安居家权益的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberproductname, operator: NOT_EXISTS, value: ''}
      - query: "平安居家权益为空的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberproductname, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不是平安居家的客户"
        reason: "可能是排除特定值而非判断字段是否存在"

  - id: pajj_member_grade_match
    retrieval_text: |-
        平安居家 居家养老 居家 会员等级 等级 版本 级别 档次 平安居家V0 平安居家V1 平安居家V1优享 平安居家V2 平安居家V2优享 居家V0 居家V1 居家V1优享 居家V2 居家V2优享 平安居家V0 平安居家V1
        平安居家V1优享 平安居家V2 平安居家V2优享 居家养老V1 最高等级 最高版本 最好等级 最好版本 顶级 最低等级 最低版本 平安居家|居家养老|居家等级 平安居家|居家养老|居家版本 平安居家|居家养老|居家什么等级
        平安居家|居家养老|居家哪个版本 平安居家|居家养老|居家是什么级别 包含 不包含 有等级 无等级 等级为空 等级不为空 平安居家|居家养老|居家有等级吗
    field: pajjMemberGradeInfo.pajjmembergradesearch
    operator: MATCH
    value_type: enum
    enum_ref: pajjMemberGradeInfo.pajjmembergradesearch
    enum_ordered: true
    description: "平安居家会员等级或版本，不表示平安居家达标状态"
    notes: "枚举值共5个：平安居家V0、平安居家V1、平安居家V1优享、平安居家V2、平安居家V2优享；排序：平安居家V0 < 平安居家V1 < 平安居家V1优享 < 平安居家V2 < 平安居家V2优享；以上/及以上/以下/及以下包含边界"
    examples:
      - query: "平安居家平安居家V0的客户"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: MATCH, value: 平安居家V0}
      - query: "平安居家等级是平安居家V2优享的客户"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: MATCH, value: 平安居家V2优享}
      - query: "平安居家最高等级的客户"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: MATCH, value: 平安居家V2优享}
    negative_examples:
      - query: "平安居家达标的客户"
        reason: "达标是会员状态(status)，不是等级(grade)"

  - id: pajj_member_grade_contains
    retrieval_text: >
      平安居家 居家养老 居家 会员等级 等级 版本 级别
      平安居家V0 平安居家V1 平安居家V1优享 平安居家V2 平安居家V2优享 居家V0 居家V1 居家V1优享 居家V2 居家V2优享
      或者 或 和 及 与 都要 都查 都查一下 都可以 多个等级 多个版本
      以上 及以上 以下 及以下 高于 大于 超过 低于 小于 不足 不到
      居家V1以上 居家V2及以上 居家V2以下 居家V1及以下 居家V1+ 居家V1优享以上
      平安居家V2优享客户 居家V0和V2都要 居家V2以下的客户 居家V1优享以上
    field: pajjMemberGradeInfo.pajjmembergradesearch
    operator: CONTAINS
    value_type: enum
    enum_ref: pajjMemberGradeInfo.pajjmembergradesearch
    enum_ordered: true
    description: "平安居家会员等级多值查询与范围比较；“以上”、”及以上”、”以下”、”及以下”含边界"
    notes: "排序：平安居家V0<平安居家V1<平安居家V1优享<平安居家V2<平安居家V2优享。平安居家V1以上和及以上=含平安居家V1即平安居家V1/平安居家V1优享/平安居家V2/平安居家V2优享；平安居家V2以下和及以下=含平安居家V2即平安居家V0/平安居家V1/平安居家V1优享/平安居家V2"
    examples:
      - query: "居家V0和V2都要"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: CONTAINS, value: [平安居家V0, 平安居家V2]}
      - query: "居家V1以上的客户"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: CONTAINS, value: [平安居家V1, 平安居家V1优享, 平安居家V2, 平安居家V2优享]}
      - query: "居家V1及以上的客户"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: CONTAINS, value: [平安居家V1, 平安居家V1优享, 平安居家V2, 平安居家V2优享]}
      - query: "居家V2以下的客户"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: CONTAINS, value: [平安居家V0, 平安居家V1, 平安居家V1优享, 平安居家V2]}
      - query: "居家V2及以下的客户"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: CONTAINS, value: [平安居家V0, 平安居家V1, 平安居家V1优享, 平安居家V2]}
    negative_examples:
      - query: "居家V1的客户"
        reason: "单一等级精确匹配应使用MATCH"

  - id: pajj_member_grade_not_contains
    retrieval_text: |-
        平安居家 居家养老 居家 会员等级 等级 版本 平安居家V0 平安居家V1 平安居家V1优享 平安居家V2 平安居家V2优享 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 平安居家|居家养老|居家不要
        平安居家|居家养老|居家排除 平安居家|居家养老|居家不是 平安居家|居家养老|居家不包含
    field: pajjMemberGradeInfo.pajjmembergradesearch
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: pajjMemberGradeInfo.pajjmembergradesearch
    description: "平安居家会员等级排除查询"
    notes: "排除某个平安居家等级时使用NOT_CONTAINS"
    examples:
      - query: "不要平安居家V0的平安居家客户"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: NOT_CONTAINS, value: 平安居家V0}
    negative_examples:
      - query: "平安居家平安居家V0的客户"
        reason: "正向匹配应使用MATCH"

  - id: pajj_member_grade_exists
    retrieval_text: |-
        平安居家 居家养老 居家 会员等级 等级 版本 有等级 有版本 有等级吗 有没有等级 是否有等级 等级不为空 等级已定 等级已填 已定级 平安居家|居家养老|居家有等级 平安居家|居家养老|居家有版本
        平安居家|居家养老|居家已定级 平安居家|居家养老|居家等级不为空
    field: pajjMemberGradeInfo.pajjmembergradesearch
    operator: EXISTS
    value_type: exists
    description: "平安居家会员等级是否有值"
    notes: "仅判断平安居家是否有等级记录，不关心具体等级值"
    examples:
      - query: "有平安居家等级的客户"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: EXISTS, value: ''}
    negative_examples:
      - query: "平安居家平安居家V0的客户"
        reason: "指定了具体等级值，应使用MATCH"

  - id: pajj_member_grade_not_exists
    retrieval_text: |-
        平安居家 居家养老 居家 会员等级 等级 版本 等级为空 等级没值 等级没填 等级没定 还没定级 没有等级 无等级 等级没登记 等级还没定的 没等级 平安居家|居家养老|居家等级为空 平安居家|居家养老|居家没等级
        平安居家|居家养老|居家等级还没定的 平安居家|居家养老|居家等级没登记的
    field: pajjMemberGradeInfo.pajjmembergradesearch
    operator: NOT_EXISTS
    value_type: exists
    description: "平安居家会员等级是否为空"
    notes: "查询平安居家等级未登记或未填写的客户"
    examples:
      - query: "平安居家等级还没定的客户"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: NOT_EXISTS, value: ''}
      - query: "没有平安居家等级的客户"
        output: {field: pajjMemberGradeInfo.pajjmembergradesearch, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要平安居家平安居家V0的客户"
        reason: "排除特定等级值使用NOT_CONTAINS"

  - id: pajj_member_status_match
    enum_requires_anchor: true
    retrieval_text: |-
        平安居家 居家养老 居家 会员类型 会员状态 类型 状态 是什么状态 什么状态 什么类型 哪种状态 潜客 意向 达标 预达标 维持 居家状态 居家类型 居家会员类型
        居家的状态 居家是什么状态 居家会员状态
    field: pajjMemberGradeInfo.pajjmemberstatus
    operator: MATCH
    value_type: enum
    enum_ref: pajjMemberGradeInfo.pajjmemberstatus
    description: "平安居家会员类型或状态，不表示平安居家等级版本"
    notes: "枚举值共5个：潜客、意向、达标、预达标、维持；状态互斥，一个客户同一时间只能属于一种状态"
    examples:
      - query: "平安居家潜客的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberstatus, operator: MATCH, value: 潜客}
      - query: "老客户这个月可以增加保费升级到居养的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberstatus, operator: MATCH, value: 潜客}
      - query: "平安居家是维持客户"
        output: {field: pajjMemberGradeInfo.pajjmemberstatus, operator: MATCH, value: 维持}
    negative_examples:
      - query: "平安居家平安居家V0的客户"
        reason: "平安居家V0是等级(grade)，不是状态(status)"

  - id: pajj_member_status_contains
    enum_requires_anchor: true
    retrieval_text: |-
        平安居家 居家养老 居家 会员类型 会员状态 类型 状态 潜客 意向 达标 预达标 维持 临界 临界客户 包含 含有 或者 或 和 都要 都查 平安居家|居家养老|居家或者 平安居家|居家养老|居家或 平安居家|居家养老|居家以及
        平安居家|居家养老|居家和
    field: pajjMemberGradeInfo.pajjmemberstatus
    operator: CONTAINS
    value_type: enum
    enum_ref: pajjMemberGradeInfo.pajjmemberstatus
    description: "平安居家会员类型多值查询"
    notes: "查询多种平安居家状态时使用CONTAINS；临界客户=潜客或意向"
    examples:
      - query: "平安居家潜客或者维持客户"
        output: {field: pajjMemberGradeInfo.pajjmemberstatus, operator: CONTAINS, value: [潜客, 维持]}
      - query: "居家临界客户"
        output: {field: pajjMemberGradeInfo.pajjmemberstatus, operator: CONTAINS, value: [潜客, 意向]}
    negative_examples:
      - query: "平安居家潜客客户"
        reason: "单一状态查询应为MATCH"

  - id: pajj_member_status_not_contains
    enum_requires_anchor: true
    retrieval_text: |-
        平安居家 居家养老 居家 会员类型 会员状态 类型 状态 潜客 意向 达标 预达标 维持 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 平安居家|居家养老|居家不要 平安居家|居家养老|居家排除
        平安居家|居家养老|居家不包含
    field: pajjMemberGradeInfo.pajjmemberstatus
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: pajjMemberGradeInfo.pajjmemberstatus
    description: "平安居家会员类型排除查询"
    notes: "排除某种平安居家状态时使用NOT_CONTAINS"
    examples:
      - query: "平安居家不要潜客客户"
        output: {field: pajjMemberGradeInfo.pajjmemberstatus, operator: NOT_CONTAINS, value: 潜客}
    negative_examples:
      - query: "平安居家潜客客户"
        reason: "正向匹配应使用MATCH"

  - id: pajj_member_status_exists
    retrieval_text: |-
        平安居家 居家养老 居家 会员类型 会员状态 类型 状态 有状态 有类型 有会员状态 有会员类型 状态不为空 类型不为空 状态已标 状态已登记 已有状态 平安居家|居家养老|居家有状态 平安居家|居家养老|居家状态不为空
        平安居家|居家养老|居家状态已填
    field: pajjMemberGradeInfo.pajjmemberstatus
    operator: EXISTS
    value_type: exists
    description: "平安居家会员类型是否有值"
    notes: "仅判断平安居家是否有状态记录，不关心具体状态值"
    examples:
      - query: "有平安居家状态的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberstatus, operator: EXISTS, value: ''}
    negative_examples:
      - query: "平安居家潜客客户"
        reason: "指定了具体状态值，应使用MATCH"

  - id: pajj_member_status_not_exists
    retrieval_text: |-
        平安居家 居家养老 居家 会员类型 会员状态 类型 状态 状态为空 类型为空 没有状态 无状态 状态没标 状态没填 会员状态没标的 状态还没登记 状态没值 平安居家|居家养老|居家状态为空 平安居家|居家养老|居家状态没标的
        平安居家|居家养老|居家没状态 平安居家|居家养老|居家状态还没登记的
    field: pajjMemberGradeInfo.pajjmemberstatus
    operator: NOT_EXISTS
    value_type: exists
    description: "平安居家会员类型是否为空"
    notes: "查询平安居家状态未登记的客户"
    examples:
      - query: "平安居家会员状态没标的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberstatus, operator: NOT_EXISTS, value: ''}
      - query: "没有平安居家状态的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberstatus, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要平安居家潜客客户"
        reason: "排除特定状态值使用NOT_CONTAINS"

  - id: pajj_member_period_match
    retrieval_text: |-
        平安居家 居家养老 居家 会员期次 期次 会员年度 年度 哪一期 什么期次 哪个年度 M2023 M2024 M2025 M年份 包含2023年期 包含2024年期的 包含2025年期的 2023年那期 2024年那期
        23年那期 24年那期 平安居家|居家养老|居家2023年 平安居家|居家养老|居家2024年 平安居家|居家养老|居家2025年 平安居家|居家养老|居家期次 平安居家|居家养老|居家年度 平安居家|居家养老|居家哪一期
        平安居家|居家养老|居家哪个年度 是哪一期 哪年那期 2024年那一期 2025年那一期 有期次 无期次 期次为空 期次不为空
    field: pajjMemberGradeInfo.pajjmemberperiod
    operator: MATCH
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "平安居家会员期次（年度），不表示平安居家达标时间"
    notes: "期次为年份格式YYYY，如2023、2024、2025；一个客户可能拥有多个年度的期次记录"
    examples:
      - query: "平安居家2024年期的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberperiod, operator: MATCH, value: '2024'}
      - query: "23年那期平安居家"
        output: {field: pajjMemberGradeInfo.pajjmemberperiod, operator: MATCH, value: '2023'}
    negative_examples:
      - query: "2024年达标的平安居家客户"
        reason: "2024年是达标时间(qualifiedtime)，不是期次(period)"

  - id: pajj_member_period_contains
    retrieval_text: |-
        平安居家 居家养老 居家 会员期次 期次 年度 包含 含有 包括 有 都有 和 及 与 以及 包含2023年期 包含2024年期的 包含2025年期的 平安居家|居家养老|居家2023到2025
        平安居家|居家养老|居家2023至2025 2023和2024年期 多个期次 几个年度
    field: pajjMemberGradeInfo.pajjmemberperiod
    operator: CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "平安居家会员期次多值查询"
    notes: "查询包含多个期次时使用CONTAINS"
    examples:
      - query: "平安居家包含2023年期和2024年期的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberperiod, operator: CONTAINS, value: ['2023',
    '2024']}
    negative_examples:
      - query: "平安居家2024年期的客户"
        reason: "单一年份应使用MATCH"

  - id: pajj_member_period_not_contains
    retrieval_text: |-
        平安居家 居家养老 居家 会员期次 期次 年度 不包含 不含 不要 排除 去除 没有 不包含2023年期 不包含2024年期 不包含2025年期 平安居家|居家养老|居家不包含 平安居家|居家养老|居家不含
        平安居家|居家养老|居家不要
    field: pajjMemberGradeInfo.pajjmemberperiod
    operator: NOT_CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "平安居家会员期次排除查询"
    notes: "排除某些期次时使用NOT_CONTAINS"
    examples:
      - query: "平安居家不包含2023年期的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberperiod, operator: NOT_CONTAINS, value: '2023'}
    negative_examples:
      - query: "平安居家包含2023年期的客户"
        reason: "正向匹配应使用MATCH或CONTAINS"

  - id: pajj_member_period_exists
    retrieval_text: |-
        平安居家 居家养老 居家 会员期次 期次 年度 有期次 有年度 有期次吗 有没有期次 是否有期次 期次不为空 期次已登记 期次已填 已登记期次 平安居家|居家养老|居家有期次 平安居家|居家养老|居家期次不为空
        平安居家|居家养老|居家期次已填
    field: pajjMemberGradeInfo.pajjmemberperiod
    operator: EXISTS
    value_type: exists
    description: "平安居家会员期次是否有值"
    notes: "仅判断平安居家是否有期次记录，不关心具体年份"
    examples:
      - query: "有平安居家期次的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberperiod, operator: EXISTS, value: ''}
    negative_examples:
      - query: "平安居家2024年期的客户"
        reason: "指定了具体年份值，应使用MATCH"

  - id: pajj_member_period_not_exists
    retrieval_text: |-
        平安居家 居家养老 居家 会员期次 期次 年度 期次为空 期次没值 期次没填 没有期次 无期次 期次没登记 期次还没登记 没填期次 哪一期没登记 哪一期还没登记 权益期次没有的 期次没填的 平安居家|居家养老|居家期次为空
        平安居家|居家养老|居家期次没填的 平安居家|居家养老|居家没有期次 平安居家|居家养老|居家哪一期没登记 平安居家|居家养老|居家期次没登记
    field: pajjMemberGradeInfo.pajjmemberperiod
    operator: NOT_EXISTS
    value_type: exists
    description: "平安居家会员期次是否为空"
    notes: "查询平安居家期次未登记的客户"
    examples:
      - query: "平安居家期次没填的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberperiod, operator: NOT_EXISTS, value: ''}
      - query: "平安居家是哪一期还没登记的客户"
        output: {field: pajjMemberGradeInfo.pajjmemberperiod, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "平安居家不包含2023年期的客户"
        reason: "排除特定期次值使用NOT_CONTAINS"

  - id: pajj_qualified_time_range
    retrieval_text: |-
        平安居家 居家养老 居家 达标时间 达标日期 获得时间 获得日期 拿到时间 新获得 新拿到 新增权益 新增会员 刚获得 什么时候达标 何时达标 哪年达标 什么时候获得 居家达标 居家获得 居家拿到
        居家达标时间 居家获得时间 居家什么时候达标 时间范围 从到 之间 去年 今年 2023年 2024年 2025年 近一周 近一个月 近一年 近期 最近 最近一个月 居家达标时间 居家养老达标时间
        本季度 去年 前年 去年二季度 去年下半年 上半年 下半年 一个月内 一年内 一周内 半年内 三个月内 去年6月以后 最近一个月新获得居家权益 最近一个月新增居家会员
    field: pajjMemberGradeInfo.pajjqualifiedtime
    operator: RANGE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "平安居家会员达标时间（达标日期）；“新获得/新拿到/新增/刚获得居家权益”均按达标时间判断，不表示平安居家期次"
    notes: "业务口径：当“新获得、新拿到、新增、刚获得”等权益获得语义与时间范围同时出现时，时间条件必须作用于本字段；“最近一个月新获得居家权益”指平安居家达标时间落在最近一个月内。"
    examples:
      - query: "2024年平安居家达标的客户"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: RANGE, value: {max: '2024-12-31',
    min: '2024-01-01'}}
      - query: "2025年居养老客户"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: RANGE, value: {min: '2025-01-01',
    max: '2025-12-31'}}
      - query: "6-8月份居养客户"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: RANGE, value: {min: '2026-06-01',
    max: '2026-08-31'}}
      - query: "平安居家去年二季度达标的客户"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: RANGE, value: {max: '2025-06-30',
    min: '2025-04-01'}}
      - query: "上个月新增的居家会员"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: RANGE, value: {max: '2026-05-31',
    min: '2026-05-01'}}
      - query: "最近一个月新获得居家或者高端康养权益的客户"
        output: {query_logic: OR, conditions: [{field: pajjMemberGradeInfo.pajjqualifiedtime, operator: RANGE,
              value: {min: '2026-05-11', max: '2026-06-11'}}, {field: gdkyMemberGradeInfo.gdkyqualifiedtime,
              operator: RANGE, value: {min: '2026-05-11', max: '2026-06-11'}}]}
    negative_examples:
      - query: "平安居家2024年期的客户"
        reason: "2024年期是期次(period)，不是达标时间"
      - query: "最近一个月使用过居家服务的客户"
        reason: "这是服务使用时间，不是居家权益达标时间"

  - id: pajj_qualified_time_gt
    retrieval_text: |-
        平安居家 居家养老 居家 达标时间 获得时间 达标日期 大于 之后 以后 之后达标 以后获得 平安居家|居家养老|居家之后达标 平安居家|居家养老|居家以后获得 2023年以后 2024年以后 2025年以后 去年以后
        去年6月以后
    field: pajjMemberGradeInfo.pajjqualifiedtime
    operator: GT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "平安居家会员达标时间大于某日期"
    notes: "查询在某日期之后达标的客户"
    examples:
      - query: "2023年以后拿到平安居家权益的"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: GT, value: '2023-12-31'}
    negative_examples:
      - query: "2024年平安居家达标的客户"
        reason: "指定年份范围应使用RANGE"

  - id: pajj_qualified_time_gte
    retrieval_text: |-
        平安居家 居家养老 居家 达标时间 获得时间 达标日期 大于等于 不小于 及之后 及以上 及以后 至少 平安居家|居家养老|居家及之后达标 平安居家|居家养老|居家及以上 平安居家|居家养老|居家大于等于 2023年及之后
        2024年及以后
    field: pajjMemberGradeInfo.pajjqualifiedtime
    operator: GTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "平安居家会员达标时间大于等于某日期"
    notes: "查询在某日期及之后达标的客户"
    examples:
      - query: "2024年及之后平安居家达标的客户"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: GTE, value: '2024-01-01'}
    negative_examples:
      - query: "2024年平安居家达标的客户"
        reason: "精确年份范围应使用RANGE"

  - id: pajj_qualified_time_lt
    retrieval_text: |-
        平安居家 居家养老 居家 达标时间 获得时间 达标日期 小于 之前 以前 之前达标 以前获得 平安居家|居家养老|居家之前达标 平安居家|居家养老|居家以前获得 2025年以前 25年以前 2024年之前 2023年之前
    field: pajjMemberGradeInfo.pajjqualifiedtime
    operator: LT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "平安居家会员达标时间小于某日期"
    notes: "查询在某日期之前达标的客户"
    examples:
      - query: "25年以前获得平安居家的"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: LT, value: '2025-01-01'}
    negative_examples:
      - query: "2024年之前平安居家期次"
        reason: "期次使用memberperiod字段，不是qualifiedtime"

  - id: pajj_qualified_time_lte
    retrieval_text: |-
        平安居家 居家养老 居家 达标时间 获得时间 达标日期 小于等于 不大于 及之前 及以前 至多 最晚 平安居家|居家养老|居家及之前达标 平安居家|居家养老|居家不大于 平安居家|居家养老|居家小于等于 去年年底前
        2024年底前 2023年底前
    field: pajjMemberGradeInfo.pajjqualifiedtime
    operator: LTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "平安居家会员达标时间小于等于某日期"
    notes: "查询在某日期及之前达标的客户"
    examples:
      - query: "去年年底前获得平安居家的客户"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: LTE, value: '2025-12-31'}
    negative_examples:
      - query: "平安居家去年达标的客户"
        reason: "整年范围应使用RANGE"

  - id: pajj_qualified_time_exists
    retrieval_text: |-
        平安居家 居家养老 居家 达标时间 获得时间 达标日期 拿到时间 有达标时间 有获得时间 有时间 达标时间不为空 获得时间不为空 已达标 已拿到 已获得 已登记达标时间 平安居家|居家养老|居家有达标时间
        平安居家|居家养老|居家获得时间不为空 平安居家|居家养老|居家已达标
    field: pajjMemberGradeInfo.pajjqualifiedtime
    operator: EXISTS
    value_type: exists
    description: "平安居家会员达标时间是否有值"
    notes: "仅判断平安居家是否有达标时间记录"
    examples:
      - query: "有平安居家达标时间的客户"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: EXISTS, value: ''}
    negative_examples:
      - query: "2024年平安居家达标的客户"
        reason: "指定了具体达标时间，应使用RANGE"

  - id: pajj_qualified_time_not_exists
    retrieval_text: |-
        平安居家 居家养老 居家 达标时间 达标日期 获得时间 获得日期 达标时间为空 获得时间为空 达标时间没值 达标时间没填 没有达标时间 达标时间没记录 达标日期为空 获得时间没记录的 达标时间空着 达标时间还空着
        没有获得时间 无达标时间 无获得时间 获得日期为空 什么时候达标的没记 获得时间没记录的 平安居家|居家养老|居家达标时间为空 平安居家|居家养老|居家获得时间没记录的 平安居家|居家养老|居家达标时间还空着
        平安居家|居家养老|居家没有达标时间
    field: pajjMemberGradeInfo.pajjqualifiedtime
    operator: NOT_EXISTS
    value_type: exists
    description: "平安居家会员达标时间是否为空"
    notes: "查询平安居家达标时间未记录的客户"
    examples:
      - query: "平安居家达标时间为空的客户"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: NOT_EXISTS, value: ''}
      - query: "平安居家获得时间没记录的"
        output: {field: pajjMemberGradeInfo.pajjqualifiedtime, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "平安居家还没有达标的客户"
        reason: "可能是查询达标状态(status)而非达标时间"

  - id: yxgy_member_product_match
    retrieval_text: |-
        御享国医 服务线 服务线名称 产品线 会员服务 权益 开通了御享国医 购买了御享国医 买了御享国医 享有御享国医 已有御享国医 有御享国医权益的 御享国医客户 御享国医会员 御享国医的客户 开通御享国医服务的 有御享国医权益
        包含御享国医 有御享国医服务线 有御享国医的 获得御享国医的客户 拿到御享国医的 有御享国医吗 是不是御享国医 怎么查御享国医 有御享国医权益的客户
    field: yxgyMemberGradeInfo.yxgymemberproductname
    operator: MATCH
    value_type: enum
    enum_ref: yxgyMemberGradeInfo.yxgymemberproductname
    description: "御享国医会员服务线名称，不表示其他服务线"
    notes: "枚举值「御享国医」；有该服务线即表示客户开通了御享国医会员服务"
    examples:
      - query: "服务线名为御享国医的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberproductname, operator: MATCH, value: 御享国医}
    negative_examples:
      - query: "御享国医达标的客户"
        reason: "达标是会员状态(status)，不是服务线"

  - id: yxgy_member_product_contains
    retrieval_text: |-
        御享国医 服务线 会员服务 权益 也开通了 同时有 还有 既有 也有 和 或 或者 包含御享国医 有御享国医和 御享国医都有 御享国医以及 多种权益 多个服务线
    field: yxgyMemberGradeInfo.yxgymemberproductname
    operator: CONTAINS
    value_type: enum
    enum_ref: yxgyMemberGradeInfo.yxgymemberproductname
    description: "御享国医会员服务线名称，用于多服务线组合查询"
    notes: "查询同时拥有多个服务线的客户时使用CONTAINS"
    examples:
      - query: "有御享国医也有安有护的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberproductname, operator: CONTAINS, value: [御享国医,
    安有护]}
    negative_examples:
      - query: "只有御享国医的客户"
        reason: "单一服务线查询应为MATCH"

  - id: yxgy_member_product_not_contains
    retrieval_text: |-
        御享国医 服务线 会员服务 权益 没有御享国医 不是御享国医 不包含御享国医 不含御享国医 排除御享国医 不要御享国医 无御享国医 没御享国医 非御享国医 除了御享国医之外 御享国医除外 去掉御享国医 但没有御享国医
    field: yxgyMemberGradeInfo.yxgymemberproductname
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: yxgyMemberGradeInfo.yxgymemberproductname
    description: "御享国医会员服务线名称，用于排除查询"
    notes: "排除御享国医服务线的客户时使用NOT_CONTAINS"
    examples:
      - query: "没有御享国医服务线的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberproductname, operator: NOT_CONTAINS, value: 御享国医}
      - query: "有安有护但没有御享国医的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberproductname, operator: NOT_CONTAINS, value: 御享国医}
    negative_examples:
      - query: "有御享国医的客户"
        reason: "正向匹配应使用MATCH"

  - id: yxgy_member_product_exists
    retrieval_text: |-
        御享国医 服务线 会员服务 权益 开通御享国医了吗 是否有御享国医 有没有御享国医服务线 获得御享国医的客户 拿到御享国医的 有御享国医会员 御享国医服务线不为空 有御享国医服务线 有御享国医权益
    field: yxgyMemberGradeInfo.yxgymemberproductname
    operator: EXISTS
    value_type: exists
    description: "御享国医会员服务线是否有值"
    notes: "仅判断御享国医服务线是否有记录，不关心具体值；权益潜客在解析阶段使用memberstatus，最终由系统后处理生成本条件。"
    examples:
      - query: "开通了御享国医的客户"
        output: { field: yxgyMemberGradeInfo.yxgymemberproductname, operator: EXISTS, value: '' }
      - query: "有御享国医权益的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberproductname, operator: EXISTS, value: ''}
    negative_examples:
      - query: "御享国医客户"
        reason: "指定了具体服务线值，应使用MATCH"

  - id: yxgy_member_product_not_exists
    retrieval_text: |-
        御享国医 服务线 会员服务 权益 御享国医服务线为空 御享国医权益为空 御享国医服务线没值 御享国医没有记录 没有御享国医服务线 没有御享国医权益 没有御享国医会员 还没开通御享国医 没拿到御享国医 无御享国医服务线
        无御享国医权益 御享国医为空 所有会员权益都没标的 权益都没标
    field: yxgyMemberGradeInfo.yxgymemberproductname
    operator: NOT_EXISTS
    value_type: exists
    description: "御享国医会员服务线是否为空"
    notes: "查询没有御享国医服务线记录的客户"
    examples:
      - query: "没有御享国医权益的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberproductname, operator: NOT_EXISTS, value: ''}
      - query: "御享国医权益为空的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberproductname, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不是御享国医的客户"
        reason: "可能是排除特定值而非判断字段是否存在"

  - id: yxgy_member_grade_match
    retrieval_text: |-
        御享国医 会员等级 等级 版本 级别 档次 御享国医 御享国医等级 御享国医版本 御享国医什么等级 御享国医哪个版本 御享国医是什么级别 包含 不包含 有等级 无等级 等级为空 等级不为空 御享国医有等级吗
    field: yxgyMemberGradeInfo.yxgymembergradesearch
    operator: MATCH
    value_type: enum
    enum_ref: yxgyMemberGradeInfo.yxgymembergradesearch
    description: "御享国医会员等级或版本，不表示御享国医达标状态"
    notes: "枚举值共1个：御享国医；各版本为并列关系，无固定高低排序"
    examples:
      - query: "御享国医御享国医的客户"
        output: {field: yxgyMemberGradeInfo.yxgymembergradesearch, operator: MATCH, value: 御享国医}
      - query: "御享国医等级是御享国医的客户"
        output: {field: yxgyMemberGradeInfo.yxgymembergradesearch, operator: MATCH, value: 御享国医}
    negative_examples:
      - query: "御享国医达标的客户"
        reason: "达标是会员状态(status)，不是等级(grade)"

  - id: yxgy_member_grade_contains
    retrieval_text: |-
        御享国医 会员等级 等级 版本 御享国医 或者 或 和 及 与 都要 都查 都查一下 都可以 御享国医或者 御享国医和 御享国医以及 包含 含有 多个等级 多个版本
    field: yxgyMemberGradeInfo.yxgymembergradesearch
    operator: CONTAINS
    value_type: enum
    enum_ref: yxgyMemberGradeInfo.yxgymembergradesearch
    description: "御享国医会员等级多值查询"
    notes: "查询多个御享国医等级时使用CONTAINS"
    examples:
      - query: "御享国医御享国医或者御享国医都查一下"
        output: {field: yxgyMemberGradeInfo.yxgymembergradesearch, operator: CONTAINS, value: [御享国医,
    御享国医]}
    negative_examples:
      - query: "御享国医御享国医的客户"
        reason: "单一等级查询应为MATCH"

  - id: yxgy_member_grade_not_contains
    retrieval_text: |-
        御享国医 会员等级 等级 版本 御享国医 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 御享国医不要 御享国医排除 御享国医不是 御享国医不包含
    field: yxgyMemberGradeInfo.yxgymembergradesearch
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: yxgyMemberGradeInfo.yxgymembergradesearch
    description: "御享国医会员等级排除查询"
    notes: "排除某个御享国医等级时使用NOT_CONTAINS"
    examples:
      - query: "不要御享国医的御享国医客户"
        output: {field: yxgyMemberGradeInfo.yxgymembergradesearch, operator: NOT_CONTAINS, value: 御享国医}
    negative_examples:
      - query: "御享国医御享国医的客户"
        reason: "正向匹配应使用MATCH"

  - id: yxgy_member_grade_exists
    retrieval_text: |-
        御享国医 会员等级 等级 版本 有等级 有版本 有等级吗 有没有等级 是否有等级 等级不为空 等级已定 等级已填 已定级 御享国医有等级 御享国医有版本 御享国医已定级 御享国医等级不为空
    field: yxgyMemberGradeInfo.yxgymembergradesearch
    operator: EXISTS
    value_type: exists
    description: "御享国医会员等级是否有值"
    notes: "仅判断御享国医是否有等级记录，不关心具体等级值"
    examples:
      - query: "有御享国医等级的客户"
        output: {field: yxgyMemberGradeInfo.yxgymembergradesearch, operator: EXISTS, value: ''}
    negative_examples:
      - query: "御享国医御享国医的客户"
        reason: "指定了具体等级值，应使用MATCH"

  - id: yxgy_member_grade_not_exists
    retrieval_text: |-
        御享国医 会员等级 等级 版本 等级为空 等级没值 等级没填 等级没定 还没定级 没有等级 无等级 等级没登记 等级还没定的 没等级 御享国医等级为空 御享国医没等级 御享国医等级还没定的 御享国医等级没登记的
    field: yxgyMemberGradeInfo.yxgymembergradesearch
    operator: NOT_EXISTS
    value_type: exists
    description: "御享国医会员等级是否为空"
    notes: "查询御享国医等级未登记或未填写的客户"
    examples:
      - query: "御享国医等级还没定的客户"
        output: {field: yxgyMemberGradeInfo.yxgymembergradesearch, operator: NOT_EXISTS, value: ''}
      - query: "没有御享国医等级的客户"
        output: {field: yxgyMemberGradeInfo.yxgymembergradesearch, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要御享国医御享国医的客户"
        reason: "排除特定等级值使用NOT_CONTAINS"

  - id: yxgy_member_status_match
    enum_requires_anchor: true
    retrieval_text: |-
        御享国医 会员类型 会员状态 类型 状态 是什么状态 什么状态 什么类型 哪种状态 预达标 潜客 意向 达标 御享国医状态 御享国医类型 御享国医会员类型 御享国医的状态 御享国医是什么状态 御享国医会员状态 包含 不包含
        有状态 无状态 状态为空 状态不为空
    field: yxgyMemberGradeInfo.yxgymemberstatus
    operator: MATCH
    value_type: enum
    enum_ref: yxgyMemberGradeInfo.yxgymemberstatus
    description: "御享国医会员类型或状态，不表示御享国医等级版本"
    notes: "枚举值共4个：预达标、潜客、意向、达标；状态互斥，一个客户同一时间只能属于一种状态"
    examples:
      - query: "御享国医潜客"
        output: {field: yxgyMemberGradeInfo.yxgymemberstatus, operator: MATCH, value: 潜客}
      - query: "御享国医预达标的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberstatus, operator: MATCH, value: 预达标}
      - query: "御享国医是达标客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberstatus, operator: MATCH, value: 达标}
    negative_examples:
      - query: "御享国医御享国医的客户"
        reason: "御享国医是等级(grade)，不是状态(status)"

  - id: yxgy_member_status_contains
    enum_requires_anchor: true
    retrieval_text: |-
        御享国医 会员类型 会员状态 类型 状态 预达标 潜客 意向 达标 临界 临界客户 包含 含有 或者 或 和 都要 都查 御享国医或者 御享国医或 御享国医以及 御享国医和
    field: yxgyMemberGradeInfo.yxgymemberstatus
    operator: CONTAINS
    value_type: enum
    enum_ref: yxgyMemberGradeInfo.yxgymemberstatus
    description: "御享国医会员类型多值查询"
    notes: "查询多种御享国医状态时使用CONTAINS；临界客户=潜客或意向"
    examples:
      - query: "御享国医预达标或者达标客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberstatus, operator: CONTAINS, value: [预达标, 达标]}
    negative_examples:
      - query: "御享国医预达标客户"
        reason: "单一状态查询应为MATCH"

  - id: yxgy_member_status_not_contains
    enum_requires_anchor: true
    retrieval_text: |-
        御享国医 会员类型 会员状态 类型 状态 预达标 潜客 意向 达标 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 御享国医不要 御享国医排除 御享国医不包含
    field: yxgyMemberGradeInfo.yxgymemberstatus
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: yxgyMemberGradeInfo.yxgymemberstatus
    description: "御享国医会员类型排除查询"
    notes: "排除某种御享国医状态时使用NOT_CONTAINS"
    examples:
      - query: "御享国医不要预达标客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberstatus, operator: NOT_CONTAINS, value: 预达标}
    negative_examples:
      - query: "御享国医预达标客户"
        reason: "正向匹配应使用MATCH"

  - id: yxgy_member_status_exists
    retrieval_text: |-
        御享国医 会员类型 会员状态 类型 状态 有状态 有类型 有会员状态 有会员类型 状态不为空 类型不为空 状态已标 状态已登记 已有状态 御享国医有状态 御享国医状态不为空 御享国医状态已填
    field: yxgyMemberGradeInfo.yxgymemberstatus
    operator: EXISTS
    value_type: exists
    description: "御享国医会员类型是否有值"
    notes: "仅判断御享国医是否有状态记录，不关心具体状态值"
    examples:
      - query: "有御享国医状态的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberstatus, operator: EXISTS, value: ''}
    negative_examples:
      - query: "御享国医预达标客户"
        reason: "指定了具体状态值，应使用MATCH"

  - id: yxgy_member_status_not_exists
    retrieval_text: |-
        御享国医 会员类型 会员状态 类型 状态 状态为空 类型为空 没有状态 无状态 状态没标 状态没填 会员状态没标的 状态还没登记 状态没值 御享国医状态为空 御享国医状态没标的 御享国医没状态 御享国医状态还没登记的
    field: yxgyMemberGradeInfo.yxgymemberstatus
    operator: NOT_EXISTS
    value_type: exists
    description: "御享国医会员类型是否为空"
    notes: "查询御享国医状态未登记的客户"
    examples:
      - query: "御享国医会员状态没标的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberstatus, operator: NOT_EXISTS, value: ''}
      - query: "没有御享国医状态的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberstatus, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要御享国医预达标客户"
        reason: "排除特定状态值使用NOT_CONTAINS"

  - id: yxgy_member_period_match
    retrieval_text: |-
        御享国医 会员期次 期次 会员年度 年度 哪一期 什么期次 哪个年度 M2023 M2024 M2025 M年份 包含2023年期 包含2024年期的 包含2025年期的 2023年那期 2024年那期 23年那期
        24年那期 御享国医2023年 御享国医2024年 御享国医2025年 御享国医期次 御享国医年度 御享国医哪一期 御享国医哪个年度 是哪一期 哪年那期 2024年那一期 2025年那一期 有期次 无期次 期次为空
        期次不为空
    field: yxgyMemberGradeInfo.yxgymemberperiod
    operator: MATCH
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "御享国医会员期次（年度），不表示御享国医达标时间"
    notes: "期次为年份格式YYYY，如2023、2024、2025；一个客户可能拥有多个年度的期次记录"
    examples:
      - query: "御享国医2024年期的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberperiod, operator: MATCH, value: '2024'}
      - query: "23年那期御享国医"
        output: {field: yxgyMemberGradeInfo.yxgymemberperiod, operator: MATCH, value: '2023'}
    negative_examples:
      - query: "2024年达标的御享国医客户"
        reason: "2024年是达标时间(qualifiedtime)，不是期次(period)"

  - id: yxgy_member_period_contains
    retrieval_text: |-
        御享国医 会员期次 期次 年度 包含 含有 包括 有 都有 和 及 与 以及 包含2023年期 包含2024年期的 包含2025年期的 御享国医2023到2025 御享国医2023至2025 2023和2024年期 多个期次
        几个年度
    field: yxgyMemberGradeInfo.yxgymemberperiod
    operator: CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "御享国医会员期次多值查询"
    notes: "查询包含多个期次时使用CONTAINS"
    examples:
      - query: "御享国医包含2023年期和2024年期的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberperiod, operator: CONTAINS, value: ['2023',
    '2024']}
    negative_examples:
      - query: "御享国医2024年期的客户"
        reason: "单一年份应使用MATCH"

  - id: yxgy_member_period_not_contains
    retrieval_text: |-
        御享国医 会员期次 期次 年度 不包含 不含 不要 排除 去除 没有 不包含2023年期 不包含2024年期 不包含2025年期 御享国医不包含 御享国医不含 御享国医不要
    field: yxgyMemberGradeInfo.yxgymemberperiod
    operator: NOT_CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "御享国医会员期次排除查询"
    notes: "排除某些期次时使用NOT_CONTAINS"
    examples:
      - query: "御享国医不包含2023年期的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberperiod, operator: NOT_CONTAINS, value: '2023'}
    negative_examples:
      - query: "御享国医包含2023年期的客户"
        reason: "正向匹配应使用MATCH或CONTAINS"

  - id: yxgy_member_period_exists
    retrieval_text: |-
        御享国医 会员期次 期次 年度 有期次 有年度 有期次吗 有没有期次 是否有期次 期次不为空 期次已登记 期次已填 已登记期次 御享国医有期次 御享国医期次不为空 御享国医期次已填
    field: yxgyMemberGradeInfo.yxgymemberperiod
    operator: EXISTS
    value_type: exists
    description: "御享国医会员期次是否有值"
    notes: "仅判断御享国医是否有期次记录，不关心具体年份"
    examples:
      - query: "有御享国医期次的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberperiod, operator: EXISTS, value: ''}
    negative_examples:
      - query: "御享国医2024年期的客户"
        reason: "指定了具体年份值，应使用MATCH"

  - id: yxgy_member_period_not_exists
    retrieval_text: |-
        御享国医 会员期次 期次 年度 期次为空 期次没值 期次没填 没有期次 无期次 期次没登记 期次还没登记 没填期次 哪一期没登记 哪一期还没登记 权益期次没有的 期次没填的 御享国医期次为空 御享国医期次没填的
        御享国医没有期次 御享国医哪一期没登记 御享国医期次没登记
    field: yxgyMemberGradeInfo.yxgymemberperiod
    operator: NOT_EXISTS
    value_type: exists
    description: "御享国医会员期次是否为空"
    notes: "查询御享国医期次未登记的客户"
    examples:
      - query: "御享国医期次没填的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberperiod, operator: NOT_EXISTS, value: ''}
      - query: "御享国医是哪一期还没登记的客户"
        output: {field: yxgyMemberGradeInfo.yxgymemberperiod, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "御享国医不包含2023年期的客户"
        reason: "排除特定期次值使用NOT_CONTAINS"

  - id: yxgy_qualified_time_range
    retrieval_text: |-
        御享国医 达标时间 达标日期 获得时间 获得日期 拿到时间 什么时候达标 何时达标 哪年达标 什么时候获得 御享国医达标 御享国医获得 御享国医拿到 御享国医达标时间 御享国医获得时间 御享国医什么时候达标 时间范围 从到
        之间 去年 今年 2023年 2024年 2025年 近一周 近一个月 近一年 近期 最近 最近一个月 本季度 去年 前年 去年二季度 去年下半年 上半年 下半年 大于 小于 之后 之前 以来 至今 一个月内 一年内 一周内
        半年内 三个月内 去年6月以后
    field: yxgyMemberGradeInfo.yxgyqualifiedtime
    operator: RANGE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "御享国医会员达标时间（达标日期），不表示御享国医期次"
    notes: "达标时间指客户满足会员资格条件的日期，格式yyyy-MM-dd"
    examples:
      - query: "2024年御享国医达标的客户"
        output: {field: yxgyMemberGradeInfo.yxgyqualifiedtime, operator: RANGE, value: {max: '2024-12-31',
    min: '2024-01-01'}}
      - query: "御享国医近一年达标的客户"
        output: {field: yxgyMemberGradeInfo.yxgyqualifiedtime, operator: RANGE, value: {max: '2026-06-11',
    min: '2025-06-11'}}
      - query: "御享国医去年二季度达标的客户"
        output: {field: yxgyMemberGradeInfo.yxgyqualifiedtime, operator: RANGE, value: {max: '2025-06-30',
    min: '2025-04-01'}}
    negative_examples:
      - query: "御享国医2024年期的客户"
        reason: "2024年期是期次(period)，不是达标时间"

  - id: yxgy_qualified_time_gt
    retrieval_text: |-
        御享国医 达标时间 获得时间 达标日期 大于 之后 以后 之后达标 以后获得 御享国医之后达标 御享国医以后获得 2023年以后 2024年以后 2025年以后 去年以后 去年6月以后
    field: yxgyMemberGradeInfo.yxgyqualifiedtime
    operator: GT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "御享国医会员达标时间大于某日期"
    notes: "查询在某日期之后达标的客户"
    examples:
      - query: "2023年以后拿到御享国医权益的"
        output: {field: yxgyMemberGradeInfo.yxgyqualifiedtime, operator: GT, value: '2023-12-31'}
    negative_examples:
      - query: "2024年御享国医达标的客户"
        reason: "指定年份范围应使用RANGE"

  - id: yxgy_qualified_time_gte
    retrieval_text: |-
        御享国医 达标时间 获得时间 达标日期 大于等于 不小于 及之后 及以上 及以后 至少 御享国医及之后达标 御享国医及以上 御享国医大于等于 2023年及之后 2024年及以后
    field: yxgyMemberGradeInfo.yxgyqualifiedtime
    operator: GTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "御享国医会员达标时间大于等于某日期"
    notes: "查询在某日期及之后达标的客户"
    examples:
      - query: "2024年及之后御享国医达标的客户"
        output: {field: yxgyMemberGradeInfo.yxgyqualifiedtime, operator: GTE, value: '2024-01-01'}
    negative_examples:
      - query: "2024年御享国医达标的客户"
        reason: "精确年份范围应使用RANGE"

  - id: yxgy_qualified_time_lt
    retrieval_text: |-
        御享国医 达标时间 获得时间 达标日期 小于 之前 以前 之前达标 以前获得 御享国医之前达标 御享国医以前获得 2025年以前 25年以前 2024年之前 2023年之前
    field: yxgyMemberGradeInfo.yxgyqualifiedtime
    operator: LT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "御享国医会员达标时间小于某日期"
    notes: "查询在某日期之前达标的客户"
    examples:
      - query: "25年以前获得御享国医的"
        output: {field: yxgyMemberGradeInfo.yxgyqualifiedtime, operator: LT, value: '2025-01-01'}
    negative_examples:
      - query: "2024年之前御享国医期次"
        reason: "期次使用memberperiod字段，不是qualifiedtime"

  - id: yxgy_qualified_time_lte
    retrieval_text: |-
        御享国医 达标时间 获得时间 达标日期 小于等于 不大于 及之前 及以前 至多 最晚 御享国医及之前达标 御享国医不大于 御享国医小于等于 去年年底前 2024年底前 2023年底前
    field: yxgyMemberGradeInfo.yxgyqualifiedtime
    operator: LTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "御享国医会员达标时间小于等于某日期"
    notes: "查询在某日期及之前达标的客户"
    examples:
      - query: "去年年底前获得御享国医的客户"
        output: {field: yxgyMemberGradeInfo.yxgyqualifiedtime, operator: LTE, value: '2025-12-31'}
    negative_examples:
      - query: "御享国医去年达标的客户"
        reason: "整年范围应使用RANGE"

  - id: yxgy_qualified_time_exists
    retrieval_text: |-
        御享国医 达标时间 获得时间 达标日期 拿到时间 有达标时间 有获得时间 有时间 达标时间不为空 获得时间不为空 已达标 已拿到 已获得 已登记达标时间 御享国医有达标时间 御享国医获得时间不为空 御享国医已达标
    field: yxgyMemberGradeInfo.yxgyqualifiedtime
    operator: EXISTS
    value_type: exists
    description: "御享国医会员达标时间是否有值"
    notes: "仅判断御享国医是否有达标时间记录"
    examples:
      - query: "有御享国医达标时间的客户"
        output: {field: yxgyMemberGradeInfo.yxgyqualifiedtime, operator: EXISTS, value: ''}
    negative_examples:
      - query: "2024年御享国医达标的客户"
        reason: "指定了具体达标时间，应使用RANGE"

  - id: yxgy_qualified_time_not_exists
    retrieval_text: |-
        御享国医 达标时间 达标日期 获得时间 获得日期 达标时间为空 获得时间为空 达标时间没值 达标时间没填 没有达标时间 达标时间没记录 达标日期为空 获得时间没记录的 达标时间空着 达标时间还空着 没有获得时间 无达标时间
        无获得时间 获得日期为空 什么时候达标的没记 获得时间没记录的 御享国医达标时间为空 御享国医获得时间没记录的 御享国医达标时间还空着 御享国医没有达标时间
    field: yxgyMemberGradeInfo.yxgyqualifiedtime
    operator: NOT_EXISTS
    value_type: exists
    description: "御享国医会员达标时间是否为空"
    notes: "查询御享国医达标时间未记录的客户"
    examples:
      - query: "御享国医达标时间为空的客户"
        output: {field: yxgyMemberGradeInfo.yxgyqualifiedtime, operator: NOT_EXISTS, value: ''}
      - query: "御享国医获得时间没记录的"
        output: {field: yxgyMemberGradeInfo.yxgyqualifiedtime, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "御享国医还没有达标的客户"
        reason: "可能是查询达标状态(status)而非达标时间"

  - id: sdbjy_member_product_match
    retrieval_text: |-
        私董保健医 私董 保健医 服务线 服务线名称 产品线 会员服务 权益 开通了私董保健医|私董|保健医 购买了私董保健医|私董|保健医 买了私董保健医|私董|保健医 享有私董保健医|私董|保健医 已有私董保健医|私董|保健医
        有私董保健医|私董|保健医权益的 私董保健医|私董|保健医客户 私董保健医|私董|保健医会员 私董保健医|私董|保健医的客户 开通私董保健医|私董|保健医服务的 有私董保健医|私董|保健医权益 包含私董保健医|私董|保健医
        有私董保健医|私董|保健医服务线 有私董保健医|私董|保健医的 获得私董保健医|私董|保健医的客户 拿到私董保健医|私董|保健医的 有私董保健医|私董|保健医吗 是不是私董保健医|私董|保健医 怎么查私董保健医|私董|保健医
        有私董保健医|私董|保健医权益的客户
    field: sdbjyMemberGradeInfo.sdbjymemberproductname
    operator: MATCH
    value_type: enum
    enum_ref: sdbjyMemberGradeInfo.sdbjymemberproductname
    description: "私董保健医会员服务线名称，不表示其他服务线"
    notes: "枚举值「私董保健医」；有该服务线即表示客户开通了私董保健医会员服务"
    examples:
      - query: "服务线名为私董保健医客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberproductname, operator: MATCH, value: 私董保健医}
    negative_examples:
      - query: "私董保健医达标的客户"
        reason: "达标是会员状态(status)，不是服务线"

  - id: sdbjy_member_product_contains
    retrieval_text: |-
        私董保健医 私董 保健医 服务线 会员服务 权益 也开通了 同时有 还有 既有 也有 和 或 或者 包含私董保健医|私董|保健医 有私董保健医|私董|保健医和 私董保健医|私董|保健医都有 私董保健医|私董|保健医以及
        多种权益 多个服务线
    field: sdbjyMemberGradeInfo.sdbjymemberproductname
    operator: CONTAINS
    value_type: enum
    enum_ref: sdbjyMemberGradeInfo.sdbjymemberproductname
    description: "私董保健医会员服务线名称，用于多服务线组合查询"
    notes: "查询同时拥有多个服务线的客户时使用CONTAINS"
    examples:
      - query: "有私董保健医也有安有护的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberproductname, operator: CONTAINS, value: [
    私董保健医, 安有护]}
    negative_examples:
      - query: "只有私董保健医的客户"
        reason: "单一服务线查询应为MATCH"

  - id: sdbjy_member_product_not_contains
    retrieval_text: |-
        私董保健医 私董 保健医 服务线 会员服务 权益 没有私董保健医|私董|保健医 不是私董保健医|私董|保健医 不包含私董保健医|私董|保健医 不含私董保健医|私董|保健医 排除私董保健医|私董|保健医
        不要私董保健医|私董|保健医 无私董保健医|私董|保健医 没私董保健医|私董|保健医 非私董保健医|私董|保健医 除了私董保健医|私董|保健医之外 私董保健医|私董|保健医除外 去掉私董保健医|私董|保健医
        但没有私董保健医|私董|保健医
    field: sdbjyMemberGradeInfo.sdbjymemberproductname
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: sdbjyMemberGradeInfo.sdbjymemberproductname
    description: "私董保健医会员服务线名称，用于排除查询"
    notes: "排除私董保健医服务线的客户时使用NOT_CONTAINS"
    examples:
      - query: "没有私董保健医服务线的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberproductname, operator: NOT_CONTAINS, value: 私董保健医}
      - query: "有安有护但没有私董保健医的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberproductname, operator: NOT_CONTAINS, value: 私董保健医}
    negative_examples:
      - query: "有私董保健医的客户"
        reason: "正向匹配应使用MATCH"

  - id: sdbjy_member_product_exists
    retrieval_text: |-
        私董保健医 私董 保健医 服务线 会员服务 权益 开通私董保健医|私董|保健医了吗 是否有私董保健医|私董|保健医 有没有私董保健医|私董|保健医服务线 获得私董保健医|私董|保健医的客户 拿到私董保健医|私董|保健医的
        有私董保健医|私董|保健医会员 私董保健医|私董|保健医服务线不为空 有私董保健医|私董|保健医服务线 有私董保健医|私董|保健医权益
    field: sdbjyMemberGradeInfo.sdbjymemberproductname
    operator: EXISTS
    value_type: exists
    description: "私董保健医会员服务线是否有值"
    notes: "仅判断私董保健医服务线是否有记录，不关心具体值；权益潜客在解析阶段使用memberstatus，最终由系统后处理生成本条件。"
    examples:
      - query: "有私董保健医权益的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberproductname, operator: EXISTS, value: ''}
      - query: "开通了私董保健医的客户"
        output: { field: sdbjyMemberGradeInfo.sdbjymemberproductname, operator: EXISTS, value: '' }
    negative_examples:
      - query: "私董保健医客户"
        reason: "指定了具体服务线值，应使用MATCH"

  - id: sdbjy_member_product_not_exists
    retrieval_text: |-
        私董保健医 私董 保健医 服务线 会员服务 权益 私董保健医|私董|保健医服务线为空 私董保健医|私董|保健医权益为空 私董保健医|私董|保健医服务线没值 私董保健医|私董|保健医没有记录 没有私董保健医|私董|保健医服务线
        没有私董保健医|私董|保健医权益 没有私董保健医|私董|保健医会员 还没开通私董保健医|私董|保健医 没拿到私董保健医|私董|保健医 无私董保健医|私董|保健医服务线 无私董保健医|私董|保健医权益
        私董保健医|私董|保健医为空 所有会员权益都没标的 权益都没标
    field: sdbjyMemberGradeInfo.sdbjymemberproductname
    operator: NOT_EXISTS
    value_type: exists
    description: "私董保健医会员服务线是否为空"
    notes: "查询没有私董保健医服务线记录的客户"
    examples:
      - query: "没有私董保健医权益的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberproductname, operator: NOT_EXISTS, value: ''}
      - query: "私董保健医权益为空的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberproductname, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不是私董保健医的客户"
        reason: "可能是排除特定值而非判断字段是否存在"

  - id: sdbjy_member_grade_match
    retrieval_text: |-
        私董保健医 私董 保健医 会员等级 等级 版本 级别 档次 京华版 繁花版 私董京华版 私董繁花版 保健医京华版 保健医繁花版 私董保健医京华版 私董保健医繁花版 京华版 繁花版 私董京华 繁花版私董
        私董保健医|私董|保健医等级 私董保健医|私董|保健医版本 私董保健医|私董|保健医什么等级 私董保健医|私董|保健医哪个版本 私董保健医|私董|保健医是什么级别 包含 不包含 有等级 无等级 等级为空 等级不为空
        私董保健医|私董|保健医有等级吗
    field: sdbjyMemberGradeInfo.sdbjymembergradesearch
    operator: MATCH
    value_type: enum
    enum_ref: sdbjyMemberGradeInfo.sdbjymembergradesearch
    description: "私董保健医会员等级或版本，不表示私董保健医达标状态"
    notes: "枚举值共2个：京华版、繁花版；各版本为并列关系，无固定高低排序"
    examples:
      - query: "私董保健医京华版的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymembergradesearch, operator: MATCH, value: 京华版}
      - query: "私董保健医等级是京华版的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymembergradesearch, operator: MATCH, value: 京华版}
    negative_examples:
      - query: "私董保健医达标的客户"
        reason: "达标是会员状态(status)，不是等级(grade)"

  - id: sdbjy_member_grade_contains
    retrieval_text: |-
        私董保健医 私董 保健医 会员等级 等级 版本 京华版 繁花版 或者 或 和 及 与 都要 都查 都查一下 都可以 私董保健医|私董|保健医或者 私董保健医|私董|保健医和 私董保健医|私董|保健医以及 包含 含有 多个等级
        多个版本
    field: sdbjyMemberGradeInfo.sdbjymembergradesearch
    operator: CONTAINS
    value_type: enum
    enum_ref: sdbjyMemberGradeInfo.sdbjymembergradesearch
    description: "私董保健医会员等级多值查询"
    notes: "查询多个私董保健医等级时使用CONTAINS"
    examples:
      - query: "私董保健医京华版或者京华版都查一下"
        output: {field: sdbjyMemberGradeInfo.sdbjymembergradesearch, operator: CONTAINS, value: [
    京华版, 京华版]}
    negative_examples:
      - query: "私董保健医京华版的客户"
        reason: "单一等级查询应为MATCH"

  - id: sdbjy_member_grade_not_contains
    retrieval_text: |-
        私董保健医 私董 保健医 会员等级 等级 版本 京华版 繁花版 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 私董保健医|私董|保健医不要 私董保健医|私董|保健医排除 私董保健医|私董|保健医不是
        私董保健医|私董|保健医不包含
    field: sdbjyMemberGradeInfo.sdbjymembergradesearch
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: sdbjyMemberGradeInfo.sdbjymembergradesearch
    description: "私董保健医会员等级排除查询"
    notes: "排除某个私董保健医等级时使用NOT_CONTAINS"
    examples:
      - query: "不要京华版的私董保健医客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymembergradesearch, operator: NOT_CONTAINS, value: 京华版}
    negative_examples:
      - query: "私董保健医京华版的客户"
        reason: "正向匹配应使用MATCH"

  - id: sdbjy_member_grade_exists
    retrieval_text: |-
        私董保健医 私董 保健医 会员等级 等级 版本 有等级 有版本 有等级吗 有没有等级 是否有等级 等级不为空 等级已定 等级已填 已定级 私董保健医|私董|保健医有等级 私董保健医|私董|保健医有版本
        私董保健医|私董|保健医已定级 私董保健医|私董|保健医等级不为空
    field: sdbjyMemberGradeInfo.sdbjymembergradesearch
    operator: EXISTS
    value_type: exists
    description: "私董保健医会员等级是否有值"
    notes: "仅判断私董保健医是否有等级记录，不关心具体等级值"
    examples:
      - query: "有私董保健医等级的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymembergradesearch, operator: EXISTS, value: ''}
    negative_examples:
      - query: "私董保健医京华版的客户"
        reason: "指定了具体等级值，应使用MATCH"

  - id: sdbjy_member_grade_not_exists
    retrieval_text: |-
        私董保健医 私董 保健医 会员等级 等级 版本 等级为空 等级没值 等级没填 等级没定 还没定级 没有等级 无等级 等级没登记 等级还没定的 没等级 私董保健医|私董|保健医等级为空 私董保健医|私董|保健医没等级
        私董保健医|私董|保健医等级还没定的 私董保健医|私董|保健医等级没登记的
    field: sdbjyMemberGradeInfo.sdbjymembergradesearch
    operator: NOT_EXISTS
    value_type: exists
    description: "私董保健医会员等级是否为空"
    notes: "查询私董保健医等级未登记或未填写的客户"
    examples:
      - query: "私董保健医等级还没定的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymembergradesearch, operator: NOT_EXISTS, value: ''}
      - query: "没有私董保健医等级的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymembergradesearch, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要私董保健医京华版的客户"
        reason: "排除特定等级值使用NOT_CONTAINS"

  - id: sdbjy_member_status_match
    enum_requires_anchor: true
    retrieval_text: |-
        私董保健医 私董 保健医 会员类型 会员状态 类型 状态 是什么状态 什么状态 什么类型 哪种状态 预达标 达标 潜客 意向 私董保健医|私董|保健医状态 私董保健医|私董|保健医类型 私董保健医|私董|保健医会员类型
        私董保健医|私董|保健医的状态 私董保健医|私董|保健医是什么状态 私董保健医|私董|保健医会员状态 包含 不包含 有状态 无状态 状态为空 状态不为空
    field: sdbjyMemberGradeInfo.sdbjymemberstatus
    operator: MATCH
    value_type: enum
    enum_ref: sdbjyMemberGradeInfo.sdbjymemberstatus
    description: "私董保健医会员类型或状态，不表示私董保健医等级版本"
    notes: "枚举值共4个：预达标、达标、潜客、意向；状态互斥，一个客户同一时间只能属于一种状态"
    examples:
      - query: "私董潜客"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberstatus, operator: MATCH, value: 潜客}
      - query: "私董保健医预达标的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberstatus, operator: MATCH, value: 预达标}
      - query: "私董保健医是意向客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberstatus, operator: MATCH, value: 意向}
    negative_examples:
      - query: "私董保健医京华版的客户"
        reason: "京华版是等级(grade)，不是状态(status)"

  - id: sdbjy_member_status_contains
    enum_requires_anchor: true
    retrieval_text: |-
        私董保健医 私董 保健医 会员类型 会员状态 类型 状态 预达标 达标 潜客 意向 临界 临界客户 包含 含有 或者 或 和 都要 都查 私董保健医|私董|保健医或者 私董保健医|私董|保健医或 私董保健医|私董|保健医以及
        私董保健医|私董|保健医和
    field: sdbjyMemberGradeInfo.sdbjymemberstatus
    operator: CONTAINS
    value_type: enum
    enum_ref: sdbjyMemberGradeInfo.sdbjymemberstatus
    description: "私董保健医会员类型多值查询"
    notes: "查询多种私董保健医状态时使用CONTAINS；临界客户=潜客或意向"
    examples:
      - query: "私董保健医预达标或者意向客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberstatus, operator: CONTAINS, value: [预达标, 意向]}
    negative_examples:
      - query: "私董保健医预达标客户"
        reason: "单一状态查询应为MATCH"

  - id: sdbjy_member_status_not_contains
    enum_requires_anchor: true
    retrieval_text: |-
        私董保健医 私董 保健医 会员类型 会员状态 类型 状态 预达标 达标 潜客 意向 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 私董保健医|私董|保健医不要 私董保健医|私董|保健医排除
        私董保健医|私董|保健医不包含
    field: sdbjyMemberGradeInfo.sdbjymemberstatus
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: sdbjyMemberGradeInfo.sdbjymemberstatus
    description: "私董保健医会员类型排除查询"
    notes: "排除某种私董保健医状态时使用NOT_CONTAINS"
    examples:
      - query: "私董保健医不要预达标客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberstatus, operator: NOT_CONTAINS, value: 预达标}
    negative_examples:
      - query: "私董保健医预达标客户"
        reason: "正向匹配应使用MATCH"

  - id: sdbjy_member_status_exists
    retrieval_text: |-
        私董保健医 私董 保健医 会员类型 会员状态 类型 状态 有状态 有类型 有会员状态 有会员类型 状态不为空 类型不为空 状态已标 状态已登记 已有状态 私董保健医|私董|保健医有状态 私董保健医|私董|保健医状态不为空
        私董保健医|私董|保健医状态已填
    field: sdbjyMemberGradeInfo.sdbjymemberstatus
    operator: EXISTS
    value_type: exists
    description: "私董保健医会员类型是否有值"
    notes: "仅判断私董保健医是否有状态记录，不关心具体状态值"
    examples:
      - query: "有私董保健医状态的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberstatus, operator: EXISTS, value: ''}
    negative_examples:
      - query: "私董保健医预达标客户"
        reason: "指定了具体状态值，应使用MATCH"

  - id: sdbjy_member_status_not_exists
    retrieval_text: |-
        私董保健医 私董 保健医 会员类型 会员状态 类型 状态 状态为空 类型为空 没有状态 无状态 状态没标 状态没填 会员状态没标的 状态还没登记 状态没值 私董保健医|私董|保健医状态为空 私董保健医|私董|保健医状态没标的
        私董保健医|私董|保健医没状态 私董保健医|私董|保健医状态还没登记的
    field: sdbjyMemberGradeInfo.sdbjymemberstatus
    operator: NOT_EXISTS
    value_type: exists
    description: "私董保健医会员类型是否为空"
    notes: "查询私董保健医状态未登记的客户"
    examples:
      - query: "私董保健医会员状态没标的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberstatus, operator: NOT_EXISTS, value: ''}
      - query: "没有私董保健医状态的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberstatus, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要私董保健医预达标客户"
        reason: "排除特定状态值使用NOT_CONTAINS"

  - id: sdbjy_member_period_match
    retrieval_text: |-
        私董保健医 私董 保健医 会员期次 期次 会员年度 年度 哪一期 什么期次 哪个年度 M2023 M2024 M2025 M年份 包含2023年期 包含2024年期的 包含2025年期的 2023年那期 2024年那期
        23年那期 24年那期 私董保健医|私董|保健医2023年 私董保健医|私董|保健医2024年 私董保健医|私董|保健医2025年 私董保健医|私董|保健医期次 私董保健医|私董|保健医年度 私董保健医|私董|保健医哪一期
        私董保健医|私董|保健医哪个年度 是哪一期 哪年那期 2024年那一期 2025年那一期 有期次 无期次 期次为空 期次不为空
    field: sdbjyMemberGradeInfo.sdbjymemberperiod
    operator: MATCH
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "私董保健医会员期次（年度），不表示私董保健医达标时间"
    notes: "期次为年份格式YYYY，如2023、2024、2025；一个客户可能拥有多个年度的期次记录"
    examples:
      - query: "私董保健医2024年期的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberperiod, operator: MATCH, value: '2024'}
      - query: "23年那期私董保健医"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberperiod, operator: MATCH, value: '2023'}
    negative_examples:
      - query: "2024年达标的私董保健医客户"
        reason: "2024年是达标时间(qualifiedtime)，不是期次(period)"

  - id: sdbjy_member_period_contains
    retrieval_text: |-
        私董保健医 私董 保健医 会员期次 期次 年度 包含 含有 包括 有 都有 和 及 与 以及 包含2023年期 包含2024年期的 包含2025年期的 私董保健医|私董|保健医2023到2025
        私董保健医|私董|保健医2023至2025 2023和2024年期 多个期次 几个年度
    field: sdbjyMemberGradeInfo.sdbjymemberperiod
    operator: CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "私董保健医会员期次多值查询"
    notes: "查询包含多个期次时使用CONTAINS"
    examples:
      - query: "私董保健医包含2023年期和2024年期的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberperiod, operator: CONTAINS, value: ['2023',
    '2024']}
    negative_examples:
      - query: "私董保健医2024年期的客户"
        reason: "单一年份应使用MATCH"

  - id: sdbjy_member_period_not_contains
    retrieval_text: |-
        私董保健医 私董 保健医 会员期次 期次 年度 不包含 不含 不要 排除 去除 没有 不包含2023年期 不包含2024年期 不包含2025年期 私董保健医|私董|保健医不包含 私董保健医|私董|保健医不含
        私董保健医|私董|保健医不要
    field: sdbjyMemberGradeInfo.sdbjymemberperiod
    operator: NOT_CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "私董保健医会员期次排除查询"
    notes: "排除某些期次时使用NOT_CONTAINS"
    examples:
      - query: "私董保健医不包含2023年期的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberperiod, operator: NOT_CONTAINS, value: '2023'}
    negative_examples:
      - query: "私董保健医包含2023年期的客户"
        reason: "正向匹配应使用MATCH或CONTAINS"

  - id: sdbjy_member_period_exists
    retrieval_text: |-
        私董保健医 私董 保健医 会员期次 期次 年度 有期次 有年度 有期次吗 有没有期次 是否有期次 期次不为空 期次已登记 期次已填 已登记期次 私董保健医|私董|保健医有期次 私董保健医|私董|保健医期次不为空
        私董保健医|私董|保健医期次已填
    field: sdbjyMemberGradeInfo.sdbjymemberperiod
    operator: EXISTS
    value_type: exists
    description: "私董保健医会员期次是否有值"
    notes: "仅判断私董保健医是否有期次记录，不关心具体年份"
    examples:
      - query: "有私董保健医期次的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberperiod, operator: EXISTS, value: ''}
    negative_examples:
      - query: "私董保健医2024年期的客户"
        reason: "指定了具体年份值，应使用MATCH"

  - id: sdbjy_member_period_not_exists
    retrieval_text: |-
        私董保健医 私董 保健医 会员期次 期次 年度 期次为空 期次没值 期次没填 没有期次 无期次 期次没登记 期次还没登记 没填期次 哪一期没登记 哪一期还没登记 权益期次没有的 期次没填的 私董保健医|私董|保健医期次为空
        私董保健医|私董|保健医期次没填的 私董保健医|私董|保健医没有期次 私董保健医|私董|保健医哪一期没登记 私董保健医|私董|保健医期次没登记
    field: sdbjyMemberGradeInfo.sdbjymemberperiod
    operator: NOT_EXISTS
    value_type: exists
    description: "私董保健医会员期次是否为空"
    notes: "查询私董保健医期次未登记的客户"
    examples:
      - query: "私董保健医期次没填的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberperiod, operator: NOT_EXISTS, value: ''}
      - query: "私董保健医是哪一期还没登记的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjymemberperiod, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "私董保健医不包含2023年期的客户"
        reason: "排除特定期次值使用NOT_CONTAINS"

  - id: sdbjy_qualified_time_range
    retrieval_text: |-
        私董保健医 私董 保健医 达标时间 达标日期 获得时间 获得日期 拿到时间 什么时候达标 何时达标 哪年达标 什么时候获得 保健医达标 保健医获得 保健医拿到
        保健医达标时间 保健医获得时间 保健医什么时候达标 时间范围 从到 之间 去年 今年 2023年 2024年 2025年 近一周 近一个月 近一年 近期 最近 最近一个月
        本季度 去年 前年 去年二季度 去年下半年 上半年 下半年 大于 小于 之后 之前 以来 至今 一个月内 一年内 一周内 半年内 三个月内 去年6月以后 私董保健医达标时间
    field: sdbjyMemberGradeInfo.sdbjyqualifiedtime
    operator: RANGE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "私董保健医会员达标时间（达标日期），不表示私董保健医期次"
    notes: "达标时间指客户满足会员资格条件的日期，格式yyyy-MM-dd"
    examples:
      - query: "2024年私董保健医达标的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjyqualifiedtime, operator: RANGE, value: {max: '2024-12-31',
    min: '2024-01-01'}}
      - query: "私董保健医近一年达标的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjyqualifiedtime, operator: RANGE, value: {max: '2026-06-11',
    min: '2025-06-11'}}
      - query: "私董保健医去年二季度达标的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjyqualifiedtime, operator: RANGE, value: {max: '2025-06-30',
    min: '2025-04-01'}}
    negative_examples:
      - query: "私董保健医2024年期的客户"
        reason: "2024年期是期次(period)，不是达标时间"

  - id: sdbjy_qualified_time_gt
    retrieval_text: |-
        私董保健医 私董 保健医 达标时间 获得时间 达标日期 大于 之后 以后 之后达标 以后获得 私董保健医|私董|保健医之后达标 私董保健医|私董|保健医以后获得 2023年以后 2024年以后 2025年以后 去年以后
        去年6月以后
    field: sdbjyMemberGradeInfo.sdbjyqualifiedtime
    operator: GT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "私董保健医会员达标时间大于某日期"
    notes: "查询在某日期之后达标的客户"
    examples:
      - query: "2023年以后拿到私董保健医权益的"
        output: {field: sdbjyMemberGradeInfo.sdbjyqualifiedtime, operator: GT, value: '2023-12-31'}
    negative_examples:
      - query: "2024年私董保健医达标的客户"
        reason: "指定年份范围应使用RANGE"

  - id: sdbjy_qualified_time_gte
    retrieval_text: |-
        私董保健医 私董 保健医 达标时间 获得时间 达标日期 大于等于 不小于 及之后 及以上 及以后 至少 私董保健医|私董|保健医及之后达标 私董保健医|私董|保健医及以上 私董保健医|私董|保健医大于等于 2023年及之后
        2024年及以后
    field: sdbjyMemberGradeInfo.sdbjyqualifiedtime
    operator: GTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "私董保健医会员达标时间大于等于某日期"
    notes: "查询在某日期及之后达标的客户"
    examples:
      - query: "2024年及之后私董保健医达标的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjyqualifiedtime, operator: GTE, value: '2024-01-01'}
    negative_examples:
      - query: "2024年私董保健医达标的客户"
        reason: "精确年份范围应使用RANGE"

  - id: sdbjy_qualified_time_lt
    retrieval_text: |-
        私董保健医 私董 保健医 达标时间 获得时间 达标日期 小于 之前 以前 之前达标 以前获得 私董保健医|私董|保健医之前达标 私董保健医|私董|保健医以前获得 2025年以前 25年以前 2024年之前 2023年之前
    field: sdbjyMemberGradeInfo.sdbjyqualifiedtime
    operator: LT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "私董保健医会员达标时间小于某日期"
    notes: "查询在某日期之前达标的客户"
    examples:
      - query: "25年以前获得私董保健医的"
        output: {field: sdbjyMemberGradeInfo.sdbjyqualifiedtime, operator: LT, value: '2025-01-01'}
    negative_examples:
      - query: "2024年之前私董保健医期次"
        reason: "期次使用memberperiod字段，不是qualifiedtime"

  - id: sdbjy_qualified_time_lte
    retrieval_text: |-
        私董保健医 私董 保健医 达标时间 获得时间 达标日期 小于等于 不大于 及之前 及以前 至多 最晚 私董保健医|私董|保健医及之前达标 私董保健医|私董|保健医不大于 私董保健医|私董|保健医小于等于 去年年底前
        2024年底前 2023年底前
    field: sdbjyMemberGradeInfo.sdbjyqualifiedtime
    operator: LTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "私董保健医会员达标时间小于等于某日期"
    notes: "查询在某日期及之前达标的客户"
    examples:
      - query: "去年年底前获得私董保健医的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjyqualifiedtime, operator: LTE, value: '2025-12-31'}
    negative_examples:
      - query: "私董保健医去年达标的客户"
        reason: "整年范围应使用RANGE"

  - id: sdbjy_qualified_time_exists
    retrieval_text: |-
        私董保健医 私董 保健医 达标时间 获得时间 达标日期 拿到时间 有达标时间 有获得时间 有时间 达标时间不为空 获得时间不为空 已达标 已拿到 已获得 已登记达标时间 私董保健医|私董|保健医有达标时间
        私董保健医|私董|保健医获得时间不为空 私董保健医|私董|保健医已达标
    field: sdbjyMemberGradeInfo.sdbjyqualifiedtime
    operator: EXISTS
    value_type: exists
    description: "私董保健医会员达标时间是否有值"
    notes: "仅判断私董保健医是否有达标时间记录"
    examples:
      - query: "有私董保健医达标时间的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjyqualifiedtime, operator: EXISTS, value: ''}
    negative_examples:
      - query: "2024年私董保健医达标的客户"
        reason: "指定了具体达标时间，应使用RANGE"

  - id: sdbjy_qualified_time_not_exists
    retrieval_text: |-
        私董保健医 私董 保健医 达标时间 达标日期 获得时间 获得日期 达标时间为空 获得时间为空 达标时间没值 达标时间没填 没有达标时间 达标时间没记录 达标日期为空 获得时间没记录的 达标时间空着 达标时间还空着
        没有获得时间 无达标时间 无获得时间 获得日期为空 什么时候达标的没记 获得时间没记录的 私董保健医|私董|保健医达标时间为空 私董保健医|私董|保健医获得时间没记录的 私董保健医|私董|保健医达标时间还空着
        私董保健医|私董|保健医没有达标时间
    field: sdbjyMemberGradeInfo.sdbjyqualifiedtime
    operator: NOT_EXISTS
    value_type: exists
    description: "私董保健医会员达标时间是否为空"
    notes: "查询私董保健医达标时间未记录的客户"
    examples:
      - query: "私董保健医达标时间为空的客户"
        output: {field: sdbjyMemberGradeInfo.sdbjyqualifiedtime, operator: NOT_EXISTS, value: ''}
      - query: "私董保健医获得时间没记录的"
        output: {field: sdbjyMemberGradeInfo.sdbjyqualifiedtime, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "私董保健医还没有达标的客户"
        reason: "可能是查询达标状态(status)而非达标时间"

  - id: gdky_member_product_match
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 服务线 服务线名称 产品线 会员服务 权益 开通了高端康养|康养|平安康养 购买了高端康养|康养|平安康养 买了高端康养|康养|平安康养 享有高端康养|康养|平安康养
        已有高端康养|康养|平安康养 有高端康养|康养|平安康养权益的 高端康养|康养|平安康养客户 高端康养|康养|平安康养会员 高端康养|康养|平安康养的客户 开通高端康养|康养|平安康养服务的 有高端康养|康养|平安康养权益
        包含高端康养|康养|平安康养 有高端康养|康养|平安康养服务线 有高端康养|康养|平安康养的 获得高端康养|康养|平安康养的客户 拿到高端康养|康养|平安康养的 有高端康养|康养|平安康养吗 是不是高端康养|康养|平安康养
        怎么查高端康养|康养|平安康养 有高端康养|康养|平安康养权益的客户
    field: gdkyMemberGradeInfo.gdkymemberproductname
    operator: MATCH
    value_type: enum
    enum_ref: gdkyMemberGradeInfo.gdkymemberproductname
    description: "高端康养会员服务线名称，不表示其他服务线"
    notes: "枚举值「高端康养」；有该服务线即表示客户开通了高端康养会员服务"
    examples:
      - query: "服务线为高端康养客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberproductname, operator: MATCH, value: 高端康养}
    negative_examples:
      - query: "高端康养达标的客户"
        reason: "达标是会员状态(status)，不是服务线"

  - id: gdky_member_product_contains
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 服务线 会员服务 权益 也开通了 同时有 还有 既有 也有 和 或 或者 包含高端康养|康养|平安康养 有高端康养|康养|平安康养和 高端康养|康养|平安康养都有
        高端康养|康养|平安康养以及 多种权益 多个服务线
    field: gdkyMemberGradeInfo.gdkymemberproductname
    operator: CONTAINS
    value_type: enum
    enum_ref: gdkyMemberGradeInfo.gdkymemberproductname
    description: "高端康养会员服务线名称，用于多服务线组合查询"
    notes: "查询同时拥有多个服务线的客户时使用CONTAINS"
    examples:
      - query: "有高端康养也有安有护的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberproductname, operator: CONTAINS, value: [高端康养,
    安有护]}
    negative_examples:
      - query: "只有高端康养的客户"
        reason: "单一服务线查询应为MATCH"

  - id: gdky_member_product_not_contains
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 服务线 会员服务 权益 没有高端康养|康养|平安康养 不是高端康养|康养|平安康养 不包含高端康养|康养|平安康养 不含高端康养|康养|平安康养 排除高端康养|康养|平安康养
        不要高端康养|康养|平安康养 无高端康养|康养|平安康养 没高端康养|康养|平安康养 非高端康养|康养|平安康养 除了高端康养|康养|平安康养之外 高端康养|康养|平安康养除外 去掉高端康养|康养|平安康养
        但没有高端康养|康养|平安康养
    field: gdkyMemberGradeInfo.gdkymemberproductname
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: gdkyMemberGradeInfo.gdkymemberproductname
    description: "高端康养会员服务线名称，用于排除查询"
    notes: "排除高端康养服务线的客户时使用NOT_CONTAINS"
    examples:
      - query: "没有高端康养服务线的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberproductname, operator: NOT_CONTAINS, value: 高端康养}
      - query: "有安有护但没有高端康养的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberproductname, operator: NOT_CONTAINS, value: 高端康养}
    negative_examples:
      - query: "有高端康养的客户"
        reason: "正向匹配应使用MATCH"

  - id: gdky_member_product_exists
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 服务线 会员服务 权益 开通高端康养|康养|平安康养了吗 是否有高端康养|康养|平安康养 有没有高端康养|康养|平安康养服务线 获得高端康养|康养|平安康养的客户
        拿到高端康养|康养|平安康养的 有高端康养|康养|平安康养会员 高端康养|康养|平安康养服务线不为空 有高端康养|康养|平安康养服务线 有高端康养|康养|平安康养权益
    field: gdkyMemberGradeInfo.gdkymemberproductname
    operator: EXISTS
    value_type: exists
    description: "高端康养会员服务线是否有值"
    notes: "仅判断高端康养服务线是否有记录，不关心具体值；权益潜客在解析阶段使用memberstatus，最终由系统后处理生成本条件。"
    examples:
      - query: "有高端康养权益的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberproductname, operator: EXISTS, value: ''}
      - query: "开通了高端康养的客户"
        output: { field: gdkyMemberGradeInfo.gdkymemberproductname, operator: EXISTS, value: '' }
    negative_examples:
      - query: "高端康养客户"
        reason: "指定了具体服务线值，应使用MATCH"

  - id: gdky_member_product_not_exists
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 服务线 会员服务 权益 高端康养|康养|平安康养服务线为空 高端康养|康养|平安康养权益为空 高端康养|康养|平安康养服务线没值 高端康养|康养|平安康养没有记录
        没有高端康养|康养|平安康养服务线 没有高端康养|康养|平安康养权益 没有高端康养|康养|平安康养会员 还没开通高端康养|康养|平安康养 没拿到高端康养|康养|平安康养 无高端康养|康养|平安康养服务线
        无高端康养|康养|平安康养权益 高端康养|康养|平安康养为空 所有会员权益都没标的 权益都没标
    field: gdkyMemberGradeInfo.gdkymemberproductname
    operator: NOT_EXISTS
    value_type: exists
    description: "高端康养会员服务线是否为空"
    notes: "查询没有高端康养服务线记录的客户"
    examples:
      - query: "没有高端康养权益的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberproductname, operator: NOT_EXISTS, value: ''}
      - query: "高端康养权益为空的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberproductname, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不是高端康养的客户"
        reason: "可能是排除特定值而非判断字段是否存在"

  - id: gdky_member_grade_match
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员等级 等级 版本 级别 档次 逸享会员 逸享PLUS会员 颐享家会员 臻享V1会员 臻享V2会员 逸享会员 逸享PLUS会员 颐享家会员 臻享V1会员 臻享V2会员 康养逸享
        康养逸享PLUS 康养颐享家 康养臻享V1 康养臻享V2 高端康养逸享会员 高端康养臻享V2 康养逸享会员 康养PLUS 康养臻享V1 最高等级 最高版本 最好等级 最好版本 顶级 最低等级 最低版本
        高端康养|康养|平安康养等级 高端康养|康养|平安康养版本 高端康养|康养|平安康养什么等级 高端康养|康养|平安康养哪个版本 高端康养|康养|平安康养是什么级别 包含 不包含 有等级 无等级 等级为空 等级不为空
        高端康养|康养|平安康养有等级吗
    field: gdkyMemberGradeInfo.gdkymembergradesearch
    operator: MATCH
    value_type: enum
    enum_ref: gdkyMemberGradeInfo.gdkymembergradesearch
    enum_ordered: true
    description: "高端康养会员等级或版本，不表示高端康养达标状态"
    notes: "枚举值共5个：逸享会员、逸享PLUS会员、颐享家会员、臻享V1会员、臻享V2会员；排序：逸享会员 < 逸享PLUS会员 < 颐享家会员 < 臻享V1会员 < 臻享V2会员；以上/及以上/以下/及以下包含边界"
    examples:
      - query: "高端康养逸享会员的客户"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: MATCH, value: 逸享会员}
      - query: "高端康养等级是臻享V2会员的客户"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: MATCH, value: 臻享V2会员}
      - query: "高端康养最高等级的客户"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: MATCH, value: 臻享V2会员}
    negative_examples:
      - query: "高端康养达标的客户"
        reason: "达标是会员状态(status)，不是等级(grade)"

  - id: gdky_member_grade_contains
    retrieval_text: >
      高端康养 康养 平安康养 会员等级 等级 版本 级别
      逸享会员 逸享PLUS会员 颐享家会员 臻享V1会员 臻享V2会员 康养逸享 康养逸享PLUS 康养颐享家 康养臻享V1 康养臻享V2
      或者 或 和 及 与 都要 都查 都查一下 都可以 多个等级 多个版本
      以上 及以上 以下 及以下 高于 大于 超过 低于 小于 不足 不到
      逸享以上 逸享及以上 颐享家以下 颐享家及以下 高于逸享 低于颐享家
      高端康养PLUS会员及以上 颐享家以上的康养客户 臻享V1以下的 康养PLUS以上
    field: gdkyMemberGradeInfo.gdkymembergradesearch
    operator: CONTAINS
    value_type: enum
    enum_ref: gdkyMemberGradeInfo.gdkymembergradesearch
    enum_ordered: true
    description: "高端康养会员等级多值查询与范围比较；“以上”、”及以上”、”以下”、”及以下”含边界"
    notes: "排序：逸享会员<逸享PLUS会员<颐享家会员<臻享V1会员<臻享V2会员。逸享会员以上和及以上=含逸享会员即全部5个；颐享家会员以下和及以下=含颐享家会员即逸享会员/逸享PLUS会员/颐享家会员"
    examples:
      - query: "逸享会员或者颐享家会员"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: CONTAINS, value: [逸享会员, 颐享家会员]}
      - query: "康养逸享以上的客户"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: CONTAINS, value: [逸享会员, 逸享PLUS会员, 颐享家会员, 臻享V1会员, 臻享V2会员]}
      - query: "康养逸享及以上的客户"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: CONTAINS, value: [逸享会员, 逸享PLUS会员, 颐享家会员, 臻享V1会员, 臻享V2会员]}
      - query: "康养颐享家以下的客户"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: CONTAINS, value: [逸享会员, 逸享PLUS会员, 颐享家会员]}
      - query: "康养颐享家及以下的客户"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: CONTAINS, value: [逸享会员, 逸享PLUS会员, 颐享家会员]}
    negative_examples:
      - query: "康养逸享会员客户"
        reason: "单一等级精确匹配应使用MATCH"

  - id: gdky_member_grade_not_contains
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员等级 等级 版本 逸享会员 逸享PLUS会员 颐享家会员 臻享V1会员 臻享V2会员 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 高端康养|康养|平安康养不要
        高端康养|康养|平安康养排除 高端康养|康养|平安康养不是 高端康养|康养|平安康养不包含
    field: gdkyMemberGradeInfo.gdkymembergradesearch
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: gdkyMemberGradeInfo.gdkymembergradesearch
    description: "高端康养会员等级排除查询"
    notes: "排除某个高端康养等级时使用NOT_CONTAINS"
    examples:
      - query: "不要逸享会员的高端康养客户"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: NOT_CONTAINS, value: 逸享会员}
    negative_examples:
      - query: "高端康养逸享会员的客户"
        reason: "正向匹配应使用MATCH"

  - id: gdky_member_grade_exists
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员等级 等级 版本 有等级 有版本 有等级吗 有没有等级 是否有等级 等级不为空 等级已定 等级已填 已定级 高端康养|康养|平安康养有等级 高端康养|康养|平安康养有版本
        高端康养|康养|平安康养已定级 高端康养|康养|平安康养等级不为空
    field: gdkyMemberGradeInfo.gdkymembergradesearch
    operator: EXISTS
    value_type: exists
    description: "高端康养会员等级是否有值"
    notes: "仅判断高端康养是否有等级记录，不关心具体等级值"
    examples:
      - query: "有高端康养等级的客户"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: EXISTS, value: ''}
    negative_examples:
      - query: "高端康养逸享会员的客户"
        reason: "指定了具体等级值，应使用MATCH"

  - id: gdky_member_grade_not_exists
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员等级 等级 版本 等级为空 等级没值 等级没填 等级没定 还没定级 没有等级 无等级 等级没登记 等级还没定的 没等级 高端康养|康养|平安康养等级为空 高端康养|康养|平安康养没等级
        高端康养|康养|平安康养等级还没定的 高端康养|康养|平安康养等级没登记的
    field: gdkyMemberGradeInfo.gdkymembergradesearch
    operator: NOT_EXISTS
    value_type: exists
    description: "高端康养会员等级是否为空"
    notes: "查询高端康养等级未登记或未填写的客户"
    examples:
      - query: "高端康养等级还没定的客户"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: NOT_EXISTS, value: ''}
      - query: "没有高端康养等级的客户"
        output: {field: gdkyMemberGradeInfo.gdkymembergradesearch, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要高端康养逸享会员的客户"
        reason: "排除特定等级值使用NOT_CONTAINS"

  - id: gdky_member_status_match
    enum_requires_anchor: true
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员类型 会员状态 类型 状态 是什么状态 什么状态 什么类型 哪种状态 预达标 潜客 意向 达标 高端康养|康养|平安康养状态 高端康养|康养|平安康养类型
        高端康养|康养|平安康养会员类型 高端康养|康养|平安康养的状态 高端康养|康养|平安康养是什么状态 高端康养|康养|平安康养会员状态 包含 不包含 有状态 无状态 状态为空 状态不为空
    field: gdkyMemberGradeInfo.gdkymemberstatus
    operator: MATCH
    value_type: enum
    enum_ref: gdkyMemberGradeInfo.gdkymemberstatus
    description: "高端康养会员类型或状态，不表示高端康养等级版本"
    notes: "枚举值共4个：预达标、潜客、意向、达标；状态互斥，一个客户同一时间只能属于一种状态"
    examples:
      - query: "康养潜客"
        output: {field: gdkyMemberGradeInfo.gdkymemberstatus, operator: MATCH, value: 潜客}
      - query: "高端康养预达标的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberstatus, operator: MATCH, value: 预达标}
      - query: "高端康养是达标客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberstatus, operator: MATCH, value: 达标}
    negative_examples:
      - query: "高端康养逸享会员的客户"
        reason: "逸享会员是等级(grade)，不是状态(status)"

  - id: gdky_member_status_contains
    enum_requires_anchor: true
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员类型 会员状态 类型 状态 预达标 潜客 意向 达标 临界 临界客户 包含 含有 或者 或 和 都要 都查 高端康养|康养|平安康养或者 高端康养|康养|平安康养或 高端康养|康养|平安康养以及
        高端康养|康养|平安康养和
    field: gdkyMemberGradeInfo.gdkymemberstatus
    operator: CONTAINS
    value_type: enum
    enum_ref: gdkyMemberGradeInfo.gdkymemberstatus
    description: "高端康养会员类型多值查询"
    notes: "查询多种高端康养状态时使用CONTAINS；临界客户=潜客或意向"
    examples:
      - query: "高端康养预达标或者达标客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberstatus, operator: CONTAINS, value: [预达标, 达标]}
    negative_examples:
      - query: "高端康养预达标客户"
        reason: "单一状态查询应为MATCH"

  - id: gdky_member_status_not_contains
    enum_requires_anchor: true
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员类型 会员状态 类型 状态 预达标 潜客 意向 达标 不包含 不含 不要 排除 去除 去掉 除了 之外 除外 不是 没有 高端康养|康养|平安康养不要 高端康养|康养|平安康养排除
        高端康养|康养|平安康养不包含
    field: gdkyMemberGradeInfo.gdkymemberstatus
    operator: NOT_CONTAINS
    value_type: enum
    enum_ref: gdkyMemberGradeInfo.gdkymemberstatus
    description: "高端康养会员类型排除查询"
    notes: "排除某种高端康养状态时使用NOT_CONTAINS"
    examples:
      - query: "高端康养不要预达标客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberstatus, operator: NOT_CONTAINS, value: 预达标}
    negative_examples:
      - query: "高端康养预达标客户"
        reason: "正向匹配应使用MATCH"

  - id: gdky_member_status_exists
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员类型 会员状态 类型 状态 有状态 有类型 有会员状态 有会员类型 状态不为空 类型不为空 状态已标 状态已登记 已有状态 高端康养|康养|平安康养有状态
        高端康养|康养|平安康养状态不为空 高端康养|康养|平安康养状态已填
    field: gdkyMemberGradeInfo.gdkymemberstatus
    operator: EXISTS
    value_type: exists
    description: "高端康养会员类型是否有值"
    notes: "仅判断高端康养是否有状态记录，不关心具体状态值"
    examples:
      - query: "有高端康养状态的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberstatus, operator: EXISTS, value: ''}
    negative_examples:
      - query: "高端康养预达标客户"
        reason: "指定了具体状态值，应使用MATCH"

  - id: gdky_member_status_not_exists
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员类型 会员状态 类型 状态 状态为空 类型为空 没有状态 无状态 状态没标 状态没填 会员状态没标的 状态还没登记 状态没值 高端康养|康养|平安康养状态为空
        高端康养|康养|平安康养状态没标的 高端康养|康养|平安康养没状态 高端康养|康养|平安康养状态还没登记的
    field: gdkyMemberGradeInfo.gdkymemberstatus
    operator: NOT_EXISTS
    value_type: exists
    description: "高端康养会员类型是否为空"
    notes: "查询高端康养状态未登记的客户"
    examples:
      - query: "高端康养会员状态没标的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberstatus, operator: NOT_EXISTS, value: ''}
      - query: "没有高端康养状态的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberstatus, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "不要高端康养预达标客户"
        reason: "排除特定状态值使用NOT_CONTAINS"

  - id: gdky_member_period_match
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员期次 期次 会员年度 年度 哪一期 什么期次 哪个年度 M2023 M2024 M2025 M年份 包含2023年期 包含2024年期的 包含2025年期的 2023年那期
        2024年那期 23年那期 24年那期 高端康养|康养|平安康养2023年 高端康养|康养|平安康养2024年 高端康养|康养|平安康养2025年 高端康养|康养|平安康养期次 高端康养|康养|平安康养年度
        高端康养|康养|平安康养哪一期 高端康养|康养|平安康养哪个年度 是哪一期 哪年那期 2024年那一期 2025年那一期 有期次 无期次 期次为空 期次不为空
    field: gdkyMemberGradeInfo.gdkymemberperiod
    operator: MATCH
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "高端康养会员期次（年度），不表示高端康养达标时间"
    notes: "期次为年份格式YYYY，如2023、2024、2025；一个客户可能拥有多个年度的期次记录"
    examples:
      - query: "高端康养2024年期的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberperiod, operator: MATCH, value: '2024'}
      - query: "23年那期高端康养"
        output: {field: gdkyMemberGradeInfo.gdkymemberperiod, operator: MATCH, value: '2023'}
    negative_examples:
      - query: "2024年达标的高端康养客户"
        reason: "2024年是达标时间(qualifiedtime)，不是期次(period)"

  - id: gdky_member_period_contains
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员期次 期次 年度 包含 含有 包括 有 都有 和 及 与 以及 包含2023年期 包含2024年期的 包含2025年期的 高端康养|康养|平安康养2023到2025
        高端康养|康养|平安康养2023至2025 2023和2024年期 多个期次 几个年度
    field: gdkyMemberGradeInfo.gdkymemberperiod
    operator: CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "高端康养会员期次多值查询"
    notes: "查询包含多个期次时使用CONTAINS"
    examples:
      - query: "高端康养包含2023年期和2024年期的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberperiod, operator: CONTAINS, value: ['2023',
    '2024']}
    negative_examples:
      - query: "高端康养2024年期的客户"
        reason: "单一年份应使用MATCH"

  - id: gdky_member_period_not_contains
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员期次 期次 年度 不包含 不含 不要 排除 去除 没有 不包含2023年期 不包含2024年期 不包含2025年期 高端康养|康养|平安康养不包含 高端康养|康养|平安康养不含
        高端康养|康养|平安康养不要
    field: gdkyMemberGradeInfo.gdkymemberperiod
    operator: NOT_CONTAINS
    value_type: extract
    format: "格式：YYYY，例如：2023"
    description: "高端康养会员期次排除查询"
    notes: "排除某些期次时使用NOT_CONTAINS"
    examples:
      - query: "高端康养不包含2023年期的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberperiod, operator: NOT_CONTAINS, value: '2023'}
    negative_examples:
      - query: "高端康养包含2023年期的客户"
        reason: "正向匹配应使用MATCH或CONTAINS"

  - id: gdky_member_period_exists
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员期次 期次 年度 有期次 有年度 有期次吗 有没有期次 是否有期次 期次不为空 期次已登记 期次已填 已登记期次 高端康养|康养|平安康养有期次 高端康养|康养|平安康养期次不为空
        高端康养|康养|平安康养期次已填
    field: gdkyMemberGradeInfo.gdkymemberperiod
    operator: EXISTS
    value_type: exists
    description: "高端康养会员期次是否有值"
    notes: "仅判断高端康养是否有期次记录，不关心具体年份"
    examples:
      - query: "有高端康养期次的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberperiod, operator: EXISTS, value: ''}
    negative_examples:
      - query: "高端康养2024年期的客户"
        reason: "指定了具体年份值，应使用MATCH"

  - id: gdky_member_period_not_exists
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 会员期次 期次 年度 期次为空 期次没值 期次没填 没有期次 无期次 期次没登记 期次还没登记 没填期次 哪一期没登记 哪一期还没登记 权益期次没有的 期次没填的
        高端康养|康养|平安康养期次为空 高端康养|康养|平安康养期次没填的 高端康养|康养|平安康养没有期次 高端康养|康养|平安康养哪一期没登记 高端康养|康养|平安康养期次没登记
    field: gdkyMemberGradeInfo.gdkymemberperiod
    operator: NOT_EXISTS
    value_type: exists
    description: "高端康养会员期次是否为空"
    notes: "查询高端康养期次未登记的客户"
    examples:
      - query: "高端康养期次没填的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberperiod, operator: NOT_EXISTS, value: ''}
      - query: "高端康养是哪一期还没登记的客户"
        output: {field: gdkyMemberGradeInfo.gdkymemberperiod, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "高端康养不包含2023年期的客户"
        reason: "排除特定期次值使用NOT_CONTAINS"

  - id: gdky_qualified_time_range
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 达标时间 达标日期 获得时间 获得日期 拿到时间 新获得 新拿到 新增权益 新增会员 刚获得 什么时候达标 何时达标 哪年达标 什么时候获得 平安康养达标 平安康养获得 平安康养拿到
        平安康养达标时间 平安康养获得时间 平安康养什么时候达标 时间范围 从到 之间 去年 今年 2023年 2024年 2025年 近一周 近一个月 近一年 近期 最近 最近一个月 高端康养达标时间
        本季度 去年 前年 去年二季度 去年下半年 上半年 下半年 一个月内 一年内 一周内 半年内 三个月内 去年6月以后 最近一个月新获得高端康养权益 最近一个月新增康养会员
    field: gdkyMemberGradeInfo.gdkyqualifiedtime
    operator: RANGE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "高端康养会员达标时间（达标日期）；“新获得/新拿到/新增/刚获得高端康养权益”均按达标时间判断，不表示高端康养期次"
    notes: "业务口径：当“新获得、新拿到、新增、刚获得”等权益获得语义与时间范围同时出现时，时间条件必须作用于本字段；“最近一个月新获得高端康养权益”指高端康养达标时间落在最近一个月内。查询“新获得居家或者高端康养权益”时，本字段与平安居家达标时间字段使用OR关系。不得按权益领取时间、服务使用时间、记录创建时间或更新时间判断。格式yyyy-MM-dd"
    examples:
      - query: "2024年高端康养达标的客户"
        output: {field: gdkyMemberGradeInfo.gdkyqualifiedtime, operator: RANGE, value: {max: '2024-12-31',
    min: '2024-01-01'}}
      - query: "高端康养近一年达标的客户"
        output: {field: gdkyMemberGradeInfo.gdkyqualifiedtime, operator: RANGE, value: {max: '2026-06-11',
    min: '2025-06-11'}}
      - query: "高端康养去年二季度达标的客户"
        output: {field: gdkyMemberGradeInfo.gdkyqualifiedtime, operator: RANGE, value: {max: '2025-06-30',
    min: '2025-04-01'}}
      - query: "最近一个月新获得居家或者高端康养权益的客户"
        output: {query_logic: OR, conditions: [{field: pajjMemberGradeInfo.pajjqualifiedtime, operator: RANGE,
              value: {min: '2026-05-11', max: '2026-06-11'}}, {field: gdkyMemberGradeInfo.gdkyqualifiedtime,
              operator: RANGE, value: {min: '2026-05-11', max: '2026-06-11'}}]}
    negative_examples:
      - query: "高端康养2024年期的客户"
        reason: "2024年期是期次(period)，不是达标时间"
      - query: "最近一个月使用过高端康养服务的客户"
        reason: "这是服务使用时间，不是高端康养权益达标时间"
      - query: "最近一个月更新过高端康养权益记录的客户"
        reason: "这是记录更新时间，不是高端康养权益达标时间"

  - id: gdky_qualified_time_gt
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 达标时间 获得时间 达标日期 大于 之后 以后 之后达标 以后获得 高端康养|康养|平安康养之后达标 高端康养|康养|平安康养以后获得 2023年以后 2024年以后 2025年以后
        去年以后 去年6月以后
    field: gdkyMemberGradeInfo.gdkyqualifiedtime
    operator: GT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "高端康养会员达标时间大于某日期"
    notes: "查询在某日期之后达标的客户"
    examples:
      - query: "2023年以后拿到高端康养权益的"
        output: {field: gdkyMemberGradeInfo.gdkyqualifiedtime, operator: GT, value: '2023-12-31'}
    negative_examples:
      - query: "2024年高端康养达标的客户"
        reason: "指定年份范围应使用RANGE"

  - id: gdky_qualified_time_gte
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 达标时间 获得时间 达标日期 大于等于 不小于 及之后 及以上 及以后 至少 高端康养|康养|平安康养及之后达标 高端康养|康养|平安康养及以上 高端康养|康养|平安康养大于等于
        2023年及之后 2024年及以后
    field: gdkyMemberGradeInfo.gdkyqualifiedtime
    operator: GTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "高端康养会员达标时间大于等于某日期"
    notes: "查询在某日期及之后达标的客户"
    examples:
      - query: "2024年及之后高端康养达标的客户"
        output: {field: gdkyMemberGradeInfo.gdkyqualifiedtime, operator: GTE, value: '2024-01-01'}
    negative_examples:
      - query: "2024年高端康养达标的客户"
        reason: "精确年份范围应使用RANGE"

  - id: gdky_qualified_time_lt
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 达标时间 获得时间 达标日期 小于 之前 以前 之前达标 以前获得 高端康养|康养|平安康养之前达标 高端康养|康养|平安康养以前获得 2025年以前 25年以前 2024年之前
        2023年之前
    field: gdkyMemberGradeInfo.gdkyqualifiedtime
    operator: LT
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "高端康养会员达标时间小于某日期"
    notes: "查询在某日期之前达标的客户"
    examples:
      - query: "25年以前获得高端康养的"
        output: {field: gdkyMemberGradeInfo.gdkyqualifiedtime, operator: LT, value: '2025-01-01'}
    negative_examples:
      - query: "2024年之前高端康养期次"
        reason: "期次使用memberperiod字段，不是qualifiedtime"

  - id: gdky_qualified_time_lte
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 达标时间 获得时间 达标日期 小于等于 不大于 及之前 及以前 至多 最晚 高端康养|康养|平安康养及之前达标 高端康养|康养|平安康养不大于 高端康养|康养|平安康养小于等于 去年年底前
        2024年底前 2023年底前
    field: gdkyMemberGradeInfo.gdkyqualifiedtime
    operator: LTE
    value_type: date
    format: "格式：yyyy-MM-dd"
    description: "高端康养会员达标时间小于等于某日期"
    notes: "查询在某日期及之前达标的客户"
    examples:
      - query: "去年年底前获得高端康养的客户"
        output: {field: gdkyMemberGradeInfo.gdkyqualifiedtime, operator: LTE, value: '2025-12-31'}
    negative_examples:
      - query: "高端康养去年达标的客户"
        reason: "整年范围应使用RANGE"

  - id: gdky_qualified_time_exists
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 达标时间 获得时间 达标日期 拿到时间 有达标时间 有获得时间 有时间 达标时间不为空 获得时间不为空 已达标 已拿到 已获得 已登记达标时间 高端康养|康养|平安康养有达标时间
        高端康养|康养|平安康养获得时间不为空 高端康养|康养|平安康养已达标
    field: gdkyMemberGradeInfo.gdkyqualifiedtime
    operator: EXISTS
    value_type: exists
    description: "高端康养会员达标时间是否有值"
    notes: "仅判断高端康养是否有达标时间记录"
    examples:
      - query: "有高端康养达标时间的客户"
        output: {field: gdkyMemberGradeInfo.gdkyqualifiedtime, operator: EXISTS, value: ''}
    negative_examples:
      - query: "2024年高端康养达标的客户"
        reason: "指定了具体达标时间，应使用RANGE"

  - id: gdky_qualified_time_not_exists
    retrieval_text: |-
        高端康养 康养 平安康养 康养服务 达标时间 达标日期 获得时间 获得日期 达标时间为空 获得时间为空 达标时间没值 达标时间没填 没有达标时间 达标时间没记录 达标日期为空 获得时间没记录的 达标时间空着 达标时间还空着
        没有获得时间 无达标时间 无获得时间 获得日期为空 什么时候达标的没记 获得时间没记录的 高端康养|康养|平安康养达标时间为空 高端康养|康养|平安康养获得时间没记录的 高端康养|康养|平安康养达标时间还空着
        高端康养|康养|平安康养没有达标时间
    field: gdkyMemberGradeInfo.gdkyqualifiedtime
    operator: NOT_EXISTS
    value_type: exists
    description: "高端康养会员达标时间是否为空"
    notes: "查询高端康养达标时间未记录的客户"
    examples:
      - query: "高端康养达标时间为空的客户"
        output: {field: gdkyMemberGradeInfo.gdkyqualifiedtime, operator: NOT_EXISTS, value: ''}
      - query: "高端康养获得时间没记录的"
        output: {field: gdkyMemberGradeInfo.gdkyqualifiedtime, operator: NOT_EXISTS, value: ''}
    negative_examples:
      - query: "高端康养还没有达标的客户"
        reason: "可能是查询达标状态(status)而非达标时间"

  # ==================== 地址查询（新增） ====================

  - id: contact_address_match
    retrieval_text: >
      联系地址 通讯地址 通信地址 联系地址是 通讯地址是 通信地址是 客户联系地址 客户通讯地址
    field: CONTACT_ADDRESS_FIELD
    operator: MATCH
    value_type: extract
    is_supported: true
    description: "客户联系（通讯）地址字段。仅表示客户本人的联系地址。"
    examples:
      - query: "联系地址是幸福花园"
        output: {field: CONTACT_ADDRESS_FIELD, operator: MATCH, value: "幸福花园"}
      - query: "通讯地址为南京西路"
        output: {field: CONTACT_ADDRESS_FIELD, operator: MATCH, value: "南京西路"}
    negative_examples:
      - query: "家庭地址是幸福花园"
        reason: "明确说明家庭地址，应映射到 FAMILY_ADDRESS_FIELD"
      - query: "投保人联系地址"
        reason: "投保人地址不是客户本人联系地址"

  - id: any_address_match
    retrieval_text: >
      地址 居住地址 住址 地址是 地址为 居住地址是 居住地址为 居住地址在 居住地址位于 住址是 住址为 住址在 住址位于 住在 家住 家在 居住在 定居在 现居 裸地址 村 路 街 区 县 社区 小区
    field: ANY_ADDRESS_FIELD
    operator: MATCH
    value_type: extract
    is_supported: true
    description: "用户未明确说明联系地址或家庭地址时，同时查询两类地址。居住地址、普通地址、住址、住在、家住、家在和裸地址均属于未指定地址类型。"
    notes: "只有原文明确出现联系地址/通讯地址/通信地址时使用 CONTACT_ADDRESS_FIELD；只有原文明确出现家庭地址/家庭住址时使用 FAMILY_ADDRESS_FIELD；居住地址及其他地址表达使用 ANY_ADDRESS_FIELD。"
    examples:
      - query: "住址是某区的客户"
        output: {field: ANY_ADDRESS_FIELD, operator: MATCH, value: "某区"}
      - query: "家住某路的客户"
        output: {field: ANY_ADDRESS_FIELD, operator: MATCH, value: "某路"}
      - query: "居住地址为星河公寓"
        output: {field: ANY_ADDRESS_FIELD, operator: MATCH, value: "星河公寓"}
      - query: "某村客户"
        output: {field: ANY_ADDRESS_FIELD, operator: MATCH, value: "某村"}
    negative_examples:
      - query: "家庭住址是幸福花园"
        reason: "明确说明家庭住址，应映射到 FAMILY_ADDRESS_FIELD"
      - query: "通讯地址为南京西路"
        reason: "明确说明通讯地址，应映射到 CONTACT_ADDRESS_FIELD"

  - id: family_address_match
    retrieval_text: >
      家庭地址 家庭住址 家庭地址是 家庭住址是 家庭地址为 家庭住址为 客户家庭地址 客户家庭住址
    field: FAMILY_ADDRESS_FIELD
    operator: MATCH
    value_type: extract
    is_supported: true
    description: "客户家庭地址字段。只有原文明确出现家庭地址或家庭住址时使用。"
    examples:
      - query: "家庭地址是幸福花园"
        output: {field: FAMILY_ADDRESS_FIELD, operator: MATCH, value: "幸福花园"}
    negative_examples:
      - query: "联系地址是幸福花园"
        reason: "明确说明联系地址，应映射到 CONTACT_ADDRESS_FIELD"
      - query: "家庭成员住在南京西路"
        reason: "这是家庭成员地址，不是客户本人家庭地址"
      - query: "居住地址包含张江路"
        reason: "居住地址未明确是家庭地址，应映射到 ANY_ADDRESS_FIELD"

  - id: any_address_radius
    retrieval_text: >
      地址附近 居住地址附近 住址附近 住在附近 家住附近 地点附近 地点周边 地点周围 公里内 米内 公里以内 范围内 千米内 当前位置 我的位置 附近 我周围 方圆 周边 周围 距离以内
    field: ANY_ADDRESS_FIELD
    operator: GEO_RADIUS
    value_type: geo_radius
    is_supported: true
    description: "未明确地址类型时，同时对联系地址和家庭地址执行空间距离查询；地点附近、周边、周围未提供距离时默认按5公里范围内查询。"
    notes: "居住地址、普通地址、住址、住在、家住不指定地址类型，必须使用 ANY_ADDRESS_FIELD。GEO value 只保留地点实体，不包含地址、住址、住在、家住、搜索、查询、在等字段词和动作词。"
    examples:
      - query: "幸福花园3公里内"
        output: {field: ANY_ADDRESS_FIELD, operator: GEO_RADIUS, value: {place_name: "幸福花园", is_current_location: false, distance: 3, unit: "km"}}
      - query: "在某大街附近的客户"
        output: {field: ANY_ADDRESS_FIELD, operator: GEO_RADIUS, value: {place_name: "某大街", is_current_location: false, distance: 5, unit: "km"}}
      - query: "地址是某医院附近的客户"
        output: {field: ANY_ADDRESS_FIELD, operator: GEO_RADIUS, value: {place_name: "某医院", is_current_location: false, distance: 5, unit: "km"}}
      - query: "居住地址在某公园周边"
        output: {field: ANY_ADDRESS_FIELD, operator: GEO_RADIUS, value: {place_name: "某公园", is_current_location: false, distance: 5, unit: "km"}}
    negative_examples:
      - query: "幸福花园"
        reason: "无距离范围关键词，不是GEO查询，是裸地址查询"

  - id: any_address_not_radius
    retrieval_text: >
      公里外 米外 公里以外 范围外 千米外 距离以外 当前位置以外
    field: ANY_ADDRESS_FIELD
    operator: NOT_GEO_RADIUS
    value_type: geo_radius
    is_supported: true
    description: "未明确地址类型时，同时对联系地址和家庭地址执行空间距离范围外查询。"
    examples:
      - query: "当前位置5公里外"
        output: {field: ANY_ADDRESS_FIELD, operator: NOT_GEO_RADIUS, value: {place_name: null, is_current_location: true, distance: 5, unit: "km"}}

  - id: contact_address_radius
    retrieval_text: >
      联系地址 通讯地址 通信地址 公里内 公里外 米内 米外 范围内 范围外 附近 周边 距离
    field: CONTACT_ADDRESS_FIELD
    operator: GEO_RADIUS
    value_type: geo_radius
    is_supported: true
    description: "用户明确对联系地址、通讯地址或通信地址执行空间距离查询。"
    examples:
      - query: "联系地址在幸福花园3公里内"
        output: {field: CONTACT_ADDRESS_FIELD, operator: GEO_RADIUS, value: {place_name: "幸福花园", is_current_location: false, distance: 3, unit: "km"}}

  - id: family_address_radius
    retrieval_text: >
      家庭地址 家庭住址 公里内 公里外 米内 米外 范围内 范围外 附近 周边 距离
    field: FAMILY_ADDRESS_FIELD
    operator: GEO_RADIUS
    value_type: geo_radius
    is_supported: true
    description: "用户明确对家庭地址或家庭住址执行空间距离查询。居住地址、普通住址、住在、家住未明确地址类型，应使用 ANY_ADDRESS_FIELD。"
    examples:
      - query: "家庭地址在幸福花园3公里内"
        output: {field: FAMILY_ADDRESS_FIELD, operator: GEO_RADIUS, value: {place_name: "幸福花园", is_current_location: false, distance: 3, unit: "km"}}
