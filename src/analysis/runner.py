"""
分析运行器模块
"""
import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any
from ..utils.paths import bucket
from ..utils.logging import setup_logger, log_module_start, log_success, log_error, log_save_success
from ..utils.settings import settings
from ..io.excel import read_csv
from .functions.volume import analyze_volume_overall
from .functions.attitude import analyze_attitude_overall, analyze_attitude_by_channel, generate_echarts_pie_html
from .functions.trends import analyze_trends_by_channel
# 注意：keywords 模块会触发 jieba 加载，这里不在顶部导入，按需在分支内延迟导入
from .functions.geography import analyze_geography_overall, analyze_geography_by_channel, generate_china_map_html
from .functions.publishers import analyze_publishers_by_channel
from .functions.theme import analyze_theme_overall
from .functions.highlights import analyze_highlights_overall, analyze_highlights_by_channel, generate_highlights_html

def run_analysis(topic: str, date: str, logger=None, only_function: str = None) -> bool:
    """
    运行分析任务
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
        only_function (str, optional): 仅运行指定分析函数
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, date)
    
    log_module_start(logger, "数据分析")
    
    # 获取分析配置
    analysis_config = settings.get_analysis_config()
    functions = analysis_config.get('functions', [])
    
    if not functions:
        log_error(logger, "未配置分析函数")
        return False
    
    # 读取数据：总体.csv 与各渠道 *.csv（排除 总体.csv）
    warehouse_dir = bucket("warehouse", topic, date)
    if not warehouse_dir.exists():
        log_error(logger, f"未找到数据目录: {warehouse_dir}")
        return False
    overall_file = warehouse_dir / "总体.csv"
    if not overall_file.exists():
        log_error(logger, f"未找到总体数据文件: {overall_file}")
        return False
    try:
        df_overall = read_csv(overall_file)
        logger.info(f"📊 总体数据: {len(df_overall)} 条记录")
    except Exception as e:
        log_error(logger, f"读取总体数据失败: {e}")
        return False
    # 收集渠道文件
    channel_files: Dict[str, Path] = {}
    for csv_path in warehouse_dir.glob("*.csv"):
        if csv_path.name == "总体.csv":
            continue
        channel_name = csv_path.stem
        channel_files[channel_name] = csv_path
    
    # 创建输出目录（按功能/渠道分层）
    processed_root = bucket("processed", topic, date)
    processed_root.mkdir(parents=True, exist_ok=True)
    rejects_dir = processed_root / "_rejects"
    rejects_dir.mkdir(exist_ok=True)
    
    success_count = 0
    
    # 若仅运行单功能，先做一次过滤（支持别名与大小写不敏感）
    if only_function:
        alias = only_function.strip()
        alias_norm = alias.lower()
        before = len(functions)
        functions = [f for f in functions if (f.get('name','').strip().lower() == alias_norm)]
        if not functions:
            log_error(logger, f"--func 未匹配到任何分析项：{only_function}")
            return False
        logger.info(f"🎯 仅运行: {alias} ({len(functions)}/{before})")

    # 运行分析函数
    for func_config in functions:
        func_name = func_config.get('name')
        target = func_config.get('target')
        # 这里不再逐项跳过，已在上方统一过滤
        
        logger.info(f"🔍 {func_name}_{target}")
        
        try:
            # 根据函数名和目标调用对应的分析函数，并按功能/渠道落盘
            if target == '总体':
                # 运行总体
                result = None
                if func_name == 'volume':
                    # 使用专用输出逻辑，直接生成 JSON/HTML（总体与渠道及饼图）
                    from .functions.volume import run_volume_analysis
                    run_volume_analysis(topic, date, logger)
                    # 这里仍落一个占位 JSON 以保持接口一致
                    result = {"generated": True}
                elif func_name == 'attitude':
                    result = analyze_attitude_overall(df_overall, logger)
                elif func_name == 'trends':
                    # 使用专用输出逻辑，直接生成 JSON/HTML（总体与渠道及总体多折线）
                    from .functions.trends import run_trends
                    run_trends(topic, date, logger)
                    # 这里仍落一个占位 JSON 以保持接口一致
                    result = {"generated": True}
                elif func_name == 'keywords':
                    from .functions.keywords import analyze_keywords_overall
                    result = analyze_keywords_overall(df_overall, logger)
                elif func_name == 'geography':
                    result = analyze_geography_overall(df_overall, logger)
                elif func_name == 'publishers':
                    # 发布机构（实现总体版本）
                    from .functions.publishers import analyze_publishers_by_channel, generate_publishers_html_from_result
                    result = analyze_publishers_by_channel(df_overall, logger)
                elif func_name == 'highlights':
                    result = analyze_highlights_overall(df_overall, logger)
                elif func_name == 'theme':
                    result = analyze_theme_overall(df_overall, logger)

                # 保存总体
                func_dir = processed_root / func_name / '总体'
                func_dir.mkdir(parents=True, exist_ok=True)
                output_file = func_dir / 'result.json'
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(result or {}, f, ensure_ascii=False, indent=2, default=str)
                
                # 生成highlights的HTML展示页面
                if func_name == 'highlights' and result and 'highlights' in result:
                    generate_highlights_html(result, func_dir)
                # 额外输出 d3 饼图（如有态度分布）
                if func_name == 'attitude' and result:
                    dist = (result or {}).get('attitude_distribution', {})
                    items = dist.get('data', [])
                    counts = {item.get('name'): item.get('value') for item in items if isinstance(item, dict)}
                    html = generate_echarts_pie_html('态度分布 - 总体', counts)
                    with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                        f.write(html)
                # 趋势分析 HTML 输出（总体）
                if func_name == 'trends' and result:
                    try:
                        from .functions.trends import _compute_daily_counts
                        dates, values = _compute_daily_counts(df_overall)
                        trend_result = {"dates": dates, "values": values}
                        from .functions.trends import generate_trend_area_html
                        html = generate_trend_area_html(dates, values, '总体发布趋势（按天）')
                        with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                            f.write(html)
                    except Exception as e:
                        logger.error(f"生成总体趋势HTML失败: {e}")
                
                # 地图 HTML 输出（总体）
                if func_name == 'geography' and result:
                    dist = (result or {}).get('region_distribution', {})
                    items = dist.get('data', [])
                    counts = {item.get('name'): item.get('value') for item in items if isinstance(item, dict)}
                    html = generate_china_map_html('地域分布 - 总体', counts)
                    with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                        f.write(html)
                # 关键词词云图 HTML 输出（总体）
                if func_name == 'keywords' and result:
                    from .functions.keywords import generate_wordcloud_html
                    html = generate_wordcloud_html(result, topic, date, func_dir)
                    with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                        f.write(html)
                # 发布机构 HTML 输出（总体）
                if func_name == 'publishers' and result:
                    # 渠道总量用于饼图
                    try:
                        channel_totals = df_overall['channel'].value_counts().to_dict()
                    except Exception:
                        channel_totals = {}
                    from .functions.publishers import generate_publishers_html_from_result
                    html = generate_publishers_html_from_result(result, channel_totals=channel_totals)
                    with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                        f.write(html)

                # 主题 HTML 输出（总体）
                if func_name == 'theme' and result:
                    from .functions.theme import generate_theme_bars_html
                    html = generate_theme_bars_html(result)
                    with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                        f.write(html)

                success_count += 1
                log_save_success(logger, f"{func_name}_总体")

            elif target == '渠道':
                # 逐渠道运行
                any_success = False
                for channel_name, csv_path in channel_files.items():
                    try:
                        df_channel = read_csv(csv_path)
                    except Exception as e:
                        logger.error(f"读取渠道 {channel_name} 数据失败: {e}")
                        continue

                    result = None
                    if func_name == 'volume':
                        # volume分析只处理总体，跳过渠道
                        continue
                    elif func_name == 'trends':
                        # 渠道：调用trends模块的函数进行分析
                        try:
                            from .functions.trends import _compute_daily_counts
                            dates, values = _compute_daily_counts(df_channel)
                            result = {"dates": dates, "values": values}
                        except Exception as e:
                            logger.error(f"渠道 {channel_name} 趋势聚合失败: {e}")
                            result = {}
                    elif func_name == 'publishers':
                        from .functions.publishers import analyze_publishers_by_channel, generate_publishers_html_from_result
                        result = analyze_publishers_by_channel(df_channel, logger)
                    elif func_name == 'keywords':
                        # 渠道关键词分析
                        from .functions.keywords import analyze_keywords_overall
                        result = analyze_keywords_overall(df_channel, logger)
                    elif func_name == 'attitude':
                        result = analyze_attitude_by_channel(df_channel, logger)
                    elif func_name == 'geography':
                        result = analyze_geography_by_channel(df_channel, logger)
                    elif func_name == 'highlights':
                        result = analyze_highlights_by_channel(df_channel, logger)
                    elif func_name == 'theme':
                        result = analyze_theme_overall(df_channel, logger)

                    func_dir = processed_root / func_name / channel_name
                    func_dir.mkdir(parents=True, exist_ok=True)
                    output_file = func_dir / 'result.json'
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(result or {}, f, ensure_ascii=False, indent=2, default=str)
                    
                    # 生成highlights的HTML展示页面
                    if func_name == 'highlights' and result and 'highlights' in result:
                        generate_highlights_html(result, func_dir)
                    if func_name == 'attitude' and result:
                        dist = (result or {}).get('attitude_distribution', {})
                        items = dist.get('data', [])
                        counts = {item.get('name'): item.get('value') for item in items if isinstance(item, dict)}
                        html = generate_echarts_pie_html(f'态度分布 - {channel_name}', counts)
                        with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                            f.write(html)
                    if func_name == 'geography' and result:
                        dist = (result or {}).get('region_distribution', {})
                        items = dist.get('data', [])
                        counts = {item.get('name'): item.get('value') for item in items if isinstance(item, dict)}
                        html = generate_china_map_html(f'地域分布 - {channel_name}', counts)
                        with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                            f.write(html)
                    # 关键词词云图 HTML 输出（渠道）
                    if func_name == 'keywords' and result:
                        from .functions.keywords import generate_wordcloud_html
                        html = generate_wordcloud_html(result, topic, date, func_dir)
                        with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                            f.write(html)
                    # 趋势 单序列 HTML 输出（渠道）
                    if func_name == 'trends' and result and 'dates' in result:
                        from .functions.trends import generate_trend_area_html
                        html = generate_trend_area_html(result.get('dates', []), result.get('values', []), f'{channel_name} 发布趋势（按天）')
                        with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                            f.write(html)
                    # 发布机构 HTML 输出（渠道）
                    if func_name == 'publishers' and result:
                        from .functions.publishers import generate_publishers_html_from_result
                        html = generate_publishers_html_from_result(result, channel_totals={channel_name: len(df_channel)})
                        with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                            f.write(html)

                    # 主题 HTML 输出（渠道）
                    if func_name == 'theme' and result:
                        from .functions.theme import generate_theme_bars_html
                        html = generate_theme_bars_html(result)
                        with open(func_dir / 'result.html', 'w', encoding='utf-8') as f:
                            f.write(html)

                    any_success = True
                    log_save_success(logger, f"{func_name}_渠道[{channel_name}]")

                if any_success:
                    success_count += 1
                else:
                    logger.info(f"⚠️  {func_name}_渠道 未生成结果")

        except Exception as e:
            log_error(logger, f"{func_name}_{target}: {e}")
            
            # 保存错误信息到拒绝目录
            error_info = {
                "function": f"{func_name}_{target}",
                "error": str(e),
                "timestamp": pd.Timestamp.now().isoformat()
            }
            
            error_file = rejects_dir / f"{func_name}_{target}_error.json"
            with open(error_file, 'w', encoding='utf-8') as f:
                json.dump(error_info, f, ensure_ascii=False, indent=2)
            
            continue
    
    # 输出最终统计信息
    log_success(logger, f"完成 {success_count}/{len(functions)} 项分析")
    
    # 返回是否成功（至少有一个函数成功）
    return success_count > 0
    
