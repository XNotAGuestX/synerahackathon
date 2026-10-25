import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';

const cert = process.env.VOICE_TLS_CERT;
const key = process.env.VOICE_TLS_KEY;
if (Boolean(cert) !== Boolean(key)) throw new Error('Set both VOICE_TLS_CERT and VOICE_TLS_KEY.');

export default defineConfig({ plugins: [react()], server: {
  host: '0.0.0.0', port: 5173, strictPort: true,
  ...(cert && key ? { https: { cert: readFileSync(cert), key: readFileSync(key) } } : {}),
  proxy: { '/api': process.env.API_PROXY ?? 'http://127.0.0.1:8000' },
} });
