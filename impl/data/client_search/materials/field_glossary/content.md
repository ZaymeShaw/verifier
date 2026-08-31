# client_search 字段口径表（按字段聚合）

来源：field_definitions_args.yaml（business repo revision 46296be50e9c），共 417 条意图定义聚合为 133 个字段。枚举值仅列样例，全量以 authority 工具按需查询为准。

## searchClientName
- 含义：仅表示客户本人的人名；不表示客户集合、公司/机构名称、地址、产品名，也不表示家庭成员、被保人或投保人姓名
- operators：MATCH, CONTAINS
- value_types：extract

## customerReview
- 含义：表示代理人的盘客业务动作或盘客月份，不表示客户添加日、联系日期或保单日期；当前暂不支持作为客户搜索条件
- operators：MATCH
- value_types：static

## customerActivity
- 含义：表示营销活动或活动季名称，不表示投保险种名称、险种简称或会员权益；当前暂不支持作为客户搜索条件
- operators：MATCH
- value_types：extract

## customerUnredeemedPoints
- 含义：表示客户尚未兑换的积分余额下限，不表示客户价值、保费、保额或现金金额；当前暂不支持作为客户搜索条件
- operators：GTE
- value_types：numeric
- 单位换算：积分，万=×10000；数值表示客户当前未兑换积分余额

## clientMobile
- 含义：仅表示客户本人手机号，不表示被保人、投保人、联系人、家庭成员手机号；当查询客户手机尾号|尾数|末尾|后x位|后几位|结尾时，必须设置match_mode=suffix
- operators：MATCH
- value_types：extract

## clientSex
- 含义：表示客户本人性别，不表示家庭成员、被保人、投保人性别
- operators：MATCH, EXISTS, NOT_EXISTS
- value_types：enum, exists, not_exists

## clientZodiac
- 含义：表示客户本人的十二生肖属相，不表示姓名、出生年份或家庭成员属相
- operators：MATCH
- value_types：enum

## clientAge
- 含义：表示客户本人年龄，不表示家庭成员年龄
- operators：GTE, LTE, RANGE, EXISTS, NOT_EXISTS
- value_types：numeric, exists
- 单位换算：岁，直接取数字，无需换算; 岁，直接取数字

## clientBirthday
- 含义：表示客户本人出生日期，不表示家庭成员出生日期
- operators：RANGE, GT, GTE, LT, LTE, EXISTS, NOT_EXISTS
- value_types：date, exists

## birthdayMd
- 含义：表示客户生日月日
- operators：RANGE, GTE, LTE
- value_types：date

## clientNo
- 含义：表示客户编号：以C开头，或以00开头；前缀之后为11至12位数字或字母。英文字母统一转为大写
- operators：MATCH
- value_types：extract

## newValueLabel
- 含义：表示用户明确指定的单个客户价值等级；只有原文出现具体等级值时使用。
- operators：MATCH, CONTAINS
- value_types：enum

## clientTemperature
- 含义：表示客户活跃度分层标签，不表示最近联系时间、最后联系日期、联系次数等具体联系记录
- operators：MATCH, CONTAINS
- value_types：enum

## clientGroupLabel
- 含义：表示客户画像分群标签。年龄、资产等组合定义用于增强召回理解，不作为默认自动映射规则。
- operators：CONTAINS
- value_types：enum

## vipType
- 含义：表示寿险VIP等级标签，不表示是否持有会员权益的开通时间或其他权益体系等级
- operators：MATCH, CONTAINS, EXISTS
- value_types：enum, exists

## pointsBalanceAmt
- 含义：表示寿险VIP积分余额严格大于指定值，不表示保费、现金或其他活动积分
- operators：GT, GTE, LT, LTE, RANGE
- value_types：numeric
- 单位换算：积分，万=×10000；未明确单位时按积分原值处理

## criticalMemberFlag
- 含义：表示客户是否为寿险临界会员，即是否已满足或接近下一VIP等级升级条件
- operators：MATCH
- value_types：enum

## criticalMemberGrade
- 含义：表示寿险临界会员等级或即将升级到的目标等级，不等同于客户当前VIP等级vipType
- operators：MATCH
- value_types：enum

## pointsExpiredDate
- 含义：表示寿险会员积分的到期时间范围，不表示积分余额或保单到期时间
- operators：RANGE
- value_types：date

## qkflag
- 含义：表示未指明具体权益时，客户是否为全局潜客
- operators：MATCH
- value_types：enum

