import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// Relative asset URLs are required when Electron loads the built app with file://.
export default defineConfig({ base: './', plugins: [react()] });
