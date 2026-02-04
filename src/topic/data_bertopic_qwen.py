#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BERTopic + Qwen 主题分析数据处理模块
输入: data/fetch/{topic}/{date_range}/各渠道.csv（包含 contents 列，自动合并所有渠道）
依赖: configs/stopwords.txt, configs/userdict.txt(可选)
输出: data/topic/{topic}/{date_range}/{1..5}.json
"""
import re
import json
import warnings
import hashlib
import pickle
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# 严格抑制所有警告（在导入可能产生警告的库之前）
warnings.filterwarnings("ignore")  # 抑制所有警告
warnings.simplefilter("ignore")  # 设置默认过滤器为忽略
# 特别抑制 pkg_resources 相关警告
warnings.filterwarnings("ignore", message=".*pkg_resources.*")
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

import pandas as pd
import numpy as np
import jieba
import yaml
import asyncio
from openai import OpenAI, AsyncOpenAI
from bertopic import BERTopic
from umap import UMAP
from hdbscan import HDBSCAN
from sklearn.feature_extraction.text import CountVectorizer
from collections import defaultdict

# 抑制jieba的日志输出（设置为ERROR级别，减少输出）
jieba.setLogLevel(60)  # 60 = ERROR级别，可以抑制"Building prefix dict..."等信息

from ..utils.logging.logging import (
    setup_logger, log_success, log_error, log_module_start, log_save_success
)
from ..utils.setting.env_loader import get_api_key, load_env_file
from ..utils.setting.paths import get_project_root, bucket
from ..utils.io.excel import read_csv


# 配置常量
TARGET_TOPICS = 8  # 大模型合并后的目标主题数
LLM_MODEL_NAME = "qwen-plus"

def _default_paths(topic: str, start_date: str, end_date: str = None) -> Dict[str, Path]:
    """
    获取默认路径，防止路径遍历攻击
    
    Args:
        topic: 专题名称（会进行安全校验）
        start_date: 开始日期
        end_date: 结束日期
    """
    # 安全校验：允许中文、字母、数字、下划线、连字符
    # 中文范围使用基本中日韩统一表意文字块（\u4e00-\u9fff）
    if not re.match(r'^[\w\-\u4e00-\u9fff]+$', topic):
        raise ValueError(f"专题名称包含非法字符: {topic}，只允许中文、字母、数字、下划线、连字符")
    
    project_root = get_project_root()
    configs_root = project_root / "configs"
    # 使用fetch目录，与analyze模块一致
    if end_date:
        folder_name = f"{start_date}_{end_date}"
    else:
        folder_name = start_date
    
    # 使用Path.name确保只取文件名部分，防止路径遍历
    safe_topic = Path(topic).name
    fetch_dir = bucket("fetch", safe_topic, folder_name)
    userdict = configs_root / "userdict.txt"  # 可选：用户词典，使用项目统一配置
    stopwords = configs_root / "stopwords.txt"  # 使用项目统一配置
    # 输出路径使用相同的日期范围格式
    out_analyze = bucket("topic", safe_topic, folder_name)  # 输出到data/topic/{topic}/{date_range}/
    return {
        "fetch_dir": fetch_dir,
        "userdict": userdict,
        "stopwords": stopwords,
        "out_analyze": out_analyze,
    }


def _load_and_merge_fetch_data(fetch_dir: Path, logger) -> pd.DataFrame:
    """
    从fetch目录读取所有CSV文件并合并（与analyze模块一致）
    
    Args:
        fetch_dir (Path): fetch目录路径
        logger: 日志记录器
    
    Returns:
        pd.DataFrame: 合并后的数据框
    """
    if not fetch_dir.exists():
        log_error(logger, f"fetch目录不存在: {fetch_dir}", "TopicBertopic")
        return pd.DataFrame()
    
    # 读取总体.csv文件（包含所有渠道数据）
    overall_file = fetch_dir / "总体.csv"
    if overall_file.exists():
        try:
            df = read_csv(overall_file)
            if not df.empty:
                log_success(logger, f"读取总体数据: {len(df)}条", "TopicBertopic")
                # 去重（基于contents字段）
                before_count = len(df)
                df = df.drop_duplicates(subset=['contents'], keep='last')
                after_count = len(df)
                if before_count != after_count:
                    log_success(logger, f"去重: {before_count} -> {after_count}", "TopicBertopic")
                log_success(logger, f"合并完成，共{len(df)}条数据", "TopicBertopic")
                return df
        except Exception as e:
            log_error(logger, f"读取总体数据失败: {e}", "TopicBertopic")
    
    # 如果没有总体.csv，则读取各渠道CSV文件并合并
    csv_files = sorted([f for f in fetch_dir.glob("*.csv") if f.name != "总体.csv"])
    if not csv_files:
        log_error(logger, f"未找到CSV文件: {fetch_dir}", "TopicBertopic")
        return pd.DataFrame()
    
    log_success(logger, f"找到{len(csv_files)}个渠道CSV文件", "TopicBertopic")
    
    # 读取并合并所有文件
    all_data = []
    for file_path in csv_files:
        try:
            df = read_csv(file_path)
            if not df.empty:
                all_data.append(df)
                log_success(logger, f"读取: {file_path.name} - {len(df)}条", "TopicBertopic")
        except Exception as e:
            log_error(logger, f"读取失败 {file_path.name}: {e}", "TopicBertopic")
            continue
    
    if not all_data:
        log_error(logger, "没有读取到任何数据", "TopicBertopic")
        return pd.DataFrame()
    
    # 合并所有数据
    merged_df = pd.concat(all_data, ignore_index=True)
    
    # 去重（基于contents字段）
    before_count = len(merged_df)
    merged_df = merged_df.drop_duplicates(subset=['contents'], keep='last')
    after_count = len(merged_df)
    
    if before_count != after_count:
        log_success(logger, f"合并后去重: {before_count} -> {after_count}", "TopicBertopic")
    
    log_success(logger, f"合并完成，共{len(merged_df)}条数据", "TopicBertopic")
    return merged_df


def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[^\u4e00-\u9fa5\u3000-\u303f0-9，。！？；：、（）《》【】""''\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _clean_batch(texts: List[str]) -> Tuple[List[str], Dict[str, int]]:
    cleaned, seen = [], set()
    stats = {"total": 0, "duplicates": 0, "final": 0}
    for t in texts:
        stats["total"] += 1
        ct = _clean_text(t)
        if ct in seen:
            stats["duplicates"] += 1
            continue
        seen.add(ct)
        if ct:
            cleaned.append(ct)
    stats["final"] = len(cleaned)
    return cleaned, stats


def _load_stopwords(path: Path) -> List[str]:
    if path.exists():
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return []


def _segment(texts: List[str], stopwords: List[str], userdict: Optional[Path]) -> List[str]:
    if userdict and userdict.exists():
        jieba.load_userdict(str(userdict))
    stopset = set(stopwords)
    result: List[str] = []
    for t in texts:
        words = [w for w in jieba.cut(t) if len(w) >= 2 and not w.isdigit() and w not in stopset]
        result.append(" ".join(words))
    return result


def _get_text_hash(text: str) -> str:
    """生成文本的MD5哈希值作为唯一标识"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def _load_embedding_cache(cache_file: Path, logger=None) -> Dict[str, np.ndarray]:
    """
    加载向量缓存（使用安全的JSON+NPY格式，避免pickle反序列化漏洞）
    
    缓存格式：
    - cache_file.json: 存储 {text_hash: index} 映射
    - cache_file.npy: 存储所有向量（按index顺序）
    
    兼容性：如果存在旧的.pkl文件，会自动迁移到新格式
    """
    json_file = cache_file.with_suffix('.json')
    npy_file = cache_file.with_suffix('.npy')
    old_pkl_file = cache_file.with_suffix('.pkl')
    
    # 如果存在旧的pickle文件，尝试迁移
    if old_pkl_file.exists() and (not json_file.exists() or not npy_file.exists()):
        if logger:
            log_success(logger, f"检测到旧格式缓存文件，正在迁移到安全格式...", "TopicBertopic")
        try:
            # 加载旧格式
            with open(old_pkl_file, 'rb') as f:
                old_cache = pickle.load(f)
            
            # 转换为新格式并保存
            if old_cache:
                _save_embedding_cache(old_cache, cache_file, logger)
                if logger:
                    log_success(logger, f"缓存迁移完成，已删除旧文件", "TopicBertopic")
                # 删除旧文件
                old_pkl_file.unlink(missing_ok=True)
        except Exception as e:
            if logger:
                log_error(logger, f"缓存迁移失败: {e}，将使用新格式", "TopicBertopic")
    
    if not json_file.exists() or not npy_file.exists():
        return {}
    
    try:
        # 加载JSON映射
        with open(json_file, 'r', encoding='utf-8') as f:
            hash_to_index = json.load(f)
        
        # 加载向量数组（使用内存映射，节省内存）
        vectors = np.load(npy_file, mmap_mode='r')
        
        # 重建字典
        # 注意：这里将所有向量复制到内存字典中，对于30万条数据会占用约1.2GB内存
        # 如果内存紧张（<16GB），可以考虑延迟加载：只保留hash_to_index映射，
        # 在需要时直接从vectors memmap中按索引读取（需要修改_embed函数的逻辑）
        cache = {}
        for text_hash, idx in hash_to_index.items():
            if 0 <= idx < len(vectors):
                cache[text_hash] = vectors[idx].copy()  # 复制到内存（避免mmap问题）
        
        if logger:
            log_success(logger, f"加载向量缓存: {len(cache)}条已向量化的文本", "TopicBertopic")
        return cache
    except Exception as e:
        if logger:
            log_error(logger, f"加载向量缓存失败: {e}", "TopicBertopic")
        return {}


