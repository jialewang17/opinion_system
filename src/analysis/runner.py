"""
分析运行器模块
"""
import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any
from ..utils.paths import bucket
from ..utils.logging import setup_logger, log_module_start, log_success, log_error, log_save_success, log_skip
from ..utils.settings import settings
from ..io.excel import read_csv
from .functions.volume import analyze_volume_overall, analyze_volume_by_channel
from .functions.attitude import analyze_attitude_overall, analyze_attitude_by_channel
from .functions.trends import analyze_trends_overall, analyze_trends_by_channel
from .functions.geography import analyze_geography_overall, analyze_geography_by_channel
from .functions.publishers import analyze_publishers_overall, analyze_publishers_by_channel
from .functions.theme import analyze_theme_overall
from .functions.highlights import analyze_highlights_overall, analyze_highlights_by_channel
from .functions.keywords import analyze_keywords_overall, analyze_keywords_by_channel

def run_Analyze(topic: str, date: str, logger=None, only_function: str = None) -> bool:
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
        
    # 获取分析配置
    analysis_config = settings.get_analysis_config()
    functions = analysis_config.get('functions', [])
    
    if not functions:
        log_error(logger, "未配置分析函数", "Analysis")
        return False
    
    # 读取数据：总体.csv 与各渠道 *.csv（排除 总体.csv）
    warehouse_dir = bucket("warehouse", topic, date)
    if not warehouse_dir.exists():
        log_error(logger, f"未找到数据目录: {warehouse_dir}", "Analysis")
        return False
    overall_file = warehouse_dir / "总体.csv"
    if not overall_file.exists():
        log_error(logger, f"未找到总体数据文件: {overall_file}", "Analysis")
        return False
    try:
        df_overall = read_csv(overall_file)
    except Exception as e:
        log_error(logger, f"读取总体数据失败: {e}", "Analysis")
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
    
    success_count = 0
    
    # 若仅运行单功能，先做一次过滤（支持别名与大小写不敏感）
    if only_function:
        alias = only_function.strip()
        alias_norm = alias.lower()
        before = len(functions)
        functions = [f for f in functions if (f.get('name','').strip().lower() == alias_norm)]
        if not functions:
            log_error(logger, f"--func 未匹配到任何分析项：{only_function}", "Analysis")
            return False
            
    # 运行分析函数
    for func_config in functions:
        func_name = func_config.get('name')
        target = func_config.get('target')
        # 这里不再逐项跳过，已在上方统一过滤
        try:
            # 根据函数名和目标调用对应的分析函数，并按功能/渠道落盘
            if target == '总体':
                # 运行总体
                result = None
                if func_name == 'volume':
                    result = analyze_volume_overall(df_overall, topic, date, logger)
                elif func_name == 'attitude':
                    result = analyze_attitude_overall(df_overall, logger)
                elif func_name == 'trends':
                    result = analyze_trends_overall(df_overall, logger)
                elif func_name == 'keywords':
                    result = analyze_keywords_overall(df_overall, topic, logger)
                elif func_name == 'geography':
                    result = analyze_geography_overall(df_overall, logger)
                elif func_name == 'publishers':
                    result = analyze_publishers_overall(df_overall, logger)
                elif func_name == 'highlights':
                    result = analyze_highlights_overall(df_overall, topic, logger)
                elif func_name == 'theme':
                    result = analyze_theme_overall(df_overall, logger)

                # 保存总体
                func_dir = processed_root / func_name / '总体'
                func_dir.mkdir(parents=True, exist_ok=True)
                # attitude函数保存为attitude.json，geography函数保存为geography.json，highlights函数保存为highlights.json，keywords函数保存为keywords.json，publishers函数保存为publishers.json，trends函数保存为trends.json，volume函数保存为volume.json，其他函数保存为result.json
                if func_name == 'attitude':
                    filename = 'attitude.json'
                elif func_name == 'geography':
                    filename = 'geography.json'
                elif func_name == 'highlights':
                    filename = 'highlights.json'
                elif func_name == 'keywords':
                    filename = 'keywords.json'
                elif func_name == 'publishers':
                    filename = 'publishers.json'
                elif func_name == 'trends':
                    filename = 'trends.json'
                elif func_name == 'volume':
                    filename = 'volume.json'
                else:
                    filename = 'result.json'
                output_file = func_dir / filename
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(result or {}, f, ensure_ascii=False, indent=2, default=str)
                
                success_count += 1

            elif target == '渠道':
                # 逐渠道运行
                any_success = False
                for channel_name, csv_path in channel_files.items():
                    try:
                        df_channel = read_csv(csv_path)
                    except Exception as e:
                        log_error(logger, f"读取渠道 {channel_name} 数据失败: {e}", "Analysis")
                        continue

                    result = None
                    if func_name == 'volume':
                        result = analyze_volume_by_channel(df_channel, channel_name, topic, date, logger)
                    elif func_name == 'trends':
                        result = analyze_trends_by_channel(df_channel, channel_name, logger)
                    elif func_name == 'publishers':
                        result = analyze_publishers_by_channel(df_channel, channel_name, logger)
                    elif func_name == 'keywords':
                        result = analyze_keywords_by_channel(df_channel, topic, channel_name, logger)
                    elif func_name == 'attitude':
                        result = analyze_attitude_by_channel(df_channel, channel_name, logger)
                    elif func_name == 'geography':
                        result = analyze_geography_by_channel(df_channel, channel_name, logger)
                    elif func_name == 'highlights':
                        result = analyze_highlights_by_channel(df_channel, topic, channel_name, logger)
                    elif func_name == 'theme':
                        result = analyze_theme_overall(df_channel, logger)

                    func_dir = processed_root / func_name / channel_name
                    func_dir.mkdir(parents=True, exist_ok=True)
                    # attitude函数保存为attitude.json，geography函数保存为geography.json，highlights函数保存为highlights.json，keywords函数保存为keywords.json，publishers函数保存为publishers.json，trends函数保存为trends.json，volume函数保存为volume.json，其他函数保存为result.json
                    if func_name == 'attitude':
                        filename = 'attitude.json'
                    elif func_name == 'geography':
                        filename = 'geography.json'
                    elif func_name == 'highlights':
                        filename = 'highlights.json'
                    elif func_name == 'keywords':
                        filename = 'keywords.json'
                    elif func_name == 'publishers':
                        filename = 'publishers.json'
                    elif func_name == 'trends':
                        filename = 'trends.json'
                    elif func_name == 'volume':
                        filename = 'volume.json'
                    else:
                        filename = 'result.json'
                    output_file = func_dir / filename
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(result or {}, f, ensure_ascii=False, indent=2, default=str)
                    
                    any_success = True

                if any_success:
                    success_count += 1

        except Exception as e:
            log_error(logger, f"{func_name}_{target}: {e}", "Analysis")
            continue
    
    # 输出最终统计信息
    log_success(logger, "模块执行完成", "Analyze")
    
    # 返回是否成功（至少有一个函数成功）
    return success_count > 0
    
