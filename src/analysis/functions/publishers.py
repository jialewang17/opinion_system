"""
发布机构分析函数
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Tuple

import pandas as pd

from ...utils.logging import setup_logger
from ...utils.paths import bucket
from ...io.excel import read_csv

def analyze_publishers_by_channel(df: pd.DataFrame, logger=None, channel_name: str = None) -> Dict[str, Any]:
    """
    分析各渠道发布机构
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
        channel_name (str, optional): 渠道名称，单渠道模式时使用
    
    Returns:
        Dict[str, Any]: 发布机构分析结果
    """
    if logger is None:
        logger = setup_logger("default", "default")
    
    logger.info("开始分析发布机构")
    
    try:
        if 'author' not in df.columns:
            logger.error("数据缺少 author 列")
            return {}

        # 先计算总体发布机构统计（过滤 "未知"）
        _overall_clean = df['author'].dropna().astype(str).map(lambda x: x.strip())
        _overall_clean = _overall_clean[_overall_clean != "未知"]
        all_publisher_counts = _overall_clean.value_counts().to_dict()
        top_all_publishers = list(all_publisher_counts.items())[:30]
        all_publisher_data = [{"name": pub, "value": count} for pub, count in top_all_publishers[:20]]

        # 构造渠道发布机构统计
        channel_publishers: Dict[str, Any] = {}
        if 'channel' in df.columns:
            for channel in df['channel'].unique():
                channel_df = df[df['channel'] == channel]
                _ch = channel_df['author'].dropna().astype(str).map(lambda x: x.strip())
                _ch = _ch[_ch != "未知"]
                publisher_counts = _ch.value_counts().to_dict()
                top_publishers = list(publisher_counts.items())[:20]
                channel_publishers[channel] = {
                    "total_publishers": len(publisher_counts),
                    "top_publishers": [{"name": pub, "count": count} for pub, count in top_publishers],
                    "publisher_distribution": [{"name": pub, "value": count} for pub, count in top_publishers[:10]]
                }
        elif channel_name:
            # 单渠道模式：整张表代表一个渠道
            _ch = df['author'].dropna().astype(str).map(lambda x: x.strip())
            _ch = _ch[_ch != "未知"]
            publisher_counts = _ch.value_counts().to_dict()
            top_publishers = list(publisher_counts.items())[:20]
            channel_publishers[channel_name] = {
                "total_publishers": len(publisher_counts),
                "top_publishers": [{"name": pub, "count": count} for pub, count in top_publishers],
                "publisher_distribution": [{"name": pub, "value": count} for pub, count in top_publishers[:10]]
            }
        
        # 渠道发布机构对比
        series_data = []
        for channel, data in channel_publishers.items():
            if data["publisher_distribution"]:
                series_data.append({
                    "name": channel,
                    "type": "bar",
                    "data": data["publisher_distribution"]
                })
        
        # 计算发布机构活跃度指标
        publisher_activity = {}
        for channel, data in channel_publishers.items():
            try:
                channel_size = len(df[df['channel'] == channel]) if 'channel' in df.columns else len(df)
                avg_posts_per_publisher = (channel_size / data["total_publishers"]) if data["total_publishers"] else 0
            except Exception:
                avg_posts_per_publisher = 0
            publisher_activity[channel] = {
                "total_publishers": data.get("total_publishers", 0),
                "avg_posts_per_publisher": round(avg_posts_per_publisher, 2),
                "top_publisher": (data.get("top_publishers", []) or [{}])[0].get("name"),
                "top_publisher_count": (data.get("top_publishers", []) or [{}])[0].get("count", 0)
            }
        
        result = {
            "all_publishers": {
                "type": "bar",
                "data": all_publisher_data,
                "title": "总体发布机构排名"
            },
            "channel_publishers": {
                "type": "bar",
                "series": series_data,
                "title": "各渠道发布机构对比"
            },
            "publisher_activity": publisher_activity,
            "summary": {
                "total_channels": (len(df['channel'].unique()) if 'channel' in df.columns else (1 if channel_name else 0)),
                "total_publishers": len(all_publisher_counts),
                "total_records": len(df),
                "avg_publishers_per_channel": (
                    len(all_publisher_counts) / max(1, (len(df['channel'].unique()) if 'channel' in df.columns else (1 if channel_name else 0)))
                ),
                "most_active_publisher": top_all_publishers[0][0] if top_all_publishers else None,
                "most_active_publisher_count": top_all_publishers[0][1] if top_all_publishers else 0
            }
        }
        
        logger.info("发布机构分析完成")
        return result
        
    except Exception as e:
        logger.error(f"各渠道发布机构分析失败: {e}")
        return {}


def _compute_top10_from_series(series: pd.Series) -> List[Dict[str, Any]]:
    """
    将 value_counts 序列转换为 Top10 列表
    
    Args:
        series (pd.Series): 数据序列
    
    Returns:
        List[Dict[str, Any]]: Top10列表
    """
    cleaned = series.dropna().astype(str).map(lambda x: x.strip())
    cleaned = cleaned[cleaned != "未知"]
    counts = cleaned.value_counts()
    items: List[Tuple[Any, int]] = list(counts.items())[:10]
    top10 = [{"name": ("未识别" if (pd.isna(k) or k == "") else str(k)), "count": int(v)} for k, v in items]
    return top10


def _ensure_output_dir(topic: str, date: str, *parts: str) -> Path:
    """
    确保输出目录存在
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        *parts (str): 路径部分
    
    Returns:
        Path: 输出目录路径
    """
    root = bucket("processed", topic, date)
    out_dir = root / "publishers" / Path(*parts)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _save_json(obj: Dict[str, Any], path: Path) -> None:
    """
    保存JSON文件
    
    Args:
        obj (Dict[str, Any]): 要保存的对象
        path (Path): 保存路径
    
    Returns:
        None
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def _generate_echarts_html(overall_top10: List[Dict[str, Any]],
                           channel_top10_map: Dict[str, List[Dict[str, Any]]],
                           channel_total_map: Dict[str, int]) -> str:
    """
    生成基于 dataset + visualMap 的 ECharts HTML（去除水印/标题/定位元素）
    
    Args:
        overall_top10 (List[Dict[str, Any]]): 总体Top10数据
        channel_top10_map (Dict[str, List[Dict[str, Any]]]): 渠道Top10数据映射
        channel_total_map (Dict[str, int]): 渠道总数映射
    
    Returns:
        str: HTML内容
    """
    # 选择数据源：优先渠道，其次总体
    use = None
    if channel_top10_map:
        first_name = next(iter(channel_top10_map.keys()), None)
        if first_name:
            use = channel_top10_map.get(first_name, [])
    if not use or len(use) == 0:
        use = overall_top10

    counts = [int(item.get("count", 0)) for item in use]
    max_count = max(counts) if counts else 1

    # 构造 dataset 源数据
    rows = []
    rows.append(["score", "amount", "product"])  # 头部
    for item in use:
        amount = int(item.get("count", 0))
        # 归一化到 10~100
        score = 10 + (90 * (amount / max_count if max_count else 0))
        rows.append([round(score, 1), amount, str(item.get("name", "未识别"))])

    dataset_json = json.dumps({"source": rows}, ensure_ascii=False)

    html = f"""
<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>发布机构 Top10</title>
    <script src=\"https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js\"></script>
    <style>
      html, body, #app {{ height: 100%; margin: 0; }}
      #app {{ display: flex; flex-direction: column; }}
      #chart {{ flex: 1; min-height: 560px; }}
    </style>
  </head>
  <body>
    <div id=\"app\">
      <div id=\"chart\"></div>
    </div>
    <script>
    const option = {{
      dataset: {dataset_json},
      grid: {{ containLabel: true }},
      xAxis: {{ name: 'amount' }},
      yAxis: {{ type: 'category' }},
      visualMap: {{
        orient: 'horizontal',
        left: 'center',
        min: 10,
        max: 100,
        text: ['High Score', 'Low Score'],
        dimension: 0,
        inRange: {{ color: ['#65B581', '#FFCE34', '#FD665F'] }}
      }},
      series: [{{
        type: 'bar',
        encode: {{ x: 'amount', y: 'product' }}
      }}]
    }};
    const dom = document.getElementById('chart');
    const chart = echarts.init(dom);
    chart.setOption(option);
    window.addEventListener('resize', () => chart.resize());
    </script>
  </body>
</html>
"""
    return html


