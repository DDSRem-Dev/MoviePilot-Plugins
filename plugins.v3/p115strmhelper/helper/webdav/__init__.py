from asyncio import Lock
from collections.abc import AsyncIterator
from html import escape
from mimetypes import guess_type
from posixpath import split as splitpath
from sqlite3 import connect
from time import time
from urllib.parse import quote, unquote

from cachedict import LRUDict, TTLDict
from errno2 import errno
from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from p115client import check_response, P115Client
from p115client.exception import throw
from p115client.tool import (
    get_id_to_path,
    iterdir,
    normalize_attr_simple,
    traverse_tree_with_path,
    P115QueryDB,
)
from yarl import URL

from app.log import logger

from ._sqlitedict import SqliteTableDict
from ...core.config import configer
from ...utils.time import TimeUtils


class WebdavCore:
    """
    Webdav 模块
    """

    def __init__(
        self,
        client: P115Client,
        cache_dir_ttl: float = 300,
        cache_url: bool = True,
        cache_propfind: bool = True,
    ):
        """
        初始化 WebDAV 核心模块

        :param client (P115Client): P115Client 实例
        :param cache_dir_ttl (float): 目录缓存 TTL（秒）
        :param cache_url (bool): 是否启用 URL 缓存
        :param cache_propfind (bool): 是否启用 PROPFIND 缓存
        """
        self.client = client
        self.cache_attr: LRUDict[int | str, dict] = LRUDict(65536)
        self.cache_children: TTLDict[int, dict[str, dict]] = TTLDict(
            cache_dir_ttl, maxsize=1024
        )
        self.cache_lock: LRUDict[int, Lock] = LRUDict(1024)
        self.cache_url_enabled: bool = cache_url
        self.cache_url: TTLDict[tuple[int, str], str] = TTLDict(3600, maxsize=1024)
        self.cache_propfind_enabled: bool = cache_propfind
        self.cache_propfind: TTLDict = TTLDict(cache_dir_ttl, maxsize=128)

        with connect(":memory:", autocommit=True, check_same_thread=False) as con:
            con.executescript("""\
        PRAGMA journal_mode = WAL;
        CREATE TABLE data (
            id INTEGER NOT NULL PRIMARY KEY, 
            parent_id INTEGER NOT NULL, 
            name STRING NOT NULL, 
            is_dir INTEGER AS (1) VIRTUAL, 
            is_alive INTEGER AS (1) VIRTUAL
        );
        CREATE INDEX IF NOT EXISTS idx_data_pid ON data(parent_id);
        CREATE INDEX IF NOT EXISTS idx_data_utime ON data(parent_id, name);
        """)
            self.id_to_dirnode = SqliteTableDict(con, value=("parent_id", "name"))
            self.querydb = P115QueryDB(con)

    async def get_attr(self, path: int | str, /) -> dict:
        """
        获取文件或目录的属性

        :param path (int | str): 文件路径（str）或 115 文件 ID（int）
        :return Dict: 文件属性字典
        """
        if isinstance(path, str):
            path = "/" + path.strip("/")
            if path == "/":
                return {
                    "id": 0,
                    "parent_id": 0,
                    "is_dir": True,
                    "name": "",
                    "path": "/",
                }
            if attr := self.cache_attr.get(path):
                return attr
            dir_, name = splitpath(path)
            try:
                pid = self.querydb.get_id(path=dir_, is_alive=False)
            except FileNotFoundError:
                pass
            else:
                if (children := self.cache_children.get(pid)) is not None:
                    try:
                        return children[name]
                    except KeyError:
                        throw(errno.ENOENT, path)
            id = await get_id_to_path(
                self.client, path, async_=True, **configer.get_ios_ua_app(app=False)
            )
        else:
            id = path
            if attr := self.cache_attr.get(id):
                return attr
        resp = await self.client.fs_file(
            id, async_=True, **configer.get_ios_ua_app(app=False)
        )
        check_response(resp)
        attr = self.cache_attr[id] = self.cache_attr[path] = normalize_attr_simple(
            resp["data"][0]
        )
        return attr

    async def get_children(self, id: int, /, refresh: bool = False) -> dict[str, dict]:
        """
        获取目录的子项列表

        :param id (int): 目录 ID
        :param refresh (bool): 是否强制刷新缓存
        :return Dict: 以名称为键的子项属性字典
        """
        start = time()
        async with self.cache_lock.setdefault(id, Lock()):
            children: None | dict[str, dict]
            if time() - start > 0.05:
                refresh = False
            if not refresh and (children := self.cache_children.get(id)) is not None:
                return children
            children = {}
            async for attr in iterdir(
                self.client,
                id,
                id_to_dirnode=self.id_to_dirnode,
                escape=None,
                normalize_attr=normalize_attr_simple,
                async_=True,
                max_workers=0,
                **configer.get_ios_ua_app(app=False),
            ):
                self.cache_attr.pop(attr["id"], None)
                self.cache_attr.pop(attr["path"], None)
                children[attr["name"]] = attr
            self.cache_children[id] = children
            self.cache_propfind.pop(id, None)
            return children

    async def iter_descentants(self, id: int, /) -> AsyncIterator[dict]:
        """
        递归遍历目录下的所有后代（文件与子目录）

        :param id (int): 起始目录 ID
        :return AsyncIterator: 异步迭代器，产出文件/目录属性字典
        """
        async for attr in traverse_tree_with_path(
            self.client,
            id,
            id_to_dirnode=self.id_to_dirnode,
            escape=None,
            async_=True,
            **configer.get_ios_ua_app(app=False),
        ):
            self.cache_attr[attr["id"]] = self.cache_attr[attr["path"]] = attr
            yield attr

    async def get_url(
        self, id: int | str, /, user_agent: str = "", refresh: bool = False
    ) -> str:
        """
        获取文件的下载直链

        :param id (int | str): 文件 ID 或 pickcode
        :param user_agent (str): 请求时使用的 User-Agent
        :param refresh (bool): 是否强制刷新缓存
        :return str: 下载直链 URL
        """
        pickcode = self.client.to_pickcode(id)
        id = self.client.to_id(pickcode)
        if (
            not refresh
            and self.cache_url_enabled
            and (url := self.cache_url.get((id, user_agent)))
        ):
            if int(URL(url).query["t"]) - time() > 60 * 5:
                logger.debug(f"cached url for id {id}: {url}")
                return url
        resp = await self.client.download_url_app(
            pickcode, app="android", headers={"user-agent": user_agent}, async_=True
        )
        if not resp["state"]:
            if resp.get("error") == "文件上传不完整":
                throw(errno.EISDIR, id)
            check_response(resp)
        url = resp["data"]["url"]
        if self.cache_url_enabled:
            self.cache_url[(id, user_agent)] = url
        logger.debug(f"GET url for id {id}: {url}")
        return url

    @staticmethod
    def iter_response_parts(attr):
        """
        生成单个资源在 PROPFIND 响应中的 XML 片段

        :param attr (Dict): 文件属性字典
        :return Generator: 生成器，产出 XML 字符串片段
        """
        if attr["id"]:
            href = f"/<{attr['id']}/{quote(attr['name'])}"
        else:
            href = "/"
        yield f"<d:response><d:href>{escape(href)}</d:href><d:propstat><d:prop>"
        yield f"<d:displayname>{escape(attr['name'])}</d:displayname>"
        yield f"<d:creationdate>{TimeUtils.timestamp2isoformat(attr.get('ctime', 0))}</d:creationdate>"
        yield f"<d:getlastmodified>{TimeUtils.timestamp2gmtformat(attr.get('mtime', 0))}</d:getlastmodified>"
        if attr["is_dir"]:
            # yield "<d:getetag></d:getetag>"
            # yield "<d:getcontentlength></d:getcontentlength>"
            # yield "<d:getcontenttype></d:getcontenttype>"
            yield "<d:resourcetype><d:collection/></d:resourcetype>"
        else:
            yield f"<d:getetag>&quot;{attr.get('sha1', '')}&quot;</d:getetag>"
            yield f"<d:getcontentlength>{attr.get('size', 0)}</d:getcontentlength>"
            yield f"<d:getcontenttype>{guess_type(attr['name'])[0] or ''}</d:getcontenttype>"
            yield "<d:resourcetype></d:resourcetype>"
        yield "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"

    async def propfind(
        self,
        request: Request,
        path: str = "/",
        id: int = -1,
        pickcode: str = "",
        refresh: bool = False,
    ):
        """
        处理 WebDAV PROPFIND 请求，返回目录列表的 XML 响应

        :param request (Request): FastAPI Request 对象
        :param path (str): 请求路径
        :param id (int): 115 目录 ID（优先级高于 path）
        :param pickcode (str): 文件 pickcode
        :param refresh (bool): 是否强制刷新缓存
        :return Response: FastAPI Response 对象，状态码 207
        """
        if id >= 0:
            fid: int | str = id
        elif pickcode:
            fid = self.client.to_id(pickcode)
        elif path.lstrip("/").startswith("<"):
            fid = self.client.to_id(path.lstrip("/<").partition("/")[0])
        else:
            fid = path
        attr = await self.get_attr(fid)
        id = attr["id"]
        depth_header = request.headers.get("depth", "")
        depth = depth_header.encode() if depth_header else b""
        will_cache_propfind = False
        if (
            will_cache_propfind := self.cache_propfind_enabled
            and depth == b"1"
            and attr["is_dir"]
        ):
            if (content := self.cache_propfind.get(id)) is not None:
                logger.debug(f"PROPFIND a cached xml for {unquote(str(request.url))}")
                return Response(
                    content=content,
                    status_code=207,
                    media_type="application/xml; charset=utf-8",
                )
        parts = ['<?xml version="1.0" ?>\n<d:multistatus xmlns:d="DAV:">']
        push_parts = parts.extend
        push_parts(self.iter_response_parts(attr))
        if depth != b"0" and attr["is_dir"]:
            if depth == b"1":
                children = await self.get_children(id, refresh=refresh)
                for attr in children.values():
                    push_parts(self.iter_response_parts(attr))
            else:
                async for attr in self.iter_descentants(id):
                    push_parts(self.iter_response_parts(attr))
        parts.append("</d:multistatus>")
        content = "".join(parts).encode("utf-8")
        if will_cache_propfind:
            self.cache_propfind[id] = content
        logger.debug(f"PROPFIND a fresh xml for {unquote(str(request.url))}")
        return Response(
            content=content,
            status_code=207,
            media_type="application/xml; charset=utf-8",
        )

    async def get(
        self,
        request: Request,
        path: str = "/",
        id: int = -1,
        pickcode: str = "",
        refresh: bool = False,
    ):
        """
        处理 WebDAV GET 请求，返回文件内容或目录列表

        :param request (Request): FastAPI Request 对象
        :param path (str): 请求路径
        :param id (int): 115 文件 ID
        :param pickcode (str): 文件 pickcode
        :param refresh (bool): 是否强制刷新缓存
        :return RedirectResponse: 重定向响应或目录内容
        """
        if id >= 0:
            pickcode = self.client.to_pickcode(id)
        elif pickcode:
            id = self.client.to_id(pickcode)
        elif path.lstrip("/").startswith("<"):
            fid = path.lstrip("/<").partition("/")[0]
            id = self.client.to_id(fid)
            pickcode = self.client.to_pickcode(fid)
        else:
            attr = await self.get_attr(path)
            id = attr["id"]
            pickcode = self.client.to_pickcode(
                id, prefix="fa" if attr["is_dir"] else "a"
            )
        if not pickcode.startswith("f"):
            user_agent = request.headers.get("user-agent", "")
            try:
                return RedirectResponse(
                    url=await self.get_url(id, user_agent, refresh=refresh)
                )
            except IsADirectoryError:
                pass
        return await self.get_children(id, refresh=refresh)

    @staticmethod
    async def options():
        """
        处理 WebDAV OPTIONS 请求

        :return bytes: 空字节串
        """
        return b""
