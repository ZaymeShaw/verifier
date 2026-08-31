# time_knowledge_args.yaml

- evidence_ref: `business-time-knowledge`
- location: `business://src/main/python/data/client_search_query_parse/time_knowledge_args.yaml`
- source_revision: `a2cfd68ea351d5081d95857ca7bcbfac90434528`
- source_sha256: `bd25a9f2fe8a50f08bcccbcf001822a2c48223ba68735b990985fe7cc5e1382a`

相对时间口语（上周/下月/未来N天等）到日期区间的换算口径：时间窗口意图可执行性的当前基线。

---

time_knowledge:
  - id: current_week
    aliases: ["本周", "这周", "这个星期"]
    resolver:
      date_range: "week_offset"
      offset: 0
      format: "yyyy-MM-dd HH:mm:ss"

  - id: next_next_week
    aliases: ["下下周", "下下星期", "下下个星期"]
    resolver:
      date_range: "week_offset"
      offset: 2
      format: "yyyy-MM-dd HH:mm:ss"

  - id: next_week
    aliases: ["下周", "下星期", "下个星期"]
    resolver:
      date_range: "week_offset"
      offset: 1
      format: "yyyy-MM-dd HH:mm:ss"

  - id: last_last_week
    aliases: ["上上周", "上上星期", "上上个星期"]
    resolver:
      date_range: "week_offset"
      offset: -2
      format: "yyyy-MM-dd HH:mm:ss"

  - id: last_week
    aliases: ["上周", "上星期", "上个星期"]
    resolver:
      date_range: "week_offset"
      offset: -1
      format: "yyyy-MM-dd HH:mm:ss"

  - id: next_month
    aliases: ["下个月", "下月"]
    resolver:
      date_range: "next_month"
      format: "yyyy-MM-dd HH:mm:ss"

  - id: last_month
    aliases: ["上个月", "上月"]
    resolver:
      date_range: "last_month"
      format: "yyyy-MM-dd HH:mm:ss"

  - id: future_week
    aliases: ["未来一周", "接下来一周", "未来7天", "未来七天"]
    patterns:
      - '(?:未来|接下来)(?:一|1)(?:周|个?星期)(?:内|里)?(?:.{0,24}?(?:即将|快要|马上|将要))?'
      - '(?:最近|近)(?:一|1)(?:周|个?星期)(?:内|里)?.{0,24}?(?:即将|快要|马上|将要)'
      - '(?:即将|快要|马上|将要).{0,24}?(?:在)?(?:最近|近|未来|接下来)(?:一|1)(?:周|个?星期)(?:内|里)?'
    resolver:
      date_range: "next_n_days"
      days: 7
      format: "yyyy-MM-dd HH:mm:ss"

  - id: future_month
    aliases: ["未来一个月", "接下来一个月", "未来30天", "未来三十天", "即将到期", "快到期", "即将过期", "快过期", "近期过期"]
    resolver:
      date_range: "next_n_days"
      days: 30
      format: "yyyy-MM-dd HH:mm:ss"

  # 通用未来N个月时间知识，不绑定积分、保单、证件或权益字段。
  # “未来/接下来N个月”天然表示未来；“最近/近N个月”只有与即将/将要等
  # 未来方向词出现在同一短语中时才按未来处理，否则仍保留通常的过去语义。
  # 项目沿用一个月=30天的滚动窗口口径。
  - id: future_n_months
    patterns:
      - '(?:未来|接下来)(?P<months>\d+|[零〇一二两三四五六七八九十百]+)(?:个)?月(?:内|里)?(?:.{0,24}?(?:即将|快要|马上|将要))?'
      - '(?:最近|近)(?P<months>\d+|[零〇一二两三四五六七八九十百]+)(?:个)?月(?:内|里)?.{0,24}?(?:即将|快要|马上|将要)'
      - '(?:即将|快要|马上|将要).{0,24}?(?:在)?(?:最近|近|未来|接下来)(?P<months>\d+|[零〇一二两三四五六七八九十百]+)(?:个)?月(?:内|里)?'
    resolver:
      date_range: "next_n_days"
      days: 1
      days_group: months
      days_multiplier: 30
      format: "yyyy-MM-dd HH:mm:ss"

  - id: future_half_year
    patterns:
      - '(?:未来|接下来)半年(?:内|里)?(?:.{0,24}?(?:即将|快要|马上|将要))?'
      - '(?:最近|近)半年(?:内|里)?.{0,24}?(?:即将|快要|马上|将要)'
      - '(?:即将|快要|马上|将要).{0,24}?(?:在)?(?:最近|近|未来|接下来)半年(?:内|里)?'
    resolver:
      date_range: "next_n_days"
      days: 180
      format: "yyyy-MM-dd HH:mm:ss"

  - id: recent_half_year
    aliases: ["近半年", "最近半年", "过去半年"]
    resolver:
      date_range: "past_n_months_to_today"
      months: 6
      format: "yyyy-MM-dd HH:mm:ss"

  - id: recent_year
    aliases: ["近一年", "最近一年", "过去一年"]
    resolver:
      date_range: "past_n_months_to_today"
      months: 12
      format: "yyyy-MM-dd HH:mm:ss"

  - id: future_year
    aliases: ["未来一年", "接下来一年", "未来365天", "未来三百六十五天"]
    patterns:
      - '(?:未来|接下来)(?:一|1)(?:年|个年度)(?:内|里)?(?:.{0,24}?(?:即将|快要|马上|将要))?'
      - '(?:最近|近)(?:一|1)(?:年|个年度)(?:内|里)?.{0,24}?(?:即将|快要|马上|将要)'
      - '(?:即将|快要|马上|将要).{0,24}?(?:在)?(?:最近|近|未来|接下来)(?:一|1)(?:年|个年度)(?:内|里)?'
    resolver:
      date_range: "next_n_days"
      days: 365
      format: "yyyy-MM-dd HH:mm:ss"

  # ==================== 0610 新增字段通用时间表达 ====================

  - id: within_week
    aliases: ["一周内", "最近一周内", "近一周内", "过去一周内", "近一周", "最近一周", "过去一周"]
    resolver:
      date_range: "last_n_days"
      days: 7
      format: "yyyy-MM-dd HH:mm:ss"

  - id: within_year
    aliases: ["一年内", "最近一年内", "近一年内", "过去一年内"]
    resolver:
      date_range: "past_n_months_to_today"
      months: 12
      format: "yyyy-MM-dd HH:mm:ss"

  - id: recent
    aliases: ["近期", "近来", "这段时间"]
    resolver:
      date_range: "last_n_days"
      days: 30
      format: "yyyy-MM-dd HH:mm:ss"

  - id: last_year
    aliases: ["去年", "上一年", "上年度"]
    resolver:
      date_range: "last_year"
      format: "yyyy-MM-dd HH:mm:ss"

  - id: current_year
    aliases: ["今年", "本年", "本年度"]
    resolver:
      date_range: "current_year"
      format: "yyyy-MM-dd HH:mm:ss"
