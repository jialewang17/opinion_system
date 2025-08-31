"""
重点议题分析功能模块
"""
import json
import math
import asyncio
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from ...utils.logging import setup_logger
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
                          concurrency: int, logger=None) -> List[Dict[str, Any]]:
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
                
                if logger:
                    logger.info(f"分块{idx+1}/{total_chunks} 开始分析...")
                
                resp = await client._call_api(prompt, max_tokens=2048)
                
                if not resp or resp.strip() == "":
                    if logger:
                        logger.warning(f"分块{idx+1} API返回空响应")
                    return idx, {"error": "empty_response"}
                
                # 清理响应
                cleaned_resp = _clean_api_response(resp)
                
                try:
                    result = json.loads(cleaned_resp)
                    if logger:
                        logger.info(f"分块{idx+1} 分析完成")
                    return idx, result
                except json.JSONDecodeError as e:
                    if logger:
                        logger.warning(f"分块{idx+1} JSON解析失败: {e}")
                    
                    # 尝试提取JSON部分
                    try:
                        start = cleaned_resp.find('{')
                        end = cleaned_resp.rfind('}') + 1
                        if start != -1 and end > start:
                            json_part = cleaned_resp[start:end]
                            result = json.loads(json_part)
                            if logger:
                                logger.info(f"分块{idx+1} 提取JSON部分成功")
                            return idx, result
                    except:
                        pass
                    
                    return idx, {"error": "json_parse_failed", "raw_response": resp}
                    
            except Exception as e:
                if logger:
                    logger.error(f"分块{idx+1} 处理失败: {e}")
                return idx, {"error": str(e)}

    tasks = [run_one(i, c) for i, c in enumerate(chunks)]
    results = [None] * total_chunks
    completed = 0
    
    if logger:
        logger.info(f"启动 {total_chunks} 个并发分析任务")
    
    for future in asyncio.as_completed(tasks):
        try:
            idx, result = await future
            results[idx] = result
            completed += 1
            
            if logger:
                status = "✅" if "error" not in result else "❌"
                logger.info(f"进度: {completed}/{total_chunks} | 分块{idx+1} {status}")
                
        except Exception as e:
            if logger:
                logger.error(f"处理任务结果失败: {e}")
            completed += 1
    
    if logger:
        logger.info(f"所有 {total_chunks} 个分析任务已完成")
    
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
    
    if logger:
        logger.info(f"汇总阶段：有效分块 {len(valid_parts)}/{len(parts)}")
    
    if not valid_parts:
        if logger:
            logger.error("没有有效的分块结果可供汇总")
        return {"error": "no_valid_parts", "failed_count": failed_count}
    
    text = json.dumps(valid_parts, ensure_ascii=False)
    prompt = template_2.format(text=text)
    
    if logger:
        logger.info("开始汇总分析结果...")
    
    try:
        resp = await client._call_api(prompt, max_tokens=2048)
        
        if not resp or resp.strip() == "":
            if logger:
                logger.error("汇总API返回空响应")
            return {"error": "empty_summary_response"}
        
        cleaned_resp = _clean_api_response(resp)
        
        try:
            result = json.loads(cleaned_resp)
            if logger:
                logger.info("汇总分析完成")
            return result
        except json.JSONDecodeError as e:
            if logger:
                logger.error(f"汇总JSON解析失败: {e}")
            
            # 尝试提取JSON部分
            try:
                start = cleaned_resp.find('{')
                end = cleaned_resp.rfind('}') + 1
                if start != -1 and end > start:
                    json_part = cleaned_resp[start:end]
                    result = json.loads(json_part)
                    if logger:
                        logger.info("汇总提取JSON部分成功")
                    return result
            except:
                pass
            
            return {"error": "json_parse_failed", "raw_response": resp}
            
    except Exception as e:
        if logger:
            logger.error(f"汇总分析失败: {e}")
        return {"error": str(e)}


