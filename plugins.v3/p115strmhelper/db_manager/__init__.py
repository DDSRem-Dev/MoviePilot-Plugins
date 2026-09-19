from threading import RLock
from time import sleep
from typing import Any, Generator, List, Optional, Self, Tuple
from sqlite3 import OperationalError as SqlOperationalError, SQLITE_BUSY

from sqlalchemy import and_, inspect
from sqlalchemy.orm import declared_attr, Session
from sqlalchemy.exc import OperationalError

from app.sdk.database import PluginDatabaseHandle, plugin_declarative_base
from app.sdk.logging import logger


# 当前插件实例（本体或分身）绑定的数据库句柄
#
# v3 下每个插件实例（本体与每个分身）运行的是各自独立执行的模块副本（宿主加载器对
# 分身按实例标识重新 exec 一遍插件源码，参见 app/runtime/extensions/plugin/loader.py
# 的 load_instance/_execute_instance_module），本模块的模块级全局变量因此天然按实例
# 隔离，不会被本体与分身共用；不需要额外的线程绑定或 contextvar 方案
_HANDLE_LOCK = RLock()
_active_handle: Optional[PluginDatabaseHandle] = None


def bind_handle(handle: PluginDatabaseHandle) -> None:
    """
    绑定当前插件实例的数据库句柄

    必须在 init_plugin() 中、存量数据库迁移（core.legacy_migration）完成之后调用一次；
    重复调用（如配置热重载重新执行 init_plugin）用同一插件实例取得的句柄覆盖即可，
    句柄本身由宿主按插件标识缓存，重复获取不会重复建库

    :param handle (PluginDatabaseHandle): 宿主返回的插件自有数据库句柄
    """
    global _active_handle
    with _HANDLE_LOCK:
        _active_handle = handle


def _current_handle() -> PluginDatabaseHandle:
    """
    获取当前已绑定的数据库句柄

    :return PluginDatabaseHandle: 已绑定的句柄

    :raises RuntimeError: 尚未调用 bind_handle() 绑定句柄时抛出
    """
    if _active_handle is None:
        raise RuntimeError(
            "插件数据库句柄尚未绑定，必须先在 init_plugin() 中调用 bind_handle()"
        )
    return _active_handle


def get_db() -> Generator:
    """
    获取数据库会话，用于WEB请求

    :return Generator: 数据库会话生成器
    """
    db = None
    try:
        db = _current_handle().session()
        yield db
    finally:
        if db:
            db.close()


def get_args_db(args: tuple, kwargs: dict) -> Optional[Session]:
    """
    从参数中获取数据库Session对象

    :param args (Tuple): 位置参数元组
    :param kwargs (Dict): 关键字参数字典

    :return Session: 数据库会话对象，未找到返回 None
    """
    db = None
    if args:
        for arg in args:
            if isinstance(arg, Session):
                db = arg
                break
    if kwargs:
        for _, value in kwargs.items():
            if isinstance(value, Session):
                db = value
                break
    return db


def update_args_db(args: tuple, kwargs: dict, db: Session) -> Tuple[tuple, dict]:
    """
    更新参数中的数据库Session对象

    关键字传参时更新db的值，否则更新第1或第2个参数

    :param args (Tuple): 位置参数元组
    :param kwargs (Dict): 关键字参数字典
    :param db (Session): 数据库会话对象

    :return Tuple: 更新后的 (args, kwargs)
    """
    if kwargs and "db" in kwargs:
        kwargs["db"] = db
    elif args:
        if args[0] is None:
            args = (db, *args[1:])
        else:
            args = (args[0], db, *args[2:])
    return args, kwargs


def db_update(func):
    """
    数据库更新类操作装饰器，第一个参数必须是数据库会话或存在db参数
    """

    def wrapper(*args, **kwargs):
        """
        自动获取数据库会话、执行更新操作并处理重试逻辑

        :param args: 原始位置参数
        :param kwargs: 原始关键字参数

        :return: 被装饰函数的返回值

        :raises OperationalError: 重试耗尽后仍无法获取数据库锁时抛出
        """
        # 是否关闭数据库会话
        _close_db = False
        db = get_args_db(args, kwargs)
        if not db:
            # 每个插件实例线程绑定各自独立的会话，不同实例互不复用
            db = _current_handle().scoped_session()
            # 标记需要关闭数据库会话
            _close_db = True
            # 更新参数中的数据库会话
            args, kwargs = update_args_db(args, kwargs, db)

        max_retries = 3
        retry_delay = 0.1
        last_err = None

        try:
            for attempt in range(max_retries):
                try:
                    # 执行函数
                    result = func(*args, **kwargs)
                    # 提交事务
                    db.commit()
                    return result
                except OperationalError as err:
                    # 回滚事务
                    db.rollback()
                    last_err = err
                    if not (
                        isinstance(err.orig, SqlOperationalError)
                        and err.orig.sqlite_errorcode == SQLITE_BUSY
                    ):
                        raise err

                    logger.warning(
                        f"数据库锁定，第 {attempt + 1} 次重试，等待 {retry_delay}s..."
                    )
                    sleep(retry_delay)
                    retry_delay *= 2
            if last_err:
                raise last_err
        except Exception as err:
            if not isinstance(err, OperationalError):
                db.rollback()
            raise err
        finally:
            # 关闭数据库会话
            if _close_db:
                db.close()

    return wrapper


