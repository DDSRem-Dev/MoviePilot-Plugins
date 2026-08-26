from base64 import b64decode, b64encode, urlsafe_b64encode
from re import IGNORECASE, compile as re_compile
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import Request


EXTERNAL_PLAYERS: Dict[str, Dict[str, str]] = {
    "potplayer": {"name": "PotPlayer"},
    "vlc": {"name": "VLC"},
    "iina": {"name": "IINA"},
    "infuse": {"name": "Infuse"},
    "mpv": {"name": "MPV"},
    "nplayer": {"name": "nPlayer"},
    "omniplayer": {"name": "OmniPlayer"},
    "figplayer": {"name": "FigPlayer"},
    "senplayer": {"name": "SenPlayer"},
    "fileball": {"name": "Fileball"},
    "stellarplayer": {"name": "StellarPlayer"},
    "mxplayer": {"name": "MX Player"},
    "mxplayerpro": {"name": "MX Player Pro"},
    "ddplay": {"name": "弹弹Play"},
}

ALL_EXTERNAL_PLAYER_KEYS = list(EXTERNAL_PLAYERS.keys())

EXTERNAL_PLAYER_MARKER = "[EmbyReverseProxy] externalPlayer"
REDIRECT_PATH = "/redirect2external"
EMBY_AUTH_TOKEN_RE = re_compile(r'Token="([^"]+)"')


def extract_api_key(request: Request) -> Optional[str]:
    """
    从请求中提取 api_key（query、X-Emby-Token 头、或 MediaBrowser 认证头）

    :param request (Request): 当前请求

    :return str: API Key 或 None
    """
    api_key = request.query_params.get("api_key") or request.query_params.get(
        "X-Emby-Token"
    )
    if not api_key:
        api_key = request.headers.get("X-Emby-Token")
    if not api_key:
        for hdr in ("X-Emby-Authorization", "Authorization"):
            val = request.headers.get(hdr)
            if val:
                m = EMBY_AUTH_TOKEN_RE.search(val)
                if m:
                    api_key = m.group(1)
                    break
    return api_key


def decode_redirect_link(link: str) -> str:
    """
    解码 redirect2external 的 base64 链接参数

    :param link (str): 查询参数 link

    :return str: 解码后的原始目标链接
    """
    padding = "=" * (-len(link) % 4)
    return b64decode((link + padding).encode("ascii")).decode("utf-8")


