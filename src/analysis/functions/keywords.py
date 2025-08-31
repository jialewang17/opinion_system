"""
关键词分析函数 - 重写版本
"""
import pandas as pd
import re
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List, Any, Tuple
from ...utils.logging import setup_logger
from ...utils.paths import bucket
from ...io.excel import read_excel, read_csv

# 导入jieba分词
try:
    import jieba
    import jieba.posseg as pseg
    JIEBA_AVAILABLE = True
    
    # 初始化jieba，添加自定义词典
    def init_jieba():
        """
        初始化jieba分词器，添加自定义专业词汇
        
        Returns:
            None
        """
        # 添加一些专业词汇到jieba词典
        custom_words = [
            '控烟', '戒烟', '禁烟', '无烟', '吸烟', '二手烟', '烟草', '香烟', '打火机',
            '鲁迅', '纪念馆', '墙画', '打卡', '网红', '游客', '投诉', '志愿者',
            '文旅局', '绍兴', '浙江省', '微头条', '微博', '微信', '自媒体',
            '政务平台', '浙里办', '新青年', '极目新闻', '纵览新闻'
        ]
        
        for word in custom_words:
            jieba.add_word(word)
        
        # 已添加自定义词汇到jieba词典
    
    # 初始化jieba
    init_jieba()
    
except ImportError:
    JIEBA_AVAILABLE = False
    # 警告: jieba分词库未安装，将使用简单分词

# 导入词云图相关库
try:
    import matplotlib.pyplot as plt
    from wordcloud import WordCloud
    import numpy as np
    WORDCLOUD_AVAILABLE = True
except ImportError:
    WORDCLOUD_AVAILABLE = False
    # 警告: wordcloud库未安装，将使用HTML词云图

def load_stopwords() -> set:
    """
    从配置文件加载停用词库
    
    Returns:
        set: 停用词集合
    """
    try:
        # 获取项目根目录
        project_root = Path(__file__).resolve().parents[4]
        stopwords_file = project_root / "configs" / "stopwords.txt"
        
        # 如果第一个路径不存在，尝试其他可能的路径
        if not stopwords_file.exists():
            # 尝试从当前工作目录查找
            cwd = Path.cwd()
            stopwords_file = cwd / "configs" / "stopwords.txt"
            
        if not stopwords_file.exists():
            # 尝试从环境变量或配置文件获取
            import os
            config_dir = os.getenv('OPINION_CONFIG_DIR', 'configs')
            stopwords_file = Path(config_dir) / "stopwords.txt"
        
        if not stopwords_file.exists():
            # 警告: 停用词文件不存在，返回基础停用词
            return get_basic_stopwords()
        
        with open(stopwords_file, 'r', encoding='utf-8') as f:
            stopwords = {line.strip() for line in f if line.strip()}
        
        # 添加基础停用词
        stopwords.update(get_basic_stopwords())
        
        return stopwords
    except Exception as e:
        # 加载停用词失败，返回基础停用词
        return get_basic_stopwords()

def get_basic_stopwords() -> set:
    """
    获取基础停用词集合
    
    Returns:
        set: 基础停用词集合
    """
    basic_stopwords = {
        # 常用虚词
        '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这',
        # 时间词
        '今天', '明天', '昨天', '现在', '以前', '以后', '时候', '时间', '日期',
        # 数量词
        '一些', '很多', '几个', '多少', '全部', '部分', '大部分', '小部分',
        # 程度词
        '非常', '特别', '比较', '更加', '最', '太', '很', '十分', '极其',
        # 其他常见无意义词
        '什么', '怎么', '为什么', '哪里', '哪个', '谁', '哪个', '什么', '怎么', '为什么', '哪里', '哪个', '谁'
    }
    return basic_stopwords

