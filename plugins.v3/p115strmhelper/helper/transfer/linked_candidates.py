from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.chain.storage import StorageChain
from app.schemas import FileItem
from app.schemas.types import MediaType


def plan_linked_candidates(
    original: Any, planner: Any, items: List[Tuple[FileItem, bool]]
) -> Any:
    """
    沿用宿主筛选和媒体归属规则发现附件，交回原请求创建独立持久任务

    关联模式允许单视频请求发现同媒体附件，保留官方手动季集和识别词上下文
    显式选择的未匹配附件继续由宿主独立整理
    """
    if planner._batch_mtype == MediaType.MUSIC:
        return original(planner, items)
    chain = planner._chain
    mains = [
        item
        for item, bluray in items
        if not bluray
        and item.type == "file"
        and chain._is_media_file(item, planner._batch_mtype)
    ]
    if not mains:
        return original(planner, items)
    storage = StorageChain()
    folders: Dict[Any, List[FileItem]] = {}
    expanded = list(items)
    seen = {chain._get_file_key(item) for item, _ in items}
    inherited = {}
    for main in mains:
        key = chain._get_file_parent_key(main)
        if key not in folders:
            parent = storage.get_parent_item(main)
            folders[key] = (
                list(storage.list_files(parent, recursion=False) or [])
                if parent
                else []
            )
        siblings = folders[key]
        sibling_mains = [
            item
            for item in siblings
            if item.type == "file" and chain._is_media_file(item, planner._batch_mtype)
        ]
        history = chain._resolve_download_history(
            repository=chain.download_history_repository,
            file_path=Path(main.path),
            bluray_dir=False,
            download_hash=planner._download_hash,
        )
        words = chain._get_subscribe_custom_words(history)
        main_meta = planner._build_file_meta(main, custom_word_list=words)
        if not main_meta:
            continue
        for extra in siblings:
            extra_key = chain._get_file_key(extra)
            if (
                extra.type != "file"
                or extra_key in seen
                or not (chain._is_subtitle_file(extra) or chain._is_audio_file(extra))
                or not planner._is_allowed_transfer_item(extra, False)
            ):
                continue
            owner = chain._get_related_main_file_key(extra, sibling_mains or [main])
            if owner:
                if owner != chain._get_file_key(main):
                    continue
                extra_meta = main_meta
            else:
                extra_meta = planner._build_path_meta(
                    Path(extra.path), custom_word_list=words, force_video=True
                )
                if not chain._is_same_media_meta(main_meta, extra_meta):
                    continue
            expanded.append((extra, False))
            seen.add(extra_key)
            inherited[extra_key] = deepcopy(extra_meta)
    planned, host_inherited = original(planner, expanded)
    inherited.update(host_inherited)
    return planned, inherited
