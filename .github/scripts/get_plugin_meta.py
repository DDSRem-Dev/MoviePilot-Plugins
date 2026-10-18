import json
import os
import subprocess
import sys
import ast
from typing import Dict, Optional, Tuple, List

from plugin_frontend import get_frontend_path


def _extract_version_from_file(
    file_path: str, var_name: str
) -> Tuple[Optional[str], Optional[str]]:
    """
    从指定的 py 文件中，提取特定名称的字符串或数字变量。
    """
    if not os.path.exists(file_path):
        return None, f"文件未找到: {file_path}"
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=file_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == var_name:
                        if isinstance(node.value, ast.Constant):
                            return str(node.value.value), None
                        # ast.Str 和 ast.Num 在旧版 Python 中使用
                        elif isinstance(node.value, (ast.Str, ast.Num)):
                            return str(node.value.s), None
        return None, f"在 {file_path} 中未找到 '{var_name}' 变量"
    except Exception as e:
        return None, f"解析文件 {file_path} 时出错: {e}"


def get_version_from_source(plugin_dir: str) -> Tuple[Optional[str], Optional[str]]:
    """
    从插件源码目录中获取版本号。
    优先检查 version.py 中的 'VERSION' 变量。
    如果不存在或未找到，则回退到检查 __init__.py 中的 'plugin_version' 变量。
    """
    # 优先尝试从 version.py 获取
    version_py_path = os.path.join(plugin_dir, "version.py")
    if os.path.exists(version_py_path):
        version, err = _extract_version_from_file(version_py_path, "VERSION")
        # 如果成功获取到版本，或者遇到了文件不存在以外的致命错误，则直接返回
        if version or (err and "文件未找到" not in err):
            log(f"[Info] 尝试从 {version_py_path} 获取版本...")
            return version, err

    # 如果 version.py 不存在或其中没有版本，则回退到 __init__.py
    init_py_path = os.path.join(plugin_dir, "__init__.py")
    log(f"[Info] 尝试从 {init_py_path} 获取版本...")
    return _extract_version_from_file(init_py_path, "plugin_version")


def build_plugin_metadata(
    plugin_id, version, source_dir, package_data, is_prerelease=False
) -> Dict:
    """
    根据输入信息，为插件创建标准的元数据字典。
    """
    plugin_info = package_data.get(plugin_id, {})
    lowercase_id = plugin_id.lower()
    history_key = "prerelease_history" if is_prerelease else "history"
    notes = plugin_info.get(history_key, {}).get(f"v{version}", "")
    return {
        "id": plugin_id,  # 插件 ID （package(.*).json 中的键）
        "version": version,  # 插件版本
        "name": plugin_info.get("name", ""),  # 插件名称
        "notes": notes,  # 使用 package(.*).json 中的更新历史
        "tag_name": f"{plugin_id}_v{version}",  # 发布的标签名
        "archive_base": f"{lowercase_id}_v{version}",  # 插件归档文件名的基础部分
        "backend_worker_path": f"{source_dir}",  # 打包时的工作目录
        "backend_path": f"{lowercase_id}",  # 插件的后端源码目录
        "frontend_path": get_frontend_path(source_dir, lowercase_id),
    }


def handle_workflow_dispatch() -> List[Dict]:
    """
    处理手动触发 (workflow_dispatch) 的逻辑。
    """
    plugins_to_release = []
    plugin_id = os.environ.get("INPUT_PLUGIN_ID").strip()
    source_dir = os.environ.get("INPUT_SOURCE_DIRECTORY").strip()
    is_prerelease = os.environ.get("INPUT_PRERELEASE", "false").lower() == "true"

    try:
        if not plugin_id or not source_dir:
            raise ValueError(
                "[必须提供插件 ID 和源码目录。请检查输入参数是否正确设置。"
            )
        suffix = source_dir.replace("plugins", "")
        package_file_name = f"package{suffix}.json"
        release_mode_text = "预发布" if is_prerelease else "正式版"
        log(
            f"[Info] 手动模式 ({release_mode_text})：正在处理来自 {package_file_name} 的插件 {plugin_id}"
        )

        if not os.path.exists(package_file_name):
            raise FileNotFoundError(
                f"文件 {package_file_name} 未找到。请检查路径是否正确。"
            )

        with open(package_file_name, "r", encoding="utf-8") as f:
            package_data = json.load(f)
        plugin_info = package_data.get(plugin_id)

        if not plugin_info:
            raise ValueError(
                f"插件 {plugin_id} 在 package(.*).json 文件中未找到。请检查插件 ID 是否正确。"
            )

        plugin_code_dir = f"{source_dir}/{plugin_id.lower()}"
        py_version, err = get_version_from_source(plugin_code_dir)

        if err:
            raise ValueError(err)

        log(f"[Info] 从源码 (version.py 或 __init__.py) 中获取的版本号为: {py_version}")

        if is_prerelease:
            prerelease_versions = plugin_info.get("prerelease_vers", [])
            if py_version in prerelease_versions:
                log(
                    f"[Info] ✅ 版本校验通过: {py_version} 存在于 prerelease_vers 列表中。"
                )
                plugins_to_release.append(
                    build_plugin_metadata(
                        plugin_id,
                        py_version,
                        source_dir,
                        package_data,
                        is_prerelease=True,
                    )
                )
            else:
                raise ValueError(
                    f"预发布版本号不匹配: {py_version} 不在 package.json 的 prerelease_vers 列表中 ({prerelease_versions})。"
                )
        else:
            json_version = plugin_info.get("version")
            if not plugin_info.get("release", False):
                raise ValueError(
                    f"插件 '{plugin_id}' 未被标记为可发布 (release: true)。"
                )
            if py_version == json_version:
                log(
                    f"[Info] ✅ 版本校验通过: 源码文件与 package.json 中的版本一致 ({py_version})。"
                )
                plugins_to_release.append(
                    build_plugin_metadata(
                        plugin_id,
                        py_version,
                        source_dir,
                        package_data,
                        is_prerelease=False,
                    )
                )
            else:
                raise ValueError(
                    f"正式版版本号不匹配: 源码中的版本 {py_version} 与 package.json 中的版本 {json_version} 不一致。"
                )

    except Exception as e:
        log(f"[Fatal] 处理手动触发时出错: {e}")

    return plugins_to_release


