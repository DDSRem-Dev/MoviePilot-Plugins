from re import search
from typing import Any, Dict, Optional, Tuple

from clouddrive2_client.proto import clouddrive_pb2
from google.protobuf import empty_pb2
from grpc import RpcError, StatusCode

from app.sdk.logging import logger


def convert_bytes(size_in_bytes: float) -> str:
    """
    将字节转换为最合适的单位

    :param size_in_bytes (float): 字节数

    :return str: 转换后的字符串
    """
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_index = 0
    while size_in_bytes >= 1024 and unit_index < len(units) - 1:
        size_in_bytes /= 1024
        unit_index += 1
    return f"{size_in_bytes:.2f} {units[unit_index]}"


def convert_seconds(seconds: float) -> str:
    """
    将秒数转换为天时分秒格式

    :param seconds (float): 秒数

    :return str: 格式化后的时间字符串
    """
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days > 0:
        parts.append(f"{int(days)}天")
    if hours > 0:
        parts.append(f"{int(hours)}小时")
    if minutes > 0:
        parts.append(f"{int(minutes)}分钟")
    if seconds > 0 or not parts:
        parts.append(f"{seconds:.0f}秒")
    return "".join(parts)


def check_cookie(client, black_dir: str = "") -> Optional[str]:
    """
    检查云盘cookie是否过期

    通过遍历根目录下的挂载点，尝试列出每个云盘的内容
    如果列出失败或结果为空，则认为该云盘的cookie已过期

    :param client (CloudDriveClient): CloudDriveClient 实例
    :param black_dir (str): 黑名单目录，逗号分隔

    :return str: 错误信息，无错误返回 None
    """
    if not client:
        logger.error("CloudDrive2 客户端未初始化")
        return "CloudDrive2 客户端未初始化"

    black_list = [d.strip() for d in black_dir.split(",") if d.strip()]

    try:
        drives = client.get_sub_files("/", force_refresh=True)
    except Exception as e:
        logger.error("获取云盘列表失败: %s", e)
        return f"获取云盘列表失败: {e}"

    for drive in drives:
        name = getattr(drive, "name", "") or ""
        full_path = getattr(drive, "fullPathName", "") or ""
        is_dir = getattr(drive, "isDirectory", False)

        if not is_dir or not name:
            continue
        if name in black_list:
            continue

        try:
            sub_files = list(client.get_sub_files(full_path, force_refresh=True))
            if not sub_files:
                logger.warning("云盘 %s 为空", name)
                return f"云盘 {name} cookie过期"
        except Exception as e:
            logger.error("云盘 %s 检查失败: %s", name, e)
            err_str = str(e)
            if "429" in err_str:
                return f"云盘 {name} 访问频率过高，请稍后再试"
            return f"云盘 {name} cookie过期"

    return None


def check_upload_tasks(client, keyword: str = "") -> Optional[str]:
    """
    检查上传任务是否有异常

    :param client (CloudDriveClient): CloudDriveClient 实例
    :param keyword (str): 检测关键字正则表达式

    :return str: 异常任务错误信息，无异常返回 None
    """
    if not client:
        logger.error("CloudDrive2 客户端未初始化")
        return None

    try:
        resp = client.get_upload_file_list(get_all=True)
    except Exception as e:
        logger.error("获取上传任务列表失败: %s", e)
        return None

    upload_files = getattr(resp, "uploadFiles", None) or []
    if not upload_files:
        logger.info("没有发现上传任务")
        return None

    for task in upload_files:
        status = getattr(task, "status", "") or ""
        error_message = getattr(task, "errorMessage", "") or ""

        if status == "FatalError" and keyword and search(keyword, error_message):
            logger.info("发现异常上传任务: %s", error_message)
            return error_message

    return None


def get_cloud_space(client, black_dir: str = "") -> str:
    """
    获取云盘空间信息

    :param client (CloudDriveClient): CloudDriveClient 实例
    :param black_dir (str): 黑名单目录，逗号分隔

    :return str: 云盘空间信息字符串
    """
    if not client:
        return "\n"

    black_list = [d.strip() for d in black_dir.split(",") if d.strip()]
    space_info = "\n"

    try:
        drives = client.get_sub_files("/", force_refresh=True)
    except Exception as e:
        logger.error("获取云盘列表失败: %s", e)
        return "\n"

    for drive in drives:
        name = getattr(drive, "name", "") or ""
        full_path = getattr(drive, "fullPathName", "") or ""
        is_dir = getattr(drive, "isDirectory", False)

        if not is_dir or not name:
            continue
        if name in black_list:
            continue

        try:
            info = client.get_space_info(full_path)
            total = getattr(info, "totalSpace", 0) or 0
            used = getattr(info, "usedSpace", 0) or 0
            space_info += f"{name}：{convert_bytes(used)}/{convert_bytes(total)}\n"
        except Exception as e:
            logger.error("获取云盘 %s 空间信息失败: %s", name, e)

    return space_info


