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
                tag=tag,
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
    ) -> List[ImageBuildResult]:
        """批量构建目录中的所有 yaml 文件"""
        yaml_files = sorted(list(env_dir.glob("*.yaml")) + list(env_dir.glob("*.yml")))
        
        if not yaml_files:
            logger.warning(f"🔍 在 {env_dir} 中没有找到 YAML 文件")
            return []
        
        logger.info(f"📦 批量构建模式，找到 [cyan]{len(yaml_files)}[/cyan] 个环境文件")
        
        results = []
        for idx, yaml_file in enumerate(yaml_files, 1):
            logger.info(f"🔧 [{idx}/{len(yaml_files)}] 处理: [cyan]{yaml_file.name}[/cyan]")
            result = self.build(
                env_file=yaml_file,
                registry=registry,
                push=push,
            )
            results.append(result)
        
        return results


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
                full_image_uri = f"{result.registry}{result.tag}"
            
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
