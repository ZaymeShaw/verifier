# field_enums_args.yaml

- evidence_ref: `business-field-enums`
- location: `business://src/main/python/data/client_search_query_parse/field_enums_args.yaml`
- source_revision: `a2cfd68ea351d5081d95857ca7bcbfac90434528`
- source_sha256: `9adabeb667fd70cd5120acf9dd69918df35c60c6525a88b270d5885c23a6e24e`

各字段合法枚举值列表：判断 actual 值是否清单外值的当前行为基线。

---

# ============================================================
# 统一枚举配置 - 所有字段的标准枚举值
# 结构：
#   fieldName:
#     values: [...]      # 枚举值列表
#     ordered: true      # 可选，标记有序枚举（低→高），供 enum_gte/enum_lte 使用
# ============================================================

# 性别
clientSex:
  values:
    - "男"
    - "女"

# 客户属相
clientZodiac:
  values:
    - "鼠"
    - "牛"
    - "虎"
    - "兔"
    - "龙"
    - "蛇"
    - "马"
    - "羊"
    - "猴"
    - "鸡"
    - "狗"
    - "猪"

# 家庭成员性别
familyInfo.familyclientsex:
  values:
    - "男"
    - "女"

# 婚姻状况
mariSts:
  values:
    - "未婚"
    - "已婚"
    - "离婚"
    - "丧偶"
    - "未知"

# 证件类型
idType:
  values:
    - "出生证"
    - "身份证"
    - "户口本"
    - "港澳台居住证"
    - "军人证"
    - "港澳台证"
    - "护照"
    - "外国人居留证"

# 客户温度（低→高）
clientTemperature:
  values:
    - "冷却"
    - "低温"
    - "中温"
    - "高温"
  ordered: true

# 客户价值（低→高，以Excel官方文档为准）
newValueLabel:
  values:
    - "F"
    - "E"
    - "D"
    - "C"
    - "B"
    - "A4"
    - "A3"
    - "A2"
    - "A1"
  ordered: true

# 学历（低→高）
education:
  values:
    - "小学以下"
    - "小学"
    - "初中"
    - "中专"
    - "高中"
    - "大学专科"
    - "大学本科生"
    - "硕士研究生"
    - "博士研究生"
    - "博士后"
  ordered: true

# 客群标签
clientGroupLabel:
  values:
    - "奋斗青年"
    - "都市白领"
    - "而立一族"
    - "社会中坚"
    - "邻退天命"
    - "慈爱祖辈"
    - "创业新贵"
    - "创富一代"
    - "荣耀高堂"
    - "承富二代"
    - "已退小康"

# 寿险VIP等级（低→高，以Excel官方文档为准）
vipType:
  values:
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
  ordered: true

# 是否临界会员
criticalMemberFlag:
  values:
    - "是"
    - "否"

# 临界会员等级
criticalMemberGrade:
  values:
    - "黑钻"
    - "钻石"
    - "黄金V1"
    - "黄金V2"
    - "黄金V3"
    - "铂金V1"
    - "铂金V2"
    - "金钻"
    - "白银V2"
    - "白银V3"

# 存量客户类型
orphanType:
  values:
    - "在职有效客户"
    - "纯存续单客户"
    - "非纯存续单客户"

# 保单托管
trusteeshipFlag:
  values:
    - "是"
    - "否"

# 成功授权后 30 天未面访并触发回收、共享给当前用户的客户；只有 Y，没有 N。
onlyShareClientFlag:
  values:
    - "Y"

# 持有产品类型
pTypes:
  values:
    - "普通型"
    - "分红型"
    - "投资连结型"
    - "万能型"
    - "其他"

# 持有产品品类（以Excel官方文档为准）
pCategorys:
  values:
    - "意外伤害保险"
    - "医疗保险"
    - "护理保险"
    - "疾病保险"
    - "定期寿险"
    - "终身寿险"

