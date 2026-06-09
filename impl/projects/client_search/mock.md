# Mock

V1 mock cases should cover single-query and multi-condition customer-search intents using current `projects/client_search/prompt.md` rules and `projects/client_search/config.md` field definitions.

Seed cases:

- `45岁女性保费10万以上`
- `有生存金未领取的客户`
- `年缴保费一万以上的客户`
- `45岁以上女性客户`
- `买了年金险或两全险的客户`
- `大于50岁的客户`
- `只有重疾险的客户`
- `上有老下有小的客户`

Mock guidance:

- Expected intent should be written in business language first.
- Field-level expectations are allowed here because this file belongs to the client_search project implementation, not generic core.
- Mock cases should include exact age, age boundary wording, amount unit conversion, enum/contains conditions, and multi-condition AND semantics.
- Do not use one historical case to judge unrelated cases.
