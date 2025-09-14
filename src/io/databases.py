"""
数据仓库模块 - 入库和提数
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

def upload_cleaned(topic: str, date: str, logger=None) -> bool:
    """
    上传清洗后的数据到数据库
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, date)

    log_success(logger, "开始上传清洗后的数据到数据库", "Warehouse")
    
    clean_dir = bucket("clean", topic, date)
    clean_files = list(clean_dir.glob("*.parquet"))
    
    if not clean_files:
        log_error(logger, "未找到清洗后的数据文件", "Upload")
        return False
    
    success_count = 0
    
    for file_path in clean_files:
        channel = file_path.stem
        log_success(logger, f"正在处理渠道: {channel}", "Warehouse")
        
        try:
            # 读取数据
            df = pd.read_parquet(file_path)
            
            # 生成ID
            df['id'] = df.apply(
                lambda row: generate_id(
                    row.get('segment', ''),
                    row.get('url', ''),
                    str(row.get('published_at', ''))
                ), axis=1
            )
            
            # 确保必要字段存在
            required_fields = ['id', 'segment', 'author', 'published_at', 'url', 'region', 'hit_words', 'polarity']
            for field in required_fields:
                if field not in df.columns:
                    df[field] = ''
            
            # 创建表（如果不存在）
            table_name = f"{topic}_{channel}"
            columns = [
                {'name': 'id', 'type': 'VARCHAR(40) PRIMARY KEY'},
                {'name': 'segment', 'type': 'TEXT'},
                {'name': 'author', 'type': 'VARCHAR(255)'},
                {'name': 'published_at', 'type': 'DATETIME'},
                {'name': 'url', 'type': 'VARCHAR(500)'},
                {'name': 'region', 'type': 'VARCHAR(100)'},
                {'name': 'hit_words', 'type': 'TEXT'},
                {'name': 'polarity', 'type': 'VARCHAR(50)'},
                {'name': 'channel', 'type': 'VARCHAR(100)'},
                {'name': 'topic', 'type': 'VARCHAR(100)'},
                {'name': 'created_at', 'type': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'}
            ]
            
            if not db_manager.table_exists(table_name):
                db_manager.create_table(table_name, columns)
            
            # 准备数据
            df['channel'] = channel
            df['topic'] = topic
            
            # 分批插入数据（避免内存问题）
            batch_size = 1000
            for i in range(0, len(df), batch_size):
                batch_df = df.iloc[i:i+batch_size]
                
                # 构建UPSERT语句
                columns_str = ', '.join(batch_df.columns)
                placeholders = ', '.join([f':{col}' for col in batch_df.columns])
                update_str = ', '.join([f"{col} = VALUES({col})" for col in batch_df.columns if col != 'id'])
                
                sql = f"""
                INSERT INTO {table_name} ({columns_str})
                VALUES ({placeholders})
                ON DUPLICATE KEY UPDATE {update_str}
                """
                
                # 执行插入
                for _, row in batch_df.iterrows():
                    params = row.to_dict()
                    db_manager.execute_update(sql, params)
            
            success_count += 1
            log_success(logger, f"渠道 {channel} 数据上传完成，记录数: {len(df)}", "Warehouse")

        except Exception as e:
            log_error(logger, f"处理渠道 {channel} 失败: {e}", "Warehouse")
            continue

    log_success(logger, f"数据上传完成，成功渠道数: {success_count}/{len(clean_files)}", "Warehouse")
    return success_count > 0

def upload_filtered_excels(topic: str, date: str, logger=None) -> bool:
    """
    扫描 data/filtered/<topic>/<date> 下的 Excel 文件，将每个 Excel 上传为 MySQL 中 <topic> 库下、以文件名为表名的表。
    - 如库不存在则创建
    - 如表不存在则按 DataFrame 推断字段并创建
    - 插入前尽量校验并规范常见字段类型
    """
    if logger is None:
        logger = setup_logger(topic, date)
    # 1. 定位目录与文件
    filtered_dir = bucket("filtered", topic, date)
    excel_files = list(filtered_dir.glob("*.xlsx"))
    if not excel_files:
        log_error(logger, "未在 filtered 目录找到 Excel 文件", "Upload")
        return False

    # 2. 确保数据库存在
    if not db_manager.ensure_database(topic):
        log_error(logger, f"创建或确认数据库 {topic} 失败", "Upload")
        return False

    # 使用指向该数据库的独立引擎
    engine = db_manager.get_engine_for_database(topic)

    def _table_exists(conn, table_name: str) -> bool:
        """
        检查表是否存在
        
        Args:
            conn: 数据库连接
            table_name (str): 表名
        
        Returns:
            bool: 表是否存在
        """
        rs = conn.execute(text(
            """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = :schema AND table_name = :table
            """
        ), {"schema": topic, "table": table_name})
        return (rs.scalar() or 0) > 0

    def _infer_mysql_type(s: pd.Series) -> str:
        """
        推断MySQL字段类型
        
        Args:
            s (pd.Series): 数据列
        
        Returns:
            str: MySQL字段类型
        """
        if pd.api.types.is_datetime64_any_dtype(s):
            return "DATETIME"
        if pd.api.types.is_integer_dtype(s):
            return "BIGINT"
        if pd.api.types.is_float_dtype(s):
            return "DOUBLE"
        if pd.api.types.is_bool_dtype(s):
            return "TINYINT(1)"
        # 默认文本，长度不确定时用 TEXT
        # 如果平均长度较短，也可以用 VARCHAR(1000)
        return "TEXT"

    def _sanitize_columns(df: pd.DataFrame) -> pd.DataFrame:
        """
        清理和规范化列名
        
        Args:
            df (pd.DataFrame): 数据框
        
        Returns:
            pd.DataFrame: 列名规范化后的数据框
        """
        new_cols = []
        for c in df.columns:
            col = str(c).strip()
            col = col.replace(" ", "_")
            col = col.replace("-", "_")
            new_cols.append(col)
        df.columns = new_cols
        # 常见字段类型规范化
        if 'published_at' in df.columns:
            df['published_at'] = pd.to_datetime(df['published_at'], errors='coerce')
        return df

    success_tables = 0

    with engine.begin() as conn:
        for file_path in excel_files:
            table_name = file_path.stem

            try:
                df = read_excel(file_path)
                if df is None or len(df) == 0:
                    log_skip(logger, f"{file_path.name} 无数据，跳过", "Warehouse")
                    continue

                df = _sanitize_columns(df)

                # 3. 表存在性检查，不存在则创建
                if not _table_exists(conn, table_name):
                    column_defs = []
                    for col in df.columns:
                        if col == 'id':
                            # id 列作为主键，使用 VARCHAR(64)
                            column_defs.append("`id` VARCHAR(64) PRIMARY KEY")
                        else:
                            mysql_type = _infer_mysql_type(df[col])
                            column_defs.append(f"`{col}` {mysql_type}")
                    create_sql = f"CREATE TABLE IF NOT EXISTS `{table_name}` ({', '.join(column_defs)}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                    conn.execute(text(create_sql))
                    log_success(logger, f"已创建表 {topic}.{table_name}", "Upload")
                else:
                    # 表已存在，尝试为 id 添加主键或索引
                    if 'id' in df.columns:
                        try:
                            conn.execute(text(f"ALTER TABLE `{table_name}` ADD PRIMARY KEY (`id`)"))
                        except Exception:
                            try:
                                conn.execute(text(f"ALTER TABLE `{table_name}` ADD INDEX `idx_id` (`id`)"))
                            except Exception:
                                pass

            except Exception as e:
                log_error(logger, f"读取或建表步骤失败（{file_path.name}）: {e}", "Warehouse")
                continue

    # 4. 使用 pandas.to_sql 追加数据（分批）；若存在 id 列，则在插入前去重并设置为索引
    for file_path in excel_files:
        table_name = file_path.stem
        try:
            df = read_excel(file_path)
            if df is None or len(df) == 0:
                continue
            df = _sanitize_columns(df)
            if 'id' in df.columns:
                # 去重并将 id 作为索引（仅用于写入前处理，不改变 to_sql 行为）
                before = len(df)
                df = df.drop_duplicates(subset=['id'])
                after = len(df)
                if after < before:
                    log_success(logger, f"{file_path.name} 按 id 去重：{before} -> {after}", "Warehouse")
            # to_sql 会在表不存在时尝试创建，因此我们已先手动创建保证字段类型
            df.to_sql(table_name, con=engine, if_exists='append', index=False, method='multi', chunksize=1000)
            success_tables += 1
            # 简单的格式校验日志
            non_null_ratio = (df.notnull().sum() / len(df)).mean()
            log_success(logger, f"上传成功：{topic}.{table_name} -- 共{len(df)}条", "Upload")
        except Exception as e:
            log_error(logger, f"上传表 {topic}.{table_name} 失败（源文件 {file_path.name}）: {e}", "Upload")
            continue

    engine.dispose()
    return success_tables > 0

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
    
    # 获取所有渠道（从channels.yaml的keep配置）
    channels_config = settings.get_channel_config()
    channels = channels_config.get('keep', [])
    log_success(logger, f"从配置获取渠道列表: {channels}", "Fetch")
    
    # 文件夹命名改为时间范围格式
    folder_name = f"{start_date}_{end_date}"
    warehouse_dir = ensure_bucket("warehouse", topic, folder_name)
    all_data = []
    channel_files = {}  # 用于后续合并
    
    # 从databases.yaml读取数据库连接配置
    db_config = settings.get('databases', {})
    db_url = db_config.get('db_url')
    if not db_url:
        log_error(logger, "未找到数据库连接配置", "Fetch")
        return False
    
    # 创建指向特定数据库的连接
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine.url import make_url
    
    base_url = make_url(db_url)
    db_url_with_db = base_url.set(database=topic)
    engine = create_engine(db_url_with_db)
    
    def _table_exists(conn, table_name: str) -> bool:
        """
        检查表是否存在
        
        Args:
            conn: 数据库连接
            table_name (str): 表名
        
        Returns:
            bool: 表是否存在
        """
        rs = conn.execute(text(
            """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = :schema AND table_name = :table
            """
        ), {"schema": topic, "table": table_name})
        return (rs.scalar() or 0) > 0
    
    def _execute_query(query: str, params: dict) -> pd.DataFrame:
        """
        执行SQL查询
        
        Args:
            query (str): SQL查询语句
            params (dict): 查询参数
        
        Returns:
            pd.DataFrame: 查询结果
        """
        with engine.connect() as conn:
            result = conn.execute(text(query), params)
            return pd.DataFrame(result.fetchall(), columns=result.keys())
    
    for channel in channels:
        try:
            # 表名直接使用渠道名
            table_name = channel
            
            # 检查表是否存在
            with engine.connect() as conn:
                if not _table_exists(conn, table_name):
                    log_error(logger, f"表 {topic}.{table_name} 不存在，跳过", "Fetch")
                    continue
            
            # 先检查表中的数据情况
            check_query = f"SELECT COUNT(*) as total_count FROM {table_name}"
            total_count = _execute_query(check_query, {})

            # 检查时间字段范围
            time_range_query = f"""
            SELECT
                MIN(published_at) as min_time,
                MAX(published_at) as max_time,
                COUNT(*) as count
            FROM {table_name}
            """
            time_range = _execute_query(time_range_query, {})
            time_range_str = ""
            if len(time_range) > 0:
                min_time = time_range.iloc[0]['min_time']
                max_time = time_range.iloc[0]['max_time']
                if min_time and max_time:
                    time_range_str = f" (时间范围: {min_time} 到 {max_time})"

            # 查询数据
            query = f"""
            SELECT * FROM {table_name}
            WHERE DATE(published_at) BETWEEN :start_date AND :end_date
            ORDER BY published_at DESC
            """

            params = {
                'start_date': start_date,
                'end_date': end_date
            }

            df = _execute_query(query, params)

            if len(df) > 0:
                # 保存单个渠道数据
                channel_file = warehouse_dir / f"{channel}.csv"
                write_csv(df, channel_file)
                channel_files[channel] = channel_file

                # 添加到总数据
                all_data.append(df)

                log_success(logger, f"渠道 {channel} 提取完成，记录数: {len(df)}{time_range_str}", "Fetch")
            else:
                log_skip(logger, f"渠道 {channel} 在时间范围 {start_date} 到 {end_date} 内无数据", "Fetch")
                
        except Exception as e:
            log_error(logger, f"提取渠道 {channel} 数据失败: {e}", "Fetch")
            continue

    # 3. 按channels.yaml配置进行合并
    merge_config = channels_config.get('merge_for_analysis', {})
    log_success(logger, f"开始按配置合并渠道: {merge_config}", "Fetch")
    
    # 记录需要删除的原始文件
    files_to_remove = set()
    
    for merge_name, source_channels in merge_config.items():
        try:
            merge_data = []
            for source_channel in source_channels:
                if source_channel in channel_files and channel_files[source_channel].exists():
                    df = pd.read_csv(channel_files[source_channel])
                    if len(df) > 0:
                        merge_data.append(df)
                        log_success(logger, f"合并 {source_channel} -> {merge_name}，记录数: {len(df)}", "Fetch")
                        # 标记原始文件需要删除
                        files_to_remove.add(source_channel)

            if merge_data:
                merged_df = pd.concat(merge_data, ignore_index=True)
                merged_file = warehouse_dir / f"{merge_name}.csv"
                write_csv(merged_df, merged_file)
                log_success(logger, f"合并完成: {merge_name}.csv，总记录数: {len(merged_df)}", "Fetch")
            else:
                log_skip(logger, f"合并 {merge_name} 无数据源", "Warehouse")
                
        except Exception as e:
            log_error(logger, f"合并 {merge_name} 失败: {e}", "Warehouse")
            continue

    # 删除已合并的原始文件
    for channel in files_to_remove:
        if channel in channel_files and channel_files[channel].exists():
            try:
                channel_files[channel].unlink()
            except Exception as e:
                log_error(logger, f"删除文件 {channel}.csv 失败: {e}", "Warehouse")
    
    # 保存总体数据（不包含已合并的渠道）
    if all_data:
        # 重新读取未合并的渠道数据
        final_data = []
        for channel in channels:
            if channel not in files_to_remove and channel in channel_files and channel_files[channel].exists():
                df = pd.read_csv(channel_files[channel])
                if len(df) > 0:
                    final_data.append(df)
        
        # 添加合并后的渠道数据
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
            engine.dispose()
            return True
        else:
            log_error(logger, "没有提取到任何数据", "Warehouse")
            engine.dispose()
            return False
    else:
        log_error(logger, "没有提取到任何数据", "Warehouse")
        engine.dispose()
        return False

def fetch_by_config(topic: str, output_date: str, logger=None) -> bool:
    """
    根据defaults.yaml中的time_window配置提取数据
    
    Args:
        topic (str): 专题名称
        output_date (str): 输出日期（用于分桶）
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, output_date)
    
    # 从defaults.yaml读取时间范围
    time_window = settings.get('defaults.time_window', {})
    start_date = time_window.get('start')
    end_date = time_window.get('end')
    
    if not start_date or not end_date:
        log_error(logger, "未在defaults.yaml中找到有效的time_window配置", "Warehouse")
        return False

    log_success(logger, f"从配置读取时间范围: {start_date} 到 {end_date}", "Warehouse")
    
    return fetch_range(topic, start_date, end_date, output_date, logger)