# 综拓产品类别（以Excel官方文档为准）
agentPerspProductType:
  values:
    - "车辆交强险"
    - "车辆商业险"
    - "e生保"
    - "中高端医疗"
    - "合家欢"
    - "家财险"
    - "学平险"
    - "财富"
    - "健康"
    - "生活"

# 综拓理赔
occurPassPayRegst:
  values:
    - "综拓理赔报案"
    - "综拓理赔结案"

# 有效短险保单
validSinsPol:
  values:
    - "综拓"
    - "O2O"
    - "意健险"

# 准客来源
pcustSourcType:
  values:
    - "综拓准客"
    - "O2O准客"
    - "意健险准客"

# 居家达标客户等级（低→高，以Excel官方文档为准）
jujiaClientGrade:
  values:
    - "居家潜客"
    - "v0.5"
    - "v1"
    - "v1.5"
    - "v2"
    - "v2.5"
    - "v3"
  ordered: true

# 康养达标客户等级（低→高，以Excel官方文档为准）
kangyangClientGrade:
  values:
    - "康养预达标会员"
    - "逸享会员"
    - "逸享PLUS会员"
    - "颐享家会员"
    - "臻享会员V1"
    - "臻享会员V2"
    - "臻享会员V3"
  ordered: true

# 安有护权益等级
zhenxiangRunEquityGrade:
  values:
    - "安有护(国内版)"
    - "安有护(国际版)"
  ordered: true

# 臻享家医权益等级
zxjyEquityGrade:
  values:
    - "预达标"
    - "已达标"
  ordered: true

# 资产状况
assetsCondition:
  values:
    - "有房"
    - "有车"
    - "有房有车"
    - "无房无车"

# 产险产品
isBuyInsuranceCar:
  values:
    - "车险"
    - "非车险"

# 寿险投保被保人
is_life_insured:
  values:
    - "仅投保人"
    - "仅被保人"
    - "投被保人"

# 家庭成员关系
familyInfo.familyrelation:
  values:
    - "配偶"
    - "父母"
    - "子女"
    - "兄弟姐妹"
    - "法定"
    - "(外)祖父母"
    - "(外)孙子女"

# 保单状态
polNoInfo.polStatus:
  values:
    - "预收"
    - "拒保"
    - "自垫有效"
    - "死亡有效"
    - "取消"
    - "死亡理赔"
    - "展期"
    - "迁出"
    - "自垫停效"
    - "贷款超停"
    - "交费有效"
    - "自垫交清"
    - "贷款超失"
    - "停效"
    - "到期终止"
    - "犹豫期退保"
    - "自垫失效"
    - "交清"
    - "减额交清"
    - "退保"
    - "转换终止"
    - "等待续保"
    - "失效"
    - "免交"
    - "终止效力"
    - "效力终止"
    - "人为停效"

# 百万医疗产品集合
millionMedicalProducts:
  values:
    - "百万任我行"
    - "百万任我行17"
    - "百万任我行18"
    - "百万任我行22"
    - "百万任我行23"
    - "百万任我行25"
    - "倍享百万"
    - "百万随行"

# 税优产品/税优养老产品集合
taxPreferredPensionProducts:
  values:
    - "税优养老"
    - "智盈倍护"
    - "智盈倍护25"
    - "智盈倍护26"
    - "盛世优享"
    - "盛世优享传统"
    - "盛世优享红26"
    - "盛世优享26"
    - "安颐尊享"
    - "颐享延年"
    - "颐享延年23"
    - "颐享延年24"
    - "颐享延年25"
    - "颐享延年26"
    - "颐享延年分红"
    - "颐享延年加护"
    - "金越养老年金（分红）"

polNoInfo.plancodeinfo.plantypedesc:
  values:
    - "年金"
    - "两全险"
    - "健康险"
    - "寿险"
    - "定期险"

polNoInfo.payamountdue:
  values:
    - "是"
    - "否"

# 是否产险客户
isBuyProperty:
  values:
    - "有购买"
    - "没有购买"

