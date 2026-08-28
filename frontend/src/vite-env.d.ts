/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** `mock` (implicit) rulează pe backend-ul simulat; `http` lovește API-ul real. */
  readonly VITE_API_MODE?: "mock" | "http";
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
