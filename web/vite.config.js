import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 개발(serve)은 루트 '/', 배포 빌드(build)만 GitHub Pages 경로 '/stock-lab/'
// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? '/stock-lab/' : '/',
}))
