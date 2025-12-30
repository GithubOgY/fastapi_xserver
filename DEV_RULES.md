# Development Rules

## Command Execution (PowerShell)

The development environment uses Windows PowerShell (v5.1 default).

**Rule: Do NOT use `&&` for command chaining.**
The `&&` operator is not supported in this version.

- ❌ **Incorrect:** `command1 && command2`
- ✅ **Correct:** `command1 ; command2`

Always use `;` to separate commands or execute them in separate steps.