def _save_embedding_cache(cache: Dict[str, np.ndarray], cache_file: Path, logger=None):
    """
    保存向量缓存（使用安全的JSON+NPY格式，避免pickle反序列化漏洞）
    """
    if not cache:
        return
    
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 设置文件权限：仅当前用户可读写（Unix/Linux）
        if hasattr(os, 'chmod'):
            os.chmod(cache_file.parent, 0o700)
        
        json_file = cache_file.with_suffix('.json')
        npy_file = cache_file.with_suffix('.npy')
        
        # 构建向量数组和索引映射
        vectors = []
        hash_to_index = {}
        
        for idx, (text_hash, vec) in enumerate(cache.items()):
            hash_to_index[text_hash] = idx
            vectors.append(vec)
        
        if vectors:
            vectors_array = np.array(vectors, dtype=np.float32)
            
            # 保存JSON映射
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(hash_to_index, f, ensure_ascii=False)
            
            # 保存向量数组（使用numpy原生格式，安全且快速）
            np.save(npy_file, vectors_array)
            
            # 设置文件权限
            if hasattr(os, 'chmod'):
                os.chmod(json_file, 0o600)
                os.chmod(npy_file, 0o600)
        
        if logger:
            log_success(logger, f"保存向量缓存: {len(cache)}条向量", "TopicBertopic")
    except Exception as e:
        if logger:
            log_error(logger, f"保存向量缓存失败: {e}", "TopicBertopic")


