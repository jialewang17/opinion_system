"""
TRS Excel导入模块（按工作表名合并）
"""
import pandas as pd
from pathlib import Path
from typing import Dict, List
from ..utils.paths import bucket
from ..utils.logging import setup_logger, log_error, log_save_success
from ..utils.settings import settings

def _collect_excel_files(raw_dir: Path) -> List[Path]:
    """
    收集目录下所有 Excel 文件（.xlsx/.xls）
    
    Args:
        raw_dir (Path): 原始数据目录
    
    Returns:
        List[Path]: Excel文件路径列表
    """
    return list(raw_dir.glob("*.xlsx")) + list(raw_dir.glob("*.xls"))

def _safe_filename(name: str) -> str:
    """
    将工作表名转换为安全的文件名（Windows 兼容）
    
    Args:
        name (str): 工作表名
    
    Returns:
        str: 安全的文件名
    """
    invalid = '<>:"/\\|?*\n\r\t'
    safe = ''.join('_' if ch in invalid else ch for ch in name).strip()
    if not safe:
        safe = 'sheet'
    # 控制长度，避免路径过长
    return safe[:80]

def merge_folder(raw_dir: Path, staging_dir: Path, logger=None) -> Path:
    """
    按工作表名合并文件夹中的所有 TRS Excel 文件。
    - 同名 sheet 的数据进行纵向合并
    - 生成一个多工作表的 merged.xlsx 输出

    Args:
        raw_dir (Path): 原始数据目录（data/raw/<topic>/<date>）
        staging_dir (Path): 暂存目录（data/staging/<topic>/<date>）
        logger: 日志记录器

    Returns:
        Path: 输出的 merged.xlsx 路径；若无数据则返回 None
    """
    if logger is None:
        logger = setup_logger("default", "default")

    # 读取渠道白名单（channels.yaml -> keep）。若未配置则不过滤
    channel_config = settings.get_channel_config()
    keep_channels = set(channel_config.get('keep', []) or [])

    excel_files = _collect_excel_files(raw_dir)

    if not excel_files:
        log_error(logger, f"在 {raw_dir} 中未找到 Excel 文件", "Merge")
        return None

    # sheet_name -> list[pd.DataFrame]
    sheet_to_frames: Dict[str, List[pd.DataFrame]] = {}

    for file_path in excel_files:
        try:
            xl = pd.ExcelFile(file_path)
            for sheet_name in xl.sheet_names:
                try:
                    # 若配置了白名单且当前工作表不在其中，则跳过
                    if keep_channels and sheet_name not in keep_channels:
                        continue
                    df = xl.parse(sheet_name)
                    if df is None or df.empty:
                        continue
                    df = df.copy()
                    df["source_file"] = file_path.name
                    if sheet_name not in sheet_to_frames:
                        sheet_to_frames[sheet_name] = []
                    sheet_to_frames[sheet_name].append(df)
                except Exception as e:
                    log_error(logger, f"读取 {file_path.name} 的工作表 {sheet_name} 失败: {e}", "Merge")
                    continue
        except Exception as e:
            log_error(logger, f"打开 Excel {file_path.name} 失败: {e}", "Merge")
            continue

    if not sheet_to_frames:
        log_error(logger, "未从任何文件读取到有效工作表数据", "Merge")
        return None

    staging_dir.mkdir(parents=True, exist_ok=True)

    # 为每个工作表写入独立的 Excel 文件，文件名为工作表名（已安全化）
    output_files: List[Path] = []
    for sheet_name, frames in sheet_to_frames.items():
        try:
            merged = pd.concat(frames, ignore_index=True)
            # 去重策略（若存在 url 列优先；否则标题+发布时间）
            if "url" in merged.columns:
                merged = merged.drop_duplicates(subset=["url"], keep="first")
            elif "标题" in merged.columns and "发布时间" in merged.columns:
                merged = merged.drop_duplicates(subset=["标题", "发布时间"], keep="first")

            safe_name = _safe_filename(sheet_name)
            output_excel = staging_dir / f"{safe_name}.xlsx"
            merged.to_excel(output_excel, sheet_name=sheet_name[:31], index=False)
            log_save_success(logger, f"{sheet_name} -- 共{len(merged)}条", "Merge")
            output_files.append(output_excel)
        except Exception as e:
            log_error(logger, f"合并/写入工作表 {sheet_name} 失败: {e}", "Merge")
            continue

    if output_files:        # 返回目录路径以表明成功
        return staging_dir
    else:
        log_error(logger, "没有任何工作表成功导出", "Merge")
        return None

def merge_trs_data(topic: str, date: str, logger=None) -> Path:
    """
    合并指定专题和日期的 TRS Excel（按工作表名）
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        Path: 合并后的文件路径
    """
    raw_dir = bucket("raw", topic, date)
    staging_dir = bucket("staging", topic, date)

    return merge_folder(raw_dir, staging_dir, logger)