def handle_push() -> List[Dict]:
    """
    处理自动推送 (push) 触发的逻辑，支持正式版和预发布版。
    """
    plugins_to_release = []
    before_sha = os.environ.get("BEFORE_SHA")
    after_sha = os.environ.get("AFTER_SHA")

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", before_sha, after_sha],
            capture_output=True,
            text=True,
            check=True,
        )
        changed_files = result.stdout.strip().split("\n")
        log(f"[Info] 检测到以下文件变更:\n{result.stdout.strip()}")

        package_files = [
            f for f in changed_files if f.startswith("package") and f.endswith(".json")
        ]

        for package_file in package_files:
            log(f"[Info] 正在处理变更的 package 文件: {package_file}")

            try:
                old_content_raw = subprocess.check_output(
                    ["git", "show", f"{before_sha}:{package_file}"]
                )
                old_package_data = json.loads(old_content_raw)
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                old_package_data = {}

            with open(package_file, "r", encoding="utf-8") as f:
                new_package_data = json.load(f)

            suffix = package_file.replace("package", "").replace(".json", "")
            source_dir = f"plugins{suffix}"
            log(f"[Info] 推断出的源码目录: {source_dir}")

            all_plugin_ids = set(old_package_data.keys()) | set(new_package_data.keys())

            for plugin_id in all_plugin_ids:
                old_info = old_package_data.get(plugin_id, {})
                new_info = new_package_data.get(plugin_id, {})

                # 获取新旧版本信息
                old_version = old_info.get("version")
                new_version = new_info.get("version")
                is_releasable = new_info.get("release", False)

                old_prerelease_vers = set(old_info.get("prerelease_vers", []))
                new_prerelease_vers = set(new_info.get("prerelease_vers", []))

                plugin_code_dir = f"{source_dir}/{plugin_id.lower()}"

                # 优先处理正式版发布
                if old_version != new_version and new_version and is_releasable:
                    log(
                        f"[Info] 检测到正式版发布意图: {plugin_id} (版本: {old_version} -> {new_version})"
                    )

                    py_version, err = get_version_from_source(plugin_code_dir)

                    if err:
                        log(f"[Fatal] {err}")
                        continue

                    if new_version == py_version:
                        log(
                            f"[Info] ✅ 版本一致 ({new_version})。准备加入正式版发布矩阵。"
                        )
                        plugins_to_release.append(
                            build_plugin_metadata(
                                plugin_id,
                                new_version,
                                source_dir,
                                new_package_data,
                                is_prerelease=False,
                            )
                        )
                    else:
                        log(
                            f"[Fatal] 正式版版本号不匹配: {plugin_id}",
                            f"\n- package.json 中的版本: {new_version}",
                            f"\n- 源码文件中的版本:  {py_version}",
                        )
                        continue

                # 处理预发布版发布
                elif old_prerelease_vers != new_prerelease_vers:
                    added_vers = new_prerelease_vers - old_prerelease_vers
                    if not added_vers:
                        log(
                            f"[Debug] ⏩ 跳过插件: {plugin_id} (仅删除了预发布版本，无新增)"
                        )
                        continue

                    prerelease_version_to_check = list(added_vers)[0]
                    if len(added_vers) > 1:
                        log(
                            f"[Warn] 检测到多个新增的预发布版本 {added_vers}，将只处理第一个: {prerelease_version_to_check}"
                        )

                    log(
                        f"[Info] 检测到预发布版发布意图: {plugin_id} (新增版本: {prerelease_version_to_check})"
                    )

                    py_version, err = get_version_from_source(plugin_code_dir)

                    if err:
                        log(f"[Fatal] {err}")
                        continue

                    if prerelease_version_to_check == py_version:
                        log(
                            f"[Info] ✅ 版本一致 ({py_version})。准备加入预发布版发布矩阵。"
                        )
                        plugins_to_release.append(
                            build_plugin_metadata(
                                plugin_id,
                                py_version,
                                source_dir,
                                new_package_data,
                                is_prerelease=True,
                            )
                        )
                    else:
                        log(f"[Fatal] 预发布版版本号不匹配: {plugin_id}")
                        log(
                            f"- package.json 中新增的版本: {prerelease_version_to_check}"
                        )
                        log(f"- 源码文件中的版本:  {py_version}")
                        continue

                else:
                    log(f"[Debug] ⏩ 跳过插件: {plugin_id} (无版本变更)")

    except subprocess.CalledProcessError as e:
        log(f"[Fatal] 执行 git diff 时出错: {e}")
    except Exception as e:
        log(f"[Fatal] 处理推送事件时出错: {e}")

    return plugins_to_release


def log(*args, **kwargs):
    """
    将消息打印到 stderr
    """
    print(*args, file=sys.stderr, **kwargs)


if __name__ == "__main__":
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    final_plugins = []
    if event_name == "workflow_dispatch":
        final_plugins = handle_workflow_dispatch()
    elif event_name == "push":
        final_plugins = handle_push()
    else:
        log(f"[Error] 不支持的事件类型: {event_name}")
        sys.exit(1)

    print(json.dumps(final_plugins))
