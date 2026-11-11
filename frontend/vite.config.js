import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  publicDir: false,
  build: {
    outDir: '../nuclemu/static',
    emptyOutDir: false,
    modulePreload: false,
    rollupOptions: {
      external: ['/draw.js'],
      makeAbsoluteExternalsRelative: false,
      output: { entryFileNames: 'app.js' },
    },
  },
})