async def analyze_highlights_async(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    异步分析重点议题
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 重点议题分析结果
    """
    if logger is None:
        logger = setup_logger("default", "default")
    
    logger.info("开始重点议题分析")
    
    # 获取配置
    llm_cfg = settings.get('defaults.highlights_llm', {})
    prompts = settings.get_prompts_config().get('highlights', {})
    
    template_1: str = prompts.get('template_1', '{text}')
    template_2: str = prompts.get('template_2', '{text}')
    trunc_cfg = prompts.get('truncation', {})
    max_tokens = int(trunc_cfg.get('max_tokens', 40000))
    
    # 获取LLM配置
    provider = llm_cfg.get('provider', 'qwen')
    model = llm_cfg.get('model', 'qwen-plus')
    qps = llm_cfg.get('qps', 10)
    concurrency = llm_cfg.get('concurrency', 10)
    
    # 初始化客户端
    client = get_qwen_client()
    
    # 准备语料
    n = len(df)
    sample_size = _decide_sample_size(n)
    logger.info(f"重点议题分析采样：总数 {n} -> 采样 {sample_size}")
    
    corpus = _prepare_corpus(df)
    if not corpus:
        logger.error("文本语料为空，无法进行分析")
        return {"error": "empty_corpus"}
    
    # 分块
    chunks = _chunk_text(corpus, max_tokens)
    if not chunks:
        logger.error("文本分块为空，无法进行分析")
        return {"error": "empty_chunks"}
    
    logger.info(f"分块数：{len(chunks)}，并发：{concurrency}")
    logger.info("开始分块分析（template_1）")
    
    # 分析分块
    parts = await _analyze_chunks(client, template_1, chunks, concurrency, logger)
    
    logger.info("分块分析完成，开始汇总（template_2）")
    
    # 汇总结果
    merged = await _summarize_all(client, template_2, parts, logger)
    
    logger.info("重点议题分析完成")
    
    # 构建结果
    result = {
        "highlights": merged.get('highlights', []) if isinstance(merged, dict) and 'error' not in merged else [],
        "meta": {
            "total": n,
            "sampled": sample_size,
            "chunks": len(chunks),
            "concurrency": concurrency,
            "max_chars_per_chunk": max_tokens,
            "provider": provider,
            "model": model,
            "qps": qps
        }
    }
    
    # 如果有错误，添加到结果中
    if isinstance(merged, dict) and 'error' in merged:
        result["error"] = merged["error"]
    
    return result


def analyze_highlights_overall(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    总体重点议题分析
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 重点议题分析结果
    """
    return asyncio.run(analyze_highlights_async(df, logger))


def analyze_highlights_by_channel(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    按渠道重点议题分析
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 重点议题分析结果
    """
    if logger is None:
        logger = setup_logger("default", "default")
    
    logger.info("开始按渠道重点议题分析")
    
    result = {}
    
    if 'channel' in df.columns:
        for channel in df['channel'].unique():
            channel_df = df[df['channel'] == channel]
            logger.info(f"分析渠道: {channel}，记录数: {len(channel_df)}")
            
            channel_result = asyncio.run(analyze_highlights_async(channel_df, logger))
            result[channel] = channel_result
    else:
        # 如果没有channel列，直接分析整个数据集
        result = asyncio.run(analyze_highlights_async(df, logger))
    
    logger.info("按渠道重点议题分析完成")
    return result


def analyze_highlights_overall_sync(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    同步版本的总体重点议题分析
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 重点议题分析结果
    """
    return analyze_highlights_overall(df, logger)


def analyze_highlights_by_channel_sync(df: pd.DataFrame, logger=None) -> Dict[str, Any]:
    """
    同步版本的按渠道重点议题分析
    
    Args:
        df (pd.DataFrame): 数据框
        logger: 日志记录器
    
    Returns:
        Dict[str, Any]: 重点议题分析结果
    """
    return analyze_highlights_by_channel(df, logger)


def generate_highlights_html(highlights_data: Dict[str, Any], output_path: Path) -> None:
    """
    生成重点议题HTML展示页面
    
    Args:
        highlights_data (Dict[str, Any]): 重点议题数据
        output_path (Path): 输出路径
    
    Returns:
        None
    """
    highlights = highlights_data.get('highlights', [])
    if not highlights:
        return
    
    # 只取前20个议题
    highlights = highlights[:20]
    
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>重点议题排行</title>
    <style>
        body {{
            font-family: 'Microsoft YaHei', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            padding: 30px;
        }}
        .title {{
            text-align: center;
            color: #333;
            margin-bottom: 30px;
            font-size: 24px;
            font-weight: bold;
        }}
        .highlights-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 15px;
        }}
        .highlight-item {{
            background: #f8f9fa;
            border-radius: 8px;
            padding: 15px;
            border-left: 4px solid #007bff;
            transition: all 0.3s ease;
            position: relative;
            cursor: pointer;
        }}
        .highlight-item:hover {{
            background: #e9ecef;
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }}
        .rank {{
            position: absolute;
            top: -8px;
            left: -8px;
            background: #007bff;
            color: white;
            width: 25px;
            height: 25px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 12px;
        }}
        .highlight-text {{
            margin-left: 15px;
            line-height: 1.5;
            color: #333;
            font-size: 14px;
            word-break: break-word;
        }}
        .highlight-text.editing {{
            background: #fff;
            border: 2px solid #007bff;
            border-radius: 4px;
            padding: 8px;
            outline: none;
        }}
        @media (max-width: 768px) {{
            .highlights-grid {{
                grid-template-columns: 1fr;
            }}
            .container {{
                padding: 20px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="title">🏆 重点议题排行</div>
        <div class="highlights-grid">
"""
    
    for i, highlight in enumerate(highlights, 1):
        html_content += f"""
            <div class="highlight-item" data-rank="{i}">
                <div class="rank">{i}</div>
                <div class="highlight-text" contenteditable="false">{highlight}</div>
            </div>
"""
    
    html_content += """
        </div>
    </div>
    
    <script>
        // 双击编辑功能
        document.querySelectorAll('.highlight-text').forEach(function(element) {
            element.addEventListener('dblclick', function() {
                if (this.getAttribute('contenteditable') === 'false') {
                    this.setAttribute('contenteditable', 'true');
                    this.classList.add('editing');
                    this.focus();
                    
                    // 选中文本
                    const range = document.createRange();
                    range.selectNodeContents(this);
                    const selection = window.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                }
            });
            
            element.addEventListener('blur', function() {
                this.setAttribute('contenteditable', 'false');
                this.classList.remove('editing');
            });
            
            element.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.blur();
                }
                if (e.key === 'Escape') {
                    this.textContent = this.getAttribute('data-original') || this.textContent;
                    this.blur();
                }
            });
            
            // 保存原始内容
            element.setAttribute('data-original', element.textContent);
        });
    </script>
</body>
</html>
"""
    
    # 保存HTML文件
    html_path = output_path / "result.html"
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
