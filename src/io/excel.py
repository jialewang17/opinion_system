"""
Excel读写工具模块
"""
import pandas as pd
from pathlib import Path
from typing import Union, Optional, Dict, Any

def read_excel(file_path: Union[str, Path], **kwargs) -> pd.DataFrame:
    """
    读取Excel文件
    
    Args:
        file_path (Union[str, Path]): 文件路径
        **kwargs: 传递给pd.read_excel的参数
    
    Returns:
        pd.DataFrame: 读取的数据
    """
    return pd.read_excel(file_path, **kwargs)

def write_excel(df: pd.DataFrame, file_path: Union[str, Path], **kwargs) -> None:
    """
    写入Excel文件
    
    Args:
        df (pd.DataFrame): 要保存的数据框
        file_path (Union[str, Path]): 文件路径
        **kwargs: 传递给df.to_excel的参数
    """
    df.to_excel(file_path, index=False, **kwargs)

def read_parquet(file_path: Union[str, Path], **kwargs) -> pd.DataFrame:
    """
    读取Parquet文件
    
    Args:
        file_path: 文件路径
        **kwargs: 传递给pd.read_parquet的参数
    
    Returns:
        pd.DataFrame: 读取的数据
    """
    return pd.read_parquet(file_path, **kwargs)

def write_parquet(df: pd.DataFrame, file_path: Union[str, Path], **kwargs) -> None:
    """
    写入Parquet文件
    
    Args:
        df: 要保存的数据框
        file_path: 文件路径
        **kwargs: 传递给df.to_parquet的参数
    """
    df.to_parquet(file_path, index=False, **kwargs)

def read_csv(file_path: Union[str, Path], **kwargs) -> pd.DataFrame:
    """
    读取CSV文件
    
    Args:
        file_path: 文件路径
        **kwargs: 传递给pd.read_csv的参数
    
    Returns:
        pd.DataFrame: 读取的数据
    """
    return pd.read_csv(file_path, **kwargs)

def write_csv(df: pd.DataFrame, file_path: Union[str, Path], **kwargs) -> None:
    """
    写入CSV文件
    
    Args:
        df: 要保存的数据框
        file_path: 文件路径
        **kwargs: 传递给df.to_csv的参数
    """
    df.to_csv(file_path, index=False, encoding='utf-8-sig', **kwargs)
