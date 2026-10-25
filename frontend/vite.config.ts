import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';

const cert = process.env.VOICE_TLS_CERT;
const key = process.env.VOICE_TLS_KEY;
if (Boolean(cert) !== Boolean(key)) throw new Error('Set both VOICE_TLS_CERT and VOICE_TLS_KEY.');

const proxy = { '/api': process.env.API_PROXY ?? 'http://127.0.0.1:8000' };
const https = cert && key ? { https: { cert: readFileSync(cert), key: readFileSync(key) } } : {};

// `vite preview` serves the production build with the same API proxy as the dev server.
export default defineConfig({ plugins: [react()],
  server: { host: '0.0.0.0', port: 5173, strictPort: true, ...https, proxy },
  preview: { port: 4173, strictPort: true, ...https, proxy },
});
