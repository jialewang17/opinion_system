"""
数据仓库模块 - 入库和提数
统一数据格式，锁死字段类型，按最大容量设计
"""
import pandas as pd
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from ..utils.paths import bucket, ensure_bucket
from ..utils.logging import setup_logger, log_success, log_error, log_skip
from ..utils.settings import settings
from .db import db_manager
from .excel import write_csv, write_parquet, read_excel
from sqlalchemy import text


def generate_id(segment: str, url: str = "", published_at: str = "") -> str:
    """
    生成数据指纹ID
    
    Args:
        segment (str): 文本片段
        url (str, optional): URL
        published_at (str, optional): 发布时间
    
    Returns:
        str: SHA1哈希值
    """
    if url and published_at:
        content = f"{url}{published_at}"
    else:
        content = segment
    
    return hashlib.sha1(content.encode('utf-8')).hexdigest()


def get_standard_table_schema() -> Dict[str, str]:
    """
    获取标准表结构定义（锁死格式，按最大容量设计）
    
    Returns:
        Dict[str, str]: 字段名到MySQL类型的映射
    """
    return {
        'id': 'VARCHAR(64) PRIMARY KEY',
        'title': 'LONGTEXT',
        'contents': 'LONGTEXT', 
        'platform': 'VARCHAR(50)',
        'author': 'LONGTEXT',
        'published_at': 'DATETIME',
        'url': 'LONGTEXT',
        'region': 'VARCHAR(100)',
        'hit_words': 'TEXT',
        'polarity': 'VARCHAR(20)',
        'classification': 'VARCHAR(100)'
    }


def sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    清理和规范化DataFrame
    
    Args:
        df (pd.DataFrame): 原始数据框
    
    Returns:
        pd.DataFrame: 清理后的数据框
    """
    # 1. 清理列名
    new_cols = []
    for c in df.columns:
        col = str(c).strip()
        col = col.replace(" ", "_")
        col = col.replace("-", "_")
        new_cols.append(col)
    df.columns = new_cols
    
    # 2. 处理时间字段
    if 'published_at' in df.columns:
        df['published_at'] = pd.to_datetime(df['published_at'], errors='coerce')
    
    # 3. 处理分类字段
    if 'classification' in df.columns:
        df['classification'] = df['classification'].astype(str).str.strip()
        df['classification'] = df['classification'].replace(['', 'nan', 'None', 'null'], '未知')
    else:
        df['classification'] = '未知'
    
    # 4. 确保所有字段都是字符串类型（除了时间字段）
    for col in df.columns:
        if col not in ['published_at', 'id']:
            df[col] = df[col].astype(str)
    
    # 5. 移除完全空白的行
    df = df.dropna(how='all')
    
    return df


def create_table_with_standard_schema(conn, table_name: str, topic: str, logger) -> bool:
    """
    使用标准结构创建表
    
    Args:
        conn: 数据库连接
        table_name (str): 表名
        topic (str): 专题名称
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    try:
        schema = get_standard_table_schema()
        column_defs = [f"`{col}` {mysql_type}" for col, mysql_type in schema.items()]
        
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS `{table_name}` (
            {', '.join(column_defs)}
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
        
        conn.execute(text(create_sql))
        log_success(logger, f"已创建表 {topic}.{table_name}（标准结构）", "Upload")
        return True
        
    except Exception as e:
        log_error(logger, f"创建表 {topic}.{table_name} 失败: {e}", "Upload")
        return False


def table_exists(conn, table_name: str, topic: str) -> bool:
    """
    检查表是否存在
    
    Args:
        conn: 数据库连接
        table_name (str): 表名
        topic (str): 专题名称
    
    Returns:
        bool: 表是否存在
    """
    try:
        query = """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = :schema AND table_name = :table
        """
        result = conn.execute(text(query), {"schema": topic, "table": table_name})
        return (result.scalar() or 0) > 0
    except Exception:
        return False


def upload_filtered_excels(topic: str, date: str, logger=None) -> bool:
    """
    上传筛选后的Excel文件到数据库
    使用锁死的标准表结构，按最大容量设计
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, date)
    
    log_success(logger, "开始上传筛选后的Excel文件", "Upload")
    
    # 1. 定位文件
    filtered_dir = bucket("filtered", topic, date)
    excel_files = list(filtered_dir.glob("*.xlsx"))
    
    if not excel_files:
        log_error(logger, "未找到Excel文件", "Upload")
        return False
    
    # 2. 确保数据库存在
    if not db_manager.ensure_database(topic):
        log_error(logger, f"创建数据库 {topic} 失败", "Upload")
        return False
    
    # 3. 获取数据库引擎
    engine = db_manager.get_engine_for_database(topic)
    success_count = 0
    
    with engine.begin() as conn:
        # 4. 创建表（如果不存在）
        for file_path in excel_files:
            table_name = file_path.stem
            
            if not table_exists(conn, table_name, topic):
                if not create_table_with_standard_schema(conn, table_name, topic, logger):
                    continue
        
        # 5. 上传数据
        for file_path in excel_files:
            table_name = file_path.stem
            
            try:
                # 读取Excel文件
                df = read_excel(file_path)
                if df is None or len(df) == 0:
                    log_skip(logger, f"{file_path.name} 无数据，跳过", "Upload")
                    continue
                
                # 清理数据
                df = sanitize_dataframe(df)
                
                # 去重（基于id字段）
                if 'id' in df.columns:
                    before_count = len(df)
                    df = df.drop_duplicates(subset=['id'])
                    after_count = len(df)
                    if before_count != after_count:
                        log_success(logger, f"{file_path.name} 去重: {before_count} -> {after_count}", "Upload")
                
                # 上传数据
                df.to_sql(
                    table_name, 
                    con=engine, 
                    if_exists='append', 
                    index=False, 
                    method='multi', 
                    chunksize=1000
                )
                
                success_count += 1
                log_success(logger, f"上传成功: {topic}.{table_name} ({len(df)}条记录)", "Upload")
                
            except Exception as e:
                log_error(logger, f"上传失败: {topic}.{table_name} - {e}", "Upload")
                continue
    
    engine.dispose()
    log_success(logger, f"上传完成: {success_count}/{len(excel_files)} 个文件成功", "Upload")
    return success_count > 0


def fetch_range(topic: str, start_date: str, end_date: str, output_date: str, logger=None) -> bool:
    """
    从数据库提取指定时间范围的数据
    
    Args:
        topic (str): 专题名称（作为数据库名）
        start_date (str): 开始日期
        end_date (str): 结束日期
        output_date (str): 输出日期（用于分桶）
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, output_date)
    
    log_success(logger, f"开始提取数据: {start_date} 到 {end_date}", "Fetch")
    
    # 1. 获取渠道配置
    channels_config = settings.get_channel_config()
    channels = channels_config.get('keep', [])
    
    # 2. 创建输出目录
    folder_name = f"{start_date}_{end_date}"
    warehouse_dir = ensure_bucket("warehouse", topic, folder_name)
    
    # 3. 获取数据库连接
    db_config = settings.get('databases', {})
    db_url = db_config.get('db_url')
    if not db_url:
        log_error(logger, "未找到数据库连接配置", "Fetch")
        return False
    
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine.url import make_url
    
    base_url = make_url(db_url)
    db_url_with_db = base_url.set(database=topic)
    engine = create_engine(db_url_with_db)
    
    all_data = []
    channel_files = {}
    
    try:
        with engine.connect() as conn:
            # 4. 提取各渠道数据
            for channel in channels:
                try:
                    if not table_exists(conn, channel, topic):
                        log_skip(logger, f"表 {topic}.{channel} 不存在，跳过", "Fetch")
                        continue
                    
                    # 查询数据
                    query = """
                    SELECT * FROM {table_name}
                    WHERE DATE(published_at) BETWEEN :start_date AND :end_date
                    ORDER BY published_at DESC
                    """.format(table_name=channel)
                    
                    result = conn.execute(text(query), {
                        'start_date': start_date,
                        'end_date': end_date
                    })
                    
                    df = pd.DataFrame(result.fetchall(), columns=result.keys())
                    
                    if len(df) > 0:
                        # 确保classification字段存在
                        if 'classification' not in df.columns:
                            df['classification'] = '未知'
                        else:
                            df['classification'] = df['classification'].fillna('未知')
                        
                        # 保存渠道数据
                        channel_file = warehouse_dir / f"{channel}.csv"
                        write_csv(df, channel_file)
                        channel_files[channel] = channel_file
                        all_data.append(df)
                        
                        log_success(logger, f"渠道 {channel}: {len(df)}条记录", "Fetch")
                    else:
                        log_skip(logger, f"渠道 {channel} 无数据", "Fetch")
                        
                except Exception as e:
                    log_error(logger, f"提取渠道 {channel} 失败: {e}", "Fetch")
                    continue
            
            # 5. 合并渠道数据
            merge_config = channels_config.get('merge_for_analysis', {})
            files_to_remove = set()
            
            for merge_name, source_channels in merge_config.items():
                try:
                    merge_data = []
                    for source_channel in source_channels:
                        if source_channel in channel_files and channel_files[source_channel].exists():
                            df = pd.read_csv(channel_files[source_channel])
                            if len(df) > 0:
                                merge_data.append(df)
                                files_to_remove.add(source_channel)
                    
                    if merge_data:
                        merged_df = pd.concat(merge_data, ignore_index=True)
                        merged_file = warehouse_dir / f"{merge_name}.csv"
                        write_csv(merged_df, merged_file)
                        all_data.append(merged_df)
                        log_success(logger, f"合并完成: {merge_name} ({len(merged_df)}条记录)", "Fetch")
                        
                except Exception as e:
                    log_error(logger, f"合并 {merge_name} 失败: {e}", "Fetch")
                    continue
            
            # 6. 删除已合并的原始文件
            for channel in files_to_remove:
                if channel in channel_files and channel_files[channel].exists():
                    try:
                        channel_files[channel].unlink()
                    except Exception as e:
                        log_error(logger, f"删除文件 {channel}.csv 失败: {e}", "Fetch")
            
            # 7. 保存总体数据
            if all_data:
                # 重新收集未合并的数据
                final_data = []
                for channel in channels:
                    if channel not in files_to_remove and channel in channel_files and channel_files[channel].exists():
                        df = pd.read_csv(channel_files[channel])
                        if len(df) > 0:
                            final_data.append(df)
                
                # 添加合并后的数据
                for merge_name in merge_config.keys():
                    merged_file = warehouse_dir / f"{merge_name}.csv"
                    if merged_file.exists():
                        df = pd.read_csv(merged_file)
                        if len(df) > 0:
                            final_data.append(df)
                
                if final_data:
                    all_df = pd.concat(final_data, ignore_index=True)
                    all_file = warehouse_dir / "总体.csv"
                    write_csv(all_df, all_file)
                    log_success(logger, f"总体数据保存完成: {len(all_df)}条记录", "Fetch")
                    return True
                else:
                    log_error(logger, "没有提取到任何数据", "Fetch")
                    return False
            else:
                log_error(logger, "没有提取到任何数据", "Fetch")
                return False
                
    finally:
        engine.dispose()