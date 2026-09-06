import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const vuePdfEntry = fileURLToPath(import.meta.resolve('@tato30/vue-pdf'))
const pdfJsEntry = createRequire(vuePdfEntry).resolve('pdfjs-dist')
const pdfJsRoot = resolve(dirname(pdfJsEntry), '..')

export const pdfJsLegacyAliases = [
  // Both main builds expose the same named API. The legacy build supplies
  // PDF.js's bundled compatibility support (including Iterator) for Safari.
  { find: /^pdfjs-dist$/, replacement: resolve(pdfJsRoot, 'legacy/build/pdf.mjs') },
  {
    find: /^pdfjs-dist\/legacy\/build\/pdf\.worker\.min\.mjs(\?url)?$/,
    replacement: `${resolve(pdfJsRoot, 'legacy/build/pdf.worker.min.mjs')}$1`,
  },
]