async def _embed_async_batches(
    texts_to_embed: List[Tuple[int, str, str]], api_key: str, base_url: str,
    model: str, dimensions: int, batch_size: int, MAX_INPUT_LENGTH: int,
    cache: Dict[str, np.ndarray], new_vecs_dict: Dict[str, np.ndarray],
    cache_file: Optional[Path], total_batches: int, logger
):
    """
    异步并发处理向量化批次，带指数退避重试机制
    
    优化：
    1. 使用滑动窗口控制并发，避免一次性创建3万个协程导致内存爆炸
    2. 添加指数退避重试，应对429限流
    3. 批量处理，减少内存占用
    """
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    semaphore = asyncio.Semaphore(5)  # 控制并发数量，避免触发API限流
    completed_batches = 0
    lock = asyncio.Lock()
    
    async def process_batch_with_retry(batch_items: List[Tuple[int, str, str]], batch_num: int, max_retries: int = 5):
        """
        处理单个批次，带指数退避重试
        
        Args:
            batch_items: 批次数据
            batch_num: 批次编号
            max_retries: 最大重试次数
        """
        nonlocal completed_batches
        sub = [item[1] for item in batch_items]  # 提取文本
        batch_hashes = [item[2] for item in batch_items]  # 提取哈希值
        
        # 防御性检查
        max_len_in_batch = max(len(t) for t in sub) if sub else 0
        if max_len_in_batch > MAX_INPUT_LENGTH:
            if logger:
                log_error(logger, f"批次{batch_num}中发现超长文本: {max_len_in_batch}字符，已截断", "TopicBertopic")
            sub = [text[:MAX_INPUT_LENGTH] if len(text) > MAX_INPUT_LENGTH else text for text in sub]
        
        # 指数退避重试
        for attempt in range(max_retries):
            try:
                async with semaphore:  # 控制并发数量
                    resp = await client.embeddings.create(
                        model=model, input=sub, dimensions=dimensions, encoding_format="float"
                    )
                    
                    # 保存新向量到缓存和结果字典（需要加锁）
                    async with lock:
                        for j, embedding_item in enumerate(resp.data):
                            text_hash = batch_hashes[j]
                            vec = np.array(embedding_item.embedding, dtype=np.float32)
                            cache[text_hash] = vec
                            new_vecs_dict[text_hash] = vec
                        
                        completed_batches += 1
                        
                        # 【关键优化】：大幅降低自动保存频率（每2000个批次，约1-2万条数据）
                        # 原因：np.save 是全量重写整个数组，频繁保存会导致严重的 I/O 瓶颈
                        # 当缓存积累到20万条（约800MB）时，每次保存都会重写整个文件，耗时数秒到数十秒
                        SAVE_INTERVAL = 2000  # 每2000个批次保存一次
                        
                        if cache_file and completed_batches % SAVE_INTERVAL == 0:
                            if logger:
                                log_success(logger, f"正在执行定期检查点保存（已完成{completed_batches}批次）...", "TopicBertopic")
                            # 注意：_save_embedding_cache 是阻塞 I/O，可能会阻塞几秒到几十秒
                            # 但由于频率已大幅降低，对整体性能影响可接受
                            _save_embedding_cache(cache, cache_file, logger)
                            if logger:
                                progress_pct = (completed_batches / total_batches * 100)
                                log_success(logger, f"检查点保存完成，向量化进度: {completed_batches}/{total_batches}批次 ({progress_pct:.1f}%)", "TopicBertopic")
                        
                        # 进度日志保持高频（每100批次），方便实时监控，不影响性能
                        elif logger and completed_batches % 100 == 0:
                            progress_pct = (completed_batches / total_batches * 100)
                            log_success(logger, f"向量化进度: {completed_batches}/{total_batches}批次 ({progress_pct:.1f}%)", "TopicBertopic")
                    
                    return  # 成功，退出重试循环
                    
            except Exception as e:
                error_str = str(e)
                is_rate_limit = '429' in error_str or 'rate limit' in error_str.lower() or 'too many requests' in error_str.lower()
                
                if attempt < max_retries - 1:
                    # 指数退避：2^attempt 秒
                    wait_time = min(2 ** attempt, 60)  # 最多等待60秒
                    if logger:
                        if is_rate_limit:
                            log_error(logger, f"批次{batch_num}触发限流，{wait_time}秒后重试 (尝试 {attempt+1}/{max_retries})", "TopicBertopic")
                        else:
                            log_error(logger, f"批次{batch_num}失败，{wait_time}秒后重试 (尝试 {attempt+1}/{max_retries}): {type(e).__name__}", "TopicBertopic")
                    await asyncio.sleep(wait_time)
                else:
                    # 最后一次重试失败
                    if logger:
                        max_len = max(len(t) for t in sub) if sub else 0
                        log_error(logger, f"向量化批次{batch_num}最终失败（已重试{max_retries}次）: {e}", "TopicBertopic")
                        log_error(logger, f"批次大小: {len(sub)}, 最大文本长度: {max_len}字符", "TopicBertopic")
                    # 异常时保存已完成的缓存
                    async with lock:
                        if cache_file and cache:
                            _save_embedding_cache(cache, cache_file, logger)
                    raise  # 重试耗尽，抛出异常
    
    # 使用滑动窗口批量处理，避免一次性创建3万个协程导致内存爆炸
    # 每次只处理1000个批次，处理完一批再处理下一批
    window_size = 1000  # 每批处理1000个任务
    all_batches = []
    for i in range(0, len(texts_to_embed), batch_size):
        batch_items = texts_to_embed[i:i + batch_size]
        batch_num = i // batch_size + 1
        all_batches.append((batch_items, batch_num))
    
    # 分批处理，避免内存爆炸
    for window_start in range(0, len(all_batches), window_size):
        window_batches = all_batches[window_start:window_start + window_size]
        tasks = [process_batch_with_retry(batch_items, batch_num) for batch_items, batch_num in window_batches]
        
        # 并发执行当前窗口的批次
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 检查是否有失败的任务
        failed_count = sum(1 for r in results if isinstance(r, Exception))
        if failed_count > 0 and logger:
            log_error(logger, f"窗口 {window_start//window_size + 1} 中有 {failed_count} 个批次失败", "TopicBertopic")


