import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const DJANGO_BACKEND = 'http://127.0.0.1:8001'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    port: 5000,
    proxy: {
      // All API routes → Django
      '/api': {
        target: DJANGO_BACKEND,
        changeOrigin: true,
        secure: false,
        cookieDomainRewrite: 'localhost',
      },
      // Google Auth routes → Django
      '/auth': {
        target: DJANGO_BACKEND,
        changeOrigin: true,
        secure: false,
        cookieDomainRewrite: 'localhost',
      },
      // MT5 trading routes → Django
      '/mt5': {
        target: DJANGO_BACKEND,
        changeOrigin: true,
        secure: false,
        cookieDomainRewrite: 'localhost',
      },
      // Admin API routes → Django
      '/admin/api': {
        target: DJANGO_BACKEND,
        changeOrigin: true,
        secure: false,
        cookieDomainRewrite: 'localhost',
      },
      // Django static files
      '/static': {
        target: DJANGO_BACKEND,
        changeOrigin: true,
        secure: false,
      },
    },
  },
})

