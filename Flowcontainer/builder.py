"""
Flowcontainer 镜像构建核心模块
"""
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

import yaml
from loguru import logger

from .docker_client import DockerClient, RegistryChecker
from .config import ConfigManager, FlowcontainerConfig


@dataclass
class ImageBuildResult:
    """镜像构建结果"""
    env_name: str
    tag: str
    status: str  # "success", "failed", "skipped"
    duration: float
    image_size: Optional[str] = None
    image_id: Optional[str] = None
    image_digest: Optional[str] = None
    pushed: bool = False
    push_time: Optional[str] = None
    error_msg: Optional[str] = None
    tools_detected: List[str] = field(default_factory=list)
    env_file: Optional[str] = None
    created_at: Optional[str] = None
    registry: Optional[str] = None


class DockerfileGenerator:
    """Dockerfile 生成器"""
    
    # 默认 Dockerfile 模板
    DEFAULT_TEMPLATE = """# Flowcontainer 自动生成 Dockerfile
# 环境: {{env_name}}
FROM condaforge/mambaforge:latest

LABEL maintainer="Flowcontainer"
LABEL env_name="{{env_name}}"

# 设置工作目录
WORKDIR /opt

# 复制环境文件
COPY {{env_file}} /tmp/environment.yaml

# 创建 conda 环境
RUN mamba env create -f /tmp/environment.yaml -n {{env_name}} -y && \\
    mamba clean -afy

# 设置环境变量
ENV PATH=/opt/conda/envs/{{env_name}}/bin:$PATH
ENV CONDA_DEFAULT_ENV={{env_name}}

# 健康检查
{% if health_check_cmd %}
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
    CMD {{health_check_cmd}} || exit 1
{% endif %}

# 默认命令
CMD ["/bin/bash"]
"""
    
    def __init__(self, template_file: Optional[Path] = None):
        self.template = self._load_template(template_file)
    
    def _load_template(self, template_file: Optional[Path]) -> str:
        """加载 Dockerfile 模板"""
        if template_file and template_file.exists():
            with open(template_file, 'r') as f:
                return f.read()
        
        # 查找内置模板
        builtin_template = Path(__file__).parent / "templates" / "Dockerfile.template"
        if builtin_template.exists():
            with open(builtin_template, 'r') as f:
                return f.read()
        
        return self.DEFAULT_TEMPLATE
    
    def generate(
        self,
        env_file: Path,
        output_dir: Path,
        health_check: Optional[str] = None,
    ) -> Path:
        """
        生成 Dockerfile
        
        Returns:
            Dockerfile 路径
        """
        env_name = self._get_env_name(env_file)
        
        # 替换模板变量
        content = self.template.replace("{{env_name}}", env_name)
        content = content.replace("{{env_file}}", str(env_file.name))
        content = content.replace("{{health_check_cmd}}", health_check or "")
        
        # 移除空的 health check 块
        if not health_check:
            content = re.sub(
                r'\n# 健康检查.*?\{% endif %}\n',
                '\n',
                content,
                flags=re.DOTALL,
            )
        else:
            content = content.replace("{% if health_check_cmd %}", "")
            content = content.replace("{% endif %}", "")
        
        # 写入 Dockerfile
        dockerfile_path = output_dir / "Dockerfile"
        with open(dockerfile_path, 'w') as f:
            f.write(content)
        
        # 复制环境文件
        yaml_dest = output_dir / env_file.name
        shutil.copy2(env_file, yaml_dest)
        
        logger.debug(f"生成 Dockerfile: {dockerfile_path}")
        logger.debug(f"复制环境文件: {yaml_dest}")
        
        return dockerfile_path
    
    @staticmethod
    def _get_env_name(yaml_path: Path) -> str:
        """从 yaml 文件中提取环境名称"""
        try:
            with open(yaml_path, 'r') as f:
                content = yaml.safe_load(f) or {}
            return content.get("name", yaml_path.stem)
        except Exception:
            return yaml_path.stem


