<script setup lang="ts">
import { onLaunch } from "@dcloudio/uni-app";
import { silentWxLogin } from "./api/auth";
// 启动静默登录（gateway 模式：wx.login → star 网关换 JWT；失败不打扰，接口层 401 会再触发）
onLaunch(() => {
  silentWxLogin();
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
