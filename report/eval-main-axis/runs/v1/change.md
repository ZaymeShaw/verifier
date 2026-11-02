兑现轴补 demand/main_axis.md §4.3、§4.5、§4.7：如实说明 / 澄清只作附带期望；附带说法错的、核实不了的都挡（单位例外）；多轮时附各轮用户原话。

- `fulfillment.py`："办成看结果"后加一句附带期望规则；"真实性核验结果"一节加附带说法规则；多轮时 user_prompt_extras 加 `conversation`。
- `extract.py`：抽取的 question 改为用户各轮原话（`user_turns`）。
- `judge.py`（旧内置轴1）同步附带期望那句，保持与扩展轴提示词一致。
- 只跑开发集（43 条）。基线开发集 38/43，判错：hr-probation-side、hr-resign-side、B02 旧答案、neg-unknown、unit-policy-absent。
