"""
声量分析函数
"""
import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any
from ...utils.logging import setup_logger
from ...utils.paths import bucket
from ...io.excel import read_csv

def analyze_volume_overall(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    分析总体声量分布
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 声量分析结果，包含总记录数和渠道分布
    """
    if logger is None:
        logger = setup_logger("default", "default")
    
    logger.info("开始分析总体声量")
    
    try:
        # 按渠道统计声量
        channel_counts = df['channel'].value_counts().to_dict()
        
        # 转换为饼图数据格式
        channel_data = [{"name": k, "value": v} for k, v in channel_counts.items()]
        
        result = {
            "total_count": len(df),
            "channel_distribution": {
                "type": "pie",
                "data": channel_data,
                "title": "渠道声量分布"
            }
        }
        
        logger.info(f"总体声量分析完成，总记录数: {len(df)}")
        return result
        
    except Exception as e:
        logger.error(f"总体声量分析失败: {e}")
        return {}

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
        pass

def generate_volume_pie_html(channel_data: List[Dict[str, Any]], title: str) -> str:
    """
    生成声量分布饼图HTML
    
    Args:
        channel_data (List[Dict[str, Any]]): 渠道数据列表
        title (str): 图表标题
    
    Returns:
        str: HTML内容
    """
    if not channel_data:
        return f"<html><body><h1>{title}</h1><p>暂无数据</p></body></html>"
    
    # 使用你提供的饼图配置
    option = {
        "tooltip": {
            "trigger": "item"
        },
        "legend": {
            "top": "5%",
            "left": "center"
        },
        "series": [
            {
                "name": "渠道声量分布",
                "type": "pie",
                "radius": ["40%", "70%"],
                "avoidLabelOverlap": False,
                "itemStyle": {
                    "borderRadius": 10,
                    "borderColor": "#fff",
                    "borderWidth": 2
                },
                "label": {
                    "show": False,
                    "position": "center"
                },
                "emphasis": {
                    "label": {
                        "show": True,
                        "fontSize": 40,
                        "fontWeight": "bold"
                    }
                },
                "labelLine": {
                    "show": False
                },
                "data": channel_data
            }
        ]
    }
    
    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    html, body, #chart {{ height: 100%; margin: 0; }}
  </style>
</head>
<body>
  <div id="chart"></div>
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

def run_volume_analysis(topic: str, date: str, logger=None) -> bool:
    """
    从仓库读取数据，进行声量分析，输出JSON与HTML
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, date)

    logger.info(f"开始运行声量分析，专题: {topic}, 日期: {date}")

    # 尝试从warehouse目录读取数据
    warehouse_dir = bucket("warehouse", topic, date)
    if warehouse_dir.exists():
        logger.info(f"从warehouse目录读取数据: {warehouse_dir}")
        return _analyze_from_warehouse(topic, date, warehouse_dir, logger)
    
    # 如果warehouse目录不存在，尝试从clean目录读取
    clean_dir = bucket("clean", topic, date)
    if clean_dir.exists():
        logger.info(f"从clean目录读取数据: {clean_dir}")
        return _analyze_from_clean(topic, date, clean_dir, logger)
    
    logger.error(f"未找到数据目录: {warehouse_dir} 或 {clean_dir}")
    return False

def _analyze_from_warehouse(topic: str, date: str, warehouse_dir: Path, logger) -> bool:
    """
    从warehouse目录分析数据
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        warehouse_dir (Path): warehouse目录路径
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    csv_files = list(warehouse_dir.glob('*.csv'))
    if not csv_files:
        logger.error(f"warehouse目录中没有CSV文件: {warehouse_dir}")
        return False

    logger.info(f"找到 {len(csv_files)} 个CSV文件")

    # 统计每个渠道CSV文件的行数（排除总体.csv）
    channel_counts = {}
    total_count = 0
    
    for csv_path in csv_files:
        # 跳过总体.csv文件
        if csv_path.name == '总体.csv':
            logger.info(f"跳过总体文件: {csv_path.name}")
            continue
            
        try:
            # 读取CSV文件获取行数
            df = read_csv(csv_path)
            channel_name = csv_path.stem
            record_count = len(df)
            channel_counts[channel_name] = record_count
            total_count += record_count
            logger.info(f"渠道 {channel_name}: {record_count} 条记录")
        except Exception as e:
            logger.warning(f"读取 {csv_path.name} 失败: {e}")
            continue

    if not channel_counts:
        logger.error("没有成功读取任何渠道CSV文件")
        return False

    # 进行声量分析
    return _process_volume_analysis_from_counts(topic, date, channel_counts, total_count, logger, "warehouse")

def _analyze_from_clean(topic: str, date: str, clean_dir: Path, logger) -> bool:
    """
    从clean目录分析数据
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        clean_dir (Path): clean目录路径
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    excel_files = list(clean_dir.glob('*.xlsx'))
    if not excel_files:
        logger.error(f"clean目录中没有Excel文件: {clean_dir}")
        return False

    logger.info(f"找到 {len(excel_files)} 个Excel文件")

    # 统计每个渠道Excel文件的行数
    channel_counts = {}
    total_count = 0
    
    for excel_path in excel_files:
        try:
            # 读取Excel文件获取行数
            df = pd.read_excel(excel_path)
            channel_name = excel_path.stem
            record_count = len(df)
            channel_counts[channel_name] = record_count
            total_count += record_count
            logger.info(f"渠道 {channel_name}: {record_count} 条记录")
        except Exception as e:
            logger.warning(f"读取 {excel_path.name} 失败: {e}")
            continue

    if not channel_counts:
        logger.error("没有成功读取任何Excel文件")
        return False

    # 进行声量分析
    return _process_volume_analysis_from_counts(topic, date, channel_counts, total_count, logger, "clean")

def _process_volume_analysis_from_counts(topic: str, date: str, channel_counts: Dict[str, int], 
                                       total_count: int, logger, source_type: str) -> bool:
    """
    处理声量分析（基于计数）
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        channel_counts (Dict[str, int]): 渠道计数字典
        total_count (int): 总记录数
        logger: 日志记录器
        source_type (str): 数据来源类型
    
    Returns:
        bool: 是否成功
    """
    try:
        # 转换为饼图数据格式
        channel_data = [{"name": k, "value": v} for k, v in channel_counts.items()]
        
        # 创建分析结果
        overall_result = {
            "total_count": total_count,
            "channel_distribution": {
                "type": "pie",
                "data": channel_data,
                "title": "渠道声量分布"
            },
            "channel_details": channel_counts
        }
        
        # 创建输出目录
        processed_root = bucket("processed", topic, date)
        volume_dir = processed_root / 'volume' / '总体'
        volume_dir.mkdir(parents=True, exist_ok=True)

        # 保存总体分析结果
        _save_json(overall_result, volume_dir / 'result.json')
        
        # 生成总体饼图HTML
        overall_html = generate_volume_pie_html(channel_data, '总体渠道声量分布')
        with open(volume_dir / 'result.html', 'w', encoding='utf-8') as f:
            f.write(overall_html)
        logger.info("总体声量分析HTML生成完成")

        logger.info(f"声量分析完成：JSON 与 HTML 已生成（数据来源: {source_type}）")
        logger.info(f"总记录数: {total_count}, 渠道数: {len(channel_counts)}")
        return True

    except Exception as e:
        logger.error(f"处理声量分析失败: {e}")
        import traceback
        traceback.print_exc()
        return False