class EnvAnalyzer:
    """Conda 环境分析器"""
    
    # 常见生物信息学工具
    TOOL_PATTERNS = [
        "bwa", "star", "samtools", "fastqc", "fastp", "rsem",
        "gatk", "picard", "stringtie", "arriba", "rmats", "multiqc",
        "qualimap", "rseqc", "preseq", "mosdepth", "deeptools",
        "bcftools", "snpeff", "circexplorer2", "hisat2", "bowtie2",
        "cellranger", "salmon", "kallisto", "cutadapt", "trim-galore",
        "bedtools", "macs2", "idr", "tobias", "homer", "meme",
    ]
    
    # 特殊工具的健康检查命令
    SPECIAL_HEALTH_CHECKS = {
        "bwa": "bwa-mem2 version || bwa version",
        "star": "STAR --version",
        "gatk": "gatk --version || gatk --help",
        "picard": "picard --version || picard -h",
        "rsem": "rsem-calculate-expression --version",
        "samtools": "samtools --version",
        "fastqc": "fastqc --version",
        "fastp": "fastp --version",
        "multiqc": "multiqc --version",
        "bowtie2": "bowtie2 --version",
        "hisat2": "hisat2 --version",
    }
    
    def analyze(self, yaml_path: Path) -> Dict[str, Any]:
        """分析环境文件"""
        try:
            with open(yaml_path, 'r') as f:
                content = yaml.safe_load(f) or {}
            
            deps = content.get("dependencies", [])
            tools = []
            
            for dep in deps:
                if isinstance(dep, str):
                    pkg_name = dep.split("=")[0].lower()
                    for pattern in self.TOOL_PATTERNS:
                        if pattern in pkg_name:
                            tools.append(pkg_name)
                            break
            
            return {
                "name": content.get("name", yaml_path.stem),
                "tools": tools[:5],  # 返回前5个检测到的工具
                "dependencies_count": len(deps),
            }
        except Exception as e:
            logger.warning(f"分析环境文件失败: {e}")
            return {"name": yaml_path.stem, "tools": [], "dependencies_count": 0}
    
    def generate_health_check(self, tools: List[str]) -> Optional[str]:
        """生成健康检查命令"""
        if not tools:
            return None
        
        primary_tool = tools[0]
        
        # 检查特殊工具
        for key, cmd in self.SPECIAL_HEALTH_CHECKS.items():
            if key in primary_tool:
                return cmd
        
        # 通用检查
        return f"{primary_tool} --version || {primary_tool} -h || which {primary_tool}"


