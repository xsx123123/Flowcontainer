"""
Flowcontainer 配置管理模块
"""
import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field, asdict


@dataclass
class RegistryConfig:
    """Registry 配置"""
    url: str = ""
    username: Optional[str] = None
    password: Optional[str] = None
    insecure: bool = False  # 是否允许 http (非 https)
    
    
@dataclass
class BuildConfig:
    """构建配置"""
    default_registry: str = ""  # 默认推送仓库地址
    default_tag_prefix: str = "flowcontainer"
    default_version: str = "latest"
    template_file: Optional[str] = None
    no_cache: bool = False
    parallel: int = 1  # 并行构建数
    

@dataclass
class LogConfig:
    """日志配置"""
    level: str = "INFO"
    file_level: str = "DEBUG"
    log_dir: str = "logs"
    retention_days: int = 7


@dataclass
class FlowcontainerConfig:
    """Flowcontainer 主配置"""
    version: str = "1.0.0"
    build: BuildConfig = field(default_factory=BuildConfig)
    registry: RegistryConfig = field(default_factory=RegistryConfig)
    log: LogConfig = field(default_factory=LogConfig)
    
    # 额外的自定义配置
    extra: Dict[str, Any] = field(default_factory=dict)


class ConfigManager:
    """配置管理器"""
    
    DEFAULT_CONFIG_FILE = "Flowcontainer.yaml"
    
    # 搜索路径顺序
    CONFIG_SEARCH_PATHS = [
        Path.cwd() / DEFAULT_CONFIG_FILE,  # 当前目录
        Path.home() / ".config" / "flowcontainer" / DEFAULT_CONFIG_FILE,  # 用户配置
        Path("/etc/flowcontainer") / DEFAULT_CONFIG_FILE,  # 系统配置
    ]
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config = FlowcontainerConfig()
        self.config_file: Optional[Path] = None
        
        if config_path:
            self.load_config(config_path)
        else:
            self._auto_load_config()
    
    def _auto_load_config(self):
        """自动搜索并加载配置"""
        for path in self.CONFIG_SEARCH_PATHS:
            if path.exists():
                self.load_config(path)
                return
    
    def load_config(self, path: Path) -> "ConfigManager":
        """从文件加载配置"""
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        
        self._update_config(data)
        self.config_file = path
        return self
    
    def _update_config(self, data: Dict[str, Any]):
        """更新配置对象"""
        # 更新构建配置
        if 'build' in data:
            build_data = data['build']
            for key, value in build_data.items():
                if hasattr(self.config.build, key):
                    setattr(self.config.build, key, value)
        
        # 更新 Registry 配置
        if 'registry' in data:
            reg_data = data['registry']
            for key, value in reg_data.items():
                if hasattr(self.config.registry, key):
                    setattr(self.config.registry, key, value)
        
        # 更新日志配置
        if 'log' in data:
            log_data = data['log']
            for key, value in log_data.items():
                if hasattr(self.config.log, key):
                    setattr(self.config.log, key, value)
        
        # 更新版本
        if 'version' in data:
            self.config.version = data['version']
        
        # 保存额外配置
        self.config.extra = data.get('extra', {})
    
    def save_config(self, path: Optional[Path] = None):
        """保存配置到文件"""
        save_path = path or self.config_file or self.CONFIG_SEARCH_PATHS[0]
        
        # 确保目录存在
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 转换为字典
        data = {
            'version': self.config.version,
            'build': asdict(self.config.build),
            'registry': asdict(self.config.registry),
            'log': asdict(self.config.log),
        }
        
        if self.config.extra:
            data['extra'] = self.config.extra
        
        with open(save_path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    def create_default_config(self, path: Optional[Path] = None) -> Path:
        """创建默认配置文件"""
        save_path = path or self.CONFIG_SEARCH_PATHS[0]
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        default_content = """# Flowcontainer 配置文件
# 容器镜像构建工具配置

version: "1.0.0"

# 构建配置
build:
  # 默认推送仓库地址 (为空表示不推送)
  # 示例: registry.example.com/ 或 docker.io/username/
  default_registry: ""
  
  # 默认镜像标签前缀
  default_tag_prefix: "flowcontainer"
  
  # 默认版本号
  default_version: "latest"
  
  # 默认是否不使用缓存
  no_cache: false
  
  # 并行构建数 (1表示串行)
  parallel: 1

# Registry 配置
registry:
  # Registry URL
  url: ""
  
  # 用户名 (可选，留空则使用 docker login 的凭证)
  username: null
  
  # 密码 (可选，建议使用 docker login 而不是明文存储)
  password: null
  
  # 是否允许 insecure (http) 连接
  insecure: false

# 日志配置
log:
  # 控制台日志级别: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL
  level: "INFO"
  
  # 文件日志级别
  file_level: "DEBUG"
  
  # 日志目录
  log_dir: "logs"
  
  # 日志保留天数
  retention_days: 7

# 额外自定义配置
extra: {}
"""
        
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(default_content)
        
        return save_path
    
    def get_full_registry_url(self) -> str:
        """获取完整的 registry URL"""
        # 优先使用 build.default_registry
        if self.config.build.default_registry:
            return self.config.build.default_registry
        # 其次使用 registry.url
        if self.config.registry.url:
            return self.config.registry.url
        return ""
    
    @property
    def log_dir(self) -> Path:
        """获取日志目录"""
        return Path(self.config.log.log_dir)


# 全局配置实例
_global_config: Optional[ConfigManager] = None


def get_config(config_path: Optional[Path] = None) -> ConfigManager:
    """获取全局配置实例"""
    global _global_config
    if _global_config is None or config_path:
        _global_config = ConfigManager(config_path)
    return _global_config


def reset_config():
    """重置全局配置"""
    global _global_config
    _global_config = None
