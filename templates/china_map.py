"""
中国地图HTML生成模块
"""
from typing import Dict
from pyecharts.charts import Map
from pyecharts import options as opts
from pyecharts.commons.utils import JsCode

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
