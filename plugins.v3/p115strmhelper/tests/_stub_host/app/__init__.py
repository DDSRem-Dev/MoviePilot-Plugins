"""
MoviePilot V3 宿主桩（stub）。

用途：让 p115strmhelper 的单元测试在没有真实 MoviePilot 运行时的环境下可跑。
本包**不是**宿主的替代实现，只提供：

* 插件 import 期需要的模块与符号（存在且可调用）；
* 少量行为可预测的替身（枚举、pydantic 模型、logger），使断言稳定；
* 关键对象用 ``MagicMock``，避免测试因宿主内部行为漂移而假失败。

约定与真实 V3 保持一致：
* 路径采用 V3 canonical 名（``app.schemas.message.Message`` 等）；
* ``TransferChain`` 采用 ``app.chain.transfer`` 懒加载入口；
* ``app.runtime.settings.get_runtime_setting`` 提供运行时配置读取。
"""

__version__ = "3.0.0"
IS_STUB = True

# 安装自愈钩子：某些测试会用空壳 ModuleType("app") 顶替本包，导致同进程内
# 后续测试的 ``import app.xxx`` 失败。钩子会在解析 app.* 之前把包修复回来。
# 注意：这里**不能**手工赋值 ``__path__``——那会覆盖 import 系统设置的
# list 形态路径，使子模块无法按路径解析。
from . import _stub_selfheal as _selfheal  # noqa: E402

_selfheal.install_self_heal()
