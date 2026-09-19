from gzip import open as gzip_open
from os import remove as os_remove
from os.path import exists as path_exists, getsize as path_getsize
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from httpx import HTTPStatusError
from orjson import dumps, loads
from p115center import P115Center

from app.log import logger

from ....core.config import configer
from ....utils.sentry import sentry_manager


@sentry_manager.capture_all_class_exceptions
class ShareFilesDataCollector:
    """
    分享文件数据收集器
    """

    def __init__(self, data_iter: Iterable[Dict], temp_file: str):
        """
        初始化分享文件数据收集器

        :param data_iter (Iterable): 文件数据迭代器
        :param temp_file (str): 临时文件路径
        """
        self.data_iter = data_iter
        self.temp_file = temp_file
        self.count = 0
        self._file_handle = None
        self._write_buffer = bytearray()
        self._buffer_size = 64 * 1024

    def __iter__(self):
        """
        迭代器接口，在迭代时同时写入数据
        """
        self._file_handle = gzip_open(self.temp_file, "wb")
        try:
            for record in self.data_iter:
                line_data = dumps(record) + b"\n"
                self._write_buffer.extend(line_data)

                if len(self._write_buffer) >= self._buffer_size:
                    self._file_handle.write(self._write_buffer)
                    self._write_buffer.clear()

                self.count += 1
                if self.count % 1000 == 0:
                    logger.debug(
                        f"【分享STRM生成】数据上传已收集 {self.count} 条数据..."
                    )
                yield record

            if self._write_buffer:
                self._file_handle.write(self._write_buffer)
                self._write_buffer.clear()
        finally:
            if self._file_handle:
                self._file_handle.close()
                self._file_handle = None

    def get_file_info(self) -> Tuple[str, int]:
        """
        获取临时文件信息

        :return Tuple: (文件路径, 数据条数)
        """
        return self.temp_file, self.count


@sentry_manager.capture_all_class_exceptions
class ShareOOPServerHelper:
    """
    分享 OOF 服务助手
    """

    @staticmethod
    def get_client() -> P115Center:
        """
        获取 P115Center 客户端
        """
        return P115Center(
            license=configer.p115center_license,
            file_path=str(
                Path(__file__).resolve().parent.parent.parent.parent / "api.py"
            ),
        )

    @staticmethod
    def delete_share_files(batch_id: str) -> Dict[str, Any]:
        """
        删除分享文件数据

        :param batch_id (str): 分享码和提取码组成的 batch_id

        :return Dict: 删除结果响应数据
        """
        client = ShareOOPServerHelper.get_client()
        resp = client.delete_share_file_iter(
            batch_id,
            headers={"user-agent": configer.get_user_agent()},
        )
        return resp.model_dump()

    @staticmethod
    def download_share_files_data(
        share_code: str, receive_code: str, temp_file: str
    ) -> bool:
        """
        从服务器下载分享文件数据

        :param share_code (str): 分享码
        :param receive_code (str): 提取码
        :param temp_file (str): 临时文件保存路径

        :return bool: 下载成功返回 True，失败返回 False
        """
        batch_id = f"{share_code}{receive_code}"
        logger.info(f"【分享STRM生成】尝试下载数据，batch_id: {batch_id}")

        try:
            client = P115Center()
            client.download_share_file_iter(batch_id, temp_file)
            logger.info(
                f"【分享STRM生成】数据下载成功，batch_id: {batch_id}, 文件大小: {path_getsize(temp_file) / 1024 / 1024:.2f} MB"
            )
            return True
        except HTTPStatusError as e:
            code = e.response.status_code if e.response else 500
            if code == 404:
                logger.debug(f"【分享STRM生成】数据不存在，batch_id: {batch_id}")
            else:
                logger.debug(
                    f"【分享STRM生成】下载数据失败，batch_id: {batch_id}, 状态码: {code}"
                )
            return False
        except Exception as e:
            logger.debug(f"【分享STRM生成】下载数据失败，batch_id: {batch_id}: {e}")
            return False

    @staticmethod
    def read_share_files_data_from_file(temp_file: str) -> Iterable[Dict]:
        """
        从下载的 gzip 文件中读取数据并返回迭代器

        :param temp_file (str): 临时文件路径

        :return Iterable: 数据迭代器
        """
        with gzip_open(temp_file, "rb") as f:
            for line in f:
                if line.strip():
                    try:
                        yield loads(line)
                    except Exception as e:
                        logger.warn(f"【分享STRM生成】解析数据行失败: {e}")
                        continue

    @staticmethod
    def upload_file(
        share_code: str,
        receive_code: str,
        temp_file: str,
    ) -> Optional[Dict]:
        """
        上传文件到服务器

        :param share_code (str): 分享码
        :param receive_code (str): 提取码
        :param temp_file (str): 临时文件路径

        :return Dict: 上传结果响应数据，失败返回 None
        """
        batch_id = f"{share_code}{receive_code}"
        logger.info(f"【分享STRM生成】开始上传，batch_id: {batch_id}")

        try:
            client = ShareOOPServerHelper.get_client()
            resp = client.upload_share_file_iter(
                batch_id, temp_file, headers={"user-agent": configer.get_user_agent()}
            )
            logger.debug(f"【分享STRM生成】上传成功: {resp.model_dump()}")
            return resp.model_dump()
        except Exception as e:
            logger.warn(f"【分享STRM生成】上传异常: {e}")
            return None
        finally:
            if path_exists(temp_file):
                try:
                    os_remove(temp_file)
                    logger.debug(f"【分享STRM生成】已清理临时文件: {temp_file}")
                except (OSError, TypeError, ValueError):
                    pass

    @staticmethod
    def upload_share_files_data(
        share_code: str, receive_code: str, temp_file: str
    ) -> Optional[Dict]:
        """
        上传分享文件数据到服务器

        :param share_code (str): 分享码
        :param receive_code (str): 提取码
        :param temp_file (str): 临时文件路径

        :return Dict: 上传结果响应数据，失败返回 None
        """
        if not path_exists(temp_file) or path_getsize(temp_file) == 0:
            logger.warn("【分享STRM生成】临时文件不存在或为空，跳过上传")
            return None

        return ShareOOPServerHelper.upload_file(
            share_code=share_code,
            receive_code=receive_code,
            temp_file=temp_file,
        )
