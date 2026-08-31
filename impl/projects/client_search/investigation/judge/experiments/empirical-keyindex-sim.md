# Empirical Key-Index Simulation (V0–V3)

Generated: 2026-08-13 00:20 UTC+8

## Scope

- Offline deterministic Search→Load style harness only.
- **Not** selected / promoted / solidified. No Draft skill edits.
- Source-derived projections only (field YAML examples/notes/retrieval_text; rule name/patterns/field; abbrname exact values).

### Variants

| ID | Definition |
|---|---|
| V0 | Current field Builder projection (`field+retrieval_text+description`, first intent/field) + char-heuristic |
| V1 | Field projection aggregates all intents; includes `examples.query` + `notes` + retrieval_text; fused exact+IDF lexical |
| V2 | V1 field index + enhanced_rules (name/patterns/field) Search→load rule subtree + abbrname **exact** membership |
| V3 | V1 projection + allow 2-char stem / query⊂phrase when longer phrase literally in source projection |

- Entry counts: field_v0=120, field_v1=120, rules=761, abbrname=8328
- Queries: labeled=38, stress_deduped=352, focus=11, style_extra=1

### Projection smoke

```json
{
  "v0": {
    "n_entries": 120,
    "关爱客户_in_clientAge": false,
    "有钱客户_in_newValueLabel": true,
    "盘客_in_customerReview": true,
    "金凤_anywhere": false
  },
  "v1": {
    "n_entries": 120,
    "关爱客户_in_clientAge": true,
    "有钱客户_in_newValueLabel": true,
    "盘客_in_customerReview": true,
    "金凤_anywhere": false
  },
  "rules": {
    "n": 761,
    "关爱客户": true,
    "有钱": true,
    "盘客": true,
    "O2O": true
  },
  "abbr": {
    "n": 8328,
    "金凤": true
  }
}
```

## Headline labeled metrics

| variant | dev top8 | dev irr_rej | holdout top8 | holdout irr_rej | stress empty | avg hits | load_success |
|---|---:|---:|---:|---:|---:|---:|---:|
| V0 | 0.727 | 0.556 | 0.400 | 0.000 | 0.031 | 7.56 | 1.000 |
| V1 | 0.773 | 0.556 | 0.200 | 0.667 | 0.026 | 7.51 | 1.000 |
| V2 | 0.773 | 0.556 | 0.200 | 0.667 | 0.017 | 7.55 | 1.000 |
| V3 | 0.773 | 0.556 | 0.200 | 0.667 | 0.020 | 7.53 | 1.000 |

## Focus query table

### V0

| query | bucket | qual | hits (collection:key) |
|---|---|---|---|
| `关爱客户` | business_noun | **MISS** | ∅ |
| `有钱` | business_noun | **MISS** | ∅ |
| `有钱客户` | business_noun | **MISS** | ∅ |
| `金凤` | business_noun | **MISS** | ∅ |
| `盘客` | business_noun | **MISS** | ∅ |
| `去盘客` | business_noun | **OK** | field:customerReview |
| `A` | latin_bareword | **OK** | ∅ |
| `O2O` | latin_bareword | **MISS** | ∅ |
| `陈金秀` | person_name | **MISS** | ∅ |
| `天气怎么样` | irrelevant_like | **FALSE** | field:ayhMemberGradeInfo.ayhmemberproductname, field:ayyMemberGradeInfo.ayymemberproductname, field:carInsuranceMatuDateTime, field:gdkyMemberGradeInfo.gdkymemberproductname, field:pajjMemberGradeInfo.pajjmemberproductname, field:polNoInfo.poleffdate |
| `客户平时有什么兴趣爱好` | unsupported_like | **FALSE** | field:gdkyMemberGradeInfo.gdkymembergradesearch, field:gdkyMemberGradeInfo.gdkymemberperiod, field:gdkyMemberGradeInfo.gdkyqualifiedtime, field:pajjMemberGradeInfo.pajjmembergradesearch, field:pajjMemberGradeInfo.pajjmemberperiod, field:pajjMemberGradeInfo.pajjqualifiedtime |

I078/I036/I210-style iteration queries:
- `关爱客户` → MISS | ∅

### V1

| query | bucket | qual | hits (collection:key) |
|---|---|---|---|
| `关爱客户` | business_noun | **OK** | field:clientAge, field:isBuyInsurance |
| `有钱` | business_noun | **MISS** | ∅ |
| `有钱客户` | business_noun | **OK** | field:newValueLabel, field:isBuyInsurance |
| `金凤` | business_noun | **MISS** | ∅ |
| `盘客` | business_noun | **OK** | field:customerReview |
| `去盘客` | business_noun | **OK** | field:customerReview |
| `A` | latin_bareword | **OK** | ∅ |
| `O2O` | latin_bareword | **OK** | field:pcustSourcType, field:validSinsPol |
| `陈金秀` | person_name | **MISS** | ∅ |
| `天气怎么样` | irrelevant_like | **OK** | ∅ |
| `客户平时有什么兴趣爱好` | unsupported_like | **FALSE** | field:isBuyInsurance, field:pajjMemberGradeInfo.pajjmemberproductname, field:pajjMemberGradeInfo.pajjmembergradesearch, field:pajjMemberGradeInfo.pajjmemberperiod, field:pajjMemberGradeInfo.pajjmemberstatus, field:pajjMemberGradeInfo.pajjqualifiedtime |