## pajjMemberGradeInfo.pajjnextmembergrade
- 含义：表示平安居家预计升级或达标的下一会员等级
- operators：MATCH
- value_types：enum

## yxgyMemberGradeInfo.yxgynextmembergrade
- 含义：表示御享国医预计升级或达标的下一等级
- operators：MATCH
- value_types：enum

## sdbjyMemberGradeInfo.sdbjynextmembergrade
- 含义：表示私董保健康预计升级或达标的下一等级
- operators：MATCH
- value_types：enum

## gdkyMemberGradeInfo.gdkynextmembergrade
- 含义：表示高端康养预计升级或达标的下一会员等级
- operators：MATCH
- value_types：enum

## pajjMemberGradeInfo.pajjtotalpremgap
- 含义：平安居家1+N保费缺口精确值或闭区间
- operators：RANGE, GT, GTE, LT, LTE
- value_types：numeric
- 单位换算：万；10万输出10，不乘10000

## yxgyMemberGradeInfo.yxgytotalpremgap
- 含义：御享国医总保费缺口精确值或闭区间
- operators：RANGE, GT, GTE, LT, LTE
- value_types：numeric
- 单位换算：万；10万输出10，不乘10000

## sdbjyMemberGradeInfo.sdbjytotalpremgap
- 含义：私董保健康总保费缺口精确值或闭区间
- operators：RANGE, GT, GTE, LT, LTE
- value_types：numeric
- 单位换算：万；10万输出10，不乘10000

## gdkyMemberGradeInfo.gdkytotalpremgap
- 含义：高端康养新老保单保费缺口精确值或闭区间
- operators：RANGE, GT, GTE, LT, LTE
- value_types：numeric
- 单位换算：万；10万输出10，不乘10000

## orphanType
- operators：MATCH
- value_types：enum

## trusteeshipFlag
- 含义：表示保单是否有托管，是-有托管、否-未托管
- operators：CONTAINS
- value_types：enum

## onlyShareClientFlag
- 含义：表示客户已成功授权，并在授权后30天内未完成面访而触发回收、共享给当前用户；该字段是后端组合业务标签，只有 Y，没有 N。
- operators：MATCH
- value_types：enum

## mariSts
- operators：MATCH, CONTAINS
- value_types：enum

## profName
- 含义：表示客户本人的职业或从业类型枚举，不表示任职单位、公司、企业、机构或地址名称。
- operators：CONTAINS
- value_types：infer

## idType
- 含义：表示客户证件类型枚举，如身份证、护照、户口本等，不表示证件号码或证件有效期。
- operators：CONTAINS
- value_types：enum

## idNo
- 含义：表示客户证件号码或身份证号文本匹配，不表示证件类型、证件有效期或出生日期。
- operators：MATCH
- value_types：extract

## idValidDate
- 含义：表示证件有效期截止时间，不表示证件签发日期、办证日期、出生日期
- operators：RANGE, GT, GTE, LT, LTE
- value_types：date

## assetsCondition
- 含义：表示用户明确指定的单个完整资产组合状态。
- operators：MATCH, CONTAINS
- value_types：enum

## polNoInfo.plancodeinfo.abbrname
- 含义：表示百万医疗业务词对应的一组固定产品简称；输出值应限制在 millionMedicalProducts 枚举配置内。
- operators：CONTAINS, NOT_CONTAINS, MATCH
- value_types：enum

## pTypes
- 含义：表示客户持有的保险类型枚举值，不表示是否存在任意保险
- operators：MATCH, CONTAINS, NOT_CONTAINS
- value_types：enum

## pCategorys
- 含义：表示客户持有一个明确的险种类别，如医疗保险、疾病保险、意外伤害保险、定期寿险、终身寿险等，不表示具体产品名称。定期寿险、终身寿险不等于寿险。
- operators：MATCH, CONTAINS, NOT_CONTAINS
- value_types：enum

## annPremSegNum
- 含义：表示年缴保费金额（大于），不表示总保费、产品总保额
- operators：GT, GTE, RANGE, LT, LTE
- value_types：numeric
- 单位换算：元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元; 元，万=×10000，千=×1000

## polNoInfo.totmodalpremsum
- 含义：期交保费金额，≥ 达到或超过；区别于年交保费
- operators：GTE, GT, LTE, LT, RANGE
- value_types：numeric
- 单位换算：元，万=×10000，千=×1000，如果没有明确单位，则默认是元，不用做运算; 元，万=×10000，千=×1000

