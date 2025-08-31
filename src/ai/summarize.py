"""
AI解读模块
"""
import json
import asyncio
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from ..utils.paths import bucket
from ..utils.logging import setup_logger, log_module_start, log_success, log_error, log_save_success
from ..utils.settings import settings
from .qwen import get_qwen_client

class AIExplainer:
    """AI解读器"""
    
    def __init__(self, logger=None):
        self.logger = logger
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """
        初始化AI客户端
        """
        try:
            # 使用项目中已有的千问客户端
            self.client = get_qwen_client()
            self.logger.info("AI客户端初始化成功")
        except Exception as e:
            self.logger.error(f"AI客户端初始化失败: {e}")
    
    async def explain_analysis(self, prompt: str, model: str = "qwen-plus") -> Optional[str]:
        """
        调用AI模型进行解读
        
        Args:
            prompt (str): 提示词
            model (str, optional): 模型名称（保持兼容性，实际使用客户端配置），默认"qwen-plus"
        
        Returns:
            str: 解读结果
        """
        if not self.client:
            self.logger.error("AI客户端未初始化")
            return None
        
        try:
            # 使用千问客户端的API调用方法，增加max_tokens到4096，并启用联网搜索
            self.logger.info("正在调用AI模型（已启用联网搜索，将搜索最新控烟新闻）...")
            response = await self.client._call_api(prompt, max_tokens=4096, enable_search=True)
            if response:
                self.logger.info("AI模型调用成功，联网搜索已启用")
            return response
        except Exception as e:
            self.logger.error(f"AI模型调用失败: {e}")
            return None

