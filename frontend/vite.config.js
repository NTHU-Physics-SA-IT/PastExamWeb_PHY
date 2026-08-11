import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import tailwindcss from '@tailwindcss/vite'
import Components from 'unplugin-vue-components/vite'
import { PrimeVueResolver } from '@primevue/auto-import-resolver'
import eslintPlugin from 'vite-plugin-eslint'
import viteCompression from 'vite-plugin-compression'

export default defineConfig(({ mode }) => {
  return {
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    // PrimeVue components are auto-imported after Vite's initial dependency scan. Keep the
    // Archive route's exact component set in the first optimizer generation so a cold lazy
    // route load cannot invalidate and reload the document during E2E interactions.
    optimizeDeps: {
      include: [
        'primevue/accordion',
        'primevue/accordioncontent',
        'primevue/accordionheader',
        'primevue/accordionpanel',
        'primevue/autocomplete',
        'primevue/badge',
        'primevue/button',
        'primevue/checkbox',
        'primevue/datepicker',
        'primevue/dialog',
        'primevue/divider',
        'primevue/drawer',
        'primevue/fileupload',
        'primevue/floatlabel',
        'primevue/inputtext',
        'primevue/menu',
        'primevue/menubar',
        'primevue/message',
        'primevue/panelmenu',
        'primevue/password',
        'primevue/progressspinner',
        'primevue/select',
        'primevue/step',
        'primevue/steplist',
        'primevue/steppanel',
        'primevue/steppanels',
        'primevue/stepper',
        'primevue/tab',
        'primevue/tablist',
        'primevue/tabpanel',
        'primevue/tabpanels',
        'primevue/tabs',
        'primevue/tag',
        'primevue/textarea',
        'primevue/toolbar',
      ],
    },
    server: {
      host: true,
      port: 80,
      strictPort: true,
      hmr: { port: 24678, clientPort: 24678 },
    },
    build: {
      cssCodeSplit: true,
      chunkSizeWarningLimit: 600,
      sourcemap: true,
      minify: 'esbuild',
      esbuildOptions: {
        drop: mode === 'production' ? ['debugger'] : [],
        pure: mode === 'production' ? ['console.log', 'console.debug'] : [],
      },
    },
    plugins: [
      vue(),
      mode === 'development' && vueDevTools({ launchEditor: 'zed' }),
      mode !== 'test' && eslintPlugin({ include: ['src/**/*.vue', 'src/**/*.js', 'src/**/*.ts'] }),
      tailwindcss(),
      Components({ resolvers: [PrimeVueResolver()] }),
      mode === 'production' &&
        viteCompression({
          algorithm: 'gzip',
          ext: '.gz',
          threshold: 10240,
          deleteOriginFile: false,
        }),
    ].filter(Boolean),
  }
})
