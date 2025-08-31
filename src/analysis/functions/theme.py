from typing import List, Dict, Any, Optional, Tuple
import json
import math
import pandas as pd
import jieba
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer

from ...utils.logging import setup_logger
from pathlib import Path


def _load_stopwords() -> set:
    """
    加载停用词库
    
    Returns:
        set: 停用词集合，如果加载失败返回空集合
    """
    try:
        sw_path = Path(__file__).resolve().parents[3] / 'configs' / 'stopwords.txt'
        if sw_path.exists():
            return set(
                line.strip() for line in sw_path.read_text(encoding='utf-8').splitlines() if line.strip()
            )
    except Exception:
        pass
    return set()


def _tokenize_zh(text: str, stopwords: set) -> List[str]:
    """
    对中文文本进行分词处理
    
    Args:
        text (str): 待分词的文本
        stopwords (set): 停用词集合
    
    Returns:
        List[str]: 分词后的词汇列表，过滤掉停用词和短词
    """
    if not text:
        return []
    return [w.strip() for w in jieba.cut(text) if w and len(w.strip()) >= 2 and w.strip() not in stopwords]


def _pick_content_column(df: pd.DataFrame) -> Optional[str]:
    """
    从数据框中识别内容列
    
    Args:
        df (pd.DataFrame): 数据框
    
    Returns:
        Optional[str]: 内容列名，如果未找到返回None
    """
    candidates = ['contents', 'content', '正文', '全文', 'text', '文本', '内容']
    return next((c for c in candidates if c in df.columns), None)


def _decide_sample_size(n: int) -> int:
    """
    根据数据量决定采样大小
    
    Args:
        n (int): 原始数据量
    
    Returns:
        int: 采样大小
    """
    if n <= 1000:
        return n
    if n <= 2000:
        return math.ceil(n * 0.8)
    if n <= 5000:
        return math.ceil(n * 0.6)
    if n <= 10000:
        return math.ceil(n * 0.4)
    return 5000


def _prepare_corpus(df: pd.DataFrame) -> Tuple[List[str], int]:
    """
    准备文本语料库
    
    Args:
        df (pd.DataFrame): 数据框
    
    Returns:
        Tuple[List[str], int]: (文本列表, 采样大小)
    """
    col = _pick_content_column(df)
    if not col:
        return [], 0
    n = len(df)
    sample_size = _decide_sample_size(n)
    if sample_size < n:
        df_sampled = df.sample(sample_size, random_state=42)
    else:
        df_sampled = df
    texts = df_sampled[col].dropna().astype(str).tolist()
    return texts, sample_size


def _cluster_themes_lda(texts: List[str], logger=None,
                        max_k: int = 6,
                        min_k: int = 1,
                        examples_per_theme: int = 3) -> List[Dict[str, Any]]:
    """
    使用LDA主题建模，固定生成6个主题
    
    Args:
        texts (List[str]): 文本列表
        logger: 日志记录器
        max_k (int, optional): 最大主题数，默认6
        min_k (int, optional): 最小主题数，默认1
        examples_per_theme (int, optional): 每个主题的示例数，默认3
    
    Returns:
        List[Dict[str, Any]]: 主题列表，每个主题包含名称、关键词和分数
    """
    stopwords = _load_stopwords()
    docs_tokenized: List[str] = [" ".join(_tokenize_zh(t, stopwords)) for t in texts]
    non_empty_indices = [i for i, d in enumerate(docs_tokenized) if d.strip()]
    if not non_empty_indices:
        return []
    docs_tokenized = [docs_tokenized[i] for i in non_empty_indices]
    orig_texts = [texts[i] for i in non_empty_indices]

    # 用词频向量而不是 TF-IDF（LDA 基于计数模型）
    vectorizer = CountVectorizer(max_df=0.8, min_df=2, token_pattern=r"\S+", ngram_range=(1, 2))
    X = vectorizer.fit_transform(docs_tokenized)

    n_docs = X.shape[0]
    # 固定生成6个主题
    k = 6

    if logger:
        logger.info(f"LDA 主题建模：n_docs={n_docs}, k={k}")

    lda = LatentDirichletAllocation(
        n_components=k,
        random_state=42,
        learning_method="batch"
    )
    doc_topic = lda.fit_transform(X)

    terms = vectorizer.get_feature_names_out()
    results: List[Dict[str, Any]] = []

    for topic_idx, topic in enumerate(lda.components_):
        top_idx = topic.argsort()[:-9:-1]  # 取前8个词
        keywords = [{"word": terms[i], "weight": float(topic[i])} for i in top_idx]
        topic_score = float(doc_topic[:, topic_idx].sum())
        results.append({
            "name": f"主题{topic_idx+1}",
            "keywords": keywords,
            "score": topic_score
        })

    # 不按 size 排序，保持主题编号顺序
    return results


