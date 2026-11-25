import { createApp } from 'vue';
import { createVuetify } from 'vuetify';
import * as components from 'vuetify/components';
import * as directives from 'vuetify/directives';
import 'vuetify/styles';
import { aliases, mdi } from 'vuetify/iconsets/mdi';
import App from './App.vue';
import './styles/apple-theme.css';

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
          primary: '#5bcffa',
          secondary: '#f5abb9',
          accent: '#ffb8c9',
          error: '#ff3b30',
          warning: '#ff9f0a',
          info: '#5bcffa',
          success: '#34c759',
          background: '#f6f9fc',
          surface: '#ffffff',
          'on-primary': '#05263b',
          'on-secondary': '#ffffff',
          'on-surface': '#0f172a',
          'on-background': '#0f172a',
        },
      },
    },
  },
});

const app = createApp(App);
app.use(vuetify);
app.mount('#app');