## insnoSumInsSeqNum
- 含义：表示产品总保额（大于），不表示总保费、年缴保费
- operators：GT, GTE, LT, LTE, RANGE
- value_types：numeric
- 单位换算：元，万=×10000、千=×1000，若未明确标注万或元的单位，则默认为元，不需要转换; 元，万=×10000元，千=×1000，若未明确标注万或元的单位，则默认为元，不需要转换

## effAnniversaryDate
- 含义：表示保单周年日，不表示投保时间、投保日期、签单日期
- operators：RANGE
- value_types：date

## agentPerspProductType
- 含义：表示客户持有某个明确的综拓产品类别，如中高端医疗、家财险、学平险、合家欢等。
- operators：MATCH, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## occurPassPayRegst
- 含义：表示综拓理赔状态，只有报案/结案等状态语义，不表示理赔时间、理赔金额、理赔次数
- operators：MATCH, EXISTS
- value_types：enum, exists

## validSinsMatuDateTime
- 含义：表示寿险保单到期时间晚于某个日期（不含等于），不表示缴费期满、证件到期
- operators：GT, GTE, LT, LTE, RANGE
- value_types：date

## validSinsPol
- operators：CONTAINS, NOT_CONTAINS
- value_types：enum

## pcustSourcType
- operators：CONTAINS, NOT_CONTAINS
- value_types：enum

## isBuyInsuranceCar
- 含义：仅表示客户是车险还是非车险，不能判断是否有买产险；不表示购买时间、保单状态
- operators：MATCH
- value_types：enum

## carInsuranceMatuDateTime
- 含义：表示车险保单到期时间，不表示是否持有车险，也不表示寿险保单到期时间
- operators：RANGE
- value_types：date

## isBuyInsurance
- 含义：客户类型；客户/准客=买过保险，用户=没有买过保险
- operators：CONTAINS
- value_types：enum

## isBuyProperty
- 含义：是否产险客户
- operators：MATCH
- value_types：enum

## isBuyPension
- 含义：是否养老险客户
- operators：MATCH
- value_types：enum

## isBuyHealth
- 含义：是否健康险客户
- operators：MATCH
- value_types：enum

## familyInfo.familyclientsex
- 含义：表示家庭成员性别，不表示客户本人性别；出现关系词时应与 familyInfo.familyrelation 组合
- operators：MATCH
- value_types：enum

## effAppEndDate
- 含义：表示缴费期满时间，不表示保单到期时间、证件有效期
- operators：RANGE, GT, GTE, LT, LTE
- value_types：date

## familyInfo.familyclientbirthday
- 含义：表示家庭成员出生日期，不表示客户本人出生日期；出现关系词时应与 familyInfo.familyrelation 组合
- operators：RANGE, GTE, GT, LT
- value_types：date

## familyInfo.familyclientage
- 含义：表示家庭成员年龄，不表示客户本人年龄；出现关系词时应与 familyInfo.familyrelation 组合
- operators：RANGE, GT, GTE, LT, LTE
- value_types：numeric
- 单位换算：岁，直接取数字；系统会自动将年龄转换为 familyInfo.familyclientbirthday 日期范围

## education
- 含义：表示客户本人学历的精确枚举匹配。
- operators：MATCH, CONTAINS, NOT_CONTAINS
- value_types：enum

## familyInfo.familyrelation
- 含义：表示客户家庭中存在的成员关系。关系词前出现的客户姓名仍是客户本人姓名，不得因此映射为家庭成员姓名。
- operators：CONTAINS
- value_types：enum

## familyInfo.familyclientname
- 含义：表示家庭成员姓名，不表示客户本人姓名。仅当家庭成员、家属、女儿、儿子、父母、配偶等角色词直接引出或修饰姓名时使用。
- operators：MATCH
- value_types：extract

## familyInfo.familyclientmobile
- 含义：表示家庭成员手机号，不表示客户本人手机号；出现关系词时应与 familyInfo.familyrelation 组合
- operators：MATCH
- value_types：extract

## polNo
- 含义：表示保单号，不表示客户编号。标准格式包括：P或A开头后跟15至17位数字或字母（兼容历史数据中的14位）；GP开头后跟14位数字或字母；在明确写出“保单号”时也支持15至17位纯数字。字母统一转为大写
- operators：MATCH
- value_types：extract

