import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import 'vuetify/styles'
import { aliases, mdi } from 'vuetify/iconsets/mdi'
import App from './App.vue'

// 创建Vuetify实例，配置蓝粉白主题
const vuetify = createVuetify({
  components,
  directives,
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: {
      mdi,
    },
  },
  theme: {
    defaultTheme: 'bluePinkWhite',
    themes: {
      bluePinkWhite: {
        dark: false,
        colors: {
          primary: '#5bcffa',      // 蓝色基准色
          secondary: '#f5abb9',     // 粉色基准色
          accent: '#ffb8c9',        // 粉色强调色（更亮的粉色）
          error: '#F44336',
          warning: '#FF9800',
          info: '#5bcffa',
          success: '#4CAF50',
          background: '#FAFAFA',    // 浅灰白背景
          surface: '#FFFFFF',       // 白色表面
          'on-primary': '#FFFFFF',
          'on-secondary': '#FFFFFF',
          'on-surface': '#212121',
          'on-background': '#212121',
        },
      },
    },
  },
})

// 创建Vue应用实例
const app = createApp(App)
app.use(vuetify)

app.mount('#app') 
