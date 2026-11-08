/** markdown-lite：周报渲染安全与结构（禁止 v-html，解析器输出纯文本块） */
import { describe, expect, it } from 'vitest'
import { parseMarkdown } from '@/utils/markdown-lite'

describe('parseMarkdown', () => {
  it('标题/段落/列表/引用分级', () => {
    const blocks = parseMarkdown('# 一级\n## 二级\n正文段落\n- 列表项\n> 引用')
    expect(blocks.map((b) => b.kind)).toEqual(['h1', 'h2', 'p', 'li', 'quote'])
  })

  it('表格：首行为表头，--- 分隔行被跳过', () => {
    const blocks = parseMarkdown('| 月份 | 盈亏 |\n|---|---|\n| 2026-10 | +100 |')
    expect(blocks).toHaveLength(1)
    expect(blocks[0].kind).toBe('table')
    expect(blocks[0].rows).toEqual([
      ['月份', '盈亏'],
      ['2026-10', '+100'],
    ])
  })

  it('行内标记剥离：**加粗** 与 `code` 只留文本（XSS 载体不残留标记）', () => {
    const blocks = parseMarkdown('**重点** 和 `x=1`')
    expect(blocks[0].text).toBe('重点 和 x=1')
  })

  it('HTML 标签原样保留为纯文本（渲染侧不会再被解析）', () => {
    const blocks = parseMarkdown('<script>alert(1)</script>')
    expect(blocks[0].kind).toBe('p')
    expect(blocks[0].text).toContain('<script>')
  })

  it('空输入 → 空数组', () => expect(parseMarkdown('')).toEqual([]))
})
