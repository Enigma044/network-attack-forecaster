import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Dev: `npm run dev` proxies /api to the local FastAPI server on :8000.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { chunkSizeWarningLimit: 1000 },
  server: {
    host: 'localhost',
    proxy: { '/api': 'http://localhost:8000' }
  }
});
