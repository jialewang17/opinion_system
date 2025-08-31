"""
AI 相关性筛选（并发加速版）：
 - 读取 clean/<topic>/<date>/*.xlsx 的 contents
 - aiohttp + 并发(可配) + QPS(可配) 直接访问千问HTTP接口
 - 逐条截断、即时输出"分析结束 | 返回"
 - 高度相关保留，分渠道各自保存（优先 parquet，失败降级 xlsx）
"""
import json
import asyncio
import time
import os
from collections import deque
import aiohttp
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from ..utils.paths import bucket, ensure_bucket
from ..utils.logging import setup_logger
from ..utils.settings import settings
from ..utils.env_loader import get_api_key, validate_api_key
from ..io.excel import write_excel, read_excel


def _flush_log(logger, msg: str) -> None:
    """
    刷新日志输出
    
    Args:
        logger: 日志记录器
        msg (str): 日志消息
    """
    try:
        logger.info(msg)
        for h in getattr(logger, 'handlers', []) or []:
            try:
                h.flush()
            except Exception:
                pass
    except Exception:
        pass
    try:
        # 进度信息
        pass
    except Exception:
        pass


def _truncate(text: str, max_tokens: int, min_keep: int) -> str:
    """
    截断文本到指定长度
    
    Args:
        text (str): 待截断文本
        max_tokens (int): 最大token数
        min_keep (int): 最小保留长度
    
    Returns:
        str: 截断后的文本
    """
    if not isinstance(text, str):
        return ""
    if len(text) <= max_tokens:
        return text
    # 优先按句号裁切
    parts = text.split('。')
    buf = []
    total = 0
    for p in parts:
        seg = (p + '。') if p else ''
        if total + len(seg) <= max_tokens:
            buf.append(seg)
            total += len(seg)
        else:
            break
    cut = ''.join(buf)
    if len(cut) >= min_keep:
        return cut
    return text[:max_tokens]


def _parse_response(raw: str) -> Dict[str, Any]:
    """
    解析API响应
    
    Args:
        raw (str): 原始响应文本
    
    Returns:
        Dict[str, Any]: 解析后的响应数据
    """
    try:
        s = raw.strip()
        # 去掉常见围栏
        if s.startswith('```'):
            s = s.split('```', 1)[-1]
            s = s.strip()
        # 直接JSON或提取JSON片段
        if s.startswith('{') and s.endswith('}'):
            return json.loads(s)
        i = s.find('{'); j = s.rfind('}')
        if i != -1 and j != -1 and j > i:
            return json.loads(s[i:j+1])
    except Exception:
        pass
    return {"相关": False, "理由": "解析失败"}


def _is_high(parsed: Dict[str, Any]) -> bool:
    """
    判断是否为高度相关
    
    Args:
        parsed (Dict[str, Any]): 解析后的响应数据
    
    Returns:
        bool: 是否为高度相关
    """
    if not isinstance(parsed, dict):
        return False
    if isinstance(parsed.get('相关'), bool):
        return bool(parsed['相关'])
    for k in ['相关性', 'relevance', 'level', 'score', '类别']:
        v = parsed.get(k)
        if isinstance(v, str):
            t = v.strip().lower()
            if ('高' in t) or ('高度相关' in t) or (t in ['high', 'highly relevant', 'relevant']):
                return True
    return False