def db_query(func):
    """
    数据库查询操作装饰器，第一个参数必须是数据库会话或存在db参数
    注意：db.query列表数据时，需要转换为list返回
    """

    def wrapper(*args, **kwargs):
        """
        自动获取数据库会话、执行查询操作并管理会话生命周期

        :param args: 原始位置参数
        :param kwargs: 原始关键字参数

        :return: 被装饰函数的返回值
        """
        # 是否关闭数据库会话
        _close_db = False
        # 从参数中获取数据库会话
        db = get_args_db(args, kwargs)
        if not db:
            # 每个插件实例线程绑定各自独立的会话，不同实例互不复用
            db = _current_handle().scoped_session()
            # 标记需要关闭数据库会话
            _close_db = True
            # 更新参数中的数据库会话
            args, kwargs = update_args_db(args, kwargs, db)
        try:
            # 执行函数
            result = func(*args, **kwargs)
        except Exception as err:
            raise err
        finally:
            # 关闭数据库会话
            if _close_db:
                db.close()
        return result

    return wrapper


# 插件自有表的声明式基类，携带独立 MetaData：既不与宿主注册表抢注册，也不会与其它
# 插件定义同名表冲突；热重载会重新执行本模块、重新调用一次 plugin_declarative_base()，
# 因此每次都拿到干净的注册表
_PluginDeclarativeBase = plugin_declarative_base()


class P115StrmHelperBase(_PluginDeclarativeBase):
    """
    P115StrmHelper 数据库模型基类，提供通用的 CRUD 操作方法
    """

    id: Any
    __name__: str

    @db_update
    def create(self, db: Session):
        """
        创建新记录并添加到数据库

        :param db (Session): 数据库会话
        """
        db.add(self)

    @classmethod
    @db_query
    def get(cls, db: Session, rid: int) -> Self:
        """
        根据主键 ID 查询单条记录

        :param db (Session): 数据库会话
        :param rid (int): 记录 ID

        :return Self: 匹配的模型实例，未找到时返回 None
        """
        return db.query(cls).filter(and_(cls.id == rid)).first()

    @db_update
    def update(self, db: Session, payload: dict):
        """
        更新当前记录的部分字段

        :param db (Session): 数据库会话
        :param payload (Dict): 要更新的字段字典，值为 None 的键会被过滤
        """
        payload = {k: v for k, v in payload.items() if v is not None}
        for key, value in payload.items():
            setattr(self, key, value)
        if inspect(self).detached:
            db.add(self)

    @classmethod
    @db_update
    def delete(cls, db: Session, rid):
        """
        根据主键 ID 删除记录

        :param db (Session): 数据库会话
        :param rid (int): 记录 ID
        """
        db.query(cls).filter(and_(cls.id == rid)).delete()

    @classmethod
    @db_update
    def truncate(cls, db: Session):
        """
        清空当前模型对应的数据库表所有记录

        :param db (Session): 数据库会话
        """
        db.query(cls).delete()

    @classmethod
    @db_query
    def list(cls, db: Session) -> List[Self]:
        """
        查询当前模型的所有记录

        :param db (Session): 数据库会话

        :return List: 所有记录列表
        """
        result = db.query(cls).all()
        return list(result)

    def to_dict(self):
        """
        将模型实例的所有数据库列转换为字典

        :return Dict: 列名到列值的字典映射
        """
        return {c.name: getattr(self, c.name, None) for c in self.__table__.columns}  # noqa

    @declared_attr
    def __tablename__(self) -> str:
        return self.__name__.lower()


class DbOper:
    """
    数据库操作基类
    """

    _db: Session = None

    def __init__(self, db: Session = None):
        """
        初始化数据库操作基类

        :param db (Session): 数据库会话，可选
        """
        self._db = db
