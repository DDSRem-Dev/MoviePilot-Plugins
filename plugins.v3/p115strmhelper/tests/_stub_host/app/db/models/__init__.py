"""
``app.db.models`` 包替身。

真实宿主用 SQLModel 定义 ORM 模型。替身用普通类模拟模型实例的字段访问语义，
让插件在无数据库环境下也能构造/读取历史记录对象。
"""

from .transferhistory import TransferHistory

__all__ = ["TransferHistory"]