## licensePlateNo
- 含义：表示车辆号牌号码，非枚举字段；不表示车架号、发动机号或车险保单号。字母统一转为大写，如苏A80789、贵J00990
- operators：MATCH
- value_types：extract

## annual_income
- 含义：客户个人年收入，数值型，单位元
- operators：GTE, LTE, RANGE
- value_types：numeric
- 单位换算：元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元，不需要换算; 元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元

## household_income
- 含义：家庭年收入，数值型，单位元
- operators：GTE, LTE
- value_types：numeric
- 单位换算：元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元

## asset_scale
- 含义：客户资产规模，数值型，单位元
- operators：GTE, LTE
- value_types：numeric
- 单位换算：元，万=×10000，千=×1000，若为明确是万还是千单位，则默认是元

## polNoInfo.poleffdate
- 含义：业务口径中的签单、签约和成交时间统一映射为保单生效日期范围，不表示投保申请日期或承保日期
- operators：RANGE, GTE, GT, LTE, LT, EXISTS
- value_types：date, exists

## dateCreated
- 含义：客户添加到系统中的日期时间；未指定其他时间范围时，‘新客户/新客’指客户添加日在近1个月内
- operators：RANGE, GTE
- value_types：date

## polNoInfo.polStatus
- 含义：表示用户明确指定的单个保单状态。
- operators：MATCH, CONTAINS, NOT_CONTAINS
- value_types：enum

## policies_insure_date
- 含义：保单投保日期，嵌套字段；‘去年购买/买了/买过/投保某险种’中的‘去年’也是投保日期条件。该字段当前不支持搜索，但必须解析以便给出不支持提示
- operators：RANGE
- value_types：date

## latelyUndwrtSegTime
- 含义：保单承保日期，嵌套字段
- operators：RANGE, GTE, GT, LTE, LT
- value_types：date

## polNoInfo.paytodate
- 含义：保单应缴费日期，嵌套字段
- operators：RANGE, EXISTS
- value_types：date, exists

## polNoInfo.wholeDecision
- 含义：保单核保结论，嵌套字段，开放域文本
- operators：MATCH
- value_types：extract

## policies_cooling_off
- 含义：保单犹豫期截止时间，嵌套字段
- operators：RANGE
- value_types：date

## polNoInfo.plancodeinfo.planfullname
- 含义：保单投保险种全称，嵌套字段，枚举值通过独立配置文件维护；活动、活动季、守护季名称不属于投保险种
- operators：MATCH
- value_types：enum

## polNoInfo.plancodeinfo.plantypedesc
- 含义：保单投保险种类别，明确指定单一险种类别时使用MATCH
- operators：MATCH, NOT_CONTAINS
- value_types：enum

## polNoInfo.applicantname
- 含义：保单投保人姓名。只有投保人角色直接修饰姓名，或明确说明某人作为投保人时才使用。
- operators：MATCH
- value_types：extract

## polNoInfo.applicantphoneno
- 含义：保单投保人手机号，嵌套字段
- operators：MATCH
- value_types：extract

## polNoInfo.plancodeinfo.insname
- 含义：保单被保人姓名。只有被保人或被保险人角色直接修饰姓名，或明确说明某人作为被保人时才使用。
- operators：MATCH
- value_types：extract

## polNoInfo.plancodeinfo.insphoneno
- 含义：保单被保人手机号，嵌套字段
- operators：MATCH
- value_types：extract

## polNoInfo.benefinfo.benefname
- 含义：保单受益人姓名。只有受益人角色直接修饰姓名，或明确说明某人作为受益人时才使用。
- operators：MATCH, CONTAINS
- value_types：extract

## policies_beneficiary_mobile
- 含义：保单受益人手机号，嵌套字段
- operators：MATCH
- value_types：extract

## polNoInfo.payamountdue
- 含义：生存金未领取金额是否大于0；是表示生存金领取金额等于0，否表示生存金领取金大于0；该字段不表述生存金利息相关字段查询
- operators：MATCH
- value_types：enum
- 枚举样例：是, 否

## policies_universal_acct_transfer
- 含义：生存金已转入万能账户金额（转入万能账户的本金），区别于生存金总金额、生存金利息
- operators：GTE, GT, LTE, LT, EXISTS
- value_types：numeric, none
- 单位换算：元，万=×10000，千=×1000