I078/I036/I210-style iteration queries:
- `关爱客户` → FALSE | field:clientAge, field:isBuyInsurance

### V2

| query | bucket | qual | hits (collection:key) |
|---|---|---|---|
| `关爱客户` | business_noun | **OK** | enhanced_rules:关爱客户-40岁及以上女性, field:clientAge, field:isBuyInsurance |
| `有钱` | business_noun | **OK** | enhanced_rules:客户价值-高价值, enhanced_rules:最近半年未联系的高价值客户 |
| `有钱客户` | business_noun | **OK** | field:newValueLabel, field:isBuyInsurance |
| `金凤` | business_noun | **OK** | abbrname:金凤 |
| `盘客` | business_noun | **OK** | enhanced_rules:盘客-暂不支持, field:customerReview |
| `去盘客` | business_noun | **OK** | field:customerReview |
| `A` | latin_bareword | **OK** | ∅ |
| `O2O` | latin_bareword | **OK** | enhanced_rules:准客来源-简称, field:pcustSourcType, field:validSinsPol |
| `陈金秀` | person_name | **MISS** | ∅ |
| `天气怎么样` | irrelevant_like | **OK** | ∅ |
| `客户平时有什么兴趣爱好` | unsupported_like | **FALSE** | field:isBuyInsurance, field:pajjMemberGradeInfo.pajjmemberproductname, field:pajjMemberGradeInfo.pajjmembergradesearch, field:pajjMemberGradeInfo.pajjmemberperiod, field:pajjMemberGradeInfo.pajjmemberstatus, field:pajjMemberGradeInfo.pajjqualifiedtime |

I078/I036/I210-style iteration queries:
- `关爱客户` → FALSE | enhanced_rules:关爱客户-40岁及以上女性, field:clientAge, field:isBuyInsurance

### V3

| query | bucket | qual | hits (collection:key) |
|---|---|---|---|
| `关爱客户` | business_noun | **OK** | field:clientAge, field:isBuyInsurance |
| `有钱` | business_noun | **OK** | field:newValueLabel |
| `有钱客户` | business_noun | **OK** | field:newValueLabel, field:isBuyInsurance |
| `金凤` | business_noun | **MISS** | ∅ |
| `盘客` | business_noun | **OK** | field:customerReview |
| `去盘客` | business_noun | **OK** | field:customerReview |
| `A` | latin_bareword | **OK** | ∅ |
| `O2O` | latin_bareword | **OK** | field:pcustSourcType, field:validSinsPol |
| `陈金秀` | person_name | **MISS** | ∅ |
| `天气怎么样` | irrelevant_like | **OK** | ∅ |
| `客户平时有什么兴趣爱好` | unsupported_like | **FALSE** | field:isBuyInsurance, field:pajjMemberGradeInfo.pajjmemberproductname, field:pajjMemberGradeInfo.pajjmembergradesearch, field:pajjMemberGradeInfo.pajjmemberperiod, field:pajjMemberGradeInfo.pajjmemberstatus, field:pajjMemberGradeInfo.pajjqualifiedtime |

I078/I036/I210-style iteration queries:
- `关爱客户` → FALSE | field:clientAge, field:isBuyInsurance


## Solves old problems? (MISS→OK flips)

| query | V0 | V1 | V2 | V3 |
|---|---|---|---|---|
| `关爱客户` | MISS | OK | OK | OK |
| `有钱` | MISS | MISS | OK | OK |
| `有钱客户` | MISS | OK | OK | OK |
| `金凤` | MISS | MISS | OK | MISS |
| `盘客` | MISS | OK | OK | OK |
| `去盘客` | OK | OK | OK | OK |

## New problems / false accepts

| variant | weather | hobby | latin A | 陈金秀 | stress irr/unsup false-accept proxy |
|---|---|---|---|---|---|
| V0 | FALSE | FALSE | OK | MISS | {'irrelevant_like': 1, 'unsupported_like': 1} |
| V1 | OK | FALSE | OK | MISS | {'unsupported_like': 1} |
| V2 | OK | FALSE | OK | MISS | {'unsupported_like': 1} |
| V3 | OK | FALSE | OK | MISS | {'unsupported_like': 1} |

## Stress buckets

### V0

