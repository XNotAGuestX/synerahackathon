import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const proxy = { '/api': process.env.API_PROXY ?? 'http://127.0.0.1:8000' };

// `vite preview` serves the production build with the same API proxy as the dev server.
export default defineConfig({ plugins: [react()], server: { host: '0.0.0.0', port: 5173, strictPort: true, proxy }, preview: { port: 4173, strictPort: true, proxy } });