class ImageBuilder:
    """镜像构建器"""
    
    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        docker_client: Optional[DockerClient] = None,
    ):
        self.config = config or ConfigManager()
        self.docker = docker_client or DockerClient()
        self.generator = DockerfileGenerator(
            Path(self.config.config.build.template_file) if self.config.config.build.template_file else None
        )
        self.analyzer = EnvAnalyzer()
    
    def build(
        self,
        env_file: Path,
        tag: Optional[str] = None,
        registry: Optional[str] = None,
        push: bool = False,
        no_cache: bool = False,
        health_check: Optional[str] = None,
        test_tools: Optional[List[str]] = None,
    ) -> ImageBuildResult:
        """
        构建单个镜像
        
        Args:
            env_file: Conda 环境文件路径
            tag: 镜像标签 (为空则自动生成)
            registry: 推送仓库地址
            push: 是否推送
            no_cache: 是否不使用缓存
            health_check: 自定义健康检查命令
            test_tools: 要测试的工具列表
            
        Returns:
            构建结果
        """
        start_time = datetime.now()
        
        # 分析环境
        analysis = self.analyzer.analyze(env_file)
        env_name = analysis["name"]
        tools = analysis["tools"]
        
        # 生成标签
        if not tag:
            prefix = self.config.config.build.default_tag_prefix
            version = self.config.config.build.default_version
            tag = f"{prefix}-{env_name}:{version}"
        
        # 使用配置的 registry
        if not registry:
            registry = self.config.get_full_registry_url()
        
        # 检查 registry 连通性 (如果需要推送)
        if push and registry:
            can_connect, msg = RegistryChecker.check_registry(
                registry,
                insecure=self.config.config.registry.insecure
            )
            if not can_connect:
                logger.error(f"❌ Registry 检查失败: {msg}")
                return ImageBuildResult(
                    env_name=env_name,
                    tag=tag,
                    status="failed",
                    duration=0,
                    error_msg=f"Registry 不可连通: {msg}",
                    tools_detected=tools,
                    env_file=str(env_file.resolve()),
                    registry=registry,
                )
            else:
                logger.debug(f"✅ Registry 检查通过: {msg}")
        
        # 生成健康检查命令
        if not health_check and tools:
            health_check = self.analyzer.generate_health_check(tools)
        
        if health_check:
            logger.info(f"🩺 使用健康检查命令: [dim]{health_check}[/dim]")
        
        # 创建临时目录并构建
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)
                
                # 生成 Dockerfile
                dockerfile_path = self.generator.generate(
                    env_file=env_file,
                    output_dir=tmpdir_path,
                    health_check=health_check,
                )
                
                # 构建镜像
                effective_no_cache = no_cache or self.config.config.build.no_cache
                success, image_id, error = self.docker.build_image(
                    path=tmpdir_path,
                    tag=tag,
                    no_cache=effective_no_cache,
                )
                
                if not success:
                    duration = (datetime.now() - start_time).total_seconds()
                    return ImageBuildResult(
                        env_name=env_name,
                        tag=tag,
                        status="failed",
                        duration=duration,
                        error_msg=error or "构建失败",
                        tools_detected=tools,
                        env_file=str(env_file.resolve()),
                        registry=registry,
                    )
                
                # 测试镜像
                tools_to_test = test_tools or tools[:3]
                self.docker.test_image(tag, tools_to_test)
                
                # 获取镜像信息
                image_info = self.docker.get_image_info(tag)
                
                # 推送镜像
                pushed = False
                digest = None
                push_time = None
                
                if push:
                    pushed, digest = self.docker.push_image(tag, registry)
                    if pushed:
                        push_time = datetime.now().isoformat()
                
                duration = (datetime.now() - start_time).total_seconds()
                
                return ImageBuildResult(
                    env_name=env_name,
                    tag=tag,
                    status="success",
                    duration=duration,
                    image_size=image_info.get("size"),
                    image_id=image_info.get("id"),
                    image_digest=digest,
                    pushed=pushed,
                    push_time=push_time,
                    tools_detected=tools,
                    env_file=str(env_file.resolve()),
                    created_at=start_time.isoformat(),
                    registry=registry,
                )
                
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"💔 构建过程异常: {e}")
            return ImageBuildResult(
                env_name=env_name,
                tag=tag if 'tag' in locals() else f"{self.config.config.build.default_tag_prefix}-{env_name}:{self.config.config.build.default_version}",
                status="failed",
                duration=duration,
                error_msg=str(e),
                tools_detected=tools,
                env_file=str(env_file.resolve()),
                registry=registry,
            )
    
    def batch_build(
        self,
        env_dir: Path,
        registry: Optional[str] = None,
        push: bool = False,
        version_tag: Optional[str] = None,
        no_cache: bool = False,
        cleanup_dangling: bool = False,
    ) -> List[ImageBuildResult]:
        """批量构建目录中的所有 yaml 文件
        
        Args:
            env_dir: 包含环境文件的目录
            registry: 镜像仓库地址
            push: 是否推送镜像
            version_tag: 统一的版本标签 (例如: "1.0.0", "v2.1")
            no_cache: 是否不使用 Docker 缓存
            cleanup_dangling: 构建完成后是否清理悬空镜像
        """
        yaml_files = sorted(list(env_dir.glob("*.yaml")) + list(env_dir.glob("*.yml")))
        
        if not yaml_files:
            logger.warning(f"🔍 在 {env_dir} 中没有找到 YAML 文件")
            return []
        
        logger.info(f"📦 批量构建模式，找到 [cyan]{len(yaml_files)}[/cyan] 个环境文件")
        
        # 如果指定了版本标签，临时覆盖配置中的版本
        original_version = None
        if version_tag:
            original_version = self.config.config.build.default_version
            self.config.config.build.default_version = version_tag
            logger.info(f"🏷️  使用统一版本标签: [cyan]{version_tag}[/cyan]")
        
        try:
            results = []
            env_yaml = ContainerEnvYaml(self.config.config.build.output_yaml if hasattr(self.config.config.build, 'output_yaml') else Path("container_env.yaml"))
            
            for idx, yaml_file in enumerate(yaml_files, 1):
                logger.info(f"🔧 [{idx}/{len(yaml_files)}] 处理: [cyan]{yaml_file.name}[/cyan]")
                result = self.build(
                    env_file=yaml_file,
                    registry=registry,
                    push=push,
                    no_cache=no_cache,
                )
                results.append(result)
                
                # 实时写入：每成功一个立即更新 container_env.yaml
                if result.status == "success":
                    env_yaml.update([result])
                    logger.debug(f"   已实时更新配置: {result.tag}")
                
                # 如果构建失败且启用了清理，清理悬空镜像
                if result.status == "failed" and cleanup_dangling:
                    logger.info("🧹 清理悬空镜像...")
                    cleaned = self.docker.cleanup_dangling_images()
                    if cleaned > 0:
                        logger.info(f"   清理了 [cyan]{cleaned}[/cyan] 个悬空镜像")
            
            # 批量构建完成后，如果启用了清理，统一清理悬空镜像
            if cleanup_dangling:
                logger.info("🧹 批量清理悬空镜像...")
                cleaned = self.docker.cleanup_dangling_images()
                if cleaned > 0:
                    logger.info(f"   共清理 [cyan]{cleaned}[/cyan] 个悬空镜像")
            
            return results
        finally:
            # 恢复原始版本配置
            if original_version is not None:
                self.config.config.build.default_version = original_version


