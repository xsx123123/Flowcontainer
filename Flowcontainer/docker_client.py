"""
Docker SDK 客户端封装
提供 Docker 操作的高级接口
"""
import os
import sys
import time
import socket
import urllib.parse
from typing import Optional, Dict, List, Generator, Tuple, Callable
from pathlib import Path

import docker
from docker.errors import (
    DockerException,
    ImageNotFound,
    APIError,
    BuildError,
)
from loguru import logger


class RegistryChecker:
    """Registry 连通性检查器"""
    
    DEFAULT_TIMEOUT = 5  # 默认超时秒数
    
    @staticmethod
    def check_registry(registry_url: str, insecure: bool = False, timeout: int = DEFAULT_TIMEOUT) -> Tuple[bool, str]:
        """
        检查 Registry 是否可连通
        
        Args:
            registry_url: Registry URL (例如: registry.example.com 或 docker.io)
            insecure: 是否允许 http
            timeout: 超时时间
            
        Returns:
            (是否成功, 消息)
        """
        if not registry_url:
            return False, "Registry URL 为空"
        
        # 解析 URL
        parsed = urllib.parse.urlparse(registry_url)
        
        # 如果没有 scheme，根据 insecure 设置默认
        if not parsed.scheme:
            scheme = "http" if insecure else "https"
            # 尝试构造完整 URL
            if ":" in registry_url:
                test_url = f"{scheme}://{registry_url}/v2/"
            else:
                test_url = f"{scheme}://{registry_url}:{'5000' if insecure else '443'}/v2/"
        else:
            test_url = f"{registry_url}/v2/"
        
        # 重新解析
        parsed = urllib.parse.urlparse(test_url)
        host = parsed.hostname
        port = parsed.port or (5000 if insecure else 443 if parsed.scheme == "https" else 80)
        
        logger.debug(f"检查 Registry 连通性: {host}:{port}")
        
        try:
            # 使用 socket 检查端口连通性
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            
            # 对于 Docker Hub，额外检查 API
            if "docker.io" in host or "index.docker.io" in host:
                return True, "Docker Hub 可连通"
            
            return True, f"Registry {host}:{port} 可连通"
            
        except socket.timeout:
            return False, f"连接 Registry 超时 ({timeout}s): {host}:{port}"
        except socket.gaierror:
            return False, f"无法解析 Registry 地址: {host}"
        except ConnectionRefusedError:
            return False, f"Registry 拒绝连接: {host}:{port}"
        except Exception as e:
            return False, f"Registry 连接失败: {e}"
    
    @staticmethod
    def check_docker_daemon() -> Tuple[bool, str]:
        """检查 Docker Daemon 是否运行"""
        try:
            client = docker.from_env()
            version = client.version()
            return True, f"Docker Daemon 运行正常 (API: {version.get('ApiVersion', 'unknown')})"
        except DockerException as e:
            return False, f"无法连接 Docker Daemon: {e}"


