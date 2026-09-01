import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
// `vitest/config` pentru secțiunea `test`; `loadEnv` vine din `vite`, pe care
// wrapperul nu îl reexportă.
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // `loadEnv`, nu `process.env`: fișierele `.env*` sunt citite de Vite *după* ce
  // configurația a fost evaluată, deci aici nu ar exista încă.
  const env = loadEnv(mode, import.meta.dirname, 'VITE_')

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, './src'),
      },
    },
    server: {
      proxy: {
        // Backend-ul răspunde pe alt port, dar browserul trebuie să vadă o singură
        // origine. Cookie-ul de sesiune este `SameSite=Lax`: de pe altă origine nu ar
        // fi trimis la cererile pe care le fac `<img>` sau `<object>` — adică exact
        // la previzualizarea documentului. Iar un token în URL este interzis (§27).
        '/api': {
          target: env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000',
          changeOrigin: false,
        },
      },
    },
    test: {
      // Logica pură rulează în node; testele de componente cer DOM prin
      // docblock-ul `// @vitest-environment jsdom` la începutul fișierului.
      environment: 'node',
      include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
      // Testele rulează **întotdeauna** pe backendul simulat, indiferent ce scrie în
      // `.env.local`. Altfel un developer care își pune `VITE_API_MODE=http` ca să
      // lucreze cu API-ul real ar vedea suita căzând din motive care nu au nimic
      // de-a face cu ce a schimbat.
      env: { VITE_API_MODE: 'mock' },
    },
  }
})
