// web/vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import svgr from 'vite-plugin-svgr'

export default defineConfig({
  plugins: [
    react(),
    svgr({
      svgrOptions: {
        svgoConfig: {
          plugins: [
            {
              name: 'prefixIds',
              params: {
                prefix: 'dori',
                delim: '-',
              },
            },
          ],
        },
      },
    }),
    {
      name: 'strip-roslib-cdn',
      transform(code, id) {
        if (id.includes('roslib') && code.includes('cdnjs.cloudflare.com')) {
          return code.replace(
            /var script\s*=[\s\S]*?cdnjs\.cloudflare\.com[\s\S]*?document\.head\.appendChild[\s\S]*?;/g,
            ''
          );
        }
      }
    }
  ],
})
