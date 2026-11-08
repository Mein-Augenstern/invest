# invest-web · PC 端（S10）

Vue3 + TypeScript + Element Plus + ECharts 的桌面投研台，13 屏对齐小程序功能。
Spec：[docs/sdd/S10-pc-web.md](../docs/sdd/S10-pc-web.md)

## 开发

```bash
pnpm install
pnpm dev          # :5175，/api 经 vite 代理 → http://47.92.235.34（默认）
# 本机联调：INVEST_DEV_API=http://127.0.0.1:8790 pnpm dev
```

登录 token 与 `scripts/secrets/app.env` 中 `INVEST_MP_TOKEN` 同值，仅存浏览器 localStorage。

## 质量门

```bash
pnpm typecheck    # vue-tsc --noEmit
pnpm test         # vitest（口径/渲染安全/请求层）
pnpm build        # typecheck + vite build
```

## 部署（Cloudflare Pages）

```bash
# 上线前把 public/_redirects 中 __DOMAIN__ 替换为真实域名
pnpm build
wrangler pages deploy dist --project-name=invest
```

- `_redirects`：`/api/*` 同 zone 200 代理到 `https://api.<domain>`（Cloudflare Tunnel → ECS），
  浏览器视角同源，后端保持无 CORS
- SPA history 路由：`/*` 回退 `index.html`
