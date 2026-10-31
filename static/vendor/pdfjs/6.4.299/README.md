# Mozilla PDF.js 6.4.299

Pinned local browser assets from `pdfjs-dist@6.4.299` (Apache-2.0).
Source: https://github.com/mozilla/pdf.js/releases/tag/v6.4.299
Package: https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.4.299.tgz
Package SHA-256: `86269b40170eb41740ea05ad2102d71d33de4f122b34eb2f478be0ea7779c415`

Reproduce with `npm pack pdfjs-dist@6.4.299`, then copy `build/pdf.min.mjs`,
`build/pdf.worker.min.mjs`, `LICENSE`, `cmaps/`, `standard_fonts/`, and `wasm/`.
Third-party notices are preserved in those directories.

FABRO lazily imports the display module and starts its local worker only when a
PDF is opened. The controller renders one page at a time and does not initialize
PDF scripting or annotation actions. WASM is disabled to preserve FABRO's CSP;
the package's local JavaScript image-decoder fallbacks remain available.
