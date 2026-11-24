# p115client 0.0.9.7.2 → 0.0.9.7.8.3 兼容性审计

本报告对 PyPI 的两个源码包逐文件比较，并对公开导出、类方法签名和实现体做 AST 级核对。旧版本是仓库当前锁定和内置的 0.0.9.7.2，新版本是 0.0.9.7.8.3。

## 版本基线

- 升级前锁定位置：plugins.v2/p115disk/requirements.txt、plugins.v2/p115strmhelper/requirements.txt、plugins.v3/p115disk/pyproject.toml、plugins.v3/p115strmhelper/pyproject.toml，均为 p115client==0.0.9.7.2
- 升级前 V2/V3 p115strmhelper 均内置 wheels/p115client-0.0.9.7.2-py3-none-any.whl
- 新包新增 _init_magics.py、_init_xonsh.py，并把 IPython 魔法从 _init_ipython.py 拆出
- 共 20 个包内文件发生变化，其中 18 个 Python 源码模块发生差异，约新增 2663 行、删除 614 行
- `pyproject.toml` 的发行版本从 `0.0.9.7.2` 改为 `0.0.9.7.8.3`；源码 `p115client.__version__` 仍为 `(0, 0, 9)`，没有同步携带完整发行版本号

## 本次升级实施状态

- 四个依赖清单已改为 `p115client==0.0.9.7.8.3`
- V2/V3 `p115strmhelper/wheels` 已替换为 `p115client-0.0.9.7.8.3` 和 `python_httpfile-0.0.6.3`
- 插件自身版本号、`package.v2.json`、`package.v3.json` 和历史版本号均未修改

## 依赖链变化

- 新版 `p115client` 的 `pyproject.toml` 和 `PKG-INFO` 将 `python-httpfile` 最低版本从 `>=0.0.6.1` 提高到 `>=0.0.6.3`
- 升级前两套 `p115strmhelper/wheels` 内置 `python_httpfile-0.0.6.1-py3-none-any.whl`，与新版依赖声明不一致；本次已替换为 0.0.6.3
- `python-httpfile 0.0.6.3` 新增 `HTTPFileReader.new` / `AsyncHTTPFileReader.new`，并修正 Range 可寻址判断、越界 seek 和异步 Future 处理；新版 `P115PathBase.open` 默认异步读取器直接使用 `AsyncHTTPFileReader.new`，继续使用 0.0.6.1 可能在异步读取或 FUSE 扩展场景中失败

## 源码完全相同的模块

exception.py、type.py、util.py、tool/auth.py、tool/clouddownload.py、tool/export_dir.py、tool/extract.py、tool/history.py、tool/life.py、tool/media.py、tool/querydb.py、tool/tinydb.py、tool/updatedb.py、tool/upload.py、tool/xys.py 在两个版本间源码相同

## 导出集合和新增公开接口

- tool/edit.__all__ 新增 batch_desc、iter_batch_desc、update_star_fast
- tool/iter_nodes.__all__ 新增 iter_nodes_by_browse_event、iter_nodes_and_ancestors_by_label、iter_nodes_by_label_with_path
- client.P115Client 新增 fs_category_shortcut_app、fs_category_shortcut_set_app、fs_files_app3、fs_label_list2、fs_label_list_app2、life_behavior_doc_post、upload_quota、user_space_detail
- client.P115OpenClient 新增 access_token 缓存属性
- P115FileSystem/P115Path 新增 search；P115ShareFileSystem/P115SharePath 新增 search
- P115PathBase 新增 dictdir、dictdir_path、listdir、listdir_path

新增客户端接口对应端点：`fs_category_shortcut_app` / `fs_category_shortcut_set_app` → `/{app}/2.0/category/shortcut`；`fs_files_app3` → `/{app}/files/update`；`fs_label_list2` → `/label/search`；`fs_label_list_app2` → `/{app}/label/search`；`life_behavior_doc_post` → `/files/doc_behavior`；`upload_quota` → `/3.0/getuploadquota.php`；`user_space_detail` → `/user/space_detail`

## 公开签名变化

### client.py