def extract_keywords(text: str, stopwords: set, min_length: int = 2) -> List[str]:
    """
    提取关键词
    
    Args:
        text (str): 文本内容
        stopwords (set): 停用词集合
        min_length (int, optional): 最小词长度，默认2
    
    Returns:
        List[str]: 关键词列表
    """
    if not text or pd.isna(text):
        return []
    
    # 清理文本
    text = str(text).strip()
    if not text:
        return []
    
    if JIEBA_AVAILABLE:
        # 使用jieba进行智能分词
        # 设置jieba参数
        jieba.setLogLevel(20)  # 减少日志输出
        
        # 使用词性标注进行分词，只保留名词、动词、形容词等有意义的词
        words = []
        for word, flag in pseg.cut(text):
            # 只保留有意义的词性：n(名词)、v(动词)、a(形容词)、nr(人名)、ns(地名)、nt(机构名)
            if flag.startswith(('n', 'v', 'a', 'nr', 'ns', 'nt')) and len(word) >= min_length:
                # 过滤停用词
                if word not in stopwords:
                    words.append(word)
        
        return words
    else:
        # 降级到简单分词
        # 去除标点符号、数字和特殊字符，保留中文和英文
        text = re.sub(r'[^\u4e00-\u9fff\w\s]', ' ', text)
        
        # 按空格分割
        words = text.split()
        
        # 过滤短词和停用词
        keywords = [word for word in words if len(word) >= min_length and word not in stopwords]
        
        return keywords

def read_excel_contents(topic: str, date: str, logger=None) -> str:
    """
    从对应文件夹读取Excel文件并合并所有contents内容
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        str: 合并后的文本内容
    """
    if logger is None:
        logger = setup_logger("default", "default")
    
    try:
        # 获取数据目录
        data_dir = bucket("warehouse", topic, date)
        if not data_dir.exists():
            logger.error(f"数据目录不存在: {data_dir}")
            return ""
        
        all_contents = []
        
        # 读取所有Excel和CSV文件
        for file_path in data_dir.glob("*"):
            if file_path.suffix.lower() in ['.xlsx', '.xls', '.csv']:
                try:
                    logger.info(f"正在读取文件: {file_path.name}")
                    
                    if file_path.suffix.lower() == '.csv':
                        df = read_csv(file_path)
                    else:
                        df = read_excel(file_path)
                    
                    # 查找content相关列
                    content_columns = []
                    for col in df.columns:
                        if any(keyword in col.lower() for keyword in ['content', '内容', '正文', '摘要', 'ocr']):
                            content_columns.append(col)
                    
                    if content_columns:
                        # 合并所有内容列
                        for col in content_columns:
                            contents = df[col].fillna('').astype(str)
                            all_contents.extend(contents.tolist())
                        
                        logger.info(f"从 {file_path.name} 读取了 {len(content_columns)} 个内容列，共 {len(df)} 条记录")
                    else:
                        logger.warning(f"文件 {file_path.name} 中未找到内容列")
                        
                except Exception as e:
                    logger.error(f"读取文件 {file_path.name} 失败: {e}")
                    continue
        
        # 合并所有内容
        combined_text = ' '.join(all_contents)
        logger.info(f"成功合并文本内容，总长度: {len(combined_text)} 字符")
        
        return combined_text
        
    except Exception as e:
        logger.error(f"读取Excel内容失败: {e}")
        return ""

def analyze_keywords_from_excel(topic: str, date: str, logger=None) -> Dict[str, Any]:
    """
    从Excel文件分析关键词
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 关键词分析结果
    """
    if logger is None:
        logger = setup_logger(topic, date)
    
    logger.info(f"开始从Excel分析关键词，专题: {topic}, 日期: {date}")
    
    try:
        # 加载停用词
        stopwords = load_stopwords()
        
        # 读取Excel内容
        combined_text = read_excel_contents(topic, date, logger)
        if not combined_text:
            logger.error("未获取到文本内容")
            return {}
        
        # 提取关键词
        keywords = extract_keywords(combined_text, stopwords)
        
        # 统计词频
        keyword_counts = Counter(keywords)
        
        # 获取前200个关键词
        top_keywords = keyword_counts.most_common(200)
        
        # 生成JSON格式数据
        json_data = {
            "topic": topic,
            "date": date,
            "total_keywords": len(keyword_counts),
            "top_200_keywords": [
                {"word": word, "count": count} 
                for word, count in top_keywords
            ]
        }
        
        logger.info(f"关键词分析完成，总关键词数: {len(keyword_counts)}")
        return json_data
        
    except Exception as e:
        logger.error(f"关键词分析失败: {e}")
        return {}

