/**
 * 周报 markdown 轻量解析：标题/段落/表格/列表 → 结构化块（够用即可，不做通用渲染器）。
 * 支持的块：h1/h2/h3、p、table（首行表头，|---| 行跳过）、li、quote（>）。
 */

export interface MdBlock {
  kind: 'h1' | 'h2' | 'h3' | 'p' | 'li' | 'quote' | 'table'
  text?: string
  rows?: string[][] // table：rows[0] 为表头
}

/** 去掉行内 **加粗** 与 `code` 标记 */
function inline(s: string): string {
  return s.replace(/\*\*(.+?)\*\*/g, '$1').replace(/`(.+?)`/g, '$1')
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => inline(c.trim()))
}

export function parseMarkdown(md: string): MdBlock[] {
  const blocks: MdBlock[] = []
  const lines = md.split('\n')
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const t = line.trim()
    if (!t) {
      i++
      continue
    }
    if (t.startsWith('|')) {
      // 表格块：连续 | 行；第二行若是 --- 分隔则跳过
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        const row = splitRow(lines[i])
        if (!row.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(row)
        i++
      }
      if (rows.length) blocks.push({ kind: 'table', rows })
      continue
    }
    if (t.startsWith('### ')) blocks.push({ kind: 'h3', text: inline(t.slice(4)) })
    else if (t.startsWith('## ')) blocks.push({ kind: 'h2', text: inline(t.slice(3)) })
    else if (t.startsWith('# ')) blocks.push({ kind: 'h1', text: inline(t.slice(2)) })
    else if (t.startsWith('> ')) blocks.push({ kind: 'quote', text: inline(t.slice(2)) })
    else if (t.startsWith('- ') || t.startsWith('* ')) blocks.push({ kind: 'li', text: inline(t.slice(2)) })
    else blocks.push({ kind: 'p', text: inline(t) })
    i++
  }
  return blocks
}
