<script setup lang="ts">
import { onLaunch } from "@dcloudio/uni-app";
import { silentWxLogin } from "./api/auth";
import { getMode, getToken } from "./api/config";
// 启动静默登录（gateway 模式：wx.login → star 网关换 JWT；失败不打扰，接口层 401 会再触发）
onLaunch(() => {
  silentWxLogin();
  // H5（浏览器无微信环境）：gateway 模式且无 token 时引导到账密登录页（S11 三端登录）
  // #ifdef H5
  if (getMode() === "gateway" && !getToken()) {
    uni.reLaunch({ url: "/pages/login/login" });
  }
  // #endif
});
</script>

<style>
/* 全局基础样式：企业内部平台风——白卡+细边框，无渐变无重阴影 */
page {
  background: #f5f6f7;
  font-size: 28rpx;
  color: #1d2129;
}
.card {
  background: #ffffff;
  border: 1rpx solid #e5e6eb;
  border-radius: 12rpx;
  margin: 20rpx 24rpx 0;
  padding: 24rpx;
}
.card-title {
  font-size: 26rpx;
  color: #86909c;
  margin-bottom: 16rpx;
}
.muted {
  color: #86909c;
}
.danger {
  color: #d54941;
}
.success {
  color: #2e9e5b;
}
</style>
