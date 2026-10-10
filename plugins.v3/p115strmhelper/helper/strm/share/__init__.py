"""
分享 STRM 生成模块

本模块提供基于分享链接的 STRM 文件生成功能，详细迭代模式支持数据服务器共享机制

数据收集与共享机制
------------------
本模块在运行分享同步功能时，会自动启用数据服务器共享机制。此机制的设计目的和运作方式如下：

1. 数据收集范围
   - 仅收集分享链接中的文件基本信息（文件名、路径、大小、ID 等）
   - 不收集任何个人隐私信息、文件内容或访问凭证
   - 数据以匿名化、加密压缩的方式存储和传输

2. 数据收集的合理性
   - 降低风控风险：通过共享已知安全的分享数据，帮助规避平台风控机制
   - 提升生成效率：复用已处理的数据，减少重复的 API 调用和网络请求
   - 优化用户体验：加快 STRM 文件生成速度，减少等待时间
   - 数据最小化原则：仅收集生成 STRM 文件所必需的最少数据

3. 数据使用方式
   - 数据仅用于 STRM 文件生成流程
   - 数据存储在加密的服务器环境中
   - 数据可通过分享码和提取码进行访问，确保数据关联性

用户同意原则
-----------
使用详细迭代模式的分享同步功能即表示您同意以下条款：

1. 默认同意原则
   - 启用分享同步功能即视为您已阅读、理解并同意本数据收集与共享机制
   - 您可以通过禁用分享同步功能来停止数据收集和共享

2. 数据控制权
   - 您拥有对分享数据的完全控制权
   - 您可以随时停止使用本功能，已上传的数据将根据服务器策略进行处理

3. 隐私保护承诺
   - 我们承诺仅收集生成 STRM 文件所必需的数据
   - 不会收集、存储或传输任何个人敏感信息
   - 数据以加密方式传输和存储

4. 免责声明
   - 数据共享为可选功能，但分享同步功能的完整体验需要此功能支持
   - 如您不同意数据共享机制，请勿使用分享同步功能

注意事项
--------
- 本功能需要网络连接以访问数据服务器
- 首次运行时会尝试从服务器获取数据，详细迭代模式在数据不存在时自动收集并上传
- 高速简略模式不会收集或上传迭代数据
- 数据上传仅在成功处理所有文件且无异常时执行
"""

from .audit_download_queue import share_audit_download_queue
from .cleaner import (
    share_strm_cleaner,
    share_strm_cleanup_summary_store,
    share_strm_missing_media_store,
    share_strm_pending_queue,
)
from .create import ShareStrmHelper, ShareInteractiveGenStrmQueue

__all__ = [
    "ShareInteractiveGenStrmQueue",
    "ShareStrmHelper",
    "share_audit_download_queue",
    "share_strm_cleaner",
    "share_strm_cleanup_summary_store",
    "share_strm_missing_media_store",
    "share_strm_pending_queue",
]