async def run_explain_sync(topic: str, date: str, logger=None) -> bool:
    """
    运行AI解读（异步版本）
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    if logger is None:
        logger = setup_logger(topic, date)
    
    log_module_start(logger, "AI解读")
    
    # 初始化AI解读器
    explainer = AIExplainer(logger)
    
    # 读取分析结果目录
    processed_dir = bucket("processed", topic, date)
    if not processed_dir.exists():
        logger.error(f"未找到分析结果目录: {processed_dir}")
        return False
    
    # 获取提示词配置
    prompts_config = settings.get_prompts_config()
    explain_prompts = prompts_config.get('explain', {})
    
    if not explain_prompts:
        logger.error("未配置解读提示词")
        return False
    
    # 获取LLM配置
    llm_config = settings.get('summary_llm', {})
    model = llm_config.get('model', 'qwen-plus')
    concurrency = llm_config.get('concurrency', 5)
    
    logger.info(f"使用模型: {model}, 并发数: {concurrency}")
    
    # 收集需要解读的文件
    analysis_files = []
    
    # 遍历八大功能目录
    for func_dir in processed_dir.iterdir():
        if not func_dir.is_dir() or func_dir.name.startswith('_'):
            continue
        
        func_name = func_dir.name
        
        # 检查总体目录
        overall_dir = func_dir / '总体'
        if overall_dir.exists():
            result_file = overall_dir / 'result.json'
            if result_file.exists():
                # 检查文件内容是否为空
                try:
                    with open(result_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    if content and content != '{}' and content != '[]':
                        analysis_files.append({
                            'func_name': func_name,
                            'file_path': result_file,
                            'type': '总体'
                        })
                    else:
                        logger.info(f"⏭️  跳过空文件: {func_name}")
                except Exception as e:
                    logger.info(f"⏭️  跳过无效文件: {func_name}")
        
        # 检查各渠道目录
        for channel_dir in func_dir.iterdir():
            if channel_dir.is_dir() and channel_dir.name != '总体':
                result_file = channel_dir / 'result.json'
                if result_file.exists():
                    # 检查文件内容是否为空
                    try:
                        with open(result_file, 'r', encoding='utf-8') as f:
                            content = f.read().strip()
                        if content and content != '{}' and content != '[]':
                            analysis_files.append({
                                'func_name': func_name,
                                'file_path': result_file,
                                'type': channel_dir.name
                            })
                        else:
                            logger.info(f"⏭️  跳过空文件: {func_name}_{channel_dir.name}")
                    except Exception as e:
                        logger.info(f"⏭️  跳过无效文件: {func_name}_{channel_dir.name}")
    
    if not analysis_files:
        log_error(logger, "未找到任何有效的分析结果文件")
        return False
    
    logger.info(f"📁 找到 {len(analysis_files)} 个分析文件")
    
    # 创建报告根目录
    report_root_dir = bucket("reports", topic, date)
    report_root_dir.mkdir(parents=True, exist_ok=True)
    
    # 使用信号量严格控制并发数
    semaphore = asyncio.Semaphore(concurrency)
    
    # 创建异步任务
    async def process_single_analysis(analysis_file: Dict) -> bool:
        """
        处理单个分析文件
        
        Args:
            analysis_file (Dict): 分析文件信息
        
        Returns:
            bool: 是否成功
        """
        async with semaphore:
            return await _process_single_analysis_async(explainer, analysis_file, explain_prompts, model, report_root_dir, logger)
    
    # 分批处理，确保不超过并发限制
    batch_size = concurrency
    success_count = 0
    failed_count = 0
    
    async def process_batch():
        nonlocal success_count, failed_count
        for i in range(0, len(analysis_files), batch_size):
            batch = analysis_files[i:i + batch_size]
            logger.info(f"📦 批次 {i//batch_size + 1}/{(len(analysis_files) + batch_size - 1)//batch_size}")
            
            # 并发执行当前批次
            tasks = [process_single_analysis(analysis_file) for analysis_file in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 统计当前批次结果
            for j, result in enumerate(results):
                analysis_file = batch[j]
                if isinstance(result, Exception):
                    failed_count += 1
                    log_error(logger, f"{analysis_file['func_name']}_{analysis_file['type']}: {result}")
                elif result:
                    success_count += 1
                    log_success(logger, f"{analysis_file['func_name']}_{analysis_file['type']}")
                else:
                    failed_count += 1
                    logger.info(f"⚠️  {analysis_file['func_name']}_{analysis_file['type']}")
    
    # 运行异步代码
    await process_batch()
    
    log_success(logger, f"AI解读完成 ({success_count}/{len(analysis_files)})")
    return success_count > 0

async def _process_single_analysis_async(explainer: AIExplainer, analysis_file: Dict, 
                                       explain_prompts: Dict, model: str, report_root_dir: Path, logger) -> bool:
    """
    异步处理单个分析文件
    
    Args:
        explainer (AIExplainer): AI解读器
        analysis_file (Dict): 分析文件信息
        explain_prompts (Dict): 提示词配置
        model (str): 模型名称
        report_root_dir (Path): 报告目录
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    try:
        func_name = analysis_file['func_name']
        file_path = analysis_file['file_path']
        analysis_type = analysis_file['type']
        
        # 读取JSON数据
        with open(file_path, 'r', encoding='utf-8') as f:
            analysis_data = json.load(f)
        
        # 检查数据是否为空
        if not analysis_data or (isinstance(analysis_data, dict) and not analysis_data) or (isinstance(analysis_data, list) and not analysis_data):
            logger.warning(f"分析数据为空: {func_name}_{analysis_type}")
            return False
        
        # 获取对应的提示词（忽略大小写）
        func_name_lower = func_name.lower()
        if func_name_lower in explain_prompts:
            prompt_template = explain_prompts[func_name_lower]
            
            # 使用配置中的提示词模板
            prompt = prompt_template.format(json=json.dumps(analysis_data, ensure_ascii=False))
            
            # 调用AI解读
            response = await explainer.explain_analysis(prompt, model)
            
            if response and response.strip():
                # 创建与processed一致的目录结构
                func_dir = report_root_dir / func_name
                func_dir.mkdir(exist_ok=True)
                
                if analysis_type == '总体':
                    target_dir = func_dir / '总体'
                    filename = '解读.txt'
                else:
                    target_dir = func_dir / analysis_type
                    filename = '解读.txt'
                
                target_dir.mkdir(exist_ok=True)
                
                # 保存到对应的目录
                report_file = target_dir / filename
                with open(report_file, 'w', encoding='utf-8') as f:
                    f.write(response)
                
                logger.info(f"解读结果已保存: {report_file}, 字数: {len(response)}")
                return True
            else:
                logger.warning(f"AI解读失败或结果为空: {func_name}_{analysis_type}")
                return False
        else:
            logger.warning(f"未找到提示词: {func_name} (尝试: {func_name_lower})")
            return False
            
    except Exception as e:
        logger.error(f"处理分析文件失败: {e}")
        return False

async def run_explain(topic: str, date: str, logger=None) -> bool:
    """
    运行AI解读（异步版本，保持兼容性）
    
    Args:
        topic (str): 专题名称
        date (str): 日期字符串
        logger: 日志记录器
    
    Returns:
        bool: 是否成功
    """
    return await run_explain_sync(topic, date, logger)
