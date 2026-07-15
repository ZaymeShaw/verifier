# Issue Manager Implementation - Settings Patch

Add the following to `.claude/settings.json` in the "hooks" section:

```json
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /Users/xiaozijian/WorkSpace/projects/claude_code/verifier-branch2/verifier/hooks/issue-reminder/session-start.py",
            "timeout": 30,
            "statusMessage": "Issue-Reminder: 扫描 active/ 目录显示正在处理的 issue"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /Users/xiaozijian/WorkSpace/projects/claude_code/verifier-branch2/verifier/.claude/hooks/git-pre-command.py",
            "timeout": 10,
            "statusMessage": "Issue-Manager PreCommand: 检查 git checkout/pull 前的未提交改动"
          }
        ]
      }
    ],
```

Insert between "WorktreeRemove" and "Stop" hooks.