class DockerClient:
    """Docker SDK 客户端封装"""
    
    def __init__(self):
        self.client: Optional[docker.DockerClient] = None
        self.api: Optional[docker.APIClient] = None
        self._connect()
    
    def _connect(self):
        """连接到 Docker Daemon"""
        try:
            self.client = docker.from_env()
            self.api = docker.APIClient()
            logger.debug(f"Docker 客户端初始化成功 (版本: {self.client.version().get('Version', 'unknown')})")
        except DockerException as e:
            logger.error(f"无法连接 Docker Daemon: {e}")
            raise RuntimeError(f"Docker 连接失败: {e}")
    
    def ping(self) -> bool:
        """检查 Docker Daemon 是否可用"""
        try:
            return self.client.ping()
        except Exception as e:
            logger.debug(f"Docker ping 失败: {e}")
            return False
    
    def build_image(
        self,
        path: Path,
        tag: str,
        dockerfile: str = "Dockerfile",
        no_cache: bool = False,
        build_args: Optional[Dict[str, str]] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        构建 Docker 镜像
        
        Args:
            path: 构建上下文路径
            tag: 镜像标签
            dockerfile: Dockerfile 文件名
            no_cache: 是否不使用缓存
            build_args: 构建参数
            progress_callback: 进度回调函数
            
        Returns:
            (是否成功, 镜像ID, 错误信息)
        """
        try:
            logger.info(f"🐳 开始构建镜像: [cyan]{tag}[/cyan]")
            
            # 使用低层 API 获取实时构建输出
            build_kwargs = {
                "path": str(path),
                "tag": tag,
                "dockerfile": dockerfile,
                "nocache": no_cache,
                "rm": True,
                "decode": True,
            }
            
            if build_args:
                build_kwargs["buildargs"] = build_args
            
            # 存储错误信息
            error_message = None
            image_id = None
            
            # 实时输出构建日志
            for line in self.api.build(**build_kwargs):
                if 'stream' in line:
                    msg = line['stream'].strip()
                    if msg:
                        logger.debug(f"  {msg}")
                        if progress_callback:
                            progress_callback(msg)
                
                if 'error' in line:
                    error_message = line['error']
                    logger.error(f"  {error_message}")
                    return False, None, error_message
                
                if 'aux' in line and 'ID' in line['aux']:
                    image_id = line['aux']['ID']
            
            if image_id:
                short_id = image_id.replace('sha256:', '')[:12]
                logger.success(f"🎊 镜像构建成功: [green]{tag}[/green] ([dim]{short_id}[/dim])")
                return True, image_id, None
            else:
                # 重新获取镜像 ID
                try:
                    image = self.client.images.get(tag)
                    short_id = image.id.replace('sha256:', '')[:12]
                    logger.success(f"🎊 镜像构建成功: [green]{tag}[/green] ([dim]{short_id}[/dim])")
                    return True, image.id, None
                except ImageNotFound:
                    logger.error("💔 镜像构建失败: 无法获取镜像 ID")
                    return False, None, "无法获取镜像 ID"
                    
        except BuildError as e:
            logger.error(f"💔 镜像构建失败: {e}")
            return False, None, str(e)
        except Exception as e:
            logger.error(f"💔 镜像构建异常: {e}")
            return False, None, str(e)
    
    def get_image_info(self, tag: str) -> Dict:
        """获取镜像信息"""
        try:
            image = self.client.images.get(tag)
            attrs = image.attrs
            
            # 计算大小
            size_bytes = attrs.get('Size', 0)
            size_mb = size_bytes / (1024 * 1024)
            size_gb = size_bytes / (1024 * 1024 * 1024)
            
            if size_gb >= 1:
                size_str = f"{size_gb:.2f}GB"
            else:
                size_str = f"{size_mb:.1f}MB"
            
            return {
                'id': image.id.replace('sha256:', '')[:12],
                'full_id': image.id,
                'size': size_str,
                'size_bytes': size_bytes,
                'tags': image.tags,
                'created': attrs.get('Created', ''),
                'architecture': attrs.get('Architecture', ''),
                'os': attrs.get('Os', ''),
            }
        except ImageNotFound:
            return {}
        except Exception as e:
            logger.debug(f"获取镜像信息失败: {e}")
            return {}
    
    def get_image_digest(self, tag: str) -> Optional[str]:
        """获取镜像 digest"""
        try:
            image = self.client.images.get(tag)
            repo_digests = image.attrs.get('RepoDigests', [])
            if repo_digests:
                # 格式: registry/repo@sha256:xxx
                digest = repo_digests[0].split('@')[-1]
                return digest
            return None
        except Exception as e:
            logger.debug(f"获取镜像 digest 失败: {e}")
            return None
    
    def tag_image(self, source_tag: str, target_tag: str) -> bool:
        """给镜像打标签"""
        try:
            image = self.client.images.get(source_tag)
            image.tag(target_tag)
            logger.debug(f"镜像标签: {source_tag} -> {target_tag}")
            return True
        except Exception as e:
            logger.error(f"镜像标签失败: {e}")
            return False
    
    def push_image(
        self,
        tag: str,
        registry: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        推送镜像到仓库
        
        Returns:
            (是否成功, digest)
        """
        full_tag = f"{registry}{tag}" if registry else tag
        
        # 检查是否需要重新打标签
        if registry and not tag.startswith(registry):
            logger.info(f"🏷️  重新标记镜像: [dim]{tag}[/dim] -> [cyan]{full_tag}[/cyan]")
            if not self.tag_image(tag, full_tag):
                return False, None
        
        logger.info(f"🚀 推送镜像到仓库: [cyan]{full_tag}[/cyan]")
        
        try:
            # 推送镜像
            digest = None
            for line in self.api.push(full_tag, stream=True, decode=True):
                if 'status' in line:
                    status = line['status']
                    if progress_callback:
                        progress_callback(status)
                    logger.debug(f"  {status}")
                
                if 'error' in line:
                    error = line['error']
                    logger.error(f"💔 推送失败: {error}")
                    return False, None
                
                # 尝试获取 digest
                if 'aux' in line and 'Digest' in line['aux']:
                    digest = line['aux']['Digest']
            
            # 如果没有从推送输出获取到 digest，尝试从本地镜像获取
            if not digest:
                digest = self.get_image_digest(full_tag)
            
            if digest:
                logger.success(f"🚀✨ 推送成功: [green]{full_tag}[/green]")
                logger.info(f"📋 镜像 Digest: [dim]{digest}[/dim]")
            else:
                logger.success(f"🚀✨ 推送成功: [green]{full_tag}[/green]")
            
            return True, digest
            
        except Exception as e:
            logger.error(f"💔 推送失败: {e}")
            return False, None
    
    def test_image_tool(self, tag: str, tool: str, timeout: int = 60) -> Tuple[bool, str]:
        """
        测试镜像中是否存在指定工具
        
        Returns:
            (是否成功, 路径或错误信息)
        """
        try:
            result = self.client.containers.run(
                tag,
                f"sh -c 'command -v {tool}'",
                remove=True,
                detach=False,
                stdout=True,
                stderr=True,
            )
            path = result.decode('utf-8').strip()
            return True, path
        except Exception as e:
            return False, str(e)
    
    def test_image(
        self,
        tag: str,
        tools: List[str],
        timeout: int = 60,
    ) -> Tuple[bool, Dict[str, str]]:
        """
        测试镜像中的工具
        
        Returns:
            (是否全部通过, {工具名: 路径/错误})
        """
        if not tools:
            logger.warning("🔍 未检测到可测试的工具")
            return True, {}
        
        logger.info(f"🔬 测试镜像工具 ({len(tools)}个): {', '.join(tools)}")
        
        results = {}
        all_passed = True
        
        for tool in tools:
            success, result = self.test_image_tool(tag, tool, timeout)
            if success:
                logger.success(f"   ✅ {tool} → [dim]{result}[/dim]")
                results[tool] = result
            else:
                logger.error(f"   ❌ {tool} → 未找到")
                results[tool] = f"失败: {result}"
                all_passed = False
        
        return all_passed, results
    
    def close(self):
        """关闭客户端连接"""
        if self.api:
            self.api.close()


# 全局客户端实例
_docker_client: Optional[DockerClient] = None


def get_docker_client() -> DockerClient:
    """获取全局 Docker 客户端"""
    global _docker_client
    if _docker_client is None:
        _docker_client = DockerClient()
    return _docker_client


def reset_docker_client():
    """重置全局客户端"""
    global _docker_client
    if _docker_client:
        _docker_client.close()
    _docker_client = None