以下 P115Client 方法的 payload 从 str/dict 扩展为 int/str/dict，传入 int 时自动转换为 pickcode：download_url_info、fs_video、fs_video_history、fs_video_history_set、fs_video_push、fs_video_subtitle、upload_gettoken_open、download_files、download_files_app、download_folders、download_folders_app、download_downfolder_app、download_url_app、extract_info、extract_info_app、extract_push、extract_push_app、extract_push_progress、extract_push_progress_app、fs_document、fs_document_app、fs_edit、fs_files、fs_files_app2、fs_files_aps、fs_files_update_app、fs_folder_file、fs_history、fs_history_app、fs_history_set、fs_history_set_app、fs_image、fs_label_batch、fs_label_batch_app、fs_label_list_app、fs_music、fs_music_app、fs_music_file_exist、fs_music_info、fs_music_info_app、fs_music_status、fs_office_init、fs_preview、fs_search_app、fs_search_app2、fs_star_set、fs_star_set_app、fs_supervision、fs_supervision_app、fs_video_app、fs_video_is_transcode、fs_video_subtitle_app、multimedia_relate_file、usershare_file_list、usershare_file_list_app，以及 P115OpenClient.download_url_info、fs_star_set、fs_video、fs_video_history、fs_video_history_set、fs_video_push、fs_video_subtitle

其他签名变化：

- P115Client.fs_label_set 和 fs_label_set_app：label 改名为 label_id，默认值从空字符串改为 0
- P115Client.fs_video_transcode：新增 method，默认 GET，并传给 request
- P115Client.life_recent_operation_items：默认 payload 从 browse_document 改为 browse_image
- P115OpenClient.upload_gettoken_open：新增 payload: int | dict = {}
- P115OpenClient.upload_resume：类型顺序改为 str | dict
- P115Client.upload_resume：类型顺序改为 str | dict
- tool/fs_files.py 的 fs_files、fs_files_iter：新增 app_api_suffix: Literal[1,2,3] = 1
- tool/iterdir.py 的 ensure_path：旧参数顺序 (client, cid, attrs, ...) 改为 (client, attrs, cid=None, ...)
- tool/iterdir.py 的 search_iter：search_value 从 str 扩展为 int | str，int 表示标签 ID
- tool/edit.py 的批量编辑函数普遍接受单个 int/str/Mapping，并支持 Mapping 形式的 ID；`update_label` 参数名从 `label` 改为 `label_id`；`update_name` 额外接受单个 tuple 和异步 iterable；`update_category_shortcut` 新增 app 参数
- tool/attr.py 的内部 ID 解析兼容 file_id、pick_code

## 实现体变化

### client.py

- check_response 新增 40140137（refresh_token 终态失效）终止错误
- ClientRequestMixin.request 对 Open API 的自动刷新重试从只处理 40140125 扩展为 40140120、40140125、40140126
- P115OpenClient 新增 access_token 缓存属性，缺失时自动 refresh 或调用 login_another_open
- P115OpenClient.upload_file 改用 Bearer + self.access_token
- upload_gettoken_open 支持 upload_v2 参数；upload_init/upload_resume 文档和字段支持 preid、path、pick_code、upload_v2
- 新增 life_behavior_doc_post、upload_quota、user_space_detail
- life_recent_operation_items 强制补默认 behavior_type=browse_image
- multimedia_collection_listen/watch 不再自动注入 channel_id；multimedia_relate_file 接受 int/str 作为 multimedia_id
- fs_files_app2 增加 payload 默认值、规范化和排序默认值；新增 fs_files_app3 对应 /files/update 端点
- _fs_edit_set/_fs_edit_set_app 对 tuple-list payload 更严格，避免非 tuple 列表误索引

### fs/

- P115PathBase.glob、iter、iterdir、rglob、walk 先判定目标是否目录；文件目标改用其 parent_id，目录目标使用自身 id
- P115PathBase.get_ancestors 改用 wrap_path_iter，返回路径对象保持一致
- P115PathBase 新增 dictdir、dictdir_path、listdir、listdir_path
- P115PathBase.open 和 P115FileSystemBase.open 的 reader 参数从 type 改为任意 callable；实现改为直接构造 reader，异步默认使用 AsyncHTTPFileReader.new
- P115FileSystem/P115ShareFileSystem 新增 search；P115Path/P115SharePath 新增 search
- 文件系统属性统一使用 AttrDict；`P115Path.remove` 和 `P115FileSystem.remove` 增加 `delete` 别名
- get_parents 对空/无效属性 ID 返回根目录