class ContainerEnvYaml:
    """container_env.yaml 管理器"""
    
    def __init__(self, output_path: Optional[Path] = None):
        self.output_path = output_path or Path("container_env.yaml")
    
    def update(self, results: List[ImageBuildResult]):
        """更新 container_env.yaml"""
        existing_data = self._load_existing()
        
        if "images" not in existing_data:
            existing_data["images"] = {}
        
        for result in results:
            if result.status != "success":
                continue
            
            image_name = result.tag.split(":")[0]
            full_image_uri = result.tag
            if result.registry:
                registry = result.registry.rstrip("/")
                full_image_uri = f"{registry}/{result.tag}"
            
            # 生成 Apptainer URI 和命令
            apptainer_data = self._generate_apptainer_info(result.tag, result.registry, image_name)
            
            image_record = {
                "tag": result.tag,
                "registry": result.registry,
                "full_image_uri": full_image_uri,
                "image_id": result.image_id,
                "image_digest": result.image_digest,
                "size": result.image_size,
                "created_at": result.created_at or datetime.now().isoformat(),
                "env_file": result.env_file,
                "tools": result.tools_detected,
                "pushed": result.pushed,
                "apptainer": apptainer_data,
            }
            
            if result.push_time:
                image_record["push_time"] = result.push_time
            
            existing_data["images"][image_name] = image_record
        
        existing_data["metadata"] = {
            "last_updated": datetime.now().isoformat(),
            "total_images": len(existing_data["images"]),
            "version": "1.0",
        }
        
        with open(self.output_path, 'w') as f:
            yaml.dump(existing_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        logger.info(f"📝 容器环境配置已更新: [cyan]{self.output_path}[/cyan]")
    
    def _generate_apptainer_info(self, tag: str, registry: Optional[str], image_name: str) -> Dict[str, str]:
        """生成 Apptainer 相关信息
        
        Args:
            tag: 镜像标签 (例如: flowcontainer-preseq:latest)
            registry: 镜像仓库地址 (例如: docker.io/flowcontainer)
            image_name: 镜像名称 (例如: flowcontainer-preseq)
            
        Returns:
            Apptainer 相关信息字典
        """
        # 构建 Apptainer URI (docker:// 格式)
        if registry:
            # 完整 registry 路径: docker://docker.io/flowcontainer/flowcontainer-preseq:latest
            registry_clean = registry.rstrip("/")
            apptainer_uri = f"docker://{registry_clean}/{tag}"
        else:
            # 本地镜像: docker://flowcontainer-preseq:latest
            apptainer_uri = f"docker://{tag}"
        
        # 生成的 .sif 文件名
        sif_name = f"{image_name}.sif"
        
        return {
            "uri": apptainer_uri,
            "sif_name": sif_name,
            "pull_cmd": f"apptainer pull {sif_name} {apptainer_uri}",
            "exec_cmd": f"apptainer exec {apptainer_uri} <command>",
            "shell_cmd": f"apptainer shell {apptainer_uri}",
            "run_cmd": f"apptainer run {apptainer_uri}",
            "docker_fallback": f"singularity pull {sif_name} {apptainer_uri}",
        }
    
    def _load_existing(self) -> Dict:
        """加载现有配置"""
        if self.output_path.exists():
            try:
                with open(self.output_path, 'r') as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                logger.debug(f"无法加载现有配置: {e}")
        return {}


def print_build_summary(results: List[ImageBuildResult]):
    """打印构建摘要"""
    success_count = sum(1 for r in results if r.status == "success")
    failed_count = sum(1 for r in results if r.status == "failed")
    total_duration = sum(r.duration for r in results)
    
    logger.info("═" * 60)
    logger.info("📊 [bold]构建摘要[/bold]")
    logger.info("═" * 60)
    
    for r in results:
        if r.status == "success":
            status_icon = "✅"
            status_color = "green"
        elif r.status == "failed":
            status_icon = "❌"
            status_color = "red"
        else:
            status_icon = "⏸️"
            status_color = "yellow"
        
        size_str = r.image_size or "-"
        push_str = "🚀已推送" if r.pushed else "📦本地"
        logger.info(
            f"   {status_icon} [{status_color}]{r.env_name:<18}[/{status_color}] "
            f"[dim]{r.tag:<28}[/dim] {r.duration:>5.1f}s {size_str:>8} {push_str}"
        )
    
    logger.info("─" * 60)
    status_emoji = "🎉" if failed_count == 0 else "⚠️"
    logger.info(
        f"{status_emoji} 统计: [green]成功={success_count}[/green], "
        f"[red]失败={failed_count}[/red], 总计={len(results)}, 总耗时=[cyan]{total_duration:.1f}s[/cyan]"
    )
