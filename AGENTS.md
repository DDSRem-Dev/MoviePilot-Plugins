This file provides guidance to AI coding agents when working with code in this repository.

# MoviePilot-Plugins Project Conventions

## 1. Commit Conventions

Use **Conventional Commits** format for easier Changelog generation and semantic versioning.

### Format

```
<type>(<scope>): <subject>

[optional body]
[optional footer]

Co-authored-by: <AI Name> <ai-email@example.com>
```

- **type** (required): Commit type; see table below.
- **scope** (required): Affected scope, e.g. plugin name `p115strmhelper`, `migudiscover`, or area like `ci`, `deps`.
- **subject** (required): Short description, ~50 chars; no period at the end.
- **Co-authored-by** (required when AI is involved): Footer line attributing the AI assistant that contributed to the commit; use the **AI agent’s own identity** (its canonical name and email as defined in its system prompt), **not** a hardcoded example. For instance, an agent identifying as "Sisyphus" should use `Sisyphus <sisyphus@ohmyopenCode.com>`, while one identifying as "Cursor Agent" should use `Cursor Agent <cursoragent@cursor.com>`.

### Type Reference

| type     | Description                          |
|----------|--------------------------------------|
| feat     | New feature                          |
| fix      | Bug fix                              |
| docs     | Documentation only (README, comments)|
| style    | Code style (no logic change)         |
| refactor | Refactor (not new feature/fix)       |
| perf     | Performance improvement              |
| test     | Tests                                |
| chore    | Build/tooling/deps, etc.             |

### Examples

```
feat(p115strmhelper): support MCP tools/list and tools/call

Co-authored-by: Sisyphus <sisyphus@ohmyopenCode.com>
```

```
fix(p115strmhelper): fix offline task list pagination params

Co-authored-by: Sisyphus <sisyphus@ohmyopenCode.com>
```

### Rules

- Commit messages must be in English; keep language consistent across the repo.
- **AI Co-author required**: Commits made by or with assistance from an AI coding agent **must** include a `Co-authored-by:` line in the footer. The co-author must use the **AI agent's own identity** (its canonical name and email from its system prompt), not a hardcoded example. Use the agent that has a GitHub account so the co-author is linked correctly.
- One logical change per commit; split unrelated changes into separate commits.
- For breaking changes, describe in body or footer; use `BREAKING CHANGE:` when needed.

---

## 2. Python Coding Conventions

### 1. Style and Format

- Follow **PEP 8**: 4-space indent, line length ~88–120 chars, spaces around operators, etc.
- Strings: prefer double quotes `"`; use single quotes when embedding double quotes.
- Trailing commas: allowed at end of multi-line structures (lists, dicts, args) for cleaner diffs.
- **Comments** (`#` line comments) **and docstrings**: do not end a line with a terminal period (neither `.` nor Chinese `。`). Applies to summary lines and `:param` / `:return` / `:raises` lines alike.

### 2. Type Annotations

- Public functions and methods must have type annotations; internal helpers are encouraged.
- Use `typing`: `List`, `Dict`, `Optional`, `Any`, `Union`, `Tuple`, etc.
- Add docstring notes for complex or ambiguous parameters and return values.

```python
from typing import Any, Dict, List, Optional

async def run_tool(api: Any, name: str, arguments: Dict[str, Any]) -> str:
    ...
```

### 3. Import Order

1. Standard library (alphabetical)
2. Blank line
3. Third-party packages (alphabetical)
4. Blank line
5. Project/plugin relative imports (alphabetical)

```python
from pathlib import Path
from re import match as re_match
from time import sleep

from fastapi import Request
from orjson import dumps as orjson_dumps

from .api import Api
from .mcp import MCPManager
from .version import VERSION
```

### 4. Naming

- Modules/packages: lowercase with hyphens or underscores, e.g. `db_manager`, `mcp`.
- Classes: `CapWords`.
- Functions, methods, variables, parameters: `snake_case`.
- Constants: `UPPER_SNAKE_CASE`.
- Private implementation: single leading underscore `_internal_func`; module-level "private" may use `_`.

### 5. Exceptions and Logging

- Avoid bare `except:`; use at least `except Exception` and handle at an appropriate level.
- Use the project's shared `logger` (e.g. `from app.log import logger`) for errors and important info; use `logger.error(..., exc_info=True)` at exception sites for debugging.
- User-facing messages should be clear and actionable; internal logs may include more technical detail.

### 6. Async Code

- Use `async def` for async functions; call other async APIs with `await`. Avoid blocking calls inside async functions; wrap with `asyncio.to_thread` when needed.
- Keep the async call chain consistent; do not forget to await coroutines.

### 7. Integration with MoviePilot

- Plugin entry must inherit `_PluginBase` and implement `plugin_name`, `plugin_version`, etc. as required.
- Use the project's config prefix (e.g. `plugin_config_prefix`), events, and message channels so the interface matches the main app.
- Put dependencies in the plugin's `requirements.txt`; prefer `~=` for minor-version pinning.

