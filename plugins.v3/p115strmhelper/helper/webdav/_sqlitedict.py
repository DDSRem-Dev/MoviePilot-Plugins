#!/usr/bin/env python3
# encoding: utf-8
"""
本地内置的 ``SqliteTableDict``
"""

from collections.abc import Iterator, MutableMapping
from contextlib import suppress
from sqlite3 import connect, Connection, Cursor, ProgrammingError

from sqlitetools import enclose, execute, find, query

__all__ = ["SqliteTableDict"]


class AutoCloseCursor(Cursor):
    """
    会自动关闭的 Cursor
    """

    def __del__(self, /):
        self.close()


class AutoCloseConnection(Connection):
    """
    会自动关闭的 Connection
    """

    def __del__(self, /):
        with suppress(ProgrammingError):
            self.commit()
        self.close()

    def cursor(self, /, factory=AutoCloseCursor):
        return super().cursor(factory)


class SqliteTableDict(MutableMapping):
    def __init__(
        self,
        con,
        /,
        table: str = "data",
        key: str | tuple[str, ...] = "id",
        value: str | tuple[str, ...] = "data",
        where: str = "",
    ):
        if not isinstance(con, (Connection, Cursor)):
            con = connect(con, factory=AutoCloseConnection)
        self.con = con
        table = enclose(table)
        key_is_tuple = self._key_is_tuple = isinstance(key, tuple)
        value_is_tuple = self._value_is_tuple = isinstance(value, tuple)
        if key_is_tuple:
            self._key_len = len(key)
            key_str = ",".join(map(enclose, key))
            key_pred_str = " AND ".join(f"{k}=?" for k in map(enclose, key))
        else:
            self._key_len = 0
            key_str = enclose(key)
            key_pred_str = f"{key_str}=?"
        if value_is_tuple:
            self._value_len = len(value)
            value_str = ",".join(map(enclose, value))
            value_conflict_set_str = ",".join(
                f"{v}=excluded.{v}" for v in map(enclose, value)
            )
        else:
            self._value_len = 0
            value_str = enclose(value)
            value_conflict_set_str = f"{value_str}=excluded.{value_str}"
        where_str = where
        if where:
            where_str = " AND " + where
        self._sql_delitem = f"DELETE FROM {table} WHERE {key_pred_str}{where_str}"
        self._sql_getitem = (
            f"SELECT {value_str} FROM {table} WHERE {key_pred_str}{where_str} LIMIT 1"
        )
        n_qmarks = ",".join("?" * ((self._key_len or 1) + (self._value_len or 1)))
        self._sql_setitem = (
            f"INSERT INTO {table}({key_str},{value_str}) VALUES ({n_qmarks}) "
            f"ON CONFLICT({key_str}) DO UPDATE SET {value_conflict_set_str}"
        )
        where_str = where
        if where:
            where_str = " WHERE " + where
        self._sql_iter = f"SELECT {key_str} FROM {table}{where_str}"
        self._sql_len = f"SELECT COUNT(1) FROM {table}{where_str}"
        self._sql_clear = f"DELETE FROM {table}{where_str}"
        self._sql_iter_values = f"SELECT {value_str} FROM {table}{where_str}"
        self._sql_iter_items = f"SELECT {key_str},{value_str} FROM {table}{where_str}"

    def __delitem__(self, key, /):
        cur = execute(
            self.con,
            self._sql_delitem,
            key,
            commit=True,
        )
        cur.close()
        if not cur.rowcount:
            raise KeyError(key)

    def __getitem__(self, key, /):
        return find(
            self.con,
            self._sql_getitem,
            key,
            default=KeyError(key),
            row_factory="any" if self._value_is_tuple else "one",
        )

    def __setitem__(self, key, val, /):
        if not isinstance(key, tuple):
            key = (key,)
        if not isinstance(val, tuple):
            val = (val,)
        execute(self.con, self._sql_setitem, key + val, commit=True).close()

    def __iter__(self, /) -> Iterator:
        return query(
            self.con,
            self._sql_iter,
            row_factory="any" if self._key_is_tuple else "one",
        )

    def __len__(self, /) -> int:
        return find(self.con, self._sql_len)

    def clear(self, /):
        execute(self.con, self._sql_clear, commit=True).close()

    def iter_values(self, /):
        return query(
            self.con,
            self._sql_iter_values,
            row_factory="any" if self._value_is_tuple else "one",
        )

    def iter_items(self, /):
        return query(self.con, self._sql_iter_items, row_factory="any")
