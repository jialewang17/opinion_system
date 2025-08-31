"""
态度分析函数
"""
import pandas as pd
from typing import Dict, List, Any
from ...utils.logging import setup_logger

def _normalize_attitude_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    将数据框中的情感列标准化为 attitude 字段，兼容多种列名与取值
    
    Args:
        df (pd.DataFrame): 数据框
    
    Returns:
        pd.DataFrame: 标准化后的数据框
    """
    if 'attitude' in df.columns:
        return df
    df = df.copy()
    # 候选列名（按常见命名）
    candidate_cols = [
        'polarity', 'sentiment', '情感', '情绪', '情感倾向', 'att', 'label'
    ]
    col = next((c for c in candidate_cols if c in df.columns), None)
    if col is None:
        df['attitude'] = 'unknown'
        return df
    s = df[col]
    # 标准化值
    def to_att(v):
        """
        将情感值标准化为英文标签
        
        Args:
            v: 原始情感值
        
        Returns:
            str: 标准化的情感标签
        """
        if v is None:
            return 'unknown'
        try:
            # 数字映射
            f = float(v)
            if f > 0:
                return 'positive'
            if f < 0:
                return 'negative'
            return 'neutral'
        except Exception:
            pass
        x = str(v).strip().lower()
        mapping = {
            '正面': 'positive', '积极': 'positive', 'positive': 'positive', 'pos': 'positive', 'p': 'positive',
            '负面': 'negative', '消极': 'negative', 'negative': 'negative', 'neg': 'negative', 'n': 'negative',
            '中性': 'neutral', 'neutral': 'neutral', '客观': 'neutral', 'neu': 'neutral'
        }
        return mapping.get(x, 'unknown')
    df['attitude'] = s.map(to_att)
    return df

def generate_echarts_pie_html(title: str, data: Dict[str, int]) -> str:
    """
    使用 ECharts 生成环形饼图 HTML
    
    Args:
        title (str): 图表标题
        data (Dict[str, int]): 数据字典
    
    Returns:
        str: HTML内容
    """
    import json
    series_data = [{"value": int(v), "name": str(k)} for k, v in data.items()]
    option = {
        "tooltip": {"trigger": "item"},
        "legend": {"top": "5%", "left": "center"},
        "series": [
            {
                "name": title,
                "type": "pie",
                "radius": ["40%", "70%"],
                "avoidLabelOverlap": False,
                "padAngle": 5,
                "itemStyle": {"borderRadius": 10},
                "label": {"show": False, "position": "center"},
                "emphasis": {"label": {"show": True, "fontSize": 40, "fontWeight": "bold"}},
                "labelLine": {"show": False},
                "data": series_data,
            }
        ],
    }
    option_str = json.dumps(option, ensure_ascii=False)
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>{title}</title>
  <style>
    html, body {{ height: 100%; margin: 0; }}
    #chart {{ width: 800px; height: 520px; margin: 16px auto; }}
  </style>
  <script src=\"https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js\"></script>
</head>
<body>
  <div id=\"chart\"></div>
  <script>
    const chartDom = document.getElementById('chart');
    const myChart = echarts.init(chartDom);
    const option = {option_str};
    myChart.setOption(option);
  </script>
</body>
</html>
"""



def analyze_attitude_overall(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    分析总体态度分布
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 态度分析结果
    """
    if logger is None:
        logger = setup_logger("default", "default")
    
    logger.info("开始分析总体态度分布")
    
    try:
        # 标准化态度字段
        df = _normalize_attitude_column(df)

        # 统计态度分布
        attitude_counts = df['attitude'].value_counts().to_dict()

        # 转换为ECharts格式
        attitude_data = [{"name": k, "value": v} for k, v in attitude_counts.items()]

        result = {
            "total_count": len(df),
            "attitude_distribution": {
                "type": "pie",
                "data": attitude_data,
                "title": "态度分布"
            },
            "attitude_summary": {
                "positive_count": attitude_counts.get('positive', 0),
                "negative_count": attitude_counts.get('negative', 0),
                "neutral_count": attitude_counts.get('neutral', 0),
                "positive_ratio": attitude_counts.get('positive', 0) / len(df) if len(df) > 0 else 0,
                "negative_ratio": attitude_counts.get('negative', 0) / len(df) if len(df) > 0 else 0,
                "neutral_ratio": attitude_counts.get('neutral', 0) / len(df) if len(df) > 0 else 0
            }
        }

        # 可选：各渠道态度对比（仅当存在 channel 列时）
        if 'channel' in df.columns:
            series_data = []
            for attitude in ['positive', 'negative', 'neutral']:
                if attitude in df['attitude'].values:
                    data = []
                    for channel in df['channel'].dropna().unique():
                        count = len(df[(df['channel'] == channel) & (df['attitude'] == attitude)])
                        data.append({"name": channel, "value": int(count)})
                    series_data.append({
                        "name": attitude,
                        "type": "bar",
                        "data": data
                    })
            result["channel_attitude_comparison"] = {
                "type": "bar",
                "series": series_data,
                "title": "各渠道态度对比"
            }

        logger.info(f"总体态度分析完成，总记录数: {len(df)}")
        return result

    except Exception as e:
        logger.error(f"总体态度分析失败: {e}")
        # 返回尽量包含基础统计，避免完全空
        try:
            counts = df.get('attitude', pd.Series(dtype=str)).value_counts().to_dict() if isinstance(df, pd.DataFrame) else {}
        except Exception:
            counts = {}
        return {
            "total_count": int(len(df)) if isinstance(df, pd.DataFrame) else 0,
            "attitude_distribution": {"type": "pie", "data": [{"name": k, "value": v} for k, v in counts.items()], "title": "态度分布"}
        }

def analyze_attitude_by_channel(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    按渠道分析态度分布
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 态度分析结果
    """
    """
    分析单渠道态度分布
    """
    if logger is None:
        logger = setup_logger("default", "default")
    logger.info("开始分析渠道态度分布")
    try:
        df = _normalize_attitude_column(df)
        attitude_counts = df['attitude'].value_counts().to_dict()
        attitude_data = [{"name": k, "value": v} for k, v in attitude_counts.items()]
        result = {
            "total_count": len(df),
            "attitude_distribution": {
                "type": "pie",
                "data": attitude_data,
                "title": "态度分布"
            },
            "attitude_summary": {
                "positive_count": attitude_counts.get('positive', 0),
                "negative_count": attitude_counts.get('negative', 0),
                "neutral_count": attitude_counts.get('neutral', 0),
                "positive_ratio": attitude_counts.get('positive', 0) / len(df) if len(df) > 0 else 0,
                "negative_ratio": attitude_counts.get('negative', 0) / len(df) if len(df) > 0 else 0,
                "neutral_ratio": attitude_counts.get('neutral', 0) / len(df) if len(df) > 0 else 0
            }
        }
        logger.info(f"渠道态度分析完成，总记录数: {len(df)}")
        return result
    except Exception as e:
        logger.error(f"渠道态度分析失败: {e}")
        return {}


