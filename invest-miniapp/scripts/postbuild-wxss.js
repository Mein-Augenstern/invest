/**
 * 构建后处理：规范化 wxss——把压缩成单行的规则拆成多行，并刷新时间戳注释。
 * 背景：微信开发者工具 36.6.0 曾对超长单行 wxss 报「unexpected token Line N」
 * （实际是列位置被误报、且编译缓存与磁盘不一致）；多行规范格式可规避并便于 diff。
 */
const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '../dist/release/mp-weixin')

function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name)
    const st = fs.statSync(p)
    if (st.isDirectory()) walk(p, out)
    else if (name.endsWith('.wxss')) out.push(p)
  }
  return out
}

let changed = 0
for (const f of walk(ROOT)) {
  const src = fs.readFileSync(f, 'utf8')
  if (!src.trim()) continue
  // 规则间拆行（保守：仅在 } 后断行，不动字符串内容——wxss 无字符串场景）
  const pretty = src
    .replace(/}\s*/g, '}\n')
    .replace(/\n{2,}/g, '\n')
    .trimEnd() + '\n'
  if (pretty !== src) {
    fs.writeFileSync(f, pretty)
    changed++
  }
}
console.log(`[postbuild-wxss] 规范化 ${changed} 个 wxss 文件为多行格式`)

// 守卫：WXSS 解析器不支持 \XXXX unicode 转义。Vue 编译器会把中文类名（如 .贪婪）
// 转成 .\8d2a\5a6a——合法 CSS 但直接编译报错，且会静默炸掉 appLaunch（白屏 +
// getCurrentPages() 空 + automator page-meta null 三连锁，极难排查）。
// 源头见 src/pages/diary 的 MOOD_CLASS 映射；此处兜底拦截一切反斜杠。
const offenders = walk(ROOT).filter((f) => fs.readFileSync(f, 'utf8').includes('\\'))
if (offenders.length) {
  console.error(`[postbuild-wxss] 发现反斜杠（WXSS 不支持 \\XXXX 转义，多为中文类名/中文选择器导致）：`)
  for (const f of offenders) console.error('  - ' + path.relative(ROOT, f))
  console.error('修复：把中文类名改成 ASCII（绑定处用映射表），重建后重试。')
  process.exit(1)
}
console.log(`[postbuild-wxss] 反斜杠守卫通过`)
