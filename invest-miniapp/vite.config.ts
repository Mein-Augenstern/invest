import { defineConfig } from "vite";
import uni from "@dcloudio/vite-plugin-uni";

// H5 端开发代理：/api → invest direct 后端（同源转发避免跨域；联调 star 网关时改 8080）
export default defineConfig({
  plugins: [uni()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8792",
        changeOrigin: true,
      },
    },
  },
});
