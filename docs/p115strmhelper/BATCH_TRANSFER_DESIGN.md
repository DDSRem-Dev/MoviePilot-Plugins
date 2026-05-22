# 115网盘批量整理模块设计文档

## 目录

- [概述](#概述)
- [设计思路](#设计思路)
- [架构设计](#架构设计)
- [与 MoviePilot 的关系](#与-moviepilot-的关系)
- [核心组件](#核心组件)
- [处理流程](#处理流程)
- [关键实现细节](#关键实现细节)
- [数据流](#数据流)
- [与 MoviePilot 的差异](#与-moviepilot-的差异)
- [字幕与音轨两种模式](#字幕与音轨两种模式)
- [注意事项](#注意事项)

---

## 概述

本模块实现了 115网盘到115网盘的**批量整理功能**，通过 Monkey Patching 拦截 MoviePilot 的整理流程，将原本的单文件逐个处理改为批量处理，大幅提升整理效率。

### 核心目标

1. **性能优化**：将多个文件的移动/复制操作合并为批量 API 调用
2. **功能对等**：保持与 MoviePilot 原整理逻辑的 100% 功能对等
3. **无缝集成**：通过补丁机制，对 MoviePilot 透明，不影响其他存储模块

---

## 设计思路

### 为什么需要批量处理？

MoviePilot 的原始整理逻辑是**单文件逐个处理**：
- 每个文件独立调用 API
- 每个文件独立记录历史
- 每个文件独立发送通知

对于 115网盘这种支持批量操作的存储，这种方式效率低下：
- 100 个文件需要 100 次 API 调用
- 批量操作可以合并为 1-2 次 API 调用

### 设计原则

1. **最小侵入**：通过 Monkey Patching 拦截，不修改 MoviePilot 源码
2. **功能完整**：实现 MoviePilot 原逻辑的所有功能点
3. **状态同步**：确保 MoviePilot 的 `jobview` 状态与插件处理结果一致
4. **错误处理**：任何步骤失败都能正确记录并阻止后续处理

---

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    MoviePilot TransferChain                  │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  __handle_transfer(task)                            │   │
│  │  ├─ 识别媒体信息                                     │   │
│  │  ├─ 获取目标目录                                     │   │
│  │  └─ [被拦截] → TransferChainPatcher                 │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              TransferChainPatcher (补丁层)                    │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  _patched_handle_transfer()                          │   │
│  │  ├─ 执行 MoviePilot 的识别/目录逻辑                   │   │
│  │  ├─ 判断：115 → 115？                                │   │
│  │  └─ 是 → 创建 PluginTransferTask                     │   │
│  │      └─ 加入 TransferTaskManager 队列                │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│            TransferTaskManager (任务队列管理)                 │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  add_task(task)                                      │   │
│  │  ├─ 加入 _pending_tasks 队列                          │   │
│  │  ├─ 重置延迟定时器（10秒）                            │   │
│  │  └─ 达到 batch_max_size → 立即触发                    │   │
│  │                                                       │   │
│  │  _trigger_batch_process()                             │   │
│  │  ├─ 取出所有待处理任务                                │   │
│  │  ├─ 标记 _processing = True                           │   │
│  │  └─ 调用 TransferHandler.process_batch()              │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              TransferHandler (批量处理执行器)                  │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  process_batch(tasks)                                │   │
│  │  ├─ 关闭关联整理：批次排序（字幕→音频→其它→主视频）   │   │
│  │  ├─ 关联整理（默认开启）：发现 related_files，走 linked │   │
│  │  ├─ _batch_create_directories[_linked]()             │   │
│  │  ├─ _batch_move_or_copy[_linked]()                   │   │
│  │  ├─ _batch_rename_files[_linked]()                   │   │
│  │  ├─ _record_history[_linked]()                       │   │
│  │  └─ _batch_delete_empty_dirs()      # 删除空目录       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              MoviePilot JobManager (状态同步)                │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  finish_task() / fail_task()                        │   │
│  │  is_finished() / is_done()                          │   │
│  │  remove_job()                                        │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 与 MoviePilot 的关系

### 拦截点

**位置**：`TransferChain.__handle_transfer`

**时机**：在 MoviePilot 完成以下步骤后拦截：
1. ✅ 媒体信息识别（`mediainfo`）
2. ✅ 目标目录计算（`target_directory`）
3. ✅ 任务状态标记（`running_task`）

**拦截条件**：
- 源存储 = 目标存储 = `115网盘Plus`
- 文件类型 = `file`（目录/蓝光原盘回退到原方法）
- **字幕/音频**：与 MoviePilot 一致，作为**独立** `TransferTask` 入队并批量处理（不再「忽略后由主视频捎带」）

### 职责划分

| 组件 | 职责 | MoviePilot 原逻辑 |
|------|------|------------------|
| **TransferChainPatcher** | 拦截判断、任务转换 | 不涉及 |
| **TransferTaskManager** | 任务队列、批量触发 | `TransferChain._queue` |
| **TransferHandler** | 批量文件操作 | `TransHandler.transfer_media` |
| **JobManager** | 任务状态管理 | MoviePilot 原生 |
| **TransferHistoryOper** | 历史记录 | MoviePilot 原生 |

### 关键同步点

1. **任务状态同步**：
   - 拦截时：调用 `chain.jobview.running_task(task)`
   - 成功时：调用 `chain.jobview.finish_task(mp_task)`
   - 失败时：调用 `chain.jobview.fail_task(mp_task)`

2. **队列清理**：
   - 按媒体组检查 `is_finished()` / `is_done()`
   - 调用 `chain.jobview.remove_job(mp_task)` 移除已完成组

3. **历史记录**：
   - 使用 MoviePilot 的 `TransferHistoryOper.add_success/add_fail`
   - 保持与 MoviePilot 历史记录格式一致

---

## 核心组件

### 1. TransferChainPatcher

**文件**：`plugins.v2/p115strmhelper/patch/transfer_chain.py`

**职责**：
- Monkey Patching `TransferChain.__handle_transfer`
- 判断是否应该拦截（115 → 115）
- 转换 MoviePilot `TransferTask` → 插件 `TransferTask`
- 加入批量队列

**关键方法**：
- `enable()`: 启用补丁
- `_patched_handle_transfer()`: 拦截后的处理逻辑
- `_should_intercept()`: 判断是否拦截
- `_derive_transfer_flags()`: 与 `filemanager.transfer()` 一致推导 `need_rename` / `need_notify` / `need_scrape`
- `_compute_target_path()`: 与 `TransHandler.transfer_media` 单文件分支一致（含 `need_rename`、字幕 `__rename_subtitles`）

### 2. TransferTaskManager

**文件**：`plugins.v2/p115strmhelper/helper/transfer/task.py`

**职责**：
- 管理待处理任务队列
- 延迟批量触发（默认 10 秒）
- 批量大小控制（默认 100）

**关键特性**：
- **延迟触发**：新任务到达时重置定时器，10秒后触发
- **批量上限**：达到 `batch_max_size` 立即触发
- **连续处理**：批量处理完成后，自动检查队列并触发下一批

**关键方法**：
- `add_task()`: 添加任务到队列
- `_trigger_batch_process()`: 触发批量处理
- `_reset_timer()`: 重置延迟定时器

### 3. TransferHandler

**文件**：`plugins.v2/p115strmhelper/helper/transfer/handler.py`

**职责**：
- 执行批量文件操作
- 记录历史
- 同步 MoviePilot 状态

**关键方法**：
- `process_batch()`: 批量处理主流程（**默认**开启关联整理时先 `discover_related_files` 再走 linked；关闭该项时用 `_sort_tasks_for_batch`）
- `_batch_create_directories()` / `TransferHandlerLinkedBatch.batch_create_directories()`: 批量创建目录
- `_batch_move_or_copy()` / `TransferHandlerLinkedBatch.batch_move_or_copy()`: 批量移动/复制
- `_batch_rename_files()` / `TransferHandlerLinkedBatch.batch_rename_files()`: 批量重命名
- `_record_history()` / `TransferHandlerLinkedBatch.record_history()`: 记录历史
- `_batch_delete_empty_dirs()`: 删除空目录

**关联模式实现文件**：[`handler_linked_batch.py`](../../plugins.v2/p115strmhelper/helper/transfer/handler_linked_batch.py)（`TransferHandler` 在 `__init__` 中持有 `self._linked_batch` 并委托调用）

**辅助方法**：
- `_create_mp_task()`: 创建 MoviePilot TransferTask
- `_group_tasks_by_media()`: 按媒体分组
- `_remove_completed_jobs()`: 移除已完成任务组

### 4. TransferTask (插件)

**文件**：`plugins.v2/p115strmhelper/schemas/transfer.py`

**数据结构**（节选）：
```python
@dataclass
class TransferTask:
    fileitem: FileItem
    target_path: Path
    mediainfo: MediaInfo
    meta: MetaBase
    transfer_type: str
    overwrite_mode: Optional[str]
    need_rename: bool
    need_notify: Optional[bool]
    need_scrape: bool
    # downloader / download_hash / manual / background / username 等
```

**与 MoviePilot TransferTask 的区别**：
- 插件版本：包含已计算的 `target_path`，以及与 `filemanager.transfer()` 对齐的 `need_rename` / `need_notify` / `need_scrape`
- MoviePilot 版本：含 `target_directory`，由 `transfer_media` 内部推导上述标志
- **`related_files`**：仅在开启「关联整理」时使用（见下节）；**默认开启**下会按关联路径发现并填充；关闭该项时 `related_files` 为空列表，字幕/音轨与 MoviePilot 一致为独立任务

---

## 字幕与音轨两种模式

插件配置 **`pan_transfer_linked_subtitle_audio`**（默认 **`true`**，默认开启关联整理）：

| 设置 | 含义 |
|------|------|
| **true（默认）** | **关联整理**：补丁层对 `RMT_SUBEXT` / `RMT_AUDIOEXT` 的独立任务不入队，直接 `finish_task`（随主文件处理）；批量层按源目录 **发现** 同目录字幕/音轨并写入 `related_files`，由 [`handler_linked_batch.py`](../../plugins.v2/p115strmhelper/helper/transfer/handler_linked_batch.py) 的 `TransferHandlerLinkedBatch` 执行批量目录/移动/重命名/历史；发现与匹配逻辑在 [`linked_subtitle_audio.py`](../../plugins.v2/p115strmhelper/helper/transfer/linked_subtitle_audio.py) |
| **false** | 与当前 MoviePilot 队列语义一致：字幕、音轨各自作为独立 `TransferTask` 进入批量队列；`process_batch` 内通过 `_sort_tasks_for_batch` 排序为「字幕 → 音频 → 其它 → 主视频」，以便 `is_finished` 时主视频最后完成，从而正确发出 `MetadataScrape`；`TransferTask.related_files` 不使用 |

**补丁层**（`transfer_chain.py`）：仅在关联模式且文件为字幕/音轨时短路，避免与主视频任务重复入队。

**批量层**（`handler.py`）：关联模式下不调用 `_sort_tasks_for_batch`，先 `discover_related_files` 再执行带 `related_files` 的目录/移动/重命名/历史；历史与事件语义与旧版一致（主任务 `TransferComplete`，关联文件单独历史及 `SubtitleTransferComplete` / `AudioTransferComplete`）。

---

## 处理流程

### 完整流程

```
1. MoviePilot 调用 TransferChain.__handle_transfer(task)
   │
   ├─ [被拦截] TransferChainPatcher._patched_handle_transfer()
   │   ├─ 执行 MoviePilot 的识别/目录逻辑（复用）
   │   ├─ 判断：115 → 115？
   │   └─ 是 → 创建 PluginTransferTask
   │       └─ TransferTaskManager.add_task(plugin_task)
   │
   └─ [未拦截] 继续 MoviePilot 原逻辑

2. TransferTaskManager 队列管理
   ├─ add_task() → 加入队列
   ├─ 延迟 10 秒或达到上限 → _trigger_batch_process()
   └─ 调用 TransferHandler.process_batch(tasks)

3. TransferHandler 批量处理
   ├─ 关闭 `pan_transfer_linked_subtitle_audio`：批次内排序（字幕 → 音频 → 其它 → 主视频；主视频最后，便于 is_finished 时发出 MetadataScrape）
   ├─ 开启关联整理（**默认**）：`discover_related_files` → `TransferHandlerLinkedBatch` 各步（不排序）
   │
   ├─ _batch_create_directories()     # 批量创建目录
   │   └─ 失败 → 受影响任务标记失败，停止
   │
   ├─ _batch_move_or_copy()          # 批量移动/复制
   │   ├─ 按目标目录分组
   │   ├─ 批量检查文件存在性
   │   ├─ 处理覆盖模式（always/size/latest/never）
   │   ├─ 批量删除已存在文件（如需要）
   │   ├─ 批量删除版本文件（latest 模式，目标文件不存在时，循环外批量处理）
   │   ├─ 批量移动/复制
   │   └─ 失败 → 受影响任务标记失败，继续
   │
   ├─ _batch_rename_files()          # 批量重命名
   │   └─ 失败 → 受影响任务标记失败，继续
   │
   ├─ _record_history()              # 记录历史
   │   ├─ 成功任务：add_success()
   │   │   ├─ finish_task()
   │   │   ├─ 按主文件类型发送 TransferComplete / SubtitleTransferComplete / AudioTransferComplete
   │   │   ├─ 登记到 _success_target_files
   │   │   └─ is_finished() → 通知；MetadataScrape 仅主视频且 need_scrape（对齐 MP __default_callback）
   │   │
   │   └─ 失败路径（_record_fail）：add_fail()、按类型发送 TransferFailed / SubtitleTransferFailed / AudioTransferFailed、通知
   │
   ├─ _batch_delete_empty_dirs()     # 删除空目录（仅 move 模式）
   │   ├─ 检查 is_success()
   │   ├─ 收集空目录（递归检查）
   │   └─ 批量删除
   │
   └─ _remove_completed_jobs()        # 移除已完成任务组
       ├─ 成功任务：is_finished() → remove_job()
       └─ 失败任务：is_done() → remove_job()

4. 批量处理完成后
   └─ TransferTaskManager 检查队列
       └─ 仍有待处理任务 → 立即触发下一批
```

### 错误处理流程

```
任何步骤失败：
├─ 记录失败原因
├─ 标记任务失败（fail_task）
├─ 记录失败历史（add_fail）
├─ 发送失败通知
└─ 阻止后续步骤（remaining_tasks 清空）

批量操作失败：
├─ 不再回退到逐个处理（避免 API 风控）
└─ 批量失败的任务统一标记为失败
```

---

## 关键实现细节

### 1. 任务状态同步

**问题**：确保 MoviePilot 的 `jobview` 状态与插件处理结果一致

**实现**：
- 拦截时：`chain.jobview.running_task(task)` - 标记为运行中
- 成功时：`chain.jobview.finish_task(mp_task)` - 标记为完成
- 失败时：`chain.jobview.fail_task(mp_task)` - 标记为失败
- 移除时：按媒体组检查 `is_finished()` / `is_done()`，然后 `remove_job()`

**关键点**：
- 使用 `MPTransferTask`（MoviePilot 的 TransferTask）与 JobManager 交互
- 按媒体组统一移除，避免重复调用

### 2. 批量操作优化

**目录创建**：
- 收集各任务 `target_path` 的父目录
- 识别叶子目录（非其他目录的父目录）
- 批量创建（115 API 自动递归）

**文件移动/复制**：
- 按目标目录分组
- 批量检查文件存在性（每个目录只列出一次）
- 批量删除已存在文件（如需要）
- 批量删除版本文件（latest 模式，循环外批量处理，按目录分组）
- 批量移动/复制
- 失败时不回退到逐个处理（避免 API 风控）

**文件重命名**：
- 仅 `need_rename=True` 的任务参与；与 MP 一致，`need_rename=False` 时目标文件名为源文件名，不产生重命名 API 调用
- 批量重命名（使用 `p115client.tool.edit.update_name`）

### 3. 覆盖模式处理

**支持的模式**：
- `always`: 总是覆盖
- `size`: 大覆盖小
- `latest`: 仅保留最新版本（删除其他版本）
- `never`: 不覆盖（跳过）

**实现**：
- 批量检查目标文件是否存在
- 根据 `overwrite_mode` 决定是否覆盖
- 附加文件（字幕/音轨）强制覆盖
- `latest` 模式：
  - 目标文件已存在：收集到批量删除列表，循环外统一删除
  - 目标文件不存在：收集到 `version_delete_tasks`，循环外调用 `_batch_delete_version_files()` 批量处理
  - 按目录分组，每个目录只执行一次 `list_files`，收集所有目标文件的季集信息后批量删除

### 4. 字幕与音轨（独立任务，对齐 MP）

- MoviePilot `do_transfer` 为每个字幕/音频创建独立 `TransferTask`；插件**同样**为每条任务入队并批量处理，**不再**使用 `related_files` 或目录内「发现关联」
- 目标路径：补丁层 `_compute_target_path` 与 `TransHandler.transfer_media` 一致（`need_rename`、字幕 `__rename_subtitles`）
- 覆盖：扩展名为 `RMT_SUBEXT` / `RMT_AUDIOEXT` 的源文件在批量移动中按「附加文件」**强制覆盖**
- 历史与事件：每个文件一条 `add_success` / `add_fail`；成功/失败事件按类型为 `Subtitle*` / `Audio*` / 主视频 `Transfer*`
- 聚合通知与刮削：`need_notify` / `need_scrape` 来自目录配置（及 `task.scrape`）；`MetadataScrape` **仅**在主视频任务且 `is_finished` 时发送（与 `__default_callback` 一致）

### 5. 空目录删除

**触发条件**：
- `transfer_type == "move"`
- `is_success() == True`（媒体组所有任务都成功）

**删除逻辑**：
- 递归检查父目录
- 检查目录是否为空（无文件）
- 检查目录是否包含媒体文件
- 不删除资源目录/媒体库目录结构内的目录
- 批量删除（按深度排序，深度大的先删除）

**注意**：
- 115→115 场景下，**不删除种子**（无下载器种子）

### 6. 任务移除逻辑

**成功任务**：
- 使用 `is_finished()` 检查（需要至少一个成功）
- 按媒体组统一移除

**失败任务**：
- 使用 `is_done()` 检查（不管成功还是失败）
- 按媒体组统一移除

**关键点**：
- 确保所有任务都调用 `finish_task()` / `fail_task()`
- 使用 `_remove_completed_jobs()` 统一处理

---

## 数据流

### 任务流转

```
MoviePilot TransferTask
    │
    ├─ [识别/目录计算] (MoviePilot 原逻辑)
    │
    └─ [拦截] TransferChainPatcher
        │
        └─ Plugin TransferTask
            │
            └─ TransferTaskManager._pending_tasks
                │
                └─ [批量触发] TransferHandler.process_batch()
                    │
                    ├─ 成功 → finish_task() → add_success()
                    └─ 失败 → fail_task() → add_fail()
```

### 状态同步

```
插件处理状态          MoviePilot JobManager
─────────────────────────────────────────────
拦截任务        →     running_task()
处理成功        →     finish_task()
处理失败        →     fail_task()
媒体组完成      →     is_finished() / is_done()
                    → remove_job()
```

---

## 与 MoviePilot 的差异

### 设计原则：保持代码简洁

**核心原则**：115→115 网盘整理场景下，某些 MoviePilot 功能**不需要**，因此**故意不实现**，以保持代码简洁。

### 已实现的差异

| 功能点 | MoviePilot | 插件实现 | 说明 |
|--------|-----------|---------|------|
| **文件操作** | 逐个处理 | 批量处理 | 性能优化 |
| **字幕/音轨任务** | 每文件独立任务与历史 | ✅ 独立任务批量处理，无 related_files | 已对齐 |
| **事件触发** | 仅主媒体文件 | 仅主媒体文件 | 已对齐 |
| **空目录删除** | 支持 | ✅ 支持 | 已实现 |
| **Preview 模式** | `task.preview=True` 只计算路径不执行 | ✅ `_handle_preview` 构造预览结果并回调 | 2026-05 适配 |
| **TransferOverwriteCheck** | `ChainEventType` 允许插件介入覆盖判断 | ✅ 在 `_batch_move_or_copy` 前触发事件 | 2026-05 适配 |
| **TransferRenameBuild** | `ChainEventType` 允许插件注入命名字段 | ✅ 在 `_compute_target_path` 模板渲染前触发 | 2026-05 适配 |
| **AI Agent 重试** | `FailedRetryScheduler.schedule_retry` | ✅ `_record_fail` 中失败后触发重试 | 2026-05 适配 |
| **目录路径尾部 `/`** | `type="dir"` 时路径以 `/` 结尾 | ✅ 所有 `FileItem(type="dir")` 构造均遵循 | 已遵循，无需修改 |

### 故意不实现的功能（115→115 场景不需要）

#### 1. 种子删除功能 ❌

**MoviePilot 实现**：
- 在 `is_success()` 时检查并删除下载器种子
- 使用 `_can_delete_torrent()` 判断是否可删除
- 调用 `remove_torrents()` 删除种子

**插件未实现原因**：
- **115→115 整理场景**：文件在 115 网盘内移动，**不涉及下载器**
- **无种子文件**：115 网盘不是下载器，不存在做种文件
- **代码已移除**：已删除所有种子删除相关代码（`_can_delete_torrent`, `remove_torrents`, `transfer_exclude_words`）

**影响**：无影响，115→115 场景下确实不需要

---

#### 2. transfer_completed 调用 ❌

**MoviePilot 实现**：
```python
if self.jobview.is_done(task):
    tasks = self.jobview.all_tasks()
    for t in tasks:
        if t.download_hash:
            self.transfer_completed(hashs=t.download_hash, downloader=t.downloader)
```

**插件未实现原因**：
- **115→115 整理场景**：文件在 115 网盘内移动，**不涉及下载器**
- **transfer_completed 作用**：标记下载器中的任务为"已整理"状态
- **115 网盘无此概念**：115 网盘不是下载器，不存在"已整理"状态标记

**影响**：无影响，115→115 场景下确实不需要

---

#### 3. StorageOperSelection 事件 ❌

**MoviePilot 实现**：
- 广播 `ChainEventType.StorageOperSelection` 事件
- 获取额外的源/目标存储操作对象（`source_oper`, `target_oper`）
- 支持存储插件扩展

**插件未实现原因**：
- **115→115 整理场景**：源和目标都是 115 网盘，**使用固定的 115 API**
- **不需要扩展**：直接使用 `P115Client` 进行文件操作，不需要存储插件扩展
- **代码更简洁**：避免事件广播和额外的抽象层

**影响**：无影响，115→115 场景下直接使用 115 API 更高效

---

#### 4. sync_extra_files 同步关联文件 ❌

**MoviePilot 实现**：
- `do_transfer(sync_extra_files=True)` 时，自动扫描同目录下与主视频媒体身份匹配的字幕/音轨文件
- 将这些文件一并加入整理队列

**插件未实现原因**：
- **批量整理层内自动忽略**：当 `sync_extra_files=True` 时，MP 会为附加文件创建独立的 `TransferTask`
- **插件的批量队列会自然收到这些任务**：由于插件拦截了 `__handle_transfer`，所有 MP 生成的 `TransferTask`（包括附加文件）都会经过插件的拦截判断
- **关联整理模式 (`pan_transfer_linked_subtitle_audio=True`) 已处理**：此模式下，插件的 `discover_related_files` 已在源目录发现同目录字幕/音轨，MP 的 `sync_extra_files` 产生的额外任务被短路（`finish_task` + `remove_job`），不会重复处理
- **非关联整理模式下**：附加文件作为独立任务进入批量队列，按字幕/音轨类型排序后批量处理，行为与 MP 原生一致

**影响**：无影响，批量整理层内自动忽略，不重复处理

### 已对齐的功能

#### 1. 事件触发条件 ✅

**MoviePilot 实现**：
- `TransferComplete` 事件：仅主媒体文件触发
- `MetadataScrape` 事件：仅主媒体文件触发
- `TransferFailed` 事件：仅主媒体文件触发

**插件实现**：
- 主视频：发送 `TransferComplete` / `TransferFailed`
- 字幕主任务：`SubtitleTransferComplete` / `SubtitleTransferFailed`
- 音频主任务：`AudioTransferComplete` / `AudioTransferFailed`
- `TransferInfo.need_notify` / `need_scrape` 与 `filemanager.transfer()` 推导一致；`MetadataScrape` 仅在 `is_finished` 且当前任务文件为主视频且 `need_scrape` 时发送（批次排序保证含字幕/音轨时主视频在 `_record_history` 中最后 `finish_task`，避免最后一项是音轨导致门控永远不通过）

**状态**：已对齐 MoviePilot `__default_callback` 按文件类型分支的行为

---

#### 2. 字幕/音轨历史记录 ✅

**MoviePilot**：每文件独立任务，各写一条历史

**插件**：每条插件 `TransferTask` 对应一条 `add_success` / `add_fail`，无 `related_files` 二次写入

**状态**：已对齐

---

#### 3. 任务状态管理 ✅

**MoviePilot 实现**：
- `running_task()`: 标记运行中
- `finish_task()`: 标记完成
- `fail_task()`: 标记失败
- `is_finished()`: 检查是否完成且有成功
- `is_done()`: 检查是否完成（不管成功失败）
- `remove_job()`: 移除任务组

**插件实现**：
- 完全对齐 MoviePilot 的状态管理逻辑
- 使用 `_remove_completed_jobs()` 统一处理移除

**状态**：已对齐

---

#### 4. add_success / add_fail 返回值 ✅

**MoviePilot 实现**：
- `TransferHistoryOper.add_success()` / `add_fail()` 返回 `TransferHistory` 对象（`history.id` 用于 `transfer_history_id`）

**插件实现**：
- `handler.py`、`handler_linked_batch.py`、`linked_subtitle_audio.py` 中均已捕获返回值
- 事件数据中的 `transfer_history_id` 使用 `history.id if history else None`

**状态**：已对齐

---

#### 5. 目录路径尾部 `/` 规范 ✅

**MoviePilot 实现**：
- `type="dir"` 的 `FileItem` 路径以 `/` 结尾
- `EventManager.__normalize_transfer_event_data()` 中构造合成 `FileItem` 时遵循此约定

**插件实现**：
- `_build_plugin_target_fileitems`: `path=str(task.target_dir) + "/"`
- `_get_folder`: `path=path.as_posix() + "/"`
- `record_history` / `record_related_files`: `path=str(target_path.parent) + "/"`
- `_handle_preview`: `path=str(target_path.parent) + "/"`

**状态**：已遵循，无需修改

---

### 代码简洁性考虑

**设计原则**：
1. **只实现需要的功能**：115→115 场景不需要的功能不实现
2. **避免过度抽象**：直接使用 115 API，不需要存储操作抽象层
3. **减少依赖**：移除不必要的导入（如 `SystemConfigOper`, `SystemConfigKey`）

**已移除的代码**：
- ❌ 种子删除相关（`_can_delete_torrent`, `remove_torrents`, `transfer_exclude_words`）
- ❌ `SystemConfigOper` 和 `SystemConfigKey` 导入（仅用于种子删除判断）
- ❌ `transfer_completed()` 调用（115→115 无下载器）

**保留的代码**：
- ✅ `downloader` 和 `download_hash` 字段（历史记录需要，用于关联下载记录）
- ✅ 空目录删除（move 模式需要）

---

## 注意事项

### 1. 任务移除时机

**关键点**：
- 必须在所有任务都标记为 `completed` / `failed` 后才能移除
- 使用 `is_finished()`（成功）或 `is_done()`（完成）检查
- 按媒体组统一移除，避免重复调用

### 2. 批量处理中的新任务

**场景**：批量处理进行中，新任务不断加入队列

**处理**：
- 新任务加入时重置定时器
- 定时器触发时，如果正在处理则跳过
- **批量处理完成后，自动检查队列并触发下一批**

### 3. 失败任务处理

**原则**：
- 任何步骤失败，立即标记任务失败
- 阻止后续步骤（`remaining_tasks` 清空）
- 批量记录失败历史
- 按媒体组统一移除失败任务组

### 4. 字幕/音频历史

**实现**：与 MP 一致，每条整理任务一条历史；通知/刮削由 `need_notify` / `need_scrape` 与作业聚合（`is_finished`）决定

### 5. 115→115 特殊处理

#### 不涉及的功能（故意不实现，保持代码简洁）

**种子删除** ❌：
- **原因**：115→115 整理场景下，文件在 115 网盘内移动，不涉及下载器，无种子文件
- **代码状态**：已完全移除相关代码（`_can_delete_torrent`, `remove_torrents`, `transfer_exclude_words`）

**transfer_completed 调用** ❌：
- **原因**：115→115 整理场景下，无下载器，不需要标记下载器任务为"已整理"
- **代码状态**：未实现，保持代码简洁

**StorageOperSelection 事件** ❌：
- **原因**：115→115 整理场景下，直接使用 115 API，不需要存储插件扩展机制
- **代码状态**：未实现，避免不必要的抽象层

#### 保留的功能

**空目录删除** ✅：
- **原因**：move 模式下需要清理源目录
- **实现**：`_batch_delete_empty_dirs()` 方法

**历史记录字段** ✅：
- **原因**：`downloader` 和 `download_hash` 用于关联下载记录，即使 115→115 场景下也可能有下载历史
- **实现**：保留在 `TransferTask` 和 `add_success/add_fail` 调用中

---

## 文件结构

```
plugins.v2/p115strmhelper/
├── patch/
│   └── transfer_chain.py          # 补丁层：拦截 MoviePilot
├── helper/transfer/
│   ├── __init__.py
│   ├── task.py                    # 任务队列管理
│   ├── handler.py                 # 批量处理执行器
│   ├── handler_linked_batch.py    # 关联整理批量处理
│   ├── linked_subtitle_audio.py   # 字幕/音轨发现与历史
│   └── cache_updater.py           # 缓存管理
└── schemas/
    └── transfer.py                # 数据结构定义
```

---

## 关键配置

### TransferTaskManager 参数

- `batch_delay`: 批量等待时间（默认 10.0 秒）
- `batch_max_size`: 单批次最大任务数（默认 100）

### 触发条件

1. **延迟触发**：新任务到达后 10 秒触发
2. **立即触发**：队列达到 `batch_max_size` 立即触发
3. **连续触发**：批量处理完成后，队列仍有任务则立即触发下一批

---

## 调试建议

### 关键日志

- `【整理接管】检测到 115 → 115 整理任务`: 拦截成功
- `【整理接管】开始批量处理 N 个任务`: 批量处理开始
- `【整理接管】批量处理完成，成功: X 个，失败: Y 个`: 批量处理完成
- `【整理接管】已移除 N 个已完成的任务组`: 任务组移除成功

### 常见问题

1. **任务未移除**：
   - 检查是否所有任务都调用了 `finish_task()` / `fail_task()`
   - 检查 `is_finished()` / `is_done()` 的返回值
   - 检查是否按媒体组统一移除

2. **批量处理不触发**：
   - 检查 `TransferTaskManager._processing` 状态
   - 检查队列中是否有待处理任务
   - 检查定时器是否正常触发

3. **字幕未随主视频移动**：
   - 与 MP 一致：需由 `do_transfer` 等为字幕单独排队；插件不再从目录「发现」关联文件

4. **Preview 模式不生效**：
   - 检查 `task.preview` 是否传递到 `_patched_handle_transfer`
   - `_handle_preview` 是否正确构造 `TransferInfo` 并调用 callback

5. **sync_extra_files 产生的附加文件重复处理**：
   - 正常情况下不会重复：关联整理模式下附加文件任务被短路；非关联模式下作为独立任务进入批量队列
   - 检查 `pan_transfer_linked_subtitle_audio` 配置是否正确

---

## 版本兼容性

### MoviePilot 版本要求

- 支持 v2.10.0+ 的整理逻辑
- 关键依赖：
  - `TransferChain.__handle_transfer`
  - `JobManager` (finish_task, fail_task, is_finished, is_done, remove_job)
  - `TransferHistoryOper` (add_success, add_fail)
  - `TransHandler` (用于计算目标路径)
  - `FailedRetryScheduler` (AI Agent 自动重试)
  - `ChainEventType.TransferOverwriteCheck` (覆盖判断事件)
  - `ChainEventType.TransferRenameBuild` (重命名字段注入事件)

### 已知差异

- v2.9.5+ 引入了多线程整理，但插件通过批量处理已实现类似效果
- v2.9.5+ 的 `transfer_completed()` 调用在 115→115 场景下不需要
- v2.10.0+ 新增 Preview 模式、`TransferOverwriteCheck`、`TransferRenameBuild` 事件、`FailedRetryScheduler` AI 重试 — 均已适配

---

## 未来改进方向

### 性能优化

1. **文件存在性检查优化**：
   - 当前：每个目标目录批量列出文件
   - 优化：可以缓存结果，减少重复 API 调用

2. **批量操作失败处理**：
   - 当前：批量失败时不再回退到逐个处理（避免 API 风控）
   - 已优化：所有批量操作失败时统一标记为失败，不进行逐个重试

### 功能完善

1. **错误处理细化**：
   - 部分失败场景的处理可以更细化
   - 批量操作的原子性可以进一步优化

### 代码维护

1. **保持简洁**：
   - **不实现 115→115 场景不需要的功能**（种子删除、transfer_completed、sync_extra_files 等）
   - **避免过度抽象**（直接使用 115 API，不需要存储操作抽象层）
   - **减少不必要的依赖**（已移除 SystemConfigOper 等）

2. **与 MoviePilot 对齐**：
   - ✅ v2.10.0+ Preview 模式已适配
   - ✅ v2.10.0+ `TransferOverwriteCheck` 已适配
   - ✅ v2.10.0+ `TransferRenameBuild` 已适配
   - ✅ v2.10.0+ `FailedRetryScheduler` AI 重试已适配
   - 关注 MoviePilot 新版本的功能变更
   - 只对齐 115→115 场景需要的功能
   - 不需要的功能保持不实现，保持代码简洁

---

## 相关文件

- **补丁层**：`plugins.v2/p115strmhelper/patch/transfer_chain.py`
- **任务管理**：`plugins.v2/p115strmhelper/helper/transfer/task.py`
- **处理执行**：`plugins.v2/p115strmhelper/helper/transfer/handler.py`
- **数据结构**：`plugins.v2/p115strmhelper/schemas/transfer.py`
- **MoviePilot 源码**：`/Users/rem/Documents/Git/MoviePilot/app/chain/transfer.py`

---

*最后更新：2026-05-22*
