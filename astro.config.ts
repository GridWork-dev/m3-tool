import react from '@astrojs/react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'astro/config'

export default defineConfig({
  site: process.env.SITE_URL ?? 'http://localhost:4321',
  integrations: [react()],
  vite: { plugins: [tailwindcss()] },
})
