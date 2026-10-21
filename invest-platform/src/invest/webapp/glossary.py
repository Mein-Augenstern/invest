"""概念笔记：data/glossary/*.md 每个文件一个概念，页面自动收录。

用法：往 data/glossary/ 里加 markdown 文件即可（首行 `# 概念名`），
也可随时让 Claude 把讲过的概念沉淀成文件。文件按文件名排序展示。
"""
from __future__ import annotations

from pathlib import Path


def load_glossary(data_dir: Path) -> list[dict]:
    import markdown

    gdir = Path(data_dir) / "glossary"
    entries: list[dict] = []
    if not gdir.exists():
        return entries
    for f in sorted(gdir.glob("*.md")):
        text = f.read_text(encoding="utf-8").strip()
        if not text:
            continue
        title = f.stem
        lines = text.splitlines()
        if lines and lines[0].startswith("# "):
            title = lines[0][2:].strip()
        html = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
        # 摘要 = 第一个非标题非引用段的纯文本前80字
        summary = ""
        for ln in lines[1:]:
            s = ln.strip().lstrip("> ").strip()
            if s and not s.startswith(("#", "|", "-", ">", "`")):
                summary = s[:80]
                break
        entries.append({"slug": f.stem, "title": title, "summary": summary, "html": html})
    return entries