### tool/

- attr：新增分卷压缩扩展名识别为 type=5；normalize_attr 新增 is_q、is_family_share，并对目录强制 type=0
- download：`formalize_sha1` 现在只把 32 位、字符集为 `A-Z2-7` 的 Base32 SHA1 转成 40 位十六进制，或把 40 位十六进制 SHA1 转大写；其它长度/字符不再按旧逻辑接受。`get_url` 删除了一个冗余自导入
- fs_files：新增 app_api_suffix，非 web 且非 media 时按 suffix 选择 fs_files_app1/2/3
- iterdir：ensure_path 支持 cid=None/负数并通过 iter_nodes_and_ancestors_by_label 补祖先；with_path/with_ancestors 都为 false 时直接返回原 attrs；search_iter 支持标签 ID，非正 page_size 归一化为 10000；分享搜索非正 page_size 归一化为 1000
- iter_nodes：新增 browse event、label+path、label+ancestors 三套批量接口；iter_nodes_by_label 的标签创建/查询和响应处理改变
- edit：新增备注批量接口和 update_star_fast；批量编辑接受标量/Mapping；batch_unstar 改为快速批量路径；update_name 改为惰性 chunk 处理
- tool/__init__.py、fs/__init__.py、p115client/__init__.py 改成按模块 __all__ 动态聚合；fs.__getattr__ 删除
- 顶层 `p115client` 的动态导出只扫描包根目录 `.py`：旧版通过显式 `from .fs import *` 导出约 79 个名称，新版不再把 `fs` 子包导入根命名空间，约剩 70 个名称；`from p115client import P115Path` 等旧用法会受到影响，应改从 `p115client.fs` 导入
- `p115client.tool` 和 `p115client.fs` 的导出改为动态 `__all__` 聚合；`tool` 的显式导出集合由约 138 个模块符号变为约 144 个，旧版通过无 `__all__` 的 `tool/__init__.py` 间接暴露的 util 名称不应再假设可用
- `_init_ipython.py` 拆出 `_init_magics.py`、`_init_xonsh.py`；新增 magics/xonsh 初始化模块，属于导入副作用和交互工具层变化，不是插件业务接口
- `const.py` 新增 `.pdg`、`.sami`、`.smi`、`.xhtml`、`.xml`、`.zst`、`.appimage` 等后缀分类和一个应用 ID；视频类型中的 `.m3u8` 仍为注释项
- `fs/fs_zip.py` 生成的目录和文件属性从普通 `dict` 改为 `AttrDict`

## 函数级差异完整索引

下面列出 AST 对所有 Python 定义的结果；`SIG` 表示参数/返回注解变化，`BODY` 表示函数体或行为变化，`ADD` / `DEL` 表示定义新增或删除。机器生成的完整签名对照在本报告末尾，未列出的定义签名和函数体均未变化。

### `client.py`

- `BODY`：`ClientRequestMixin.request`、`check`、`check_response`、`P115Client._fs_edit_set`、`_fs_edit_set_app`、`fs_edit`、`fs_files`、`fs_files_app2`、`fs_files_aps`、`fs_files_update_app`、`fs_folder_file`、`fs_label_batch`、`fs_label_batch_app`、`fs_label_list_app`、`fs_search_app`、`fs_search_app2`、`fs_star_set`、`fs_star_set_app`、`multimedia_collection_listen`、`multimedia_collection_listen_set`、`multimedia_collection_watch`、`multimedia_collection_watch_set`、`multimedia_listen_update`、`multimedia_watch_update`、`recyclebin_list`、`user_space_info`、`usershare_file_list`、`usershare_file_list_app`、`P115OpenClient.fs_star_set`、`upload_file`、`upload_init`、`vip_qr_url`
- `ADD`：`P115Client.fs_category_shortcut_app`、`fs_category_shortcut_set_app`、`fs_files_app3`、`fs_label_list2`、`fs_label_list_app2`、`life_behavior_doc_post`、`upload_quota`、`user_space_detail`、`P115OpenClient.access_token`
- `SIG`：机器清单中的全部 `download_*`、`extract_*`、`fs_*`、`multimedia_relate_file`、`upload_*`、`life_recent_operation_items`、`P115OpenClient` 对应方法，以及 `fs_label_set` / `fs_label_set_app`、`fs_video_transcode`

