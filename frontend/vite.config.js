import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import os from 'os'

// Auto-detect environment:
//   - On the GCP VM (hostname contains "deltamax-instance"): bind to 0.0.0.0
//     so the external IP can reach Vite, and proxy /api to local backend.
//   - Locally: bind to localhost only, proxy to local backend.
// BACKEND_URL env var overrides the proxy target if needed.
const isVM = os.hostname().includes('deltamax-instance')
const BACKEND = process.env.BACKEND_URL || 'http://localhost:8000'
const MDM_BACKEND = process.env.MDM_BACKEND_URL || 'http://localhost:8001'

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'stabilize-migration-bundle-hooks',
      transform(code, id) {
        const cleanId = id.split('?')[0].replaceAll('\\', '/')
        if (!cleanId.endsWith('/index-AffectedFilterFix.js')) return null
        const conditional = 'if(_cmActive)return a.jsx("div",{id:"dm-cm-mount",style:{minHeight:"100%",flex:"1"}});const{data:e,loading:r,error:n}=ct("/api/migration",t);'
        const stable = 'const{data:e,loading:r,error:n}=ct("/api/migration",t);if(_cmActive)return a.jsx("div",{id:"dm-cm-mount",style:{minHeight:"100%",flex:"1"}});'
        if (!code.includes(conditional)) return null
        return { code: code.replace(conditional, stable), map: null }
      },
    },
    {
      name: 'serve-built-assets-from-dist',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url?.startsWith('/assets/')) {
            req.url = `/dist${req.url}`
          }
          if (req.url?.startsWith('/reverse-ui.js') || req.url === '/' || req.url?.startsWith('/index.html')) {
            const setHeader = res.setHeader.bind(res)
            res.setHeader = (name, value) => {
              if (String(name).toLowerCase() === 'content-type') {
                if (String(value).startsWith('text/javascript')) value = 'text/javascript; charset=utf-8'
                if (String(value).startsWith('text/html')) value = 'text/html; charset=utf-8'
              }
              return setHeader(name, value)
            }
          }
          next()
        })
        return () => {
          server.middlewares.use((req, res, next) => {
            if (req.url?.startsWith('/reverse-ui.js')) {
              res.setHeader('Content-Type', 'text/javascript; charset=utf-8')
            }
            next()
          })
        }
      },
    },
  ],
  server: {
    host: isVM ? '0.0.0.0' : 'localhost',
    port: 5173,
    // Serve the SPA for /login (and any other path not starting with /api)
    historyApiFallback: true,
    proxy: {
      // Route MDM dashboard requests to its own Oracle-backed service.
      '/api/mdm': {
        target: MDM_BACKEND,
        changeOrigin: true,
      },
      '/api': {
        target: BACKEND,
        changeOrigin: true,
        // Required for Server-Sent Events — prevent Vite from buffering the stream
        ws: false,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('Connection', 'keep-alive')
          })
        },
      },
    },
  },
})