def build_external_player_script(player_keys: List[str]) -> Optional[str]:
    """
    构建前端按钮注入脚本，前端直接使用 ExternalUrls 数据

    :param player_keys (List): 允许显示的播放器 key 列表

    :return str: 脚本文本，不启用时返回 None
    """
    if not player_keys:
        return None

    players_json = ",".join(
        f"{{key:'{k}',name:'{EXTERNAL_PLAYERS[k]['name']}'}}" for k in player_keys
    )
    return (
        "<script>\n// "
        + EXTERNAL_PLAYER_MARKER
        + "\n"
        + """(function(){
  var PLAYERS=["""
        + players_json
        + """];
  var ICON_BASE='https://emby-external-url.7o7o.cc/embyWebAddExternalUrl/icons';
  var ICON_MAP={
    potplayer:'icon-PotPlayer',vlc:'icon-VLC',iina:'icon-IINA',
    infuse:'icon-infuse',mpv:'icon-MPV',nplayer:'icon-NPlayer',
    omniplayer:'icon-OmniPlayer',figplayer:'icon-FigPlayer',
    senplayer:'icon-SenPlayer',fileball:'icon-Fileball',
    stellarplayer:'icon-StellarPlayer',mxplayer:'icon-MXPlayer',mxplayerpro:'icon-MXPlayer',
    ddplay:'icon-DDPlay'
  };
  function makeBtn(p,url,title){
    var btn=document.createElement('button');
    btn.type='button';
    btn.className='detailButton emby-button emby-button-backdropfilter raised-backdropfilter detailButton-primary';
    btn.title=title||('使用 '+p.name+' 播放');
    var content=document.createElement('div');
    content.className='detailButton-content';
    var icon=document.createElement('i');
    icon.className='md-icon detailButton-icon button-icon button-icon-left';
    var iconFile=ICON_MAP[p.key];
    if(iconFile){
      icon.textContent='\\u3000';
      icon.style.backgroundImage='url('+ICON_BASE+'/'+iconFile+'.webp)';
      icon.style.backgroundRepeat='no-repeat';
      icon.style.backgroundSize='100% 100%';
      icon.style.fontSize='1.4em';
    } else {
      icon.classList.add('material-icons');
      icon.textContent='open_in_new';
    }
    var span=document.createElement('span');
    span.className='button-text';
    span.textContent=p.name;
    content.appendChild(icon);
    content.appendChild(span);
    btn.appendChild(content);
    btn.addEventListener('click',function(){location.href=url;});
    return btn;
  }
  function getPlayerUrl(item,key){
    var arr=item&&item.ExternalUrls;
    if(!Array.isArray(arr)) return null;
    var prefix=key+':';
    for(var i=0;i<arr.length;i++){
      var it=arr[i];
      if(it&&typeof it.Name==='string'&&it.Name.indexOf(prefix)===0&&it.Url){
        return {url:it.Url,title:it.Name.substring(prefix.length)};
      }
    }
    return null;
  }
  function showFlag(){
    return !!document.querySelector("div[is='emby-scroller']:not(.hide) .mediaInfo:not(.hide)");
  }
  var _injecting=false;
  var _lastItemId=null;
  function createButtons(anchor,item){
    var wrapper=document.createElement('div');
    wrapper.id='ExternalPlayersBtns';
    wrapper.className='detailButtons flex align-items-flex-start flex-wrap-wrap detail-lineItem';
    PLAYERS.forEach(function(p){
      var v=getPlayerUrl(item,p.key);
      if(v&&v.url){
        wrapper.appendChild(makeBtn(p,v.url,v.title));
      }
    });
    if(wrapper.childElementCount>0){
      anchor.insertAdjacentElement('afterend',wrapper);
    }
  }
  function tryInject(){
    if(_injecting) return;
    var detailBtns=document.querySelector("div[is='emby-scroller']:not(.hide) .mainDetailButtons");
    if(!detailBtns||!showFlag()) return;
    var itemId=null;
    try{
      var hash=location.hash||'';
      var m=hash.match(/[?&]id=([^&]+)/i);
      if(m) itemId=m[1];
    }catch(e){}
    if(!itemId) return;
    var existing=document.getElementById('ExternalPlayersBtns');
    if(existing&&_lastItemId===itemId) return;
    if(existing) existing.remove();
    _injecting=true;
    _lastItemId=itemId;
    try{
      var userId=(ApiClient._currentUser&&ApiClient._currentUser.Id)||ApiClient.getCurrentUserId();
      ApiClient.getItem(userId,itemId).then(function(item){
        var old=document.getElementById('ExternalPlayersBtns');
        if(old) old.remove();
        if(item&&item.MediaSources&&item.MediaSources.length>0){
          var anchor=document.querySelector("div[is='emby-scroller']:not(.hide) .mainDetailButtons");
          if(anchor) createButtons(anchor,item);
        }
      }).catch(function(){}).then(function(){_injecting=false;});
    }catch(e){_injecting=false;}
  }
  function startObserver(){
    var ob=new MutationObserver(function(){
      if(showFlag()&&!document.getElementById('ExternalPlayersBtns')){
        tryInject();
      }
    });
    ob.observe(document.body,{childList:true,subtree:true});
  }
  if(document.body){startObserver();}
  else{document.addEventListener('DOMContentLoaded',startObserver);}
  document.addEventListener('viewshow',function(){
    _lastItemId=null;
    var old=document.getElementById('ExternalPlayersBtns');
    if(old) old.remove();
    setTimeout(tryInject,300);
  });
})();
</script>"""
    )


def build_stream_url_for_item(
    request: Request,
    emby_host: str,
    item_id: str,
    source: Dict[str, Any],
    api_key: str,
) -> str:
    """
    为媒体项构建流媒体直链 URL（指向代理自身，触发 302）

    :param request (Request): 当前请求（用于获取 Host）
    :param emby_host (str): Emby 服务器地址
    :param item_id (str): 媒体项 ID
    :param source (Dict): MediaSource 字典
    :param api_key (str): API Key

    :return str: 完整的流地址 URL
    """
    host_header = request.headers.get("host") or ""
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    base_url = f"{scheme}://{host_header}" if host_header else emby_host

    container = source.get("Container", "mp4")
    source_id = quote(source.get("Id", ""), safe="")
    media_type = str(source.get("Type", "")).lower()
    prefix = "audio" if media_type == "audio" else "videos"
    return (
        f"{base_url}/emby/{prefix}/{item_id}/stream.{container}"
        f"?Static=true&MediaSourceId={source_id}&api_key={api_key}"
    )