### `fs/`

- `fs/fs.py`：`P115FileSystem._get_attr_by_id`、`mkdir`、`P115Path.gen_step` 为 `AttrDict`/路径属性适配；新增 `P115Path.search`、`P115FileSystem.search`；`P115Path` 和 `P115FileSystem` 新增 `delete` 别名
- `fs/fs_base.py`：`P115FileSystemBase.get_ancestors`、`P115PathBase.gen_step`、`get_parents`、`glob`、`iter`、`iterdir`、`rglob`、`walk` 改变目录/文件目标解析及路径包装；`open` 两个公开实现改为可调用 reader，并让异步默认使用 `AsyncHTTPFileReader.new`；新增 `dictdir`、`dictdir_path`、`listdir`、`listdir_path`
- `fs/fs_share.py`：新增 `P115SharePath.gen_step`、`P115SharePath.search`、`P115ShareFileSystem.search`
- `fs/fs_zip.py`：`P115ZipFileSystem.gen_step`、`get_parent_id`、`load` 的属性对象改为 `AttrDict` 并调整加载流程

### `tool/`

- `tool/attr.py`：`_get_id`、`_get_pickcode` 接受 `file_id` / `pick_code` 键；`normalize_attr_app2`、`normalize_attr_web`、`type_of_attr` 增加 `is_q`、`is_family_share`、分卷压缩和目录类型规则
- `tool/download.py`：`formalize_sha1` 签名和 Base32/十六进制判定改变；`get_url` 删除冗余自导入
- `tool/edit.py`：`update_abstract`、`update_cover`、`update_desc`、`update_label`、`update_show_play_long`、`update_star`、`update_score`、`update_top`、`update_category_shortcut`、`update_name`、`post_event`、`batch_copy`、`batch_delete`、`batch_move`、`batch_recyclebin_clean`、`batch_recyclebin_revert`、`batch_hide` 的输入类型扩展为标量/Mapping/异步迭代器；`update_label` 的关键字改为 `label_id`；`batch_label`、`batch_makedir`、`batch_unstar` 的批处理逻辑改变；新增 `iter_batch_desc`、`batch_desc`、`update_star_fast`
- `tool/fs_files.py`：`fs_files`、`fs_files_iter` 增加 `app_api_suffix`
- `tool/iter_nodes.py`：`get_response`、`iter_nodes_by_event`、`iter_nodes_by_label` 行为改变；新增 `iter_nodes_by_browse_event`、`iter_nodes_and_ancestors_by_label`、`iter_nodes_by_label_with_path`
- `tool/iterdir.py`：`ensure_path` 位置参数破坏性调整；`iter_dirs`、`iter_files`、`iter_files_skim`、`traverse_tree`、`share_iterdir`、`share_search_iter` 行为改变；`search_iter` 接受标签 ID并调整非正分页大小

### 初始化模块

- `_init_ipython.py`：`_load_magics` 实现体改变并移除旧模块内的 `attr`、`dictdir`、`get_pic_url`、`get_url`、`listdir`、`search` 定义
- 新增 `_init_magics.py` 的 `attr`、`ancestors`、`path`、`listdir`、`search`、`dictdir`、`pic_url`、`url`、`m3u8`、`music` 命令，以及 `_cmd`、`get_buddle_id`、`get_default_app`、`open_m3u8`
- 新增 `_init_xonsh.py` 的 `_load_magics`、`alias`

## p115disk 扫描

V2/V3 直接依赖的名称均保留：P115Client、check_response、ID_TO_DIRNODE_CACHE、_CACHE_DIR、P115NotADirectoryError、normalize_attr、get_id_to_path、get_attr、fs_files_iter、iter_files_skim

- iter_files_skim(..., with_path=True) 和 fs_files_iter(...) 的现有调用仍可使用；app_api_suffix 默认 1，所以当前调用无需改参数
- p115_client.py 通过 P115Client.request.__globals__['get_request'] 探测后端并注入 timeout；request 名称和 **request_kwargs 契约未变，但 Open token 重试语义已改变
- get_ios_ua_app(app=False) 仍走 web 端，app=True 仍走 ios 端
- 需要回归 P115Api 的 list、iter_files、detail、download、upload、rename、delete、usage，以及 V3 新增的 get_folder/get_item_strict 路径
- 具体调用点：V2 `p115_api.py:141` 的 `iter_files_skim`、`p115_api.py:208` 的 `fs_files_iter`；V3 对应 `p115_api.py:195`、`p115_api.py:262`。这些调用都没有传 `app_api_suffix`，继续走旧的 `fs_files_app1` 选择逻辑
- `normalize_attr` 的新增 `is_q`、`is_family_share` 及分卷压缩类型会进入 p115disk 的 `FileItem` 映射和缓存，需验证书籍/压缩包/家庭共享文件的类型判断