def analyze_theme_overall(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    分析总体主题分布
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 主题分析结果，包含主题列表和元数据
    """
    if logger is None:
        logger = setup_logger("default", "default")
    texts, sampled = _prepare_corpus(df)
    total = len(df)
    if not texts:
        return {"themes": [], "meta": {"total": total, "sampled": sampled, "error": "empty_corpus"}}
    themes = _cluster_themes_lda(texts, logger)   # ← 改为 LDA
    return {"themes": themes, "meta": {"total": total, "sampled": sampled}}


def generate_theme_bars_html(data: Dict[str, Any]) -> str:
    """
    生成主题关键词柱状图HTML
    
    Args:
        data (Dict[str, Any]): 主题数据
    
    Returns:
        str: HTML内容
    """
    themes = data.get("themes", [])
    if not themes:
        return "<p>无主题数据</p>"

    # 确保只处理6个主题
    if len(themes) > 6:
        themes = themes[:6]
    
    # 按 score 排序，确保主题质量
    def _theme_score(t: Dict[str, Any]) -> float:
        """
        计算主题分数
        
        Args:
            t (Dict[str, Any]): 主题数据
        
        Returns:
            float: 主题分数
        """
        if isinstance(t, dict) and 'score' in t and t.get('score') is not None:
            try:
                return float(t.get('score'))
            except Exception:
                return 0.0
        try:
            return float(sum(float(kw.get('weight', 0.0)) for kw in t.get('keywords', [])))
        except Exception:
            return 0.0

    # 按 score 排序，然后重命名为 主题1..6
    themes = sorted(themes, key=_theme_score, reverse=True)
    for idx, t in enumerate(themes, 1):
        t['name'] = f"主题{idx}"

    colors = [
        '#5470C6','#91CC75','#FAC858','#EE6666','#73C0DE',
        '#3BA272','#FC8452','#9A60B4','#EA7CCC','#2aa876',
        '#ff7f50','#87cefa','#da70d6','#32cd32','#6495ed'
    ]

    charts_js = []
    chart_divs = []

    for i, t in enumerate(themes):
        kw = t.get("keywords", [])
        names = [k.get("word") for k in kw]
        values = [round(k.get("weight", 0), 4) for k in kw]  # 使用原始权重，小数展示

        color = colors[i % len(colors)]
        display_name = f"主题{i+1}"
        chart_id = f"chart_{i}"
        chart_divs.append(f'<div id="{chart_id}" class="chart-block"></div>')

        option = {
            "backgroundColor": "#fff",
            "grid": {"left": 70, "right": 30, "top": 40, "bottom": 30},
            "title": {
                "text": display_name,
                "left": "center",
                "top": 6,
                "textStyle": {"fontSize": 13, "fontWeight": 600, "color": "#2f3b52"}
            },
            "tooltip": {
                "trigger": "item",
                "formatter": "{b}: {c}",
                "borderWidth": 0,
                "backgroundColor": "rgba(50,50,50,0.85)",
                "textStyle": {"color": "#fff", "fontSize": 11}
            },
            "xAxis": {
                "type": "value",
                "axisLine": {"show": False},
                "axisTick": {"show": False},
                "splitLine": {"show": True, "lineStyle": {"color": "#eee"}},
                "axisLabel": {"color": "#666", "fontSize": 11}
            },
            "yAxis": {
                "type": "category",
                "data": names[::-1],
                "axisLabel": {"color": "#333", "fontSize": 11},
                "axisLine": {"show": False},
                "axisTick": {"show": False}
            },
            "series": [{
                "name": display_name,
                "type": "bar",
                "data": values[::-1],
                "barMaxWidth": 16,
                "itemStyle": {
                    "color": {
                        "type": "linear",
                        "x": 0, "y": 0, "x2": 1, "y2": 0,
                        "colorStops": [
                            {"offset": 0, "color": color},
                            {"offset": 1, "color": "#eeeeee"}
                        ]
                    },
                    "borderRadius": [5, 5, 5, 5]
                },
                "label": {"show": False}
            }]
        }

        charts_js.append(
            f"echarts.init(document.getElementById('{chart_id}')).setOption({json.dumps(option, ensure_ascii=False)});"
        )

    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>主题关键词柱状图</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", Arial, sans-serif;
      background: #fafafa;
    }}
    .charts-container {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
      gap: 12px;
      padding: 12px;
    }}
    .chart-block {{
      height: 220px;
      background: #fff;
      border-radius: 8px;
      box-shadow: 0 1px 6px rgba(0,0,0,0.08);
      padding: 6px;
    }}
  </style>
</head>
<body>
  <div class="charts-container">
    {''.join(chart_divs)}
  </div>
  <script>
    {''.join(charts_js)}
    window.addEventListener('resize', () => {{
        document.querySelectorAll('.chart-block').forEach(div => {{
            echarts.getInstanceByDom(div).resize();
        }});
    }});
  </script>
</body>
</html>
"""
    return html