# 是否养老险客户
isBuyPension:
  values:
    - "有购买"
    - "没有购买"

# 是否健康险客户
isBuyHealth:
  values:
    - "有购买"
    - "没有购买"

# 客户类型
isBuyInsurance:
  values:
    - "客户"
    - "准客"
    - "用户"

# ==================== 0610 新增客户分类及会员等级字段 ====================
# 是否濒临失效高客
clientChurnTag:
  values: 
    - "是"

# 安有医-服务线名称
ayyMemberGradeInfo.ayymemberproductname:
  values: 
    - "安有医"

# 安有医-会员等级
ayyMemberGradeInfo.ayymembergradesearch:
  values: 
    - "易核版"
    - "惠享版"
    - "悦享版" 
    - "尊享版"
    - "颐享版"
    - "加享1"
    - "加享2"
    - "加享3"
    - "加享4"
    - "加享5"

# 安有医-会员类型
ayyMemberGradeInfo.ayymemberstatus:
  values:
    - "潜客"    # 暂不支持
    - "意向"    # 暂不支持
    - "达标"
    - "预达标"  # 暂不支持
    - "维持"    # 暂不支持

# 安有护-服务线名称
ayhMemberGradeInfo.ayhmemberproductname:
  values: 
    - "安有护"

# 安有护-会员等级
ayhMemberGradeInfo.ayhmembergradesearch:
  values: 
    - "安有护(国内版)"
    - "安有护(国际版)"

# 安有护-会员类型
ayhMemberGradeInfo.ayhmemberstatus:
  values:
    - "潜客"    # 暂不支持
    - "意向"    # 暂不支持
    - "达标"
    - "预达标"  # 暂不支持
    - "维持"    # 暂不支持

# 臻享家医-服务线名称
zxjyMemberGradeInfo.zxjymemberproductname:
  values: 
    - "臻享家医"

# 臻享家医-会员等级
zxjyMemberGradeInfo.zxjymembergradesearch:
  values: 
    - "臻享家医V1"
    - "臻享家医V2"
    - "臻享家医V3"
  ordered: true

# 臻享家医-会员类型
zxjyMemberGradeInfo.zxjymemberstatus:
  values:
    - "潜客"    # 暂不支持
    - "意向"
    - "达标"
    - "预达标"
    - "维持"    # 暂不支持

# 平安居家-服务线名称
pajjMemberGradeInfo.pajjmemberproductname:
  values: 
    - "平安居家"

# 平安居家-会员等级
pajjMemberGradeInfo.pajjmembergradesearch:
  values: 
    - "平安居家V0"
    - "平安居家V1"
    - "平安居家V1优享"
    - "平安居家V2"
    - "平安居家V2优享"
  ordered: true

# 平安居家-下一等级
pajjMemberGradeInfo.pajjnextmembergrade:
  values:
    - "平安居家V0"
    - "平安居家V1"
    - "平安居家V1优享"
    - "平安居家V2"
    - "平安居家V2优享"

# 平安居家-会员类型
pajjMemberGradeInfo.pajjmemberstatus:
  values: 
    - "潜客"
    - "意向"
    - "达标"
    - "预达标"
    - "维持"

# 御享国医-服务线名称
yxgyMemberGradeInfo.yxgymemberproductname:
  values: 
    - "御享国医"

# 御享国医-会员等级
yxgyMemberGradeInfo.yxgymembergradesearch:
  values: 
    - "御享国医"

# 御享国医-下一等级
yxgyMemberGradeInfo.yxgynextmembergrade:
  values:
    - "御享国医"

# 御享国医-会员类型
yxgyMemberGradeInfo.yxgymemberstatus:
  values:
    - "潜客"
    - "意向"
    - "达标"
    - "预达标"
    - "维持"    # 暂不支持

# 私董保健医-服务线名称
sdbjyMemberGradeInfo.sdbjymemberproductname:
  values: 
    - "私董保健医"

# 私董保健医-会员等级
sdbjyMemberGradeInfo.sdbjymembergradesearch:
  values: 
    - "京华版"
    - "繁花版"