async def run_filter(topic: str, date: str, logger=None) -> bool:
    """
    运行相关性筛选
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, date)

    _flush_log(logger, "开始运行相关性筛选（重写版）")

    clean_dir = bucket("clean", topic, date)
    files = sorted(clean_dir.glob("*.xlsx"))
    if not files:
        _flush_log(logger, f"未找到清洗数据: {clean_dir}")
        return False

    cfg = settings.get_prompts_config().get('relevance', {})
    template = (cfg.get('template') or '').strip()
    if not template:
        _flush_log(logger, "未配置相关性模板")
        return False
    max_tokens = cfg.get('maxtokens') or cfg.get('max_tokens')
    if max_tokens is None:
        max_tokens = (cfg.get('truncation') or {}).get('max_tokens', 200)
    min_keep = cfg.get('min_keep', 0)

    # 并发与QPS（从 defaults.llm 或 llm 段读取，默认 QPS=20, 并发=50）
    llm_cfg = settings.get('defaults.filter_llm', {}) or settings.get('filter_llm', {}) or {}
    qps = int(llm_cfg.get('qps', 20))
    concurrency = int(llm_cfg.get('concurrency', 50))
    
    # 使用新的环境变量加载器获取API密钥
    api_key = get_api_key()
    if not api_key:
        _flush_log(logger, "❌ 千问API密钥未配置")
        _flush_log(logger, "请设置环境变量 DASHSCOPE_API_KEY 或编辑 .env 文件")
        return False
    
    api_url = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'
    model = llm_cfg.get('model', 'qwen-plus')
    _flush_log(logger, f"并发={concurrency} QPS={qps} 模型={model}")

    # 简易QPS限流（滑动窗口1秒）
    rate_lock = asyncio.Lock()
    recent = deque()
    async def acquire_rate():
        """
        获取速率限制许可
        """
        nonlocal recent
        while True:
            async with rate_lock:
                now = time.monotonic()
                while recent and now - recent[0] >= 1.0:
                    recent.popleft()
                if len(recent) < qps:
                    recent.append(now)
                    return
            await asyncio.sleep(0.005)

    ok = 0
    for fp in files:
        channel = fp.stem
        if channel == 'all':
            continue
        _flush_log(logger, f"处理渠道: {channel}")
        try:
            df = read_excel(fp)
            if df.empty:
                _flush_log(logger, f"{channel} 空数据，跳过")
                continue

            # 构建 prompts
            texts: List[str] = []
            for _, r in df.iterrows():
                c = r.get('contents', '')
                if isinstance(c, str) and c.strip():
                    texts.append(_truncate(c, max_tokens, min_keep))

            if not texts:
                _flush_log(logger, f"{channel} 无有效文段，跳过")
                continue

            prompts = [template.replace('{text}', t) for t in texts]

            sem = asyncio.Semaphore(concurrency)

            async def call_one(i: int, p: str, session: aiohttp.ClientSession) -> Tuple[int, str]:
                """
                调用单个API请求
                
                Args:
                    i (int): 请求索引
                    p (str): 提示词
                    session (aiohttp.ClientSession): HTTP会话
                
                Returns:
                    Tuple[int, str]: (索引, 响应内容)
                """
                headers = { 'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json' }
                payload = { 'model': model, 'input': { 'prompt': p }, 'parameters': { 'max_tokens': max_tokens } }
                async with sem:
                    await acquire_rate()
                    try:
                        async with session.post(api_url, headers=headers, json=payload) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                out = data.get('output', {}).get('text', json.dumps(data, ensure_ascii=False))
                            else:
                                error_data = await resp.json()
                                out = json.dumps(error_data, ensure_ascii=False)
                                _flush_log(logger, f"{channel} 第{i+1}条 API错误: {resp.status} - {error_data}")
                    except Exception as e:
                        out = f"Error: {e}"
                        _flush_log(logger, f"{channel} 第{i+1}条 请求异常: {e}")
                
                parsed = _parse_response(out or '')
                _flush_log(logger, f"{channel} 第{i+1}条 分析结束 | 返回: {parsed}")
                return i, out

            async with aiohttp.ClientSession() as session:
                tasks = [asyncio.create_task(call_one(i, p, session)) for i, p in enumerate(prompts)]
                total = len(tasks)
                _flush_log(logger, f"{channel} 开始调用，总数: {total}")
                results: List[Optional[str]] = [None] * total
                done = 0
                for fut in asyncio.as_completed(tasks):
                    i, raw = await fut
                    results[i] = raw
                    done += 1
                    _flush_log(logger, f"{channel} 进度 {done}/{total} ({done*100//total}%) | idx={i+1}")

            # 解析并筛选
            parsed = [_parse_response(r or '') for r in results]
            mask = [_is_high(p) for p in parsed]
            out = df.iloc[:len(mask)].copy()
            out['rel_raw'] = parsed
            out['rel_score'] = mask
            out = out[out['rel_score'] == True]

            _flush_log(logger, f"{channel} 完成：原始 {len(df)}，相关 {len(out)}")

            dst = ensure_bucket('filtered', topic, date)
            # 仅保存 Excel，且不包含 rel_raw/rel_score
            original_cols = [c for c in df.columns if c not in ['rel_raw', 'rel_score']]
            to_save = out[original_cols] if all(c in out.columns for c in original_cols) else out.drop(columns=['rel_raw','rel_score'], errors='ignore')
            write_excel(to_save, dst / f"{channel}.xlsx")
            ok += 1
        except Exception as e:
            _flush_log(logger, f"{channel} 失败：{e}")
            continue

    _flush_log(logger, f"筛选完成（分渠道保存）：{ok}/{len(files)} 成功")
    return ok > 0


def run_filter_sync(topic: str, date: str, logger=None) -> bool:
    """
    同步运行相关性筛选
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    return asyncio.run(run_filter(topic, date, logger))
