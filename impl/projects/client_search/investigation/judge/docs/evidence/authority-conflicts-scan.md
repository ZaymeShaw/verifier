# Authority conflict scan (observations only)

- Project: `client_search`
- Business source revision: `974c121667b2e34e7de47efd28b7c0c0d7983c7c`
- Value mappings: `src/main/python/data/client_search_query_parse/value_mappings_args.yaml`
  - SHA-256: `cb577c20260b6559d9c707cf3f9effa341d653936e8425c145f749c724e1f3a2`
- Field enums: `src/main/python/data/client_search_query_parse/field_enums_args.yaml`
  - SHA-256: `756787c382952c9d25fc9a6f4d31bc8ab7778535ab6ff04d5da604ef2df7b604`

## Method

For every `value_mappings` field with a same-name `field_enums` entry, report
each mapping target absent from that field's enum values list. This scan records
the observed conflict surface only; it does not decide which source is
authoritative.

## Revision recheck

- `onlyShareClientFlag` was added consistently to field definitions and field enums (`Y` only).
- No same-name value-mapping entry exists, so this addition creates no new mapping-vs-enum conflict.
- Address-rule changes are current parser behavior changes and do not alter the conflict scan method.

## Observed conflicts

| # | Field | Alias | Mapping target |
|---:|---|---|---|
| 1 | `newValueLabel` | `价值a` | `价值A` |
| 2 | `newValueLabel` | `价值b` | `价值B` |
| 3 | `newValueLabel` | `价值a或b` | `价值A或B` |
| 4 | `newValueLabel` | `a类` | `A类` |
| 5 | `newValueLabel` | `b类` | `B类` |
| 6 | `newValueLabel` | `c类` | `C类` |
| 7 | `newValueLabel` | `d类` | `D类` |
| 8 | `newValueLabel` | `e类` | `E类` |
| 9 | `newValueLabel` | `f类` | `F类` |
| 10 | `pCategorys` | `意外产品` | `意外保险` |
| 11 | `polNoInfo.plancodeinfo.plantypedesc` | `教育金` | `年金险` |
| 12 | `polNoInfo.plancodeinfo.plantypedesc` | `财富险` | `年金险` |
| 13 | `vipType` | `V1p` | `VIP` |
| 14 | `vipType` | `Vip` | `VIP` |
| 15 | `vipType` | `ViP` | `VIP` |
| 16 | `vipType` | `vIp` | `VIP` |
| 17 | `vipType` | `VIp` | `VIP` |
| 18 | `vipType` | `viP` | `VIP` |
| 19 | `vipType` | `vip` | `VIP` |
| 20 | `vipType` | `vIP` | `VIP` |
| 21 | `familyInfo.familyrelation` | `有娃` | `有子女` |
| 22 | `familyInfo.familyrelation` | `有孙辈` | `有(外)孙子女` |
| 23 | `familyInfo.familyrelation` | `有祖辈` | `有(外)祖父母` |
| 24 | `polNoInfo.polStatus` | `缴费正常生效` | `缴费有效` |
| 25 | `polNoInfo.polStatus` | `减额缴清` | `减额交情` |
| 26 | `polNoInfo.polStatus` | `保单过期` | `时效` |
| 27 | `polNoInfo.polStatus` | `保障关停` | `终止效率` |
| 28 | `polNoInfo.polStatus` | `主动停保` | `认为停效` |
| 29 | `pcustSourcType` | `o2o` | `O2O` |
| 30 | `pcustSourcType` | `O2o` | `O2O` |
| 31 | `pcustSourcType` | `o2O` | `O2O` |
| 32 | `pcustSourcType` | `意键险` | `意健险` |
| 33 | `zxjyMemberGradeInfo.zxjymembergradesearch` | `家医V1以上` | `臻享家医V1以上` |
| 34 | `zxjyMemberGradeInfo.zxjymembergradesearch` | `家医V1及以上` | `臻享家医V1及以上` |
| 35 | `zxjyMemberGradeInfo.zxjymembergradesearch` | `家医V2以上` | `臻享家医V2以上` |
| 36 | `zxjyMemberGradeInfo.zxjymembergradesearch` | `家医V2及以上` | `臻享家医V2及以上` |
| 37 | `pajjMemberGradeInfo.pajjmembergradesearch` | `居家V1+` | `平安居家V1及以上` |
| 38 | `pajjMemberGradeInfo.pajjmembergradesearch` | `居家v1+` | `平安居家V1及以上` |
| 39 | `pajjMemberGradeInfo.pajjmembergradesearch` | `居家V1以上` | `平安居家V1以上` |
| 40 | `pajjMemberGradeInfo.pajjmembergradesearch` | `居家v1以上` | `平安居家V1以上` |
| 41 | `pajjMemberGradeInfo.pajjmembergradesearch` | `居家V1及以上` | `平安居家V1及以上` |
| 42 | `pajjMemberGradeInfo.pajjmembergradesearch` | `居家v1及以上` | `平安居家V1及以上` |
| 43 | `pajjMemberGradeInfo.pajjmembergradesearch` | `居养老` | `居家养老` |
| 44 | `pajjMemberGradeInfo.pajjmembergradesearch` | `居养` | `居家养老` |
| 45 | `gdkyMemberGradeInfo.gdkymembergradesearch` | `康养PLUS以上` | `逸享PLUS会员以上` |
| 46 | `gdkyMemberGradeInfo.gdkymembergradesearch` | `康养PLUS及以上` | `逸享PLUS会员及以上` |
| 47 | `gdkyMemberGradeInfo.gdkymembergradesearch` | `高端康养PLUS会员以上` | `高端康养逸享PLUS会员以上` |
| 48 | `gdkyMemberGradeInfo.gdkymembergradesearch` | `高端康养PLUS会员及以上` | `高端康养逸享PLUS会员及以上` |
