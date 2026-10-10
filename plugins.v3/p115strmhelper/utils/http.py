__all__ = [
    "check_response",
    "check_iter_path_data",
]

from typing import Dict

from httpx import HTTPStatusError, Response

from ..utils.exception import FileItemKeyMiss


def check_response(
    resp: Response,
) -> Response:
    """
    检查 HTTP 响应，如果状态码 ≥ 400 则抛出 httpx.HTTPStatusError

    :param resp (Response): HTTP 响应对象

    :return Response: 校验通过的 HTTP 响应对象

    :raises HTTPStatusError: 状态码 ≥ 400 时抛出
    """
    if resp.status_code >= 400:
        raise HTTPStatusError(
            f"HTTP Error {resp.status_code}: {resp.reason_phrase}",
            request=resp.request,
            response=resp,
        )
    return resp


def check_iter_path_data(item: Dict) -> Dict:
    """
    校验批量拉取信息是否完整

    :param item (Dict): 待校验的数据字典

    :return Dict: 校验通过的数据字典

    :raises FileItemKeyMiss: 信息不完整时抛出
    """
    if "path" not in item:
        raise FileItemKeyMiss(f"缺失 path 信息：{item}")
    if "is_dir" not in item:
        raise FileItemKeyMiss(f"缺失 is_dir 信息：{item}")
    if "sha1" not in item:
        raise FileItemKeyMiss(f"缺失 sha1 信息：{item}")
    if ("pickcode" not in item) and ("pick_code" not in item):
        raise FileItemKeyMiss(f"缺失 pickcode 信息：{item}")
    return item
