"""
宿主 JobView 适配层。

MoviePilot V3 把作业队列实现从 ``app.chain.transfer`` 收敛到
``app.application.transfer.workflow.JobManager``，并把 ``TransferChain.jobview``
定义为该实现的一个**稳定伴生访问点**。插件原先在 handler / patch 里散落了 30 余处
``chain.jobview.xxx`` 直接调用，存在两类风险：

1. 宿主调整 JobManager 方法名或归属时，改动点分散、难以统一兜底；
2. 插件依赖了 JobManager 的**私有方法**（``_JobManager__get_media_id``）与私有容器
   （``_job_view``），名字改写规则一旦变化就会静默失效。

本模块把全部队列操作收口成 ``JobViewAdapter``，调用方只依赖插件自己的接口：

* 公开方法直接转发，缺失时记录明确的告警而非抛出；
* 依赖宿主私有的调试能力（任务状态详情）改为**能力探测 + 降级**，取不到就跳过
  诊断日志，绝不影响主流程。
"""

from typing import Any, Callable, List, Optional

from app.sdk.logging import logger

__all__ = ["JobViewAdapter", "get_jobview", "get_task_lock"]

# 适配器初始化时要求宿主必须提供的方法；缺失说明宿主接口已变更
_REQUIRED_METHODS = (
    "add_task",
    "remove_task",
    "running_task",
    "finish_task",
    "fail_task",
    "remove_job",
    "try_remove_job",
    "is_done",
)


class JobViewAdapter:
    """
    对宿主 JobManager 的薄适配器。

    对宿主公开接口做直通转发；对宿主私有实现细节做能力探测与优雅降级。
    """

    __slots__ = ("_jobview", "_owner")

    def __init__(self, jobview: Any, owner: str = "TransferChain"):
        """
        :param jobview: 宿主 JobManager 实例
        :param owner: 来源描述，仅用于日志定位
        """
        self._jobview = jobview
        self._owner = owner

    @property
    def raw(self) -> Any:
        """返回原始宿主对象，供确实需要直连的场景使用。"""
        return self._jobview

    def is_available(self) -> bool:
        """宿主对象是否存在且具备必需接口。"""
        return self._jobview is not None and all(
            callable(getattr(self._jobview, name, None)) for name in _REQUIRED_METHODS
        )

    def verify(self) -> bool:
        """
        校验宿主 JobManager 接口完整性。

        返回 False 时调用方可决定降级策略；缺失项会逐条记录，便于定位宿主变更。
        """
        if self._jobview is None:
            logger.error(f"【整理接管】{self._owner} 未提供 jobview，作业队列不可用")
            return False
        missing = [
            name
            for name in _REQUIRED_METHODS
            if not callable(getattr(self._jobview, name, None))
        ]
        if missing:
            logger.error(
                f"【整理接管】宿主 jobview 缺少方法 {missing}，"
                f"作业队列接口可能已变更，请检查插件适配"
            )
            return False
        return True

    def _call(self, name: str, *args, default: Any = None, **kwargs) -> Any:
        """
        安全调用宿主公开方法。

        :param name: 宿主方法名
        :param default: 方法缺失或调用异常时的返回值
        """
        func = getattr(self._jobview, name, None)
        if not callable(func):
            logger.warning(
                f"【整理接管】宿主 jobview 不支持 {name}，本次跳过"
                f"（宿主接口可能已变更）"
            )
            return default
        try:
            return func(*args, **kwargs)
        except Exception as err:
            logger.error(f"【整理接管】调用 jobview.{name} 失败: {err}", exc_info=True)
            return default

    # ---------- 作业状态流转 ----------

    def add_task(self, task, state: str = "waiting") -> Any:
        """加入作业队列。"""
        return self._call("add_task", task, state=state)

    def migrate_task(self, task) -> Any:
        """把任务从 meta 作业迁移到 media 作业。"""
        return self._call("migrate_task", task)

    def running_task(self, task) -> Any:
        """标记任务为处理中。"""
        return self._call("running_task", task)

    def finish_task(self, task) -> Any:
        """标记任务完成。"""
        return self._call("finish_task", task)

    def fail_task(self, task) -> Any:
        """标记任务失败。"""
        return self._call("fail_task", task)

    def remove_task(self, fileitem) -> Any:
        """按文件项移除任务。"""
        return self._call("remove_task", fileitem)

    def remove_job(self, task) -> Any:
        """移除作业。"""
        return self._call("remove_job", task)

    def try_remove_job(self, task) -> Any:
        """尝试移除已完成作业。"""
        return self._call("try_remove_job", task)

    # ---------- 状态查询 ----------

    def is_done(self, task) -> bool:
        """作业是否全部完成。"""
        return bool(self._call("is_done", task, default=False))

    def is_finished(self, task) -> bool:
        """作业是否已结束。"""
        return bool(self._call("is_finished", task, default=False))

    def is_success(self, task) -> bool:
        """作业是否成功。"""
        return bool(self._call("is_success", task, default=False))

    def count(self, media, season: Optional[int] = None) -> int:
        """统计媒体对应的任务数。"""
        return self._call("count", media, season=season, default=0)

    def size(self, media, season: Optional[int] = None) -> int:
        """统计媒体对应的任务体积。"""
        return self._call("size", media, season=season, default=0)

    def season_episodes(self, *args, **kwargs) -> Any:
        """查询季集信息。"""
        return self._call("season_episodes", *args, **kwargs)

    def success_tasks(self, *args, **kwargs) -> List[Any]:
        """查询成功任务列表。"""
        result = self._call("success_tasks", *args, **kwargs)
        return result if result is not None else []

    # ---------- 依赖宿主私有实现的诊断能力（可降级） ----------

    def describe_job_tasks(self, mediainfo, season: Optional[int] = None):
        """
        获取某媒体作业下各任务的 ``(文件名, 状态)`` 列表，用于失败诊断。

        宿主把该能力放在私有方法 ``_JobManager__get_media_id`` 与私有容器
        ``_job_view`` 上，跨版本最易失效。因此这里做逐级能力探测：任一级取不到就
        返回 ``None``，调用方跳过诊断日志即可，不影响整理主流程。

        主路径走 V3 公开导出的 ``get_job_id``（它内部会按 mediainfo 分派到
        media 作业），仅在其不可用时才回退到私有名字改写方法。
        """
        jobview = self._jobview
        if jobview is None:
            return None

        job_id = self._resolve_job_id(jobview, mediainfo, season)
        if job_id is None:
            return None

        job_view = getattr(jobview, "_job_view", None)
        if not isinstance(job_view, dict) or job_id not in job_view:
            return None

        job = job_view[job_id]
        tasks = getattr(job, "tasks", None) or []
        return [
            (
                getattr(getattr(t, "fileitem", None), "name", None) or "None",
                getattr(t, "state", None),
            )
            for t in tasks
        ]

    @staticmethod
    def _resolve_job_id(jobview: Any, mediainfo, season: Optional[int]) -> Any:
        """逐级解析作业 ID，全部不可用时返回 None。"""
        # 主路径：V3 公开导出的 get_job_id，接受完整 task
        get_job_id = getattr(jobview, "get_job_id", None)
        if callable(get_job_id):
            probe = _build_probe_task(mediainfo, season)
            if probe is not None:
                try:
                    return get_job_id(probe)
                except Exception as err:
                    logger.debug(f"【整理接管】get_job_id 解析失败，尝试回退: {err}")

        # 回退：私有名字改写方法，名字随宿主类名变化
        mangled = getattr(jobview, "_JobManager__get_media_id", None)
        if callable(mangled):
            try:
                return mangled(media=mediainfo, season=season)
            except Exception as err:
                logger.debug(f"【整理接管】私有作业 ID 方法调用失败: {err}")

        logger.debug("【整理接管】宿主未提供作业 ID 查询能力，跳过任务状态诊断")
        return None