def _embed(batch_texts: List[str], api_key: str, logger=None, base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
           model: str = "text-embedding-v4", dimensions: int = 1024, batch_size: int = 10,
           cache_file: Optional[Path] = None) -> np.ndarray:
    """
    生成文本向量，支持断点续传
    
    Args:
        batch_texts: 文本列表
        api_key: API密钥
        logger: 日志记录器
        base_url: API基础URL
        model: 模型名称
        dimensions: 向量维度
        batch_size: 批次大小
        cache_file: 缓存文件路径（可选）
    
    Returns:
        np.ndarray: 向量数组
    """
    if not batch_texts:
        return np.array([])
    
    # 处理超长文本，保留原始索引
    # API限制是[1, 8192]，但实际可能按token计算，为安全起见截断到8000字符
    MAX_INPUT_LENGTH = 4096
    processed_texts = []
    valid_indices = []
    truncated_count = 0
    
    for idx, text in enumerate(batch_texts):
        if len(text) > MAX_INPUT_LENGTH:
            processed_texts.append(text[:MAX_INPUT_LENGTH])
            valid_indices.append(idx)
            truncated_count += 1
        elif len(text) == 0:
            # 跳过空文本，但记录索引
            continue
        else:
            processed_texts.append(text)
            valid_indices.append(idx)
    
    if truncated_count > 0:
        if logger:
            log_success(logger, f"{truncated_count}条文本因超长被截断", "TopicBertopic")
    
    if not processed_texts:
        return np.array([])
    
    # 加载缓存
    cache = {}
    if cache_file:
        cache = _load_embedding_cache(cache_file, logger)
    
    # 分离需要向量化的文本和已缓存的文本
    texts_to_embed = []
    cached_vecs = {}
    text_hash_to_index = {}  # 哈希值到processed_texts索引的映射
    
    for idx, text in enumerate(processed_texts):
        text_hash = _get_text_hash(text)
        text_hash_to_index[text_hash] = idx
        if text_hash in cache:
            cached_vecs[text_hash] = cache[text_hash]
        else:
            texts_to_embed.append((idx, text, text_hash))
    
    cached_count = len(cached_vecs)
    new_count = len(texts_to_embed)
    
    if logger:
        log_success(logger, f"向量化统计: 缓存命中{cached_count}条，需新向量化{new_count}条", "TopicBertopic")
    
    # 只对未缓存的文本进行向量化
    new_vecs_dict = {}  # 存储新向量化的结果：text_hash -> vec
    if texts_to_embed:
        total_batches = (len(texts_to_embed) + batch_size - 1) // batch_size
        if logger:
            log_success(logger, f"开始生成向量，共{total_batches}个批次，每批{batch_size}条（并发处理）", "TopicBertopic")
        
        # 使用异步并发处理提升速度
        try:
            asyncio.run(_embed_async_batches(
                texts_to_embed, api_key, base_url, model, dimensions, batch_size,
                MAX_INPUT_LENGTH, cache, new_vecs_dict, cache_file, total_batches, logger
            ))
        except KeyboardInterrupt:
            # 手动中断（Ctrl+C）时保存已完成的缓存
            if logger:
                log_error(logger, "向量化被用户中断，正在保存已完成的缓存...", "TopicBertopic")
            if cache_file and cache:
                _save_embedding_cache(cache, cache_file, logger)
                if logger:
                    log_success(logger, f"已保存缓存: {len(cache)}条向量，下次运行将自动续传", "TopicBertopic")
            raise  # 重新抛出异常，让外层处理
        
        # 循环结束后保存最终缓存，确保所有数据都已保存
        if cache_file:
            _save_embedding_cache(cache, cache_file, logger)
    
    # 构建结果向量数组（按processed_texts的顺序）
    # 对于超大数据集（>20万条），使用memmap减少内存占用
    use_memmap = len(processed_texts) > 200000
    if use_memmap and cache_file:
        # 使用临时memmap文件存储向量
        memmap_file = cache_file.with_suffix('.memmap.npy')
        result_vecs = np.memmap(memmap_file, dtype=np.float32, mode='w+', 
                                shape=(len(processed_texts), dimensions))
        if logger:
            log_success(logger, f"使用内存映射文件存储向量（节省内存）: {memmap_file}", "TopicBertopic")
    else:
        result_vecs = np.zeros((len(processed_texts), dimensions), dtype=np.float32)
    
    # 填充所有向量（缓存的和新向量化的）
    for idx, text in enumerate(processed_texts):
        text_hash = _get_text_hash(text)
        if text_hash in cached_vecs:
            result_vecs[idx] = cached_vecs[text_hash]
        elif text_hash in new_vecs_dict:
            result_vecs[idx] = new_vecs_dict[text_hash]
    
    # 如果有空文本，需要调整结果向量的维度
    if len(valid_indices) < len(batch_texts):
        final_vecs = np.zeros((len(batch_texts), dimensions), dtype=np.float32)
        for i, vec_idx in enumerate(valid_indices):
            final_vecs[vec_idx] = result_vecs[i]
        # 清理memmap文件
        if use_memmap and cache_file:
            del result_vecs
            memmap_file.unlink(missing_ok=True)
        return final_vecs
    
    # 如果使用memmap，需要转换为普通数组供BERTopic使用（BERTopic需要内存数组）
    if use_memmap and cache_file:
        # 将memmap转换为普通数组
        result_array = np.array(result_vecs, dtype=np.float32)
        del result_vecs  # 释放memmap
        memmap_file.unlink(missing_ok=True)  # 删除临时文件
        return result_array
    
    return result_vecs


