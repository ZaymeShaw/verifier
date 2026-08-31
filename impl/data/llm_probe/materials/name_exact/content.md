  - id: name_exact
    retrieval_text: >
      叫 名字是 姓名 名叫 叫做 名字叫 全名 客户叫 姓 姓氏 百家姓 姓什么 姓张 姓李 姓王 姓陈 名字带 名字含 名字包含 名字里有 名字中有
    field: searchClientName
    operator: MATCH
    value_type: extract
    description: "表示客户本人完整姓名，不表示家庭成员、被保人、投保人姓名"
    notes: '当查询直接出现完整中文姓名时，必须保留全名原样输出；如"陈成""李保""张无""金美"应输出完整姓名，不能截断为"陈""李""张""金"，也不能因为名字较少见而省略、跳过或判定为无效。只有明确出现"姓张""姓李"这类姓氏表达时，才可只取姓。'
    examples:
      - query: "叫张三的客户"
        output: {field: searchClientName, operator: MATCH, value: "张三"}
      - query: "名字是李四的客户"
        output: {field: searchClientName, operator: MATCH, value: "李四"}
      - query: "陈成"
        output: {field: searchClientName, operator: MATCH, value: "陈成"}
      - query: "姓张的客户"
        output: { field: searchClientName, operator: MATCH, value: "张" }
      - query: "名字带伟的客户"
        output: {field: searchClientName, operator: MATCH, value: "伟"}
      - query: "姓zhang的客户"
        output: { field: searchClientName, operator: MATCH, value: "zhang" }
    negative_examples:
      - query: "子女叫张三的客户"
        reason: "这是家庭成员姓名，应映射到 familyInfo.familyclientname 并组合 familyInfo.familyrelation"