---

## 3. Comments & Documentation Style

### 3.1 Docstring Rules

**All public classes, methods, and functions carry a Chinese docstring.**
Chinese is the project's working language for descriptive prose; symbol names
remain English.

#### Template

Docstring structure follows this order:

1. One-line summary description.
2. (Optional) Blank line + detailed description of behavior, edge cases, etc.
3. (Optional) Blank line + `:param` lines — one per parameter.
4. (Optional) Blank line + `:return` line.
5. (Optional) Blank line + `:raises` lines — one per exception type.
6. (Optional) `:yields` line.

Standard template:

```python
"""
<description>

<detail description>

:param <name> (<Type>): <description>

:return <Type>: <description>

:raises <ExceptionType>: <description>

:yields <Type>: <description>
"""
```

Concrete example:

```python
from pathlib import Path
from typing import List, Optional, Tuple

from app.schemas import FileItem


class P115Api:
    """
    115 网盘基础操作类
    """

    def get_pid_by_path(self, path: Path) -> int:
        """
        通过文件夹路径获取文件夹 ID

        :param path (Path): 文件夹路径

        :return int: 目录 ID
        """

    def create_folder(
        self, fileitem: FileItem, name: str
    ) -> Optional[FileItem]:
        """
        创建目录

        :param fileitem (FileItem): 父目录文件项
        :param name (str): 要创建的目录名称

        :return FileItem: 创建成功返回目录文件项，失败返回 None
        """

    def upload(
        self,
        target_dir: FileItem,
        local_path: Path,
        new_name: Optional[str] = None,
    ) -> Optional[FileItem]:
        """
        上传文件到云盘

        :param target_dir (FileItem): 上传目标目录项
        :param local_path (Path): 本地文件路径
        :param new_name (str): 上传后的文件名，如果为 None 则使用本地文件名（代码中为 Optional[str]，文档仅标注 str）

        :return FileItem: 上传成功返回文件项，失败返回 None
        """
```

Requirements:

- Triple-quoted `"""`, blank line on opening and closing edges.
- Chinese prose.
- Import generic containers from `typing`: use `List` / `Dict` / `Tuple` / `Optional`,
  and do not use Python-native generics such as `list[str]` or `tuple[int, ...]`.
  See `plugins.v2/p115disk/p115_api.py` for reference.
- Parameter form: `:param name (Type): description`.
- Return form: `:return Type: description` — single concrete type where
  possible.
- Raise form: `:raises ExceptionType: description`.
- Yield form: `:yields Type: description`.
- Blank line between description, params, return, raises, and yields blocks.

#### 3.1.1 Docstring Type Label Convention

Docstring type labels use only the **parent / container type**, excluding
`Optional` wrappers and inner type parameters. This keeps docstrings concise
and avoids duplicating verbose annotations already present in code.

| Code annotation              | Docstring label        | Reason                                    |
| ---------------------------- | ---------------------- | ----------------------------------------- |
| `Optional[List[str]]`        | `List`                 | Strip `Optional`, strip inner `[str]`     |
| `Optional[int]`              | `int`                  | Strip `Optional` wrapper                  |
| `Optional[Dict[str, int]]`   | `Dict`                 | Strip `Optional`, strip inner type params |
| `List[FileItem]`             | `List`                 | Container type only                       |
| `Dict[str, str]`             | `Dict`                 | Container type only                       |
| `Tuple[str, ...]`            | `Tuple`                | Container type only                       |
| `Generator[int, None, None]` | `Generator`            | Container type only                       |
| `str` / `int` / `bool`       | `str` / `int` / `bool` | Bare types unchanged                      |
| `Optional[str]`              | `str`                  | Strip `Optional` wrapper                  |

Examples from the codebase (`plugins.v2/p115disk/p115_api.py`):

```python
# p115_api.py — return stripped to container type, param types in parentheses
def list(self, fileitem: FileItem) -> List[FileItem]:
    """
    浏览文件或目录

    :param fileitem (FileItem): 文件项，可以是文件或目录

    :return List: 文件项列表，如果是文件则返回包含该文件的列表，如果是目录则返回目录下的所有文件和子目录
    """

# p115_api.py — bare types (str) unchanged, container types (List, Dict) bare
def iter_files(
    self, fileitem: FileItem
) -> Optional[List[FileItem]]:
    """
    递归遍历文件夹

    :param fileitem (FileItem): 文件项，可以是文件或目录

    :return List: 文件项列表
    """
```

#### 3.1.2 Attributes and Enum Variants

Class attributes, dataclass fields, and enum variant docstrings **must not**
appear as individual multiline docstrings beneath each member. Instead,
collect them into an `Attributes:` section inside the parent class/enum
docstring.

**Correct — collective Attributes section:**

