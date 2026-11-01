/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Gốc máy chủ API, không gồm `/api` (ví dụ http://localhost:8000). */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
