"""
千问API调用模块
"""
import asyncio
import time
import json
import os
from typing import List, Dict, Any, Optional
from dashscope import Generation
from ..utils.settings import settings
from ..utils.logging import setup_logger
from ..utils.env_loader import get_api_key

class QwenClient:
    """千问API客户端"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化千问客户端
        
        Args:
            api_key (Optional[str]): API密钥，如果为None则从配置读取
        
        Raises:
            ValueError: 当API密钥未配置时抛出
        """
        # 使用新的环境变量加载器获取API密钥
        self.api_key = api_key or get_api_key()
        self.model = settings.get('llm.model', 'qwen-plus')
        # 使用配置文件中的QPS设置
        self.qps = settings.get('defaults.analysis_llm.qps', 10)
        self.concurrency = settings.get('llm.concurrency', 50)
        self.semaphore = asyncio.Semaphore(self.concurrency)
        self.last_request_time = 0
        
        if not self.api_key:
            raise ValueError("千问API密钥未配置，请设置环境变量 DASHSCOPE_API_KEY 或编辑 .env 文件")
    
    async def _rate_limit(self):
        """
        速率限制，确保不超过QPS限制
        """
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        min_interval = 1.0 / self.qps
        
        if time_since_last < min_interval:
            await asyncio.sleep(min_interval - time_since_last)
        
        self.last_request_time = time.time()
    
    async def _call_api(self, prompt: str, max_tokens: int = 512, enable_search: bool = False) -> Optional[str]:
        """
        调用千问API
        
        Args:
            prompt (str): 提示词
            max_tokens (int, optional): 最大token数，默认512
            enable_search (bool, optional): 是否启用联网搜索，默认False
        
        Returns:
            Optional[str]: API响应内容，失败时返回None
        """
        async with self.semaphore:
            await self._rate_limit()
            
            try:
                # 使用run_in_executor将同步调用包装为异步
                loop = asyncio.get_event_loop()
                # 根据enable_search参数决定是否启用联网搜索
                if enable_search:
                    response = await loop.run_in_executor(
                        None, 
                        lambda: Generation.call(
                            model=self.model,
                            prompt=prompt,
                            max_tokens=max_tokens,
                            api_key=self.api_key,
                            extra_body={"enable_search": True}
                        )
                    )
                else:
                    response = await loop.run_in_executor(
                        None, 
                        lambda: Generation.call(
                            model=self.model,
                            prompt=prompt,
                            max_tokens=max_tokens,
                            api_key=self.api_key
                        )
                    )
                
                if response.status_code == 200:
                    return response.output.text
                elif "quota" in response.message.lower() or "quota" in str(response).lower():
                            # 配额超限，建议检查API配额、等待配额重置或升级套餐
                    return None
                else:
                    return None
                    
            except Exception as e:
                return None
    
    async def batch_call(self, prompts: List[str], max_tokens: int = 512) -> List[Optional[str]]:
        """
        批量调用API
        
        Args:
            prompts (List[str]): 提示词列表
            max_tokens (int, optional): 最大token数，默认512
        
        Returns:
            List[Optional[str]]: 响应列表，失败的请求返回None
        """
        tasks = [self._call_api(prompt, max_tokens) for prompt in prompts]
        results = await asyncio.gather(tasks, return_exceptions=True)
        
        # 处理异常
        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                processed_results.append(None)
            else:
                processed_results.append(result)
        
        return processed_results
    
    def call_sync(self, prompt: str, max_tokens: int = 512) -> Optional[str]:
        """
        同步调用API（用于非异步环境）
        
        Args:
            prompt (str): 提示词
            max_tokens (int, optional): 最大token数，默认512
        
        Returns:
            Optional[str]: API响应内容，失败时返回None
        """
        try:
            response = Generation.call(
                model=self.model,
                prompt=prompt,
                max_tokens=max_tokens,
                api_key=self.api_key
            )
            
            if response.status_code == 200:
                return response.output.text
            else:
                return None
                
        except Exception as e:
            return None

# 全局千问客户端实例（延迟初始化）
_qwen_client = None

def get_qwen_client() -> QwenClient:
    """
    获取千问客户端实例（延迟初始化）
    
    Returns:
        QwenClient: 千问客户端实例
    """
    global _qwen_client
    if _qwen_client is None:
        _qwen_client = QwenClient()
    return _qwen_client
