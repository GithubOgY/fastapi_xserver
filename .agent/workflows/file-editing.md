---
description: File editing guidelines to prevent encoding issues
---

# File Editing Guidelines

## IMPORTANT: Do NOT use PowerShell to edit file contents

### Rule
Never use PowerShell commands like `Set-Content`, `Get-Content -Raw | ... | Set-Content`, or string replacement via PowerShell to modify file contents.

### Reason
PowerShell on Windows defaults to Windows encoding (Shift-JIS/CP932), not UTF-8. When editing UTF-8 files containing Japanese or other non-ASCII characters, this causes character corruption (mojibake/文字化け).

### Correct Approach
Always use the following tools for file editing:
- `replace_file_content` - for single contiguous edits
- `multi_replace_file_content` - for multiple non-contiguous edits
- `write_to_file` - for creating new files or overwriting entirely

### Exception
PowerShell commands are acceptable for:
- Reading file metadata (size, existence)
- Git operations
- Running applications
- Creating/deleting empty files or directories
