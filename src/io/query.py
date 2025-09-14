"""
数据库查询模块 - 查询数据库信息
"""
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Tuple
from ..utils.logging import setup_logger, log_success, log_error, log_module_start
from ..utils.settings import settings
from .db import db_manager
from sqlalchemy import text, create_engine
from sqlalchemy.engine.url import make_url


def query_database_info(logger=None) -> bool:
    """
    查询数据库信息的主函数

    Args:
        logger: 日志记录器

    Returns:
        bool: 是否查询成功
    """
    if logger is None:
        logger = setup_logger("Query", "info")

    try:
        # 从databases.yaml读取数据库连接配置
        db_config = settings.get('databases', {})
        db_url = db_config.get('db_url')

        if not db_url:
            log_error(logger, "未找到数据库连接配置，请检查 configs/databases.yaml 文件", "Query")
            return False

        # 获取所有数据库
        databases = get_all_databases(db_url, logger)
        if not databases:
            logger.info("[Query] 未找到任何数据库（可能是权限问题或数据库为空）")
            return True  # 不算错误，只是没有数据库

        log_success(logger, f"发现 {len(databases)} 个数据库: {', '.join(databases)}", "Query")

        # 查询每个数据库的详细信息
        for db_name in databases:
            query_database_details(db_name, db_url, logger)

        return True

    except Exception as e:
        log_error(logger, f"查询数据库信息失败: {e}", "Query")
        import traceback
        log_error(logger, f"详细错误信息: {traceback.format_exc()}", "Query")
        return False


def get_all_databases(db_url: str, logger) -> List[str]:
    """
    获取所有数据库列表

    Args:
        db_url (str): 数据库连接URL
        logger: 日志记录器

    Returns:
        List[str]: 数据库名称列表
    """
    try:
        # 创建连接到系统数据库的引擎
        base_url = make_url(db_url).set(database=None)
        engine = create_engine(base_url)

        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys', 'phpmyadmin')"
            ))

            databases = [row[0] for row in result.fetchall()]

        engine.dispose()
        return databases

    except Exception as e:
        log_error(logger, f"获取数据库列表失败: {e}", "Query")
        return []


def query_database_details(db_name: str, base_db_url: str, logger) -> None:
    """
    查询单个数据库的详细信息

    Args:
        db_name (str): 数据库名称
        base_db_url (str): 基础数据库连接URL
        logger: 日志记录器
    """
    try:
        # 创建指向特定数据库的连接
        db_url = make_url(base_db_url).set(database=db_name)
        engine = create_engine(db_url)

        with engine.connect() as conn:
            # 获取数据库中的所有表
            result = conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :db_name AND table_type = 'BASE TABLE'"
            ), {"db_name": db_name})

            tables = [row[0] for row in result.fetchall()]

            if not tables:
                logger.info(f"[Query] 数据库 {db_name} 中没有表")
                return

            log_success(logger, f"数据库 {db_name} 包含 {len(tables)} 个表: {', '.join(tables)}", "Query")

            # 查询每个表的详细信息
            for table_name in tables:
                query_table_details(conn, db_name, table_name, logger)

        engine.dispose()

    except Exception as e:
        log_error(logger, f"查询数据库 {db_name} 详细信息失败: {e}", "Query")


def query_table_details(conn, db_name: str, table_name: str, logger) -> None:
    """
    查询表的详细信息

    Args:
        conn: 数据库连接
        db_name (str): 数据库名称
        table_name (str): 表名
        logger: 日志记录器
    """
    try:
        # 查询表记录数
        count_result = conn.execute(text(f"SELECT COUNT(*) as count FROM `{table_name}`"))
        record_count = count_result.scalar()

        logger.info(f"[Query] 表 {db_name}.{table_name} 包含 {record_count} 条记录")

        # 查询时间范围（假设有published_at字段）
        time_columns = ['published_at', 'created_at', 'time', 'date']
        time_range = None

        for time_col in time_columns:
            try:
                time_result = conn.execute(text(
                    f"SELECT MIN(`{time_col}`) as min_time, MAX(`{time_col}`) as max_time "
                    f"FROM `{table_name}` WHERE `{time_col}` IS NOT NULL"
                ))

                row = time_result.fetchone()
                if row and row[0] is not None and row[1] is not None:
                    time_range = (row[0], row[1])
                    logger.info(f"[Query] 表 {db_name}.{table_name} 时间范围 ({time_col}): {time_range[0]} 到 {time_range[1]}")
                    break
            except Exception:
                continue

        if not time_range:
            logger.info(f"[Query] 表 {db_name}.{table_name} 未找到时间字段")

    except Exception as e:
        log_error(logger, f"查询表 {db_name}.{table_name} 详细信息失败: {e}", "Query")


def get_database_summary(db_url: str, logger) -> Dict[str, Any]:
    """
    获取数据库汇总信息

    Args:
        db_url (str): 数据库连接URL
        logger: 日志记录器

    Returns:
        Dict[str, Any]: 数据库汇总信息
    """
    summary = {
        'total_databases': 0,
        'total_tables': 0,
        'total_records': 0,
        'databases': []
    }

    try:
        databases = get_all_databases(db_url, logger)
        summary['total_databases'] = len(databases)

        for db_name in databases:
            db_info = {
                'name': db_name,
                'tables': [],
                'total_records': 0
            }

            try:
                db_url_with_db = make_url(db_url).set(database=db_name)
                engine = create_engine(db_url_with_db)

                with engine.connect() as conn:
                    # 获取表列表
                    tables_result = conn.execute(text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :db_name AND table_type = 'BASE TABLE'"
                    ), {"db_name": db_name})

                    tables = [row[0] for row in tables_result.fetchall()]

                    for table_name in tables:
                        try:
                            count_result = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`"))
                            record_count = count_result.scalar()

                            table_info = {
                                'name': table_name,
                                'record_count': record_count
                            }

                            db_info['tables'].append(table_info)
                            db_info['total_records'] += record_count
                            summary['total_records'] += record_count

                        except Exception as e:
                            log_error(logger, f"查询表 {db_name}.{table_name} 记录数失败: {e}", "Query")

                engine.dispose()

            except Exception as e:
                log_error(logger, f"查询数据库 {db_name} 信息失败: {e}", "Query")

            summary['databases'].append(db_info)
            summary['total_tables'] += len(db_info['tables'])

    except Exception as e:
        log_error(logger, f"获取数据库汇总信息失败: {e}", "Query")

    return summary