def get_cd2_system_info(client, black_dir: str = "") -> Dict[str, Any]:
    """
    获取CloudDrive2系统信息

    :param client (CloudDriveClient): CloudDriveClient 实例
    :param black_dir (str): 黑名单目录，逗号分隔

    :return Dict: 系统信息字典
    """
    result: Dict[str, Any] = {
        "cpuUsage": None,
        "memUsageKB": None,
        "uptime": None,
        "fhTableCount": None,
        "dirCacheCount": None,
        "tempFileCount": None,
        "upload_count": 0,
        "download_count": 0,
        "download_speed": "0KB/s",
        "upload_speed": "0KB/s",
        "cloud_space": "\n",
    }

    if not client:
        return result

    # 运行信息
    try:
        run_info = client.stub.GetRunningInfo(
            empty_pb2.Empty(),
            metadata=client._create_authorized_metadata(),
        )
        if run_info:
            result["cpuUsage"] = f"{getattr(run_info, 'cpuUsage', 0):.2f}%"
            mem_kb = getattr(run_info, "memUsageKB", 0) or 0
            result["memUsageKB"] = f"{mem_kb / 1024:.2f}MB"
            uptime = getattr(run_info, "uptime", 0) or 0
            result["uptime"] = convert_seconds(uptime)
            result["fhTableCount"] = getattr(run_info, "fhTableCount", 0) or 0
            result["dirCacheCount"] = getattr(run_info, "dirCacheCount", 0) or 0
            result["tempFileCount"] = getattr(run_info, "tempFileCount", 0) or 0
    except Exception as e:
        logger.error("获取CloudDrive2运行信息失败: %s", e)

    # 任务数量
    try:
        task_count = client.get_all_tasks_count()
        if task_count:
            result["upload_count"] = getattr(task_count, "uploadCount", 0) or 0
            result["download_count"] = getattr(task_count, "downloadCount", 0) or 0
    except Exception as e:
        logger.error("获取CloudDrive2任务数量失败: %s", e)

    # 下载速度
    try:
        download_resp = client.get_download_file_list()
        if download_resp:
            dl_speed = getattr(download_resp, "globalBytesPerSecond", 0) or 0
            if dl_speed:
                result["download_speed"] = f"{dl_speed / 1024 / 1024:.2f}MB/s"
            else:
                result["download_speed"] = "0KB/s"
    except Exception as e:
        logger.error("获取CloudDrive2下载速度失败: %s", e)

    # 上传速度
    try:
        upload_resp = client.get_upload_file_list(get_all=True)
        if upload_resp:
            ul_speed = getattr(upload_resp, "globalBytesPerSecond", 0) or 0
            if ul_speed:
                result["upload_speed"] = f"{ul_speed / 1024 / 1024:.2f}MB/s"
            else:
                result["upload_speed"] = "0KB/s"
    except Exception as e:
        logger.error("获取CloudDrive2上传速度失败: %s", e)

    # 云盘空间
    result["cloud_space"] = get_cloud_space(client, black_dir)

    return result


def restart_cd2(client) -> bool:
    """
    重启CloudDrive2服务

    :param client (CloudDriveClient): CloudDriveClient 实例

    :return bool: 成功返回 True，失败返回 False
    """
    if not client:
        logger.error("CloudDrive2 客户端未初始化")
        return False

    try:
        client.stub.RestartService(
            empty_pb2.Empty(),
            metadata=client._create_authorized_metadata(),
        )
        logger.info("CloudDrive2 重启命令已发送")
        return True
    except RpcError as e:
        if e.code() == StatusCode.UNAVAILABLE and "Socket closed" in str(e):
            logger.info("CloudDrive2 重启命令已发送（服务端已断开连接，正在重启中）")
            return True
        logger.error("CloudDrive2 重启失败: %s", e)
        return False
    except Exception as e:
        logger.error("CloudDrive2 重启失败: %s", e)
        return False


def add_offline_files(client, urls: str, to_folder: str) -> Tuple[bool, Optional[str]]:
    """
    添加离线下载任务

    :param client (CloudDriveClient): CloudDriveClient 实例
    :param urls (str): 下载链接，多个链接用换行分隔
    :param to_folder (str): 保存路径

    :return Tuple: (是否成功, 错误信息)
    """
    if not client:
        logger.error("CloudDrive2 客户端未初始化")
        return False, "CloudDrive2 客户端未初始化"

    try:
        request = clouddrive_pb2.AddOfflineFileRequest(
            urls=urls,
            toFolder=to_folder,
        )
        result = client.stub.AddOfflineFiles(
            request,
            metadata=client._create_authorized_metadata(),
        )
        if result and getattr(result, "success", False):
            logger.info("离线下载成功: %s -> %s", urls, to_folder)
            return True, None
        error_message = getattr(result, "errorMessage", "") or "未知错误"
        logger.error("离线下载失败: %s", error_message)
        return False, error_message
    except Exception as e:
        logger.error("离线下载异常: %s", e)
        return False, str(e)
