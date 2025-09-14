"""
重点议题分析功能模块
"""
import json
import math
import asyncio
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from ...utils.logging import setup_logger, log_success, log_error, log_module_start
from ...utils.settings import settings
from ...ai.qwen import get_qwen_client


def _pick_title_column(df: pd.DataFrame) -> Optional[str]:
    """
    识别标题列
    
    Args:
        df (pd.DataFrame): 数据框
    
    Returns:
        Optional[str]: 标题列名，如果未找到则返回None
    """
    candidates = ['title', '标题', 'headline', '主题']
    return next((c for c in candidates if c in df.columns), None)


def _decide_sample_size(n: int) -> int:
    """
    决定采样大小
    
    Args:
        n (int): 总数量
    
    Returns:
        int: 采样大小
    """
    if n <= 1000:
        return n
    if n <= 2000:
        return math.ceil(n * 0.8)
    if n <= 5000:
        return math.ceil(n * 0.6)
    if n <= 10000:
        return math.ceil(n * 0.4)
    return 5000


def _prepare_corpus(df: pd.DataFrame) -> str:
    """
    准备文本语料
    
    Args:
        df (pd.DataFrame): 数据框
    
    Returns:
        str: 合并后的文本语料
    """
    col = _pick_title_column(df)
    if not col:
        return ""
    
    # 采样数据
    n = len(df)
    sample_size = _decide_sample_size(n)
    if sample_size < n:
        df_sampled = df.sample(sample_size, random_state=42)
    else:
        df_sampled = df
    
    # 合并标题，添加分隔符
    texts = df_sampled[col].dropna().astype(str).tolist()
    return "\n---\n".join(texts)


def _chunk_text(text: str, max_chars: int) -> List[str]:
    """
    按字符数分块
    
    Args:
        text (str): 文本内容
        max_chars (int): 最大字符数
    
    Returns:
        List[str]: 分块后的文本列表
    """
    if not text:
        return []
    
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        start = end
    return chunks


def _clean_api_response(resp: str) -> str:
    """
    清理API响应，移除Markdown格式
    
    Args:
        resp (str): API响应文本
    
    Returns:
        str: 清理后的文本
    """
    if not resp:
        return ""
    
    cleaned = resp.strip()
    
    # 移除Markdown代码块
    if cleaned.startswith('```json'):
        cleaned = cleaned[7:]
    elif cleaned.startswith('```'):
        cleaned = cleaned[3:]
    
    if cleaned.endswith('```'):
        cleaned = cleaned[:-3]
    
    # 移除首尾空白
    cleaned = cleaned.lstrip('\n\r\t ')
    cleaned = cleaned.rstrip('\n\r\t ')
    
    return cleaned