## p115strmhelper 扫描

V2/V3 直接导入的名称均保留：P115Client、check_response、P115AuthenticationError、P115OSError、P115DataError、throw、DirNode、normalize_attr、get_id、get_path、get_id_to_path、fs_files_iter、iter_files、iter_files_skim、iterdir、iter_nodes、iter_life_behavior_once、life_show、clouddownload_iter、share_iterdir、share_iter_files、share_extract_payload、complete_url、posix_escape_name、update_name

- update_name 现有的 [(id, name), ...] 调用仍兼容
- 分享遍历现有参数仍兼容；非正 page_size 默认归一化为 1000
- 增量 STRM、媒体信息下载、清理、监控等调用 fs_files_iter/iter_files 时未传 app_api_suffix，继续使用 suffix=1
- V2/V3 FUSE 使用 client.get_fs().open/readdir/get_attr，命中新版本文件系统实现，是最高优先级回归面
- 具体调用点：V2 `helper/fuse/__init__.py:197/261/303/351/356`，V3 对应 `helper/fuse/__init__.py:199/263/305/353/358`；其中 `open` 使用同步 reader，`readdir`、`get_attr` 会命中目录/文件目标解析的新逻辑
- 直接命中新版签名的调用包括 V2/V3 `helper/mediainfo_download/__init__.py:161` 的 `download_url_app`、:498/:556 的 `fs_video_subtitle`，以及 V2/V3 `helper/r302/__init__.py` 的 `fs_files`；传入值均为字符串或旧式 payload，当前无需改调用形式，但要回归响应字段
- V2/V3 `core/p115.py`、`core/u115_open.py` 和 `helper/r302` 直接调用 `client.request`，因此会继承新的 Open token 自动刷新和 40140137 终态错误语义
- V2/V3 多处 `normalize_attr` 结果被用于媒体分类、STRM 路径和缓存，需针对新增字段和目录 type=0 规则做回归

## 必须适配和回归

1. 四个依赖清单和两套内置 wheel 必须一起升级到 0.0.9.7.8.3，不能只改一个版本文件（已完成）
2. FUSE 文件读取、目录枚举、glob、walk、文件目标操作要分别跑 V2/V3
3. 所有外部 ensure_path 位置调用必须改为 attrs 第二参数或使用关键字
4. 所有外部 fs_label_set/fs_label_set_app 的 label= 关键字必须改为 label_id=
5. 依赖 life_recent_operation_items 默认值的代码必须显式传入 browse_document
6. 需要覆盖 p115center/open client、WebDAV、开放上传和 refresh_token 失效（40140137）错误提示
7. 如启用 fs_files_app2/app3，必须分别核对响应字段、分页和时间字段；当前插件默认仍为 suffix=1
8. 需要检查 normalize_attr 的 type、is_q、is_family_share 和分卷压缩识别对缓存、媒体类型和刮削的影响

## 公开方法签名机器清单

以下清单由 AST 直接生成，覆盖所有发生新增、删除或参数签名变化的公开类方法；未列出的公开方法签名保持不变。每一行格式为 MODULE / ADD|DEL|SIG / 方法 / 旧签名与新签名。

完整 API 面快照（包含每个模块的 `__all__`、所有函数/异步函数、类及类方法签名）：[0.0.9.7.2 API 快照](p115client-api-surface-0.0.9.7.2.txt)、[0.0.9.7.8.3 API 快照](p115client-api-surface-0.0.9.7.8.3.txt)

### 模块级公开函数的签名变化

