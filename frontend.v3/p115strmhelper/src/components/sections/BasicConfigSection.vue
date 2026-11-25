<template>
  <div class="p115-section-stack">
    <!-- Group 1: Global Switch & Notification -->
    <AppleSettingsGroup
      title="全局运行与消息通知"
      subtitle="插件总开关与通知播报风格"
      icon="mdi-power-settings"
    >
      <AppleSettingsRow
        title="启用插件"
        description="开启后激活 115 网盘 STRM 生成、监控与相关增强服务"
      >
        <template #badge>
          <span class="p115-badge" :class="config.enabled ? 'p115-badge--green' : 'p115-badge--neutral'">
            <span class="p115-badge-dot" />
            {{ config.enabled ? '运行中' : '已停用' }}
          </span>
        </template>
        <v-switch v-model="config.enabled" color="success" density="compact" hide-details inset />
      </AppleSettingsRow>

      <AppleSettingsRow
        title="发送通知"
        description="开启后通过 MoviePilot 消息渠道推送同步进度、整理与异常告警通知"
      >
        <v-switch v-model="config.notify" color="primary" density="compact" hide-details inset />
      </AppleSettingsRow>

      <AppleSettingsRow
        title="通知语言"
        description="自定义插件发送消息通知时的文案风格与地区用语"
        wide-control
      >
        <v-select
          v-model="config.language"
          :items="languageOptions"
          density="compact"
          variant="outlined"
          hide-details
        />
      </AppleSettingsRow>
    </AppleSettingsGroup>

    <!-- Group 2: STRM URL & Link Redirect Strategy -->
    <AppleSettingsGroup
      title="直链与 STRM 链接策略"
      subtitle="决定生成的 .strm 文件内部地址格式与 302 重定向协议"
      icon="mdi-link-variant"
    >
      <AppleSettingsRow
        title="直链获取模式"
        description="选择通过 115 Cookie 接口或官方 OpenAPI 获取视频播放直链"
        wide-control
      >
        <AppleSegmentedControl v-model="config.link_redirect_mode" :items="redirectModeItems" block />
      </AppleSettingsRow>

      <AppleSettingsRow
        title="STRM 文件 URL 格式"
        :description="
          config.strm_url_template_enabled
            ? '已启用自定义模板时优先使用模板，模板渲染失败时将使用此设置作为后备方案'
            : '选择 STRM 文件的默认 URL 参数格式（推荐 pickcode 或 pickcode + name）'
        "
        wide-control
      >
        <v-select
          v-model="config.strm_url_format"
          :items="urlFormatOptions"
          density="compact"
          variant="outlined"
          hide-details
        />
      </AppleSettingsRow>

      <AppleSettingsRow
        title="STRM 文件内链接地址"
        description="留空时无法生成 STRM。点击右侧按钮可一键填入当前浏览器访问的 MoviePilot 站点地址"
        vertical
      >
        <div class="p115-input-action-row">
          <v-text-field
            v-model="config.moviepilot_address"
            label="MoviePilot 访问地址"
            placeholder="例如：http://192.168.1.10:3000"
            density="compact"
            variant="outlined"
            hide-details
          >
            <template #prepend-inner>
              <v-icon size="16" color="primary" icon="mdi-web" />
            </template>
          </v-text-field>
          <button
            type="button"
            class="p115-btn p115-btn--tonal p115-btn--sm p115-action-btn-fixed"
            title="使用当前站点地址"
            @click="setMoviePilotAddressToCurrentOrigin"
          >
            <v-icon size="15" icon="mdi-auto-fix" />
            <span>填入当前站点</span>
          </button>
        </div>
      </AppleSettingsRow>
    </AppleSettingsGroup>

    <!-- Group 3: Account Credentials -->
    <AppleSettingsGroup
      title="账号凭证与扫码授权"
      subtitle="支持多端 App 扫码快速获取 Cookie 与阿里云盘 Token"
      icon="mdi-shield-key-outline"
    >
      <AppleSettingsRow
        title="115 Cookie"
        description="点击右侧按钮可切换显隐、一键复制或打开二维码扫码获取最新 Cookie"
        vertical
      >
        <template #badge>
          <span class="p115-badge" :class="config.cookies ? 'p115-badge--blue' : 'p115-badge--amber'">
            <span class="p115-badge-dot" />
            {{ config.cookies ? '已配置' : '待设置' }}
          </span>
        </template>
        <div class="p115-input-action-row">
          <v-text-field
            v-model="config.cookies"
            label="115 网盘 Cookie"
            placeholder="UID=...; CID=...; SEID=..."
            :type="isCookieVisible ? 'text' : 'password'"
            density="compact"
            variant="outlined"
            hide-details
          >
            <template #prepend-inner>
              <v-icon size="16" color="primary" icon="mdi-key-variant" />
            </template>
            <template #append-inner>
              <button
                type="button"
                class="p115-inline-icon-btn mr-1"
                :title="isCookieVisible ? '隐藏Cookie' : '显示Cookie'"
                :aria-label="isCookieVisible ? '隐藏Cookie' : '显示Cookie'"
                @click="isCookieVisible = !isCookieVisible"
              >
                <v-icon size="16" :icon="isCookieVisible ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" />
              </button>
              <button
                type="button"
                class="p115-inline-icon-btn"
                :disabled="!config.cookies"
                title="复制Cookie到剪贴板"
                aria-label="复制Cookie"
                @click="copyCookieToClipboard"
              >
                <v-icon size="15" icon="mdi-content-copy" />
              </button>
            </template>
          </v-text-field>
          <button
            type="button"
            class="p115-btn p115-btn--primary p115-btn--sm p115-action-btn-fixed"
            :title="config.cookies ? '更新/更换Cookie (重新扫码)' : '扫码获取Cookie'"
            @click="openQrCodeDialog"
          >
            <v-icon size="15" icon="mdi-qrcode-scan" />
            <span>{{ config.cookies ? '重新扫码' : '扫码登录' }}</span>
          </button>
        </div>
      </AppleSettingsRow>

      <AppleSettingsRow
        title="阿里云盘 Token (可选)"
        description="非必填，供阿里云盘分享链接秒传至 115 功能使用。支持切换显隐、复制或手机阿里云盘扫码获取"
        vertical
      >
        <template #badge>
          <span v-if="config.aliyundrive_token" class="p115-badge p115-badge--pink">
            <span class="p115-badge-dot" />
            已绑定
          </span>
        </template>
        <div class="p115-input-action-row">
          <v-text-field
            v-model="config.aliyundrive_token"
            label="阿里云盘 Refresh Token (可选)"
            placeholder="留空不影响 115 核心功能"
            :type="isAliTokenVisible ? 'text' : 'password'"
            density="compact"
            variant="outlined"
            hide-details
          >
            <template #prepend-inner>
              <v-icon size="16" color="secondary" icon="mdi-cloud-key-outline" />
            </template>
            <template #append-inner>
              <button
                type="button"
                class="p115-inline-icon-btn mr-1"
                :title="isAliTokenVisible ? '隐藏Token' : '显示Token'"
                :aria-label="isAliTokenVisible ? '隐藏Token' : '显示Token'"
                @click="isAliTokenVisible = !isAliTokenVisible"
              >
                <v-icon size="16" :icon="isAliTokenVisible ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" />
              </button>
              <button
                type="button"
                class="p115-inline-icon-btn"
                :disabled="!config.aliyundrive_token"
                title="复制Token到剪贴板"
                aria-label="复制Token"
                @click="copyAliTokenToClipboard"
              >
                <v-icon size="15" icon="mdi-content-copy" />
              </button>
            </template>
          </v-text-field>
          <button
            type="button"
            class="p115-btn p115-btn--pink p115-btn--sm p115-action-btn-fixed"
            :title="config.aliyundrive_token ? '更新/更换Token' : '扫码获取Token'"
            @click="openAliQrCodeDialog"
          >
            <v-icon size="15" icon="mdi-qrcode-scan" />
            <span>{{ config.aliyundrive_token ? '更换 Token' : '阿里扫码' }}</span>
          </button>
        </div>
      </AppleSettingsRow>
    </AppleSettingsGroup>

    <!-- Group 4: Media Extensions -->
    <AppleSettingsGroup
      title="媒体与附属文件扩展名"
      subtitle="控制识别生成 STRM 的视频格式与同步下载的字幕/元数据后缀"
      icon="mdi-file-video-outline"
    >
      <AppleSettingsRow
        title="可整理媒体文件扩展名"
        description="支持的媒体视频文件扩展名，多个请用英文逗号分隔"
        vertical
      >
        <v-text-field
          v-model="config.user_rmt_mediaext"
          label="媒体文件扩展名"
          placeholder="mp4,mkv,ts,iso,rmvb,avi,mov..."
          density="compact"
          variant="outlined"
          hide-details
          class="p115-mono"
        />
      </AppleSettingsRow>

      <AppleSettingsRow
        title="可下载媒体数据文件扩展名"
        description="随同步任务自动下载到本地的字幕、音轨或 NFO 等附属文件扩展名，多个用英文逗号分隔"
        vertical
      >
        <v-text-field
          v-model="config.user_download_mediaext"
          label="媒体数据文件扩展名"
          placeholder="srt,ssa,ass"
          density="compact"
          variant="outlined"
          hide-details
          class="p115-mono"
        />
      </AppleSettingsRow>
    </AppleSettingsGroup>
  </div>
