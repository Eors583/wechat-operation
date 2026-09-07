"""Generate a multi-page export fixture for visual and file-structure QA."""

import sys
from pathlib import Path

from app.article_export import export_article
from tests.test_article_export import HTML

target = Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
body = (
    HTML
    + (
        '<p style="font-size:16px;color:#123456;line-height:1.8">'
        + "这是完整文章的长段落，用于验证中文换行、分页和正文排版。" * 12
        + "</p>"
    )
    * 8
)
for format in ("md", "pdf", "docx"):
    result = export_article(body, "文章导出验证", format)
    (target / f"article-export.{format}").write_bytes(result)
    print(format, len(result))
