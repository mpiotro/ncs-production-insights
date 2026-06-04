/// <reference types="vite/client" />

/**
 * Typed `import.meta.env` for the two public, non-sensitive 004 config knobs (004-R5).
 * Declared here so `config.ts` reads them under `strict` without `any` (no secrets — principle 7).
 */
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_API_SOURCE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
