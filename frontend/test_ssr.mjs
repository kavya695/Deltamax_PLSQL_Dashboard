// Test that each page component renders to a string without throwing.
// This catches: bad JSX, undefined refs, mismatched hooks, broken imports.
// It WON'T catch: data-shape bugs (because we're rendering with no data),
// but useApi returns {data:null, loading:true} initially, so we'll see the
// loading state for each — and that should also render cleanly.

import { renderToString } from 'react-dom/server'
import React from 'react'

// Stub fetch so useApi doesn't actually make HTTP calls in SSR
global.fetch = () => Promise.resolve({ ok: true, json: () => ({ ready: false, hint: 'test' }) })
global.window = { location: { hash: '' }, addEventListener: () => {}, removeEventListener: () => {} }
global.document = { getElementById: () => null }

const pages = [
  ['HomePage',       './src/pages/HomePage.jsx'],
  ['ExecPage',       './src/pages/ExecPage.jsx'],
  ['ForecastPage',   './src/pages/ForecastPage.jsx'],
  ['MdmPage',        './src/pages/MdmPage.jsx'],
  ['MigrationPage',  './src/pages/MigrationPage.jsx'],
  ['AnomaliesPage',  './src/pages/AnomaliesPage.jsx'],
]

let ok = 0, fail = 0
for (const [name, path] of pages) {
  try {
    const mod = await import(path)
    const Page = mod.default
    const html = renderToString(React.createElement(Page, { refreshKey: 0 }))
    console.log(`✓ ${name.padEnd(18)} rendered (${html.length} chars)`)
    ok++
  } catch (e) {
    console.log(`✗ ${name.padEnd(18)} ${e.message}`)
    fail++
  }
}
console.log(`\n${ok}/${pages.length} pages render cleanly`)
process.exit(fail === 0 ? 0 : 1)
