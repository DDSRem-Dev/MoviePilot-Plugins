# MoviePilot-Plugins

> [!NOTE]
> MoviePilot 第三方插件仓库

Telegram 交流群: https://t.me/+1lcscM_EbqhkN2Rl

## 插件列表

#### 探索类插件

- [CCTV探索](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/cctvdiscover)：让探索支持CCTV的数据浏览。
- [咪咕视频探索](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/migudiscover)：让探索支持咪咕视频的数据浏览。
- [哔哩哔哩探索](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/bilibilidiscover)：让探索支持哔哩哔哩的数据浏览。
- [Bangumi每日放送探索](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/bangumidailydiscover)：让探索支持Bangumi每日放送的数据浏览。
- [芒果TV探索](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/mangguodiscover)：让探索支持芒果TV的数据浏览。
- [腾讯视频探索](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/tencentvideodiscover)：让探索支持腾讯视频的数据浏览。

#### 网盘类插件

- [115网盘储存](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/p115disk)：更快更强的115网盘储存模块。
- [115网盘STRM助手](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/docs/p115strmhelper)：115网盘STRM生成一条龙服务。
- [123云盘储存](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/p123disk)：使存储支持123云盘。
- [123云盘STRM助手](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/p123strmhelper)：123云盘STRM生成一条龙服务。
- [CloudDrive2储存](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/clouddrivedisk)：使存储支持 CloudDrive2，grpc 原生 API 操作。
- [Emby 302 反向代理](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/embyreverseproxy)：Emby 302 反向代理，自动代理 HTTP 链接，跳转最终地址，支持外部播放器调用。
- [MediaWarp](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/mediawarp)：EmbyServer/Jellyfin 中间件：优化播放 Strm 文件、自定义前端样式、自定义允许访问客户端、嵌入脚本。

#### 媒体管理类

- [神医媒体文件同步删除](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/samediasyncdel)：通过神医插件通知同步删除历史记录、源文件和下载任务。
- [ffprobe命名补充](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/ffprobenamingsupplement)：整理重命名时调用 `ffprobe`，补全命名模板中的 `videoFormat`、`videoCodec`、`audioCodec`、`fps`、`effect`，支持 STRM

#### 工具类

- [115订阅站点修复](https://github.com/DDSRem-Dev/MoviePilot-Plugins/tree/main/plugins.v2/p115subfixer)：修复115网盘订阅追更插件导致的订阅站点被篡改问题，并自动卸载该插件

---

## English Overview

> This is a third-party plugin repository for [MoviePilot](https://github.com/jxxghp/MoviePilot), a self-hosted media automation tool.
> All plugins are written in Python (some with Rust via PyO3) and are licensed under GPL-3.0.

### Plugin Categories

#### Discovery Plugins

| Plugin | Description |
|---|---|
| CCTV Discover | Browse CCTV content in the Discover tab |
| Migu Video Discover | Browse Migu Video content in the Discover tab |
| Bilibili Discover | Browse Bilibili content in the Discover tab |
| Bangumi Daily Discover | Browse Bangumi daily broadcast schedule |
| Mango TV Discover | Browse Mango TV content in the Discover tab |
| Tencent Video Discover | Browse Tencent Video content in the Discover tab |

#### Cloud Storage Plugins

| Plugin | Description |
|---|---|
| 115 Pan Storage | High-performance 115 cloud storage module |
| 115 Pan STRM Helper | End-to-end STRM file generation for 115 cloud |
| 123 Pan Storage | Cloud storage support for 123 Pan |
| 123 Pan STRM Helper | End-to-end STRM file generation for 123 Pan |
| CloudDrive2 Storage | CloudDrive2 storage via native gRPC API |
| Emby 302 Reverse Proxy | Reverse proxy for Emby with HTTP→final URL redirect and external player support |
| MediaWarp | Emby/Jellyfin middleware: optimize STRM playback, custom frontend styles, script injection |

#### Media Management Plugins

| Plugin | Description |
|---|---|
| SaMedia Sync Delete | Sync-delete history records, source files, and download tasks via SaMedia plugin notifications |
| ffprobe Naming Supplement | Calls `ffprobe` during rename to fill in `videoFormat`, `videoCodec`, `audioCodec`, `fps`, `effect` — supports STRM |

#### Utility Plugins

| Plugin | Description |
|---|---|
| 115 Subscription Fixer | Fixes subscription site tampering caused by the 115 pan subscription plugin and auto-uninstalls it |

### Contributing

- Issues and PRs are welcome from international contributors.
- Please use either Chinese or English in issues/discussions.
- For installation or usage questions, join the Telegram group: https://t.me/+1lcscM_EbqhkN2Rl

---

## 感谢

- [p115client](https://github.com/ChenyangGao/p115client)
- [p123client](https://github.com/ChenyangGao/p123client)
- [MediaWarp](https://github.com/Akimio521/MediaWarp)

<a href="https://github.com/DDSRem-Dev/MoviePilot-Plugins/graphs/contributors"><img src="https://contrib.rocks/image?repo=DDSRem-Dev/MoviePilot-Plugins"></a>

## 许可证

此仓库内所有项目根据 GNU General Public License v3.0 许可证进行许可，详见[`LICENSE`](LICENSE) 文件。