def _build_bertopic() -> BERTopic:
    # 添加 low_memory=True 避免内存溢出（20万条数据需要大量内存）
    umap_model = UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric='cosine', random_state=42)
    hdbscan_model = HDBSCAN(min_cluster_size=15, min_samples=5, metric='euclidean')
    vectorizer_model = CountVectorizer(stop_words=['控烟', '吸烟'])
    return BERTopic(
        nr_topics=30,
        top_n_words=20,
        vectorizer_model=vectorizer_model,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        language="multilingual",
        calculate_probabilities=False,
        verbose=False # 关闭BERTopic的详细日志输出
    )


def _generate_jsons(topic_model: BERTopic, documents: List[str], embeddings: np.ndarray,
                    out_dir: Path, logger) -> Dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    topic_info = topic_model.get_topic_info()
    topics = topic_model.topics_

    umap_2d = UMAP(n_neighbors=15, n_components=2, min_dist=0.0, metric='cosine', random_state=42)
    coords = umap_2d.fit_transform(embeddings)

    # 主题文档统计
    topic_docs: Dict[str, Dict] = {}
    valid_topic_count = 0
    noise_doc_count = 0
    for tid in topic_info['Topic']:
        if tid != -1:
            idxs = [i for i, t in enumerate(topics) if t == tid]
            topic_docs[f"主题{tid}"] = {"文档数": len(idxs), "文档ID": idxs}
            valid_topic_count += 1
        else:
            # 统计噪声主题文档数
            noise_doc_count = len([i for i, t in enumerate(topics) if t == -1])
    
    # 记录初步聚类主题数量
    log_success(logger, f"初步聚类完成: 有效主题数={valid_topic_count}, 噪声文档数={noise_doc_count}", "TopicBertopic")

    # 主题关键词
    topic_keywords: Dict[str, Dict] = {}
    for tid in topic_info['Topic']:
        if tid != -1:
            kws = topic_model.get_topic(tid)
            top20 = kws[:20] if len(kws) >= 20 else kws
            topic_keywords[f"主题{tid}"] = {"关键词": [[w, float(s)] for w, s in top20]}

    # 文档2D坐标
    doc_coords = [
        {"doc_id": i, "topic_id": int(topics[i]), "x": float(coords[i][0]), "y": float(coords[i][1])}
        for i in range(len(documents))
    ]

    stats_result = {
        "主题文档统计": topic_docs,
        "主题关键词": topic_keywords,
        "文档2D坐标": doc_coords,
    }

    p1 = out_dir / "1主题统计结果.json"
    p2 = out_dir / "2主题关键词.json"
    p3 = out_dir / "3文档2D坐标.json"
    p1.write_text(json.dumps(stats_result, ensure_ascii=False, indent=2), encoding="utf-8")
    p2.write_text(json.dumps(topic_keywords, ensure_ascii=False, indent=2), encoding="utf-8")
    p3.write_text(json.dumps(doc_coords, ensure_ascii=False, indent=2), encoding="utf-8")

    return stats_result


