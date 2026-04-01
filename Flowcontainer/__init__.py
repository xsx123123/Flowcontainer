"""
Flowcontainer - 生物信息学工作流容器镜像构建工具

Usage:
    from flowcontainer import ImageBuilder, ConfigManager
    
    config = ConfigManager()
    builder = ImageBuilder(config)
    result = builder.build(
        env_file="envs/rsem.yaml",
        tag="rnaflow-rsem:0.1"
    )
"""

__version__ = "1.0.0"
__author__ = "Flowcontainer Team"

from .builder import ImageBuilder, ImageBuildResult
from .config import ConfigManager, FlowcontainerConfig
from .docker_client import DockerClient, RegistryChecker

__all__ = [
    "ImageBuilder",
    "ImageBuildResult",
    "ConfigManager",
    "FlowcontainerConfig",
    "DockerClient",
    "RegistryChecker",
]
