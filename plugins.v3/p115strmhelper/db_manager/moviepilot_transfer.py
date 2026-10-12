from typing import List, Optional

from app.db.base import DbOper
from app.db.models.transferhistory import TransferHistory
from app.sdk.queries import (
    MAX_QUERY_PAGE_SIZE,
    QueryPageRequest,
    QuerySort,
    QuerySortDirection,
    QuerySortField,
    TransferHistoryFilter,
    TransferHistorySnapshot,
    list_transfer_history,
)
from app.schemas.types import MediaSource, MediaType

try:
    from app.sdk.utilities import cut as jieba_cut
except ImportError:
    from app.foundation.text import cut as jieba_cut


class TransferHBOper(DbOper):
    """
    通过 V3 查询接口读取整理历史，分词搜索保留宿主原有匹配规则
    """

    @staticmethod
    def _list(filters: TransferHistoryFilter) -> List[TransferHistorySnapshot]:
        """
        按稳定主键顺序读取全部有界分页并物化快照
        """
        result = []
        seen = set()
        page_number = 1
        while True:
            page = list_transfer_history(
                filters=filters,
                page=QueryPageRequest(
                    page=page_number,
                    count=MAX_QUERY_PAGE_SIZE,
                    sort=QuerySort(
                        field=QuerySortField.ID, direction=QuerySortDirection.ASC
                    ),
                ),
            )
            for item in page.items:
                if item.id not in seen:
                    seen.add(item.id)
                    result.append(item)
            if not page.has_next or not page.items:
                return result
            page_number += 1

    def get_transfer_his_by_path_title(
        self, path: str
    ) -> List[TransferHistorySnapshot]:
        """
        按原有分词模式搜索标题、源路径和目标路径

        SDK 的 text 仅支持字面包含，分词通配检索使用宿主短会话查询

        :param path (str): 查询路径

        :return List: 按原匹配规则返回的整理历史快照
        """
        words = jieba_cut(path, HMM=False)
        title = "%".join(words)

        def query(session):
            total = TransferHistory.count_by_title(session, title=title)
            records = TransferHistory.list_by_title(
                session, title=title, page=1, count=total
            )
            return [TransferHistorySnapshot.model_validate(row) for row in records]

        return self._execute_sync_query(query)

    def get_by_dest(self, path: str) -> Optional[TransferHistorySnapshot]:
        """
        精确查找目标路径对应的最新整理快照

        :param path (str): 完整目标路径，空路径返回 None

        :return TransferHistorySnapshot: 最新匹配记录，未找到返回 None
        """
        if not path or not path.strip():
            return None
        page = list_transfer_history(
            filters=TransferHistoryFilter(dest=path),
            page=QueryPageRequest(
                count=1,
                sort=QuerySort(
                    field=QuerySortField.ID, direction=QuerySortDirection.DESC
                ),
            ),
        )
        return page.items[0] if page.items else None

    def list_by_media_identity(
        self,
        media_source: MediaSource,
        media_id: str,
        media_type: MediaType,
        season: Optional[str] = None,
        episode: Optional[str] = None,
        dest: Optional[str] = None,
    ) -> List[TransferHistorySnapshot]:
        """
        按完整来源身份、媒体类型及可选季集路径精确查询

        :param media_source (MediaSource): 媒体数据来源
        :param media_id (str): 来源原生 ID
        :param media_type (MediaType): 电影或剧集类型
        :param season (str): 季标识，例如 S01
        :param episode (str): 集标识，例如 E01
        :param dest (str): 完整目标路径

        :return List: 符合全部条件的历史快照

        :raises ValueError: 身份或媒体类型为空，或指定空目标路径
        """
        if (
            not media_source
            or not media_id
            or str(media_id).strip() in ("", "0")
            or not media_type
        ):
            raise ValueError("查询整理历史必须提供完整媒体身份和类型")
        if dest is not None and not dest.strip():
            raise ValueError("显式目标路径不能为空")
        if episode is not None and (not season or not dest):
            raise ValueError("查询单集历史必须同时指定季和目标路径")
        return self._list(
            TransferHistoryFilter(
                media_source=media_source,
                media_id=str(media_id),
                media_types=(media_type,),
                seasons=season,
                episodes=episode,
                dest=dest,
            )
        )
