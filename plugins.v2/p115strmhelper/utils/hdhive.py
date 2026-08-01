from typing import Any, Dict, List


def extract_hdhive_resource_rows(body: Any) -> List[Dict[str, Any]]:
    """
    从 HDHive JSON 响应中筛出带资源详情链接的条目

    :param body (Any): JSON 响应体

    :return List: 可供资源搜索消费的资源条目
    """
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if not isinstance(data, list):
        return []
    return [
        row
        for row in data
        if isinstance(row, dict)
        and "/resource/" in str(row.get("href") or "")
    ]