```python
class StrmApiData(BaseModel):
    """
    API 调用生成 STRM 数据

    Attributes:
        id: 文件 ID
        name: 文件名
        sha1: 文件 SHA1
        size: 文件大小
        pick_code: 文件 pickcode
        local_path: 本地路径
        pan_path: 网盘路径
        pan_media_path: 网盘媒体库路径
        media_server_refresh: 是否刷新媒体服务器
        scrape_metadata: 是否刮削元数据
        auto_download_mediainfo: 是否自动下载媒体元数据
    """

    id: Optional[int] = Field(default=None, description="文件ID")
    name: Optional[str] = Field(default=None, description="文件名")
    sha1: Optional[str] = Field(default=None, description="文件SHA1")
    size: Optional[int] = Field(default=None, description="文件大小")
    pick_code: Optional[str] = Field(default=None, description="文件pickcode")
    local_path: Optional[str] = Field(default=None, description="本地路径")
    pan_path: Optional[str] = Field(default=None, description="网盘路径")
    pan_media_path: Optional[str] = Field(default=None, description="网盘媒体库路径")
    media_server_refresh: Optional[bool] = Field(
        default=None, description="是否刷新媒体服务器"
    )
    scrape_metadata: Optional[bool] = Field(default=None, description="是否刮削元数据")
    auto_download_mediainfo: bool = Field(
        default=False, description="是否自动下载媒体元数据"
    )
```

#### Where docstrings are required

- Every public class.
- Every public method / function.
- Every `@staticmethod` on a service or API class.
- Every Pydantic model field via `Field(description="...")`.

#### 3.1.3 Usage Examples in Docstrings

Do **not** include code usage examples inside docstrings. They bloat the
docstring, drift out of sync with the actual API, and distract from the
contract description. If an example is genuinely helpful, put it in a
dedicated `examples/` directory or a test file.

**Correct — describe the contract, not the usage:**

```python
class P115Api:
    """
    115 网盘基础操作类

    封装 115 网盘的文件列表、上传下载、目录管理、快照等核心操作
    提供限速、缓存和错误重试机制
    """
```

#### 3.1.4 Line Separator Comments

Do **not** use line-separator comments (`# ── … ──`) to visually group
sections inside a file. They add noise, break searchability, and duplicate
what structural elements (classes, blank lines, import groups) already
provide.

**Correct — plain fields, no separators:**

```python
_enabled = False
_client = None
_disk_name = None
_p115_api = None
_cookie = None
```

#### Where docstrings are optional

- Private helpers (`_prefix`) — docstring when behavior is non-obvious,
  otherwise skip.
- Trivial one-line lambdas / factories.

### 3.2 Inline Comment Rules

Default to **no inline comments**. Code should explain *what* it does through
clear names and shape. Add a comment only when the **why** is non-obvious.

Write comments for:

- Protection / risk-control trade-offs (`# 防止误删：旧路径与新生成路径相同（原地 move 场景）`).
- Version-specific workarounds with an expiry condition (`# 检查 token 是否即将过期（提前 5 分钟刷新）`).
- Version-specific workarounds with an expiry condition.

Do **not** write comments that:

- Restate code (`# increment counter`).
- Describe the current task, PR, or reviewer handoff.
- Mark removed code (`# was: xyz()`) — Git history is authoritative.

### 3.3 Field Descriptions in Pydantic Models

```python
from typing import Optional

from pydantic import BaseModel, Field


class StrmApiData(BaseModel):
    """
    API 调用生成 STRM 数据
    """

    id: Optional[int] = Field(default=None, description="文件ID")
    name: Optional[str] = Field(default=None, description="文件名")
    sha1: Optional[str] = Field(default=None, description="文件SHA1")
    size: Optional[int] = Field(default=None, description="文件大小")
    pick_code: Optional[str] = Field(default=None, description="文件pickcode")
    local_path: Optional[str] = Field(default=None, description="本地路径")
    pan_path: Optional[str] = Field(default=None, description="网盘路径")
```

Descriptions are mandatory and in Chinese; they become the single source of
truth used by docs and log-formatting helpers.

### 3.4 Deprecation Markers

```python
# @deprecated: use P115Api.create_folder instead — removal in v0.3.0.
def legacy_mkdir(...):
    ...
```

- Must cite the replacement.
- Must cite a removal milestone (version, date, or release tag).
- Deprecated code is removed within one minor release of the marker —
  no `// removed` tombstones left behind.

### 3.5 Changelog

Release notes are generated from commit messages in this repository.
Keep commit subjects descriptive enough to be published verbatim.

---

## 4. Quick Checklist

**Before committing:**

- [ ] Message follows type(scope): subject format
- [ ] Footer includes `Co-authored-by: <AI Name> <email>` when AI contributed
- [ ] New/changed public API has type annotations and docstrings
- [ ] Imports are ordered correctly; no unused imports
- [ ] Exception handling and logging are appropriate

**During review:**

- [ ] Logic is correct; edge cases and error paths considered
- [ ] No hardcoded secrets (keys, tokens)
- [ ] Consistent with existing plugin style and MoviePilot conventions

*Last Updated: 2026-06-04*
