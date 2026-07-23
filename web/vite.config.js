import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages 배포 경로: https://2bfranklyes-eng.github.io/stock-lab/
// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: '/stock-lab/',
})
