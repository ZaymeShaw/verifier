# client_search 姓名匹配口径（样例资料）

「客户姓名是张伟」「张伟」这类全名查询：

- 匹配模式应为姓名全值等值匹配，不是前缀、不是姓氏。
- 若接口只做前缀模糊（match_mode=prefix），属于能力范围外，应明确说明并拒绝，而不是默默改写。

引用方式（在能力描述 / 能力边界里写，必须有 {} 定界）：

```text
匹配规则见 {material://llm_probe/client-search-match-rule}
```