</template>

<script setup>
import { inject } from 'vue';
import AppleSettingsGroup from '../ui/AppleSettingsGroup.vue';
import AppleSettingsRow from '../ui/AppleSettingsRow.vue';
import AppleSegmentedControl from '../ui/AppleSegmentedControl.vue';

const config = inject('config');
const isCookieVisible = inject('isCookieVisible');
const isAliTokenVisible = inject('isAliTokenVisible');
const openQrCodeDialog = inject('openQrCodeDialog');
const openAliQrCodeDialog = inject('openAliQrCodeDialog');
const copyCookieToClipboard = inject('copyCookieToClipboard');
const copyAliTokenToClipboard = inject('copyAliTokenToClipboard');
const setMoviePilotAddressToCurrentOrigin = inject('setMoviePilotAddressToCurrentOrigin');

const languageOptions = [
  { title: '简体中文', value: 'zh_CN' },
  { title: '繁中台湾', value: 'zh_TW' },
  { title: '繁中港澳', value: 'zh_HK' },
  { title: '柔情猫娘', value: 'zh_CN_catgirl' },
  { title: '粤韵风华', value: 'zh_yue' },
  { title: '咚咚搬砖', value: 'zh_CN_dong' },
];

const urlFormatOptions = [
  { title: 'pickcode', value: 'pickcode' },
  { title: 'pickcode + name', value: 'pickname' },
];

const redirectModeItems = [
  { label: 'Cookie', value: 'cookie', icon: 'mdi-cookie-outline' },
  { label: 'OpenAPI', value: 'open', icon: 'mdi-api' },
];
</script>

<style scoped>
.p115-section-stack {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
  max-width: 100%;
}

.p115-inline-icon-btn {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--p115-text-secondary);
  width: 26px;
  height: 26px;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.p115-inline-icon-btn:hover:not(:disabled) {
  background: var(--p115-bg-hover);
  color: var(--p115-text-primary);
}

.p115-inline-icon-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.p115-input-action-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 128px;
  align-items: center;
  gap: 10px;
  width: 100%;
}

.p115-action-btn-fixed {
  width: 100%;
}

@media (max-width: 520px) {
  .p115-input-action-row {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }
}
</style>
