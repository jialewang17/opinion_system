"""
地域分析函数
"""
import pandas as pd
from typing import Dict, List, Any
from ...utils.logging import setup_logger
from pyecharts.charts import Map
from pyecharts import options as opts
from pyecharts.commons.utils import JsCode

def _detect_region_col(df: pd.DataFrame) -> str:
    """
    检测地域列名
    
    Args:
        df (pd.DataFrame): 数据框
    
    Returns:
        str: 地域列名，如果未找到则返回None
    """
    candidate_cols = ['region', '地区', '省份', 'province', 'Province', 'location_province']
    return next((c for c in candidate_cols if c in df.columns), None)

def _count_regions(df: pd.DataFrame) -> Dict[str, int]:
    """
    统计地域分布
    
    Args:
        df (pd.DataFrame): 数据框
    
    Returns:
        Dict[str, int]: 地域统计结果
    """
    # 兼容多种列名
    region_col = _detect_region_col(df)
    if region_col is None:
        return {}
    series = df[region_col].fillna('未知')
    # 去除空白
    series = series.astype(str).str.strip()
    counts = series.value_counts().to_dict()
    return counts

def generate_china_map_html(title: str, region_counts: Dict[str, int]) -> str:
    """
    使用 pyecharts 生成中国地图 HTML，显示各省数值与分段配色
    
    Args:
        title (str): 地图标题
        region_counts (Dict[str, int]): 地域统计数据
    
    Returns:
        str: HTML内容
    """
    # 组装数据：过滤无效与 NAN/未知
    filtered = {}
    for k, v in region_counts.items():
        if k is None:
            continue
        name = str(k).strip()
        if name == '' or name.lower() == 'nan' or name == '未知':
            continue
        iv = int(v)
        if iv <= 0:
            continue
        filtered[name] = iv
    data = list(filtered.items())
    chart = (
        Map(init_opts=opts.InitOpts(width="960px", height="640px"))
        .add(series_name=title, data_pair=data, maptype="china", is_map_symbol_show=False)
        .set_global_opts(
            title_opts=opts.TitleOpts(title=title),
            legend_opts=opts.LegendOpts(is_show=False),
            visualmap_opts=opts.VisualMapOpts(
                max_=max(filtered.values()) if filtered else 1,
                is_piecewise=False,
            ),
        )
        .set_series_opts(
            # 仅显示有数据的数值；无数据时不显示，避免出现 NaN
            label_opts=opts.LabelOpts(
                is_show=True,
                formatter=JsCode("function(params){ return (params.value!=null && !isNaN(params.value)) ? params.value : ''; }"),
                font_size=12,
            ),
            itemstyle_opts=opts.ItemStyleOpts(border_color="#FFFFFF", border_width=0.5),
        )
    )
    return chart.render_embed()

def analyze_geography_overall(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    分析总体地域分布
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 地域分析结果
    """
    if logger is None:
        logger = setup_logger("default", "default")
    
    logger.info("开始分析总体地域分布")
    
    try:
        # 统计地域分布
        region_counts = _count_regions(df)
        
        # 转换为ECharts格式
        region_data = [{"name": k, "value": v} for k, v in region_counts.items()]
        
        # 渠道地域对比
        series_data = []
        # 渠道对比可选，需存在 channel 与 region 列
        region_col = _detect_region_col(df)
        if region_col is not None:
            regions_iter = df[region_col].dropna().unique()
        else:
            regions_iter = []
        for region in regions_iter:
            if pd.notna(region) and region:
                data = []
                if 'channel' in df.columns:
                    for channel in df['channel'].dropna().unique():
                        count = len(df[(df['channel'] == channel) & (df[region_col] == region)])
                        data.append({"name": channel, "value": int(count)})
                
                series_data.append({
                    "name": region,
                    "type": "bar",
                    "data": data
                })
        
        # 地域热度排名
        region_ranking = sorted(region_counts.items(), key=lambda x: x[1], reverse=True)
        top_regions = region_ranking[:10]
        
        # 计算地域覆盖率
        total_records = len(df)
        region_coverage = {}
        for region, count in region_counts.items():
            if pd.notna(region) and region:
                coverage = count / total_records if total_records > 0 else 0
                region_coverage[region] = round(coverage, 3)
        
        result = {
            "total_count": total_records,
            "region_distribution": {
                "type": "pie",
                "data": region_data,
                "title": "地域分布"
            },
            "channel_region_comparison": {
                "type": "bar",
                "series": series_data,
                "title": "各渠道地域对比"
            },
            "region_ranking": {
                "type": "bar",
                "data": [{"name": region, "value": count} for region, count in top_regions],
                "title": "地域热度排名"
            },
            "geography_summary": {
                "total_regions": len(region_counts),
                "top_region": top_regions[0][0] if top_regions else None,
                "top_region_count": top_regions[0][1] if top_regions else 0,
                "region_coverage": region_coverage,
                "unknown_region_count": region_counts.get('未知', 0),
                "unknown_region_ratio": region_counts.get('未知', 0) / total_records if total_records > 0 else 0
            }
        }
        
        logger.info(f"总体地域分析完成，总记录数: {total_records}, 地域数: {len(region_counts)}")
        return result
        
    except Exception as e:
        logger.error(f"总体地域分析失败: {e}")
        return {}

def analyze_geography_by_channel(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    分析单渠道地域分布，返回与总体类似的结构
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 渠道地域分析结果
    """
    if logger is None:
        logger = setup_logger("default", "default")
    logger.info("开始分析渠道地域分布")
    try:
        region_counts = _count_regions(df)
        region_data = [{"name": k, "value": v} for k, v in region_counts.items()]
        total_records = len(df)
        region_ranking = sorted(region_counts.items(), key=lambda x: x[1], reverse=True)
        top_regions = region_ranking[:10]
        result = {
            "total_count": total_records,
            "region_distribution": {
                "type": "map",
                "data": region_data,
                "title": "地域分布"
            },
            "region_ranking": {
                "type": "bar",
                "data": [{"name": region, "value": count} for region, count in top_regions],
                "title": "地域热度排名"
            }
        }
        logger.info(f"渠道地域分析完成，总记录数: {total_records}, 地域数: {len(region_counts)}")
        return result
    except Exception as e:
        logger.error(f"渠道地域分析失败: {e}")
        return {}
