# Agno 最简化使用方法

## 最简化使用方法

最简单的 Agno 使用方式只需要 3 步：导入、创建 Agent、运行：

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="You are a helpful assistant",
    markdown=True,
)
agent.print_response("Your query", stream=True)
``` [1](#0-0) 

## 重要参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `model` | 使用的 LLM 模型 | `OpenAIResponses(id="gpt-5.5")` [2](#0-1)  |
| `instructions` | Agent 的系统指令 | `"You are a helpful assistant"` [3](#0-2)  |
| `tools` | Agent 可用的工具列表 | `[WebSearchTools()]` [4](#0-3)  |
| `markdown` | 启用 Markdown 输出 | `markdown=True` [5](#0-4)  |
| `description` | Agent 描述 | 用于 AgentOS 注册时的说明 |
| `enable_agentic_memory` | 启用智能记忆 | 让 Agent 记住用户偏好 [6](#0-5)  |
| `add_history_to_context` | 添加历史到上下文 | 包含之前的对话历史 [7](#0-6)  |

## 最简单的 Tool 封装

使用 `@tool` 装饰器创建自定义工具：

```python
from agno.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"Weather in {city}: Sunny, 72F"

agent = Agent(tools=[get_weather])
``` [8](#0-7) 

## 完整示例：带工具的 Agent

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    name="Tool-Enabled Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[DuckDuckGoTools()],
)

agent.print_response("Find one recent AI safety headline", stream=True)
``` [9](#0-8) 

## Notes

- **性能关键**：永远不要在循环中创建 Agent，应该创建一次并重复使用 [10](#0-9) 
- **模型选择**：Agno 支持多种模型提供商（OpenAI、Anthropic、Google Gemini 等），可通过字符串语法如 `"openai:gpt-4o"` 快速切换
- **内置工具**：除了自定义工具，Agno 还提供 100+ 预构建工具包（YFinance、DuckDuckGo、GitHub 等） [11](#0-10) 

Wiki pages you might want to explore:
- [Quick Start Guide (agno-agi/agno)](/wiki/agno-agi/agno#1.1)
- [Examples and Patterns (agno-agi/agno)](/wiki/agno-agi/agno#10)
- [AI-Assisted Development (agno-agi/agno)](/wiki/agno-agi/agno#9.4)

### Citations

**File:** .cursorrules (L13-24)
```text
Basic Agent (start here):
```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="You are a helpful assistant",
    markdown=True,
)
agent.print_response("Your query", stream=True)
```
```

**File:** .cursorrules (L32-32)
```text
    tools=[WebSearchTools()],
```

**File:** .cursorrules (L37-47)
```text
CRITICAL: Agent Reuse Performance
```python
# WRONG - Recreates agent every time (significant overhead)
for query in queries:
    agent = Agent(...)  # DON'T DO THIS
    
# CORRECT - Create once, reuse
agent = Agent(...)
for query in queries:
    agent.run(query)
```
```

**File:** cookbook/05_agent_os/dbs/surreal_db/agents.py (L24-25)
```python
    # Enable agentic memory
    enable_agentic_memory=True,
```

**File:** cookbook/05_agent_os/dbs/surreal_db/agents.py (L26-27)
```python
    # Add the previous session history to the context
    add_history_to_context=True,
```

**File:** cookbook/91_tools/README.md (L16-25)
```markdown
```python
from agno.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"Weather in {city}: Sunny, 72F"

agent = Agent(tools=[get_weather])
```
```

**File:** cookbook/02_agents/01_quickstart/agent_with_tools.py (L8-27)
```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Tool-Enabled Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[DuckDuckGoTools()],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Find one recent AI safety headline and summarize it.", stream=True
    )
```

**File:** cookbook/README.md (L57-58)
```markdown
### Tools
[91_tools](./91_tools) — Extend what agents can do. Web search, SQL, email, APIs, MCP, Discord, Slack, Docker, and custom tools with the `@tool` decorator.
```