async def _analyze_chunks(client, template_1: str, chunks: List[str], 
                          concurrency: int, logger=None, channel_name: str = "总体") -> List[Dict[str, Any]]:
    """
    并发分析文本块
    
    Args:
        client: AI客户端
        template_1 (str): 提示词模板
        chunks (List[str]): 文本块列表
        concurrency (int): 并发数
        logger: 日志记录器
    
    Returns:
        List[Dict[str, Any]]: 分析结果列表
    """
    sem = asyncio.Semaphore(concurrency)
    total_chunks = len(chunks)

    async def run_one(idx: int, chunk: str) -> Tuple[int, Dict[str, Any]]:
        """
        处理单个文本块
        
        Args:
            idx (int): 块索引
            chunk (str): 文本块内容
        
        Returns:
            Tuple[int, Dict[str, Any]]: 索引和分析结果
        """
        async with sem:
            try:
                # 转义文本块中的大括号，防止与format占位符冲突
                escaped_chunk = chunk.replace('{', '{{').replace('}', '}}')
                prompt = template_1.format(text=escaped_chunk)
                
                result = await client.call(prompt, max_tokens=2048)
                resp = result.get('text', '') if result else None
                
                if not resp or resp.strip() == "":
                    return idx, {"error": "empty_response"}
                
                # 清理响应
                cleaned_resp = _clean_api_response(resp)
                
                try:
                    result = json.loads(cleaned_resp)
                    # 提取返回的文本用于日志显示
                    highlights = result.get('highlights', [])
                    result_text = highlights[0][:10] + "..." if highlights and len(highlights[0]) > 10 else (highlights[0] if highlights else "")
                    
                    # 计算token使用量（简单估算）
                    token_count = len(prompt) // 4 + len(cleaned_resp) // 4
                    
                    log_success(logger, f"[{channel_name}] 任务{idx+1} 成功 | 结果: {result_text} | Token: {token_count}", "Analyze")
                    return idx, result
                except json.JSONDecodeError as e:
                    # 尝试提取JSON部分
                    try:
                        start = cleaned_resp.find('{')
                        end = cleaned_resp.rfind('}') + 1
                        if start != -1 and end > start:
                            json_part = cleaned_resp[start:end]
                            result = json.loads(json_part)
                            highlights = result.get('highlights', [])
                            result_text = highlights[0][:10] + "..." if highlights and len(highlights[0]) > 10 else (highlights[0] if highlights else "")
                            token_count = len(prompt) // 4 + len(cleaned_resp) // 4
                            log_success(logger, f"[{channel_name}] 任务{idx+1} 成功 | 结果: {result_text} | Token: {token_count}", "Analyze")
                            return idx, result
                    except:
                        pass
                    
                    return idx, {"error": "json_parse_failed", "raw_response": resp}
                    
            except Exception as e:
                return idx, {"error": str(e)}

    tasks = [run_one(i, c) for i, c in enumerate(chunks)]
    results = [None] * total_chunks
    
    for future in asyncio.as_completed(tasks):
        try:
            idx, result = await future
            results[idx] = result
        except Exception as e:
            if logger:
                log_error(logger, f"处理任务结果失败: {e}", "Analyze")
    
    return results


async def _summarize_all(client, template_2: str, parts: List[Dict[str, Any]], 
                         logger=None) -> Dict[str, Any]:
    """
    汇总所有分块结果
    
    Args:
        client: AI客户端
        template_2 (str): 汇总提示词模板
        parts (List[Dict[str, Any]]): 分块结果列表
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 汇总结果
    """
    # 过滤掉失败的分块结果
    valid_parts = []
    failed_count = 0
    
    for i, part in enumerate(parts):
        if part and "error" not in part:
            valid_parts.append(part)
        else:
            failed_count += 1
    
    if not valid_parts:
        log_error(logger, "没有有效的分块结果可供汇总", "Analyze")
        return {"error": "no_valid_parts", "failed_count": failed_count}
    
    text = json.dumps(valid_parts, ensure_ascii=False)
    prompt = template_2.format(text=text)
    
    try:
        result = await client.call(prompt, max_tokens=2048)
        resp = result.get('text', '') if result else None
        
        if not resp or resp.strip() == "":
            log_error(logger, "汇总API返回空响应", "Analyze")
            return {"error": "empty_summary_response"}
        
        cleaned_resp = _clean_api_response(resp)
        
        try:
            result = json.loads(cleaned_resp)
            return result
        except json.JSONDecodeError as e:
            # 尝试提取JSON部分
            try:
                start = cleaned_resp.find('{')
                end = cleaned_resp.rfind('}') + 1
                if start != -1 and end > start:
                    json_part = cleaned_resp[start:end]
                    result = json.loads(json_part)
                    return result
            except:
                pass
            
            return {"error": "json_parse_failed", "raw_response": resp}
            
    except Exception as e:
        log_error(logger, f"汇总分析失败: {e}", "Analyze")
        return {"error": str(e)}