def _build_probe_task(mediainfo, season: Optional[int], fileitem=None):
    """
    构造一个仅用于计算作业 ID 的最小任务对象。

    作业 ID 由媒体身份与季信息决定，与文件项无关，因此传最小可用字段即可。
    任一步不可用时返回 ``None``，由调用方回退到私有方法或直接降级。

    :param mediainfo: 已识别的媒体信息
    :param season: 季号
    :param fileitem: 可选文件项
    :return: 最小 TransferTask；构造不可用返回 None
    """
    try:
        from app.schemas import TransferTask as MPTransferTask
        from app.sdk.media import MetaBase
    except Exception as err:
        logger.debug(f"【整理接管】探针任务所需宿主类型不可用: {err}")
        return None

    try:
        meta = MetaBase()
        if season is not None:
            try:
                meta.begin_season = season
            except Exception:
                pass
        return MPTransferTask(fileitem=fileitem, mediainfo=mediainfo, meta=meta)
    except Exception as err:
        logger.debug(f"【整理接管】构造探针任务失败: {err}")
        return None


def get_jobview(chain) -> Optional[JobViewAdapter]:
    """
    从宿主链对象取得 JobView 适配器。

    :param chain: 宿主 TransferChain 实例
    :return: 适配器；宿主未提供 jobview 时返回 None
    """
    jobview = getattr(chain, "jobview", None)
    if jobview is None:
        logger.warning("【整理接管】宿主对象未提供 jobview，作业队列功能将跳过")
        return None
    return JobViewAdapter(jobview, owner=getattr(chain, "__class__", type(chain)).__name__)


def get_task_lock() -> Optional[Callable]:
    """
    取得宿主提供的整理任务锁。

    :return: 锁对象（可作上下文管理器）；宿主未提供时返回 None
    """
    try:
        from app.chain.transfer import task_lock
    except Exception as err:
        logger.error(f"【整理接管】获取宿主 task_lock 失败: {err}")
        return None
    return task_lock