def create_python_wordcloud(keywords_data: Dict[str, Any], topic: str, date: str, output_dir: Path) -> str:
    """
    使用Python生成椭圆形词云图
    
    Args:
        keywords_data (Dict[str, Any]): 关键词数据
        topic (str): 专题名称
        date (str): 日期字符串
        output_dir (Path): 输出目录
    
    Returns:
        str: 生成的图片文件名
    """
    if not WORDCLOUD_AVAILABLE:
        return None
    
    try:
        # 提取关键词数据
        keywords_dict = {}
        if 'top_200_keywords' in keywords_data:
            for item in keywords_data['top_200_keywords']:
                if item.get('word') and item.get('count', 0) > 0:
                    keywords_dict[item['word']] = item['count']
        elif 'top_50_keywords' in keywords_data:
            for item in keywords_data['top_50_keywords']:
                if item.get('word') and item.get('count', 0) > 0:
                    keywords_dict[item['word']] = item['count']
        elif 'top_keywords' in keywords_data and 'data' in keywords_data['top_keywords']:
            for item in keywords_data['top_keywords']['data']:
                if item.get('name') and item.get('value', 0) > 0:
                    keywords_dict[item['name']] = item['value']
        
        if not keywords_dict:
            return None
        
        # 创建带虚化边缘的椭圆蒙版
        def create_gradient_ellipse_mask(width=1200, height=800, rx=500, ry=300, fade=60):
            """
            创建带虚化边缘的椭圆蒙版
            
            Args:
                width (int): 图片宽度
                height (int): 图片高度
                rx (int): 椭圆X轴半径
                ry (int): 椭圆Y轴半径
                fade (int): 虚化边缘宽度
            
            Returns:
                np.ndarray: 椭圆蒙版
            """
            mask = np.ones((height, width), dtype=np.uint8) * 255
            cx, cy = width // 2, height // 2
            
            for y in range(height):
                for x in range(width):
                    d = (x - cx) ** 2 / rx ** 2 + (y - cy) ** 2 / ry ** 2
                    if d <= 1:
                        edge_dist = 1 - d
                        if edge_dist > fade / max(rx, ry):
                            mask[y, x] = 0  # 中间区域全黑（可用）
                        else:
                            alpha = edge_dist / (fade / max(rx, ry))
                            mask[y, x] = int(255 * (1 - alpha))  # 边缘逐渐虚化
            return mask
        
        # 设置字体
        font_path = 'C:/Windows/Fonts/msyh.ttc'  # 微软雅黑
        if not Path(font_path).exists():
            font_path = None
        
        # 创建渐变椭圆蒙版
        mask = create_gradient_ellipse_mask()
        
        # 自定义颜色函数 - 黑白风格
        def color_func(word, font_size, position, orientation, random_state=None, **kwargs):
            """
            自定义颜色函数 - 黑白风格
            
            Args:
                word (str): 词汇
                font_size (int): 字体大小
                position (tuple): 位置
                orientation (float): 方向
                random_state: 随机状态
                **kwargs: 其他参数
            
            Returns:
                str: RGB颜色值
            """
            count = keywords_dict.get(word, 0)
            max_count = max(keywords_dict.values())
            ratio = count / max_count if max_count > 0 else 0
            
            # 高频词更黑，低频词浅灰
            gray = int(50 + (1 - ratio) * 150)  # [50,200]之间
            return f"rgb({gray},{gray},{gray})"
        
        # 创建词云对象
        wordcloud = WordCloud(
            font_path=font_path,
            width=1200,
            height=800,
            background_color='white',
            max_words=200,
            max_font_size=120,   # 字体更大更粗
            min_font_size=14,
            random_state=42,
            collocations=False,
            prefer_horizontal=0.6,
            relative_scaling=0.6,  # 控制字重感
            scale=3,  # 高清导出
            mask=mask,
            mode='RGB',
            color_func=color_func
        )
        
        # 生成词云
        wordcloud.generate_from_frequencies(keywords_dict)
        
        # 创建图形
        plt.figure(figsize=(15, 10))
        plt.imshow(wordcloud, interpolation='bilinear')
        plt.axis('off')
        
        # 保存图片
        image_filename = f"{topic}_{date}_wordcloud.png"
        image_path = output_dir / image_filename
        plt.savefig(image_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()  # 关闭图形，释放内存
        
        return image_filename
        
    except Exception as e:
        return None

def generate_wordcloud_html(keywords_data: Dict[str, Any], topic: str, date: str, output_dir: Path = None) -> str:
    """
    生成美观的词云图HTML - 优先使用Python生成的图片，备用JavaScript
    
    Args:
        keywords_data (Dict[str, Any]): 关键词数据
        topic (str): 专题名称
        date (str): 日期字符串
        output_dir (Path, optional): 输出目录
    
    Returns:
        str: HTML内容
    """
    # 支持多种数据格式
    top_keywords = []
    if 'top_200_keywords' in keywords_data:
        top_keywords = keywords_data['top_200_keywords'][:150]  # 显示前150个词
    elif 'top_50_keywords' in keywords_data:
        top_keywords = keywords_data['top_50_keywords'][:150]
    elif 'top_keywords' in keywords_data and 'data' in keywords_data['top_keywords']:
        top_keywords = keywords_data['top_keywords']['data'][:150]
    else:
        return "<p>无关键词数据</p>"
    
    if not top_keywords:
        return "<p>无关键词数据</p>"
    
    # 计算字体大小范围
    max_count = max(kw.get('count', 0) or kw.get('value', 0) for kw in top_keywords) if top_keywords else 1
    min_count = min(kw.get('count', 0) or kw.get('value', 0) for kw in top_keywords) if top_keywords else 1
    
    # 尝试生成Python词云图
    image_filename = None
    if output_dir and WORDCLOUD_AVAILABLE:
        image_filename = create_python_wordcloud(keywords_data, topic, date, output_dir)
    
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{topic} - 关键词词云图</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            background: #ffffff;
            text-align: center;
        }}
        .wordcloud-container {{
            padding: 20px;
            text-align: center;
        }}
        .python-wordcloud img {{
            max-width: 100%;
            height: auto;
            border-radius: 10px;
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
        }}
        .loading {{
            text-align: center;
            padding: 40px;
            color: #666;
            font-size: 18px;
        }}
    </style>
