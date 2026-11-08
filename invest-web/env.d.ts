/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** S10 过渡形态：跨域 API 基地址（trycloudflare 隧道），缺省同源 */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}
