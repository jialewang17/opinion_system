"""
AI 相关性筛选（简化并发版）：
 - 读取 clean/<topic>/<date>/*.xlsx 的 contents
 - 使用简化的qwen客户端进行并发处理
 - 逐条输出任务结果和token消耗
 - 高度相关保留，分渠道各自保存
"""
import json
import asyncio
import time
import aiohttp
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from ..utils.paths import bucket, ensure_bucket
from ..utils.logging import setup_logger, log_success, log_error, log_skip
from ..utils.settings import settings
from ..utils.env_loader import get_api_key
from ..io.excel import write_excel, read_excel
from .qwen import QwenClient

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


async def run_Filter(topic: str, date: str, logger=None) -> bool:
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

    # 读取配置
    llm_cfg = settings.get('filter_llm', {})
    model = llm_cfg.get('model', 'qwen-plus')
    qps = int(llm_cfg.get('qps', 200))
    max_tokens = int(llm_cfg.get('truncation', 200))

    log_success(logger, f"使用模型: {model}, QPS: {qps}, 截断长度: {max_tokens}", "Filter")

    # 读取提示词模板
    prompt_config_path = Path(f"configs/prompt/filter/{topic}.yaml")
    if not prompt_config_path.exists():
        log_error(logger, f"未找到提示词配置文件: {prompt_config_path}", "Filter")
        return False

    try:
        import yaml
        with open(prompt_config_path, 'r', encoding='utf-8') as f:
            prompt_cfg = yaml.safe_load(f)
        template = prompt_cfg.get('template', '').strip()
        if not template:
            log_error(logger, "提示词模板为空", "Filter")
            return False
    except Exception as e:
        log_error(logger, f"读取提示词配置失败: {e}", "Filter")
        return False

    clean_dir = bucket("clean", topic, date)
    files = sorted(clean_dir.glob("*.xlsx"))
    if not files:
        log_error(logger, f"未找到清洗数据: {clean_dir}", "Filter")
        return False

    # 初始化客户端
    client = QwenClient()
    total_tasks = 0
    successful_tasks = 0
    total_tokens = 0

    # QPS控制
    last_request_time = time.time()

    async def call_with_qps(prompt: str, idx: int, channel: str) -> Tuple[int, Optional[str], int]:
        """
        带QPS控制的API调用

        Args:
            prompt (str): 提示词
            idx (int): 任务索引
            channel (str): 渠道名称

        Returns:
            Tuple[int, Optional[str], int]: (索引, 响应内容, token消耗)
        """
        nonlocal last_request_time

        # QPS控制
        current_time = time.time()
        time_diff = current_time - last_request_time
        if time_diff < 1.0 / qps:
            await asyncio.sleep(1.0 / qps - time_diff)
        last_request_time = time.time()

        try:
            # 使用简化的qwen客户端
            result = await client.call(prompt, model, max_tokens)

            if result and result.get('text'):
                text_response = result['text']
                usage_info = result.get('usage', {})

                # 解析响应并判断相关性
                parsed = _parse_response(text_response)
                is_relevant = _is_high(parsed)

                # 获取实际token消耗
                total_tokens = usage_info.get('total_tokens', 0)
                if total_tokens == 0:
                    # 如果API没有返回token信息，则估算
                    total_tokens = len(prompt) // 4 + len(text_response) // 4

                # 显示判断结果而不是原始响应
                result_text = "相关" if is_relevant else "不相关"
                log_success(logger, f"[{channel}] 任务{idx} 成功 | 结果: {result_text} | Token: {total_tokens}", "Filter")

                return idx, text_response, total_tokens
            else:
                log_error(logger, f"[{channel}] 任务{idx} 失败 | 无响应", "Filter")
                return idx, None, 0

        except Exception as e:
            log_error(logger, f"[{channel}] 任务{idx} 异常 | {str(e)}", "Filter")
            return idx, None, 0

    # 处理每个渠道
    for fp in files:
        channel = fp.stem
        if channel == 'all':
            continue

        log_success(logger, f"开始处理渠道: {channel}", "Filter")

        try:
            df = read_excel(fp)
            if df.empty:
                log_skip(logger, f"{channel} 空数据，跳过", "Filter")
                continue

            # 构建 prompts
            texts: List[str] = []
            for _, r in df.iterrows():
                c = r.get('contents', '')
                if isinstance(c, str) and c.strip():
                    texts.append(_truncate(c, max_tokens, 50))  # min_keep设为50

            if not texts:
                log_skip(logger, f"{channel} 无有效文段，跳过", "Filter")
                continue

            prompts = [template.replace('{text}', t) for t in texts]

            # 并发处理
            async with aiohttp.ClientSession() as session:
                tasks = [
                    asyncio.create_task(call_with_qps(prompt, i, channel))
                    for i, prompt in enumerate(prompts)
                ]

                results = await asyncio.gather(*tasks)

            # 处理结果
            responses = []
            channel_tokens = 0

            for idx, response, tokens in results:
                total_tasks += 1
                responses.append(response)
                channel_tokens += tokens

                if response:
                    successful_tasks += 1
                    total_tokens += tokens

            # 解析并筛选
            parsed = [_parse_response(r or '') for r in responses]
            mask = [_is_high(p) for p in parsed]
            out = df.iloc[:len(mask)].copy()
            out['rel_raw'] = parsed
            out['rel_score'] = mask
            out = out[out['rel_score'] == True]

            log_success(logger, f"{channel} 完成 | 原始:{len(df)}, 相关:{len(out)}, Token消耗:{channel_tokens}", "Filter")

            # 保存结果
            dst = ensure_bucket('Filtered', topic, date)
            original_cols = [c for c in df.columns if c not in ['rel_raw', 'rel_score']]
            to_save = out[original_cols] if all(c in out.columns for c in original_cols) else out.drop(columns=['rel_raw','rel_score'], errors='ignore')
            write_excel(to_save, dst / f"{channel}.xlsx")

        except Exception as e:
            log_error(logger, f"{channel} 处理失败: {e}", "Filter")
            continue

    # 最终汇总
    log_success(logger, f"筛选完成汇总 | 总任务:{total_tasks}, 成功:{successful_tasks}, 总Token:{total_tokens}", "Filter")
    return successful_tasks > 0


def run_Filter_sync(topic: str, date: str, logger=None) -> bool:
    """
    同步运行相关性筛选
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    return asyncio.run(run_Filter(topic, date, logger))