</head>
<body>
    <div class="wordcloud-container">
"""
    
    # 如果有Python生成的图片，优先显示
    if image_filename:
        html_content += f"""
            <div class="python-wordcloud">
                <img src="./{image_filename}" alt="{topic} - 关键词词云图" style="max-width: 100%; height: auto; border-radius: 10px; box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);">
            </div>
        """
    else:
        html_content += """
            <div class="loading">正在生成词云图...</div>
            <canvas id="wordcloud" class="wordcloud-canvas" width="800" height="600"></canvas>
        """
    
    html_content += """
    </div>
    
</body>
</html>
"""
    
    return html_content

def save_keywords_analysis(topic: str, date: str, keywords_data: Dict[str, Any], html_content: str, logger=None) -> bool:
    """
    保存关键词分析结果
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        keywords_data (Dict[str, Any]): 关键词数据
        html_content (str): HTML内容
        logger: 日志记录器
    
    Returns:
        bool: 是否保存成功
    """
    if logger is None:
        logger = setup_logger(topic, date)
    
    try:
        # 创建输出目录
        output_dir = bucket("processed", topic, date) / "keywords"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存JSON数据
        json_file = output_dir / "keywords_analysis.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(keywords_data, f, ensure_ascii=False, indent=2)
        
        # 保存HTML文件
        html_file = output_dir / "keywords_wordcloud.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"关键词分析结果已保存到: {output_dir}")
        logger.info(f"JSON文件: {json_file}")
        logger.info(f"HTML文件: {html_file}")
        
        return True
        
    except Exception as e:
        logger.error(f"保存关键词分析结果失败: {e}")
        return False

def run_keywords_analysis(topic: str, date: str, logger=None) -> bool:
    """
    运行完整的关键词分析流程
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, date)
    
    logger.info(f"开始运行关键词分析流程，专题: {topic}, 日期: {date}")
    
    try:
        # 1. 分析关键词
        keywords_data = analyze_keywords_from_excel(topic, date, logger)
        if not keywords_data:
            logger.error("关键词分析失败")
            return False
        
        # 2. 生成词云图HTML
        output_dir = bucket("processed", topic, date) / "keywords"
        html_content = generate_wordcloud_html(keywords_data, topic, date, output_dir)
        
        # 3. 保存结果
        success = save_keywords_analysis(topic, date, keywords_data, html_content, logger)
        
        if success:
            logger.info("关键词分析流程完成")
            return True
        else:
            logger.error("保存关键词分析结果失败")
            return False
            
    except Exception as e:
        logger.error(f"关键词分析流程失败: {e}")
        return False