- `tool/edit.py`：`update_abstract`、`update_cover`、`update_desc`、`update_show_play_long`、`update_star`、`update_score`、`update_top`、`update_category_shortcut`、`post_event` 的 `ids` 从仅迭代器扩展为标量/Mapping/同步或异步迭代器；`update_label` 同样扩展且参数 `label` 改为 `label_id`；`update_name` 从仅同步 iterable 扩展为单个 `(id, name)` 元组、同步或异步 iterable；`batch_copy`、`batch_delete`、`batch_move`、`batch_recyclebin_clean`、`batch_recyclebin_revert`、`batch_hide` 的 ID 参数扩展为 Mapping；新增 `iter_batch_desc`、`batch_desc`、`update_star_fast`
- `tool/fs_files.py`：`fs_files`、`fs_files_iter` 在 `app` 后新增 `app_api_suffix: Literal[1, 2, 3] = 1`
- `tool/iter_nodes.py`：新增 `iter_nodes_by_browse_event`、`iter_nodes_and_ancestors_by_label`、`iter_nodes_by_label_with_path`
- `tool/iterdir.py`：`ensure_path(client, cid, attrs, ...)` 改为 `ensure_path(client, attrs, cid=None, ...)`；`search_iter.search_value` 从 `str` 扩展为 `int | str`
- `tool/download.py`：内部 `formalize_sha1` 增加 `sha1: str` 注解并收紧格式判定

