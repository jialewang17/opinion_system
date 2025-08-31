"""
统一日志管理模块
"""
import logging
import os
from pathlib import Path
from typing import Optional
from .paths import get_logs_root


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器"""
    
    COLORS = {
        'SUCCESS': '\033[92m',  # 绿色
        'ERROR': '\033[91m',    # 红色
        'WARNING': '\033[93m',  # 黄色
        'INFO': '\033[94m',     # 蓝色
        'RESET': '\033[0m'      # 重置
    }
    
    def format(self, record):
        """
        格式化日志记录
        
        Args:
            record: 日志记录
        
        Returns:
            str: 格式化后的日志消息
        """
        # 添加颜色
        if hasattr(record, 'color'):
            record.msg = f"{self.COLORS.get(record.color, '')}{record.msg}{self.COLORS['RESET']}"
        
        return super().format(record)


def setup_logger(topic: str, date: str, log_level: str = "INFO") -> logging.Logger:
    """
    设置日志记录器
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        log_level (str, optional): 日志级别，默认INFO
    
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger(f"{topic}_{date}")
    
    # 避免重复添加handler
    if logger.handlers:  # 避免重复添加handler
        return logger
    
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # 控制台处理器（彩色输出）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = ColoredFormatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器（详细输出）
    try:
        logs_dir = get_logs_root() / topic / date
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = logs_dir / f"{topic}_{date}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"⚠️  警告: 无法创建日志文件: {e}")
        print(f"   日志目录: {get_logs_root()}")
    
    return logger


def log_module_start(logger: logging.Logger, module_name: str):
    """
    打印模块开始标识
    
    Args:
        logger (logging.Logger): 日志记录器
        module_name (str): 模块名称
    """
    logger.info(f"🚀 {module_name}")


def log_success(logger: logging.Logger, message: str):
    """
    打印成功信息（绿色）
    
    Args:
        logger (logging.Logger): 日志记录器
        message (str): 成功消息
    """
    record = logger.makeRecord('success', logging.INFO, '', 0, message, (), None)
    record.color = 'SUCCESS'
    logger.handle(record)


def log_error(logger: logging.Logger, message: str):
    """
    打印错误信息（红色）
    
    Args:
        logger (logging.Logger): 日志记录器
        message (str): 错误消息
    """
    record = logger.makeRecord('error', logging.ERROR, '', 0, message, (), None)
    record.color = 'ERROR'
    logger.handle(record)


def log_save_success(logger: logging.Logger, file_path: str):
    """
    打印保存成功信息
    
    Args:
        logger (logging.Logger): 日志记录器
        file_path (str): 文件路径
    """
    logger.info(f"✅ 已保存: {file_path}")


def log_skip(logger: logging.Logger, reason: str):
    """
    打印跳过信息
    
    Args:
        logger (logging.Logger): 日志记录器
        reason (str): 跳过原因
    """
    logger.info(f"⏭️  跳过: {reason}")


def get_logs_directory() -> Path:
    """
    获取日志目录
    
    Returns:
        Path: 日志目录路径
    """
    return get_logs_root()


def cleanup_old_logs(days_to_keep: int = 30) -> None:
    """
    清理旧日志文件
    
    Args:
        days_to_keep (int, optional): 保留天数，默认30天
    """
    import time
    from datetime import datetime, timedelta
    
    logs_root = get_logs_root()
    if not logs_root.exists():
        return
    
    cutoff_time = time.time() - (days_to_keep * 24 * 60 * 60)
    cleaned_count = 0
    
    for log_file in logs_root.rglob("*.log"):
        try:
            if log_file.stat().st_mtime < cutoff_time:
                log_file.unlink()
                cleaned_count += 1
        except Exception as e:
            print(f"❌ 删除旧日志文件失败 {log_file}: {e}")
    
    if cleaned_count > 0:
        print(f"🧹 已清理 {cleaned_count} 个旧日志文件")
    else:
        print("✨ 没有需要清理的旧日志文件")