def inject_external_urls(
    data: Dict[str, Any],
    request: Request,
    emby_host: str,
    item_id: str,
    api_key: str,
    player_keys: List[str],
) -> bool:
    """
    向 Items 响应注入 ExternalUrls 外部播放器链接

    :param data (Dict): Items API 响应 JSON 字典（就地修改）
    :param request (Request): 当前请求
    :param emby_host (str): Emby 服务器地址
    :param item_id (str): 媒体项 ID
    :param api_key (str): API Key
    :param player_keys (List): 需要注入的播放器 key

    :return bool: 是否注入了链接
    """
    sources = data.get("MediaSources")
    if not isinstance(sources, list) or not sources:
        return False

    external_urls = data.get("ExternalUrls")
    if not isinstance(external_urls, list):
        external_urls = []
        data["ExternalUrls"] = external_urls

    user_data = data.get("UserData")
    position_ticks = 0
    if isinstance(user_data, dict):
        position_ticks = user_data.get("PlaybackPositionTicks", 0) or 0

    item_title = str(data.get("Name", ""))
    server_id = str(data.get("ServerId", ""))
    os_type = _get_os_type(request.headers.get("user-agent", ""))

    injected = False
    for source in sources:
        if not isinstance(source, dict):
            continue
        stream_url = build_stream_url_for_item(
            request, emby_host, item_id, source, api_key
        )
        sub_url = _get_sub_url(stream_url, source, api_key)
        display_title = _get_display_title(source)
        source_name = source.get("Name") or display_title or ""

        for key in player_keys:
            target_url = _build_player_target_url(
                key=key,
                stream_url=stream_url,
                sub_url=sub_url,
                title=item_title,
                source_name=source_name,
                position_ticks=position_ticks,
                os_type=os_type,
                item_id=item_id,
                server_id=server_id,
                request=request,
            )
            if not target_url:
                continue
            label = (
                f"{EXTERNAL_PLAYERS[key]['name']} - {source_name}"
                if source_name
                else EXTERNAL_PLAYERS[key]["name"]
            )
            # Name 前缀保留 key，供前端稳定匹配对应播放器链接
            external_urls.append({"Name": f"{key}:{label}", "Url": target_url})
            injected = True
    return injected


def _build_player_target_url(
    key: str,
    stream_url: str,
    sub_url: str,
    title: str,
    source_name: str,
    position_ticks: int,
    os_type: str,
    item_id: str,
    server_id: str,
    request: Request,
) -> Optional[str]:
    sec, ms, hhmmss = _position_parts(position_ticks)
    media_name = source_name or "default"

    if key == "potplayer":
        raw = (
            f"potplayer://{quote(stream_url, safe=':/?&=%')} "
            f"/sub={quote(sub_url, safe=':/?&=%')} "
            f'/seek={hhmmss} /title="{title}"'
        )
    elif key == "vlc":
        if os_type == "windows" or os_type == "macOS":
            raw = f"vlc://{quote(stream_url, safe=':/?&=%')}"
        elif os_type == "ios":
            raw = (
                "vlc-x-callback://x-callback-url/stream"
                f"?url={quote(stream_url, safe='')}&sub={quote(sub_url, safe='')}"
            )
        else:
            raw = (
                f"intent:{quote(stream_url, safe=':/?&=%')}#Intent;"
                "package=org.videolan.vlc;type=video/*;"
                f"S.subtitles_location={quote(sub_url, safe='')};"
                f"S.title={quote(title, safe='')};i.position={ms};end"
            )
    elif key == "iina":
        raw = f"iina://weblink?url={quote(stream_url, safe='')}&new_window=1"
    elif key == "infuse":
        raw = (
            "infuse://x-callback-url/play"
            f"?url={quote(stream_url, safe='')}&sub={quote(sub_url, safe='')}"
        )
    elif key == "mpv":
        if os_type in ("ios", "android"):
            raw = f"mpv-handler://{quote(stream_url, safe=':/?&=%')}"
        else:
            stream_b64 = (
                urlsafe_b64encode(stream_url.encode("utf-8"))
                .decode("ascii")
                .rstrip("=")
            )
            raw = f"mpv-handler://play/{stream_b64}"
            if sub_url:
                sub_b64 = (
                    urlsafe_b64encode(sub_url.encode("utf-8"))
                    .decode("ascii")
                    .rstrip("=")
                )
                raw = f"{raw}/?subfile={sub_b64}"
    elif key == "nplayer":
        if os_type == "macOS":
            raw = f"nplayer-mac://weblink?url={quote(stream_url, safe='')}&new_window=1"
        else:
            raw = f"nplayer-{quote(stream_url, safe=':/?&=%')}"
    elif key == "omniplayer":
        raw = f"omniplayer://weblink?url={quote(stream_url, safe='')}"
    elif key == "figplayer":
        raw = f"figplayer://weblink?url={quote(stream_url, safe='')}"
    elif key == "senplayer":
        raw = f"SenPlayer://x-callback-url/play?url={quote(stream_url, safe='')}"
    elif key == "fileball":
        raw = f"filebox://play?url={quote(stream_url, safe='')}"
    elif key == "stellarplayer":
        raw = f"stellar://play/{quote(stream_url, safe=':/?&=%')}"
    elif key == "mxplayer":
        raw = (
            f"intent:{quote(stream_url, safe=':/?&=%')}#Intent;"
            "package=com.mxtech.videoplayer.ad;"
            f"S.title={quote(title, safe='')};i.position={ms};end"
        )
    elif key == "mxplayerpro":
        raw = (
            f"intent:{quote(stream_url, safe=':/?&=%')}#Intent;"
            "package=com.mxtech.videoplayer.pro;"
            f"S.title={quote(title, safe='')};i.position={ms};end"
        )
    elif key == "ddplay":
        if os_type == "android":
            raw = (
                f"intent:{quote(stream_url, safe=':/?&=%')}#Intent;"
                "package=com.xyoye.dandanplay;type=video/*;end"
            )
        else:
            # ddplay 协议不稳定支持 seek 参数，优先对齐 externalUrl.js 的实现
            raw = f"ddplay:{quote(stream_url + f'|filePath={title}', safe='')}"
    else:
        return None

    _ = media_name, item_id, server_id
    return _wrap_redirect(request, raw)


