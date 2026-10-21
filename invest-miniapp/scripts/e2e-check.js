/** invest-miniapp E2E v3：star 登录链路（wx-login mock）→ 元素文本断言 + 截图（vue3 下 page.data() 不可用） */
const automator = require('miniprogram-automator')
const fs = require('fs')

const SHOT_DIR = '/tmp/invest-miniapp-shots'
// 网关地址经环境变量注入（不写死内网 IP——本仓公开）：
//   E2E_GATEWAY=http://<你的局域网IP>:8080 node scripts/e2e-check.js
const GATEWAY = process.env.E2E_GATEWAY
if (!GATEWAY) {
  console.error('缺少 E2E_GATEWAY 环境变量（star 网关地址，如 http://192.168.x.x:8080）')
  process.exit(1)
}
fs.mkdirSync(SHOT_DIR, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function textOf(page, selector) {
  const el = await page.$(selector)
  if (!el) return null
  try {
    return await el.text()
  } catch {
    return null
  }
}

async function main() {
  const mp = await automator.connect({ wsEndpoint: 'ws://127.0.0.1:9421' })
  // star 网关模式：清旧令牌（同步 API，异步版 automator 调用不生效），登录交给静默 wx.login
  await mp.callWxMethod('setStorageSync', 'invest_auth_mode', 'gateway')
  await mp.callWxMethod('setStorageSync', 'invest_server', GATEWAY)
  await mp.callWxMethod('removeStorageSync', 'invest_token')
  const leftover = await mp.callWxMethod('getStorageSync', 'invest_token')
  if (leftover) throw new Error(`旧令牌清除失败: ${leftover}`)

  const results = []
  const check = (name, ok, extra = '') =>
    results.push(`${ok ? 'PASS' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`)

  // 总览：启动静默登录 → 401 自动重登 → 数据渲染（真实 star 登录链路）
  // 断言轮询：登录链路含 wx.login+wx-login 往返，数据可能晚于首屏到达
  await mp.reLaunch('/pages/overview/overview')
  let hero = null
  let pensionTitle = null
  for (let i = 0; i < 15; i++) {
    await sleep(1000)
    const page = await mp.currentPage()
    const heroEl = await page.$('.hero-num')
    hero = heroEl ? await heroEl.text() : null
    if (hero && /\d/.test(hero)) {
      const p = await page.$('.pension-row')
      pensionTitle = p ? await p.text() : null
      break
    }
  }
  check('总览总市值渲染（star登录链路）', !!hero && /\d/.test(hero), `hero=${hero}`)
  check('缴存进度卡渲染', !!pensionTitle, (pensionTitle || '').slice(0, 40))
  await mp.screenshot({ path: `${SHOT_DIR}/1-overview.png` })

  // 流水
  page = await mp.switchTab('/pages/trades/trades')
  await sleep(2000)
  page = await mp.currentPage()
  const tradeName = await textOf(page, '.trade-name')
  const tradeTag = await textOf(page, '.action-tag')
  check('流水列表渲染', !!tradeName, `首行=${tradeName} ${tradeTag}`)
  await mp.screenshot({ path: `${SHOT_DIR}/2-trades.png` })

  // 信号
  page = await mp.switchTab('/pages/signals/signals')
  await sleep(1500)
  page = await mp.currentPage()
  const note = await textOf(page, '.note')
  check('信号页渲染', !!note, note || '')
  await mp.screenshot({ path: `${SHOT_DIR}/3-signals.png` })

  // 设置（gateway 模式：登录状态应已由启动静默登录建立）
  page = await mp.switchTab('/pages/settings/settings')
  await sleep(1500)
  page = await mp.currentPage()
  const about = await textOf(page, '.about')
  check('设置页渲染', !!about, (about || '').slice(0, 20))
  const loginState = await textOf(page, '.login-state')
  check('star登录状态', !!loginState && loginState.includes('已登录'), `state=${loginState}`)
  await mp.screenshot({ path: `${SHOT_DIR}/4-settings.png` })

  // 录入弹层
  page = await mp.switchTab('/pages/trades/trades')
  await sleep(1200)
  page = await mp.currentPage()
  const addBtn = await page.$('.primary-btn')
  if (addBtn) {
    await addBtn.tap()
    await sleep(800)
    const sheetTitle = await textOf(page, '.sheet-title')
    check('录入表单打开', sheetTitle === '记一笔', `title=${sheetTitle}`)
    await mp.screenshot({ path: `${SHOT_DIR}/5-trade-form.png` })
  } else {
    check('录入表单打开', false, '未找到按钮')
  }

  // v0.3 标的详情页（真实持仓：养老金红利基金）
  page = await mp.navigateTo('/pages/instrument/instrument?id=csi_dividend_pension')
  await sleep(2500)
  page = await mp.currentPage()
  const detailTitle = await textOf(page, '.title')
  check('详情页标题', !!detailTitle && detailTitle.includes('红利'), `title=${detailTitle}`)
  const chart = await page.$('#navChart')
  check('净值曲线 canvas', !!chart)
  const evRow = await textOf(page, '.kv')
  check('交易事件渲染', !!evRow, (evRow || '').slice(0, 30))
  await mp.screenshot({ path: `${SHOT_DIR}/6-instrument-detail.png` })
  // v0.4 十字线：模拟 touch 曲线中部，断言读数文本出现
  if (chart) {
    try {
      await chart.touchstart({ touches: [{ x: 170, y: 100, identifier: 0 }] })
      await sleep(800)
      page = await mp.currentPage()
      const crossEl = await page.$('.cross-label')
      const crossText = crossEl ? await crossEl.text() : null
      check(
        '十字线读数',
        !!crossText && /\d{4}-\d{2}-\d{2}/.test(crossText),
        `label=${crossText}`,
      )
      await mp.screenshot({ path: `${SHOT_DIR}/6b-crosshair.png` })
      await chart.touchend({ touches: [], changedTouches: [] })
      await sleep(400)
    } catch (e) {
      results.push(`FAIL 十字线touch — ${e.message}`)
    }
  }
  await mp.navigateBack()
  await sleep(800)

  // v0.4 周报页：生成条 + 真实生成（非AI）
  page = await mp.navigateTo('/pages/report/report')
  await sleep(2000)
  page = await mp.currentPage()
  const genBtn = await page.$('.gen-btn')
  check('周报生成条渲染', !!genBtn)
  if (genBtn) {
    await genBtn.tap()
    results.push('INFO 已触发周报生成（非AI），轮询产物…')
    let generated = false
    for (let i = 0; i < 20; i++) {
      await sleep(1500)
      const fn = await textOf(page, '.file-name')
      if (fn && !/weekly-20261018\.md/.test(fn)) {
        generated = true
        break
      }
    }
    check('周报后台生成链路', generated, `fileName=${await textOf(page, '.file-name')}`)
  }
  await mp.screenshot({ path: `${SHOT_DIR}/7-report.png` })
  await mp.navigateBack()

  console.log(results.join('\n'))
  await mp.disconnect()
}

main().catch((e) => {
  console.error('E2E ERROR:', e.message)
  process.exit(1)
})
