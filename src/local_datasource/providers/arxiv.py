"""arXiv 学术论文搜索 provider。

通过 arxiv 官方库搜索论文，并将结果结构化输出为 CSV。
"""
from __future__ import annotations

from typing import Literal

import arxiv
import pandas as pd

from local_datasource.formatters import format_csv_output


SortBy = Literal["relevance", "submitted", "last_updated"]

# 排序方式字符串到 arxiv 枚举的映射
_SORT_MAP = {
    "relevance": arxiv.SortCriterion.Relevance,
    "submitted": arxiv.SortCriterion.SubmittedDate,
    "last_updated": arxiv.SortCriterion.LastUpdatedDate,
}


def query_arxiv(
    query: str,
    file_path: str,
    max_results: int = 10,
    sort_by: SortBy = "relevance",
) -> tuple[str, str]:
    """搜索 arXiv 论文并输出 CSV。

    参数:
        query: 检索关键词
        file_path: 输出 CSV 路径
        max_results: 最大返回条数
        sort_by: 排序方式
    """
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=_SORT_MAP.get(sort_by, arxiv.SortCriterion.Relevance),
    )

    rows = []
    for paper in client.results(search):
        rows.append({
            "title": paper.title,
            "authors": ", ".join(str(a) for a in paper.authors),
            "published": paper.published.isoformat() if paper.published else "",
            "updated": paper.updated.isoformat() if paper.updated else "",
            "summary": paper.summary[:500],
            "pdf_url": paper.pdf_url,
            "entry_id": paper.entry_id,
        })

    if not rows:
        raise ValueError(f"No arXiv papers found for query: {query}")

    df = pd.DataFrame(rows)
    return format_csv_output(df, file_path)
