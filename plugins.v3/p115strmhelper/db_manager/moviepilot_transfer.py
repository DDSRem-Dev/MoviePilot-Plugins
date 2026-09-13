from typing import TYPE_CHECKING, List

try:
    from jieba_next import cut as jieba_cut
except ImportError:
    from jieba import cut as jieba_cut

from app.db.oper.transferhistory import TransferHistoryOper

from ..utils.async_bridge import run_coroutine_sync

if TYPE_CHECKING:
    from app.db.models.transferhistory import TransferHistory


class TransferHBOper(TransferHistoryOper):
    """
    历史记录数据库操作扩展
    """

    def get_transfer_his_by_path_title(self, path: str) -> List["TransferHistory"]:
        """
        通过路径查询转移记录
        所有匹配项

        :param path (str): 查询路径

        :return List: 数据列表
        """
        words = jieba_cut(path, HMM=False)
        title = "%".join(words)
        return run_coroutine_sync(
            self.async_list_by_title(title=title, page=1, count=-1)
        )
