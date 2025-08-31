"""
项目配置管理模块
"""
import os
import yaml
from pathlib import Path
from typing import Any, Dict, List
from .paths import get_configs_root, get_project_root


class Settings:
    """项目配置管理类"""
    
    def __init__(self):
        """
        初始化配置管理器
        """
        self.configs = {}
        self._load_configs()
    
    def _load_configs(self):
        """
        加载所有配置文件
        """
        # 优先使用环境变量指定的配置目录
        config_dir = get_configs_root()
        
        if not config_dir.exists():
            print(f"⚠️  警告: 配置目录不存在: {config_dir}")
            # 尝试创建配置目录
            config_dir.mkdir(parents=True, exist_ok=True)
            print(f"✅ 已创建配置目录: {config_dir}")
        
        # 加载YAML配置文件
        yaml_files = list(config_dir.glob("*.yaml"))
        if not yaml_files:
            print(f"⚠️  警告: 在 {config_dir} 中未找到任何YAML配置文件")
        
        for config_file in yaml_files:
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    self.configs[config_file.stem] = yaml.safe_load(f)
                print(f"✅ 已加载配置: {config_file.name}")
            except Exception as e:
                print(f"❌ 加载配置文件失败 {config_file.name}: {e}")
        
        # 加载环境变量配置
        self.configs['env'] = {}
        for key, value in os.environ.items():
            if key.startswith('OPINION_'):
                self.configs['env'][key] = value
        
        # 添加项目路径信息
        project_root = get_project_root()
        self.configs['paths'] = {
            'project_root': str(project_root),
            'configs_dir': str(get_configs_root()),
            'data_dir': str(project_root / 'data'),
            'logs_dir': str(project_root / 'logs'),
            'templates_dir': str(project_root / 'templates')
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值，支持点号分隔的嵌套键
        
        Args:
            key (str): 配置键，支持点号分隔如 'defaults.db_url'
            default (Any): 默认值
        
        Returns:
            Any: 配置值
        """
        keys = key.split('.')
        value = self.configs
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_channel_config(self) -> Dict[str, Any]:
        """
        获取渠道配置
        
        Returns:
            Dict[str, Any]: 渠道配置
        """
        return self.configs.get('channels', {})
    
    def get_analysis_config(self) -> Dict[str, Any]:
        """
        获取分析配置
        
        Returns:
            Dict[str, Any]: 分析配置
        """
        return self.configs.get('analysis', {})
    
    def get_prompts_config(self) -> Dict[str, Any]:
        """
        获取提示词配置
        
        Returns:
            Dict[str, Any]: 提示词配置
        """
        return self.configs.get('prompts', {})
    
    def get_llm_config(self) -> Dict[str, Any]:
        """
        获取LLM配置
        
        Returns:
            Dict[str, Any]: LLM配置
        """
        return self.configs.get('llm', {})
    
    def get_project_paths(self) -> Dict[str, str]:
        """
        获取项目路径信息
        
        Returns:
            Dict[str, str]: 项目路径字典
        """
        return self.configs.get('paths', {})
    
    def reload_configs(self):
        """
        重新加载配置文件
        """
        print("🔄 重新加载配置文件...")
        self.configs.clear()
        self._load_configs()
        print("✅ 配置文件重新加载完成")
    
    def validate_configs(self) -> bool:
        """
        验证配置完整性
        
        Returns:
            bool: 配置是否完整
        """
        required_configs = ['channels', 'analysis', 'prompts']
        missing_configs = []
        
        for config_name in required_configs:
            if config_name not in self.configs:
                missing_configs.append(config_name)
        
        if missing_configs:
            print(f"❌ 缺少必要的配置文件: {', '.join(missing_configs)}")
            return False
        
        print("✅ 所有必要的配置文件都已加载")
        return True
    
    def print_config_summary(self):
        """
        打印配置摘要
        """
        print("📋 配置摘要:")
        print(f"   项目根目录: {self.get('paths.project_root', '未设置')}")
        print(f"   配置目录: {self.get('paths.configs_dir', '未设置')}")
        print(f"   数据目录: {self.get('paths.data_dir', '未设置')}")
        print(f"   日志目录: {self.get('paths.logs_dir', '未设置')}")
        print(f"   模板目录: {self.get('paths.templates_dir', '未设置')}")
        
        # 统计配置信息
        yaml_configs = [k for k in self.configs.keys() if k not in ['env', 'paths']]
        env_configs = [k for k in self.configs.get('env', {}).keys()]
        
        print(f"   已加载配置: {', '.join(yaml_configs)}")
        print(f"   环境变量: {len(env_configs)} 个")


# 全局配置实例
settings = Settings()