## polNoInfo.survivalinterestunpaidamt
- 含义：生存金利息未领取精确金额或区间金额查询
- operators：RANGE, GTE, GT, LTE, LT
- value_types：range, numeric
- 单位换算：元，万=×10000，千=×1000，若没明确单位，默认为元; 元，万=×10000，千=×1000

## polNoInfo.claimdatainfo.claimdate
- 含义：理赔记录中的理赔时间，嵌套字段；若仅判断是否有理赔记录，用 EXISTS
- operators：RANGE
- value_types：date

## polNoInfo.claimdatainfo.claimno
- 含义：理赔案件号，格式为MC+14位数字，例如：MC20240509000001
- operators：MATCH
- value_types：extract

## polNoInfo.claimdatainfo.claimamt
- 含义：理赔金额，≥ 达到或超过
- operators：GTE, GT, LTE, LT, RANGE
- value_types：numeric
- 单位换算：元，万=×10000，千=×1000

## polNoInfo.claimdatainfo.claimplancodename
- 含义：指定明确发生过理赔的单一险种名称；必须同时存在理赔动作和具体险种，使用MATCH
- operators：MATCH, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：extract, none

## is_life_insured
- 含义：表示客户在寿险保单中的投保人/被保人身份关系。
- operators：MATCH
- value_types：enum
- 枚举样例：仅投保人, 仅被保人, 投被保人

## polNum
- 含义：客户持有的保单总数量；张以上/张及以上表示 ≥N，张以下表示 ≤N
- operators：GTE
- value_types：-

## polNoInfo.surrenderDateTime
- 含义：保单退保时间，嵌套字段，格式 yyyy-MM-dd HH:mm:ss
- operators：RANGE
- value_types：-

## clientChurnTag
- 含义：客户是否属于濒临失效高客；定义为可投资资产达到或超过50万元，且存在保单失效风险
- operators：MATCH, NOT_EXISTS
- value_types：enum, none

## ayyMemberGradeInfo.ayymemberproductname
- 含义：安有医会员服务线名称，不表示其他服务线
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## ayyMemberGradeInfo.ayymembergradesearch
- 含义：安有医会员等级或版本，不表示安有医达标状态
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## ayyMemberGradeInfo.ayymemberstatus
- 含义：安有医会员类型或状态，不表示安有医等级版本
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## ayyMemberGradeInfo.ayymemberperiod
- 含义：安有医会员期次（年度），不表示安有医达标时间
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：extract, exists

## ayyMemberGradeInfo.ayyqualifiedtime
- 含义：安有医会员达标时间（达标日期），不表示安有医期次
- operators：RANGE, GT, GTE, LT, LTE, EXISTS, NOT_EXISTS
- value_types：date, exists

## ayhMemberGradeInfo.ayhmemberproductname
- 含义：安有护会员服务线名称，不表示其他服务线
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## ayhMemberGradeInfo.ayhmembergradesearch
- 含义：安有护会员等级或版本，不表示安有护达标状态
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## ayhMemberGradeInfo.ayhmemberstatus
- 含义：安有护会员类型或状态，不表示安有护等级版本
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## ayhMemberGradeInfo.ayhmemberperiod
- 含义：安有护会员期次（年度），不表示安有护达标时间
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：extract, exists

## ayhMemberGradeInfo.ayhqualifiedtime
- 含义：安有护会员达标时间（达标日期），不表示安有护期次
- operators：RANGE, GT, GTE, LT, LTE, EXISTS, NOT_EXISTS
- value_types：date, exists

## zxjyMemberGradeInfo.zxjymemberproductname
- 含义：臻享家医会员服务线名称，不表示其他服务线
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## zxjyMemberGradeInfo.zxjymembergradesearch
- 含义：臻享家医会员等级或版本，不表示臻享家医达标状态
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## zxjyMemberGradeInfo.zxjymemberstatus
- 含义：臻享家医会员类型或状态，不表示臻享家医等级版本
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## zxjyMemberGradeInfo.zxjymemberperiod
- 含义：臻享家医会员期次（年度），不表示臻享家医达标时间
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：extract, exists

## zxjyMemberGradeInfo.zxjyqualifiedtime
- 含义：臻享家医会员达标时间（达标日期），不表示臻享家医期次
- operators：RANGE, GT, GTE, LT, LTE, EXISTS, NOT_EXISTS
- value_types：date, exists