async def _call_llm_recluster(topic_stats: Dict, topic: str, logger) -> Optional[Dict]:
    """调用大模型进行主题合并"""
    try:
        client = OpenAI(api_key=get_api_key(), base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        
        # 控制输入规模：保留所有主题，每个主题前 10 个关键词
        input_data = {"主题信息": {}}
        max_keywords = 10
        for topic_key, topic_info in topic_stats["主题文档统计"].items():
            keywords = topic_stats["主题关键词"][topic_key]["关键词"][:max_keywords]
            input_data["主题信息"][topic_key] = {
                "文档数": topic_info["文档数"],
                "关键词": keywords
            }
        
        # 加载提示词配置：根据主题动态加载对应的yaml文件
        prompt_config = _load_prompt(f"topic_bertopic/{topic}.yaml", "topic_bertopic_recluster", logger)
        if not prompt_config:
            log_error(logger, "无法加载再聚类提示词，使用默认提示词", "TopicBertopic")
            prompt_config = {
                'system': '你是一个专业的控烟领域主题分析专家，擅长将相似的控烟相关主题进行归纳和合并，并对其进行命名。',
                'user': f"""分析以下控烟相关主题，将语义相似的主题合并为{TARGET_TOPICS}个左右的主题。\n\n输入数据：\n{{input_data}}\n\n请直接输出JSON，不要其他内容。"""
            }
        
        # 格式化提示词并做防御性截断
        user_prompt = prompt_config['user'].format(
            TARGET_TOPICS=TARGET_TOPICS,
            input_data=json.dumps(input_data, ensure_ascii=False, indent=2)
        )
        # 进一步收紧，留出 system+元数据空间，避免 8192 上限
        max_prompt_len = 7000
        if len(user_prompt) > max_prompt_len:
            user_prompt = user_prompt[:max_prompt_len]
        
        response = client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": prompt_config['system']},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            max_tokens=4000
        )
        
        result_text = response.choices[0].message.content.strip()
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()
        result_text = result_text.strip()
        
        try:
            merge_result = json.loads(result_text)
            log_success(logger, "大模型合并建议获取成功", "TopicBertopic")
            return merge_result
        except json.JSONDecodeError as e:
            # 兜底：尝试提取首尾花括号内的 JSON 片段再解析
            fallback_text = None
            try:
                m = re.search(r'\{.*\}', result_text, re.S)
                if m:
                    fallback_text = m.group(0).strip()
                    merge_result = json.loads(fallback_text)
                    log_success(logger, "大模型合并建议获取成功（fallback JSON 解析）", "TopicBertopic")
                    return merge_result
            except Exception:
                pass
            
            log_error(logger, f"JSON解析失败: {e}", "TopicBertopic")
            log_error(logger, f"响应长度: {len(result_text)}, 前200字符: {result_text[:200]}", "TopicBertopic")
            if fallback_text:
                log_error(logger, f"fallback 片段长度: {len(fallback_text)}, 前200字符: {fallback_text[:200]}", "TopicBertopic")
            return None
        
    except Exception as e:
        log_error(logger, f"大模型再聚类调用失败: {e}", "TopicBertopic")
        import traceback
        log_error(logger, f"完整堆栈: {traceback.format_exc()}", "TopicBertopic")
        return None


