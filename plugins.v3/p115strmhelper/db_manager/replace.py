from typing import Any, Dict, List, Type

from sqlalchemy import delete, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session


def replace_rows(db: Session, model: Type[Any], batch: List[Dict[str, Any]]) -> None:
    """
    批量替换网盘缓存记录，保持主键与唯一路径的顺序替换语义

    SQLite 使用原生 REPLACE，PostgreSQL 在表级写锁内删除冲突记录再批量插入
    同批次重复 ID 或路径以最后实际存活的记录为准，NULL 路径不参与唯一性冲突

    :param db (Session): 调用方事务
    :param model (Type): 插件自有表模型
    :param batch (List): 云端文件或事件记录
    """
    if not batch:
        return
    if db.get_bind().dialect.name == "sqlite":
        db.execute(sqlite_insert(model).prefix_with("OR REPLACE"), batch)
        return
    if db.get_bind().dialect.name != "postgresql":
        raise RuntimeError("不支持的插件数据库类型")

    table = model.__table__
    table_name = db.get_bind().dialect.identifier_preparer.quote(table.name)
    db.execute(text(f"LOCK TABLE {table_name} IN SHARE ROW EXCLUSIVE MODE"))
    survivors = {}
    path_owners = {}
    ids = set()
    paths = set()
    has_path = "path" in table.columns
    for item in batch:
        row = {}
        for column in table.columns:
            value = item.get(column.name)
            if value is None and column.default is not None:
                value = column.default.arg
            row[column.name] = value
        identity = row["id"]
        if identity is None:
            raise ValueError("网盘记录缺少 ID")
        if isinstance(identity, str):
            identity = int(identity)
            row["id"] = identity
        ids.add(identity)
        previous = survivors.pop(identity, None)
        if previous and has_path and previous["path"] is not None:
            path_owners.pop(previous["path"], None)
        if has_path and row["path"] is not None:
            path = row["path"]
            paths.add(path)
            conflict = path_owners.get(path)
            if conflict is not None:
                survivors.pop(conflict, None)
            path_owners[path] = identity
        survivors[identity] = row

    for column, values in ((table.c.id, ids), (table.c.get("path"), paths)):
        values = list(values)
        for offset in range(0, len(values), 500):
            db.execute(delete(table).where(column.in_(values[offset : offset + 500])))
    rows = list(survivors.values())
    for offset in range(0, len(rows), 500):
        db.execute(table.insert(), rows[offset : offset + 500])
