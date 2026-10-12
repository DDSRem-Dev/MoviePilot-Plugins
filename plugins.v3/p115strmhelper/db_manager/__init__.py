from functools import wraps
from inspect import signature
from threading import RLock
from time import sleep
from typing import Any, Callable, Dict, Generator, List, Optional, Self
from sqlite3 import OperationalError as SqlOperationalError, SQLITE_BUSY

from sqlalchemy import and_, inspect, func
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.exc import OperationalError

from ..core.config import configer
from app.sdk.database import PluginDatabaseHandle, plugin_declarative_base
from app.sdk.logging import logger


_DATABASE_LIFECYCLE_LOCK = RLock()


class _DBManager:
    def __init__(self) -> None:
        self._ready = False

    def get_database(self) -> PluginDatabaseHandle:
        """
        获取宿主当前实例的数据库句柄

        :return PluginDatabaseHandle: 已完成迁移的插件数据库

        :raises RuntimeError: 初始化未完成或插件已停止
        """
        with _DATABASE_LIFECYCLE_LOCK:
            if not self._ready:
                raise RuntimeError("插件数据库尚未初始化或已停止")
            return configer.plugin_instance.get_database()

    def close_database(self) -> None:
        """
        停止接受新数据库操作，连接池由宿主生命周期释放
        """
        with _DATABASE_LIFECYCLE_LOCK:
            self._ready = False


def get_db() -> Generator[Session, None, None]:
    """
    提供宿主插件数据库会话，事务提交由调用方决定

    :yields Session: 当前请求的独立会话
    """
    with ct_db_manager.get_database().session() as db:
        yield db


def init_database() -> bool:
    """
    在启动后台服务前完成宿主建表与旧库导入

    :return bool: 初始化成功时返回 True
    """
    with _DATABASE_LIFECYCLE_LOCK:
        from .init import initialize_database

        ct_db_manager._ready = False
        initialize_database(configer.plugin_instance, configer.PLUGIN_DB_PATH)
        ct_db_manager._ready = True
    return True


def _database_operation(func: Callable, write: bool) -> Callable:
    call_signature = signature(func)

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound = call_signature.bind_partial(*args, **kwargs)
        db = bound.arguments.get("db")
        if db is not None:
            if not isinstance(db, Session):
                raise TypeError("db 必须为 SQLAlchemy Session 或 None")
            return func(*args, **kwargs)

        for attempt in range(3):
            with ct_db_manager.get_database().session() as session:
                bound.arguments["db"] = session
                try:
                    result = func(*bound.args, **bound.kwargs)
                    if write:
                        session.flush()
                        session.expunge_all()
                        session.commit()
                    return result
                except OperationalError as err:
                    session.rollback()
                    code = getattr(err.orig, "sqlite_errorcode", 0)
                    if not (
                        isinstance(err.orig, SqlOperationalError)
                        and code & 0xFF == SQLITE_BUSY
                        and attempt < 2
                    ):
                        raise
                    delay = 0.1 * 2**attempt
                    logger.warning(f"插件数据库忙，{delay}s 后重试当前事务")
                except Exception:
                    session.rollback()
                    raise
            sleep(delay)
        raise RuntimeError("插件数据库操作未完成")

    return wrapper


def db_update(func: Callable) -> Callable:
    """
    自动管理插件自有表的写事务，显式传入的会话由调用方提交或回滚

    :param func (Callable): 含 db 参数的数据库操作

    :return Callable: 保留原签名的数据库操作
    """
    return _database_operation(func, write=True)


def db_query(func: Callable) -> Callable:
    """
    自动管理插件自有表的查询会话，结果须在函数内完成物化

    :param func (Callable): 含 db 参数的查询操作

    :return Callable: 保留原签名的查询操作
    """
    return _database_operation(func, write=False)


def path_startswith(db: Session, column: Any, prefix: str) -> ColumnElement[bool]:
    """
    保留原 SQLite 路径前缀匹配在两种宿主数据库中的语义

    原 startswith 使用 LIKE，百分号和下划线仍是通配符，反斜杠不作转义
    SQLite 默认仅折叠 ASCII 大小写，PostgreSQL 使用相同折叠规则

    :param db (Session): 当前数据库会话
    :param column (Any): 路径字段
    :param prefix (str): 原路径匹配前缀

    :return ColumnElement: 保持原匹配范围的 SQL 条件
    """
    if db.get_bind().dialect.name == "sqlite":
        return column.startswith(prefix)
    uppercase = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    lowercase = "abcdefghijklmnopqrstuvwxyz"
    return func.translate(column, uppercase, lowercase).startswith(
        prefix.translate(str.maketrans(uppercase, lowercase)), escape=""
    )


class P115StrmHelperBase(plugin_declarative_base()):
    """
    使用独立元数据注册表的插件模型基类
    """

    __abstract__ = True

    @db_update
    def create(self, db: Session) -> None:
        """
        将当前记录加入调用方事务
        """
        db.add(self)

    @classmethod
    @db_query
    def get(cls, db: Session, rid: int) -> Optional[Self]:
        """
        根据主键查询记录
        """
        return db.query(cls).filter(and_(cls.id == rid)).first()

    @db_update
    def update(self, db: Session, payload: Dict[str, Any]) -> None:
        """
        更新非空字段并将脱离会话的对象加入当前事务
        """
        for key, value in payload.items():
            if value is not None:
                setattr(self, key, value)
        if inspect(self).detached:
            db.add(self)

    @classmethod
    @db_update
    def delete(cls, db: Session, rid: int) -> None:
        """
        按主键删除记录
        """
        db.query(cls).filter(and_(cls.id == rid)).delete()

    @classmethod
    @db_update
    def truncate(cls, db: Session) -> None:
        """
        清空当前模型的数据
        """
        db.query(cls).delete()

    @classmethod
    @db_query
    def list(cls, db: Session) -> List[Self]:
        """
        读取并物化当前模型的全部记录
        """
        return list(db.query(cls).all())

    def to_dict(self) -> Dict[str, Any]:
        """
        返回当前记录的列值快照
        """
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }


class DbOper:
    """
    可选地接收调用方会话的插件数据库操作基类
    """

    def __init__(self, db: Optional[Session] = None) -> None:
        self._db = db


ct_db_manager = _DBManager()