def _calculate_reclustered_keywords(topic_stats: Dict, merge_result: Dict, naming_results: Dict) -> Dict:
    """根据合并方案重新计算关键词权重"""
    reclustered_topics = {}
    
    for merge_group in merge_result["合并方案"]:
        new_topic_name = merge_group["新主题名称"]
        topic_naming = naming_results.get(new_topic_name, f"主题{len(reclustered_topics)}")
        original_topics = merge_group["原始主题集合"]
        topic_description = merge_group["主题描述"]
        
        if not re.match(r'^新主题\d+$', new_topic_name):
            new_topic_name = f"新主题{len(reclustered_topics)}"
        
        all_doc_ids = []
        keyword_weights = defaultdict(float)
        total_original_docs = 0
        
        for original_topic in original_topics:
            if original_topic in topic_stats["主题文档统计"]:
                doc_count = topic_stats["主题文档统计"][original_topic]["文档数"]
                doc_ids = topic_stats["主题文档统计"][original_topic]["文档ID"]
                keywords = topic_stats["主题关键词"][original_topic]["关键词"]
                
                all_doc_ids.extend(doc_ids)
                total_original_docs += doc_count
                
                for keyword, weight in keywords:
                    keyword_weights[keyword] += weight * doc_count
        
        new_doc_count = len(all_doc_ids)
        if new_doc_count == 0:
            continue
        
        recalculated_keywords = []
        for keyword, total_weight in keyword_weights.items():
            if total_original_docs > 0:
                new_weight = (total_weight / total_original_docs) * (total_original_docs / new_doc_count)
                recalculated_keywords.append([keyword, new_weight])
        
        recalculated_keywords.sort(key=lambda x: x[1], reverse=True)
        top_20_keywords = recalculated_keywords[:20]
        
        reclustered_topics[new_topic_name] = {
            "主题命名": topic_naming,
            "原始主题集合": original_topics,
            "文档数": new_doc_count,
            "主题描述": topic_description,
            "文档ID": all_doc_ids,
            "关键词": top_20_keywords
        }
    
    return reclustered_topics


