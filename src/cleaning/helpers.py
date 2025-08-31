"""
清洗辅助工具模块
"""
import re
import pandas as pd
from datetime import datetime
from typing import Optional, List, Dict, Any
from dateutil import parser
import pytz

def remove_duplicates(df: pd.DataFrame, subset: List[str] = None) -> pd.DataFrame:
    """
    去除重复数据
    
    Args:
        df (pd.DataFrame): 数据框
        subset (List[str], optional): 去重字段列表
    
    Returns:
        pd.DataFrame: 去重后的数据框
    """
    if subset is None:
        subset = ['url'] if 'url' in df.columns else ['title', 'published_at']
    
    return df.drop_duplicates(subset=subset, keep='first')

def parse_datetime(time_str: str, formats: List[str] = None) -> Optional[datetime]:
    """
    解析时间字符串
    
    Args:
        time_str (str): 时间字符串
        formats (List[str], optional): 时间格式列表
    
    Returns:
        Optional[datetime]: 解析后的时间对象
    """
    if pd.isna(time_str) or not time_str:
        return None
    
    if formats:
        for fmt in formats:
            try:
                return datetime.strptime(str(time_str), fmt)
            except ValueError:
                continue
    
    # 使用dateutil自动解析
    try:
        parsed = parser.parse(str(time_str))
        # 设置时区为上海
        tz = pytz.timezone('Asia/Shanghai')
        if parsed.tzinfo is None:
            parsed = tz.localize(parsed)
        return parsed
    except Exception:
        return None

def clean_text(text: str) -> str:
    """
    清理文本内容
    
    Args:
        text (str): 原始文本
    
    Returns:
        str: 清理后的文本
    """
    if pd.isna(text) or not text:
        return ""
    
    text = str(text)
    
    # 去除多余空白并规范为单空格
    text = re.sub(r'\s+', ' ', text.strip())
    
    # 去除特殊字符（严格版）
    text = re.sub(r'[^\w\s\u4e00-\u9fff.,!?;:()（）【】""''\n\r]', '', text)
    
    return text

def clean_text_whitespace(text: str) -> str:
    """
    仅规范空白与空行，不移除任何标点符号
    
    Args:
        text (str): 原始文本
    
    Returns:
        str: 仅做空白处理后的文本
    """
    if pd.isna(text) or not text:
        return ""
    text = str(text)
    # 将各种空白序列折叠为单个空格，并去首尾空白
    return re.sub(r'\s+', ' ', text).strip()

def normalize_region(region: str, fillna: str = "未知") -> str:
    """
    标准化地域信息（省级化）
    
    Args:
        region (str): 原始地域
        fillna (str, optional): 空值填充，默认"未知"
    
    Returns:
        str: 标准化后的地域
    """
    if pd.isna(region) or not region:
        return fillna
    
    region = str(region).strip()
    
    # 省级映射
    province_map = {
        '北京': '北京市', '天津': '天津市', '上海': '上海市', '重庆': '重庆市',
        '河北': '河北省', '山西': '山西省', '辽宁': '辽宁省', '吉林': '吉林省',
        '黑龙江': '黑龙江省', '江苏': '江苏省', '浙江': '浙江省', '安徽': '安徽省',
        '福建': '福建省', '江西': '江西省', '山东': '山东省', '河南': '河南省',
        '湖北': '湖北省', '湖南': '湖南省', '广东': '广东省', '海南': '海南省',
        '四川': '四川省', '贵州': '贵州省', '云南': '云南省', '陕西': '陕西省',
        '甘肃': '甘肃省', '青海': '青海省', '台湾': '台湾省', '内蒙古': '内蒙古自治区',
        '广西': '广西壮族自治区', '西藏': '西藏自治区', '宁夏': '宁夏回族自治区',
        '新疆': '新疆维吾尔自治区', '香港': '香港特别行政区', '澳门': '澳门特别行政区'
    }
    
    # 查找匹配的省份
    for short, full in province_map.items():
        if short in region or full in region:
            return full
    
    # 如果没有匹配到省份，返回原值或默认值
    return region if region else fillna

def construct_segment(row: pd.Series, field_mapping: Dict[str, str]) -> str:
    """
    构造文本片段
    
    Args:
        row (pd.Series): 数据行
        field_mapping (Dict[str, str]): 字段映射
    
    Returns:
        str: 构造的文本片段
    """
    segment_parts = []
    
    # 按优先级添加字段内容
    priority_fields = ['title', 'summary', 'content', 'ocr']
    
    for field in priority_fields:
        if field in field_mapping:
            mapped_field = field_mapping[field]
            if mapped_field in row and pd.notna(row[mapped_field]):
                content = clean_text(row[mapped_field])
                if content and len(content) > 10:  # 过滤太短的内容
                    segment_parts.append(content)
                    break  # 找到第一个有效内容就停止
    
    # 如果没有找到有效内容，尝试其他字段
    if not segment_parts:
        for field, value in row.items():
            if pd.notna(value) and isinstance(value, str) and len(value) > 10:
                content = clean_text(value)
                if content:
                    segment_parts.append(content)
                    break
    
    return ' '.join(segment_parts) if segment_parts else ""

def map_field_value(value: Any, field_name: str, field_mapping: Dict[str, List[str]]) -> Any:
    """
    映射字段值
    
    Args:
        value (Any): 原始值
        field_name (str): 字段名
        field_mapping (Dict[str, List[str]]): 字段映射配置
    
    Returns:
        Any: 映射后的值
    """
    if field_name not in field_mapping:
        return value
    
    aliases = field_mapping[field_name]
    
    # 如果值在别名列表中，返回标准字段名
    if value in aliases:
        return field_name
    
    return value
