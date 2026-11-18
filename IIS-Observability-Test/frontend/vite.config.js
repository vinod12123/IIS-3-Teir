import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8008',
      '/lab-control': {
        target: 'http://127.0.0.1:8010',
        rewrite: (path) => path.replace(/^\/lab-control/, '/remote'),
      },
    },
  },
});