async def _generate_reclustered_json(topic_stats: Dict, topic: str, out_dir: Path, logger) -> Optional[Dict]:
    """生成大模型再聚类结果JSON"""
    merge_result = await _call_llm_recluster(topic_stats, topic, logger)
    if not merge_result:
        log_error(logger, "无法获取大模型合并建议", "TopicBertopic")
        return None
    
    naming_results = {}
    for merge_group in merge_result["合并方案"]:
        new_topic_name = merge_group["新主题名称"]
        topic_naming = merge_group.get("主题命名", "")
        if topic_naming:
            naming_results[new_topic_name] = topic_naming
    
    reclustered_topics = _calculate_reclustered_keywords(topic_stats, merge_result, naming_results)
    
    final_result = {}
    reclustered_keywords_data = {}
    
    for topic_name, topic_info in reclustered_topics.items():
        if topic_info["文档数"] == 0:
            continue
        
        final_result[topic_name] = {
            "主题命名": topic_info["主题命名"],
            "原始主题集合": topic_info["原始主题集合"],
            "文档数": topic_info["文档数"],
            "主题描述": topic_info["主题描述"],
            "文档ID": topic_info["文档ID"],
            "关键词": topic_info["关键词"]
        }
        
        reclustered_keywords_data[topic_name] = {
            "主题命名": topic_info["主题命名"],
            "关键词": topic_info["关键词"]
        }
    
    # 保存JSON文件
    p4 = out_dir / "4大模型再聚类结果.json"
    p5 = out_dir / "5大模型主题关键词.json"
    p4.write_text(json.dumps(final_result, ensure_ascii=False, indent=2), encoding="utf-8")
    p5.write_text(json.dumps(reclustered_keywords_data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    return final_result


def _load_prompt(file_path: str, prompt_key: str, logger) -> Optional[Dict[str, str]]:
    """加载提示词配置"""
    try:
        project_root = get_project_root()
        prompt_file = project_root / "configs" / "prompt" / file_path
        
        if not prompt_file.exists():
            log_error(logger, f"未找到提示词文件: {prompt_file}", "TopicBertopic")
            return None
        
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_config = yaml.safe_load(f)
        
        if 'prompts' not in prompt_config:
            log_error(logger, "提示词文件格式错误，缺少prompts字段", "TopicBertopic")
            return None
        
        prompts = prompt_config['prompts']
        if prompt_key not in prompts:
            log_error(logger, f"未找到{prompt_key}的提示词配置", "TopicBertopic")
            return None
        
        return prompts[prompt_key]
        
    except Exception as e:
        log_error(logger, f"加载提示词失败: {e}", "TopicBertopic")
        return None


def run_topic_bertopic(topic: str, start_date: str, end_date: str = None,
                       fetch_dir: Optional[str] = None,
                       userdict: Optional[str] = None, stopwords: Optional[str] = None) -> bool:
    # 使用日期范围格式作为日志标识
    date_range = f"{start_date}_{end_date}" if end_date else start_date
    logger = setup_logger(topic, date_range)
    log_module_start(logger, "TopicBertopic")

    paths = _default_paths(topic, start_date, end_date)
    fetch_path = Path(fetch_dir) if fetch_dir else paths["fetch_dir"]
    userdict_path = Path(userdict) if userdict else paths["userdict"]
    stopwords_path = Path(stopwords) if stopwords else paths["stopwords"]
    out_analyze = paths["out_analyze"]

    try:
        # 从fetch目录读取并合并所有CSV文件（与analyze模块一致）
        df = _load_and_merge_fetch_data(fetch_path, logger)
        if df.empty:
            log_error(logger, "未读取到任何数据", "TopicBertopic")
            return False

        # 查找contents列
        text_col = None
        for c in df.columns:
            if 'contents' in str(c).lower():
                text_col = c
                break
        if not text_col:
            log_error(logger, "CSV中未找到包含'contents'的列", "TopicBertopic")
            return False
        texts = [str(x) for x in df[text_col].tolist() if str(x).strip() and str(x).lower() not in ['nan','none','']]

        # 清洗
        cleaned, stats = _clean_batch(texts)

        # 分词
        sw = _load_stopwords(stopwords_path)
        seg = _segment(cleaned, sw, userdict_path)

        # 向量化（支持断点续传）
        load_env_file()  # 确保.env文件被加载
        api_key = get_api_key()
        if not api_key:
            log_error(logger, "未配置API密钥，请在.env文件中设置DASHSCOPE_API_KEY", "TopicBertopic")
            return False
        
        # 设置缓存文件路径
        cache_file = out_analyze / "embedding_cache.pkl"
        
        log_success(logger, f"开始向量化，文本数量: {len(seg)}", "TopicBertopic")
        vecs = _embed(seg, api_key, logger, cache_file=cache_file)
        if vecs.size == 0:
            log_error(logger, "向量化失败", "TopicBertopic")
            return False
        log_success(logger, f"向量化完成，向量维度: {vecs.shape}", "TopicBertopic")

        # 主题建模
        log_success(logger, "开始主题建模", "TopicBertopic")
        try:
            model = _build_bertopic()
            model.fit_transform(seg, embeddings=vecs)
            log_success(logger, "主题建模完成", "TopicBertopic")
        except Exception as e:
            log_error(logger, f"主题建模失败: {e}", "TopicBertopic")
            raise

        # 生成3个JSON
        log_success(logger, "开始生成初步聚类结果", "TopicBertopic")
        stats_json = _generate_jsons(model, seg, vecs, out_analyze, logger)

        # 大模型再聚类，生成第4、5个JSON
        import asyncio
        asyncio.run(_generate_reclustered_json(stats_json, topic, out_analyze, logger))

        log_success(logger, "主题分析完成", "TopicBertopic")
        return True
    except Exception as e:
        log_error(logger, f"异常: {e}", "TopicBertopic")
        return False


