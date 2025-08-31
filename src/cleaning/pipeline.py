"""
清洗流水线模块
"""
import pandas as pd
from pathlib import Path
from typing import Dict, List, Any
from ..utils.paths import bucket, ensure_bucket
from ..utils.logging import setup_logger, log_module_start, log_success, log_error, log_save_success
from ..utils.settings import settings
from .helpers import (
    remove_duplicates, parse_datetime, clean_text, clean_text_whitespace,
    normalize_region, construct_segment, map_field_value
)
from ..io.excel import read_excel, write_excel

def run_clean(topic: str, date: str, logger=None) -> bool:
    """
    运行清洗流水线（直接读取 staging/<topic>/<date> 下各渠道 Excel）
    
    需求实现：
    - 遍历 data/staging/<topic>/<date> 下每个渠道的 Excel
    - 每表重编号：id = yyyymmdd + 序号（从1开始），整型
    - 按 channels.yaml.field_alias 将列名映射
    - 针对 content 去重，再基于 contents 再去重
    - 将 title、summary、ocr、content 合并为 contents（存在则拼接）
    - 保留列：id、contents、author、published_at、url、region、hit_words、polarity
    - 清洗 contents 文本；region 省级化；published_at 解析为 MySQL 格式
    - 保存到 data/clean/<topic>/<date>/<channel>.xlsx
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, date)

    log_module_start(logger, "数据清洗")

    staging_dir = bucket("staging", topic, date)
    clean_dir = ensure_bucket("clean", topic, date)

    channel_config = settings.get_channel_config()
    field_alias = channel_config.get('field_alias', {})
    time_config = channel_config.get('time', {})
    region_config = channel_config.get('region', {})

    excel_files = sorted(staging_dir.glob("*.xlsx"))
    if not excel_files:
        log_error(logger, f"未在 {staging_dir} 找到任何渠道 Excel 文件")
        return False

    date_digits = date.replace('-', '')
    total_rows = 0
    success_files = 0

    for file_path in excel_files:
        channel_name = file_path.stem
        try:
            df = read_excel(file_path)
        except Exception as e:
            logger.error(f"读取 {file_path.name} 失败：{e}")
            continue

        if df.empty:
            logger.info(f"{file_path.name} 无数据，跳过")
            continue

        # 列名映射
        rename_map: Dict[str, str] = {}
        for std_field, aliases in field_alias.items():
            for alias in aliases:
                if alias in df.columns:
                    rename_map[alias] = std_field
                    break
        df = df.rename(columns=rename_map)

        # 内容去重（基于 content）
        if 'content' in df.columns:
            df = df.drop_duplicates(subset=['content'], keep='first')

        # 合并文本 -> contents（仅空白清理，不去除标点；缺失填"未知"；带标签前缀）
        for col in ['title', 'summary', 'ocr', 'content']:
            if col in df.columns:
                df[col] = df[col].fillna("未知").astype(str)
        pieces = [df[col] for col in ['title', 'summary', 'ocr', 'content'] if col in df.columns]
        if pieces:
            def _merge_with_labels(row):
                """
                合并文本字段，添加标签前缀
                
                Args:
                    row (pd.Series): 数据行
                
                Returns:
                    str: 合并后的文本内容
                """
                parts = []
                if 'title' in row and str(row['title']).strip() != '未知':
                    parts.append(f"title: {clean_text_whitespace(row['title'])}")
                if 'summary' in row and str(row['summary']).strip() != '未知':
                    parts.append(f"summary: {clean_text_whitespace(row['summary'])}")
                if 'ocr' in row and str(row['ocr']).strip() != '未知':
                    parts.append(f"ocr: {clean_text_whitespace(row['ocr'])}")
                if 'content' in row and str(row['content']).strip() != '未知':
                    parts.append(f"content: {clean_text_whitespace(row['content'])}")
                return ' '.join(parts).strip() if parts else '未知'
            df['contents'] = df.apply(_merge_with_labels, axis=1)
        else:
            df['contents'] = "未知"

        # 仅规范空白（不去标点）
        df['contents'] = df['contents'].apply(clean_text_whitespace)

        # region 省级化
        fillna_region = region_config.get('fillna', '未知')
        if 'region' in df.columns:
            df['region'] = df['region'].apply(lambda x: normalize_region(x, fillna_region))
        else:
            df['region'] = fillna_region

        # 时间解析与格式化
        time_formats = time_config.get('formats', [])
        if 'published_at' in df.columns:
            df['published_at'] = df['published_at'].apply(lambda x: parse_datetime(x, time_formats))
        else:
            df['published_at'] = None
        df['published_at'] = df['published_at'].apply(
            lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if pd.notna(x) and x is not None else None
        )

        # 发布平台（platform）：微博/微信固定；其他渠道优先用重命名后的标准列，其次按别名从原始列取
        if channel_name in ['微博', '微信']:
            df['platform'] = channel_name
        else:
            if 'platform' in df.columns:
                df['platform'] = df['platform'].astype(str).replace('', '未知').fillna('未知')
            else:
                platform_aliases = field_alias.get('platform', [])
                platform_col = next((a for a in platform_aliases if a in df.columns), None)
                if platform_col is not None:
                    df['platform'] = df[platform_col].astype(str).replace('', '未知').fillna('未知')
                else:
                    df['platform'] = '未知'

        # 微博的 title 用 content 替代
        if channel_name == '微博' and 'content' in df.columns:
            df['title'] = df['content']

        # 补全并保留列（保留 title；缺失统一填充“未知”）
        keep_cols = ['id', 'title', 'contents', 'platform', 'author', 'published_at', 'url', 'region', 'hit_words', 'polarity']
        for col in ['title', 'author', 'url', 'hit_words', 'polarity']:
            if col not in df.columns:
                df[col] = "未知"
            else:
                # 将空字符串/NaN 填充为 "未知"
                df[col] = df[col].replace('', '未知').fillna('未知')

        # 重编号（每表独立）
        df = df.reset_index(drop=True)
        df['id'] = df.index.map(lambda i: int(f"{date_digits}{i+1}"))

        # 基于 contents 再次去重
        df = df.drop_duplicates(subset=['contents'], keep='first')

        df_out = df[[c for c in keep_cols]]

        out_file = clean_dir / f"{channel_name}.xlsx"
        try:
            write_excel(df_out, out_file)
            log_save_success(logger, f"{channel_name} ({len(df_out)} 条)")
            total_rows += len(df_out)
            success_files += 1
        except Exception as e:
            log_error(logger, f"保存 {out_file.name} 失败：{e}")
            continue

    log_success(logger, f"清洗完成: {success_files}/{len(excel_files)} 个文件，{total_rows} 条记录")
    return success_files > 0