def run_publishers(topic: str, date: str, logger=None) -> bool:
    """
    从 data/warehouse 读取数据；按总体与各渠道统计 author Top10；
    输出 JSON 与 HTML 至 data/processed/{topic}/{date}/publishers/...
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, date)

    logger.info("开始执行发布机构分析（读取 warehouse 数据）")

    # 读取总体与各渠道 CSV（若存在）
    warehouse_dir = bucket("warehouse", topic, date)
    if not warehouse_dir.exists():
        logger.error(f"未找到数据目录: {warehouse_dir}")
        return False

    overall_path = warehouse_dir / "总体.csv"
    if not overall_path.exists():
        logger.error(f"未找到总体数据: {overall_path}")
        return False

    try:
        df_overall = read_csv(overall_path)
    except Exception as e:
        logger.error(f"读取总体数据失败: {e}")
        return False

    # 收集渠道 CSV；若后续存在 Excel，可扩展这里做兜底读取
    channel_files: Dict[str, Path] = {}
    for csv_path in warehouse_dir.glob("*.csv"):
        if csv_path.name == "总体.csv":
            continue
        channel_name = csv_path.stem
        channel_files[channel_name] = csv_path

    # 统计总体 Top10
    overall_top10 = _compute_top10_from_series(df_overall.get("author", pd.Series(dtype=str)))
    channel_totals: Dict[str, int] = {}
    channel_top10_map: Dict[str, List[Dict[str, Any]]] = {}

    # 各渠道
    for channel_name, path in channel_files.items():
        try:
            df_channel = read_csv(path)
        except Exception as e:
            logger.warning(f"读取渠道 {channel_name} 失败: {e}")
            continue
        channel_totals[channel_name] = int(len(df_channel))
        top10 = _compute_top10_from_series(df_channel.get("author", pd.Series(dtype=str)))
        channel_top10_map[channel_name] = top10

        # 保存渠道 JSON 与 HTML
        out_dir = _ensure_output_dir(topic, date, channel_name)
        result_obj = {
            "channel": channel_name,
            "top10": top10,
            "total_records": int(len(df_channel))
        }
        _save_json(result_obj, out_dir / "result.json")
        html = _generate_echarts_html(overall_top10, {channel_name: top10}, {channel_name: int(len(df_channel))})
        with open(out_dir / "result.html", "w", encoding="utf-8") as f:
            f.write(html)

    # 保存总体 JSON 与 HTML（包含渠道总量与一个示例渠道 Top10）
    overall_dir = _ensure_output_dir(topic, date, "总体")
    overall_obj = {
        "overall_top10": overall_top10,
        "channels": channel_top10_map,
        "channel_totals": channel_totals,
        "total_records": int(len(df_overall))
    }
    _save_json(overall_obj, overall_dir / "result.json")
    overall_html = _generate_echarts_html(overall_top10, channel_top10_map, channel_totals)
    with open(overall_dir / "result.html", "w", encoding="utf-8") as f:
        f.write(overall_html)

    logger.info("发布机构分析完成并已输出 JSON/HTML")
    return True


def generate_publishers_html_from_result(result: Dict[str, Any],
                                         title_overall: str = "发布机构 Top10",
                                         channel_totals: Dict[str, int] = None) -> str:
    """
    适配 runner.py 的结果结构，生成 ECharts HTML
    
    Args:
        result (Dict[str, Any]): 分析结果
        title_overall (str, optional): 总体标题，默认"发布机构 Top10"
        channel_totals (Dict[str, int], optional): 渠道总数映射，格式为 {channel: total_records}
    
    Returns:
        str: HTML内容
    """
    channel_totals = channel_totals or {}
    overall_items = (result or {}).get('all_publishers', {}).get('data', [])
    overall_top10 = [{"name": str(i.get("name")), "count": int(i.get("value", 0))} for i in overall_items]

    series = (result or {}).get('channel_publishers', {}).get('series', [])
    channel_top10_map: Dict[str, List[Dict[str, Any]]] = {}
    for s in series:
        ch_name = s.get('name')
        data = s.get('data', [])
        channel_top10_map[ch_name] = [{"name": str(i.get("name")), "count": int(i.get("value", 0))} for i in data]

    return _generate_echarts_html(overall_top10, channel_top10_map, channel_totals)