## pajjMemberGradeInfo.pajjmemberproductname
- 含义：平安居家会员服务线名称，不表示其他服务线
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## pajjMemberGradeInfo.pajjmembergradesearch
- 含义：平安居家会员等级或版本，不表示平安居家达标状态
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## pajjMemberGradeInfo.pajjmemberstatus
- 含义：平安居家会员类型或状态，不表示平安居家等级版本
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## pajjMemberGradeInfo.pajjmemberperiod
- 含义：平安居家会员期次（年度），不表示平安居家达标时间
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：extract, exists

## pajjMemberGradeInfo.pajjqualifiedtime
- 含义：平安居家会员达标时间（达标日期）；“新获得/新拿到/新增/刚获得居家权益”均按达标时间判断，不表示平安居家期次
- operators：RANGE, GT, GTE, LT, LTE, EXISTS, NOT_EXISTS
- value_types：date, exists

## yxgyMemberGradeInfo.yxgymemberproductname
- 含义：御享国医会员服务线名称，不表示其他服务线
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## yxgyMemberGradeInfo.yxgymembergradesearch
- 含义：御享国医会员等级或版本，不表示御享国医达标状态
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## yxgyMemberGradeInfo.yxgymemberstatus
- 含义：御享国医会员类型或状态，不表示御享国医等级版本
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## yxgyMemberGradeInfo.yxgymemberperiod
- 含义：御享国医会员期次（年度），不表示御享国医达标时间
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：extract, exists

## yxgyMemberGradeInfo.yxgyqualifiedtime
- 含义：御享国医会员达标时间（达标日期），不表示御享国医期次
- operators：RANGE, GT, GTE, LT, LTE, EXISTS, NOT_EXISTS
- value_types：date, exists

## sdbjyMemberGradeInfo.sdbjymemberproductname
- 含义：私董保健医会员服务线名称，不表示其他服务线
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## sdbjyMemberGradeInfo.sdbjymembergradesearch
- 含义：私董保健医会员等级或版本，不表示私董保健医达标状态
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## sdbjyMemberGradeInfo.sdbjymemberstatus
- 含义：私董保健医会员类型或状态，不表示私董保健医等级版本
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## sdbjyMemberGradeInfo.sdbjymemberperiod
- 含义：私董保健医会员期次（年度），不表示私董保健医达标时间
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：extract, exists

## sdbjyMemberGradeInfo.sdbjyqualifiedtime
- 含义：私董保健医会员达标时间（达标日期），不表示私董保健医期次
- operators：RANGE, GT, GTE, LT, LTE, EXISTS, NOT_EXISTS
- value_types：date, exists

## gdkyMemberGradeInfo.gdkymemberproductname
- 含义：高端康养会员服务线名称，不表示其他服务线
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## gdkyMemberGradeInfo.gdkymembergradesearch
- 含义：高端康养会员等级或版本，不表示高端康养达标状态
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## gdkyMemberGradeInfo.gdkymemberstatus
- 含义：高端康养会员类型或状态，不表示高端康养等级版本
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：enum, exists

## gdkyMemberGradeInfo.gdkymemberperiod
- 含义：高端康养会员期次（年度），不表示高端康养达标时间
- operators：MATCH, CONTAINS, NOT_CONTAINS, EXISTS, NOT_EXISTS
- value_types：extract, exists

## gdkyMemberGradeInfo.gdkyqualifiedtime
- 含义：高端康养会员达标时间（达标日期）；“新获得/新拿到/新增/刚获得高端康养权益”均按达标时间判断，不表示高端康养期次
- operators：RANGE, GT, GTE, LT, LTE, EXISTS, NOT_EXISTS
- value_types：date, exists

## CONTACT_ADDRESS_FIELD
- 含义：客户联系（通讯）地址字段。仅表示客户本人的联系地址。
- operators：MATCH, GEO_RADIUS
- value_types：extract, geo_radius

## ANY_ADDRESS_FIELD
- 含义：用户未明确说明联系地址或家庭地址时，同时查询两类地址。居住地址、普通地址、住址、住在、家住、家在和裸地址均属于未指定地址类型。
- operators：MATCH, GEO_RADIUS, NOT_GEO_RADIUS
- value_types：extract, geo_radius

## FAMILY_ADDRESS_FIELD
- 含义：客户家庭地址字段。只有原文明确出现家庭地址或家庭住址时使用。
- operators：MATCH, GEO_RADIUS
- value_types：extract, geo_radius