# 私董保健康-下一等级（字段前缀按接口定义为 sdbyj）
sdbjyMemberGradeInfo.sdbjynextmembergrade:
  values:
    - "京华版"
    - "繁花版"

# 私董保健医-会员类型
sdbjyMemberGradeInfo.sdbjymemberstatus:
  values:
    - "潜客"
    - "意向"
    - "达标"
    - "预达标"
    - "维持"    # 暂不支持

# 高端康养-服务线名称
gdkyMemberGradeInfo.gdkymemberproductname:
  values: 
    - "高端康养"

# 高端康养-会员等级
gdkyMemberGradeInfo.gdkymembergradesearch:
  values: 
    - "逸享会员"
    - "逸享PLUS会员"
    - "颐享家会员"
    - "臻享V1会员"
    - "臻享V2会员"
  ordered: true

# 高端康养-下一等级
gdkyMemberGradeInfo.gdkynextmembergrade:
  values:
    - "逸享会员"
    - "逸享PLUS会员"
    - "颐享家会员"
    - "臻享V1会员"
    - "臻享V2会员"

# 是否潜客
qkflag:
  values:
    - "是"
    - "否"

# 高端康养-会员类型
gdkyMemberGradeInfo.gdkymemberstatus:
  values:
    - "潜客"
    - "意向"
    - "达标"
    - "预达标"
    - "维持"    # 暂不支持

# 日期/时间字段输出格式。后处理会按这里的格式统一纠正 L2/LLM 输出。
# - yyyy-MM-dd HH:mm:ss: 缺少时分秒时自动补齐
# - yyyy-MM-dd: 多出时分秒时自动删除
date_field_formats:
  # 客户出生日
  clientBirthday: "yyyy-MM-dd HH:mm:ss"
  # 证件有效期
  idValidDate: "yyyy-MM-dd HH:mm:ss"
  # 保单到期日
  validSinsMatuDateTime: "yyyy-MM-dd"
  # 车险到期时间
  carInsuranceMatuDateTime: "yyyy-MM-dd"
  # 缴费期满日
  effAppEndDate: "yyyy-MM-dd"
  # 家庭成员生日
  familyInfo.familyclientbirthday: "yyyy-MM-dd HH:mm:ss"
  # 保单生效日
  polNoInfo.poleffdate: "yyyy-MM-dd HH:mm:ss"
  # 客户添加日
  dateCreated: "yyyy-MM-dd HH:mm:ss"
  # 承保日期
  latelyUndwrtSegTime: "yyyy-MM-dd"
  # 应缴日
  polNoInfo.paytodate: "yyyy-MM-dd HH:mm:ss"
  # 理赔时间
  polNoInfo.claimdatainfo.claimdate: "yyyy-MM-dd HH:mm:ss"
  # 退保时间
  polNoInfo.surrenderDateTime: "yyyy-MM-dd HH:mm:ss"
  # 犹豫期时间
  policies_cooling_off: "yyyy-MM-dd HH:mm:ss"
  # 投保日期
  policies_insure_date: "yyyy-MM-dd HH:mm:ss"
  # 新增会员达标时间
  ayyMemberGradeInfo.ayyqualifiedtime: "yyyy-MM-dd"
  ayhMemberGradeInfo.ayhqualifiedtime: "yyyy-MM-dd"
  zxjyMemberGradeInfo.zxjyqualifiedtime: "yyyy-MM-dd"
  pajjMemberGradeInfo.pajjqualifiedtime: "yyyy-MM-dd"
  yxgyMemberGradeInfo.yxgyqualifiedtime: "yyyy-MM-dd"
  sdbjyMemberGradeInfo.sdbjyqualifiedtime: "yyyy-MM-dd"
  gdkyMemberGradeInfo.gdkyqualifiedtime: "yyyy-MM-dd"
  # 寿险会员积分到期时间
  pointsExpiredDate: "yyyy-MM-dd"