MODULE client.py
ADD P115Client.fs_category_shortcut_app :: self, payload: int | str | dict=0, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
ADD P115Client.fs_category_shortcut_set_app :: self, payload: int | str | dict=0, /, set: bool=True, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
ADD P115Client.fs_files_app3 :: self, payload: None | int | str | dict=0, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
ADD P115Client.fs_label_list2 :: self, payload: str | dict='', /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
ADD P115Client.fs_label_list_app2 :: self, payload: str | dict='', /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
ADD P115Client.life_behavior_doc_post :: self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
ADD P115Client.upload_quota :: self, /, base_url: str | Callable[[], str]='https://uplb.115.com', *, async_: Literal[False, True]=False, **request_kwargs
ADD P115Client.user_space_detail :: self, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
ADD P115OpenClient.access_token :: self, /
SIG P115Client.download_downfolder_app :: OLD self, payload: str | dict, /, app: str='chrome', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='chrome', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.download_files :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.download_files_app :: OLD self, payload: str | dict, /, app: str='chrome', version: str='2.0', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='chrome', version: str='2.0', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.download_folders :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.download_folders_app :: OLD self, payload: str | dict, /, app: str='chrome', version: str='2.0', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='chrome', version: str='2.0', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.download_url_app :: OLD self, payload: str | dict, /, user_agent: None | str=None, app: str='chrome', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, user_agent: None | str=None, app: str='chrome', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.extract_info :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.extract_info_app :: OLD self, payload: str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.extract_push :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.extract_push_app :: OLD self, payload: str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.extract_push_progress :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.extract_push_progress_app :: OLD self, payload: str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_document :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_document_app :: OLD self, payload: str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_history :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_history_app :: OLD self, payload: str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_history_set :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_history_set_app :: OLD self, payload: str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_image :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_label_set :: OLD self, payload: int | str | Iterable[int | str] | list[tuple] | dict, /, label: int | str='', base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | Iterable[int | str] | list[tuple] | dict, /, label_id: int | str=0, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_label_set_app :: OLD self, payload: int | str | Iterable[int | str] | list[tuple] | dict, /, label: int | str='', app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | Iterable[int | str] | list[tuple] | dict, /, label_id: int | str=0, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_music :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_music_app :: OLD self, payload: str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_music_file_exist :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_music_info :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_music_info_app :: OLD self, payload: str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_music_status :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_office_init :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_preview :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_supervision :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_supervision_app :: OLD self, payload: str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_video :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_video_app :: OLD self, payload: str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_video_is_transcode :: OLD self, payload: dict | str, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_video_push :: OLD self, payload: dict | str, /, base_url: str | Callable[[], str]='https://115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | dict | str, /, base_url: str | Callable[[], str]='https://115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_video_subtitle :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_video_subtitle_app :: OLD self, payload: str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, app: str='android', base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.fs_video_transcode :: OLD self, payload: dict | str, /, app: str='web', base_url: str | Callable[[], str]='https://transcode.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: dict | str, /, app: str='web', base_url: str | Callable[[], str]='https://transcode.115.com', method: str='GET', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.life_recent_operation_items :: OLD self, payload: str | dict='browse_document', /, app: str='web', base_url: str | Callable[[], str]='https://life.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: str | dict='browse_image', /, app: str='web', base_url: str | Callable[[], str]='https://life.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.multimedia_relate_file :: OLD self, payload: dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://webapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115Client.upload_resume :: OLD self, payload: dict | str, /, base_url: str | Callable[[], str]='https://uplb.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: str | dict, /, base_url: str | Callable[[], str]='https://uplb.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115OpenClient.download_url_info :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', user_agent: None | str=None, *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', user_agent: None | str=None, *, async_: Literal[False, True]=False, **request_kwargs
SIG P115OpenClient.fs_video :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115OpenClient.fs_video_history :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115OpenClient.fs_video_history_set :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115OpenClient.fs_video_push :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115OpenClient.fs_video_subtitle :: OLD self, payload: str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115OpenClient.upload_gettoken_open :: OLD self, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: int | dict={}, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
SIG P115OpenClient.upload_resume :: OLD self, payload: dict | str, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, payload: str | dict, /, base_url: str | Callable[[], str]='https://proapi.115.com', *, async_: Literal[False, True]=False, **request_kwargs
MODULE fs/fs.py
ADD P115FileSystem.search :: self, /, search_value: int | str='.', pid: None | int=None, page_size: int=1000, *, async_: Literal[False, True]=False, **request_kwargs
ADD P115Path.search :: self, /, search_value: int | str='.', page_size: int=1000, *, async_: Literal[False, True]=False, **request_kwargs
MODULE fs/fs_base.py
ADD P115PathBase.dictdir :: self, /, refresh: None | bool=None, *, async_: Literal[False, True]=False, **request_kwargs
ADD P115PathBase.dictdir_path :: self, /, refresh: None | bool=None, *, async_: Literal[False, True]=False, **request_kwargs
ADD P115PathBase.listdir :: self, /, refresh: None | bool=None, *, async_: Literal[False, True]=False, **request_kwargs
ADD P115PathBase.listdir_path :: self, /, refresh: None | bool=None, *, async_: Literal[False, True]=False, **request_kwargs
SIG P115FileSystemBase.open :: OLD self, id_or_path: IDOrPathType, /, mode: Literal['r', 'rt', 'tr', 'rb', 'br']='rb', buffering: None | int=None, encoding: None | str=None, errors: None | str=None, newline: None | str=None, start: int=0, http_file_reader_cls: None | type[HTTPFileReader] | type[AsyncHTTPFileReader]=None, pid: None | int=None, refresh: None | bool=None, *, async_: Literal[False, True]=False :: NEW self, id_or_path: IDOrPathType, /, mode: Literal['r', 'rt', 'tr', 'rb', 'br']='rb', buffering: None | int=None, encoding: None | str=None, errors: None | str=None, newline: None | str=None, start: int=0, http_file_reader_cls: None | Callable[..., HTTPFileReader] | Callable[..., AsyncHTTPFileReader]=None, pid: None | int=None, refresh: None | bool=None, *, async_: Literal[False, True]=False
SIG P115PathBase.open :: OLD self, /, mode: Literal['r', 'rt', 'tr', 'rb', 'br']='rb', buffering: None | int=None, encoding: None | str=None, errors: None | str=None, newline: None | str=None, start: int=0, seek_threshold: int=1 << 20, http_file_reader_cls: None | type[HTTPFileReader] | type[AsyncHTTPFileReader]=None, refresh: None | bool=None, *, async_: Literal[False, True]=False, **request_kwargs :: NEW self, /, mode: Literal['r', 'rt', 'tr', 'rb', 'br']='rb', buffering: None | int=None, encoding: None | str=None, errors: None | str=None, newline: None | str=None, start: int=0, seek_threshold: int=1 << 20, http_file_reader_cls: None | Callable[..., HTTPFileReader] | Callable[..., AsyncHTTPFileReader]=None, refresh: None | bool=None, *, async_: Literal[False, True]=False, **request_kwargs
MODULE fs/fs_share.py
ADD P115ShareFileSystem.search :: self, /, search_value: str='.', pid: None | int=None, page_size: int=1000, *, async_: Literal[False, True]=False, **request_kwargs
ADD P115SharePath.search :: self, /, search_value: str='.', page_size: int=1000, *, async_: Literal[False, True]=False, **request_kwargs