# 保持向后兼容的函数
def analyze_keywords_overall(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    分析总体关键词（保持向后兼容）
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 关键词分析结果
    """
    if logger is None:
        logger = setup_logger("default", "default")
    
    logger.info("开始分析总体关键词")
    
    try:
        # 合并所有文本内容 - 支持多种列名
        content_columns = []
        for col in df.columns:
            if any(keyword in col.lower() for keyword in ['content', 'contents', '内容', '正文', '摘要', 'ocr', 'segment']):
                content_columns.append(col)
        
        if not content_columns:
            logger.warning("未找到内容列，尝试使用所有文本列")
            # 如果没有找到内容列，使用所有可能包含文本的列
            text_columns = ['title', 'summary', 'content', 'contents', '正文', '摘要']
            content_columns = [col for col in text_columns if col in df.columns]
        
        if not content_columns:
            logger.error("未找到任何可用的内容列")
            return {}
        
        all_text = ' '.join(df[content_columns].fillna('').astype(str).values.flatten())
        
        # 加载停用词
        stopwords = load_stopwords()
        
        # 提取关键词
        keywords = extract_keywords(all_text, stopwords)
        
        # 统计词频
        keyword_counts = Counter(keywords)
        
        # 获取top关键词
        top_keywords = keyword_counts.most_common(200)
        
        # 转换为ECharts格式
        keyword_data = [{"name": word, "value": count} for word, count in top_keywords[:20]]
        
        # 同时提供两种格式以保持兼容性
        result = {
            "total_keywords": len(keyword_counts),
            "top_keywords": {
                "type": "bar",
                "data": keyword_data,
                "title": "Top 20 关键词"
            },
            "top_200_keywords": [
                {"word": word, "count": count} 
                for word, count in top_keywords
            ],
            "keyword_summary": {
                "total_unique_words": len(keyword_counts),
                "most_frequent_word": top_keywords[0][0] if top_keywords else None,
                "most_frequent_count": top_keywords[0][1] if top_keywords else 0,
                "avg_word_frequency": sum(keyword_counts.values()) / len(keyword_counts) if keyword_counts else 0
            }
        }
        
        logger.info(f"总体关键词分析完成，总关键词数: {len(keyword_counts)}")
        return result
        
    except Exception as e:
        logger.error(f"总体关键词分析失败: {e}")
        return {}