async def analyze_highlights_async(df: pd.DataFrame, topic: str, channel_name: str = "总体", logger=None) -> Dict[str, Any]:
    """
    异步分析重点议题
    
    Args:
        df (pd.DataFrame): 数据框
        topic (str): 话题名称
        channel_name (str): 渠道名称
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 重点议题分析结果
    """
    if logger is None:
        logger = setup_logger("Analyze", "default")
    
    # 准备语料 - 汇总所有文段
    corpus = _prepare_corpus(df)
    if not corpus:
        log_error(logger, "文本语料为空，无法进行分析", "Analyze")
        return {"data": []}
    
    # 获取LLM配置
    llm_cfg = settings.get('highlights_llm', {})
    provider = llm_cfg.get('provider', 'qwen')
    model = llm_cfg.get('model', 'qwen-plus')
    qps = llm_cfg.get('qps', 200)
    truncation = llm_cfg.get('truncation', 40000)
    
    # 加载提示词模板
    templates = _load_prompt_template(topic)
    template_1 = templates['template_1']
    template_2 = templates['template_2']
    
    # 初始化客户端
    client = get_qwen_client()
    
    # 添加开始处理日志
    log_success(logger, f"开始处理{channel_name}", "Analyze")
    
    # 按截断长度分块
    chunks = _chunk_text(corpus, truncation)
    char_count = len(corpus)
    log_success(logger, f"汇总文段总字数: {char_count}, 截断长度分组共 {len(chunks)} 组", "Analyze")
    
    # 并发分析分块
    parts = await _analyze_chunks(client, template_1, chunks, qps, logger, channel_name)
    
    # 汇总所有结果
    merged = await _summarize_all(client, template_2, parts, logger)
    
    # 构建最终结果，只保留data内容
    highlights = merged.get('highlights', []) if isinstance(merged, dict) and 'error' not in merged else []
    
    # 转换为要求的格式
    data = [{"name": highlight, "value": 1} for highlight in highlights]
    
    result = {"data": data}
    
    log_success(logger, f"highlights | {channel_name} 分析完成", "Analyze")
    
    return result


def analyze_highlights_overall(df: pd.DataFrame, topic: str, logger=None) -> Dict[str, Any]:
    """
    总体重点议题分析
    
    Args:
        df (pd.DataFrame): 数据框
        topic (str): 话题名称
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 重点议题分析结果
    """
    if logger is None:
        logger = setup_logger("Analyze", "default")
    
    # 打印模块运行和配置信息
    log_module_start(logger, "模块运行")
    
    # 获取LLM配置并打印
    llm_cfg = settings.get('highlights_llm', {})
    model = llm_cfg.get('model', 'qwen-plus')
    qps = llm_cfg.get('qps', 200)
    truncation = llm_cfg.get('truncation', 40000)
    
    log_success(logger, f"使用模型: {model}, QPS: {qps}, 截断长度: {truncation}", "Analyze")
    
    return asyncio.run(analyze_highlights_async(df, topic, "总体", logger))


def analyze_highlights_by_channel(df: pd.DataFrame, topic: str, channel_name: str, logger=None) -> Dict[str, Any]:
    """
    按渠道重点议题分析
    
    Args:
        df (pd.DataFrame): 数据框
        topic (str): 话题名称
        channel_name (str): 渠道名称
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 重点议题分析结果
    """
    if logger is None:
        logger = setup_logger("Analyze", "default")
    
    return asyncio.run(analyze_highlights_async(df, topic, channel_name, logger))




def _load_prompt_template(topic: str) -> Dict[str, str]:
    """
    加载指定话题的提示词模板
    
    Args:
        topic (str): 话题名称
    
    Returns:
        Dict[str, str]: 包含template_1和template_2的字典
    """
    try:
        prompt_file = Path(f"configs/prompt/highlights/{topic}.yaml")
        if not prompt_file.exists():
            # 如果话题特定的文件不存在，使用默认配置
            prompts = settings.get_prompts_config().get('highlights', {})
            return {
                'template_1': prompts.get('template_1', '{text}'),
                'template_2': prompts.get('template_2', '{text}')
            }
        
        import yaml
        with open(prompt_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        return {
            'template_1': config.get('template_1', '{text}'),
            'template_2': config.get('template_2', '{text}')
        }
    except Exception as e:
        # 回退到默认配置
        prompts = settings.get_prompts_config().get('highlights', {})
        return {
            'template_1': prompts.get('template_1', '{text}'),
            'template_2': prompts.get('template_2', '{text}')
        }