def _position_parts(position_ticks: int) -> Tuple[int, int, str]:
    ms = int(position_ticks / 10_000) if position_ticks > 0 else 0
    sec = int(ms / 1000) if ms > 0 else 0
    h, remainder = divmod(sec, 3600)
    m, s = divmod(remainder, 60)
    return sec, ms, f"{h:02d}:{m:02d}:{s:02d}"


def _wrap_redirect(request: Request, raw_url: str) -> str:
    host_header = request.headers.get("host") or ""
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    server_addr = (
        f"{scheme}://{host_header}"
        if host_header
        else str(request.base_url).rstrip("/")
    )
    encoded = b64encode(raw_url.encode("utf-8")).decode("ascii")
    return f"{server_addr}{REDIRECT_PATH}?link={quote(encoded, safe='')}"


def _get_os_type(user_agent: str) -> str:
    ua = user_agent or ""
    if re_compile(r"compatible|Windows", IGNORECASE).search(ua):
        return "windows"
    if re_compile(r"Macintosh|MacIntel", IGNORECASE).search(ua):
        return "macOS"
    if re_compile(r"iphone|Ipad", IGNORECASE).search(ua):
        return "ios"
    if re_compile(r"android", IGNORECASE).search(ua):
        return "android"
    if re_compile(r"Ubuntu", IGNORECASE).search(ua):
        return "ubuntu"
    return "other"


def _get_display_title(source: Dict[str, Any]) -> str:
    streams = source.get("MediaStreams")
    if not isinstance(streams, list):
        return ""
    for s in streams:
        if isinstance(s, dict) and s.get("Type") == "Video":
            return str(s.get("DisplayTitle") or "")
    return ""


def _get_sub_url(stream_url: str, source: Dict[str, Any], api_key: str) -> str:
    streams = source.get("MediaStreams")
    if not isinstance(streams, list):
        return ""
    source_id = source.get("Id", "")
    base = stream_url.split("/stream.", 1)[0]

    preferred_idx: Optional[int] = None
    fallback_idx: Optional[int] = None
    for idx, stream in enumerate(streams):
        if not isinstance(stream, dict):
            continue
        if not stream.get("IsExternal"):
            continue
        if fallback_idx is None:
            fallback_idx = idx
        if str(stream.get("Language", "")).lower() in ("chi", "zh", "zho"):
            preferred_idx = idx
            break

    sub_idx = preferred_idx if preferred_idx is not None else fallback_idx
    if sub_idx is None:
        return ""
    codec = str((streams[sub_idx] or {}).get("Codec") or "srt")
    api_part = f"?api_key={quote(api_key or '', safe='')}" if api_key else ""
    return (
        f"{base}/{quote(str(source_id), safe='')}/Subtitles/{sub_idx}/Stream.{codec}"
        f"{api_part}"
    )
