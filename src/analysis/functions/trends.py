"""
趋势分析函数
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple

import pandas as pd
from ...utils.logging import setup_logger
from ...utils.paths import bucket
from ...io.excel import read_csv

def analyze_trends_by_channel(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    分析各渠道趋势
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 趋势分析结果
    """
    if logger is None:
        logger = setup_logger("default", "default")
    
    logger.info("开始分析各渠道趋势")
    
    try:
        # 检查数据是否为空
        if df.empty:
            logger.warning("数据框为空，无法进行趋势分析")
            return {
                "dates": [],
                "values": [],
                "summary": {
                    "total_records": 0,
                    "message": "数据为空"
                }
            }
        
        # 检查必要的列是否存在
        required_columns = ['published_at', 'channel']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"缺少必要的列: {missing_columns}")
            return {
                "dates": [],
                "values": [],
                "summary": {
                    "total_records": len(df),
                    "error": f"缺少必要的列: {missing_columns}"
                }
            }
        
        # 确保时间字段是datetime类型
        df['published_at'] = pd.to_datetime(df['published_at'], errors='coerce')
        df = df.dropna(subset=['published_at'])
        
        if df.empty:
            logger.warning("时间字段处理后数据为空，无法进行趋势分析")
            return {
                "dates": [],
                "values": [],
                "summary": {
                    "total_records": 0,
                    "message": "时间字段处理后数据为空"
                }
            }
        
        # 按小时统计趋势
        df['hour'] = df['published_at'].dt.hour
        hourly_trends = {}
        
        for channel in df['channel'].unique():
            channel_df = df[df['channel'] == channel]
            hourly_counts = channel_df['hour'].value_counts().sort_index()
            hourly_trends[channel] = [{"name": f"{k:02d}:00", "value": int(v)} for k, v in hourly_counts.items()]
        
        # 按日期统计趋势
        df['date'] = df['published_at'].dt.date
        daily_trends = {}
        
        for channel in df['channel'].unique():
            channel_df = df[df['channel'] == channel]
            daily_counts = channel_df['date'].value_counts().sort_index()
            daily_trends[channel] = [{"name": str(k), "value": int(v)} for k, v in daily_counts.items()]
        
        # 转换为ECharts格式
        hourly_series = []
        daily_series = []
        
        for channel in df['channel'].unique():
            if channel in hourly_trends:
                hourly_series.append({
                    "name": channel,
                    "type": "line",
                    "data": hourly_trends[channel]
                })
            
            if channel in daily_trends:
                daily_series.append({
                    "name": channel,
                    "type": "line",
                    "data": daily_trends[channel]
                })
        
        # 计算趋势指标
        trend_indicators = {}
        for channel in df['channel'].unique():
            channel_df = df[df['channel'] == channel]
            if len(channel_df) > 1:
                # 计算增长率
                channel_df = channel_df.sort_values('published_at')
                first_half = channel_df.iloc[:len(channel_df)//2]
                second_half = channel_df.iloc[len(channel_df)//2:]
                
                first_count = len(first_half)
                second_count = len(second_half)
                
                if first_count > 0:
                    growth_rate = (second_count - first_count) / first_count
                else:
                    growth_rate = 0
                
                trend_indicators[channel] = {
                    "total_count": len(channel_df),
                    "growth_rate": round(growth_rate, 2),
                    "trend": "上升" if growth_rate > 0.1 else "下降" if growth_rate < -0.1 else "平稳"
                }
        
        result = {
            "hourly_trends": {
                "type": "line",
                "series": hourly_series,
                "title": "各渠道24小时趋势对比"
            },
            "daily_trends": {
                "type": "line",
                "series": daily_trends,
                "title": "各渠道日期趋势对比"
            },
            "trend_indicators": trend_indicators,
            "summary": {
                "total_channels": len(df['channel'].unique()),
                "total_records": len(df),
                "time_range": {
                    "start": df['published_at'].min().isoformat() if len(df) > 0 else None,
                    "end": df['published_at'].max().isoformat() if len(df) > 0 else None
                }
            }
        }
        
        logger.info(f"各渠道趋势分析完成，渠道数: {len(df['channel'].unique())}")
        return result
        
    except Exception as e:
        logger.error(f"各渠道趋势分析失败: {e}")
        return {
            "dates": [],
            "values": [],
            "summary": {
                "total_records": len(df) if 'df' in locals() else 0,
                "error": str(e)
            }
        }


def _compute_daily_counts(df: pd.DataFrame) -> Tuple[List[str], List[int]]:
    """
    按天统计数量，返回（日期字符串数组, 计数数组）
    
    Args:
        df (pd.DataFrame): 数据框
    
    Returns:
        Tuple[List[str], List[int]]: 日期字符串数组和计数数组
    """
    if 'published_at' not in df.columns:
        return [], []
    
    try:
        s = pd.to_datetime(df['published_at'], errors='coerce').dropna()
        if s.empty:
            return [], []
        dates = s.dt.date.value_counts().sort_index()
        x = [d.strftime('%Y-%m-%d') for d in dates.index]
        y = [int(v) for v in dates.values]
        return x, y
    except Exception as e:
        # 记录错误但不中断程序
        if 'logger' in globals():
            globals()['logger'].warning(f"计算日统计失败: {e}")
        return [], []


def _save_json(obj: Dict[str, Any], path: Path) -> None:
    """
    保存JSON文件
    
    Args:
        obj (Dict[str, Any]): 要保存的对象
        path (Path): 保存路径
    
    Returns:
        None
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        if 'logger' in globals():
            globals()['logger'].error(f"保存JSON文件失败 {path}: {e}")


def generate_trend_area_html(dates: List[str], values: List[int], title: str) -> str:
    """
    单序列大面积折线图 HTML（基于示例模板）
    
    Args:
        dates (List[str]): 日期列表
        values (List[int]): 数值列表
        title (str): 图表标题
    
    Returns:
        str: HTML内容
    """
    if not dates or not values:
        return f"<html><body><h1>{title}</h1><p>暂无数据</p></body></html>"
    
    option = {
        "tooltip": {"trigger": "axis", "position": ["50%", "10%"]},
        "title": {"left": "center", "text": title},
        "toolbox": {"feature": {"dataZoom": {"yAxisIndex": "none"}, "restore": {}, "saveAsImage": {}}},
        "xAxis": {"type": "category", "boundaryGap": False, "data": dates},
        "yAxis": {"type": "value", "boundaryGap": [0, '100%']},
        "dataZoom": [{"type": "inside", "start": 0, "end": 100}, {"start": 0, "end": 100}],
        "series": [{
            "name": title,
            "type": "line",
            "symbol": "none",
            "sampling": "lttb",
            "itemStyle": {"color": "rgb(255, 70, 131)"},
            "areaStyle": {"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                                       "colorStops": [{"offset": 0, "color": "rgb(255, 158, 68)"},
                                                       {"offset": 1, "color": "rgb(255, 70, 131)"}]}},
            "data": values
        }]
    }
    html = f"""
<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{title}</title>
  <script src=\"https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js\"></script>
  <style>
    html, body, #chart {{ height: 100%; margin: 0; }}
  </style>
  </head>
  <body>
    <div id=\"chart\"></div>
    <script>
      const option = {json.dumps(option, ensure_ascii=False)};
      const chart = echarts.init(document.getElementById('chart'));
      chart.setOption(option);
      window.addEventListener('resize', () => chart.resize());
    </script>
  </body>
</html>
"""
    return html


def generate_trend_multiline_html(dates: List[str], series_map: Dict[str, List[int]], title: str) -> str:
    """
    总体多折线面积图 HTML（各渠道叠加）
    
    Args:
        dates (List[str]): 日期列表
        series_map (Dict[str, List[int]]): 系列数据映射
        title (str): 图表标题
    
    Returns:
        str: HTML内容
    """
    if not dates or not series_map:
        return f"<html><body><h1>{title}</h1><p>暂无数据</p></body></html>"
    
    legend = list(series_map.keys())
    series = []
    for name, values in series_map.items():
        series.append({
            "name": name,
            "type": "line",
            "stack": "Total",
            "areaStyle": {},
            "emphasis": {"focus": "series"},
            "data": values
        })
    option = {
        "title": {"text": title},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross", "label": {"backgroundColor": "#6a7985"}}},
        "legend": {"data": legend},
        "toolbox": {"feature": {"saveAsImage": {}}},
        "xAxis": [{"type": "category", "boundaryGap": False, "data": dates}],
        "yAxis": [{"type": "value"}],
        "series": series
    }
    html = f"""
<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{title}</title>
  <script src=\"https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js\"></script>
  <style>
    html, body, #chart {{ height: 100%; margin: 0; }}
  </style>
  </head>
  <body>
    <div id=\"chart\"></div>
    <script>
      const option = {json.dumps(option, ensure_ascii=False)};
      const chart = echarts.init(document.getElementById('chart'));
      chart.setOption(option);
      window.addEventListener('resize', () => chart.resize());
    </script>
  </body>
</html>
"""
    return html


def run_trends(topic: str, date: str, logger=None) -> bool:
    """
    从仓库读取总体与渠道数据，统计按天发布量，输出 JSON 与 HTML
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, date)

    logger.info(f"开始运行趋势分析，专题: {topic}, 日期: {date}")

    warehouse_dir = bucket("warehouse", topic, date)
    if not warehouse_dir.exists():
        logger.error(f"未找到数据目录: {warehouse_dir}")
        return False

    # 检查目录中是否有CSV文件
    csv_files = list(warehouse_dir.glob('*.csv'))
    if not csv_files:
        logger.error(f"数据目录中没有CSV文件: {warehouse_dir}")
        return False

    logger.info(f"找到 {len(csv_files)} 个CSV文件")

    overall_path = warehouse_dir / '总体.csv'
    if not overall_path.exists():
        logger.warning(f"未找到总体数据文件: {overall_path}")
        # 如果没有总体文件，尝试使用第一个可用的CSV文件
        if csv_files:
            overall_path = csv_files[0]
            logger.info(f"使用 {overall_path.name} 作为总体数据")
        else:
            logger.error("没有可用的数据文件")
            return False

    # 读取总体
    try:
        df_overall = read_csv(overall_path)
        logger.info(f"成功读取总体数据，记录数: {len(df_overall)}")
    except Exception as e:
        logger.error(f"读取总体数据失败: {e}")
        return False

    # 统计总体
    overall_dates, overall_values = _compute_daily_counts(df_overall)
    logger.info(f"总体数据统计完成，日期数: {len(overall_dates)}")

    processed_root = bucket("processed", topic, date)
    overall_dir = processed_root / 'trends' / '总体'
    overall_dir.mkdir(parents=True, exist_ok=True)

    overall_json = {"dates": overall_dates, "values": overall_values}
    _save_json(overall_json, overall_dir / 'result.json')
    
    if overall_dates and overall_values:
        overall_html = generate_trend_area_html(overall_dates, overall_values, '总体发布趋势（按天）')
        with open(overall_dir / 'result.html', 'w', encoding='utf-8') as f:
            f.write(overall_html)
        logger.info("总体趋势HTML生成完成")
    else:
        logger.warning("总体数据为空，跳过HTML生成")

    # 各渠道
    channel_series: Dict[str, Tuple[List[str], List[int]]] = {}
    channel_count = 0
    
    for csv_path in csv_files:
        if csv_path.name == '总体.csv':
            continue
            
        channel = csv_path.stem
        try:
            df_ch = read_csv(csv_path)
            logger.info(f"读取渠道 {channel} 数据，记录数: {len(df_ch)}")
        except Exception as e:
            logger.warning(f"读取渠道 {channel} 失败: {e}")
            continue
            
        dates, values = _compute_daily_counts(df_ch)
        if dates and values:  # 只处理有数据的渠道
            channel_series[channel] = (dates, values)
            channel_count += 1

            ch_dir = processed_root / 'trends' / channel
            ch_dir.mkdir(parents=True, exist_ok=True)
            _save_json({"dates": dates, "values": values}, ch_dir / 'result.json')
            ch_html = generate_trend_area_html(dates, values, f'{channel} 发布趋势（按天）')
            with open(ch_dir / 'result.html', 'w', encoding='utf-8') as f:
                f.write(ch_html)
            logger.info(f"渠道 {channel} 趋势分析完成")
        else:
            logger.warning(f"渠道 {channel} 数据为空，跳过处理")

    logger.info(f"成功处理 {channel_count} 个渠道")

    # 生成总体多折线（各渠道）
    if channel_series:
        # 统一日期轴：取所有渠道日期并排序，缺失填0
        all_dates = sorted(set(d for ds, _ in channel_series.values() for d in ds))
        series_map: Dict[str, List[int]] = {}
        date_index = {d: i for i, d in enumerate(all_dates)}
        
        for ch, (ds, vs) in channel_series.items():
            arr = [0] * len(all_dates)
            for d, v in zip(ds, vs):
                idx = date_index.get(d)
                if idx is not None:
                    arr[idx] = v
            series_map[ch] = arr

        if series_map:
            multi_dir = processed_root / 'trends' / '总体'
            multi_html = generate_trend_multiline_html(all_dates, series_map, '各渠道发布趋势对比（按天）')
            with open(multi_dir / 'result_multi.html', 'w', encoding='utf-8') as f:
                f.write(multi_html)
            logger.info("多渠道趋势对比HTML生成完成")
    else:
        logger.warning("没有可用的渠道数据，跳过多折线图生成")

    logger.info("趋势分析完成：JSON 与 HTML 已生成")
    return True