| bucket | n | with_hits | empty |
|---|---:|---:|---:|
| business_noun | 14 | 10 | 4 |
| irrelevant_like | 1 | 1 | 0 |
| iteration_case | 30 | 26 | 4 |
| latin_bareword | 2 | 0 | 2 |
| other | 300 | 300 | 0 |
| person_name | 1 | 0 | 1 |
| person_name_context | 3 | 3 | 0 |
| unsupported_like | 1 | 1 | 0 |

### V1

| bucket | n | with_hits | empty |
|---|---:|---:|---:|
| business_noun | 14 | 12 | 2 |
| irrelevant_like | 1 | 0 | 1 |
| iteration_case | 30 | 26 | 4 |
| latin_bareword | 2 | 1 | 1 |
| other | 300 | 300 | 0 |
| person_name | 1 | 0 | 1 |
| person_name_context | 3 | 3 | 0 |
| unsupported_like | 1 | 1 | 0 |

### V2

| bucket | n | with_hits | empty |
|---|---:|---:|---:|
| business_noun | 14 | 14 | 0 |
| irrelevant_like | 1 | 0 | 1 |
| iteration_case | 30 | 27 | 3 |
| latin_bareword | 2 | 1 | 1 |
| other | 300 | 300 | 0 |
| person_name | 1 | 0 | 1 |
| person_name_context | 3 | 3 | 0 |
| unsupported_like | 1 | 1 | 0 |

### V3

| bucket | n | with_hits | empty |
|---|---:|---:|---:|
| business_noun | 14 | 13 | 1 |
| irrelevant_like | 1 | 0 | 1 |
| iteration_case | 30 | 27 | 3 |
| latin_bareword | 2 | 1 | 1 |
| other | 300 | 300 | 0 |
| person_name | 1 | 0 | 1 |
| person_name_context | 3 | 3 | 0 |
| unsupported_like | 1 | 1 | 0 |

## Empirical answer (parent summary)

### Did V1/V2/V3 actually help?
**Yes, on Auth-OFF focus nouns — with clear division of labor:**

| old miss | fixed by | mechanism (measured) |
|---|---|---|
| 关爱客户 | V1/V2/V3 | V1 projection adds source `examples.query` → loads `clientAge` (+ V2 also loads rule `关爱客户-40岁及以上女性`) |
| 盘客 | V1/V2/V3 | V1 fused exact/lexical on projected `customerReview` text (V0 char-heuristic scored only 1 after ignoring 客) |
| 有钱 | V2 + V3 only | V3: 2-char stem `有钱`⊂`有钱客户` in field projection → `newValueLabel`; V2: rule patterns → `客户价值-高价值` |
| 金凤 | **V2 only** | abbrname **exact** membership; absent from field Collection entirely (smoke confirmed) |

V1 alone is **not** enough for `有钱` (matcher `len>=3` gate) or `金凤` (wrong Collection).

### What broke / new problems?
1. **Hobby false-accept persists** on V1/V2/V3 (`客户平时有什么兴趣爱好` → `isBuyInsurance` + member-grade fields). Weather false-accept is **fixed** vs V0 char-heuristic.
2. **Companion field noise**: `关爱客户`/`有钱客户` also surface `isBuyInsurance` via lexical overlap — navigable but imprecise.
3. **Holdout generalization regresses vs V0 on top8**: holdout top8 0.40→0.20 while irr_rej improves 0.00→0.67. Dual thresholds still **fail** on both splits for all variants (dev irr_rej=0.556 < 1.0; holdout top8=0.20 < 0.85).
4. **Person names**: `陈金秀` stays empty (MISS for name navigation) — examples projection did **not** spuriously index this name (good), but also does not route name queries.
5. **V2 rule router is brittle**: early loose `pattern⊂query` caused over-broad rule hits (`客户` in `关爱客户`); final harness uses query⊂pattern / long-pattern⊂query only. Enum exact for abbrname did **not** false-positive on focus names.
6. **Stress empty_rate ~0.02–0.03 is NOT a success signal** here: avg hits ≈7.5 means almost every long Chinese xlsx query gets field hits. Compare prior batch empty≈0.35 under different candidate mix; this run’s V0 char-heuristic over-fires on `other` (300/300 with hits).

### Generalization? (numbers)
- **Frozen labeled**: no variant clears dual gates. Best auth-noun fix (V2) still holdout top8=**0.200**, holdout irr_rej=**0.667**, dev irr_rej=**0.556**.
- **Unseen paraphrases**: still the failure mode (holdout).
- **Latin barewords**: `O2O` flips MISS→OK on V1+ (field retrieval_text / rules); bare `A` correctly empty.
- **Enum nouns**: only V2 generalizes (`金凤` exact).
- **Load path**: load_success=**1.0** wherever hits exist (Search→Load healthy).

### Not a selection claim
Field experiment remains unresolved for formal Key-Index selection. Empirical takeaway for next Investigate: combine **V1 projection + V3 2-char stem** for field Collection, and a **separate** V2-style rules/abbrname router — do not expect field-only Index to own 金凤.

Harness: `draft-run/run_empirical_keyindex_sim.py`
