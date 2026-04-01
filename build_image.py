#!/usr/bin/env python3
"""
RNAFlow 自动容器镜像构建脚本
根据conda环境yaml文件自动生成并构建Docker镜像

Usage:
    python build_image.py -e ../envs/bwa2.yaml -t bwa-mem2:test
    python build_image.py -e ../envs/fastqc.yaml -t rnaflow-fastqc:0.1.9 --push
    python build_image.py --batch ../envs/ --registry your-registry.io/
"""

import argparse
import subprocess
import sys
import tempfile
import os
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
import re
import shutil
from datetime import datetime
import json

# 日志和UI库
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)
from rich.tree import Tree
from rich.syntax import Syntax
from rich import box

# 配置日志
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def setup_logging(console_level: str = "INFO", file_level: str = "DEBUG"):
    """配置日志系统"""
    logger.remove()

    # 控制台日志 - 简洁美观的格式
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        ),
        level=console_level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # 文件日志 - 详细格式（保留完整信息）
    logger.add(
        str(LOG_DIR / "container_build_{time:YYYYMMDD}.log"),
        rotation="1 day",
        retention="7 days",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} - "
            "{message}"
        ),
        level=file_level,
        backtrace=True,
        diagnose=True,
    )

    # 文件日志 - 详细格式
    logger.add(
        str(LOG_DIR / "container_build_{time:YYYYMMDD}.log"),
        rotation="1 day",
        retention="7 days",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} - "
            "{message}"
        ),
        level=file_level,
        backtrace=True,
        diagnose=True,
    )


# 默认日志配置
setup_logging()

# Rich 控制台
console = Console()


@dataclass
class BuildConfig:
    """构建配置"""

    env_file: Path
    tag: str
    registry: Optional[str] = None
    push: bool = False
    no_cache: bool = False
    template_file: Optional[Path] = None
    health_check: Optional[str] = None
    test_tools: Optional[List[str]] = None


@dataclass
class BuildResult:
    """构建结果记录"""

    env_name: str
    tag: str
    status: str  # "success", "failed", "skipped"
    duration: float
    image_size: Optional[str] = None
    image_id: Optional[str] = None
    error_msg: Optional[str] = None
    tools_detected: List[str] = field(default_factory=list)


def load_pipeline_config() -> dict:
    """加载流程特有配置（如果存在）"""
    config_files = [
        Path(__file__).parent / "pipeline_config.yaml",
        Path(__file__).parent / "rnaflow_config.yaml",
        Path(__file__).parent / "atacflow_config.yaml",
    ]

    for config_file in config_files:
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                logger.debug(f"无法加载配置文件 {config_file}: {e}")

    return {}


def print_header(pipeline_name: str = "RNAFlow"):
    """打印程序头部信息"""
    console.print(
        Panel.fit(
            f"[bold cyan]{pipeline_name} Container Builder[/bold cyan]\n"
            "[dim]自动从Conda环境构建Docker镜像[/dim]",
            box=box.ROUNDED,
            border_style="cyan",
        )
    )


def load_yaml_safe(file_path: Path) -> dict:
    """安全加载yaml文件"""
    try:
        with open(file_path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"无法加载YAML文件 {file_path}: {e}")
        raise


def get_env_name(yaml_path: Path) -> str:
    """从yaml文件中提取环境名称"""
    try:
        content = load_yaml_safe(yaml_path)
        return content.get("name", yaml_path.stem)
    except Exception:
        return yaml_path.stem


def detect_main_tools(yaml_path: Path) -> List[str]:
    """
    检测yaml中的主要工具（通常是第一个主要软件包）
    返回可能的工具名称列表用于健康检查
    """
    try:
        content = load_yaml_safe(yaml_path)
        deps = content.get("dependencies", [])
        tools = []

        # 常见的生物信息学工具模式
        tool_patterns = [
            "bwa",
            "star",
            "samtools",
            "fastqc",
            "fastp",
            "rsem",
            "gatk",
            "picard",
            "stringtie",
            "arriba",
            "rmats",
            "multiqc",
            "qualimap",
            "rseqc",
            "preseq",
            "mosdepth",
            "deeptools",
            "bcftools",
            "snpeff",
            "circexplorer2",
        ]

        for dep in deps:
            if isinstance(dep, str):
                pkg_name = dep.split("=")[0].lower()
                for pattern in tool_patterns:
                    if pattern in pkg_name:
                        tools.append(pkg_name)
                        break

        return tools[:3]  # 返回前3个检测到的工具
    except Exception:
        return []


def generate_health_check(tools: List[str]) -> Optional[str]:
    """生成健康检查命令"""
    if not tools:
        return None

    # 优先使用能输出版本的命令
    primary_tool = tools[0]

    # 特殊工具处理
    special_checks = {
        "bwa": "bwa-mem2 version || bwa version",
        "star": "STAR --version",
        "gatk": "gatk --version || gatk --help",
        "picard": "picard --version || picard -h",
        "rsem": "rsem-calculate-expression --version",
        "samtools": "samtools --version",
        "fastqc": "fastqc --version",
        "fastp": "fastp --version",
        "multiqc": "multiqc --version",
    }

    for key, cmd in special_checks.items():
        if key in primary_tool:
            return cmd

    # 通用检查
    return f"{primary_tool} --version || {primary_tool} -h || which {primary_tool}"


def generate_dockerfile(config: BuildConfig, output_path: Path) -> Path:
    """
    根据模板和yaml文件生成Dockerfile
    """
    env_name = get_env_name(config.env_file)
    tools = detect_main_tools(config.env_file)

    # 优先使用用户指定的健康检查命令
    if config.health_check:
        health_cmd = config.health_check
        logger.info(f"使用自定义健康检查命令: {health_cmd}")
    else:
        health_cmd = generate_health_check(tools)

    # 读取模板
    template_path = (
        config.template_file or Path(__file__).parent / "images" / "Dockerfile.template"
    )
    with open(template_path, "r") as f:
        template = f.read()

    # 替换变量
    dockerfile_content = template.replace("{{env_name}}", env_name)
    dockerfile_content = dockerfile_content.replace(
        "{{env_file}}", str(config.env_file.name)
    )
    dockerfile_content = dockerfile_content.replace(
        "{{health_check_cmd}}", health_cmd or ""
    )

    # 移除空的health check块
    if not health_cmd:
        dockerfile_content = re.sub(
            r"\n# 健康检查.*?\n\{% endif %}\n",
            "\n",
            dockerfile_content,
            flags=re.DOTALL,
        )
    else:
        dockerfile_content = dockerfile_content.replace("{% if health_check_cmd %}", "")
        dockerfile_content = dockerfile_content.replace("{% endif %}", "")

    # 写入Dockerfile
    dockerfile_path = output_path / "Dockerfile"
    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)

    # 复制yaml文件到构建目录
    yaml_dest = output_path / config.env_file.name
    shutil.copy2(config.env_file, yaml_dest)

    logger.info(f"生成 Dockerfile: {dockerfile_path}")
    logger.info(f"复制环境文件: {yaml_dest}")
    logger.debug(f"检测到工具: {', '.join(tools) if tools else 'None'}")
    logger.debug(f"健康检查命令: {health_cmd or 'None'}")

    return dockerfile_path


def show_image_info(tag: str) -> Dict[str, str]:
    """显示镜像信息"""
    try:
        result = subprocess.run(
            [
                "docker",
                "images",
                "--format",
                "{{.Size}}\t{{.ID}}\t{{.Repository}}:{{.Tag}}",
                tag,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip():
            parts = result.stdout.strip().split("\t")
            if len(parts) >= 2:
                return {
                    "size": parts[0],
                    "id": parts[1][:12],
                    "tag": parts[2] if len(parts) > 2 else tag,
                }
    except Exception as e:
        logger.debug(f"获取镜像信息失败: {e}")
    return {}


def build_image(
    config: BuildConfig, dockerfile_path: Path
) -> tuple[bool, Optional[str]]:
    """
    执行Docker构建
    返回: (是否成功, 镜像ID)
    """
    build_args = ["docker", "build"]

    if config.no_cache:
        build_args.append("--no-cache")

    # 添加标签
    full_tag = f"{config.registry}{config.tag}" if config.registry else config.tag
    build_args.extend(["-t", full_tag])
    build_args.extend(["-f", str(dockerfile_path)])
    build_args.append(str(dockerfile_path.parent))

    logger.info(f"开始构建镜像: {full_tag}")
    logger.debug(f"构建命令: {' '.join(build_args)}")

    try:
        # 使用 subprocess 实时输出
        process = subprocess.Popen(
            build_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # 实时输出构建日志
        for line in process.stdout:
            line = line.rstrip()
            if line:
                # 根据内容设置颜色
                if "ERROR" in line or "error" in line.lower():
                    console.print(f"  [red]{line}[/red]")
                    logger.error(line)
                elif "Successfully" in line or "DONE" in line:
                    console.print(f"  [green]{line}[/green]")
                    logger.success(line)
                else:
                    logger.debug(line)

        process.wait()

        if process.returncode == 0:
            logger.success(f"镜像构建成功: {full_tag}")
            return True, full_tag
        else:
            logger.error(f"镜像构建失败，退出码: {process.returncode}")
            return False, None

    except subprocess.CalledProcessError as e:
        logger.error(f"构建失败: {e}")
        return False, None
    except Exception as e:
        logger.error(f"构建过程出错: {e}")
        return False, None


def push_image(tag: str, registry: Optional[str] = None) -> bool:
    """
    推送镜像到仓库
    """
    full_tag = f"{registry}{tag}" if registry else tag

    # 如果需要重新打标签
    if registry and not tag.startswith(registry):
        console.print(f"[yellow]重新标记镜像: {tag} -> {full_tag}[/yellow]")
        try:
            subprocess.run(
                ["docker", "tag", tag, full_tag], check=True, capture_output=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"镜像标记失败: {e}")
            return False

    logger.info(f"推送镜像到仓库: {full_tag}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("推送中...", total=None)
        try:
            result = subprocess.run(
                ["docker", "push", full_tag], capture_output=True, text=True, check=True
            )
            progress.update(task, completed=True)
            logger.success(f"推送成功: {full_tag}")
            return True
        except subprocess.CalledProcessError as e:
            progress.update(task, completed=True)
            logger.error(f"推送失败: {e}")
            logger.error(f"错误输出: {e.stderr}")
            return False


def test_image(
    tag: str, tools: List[str], user_specified_tools: Optional[List[str]] = None
) -> bool:
    """
    测试镜像是否可用
    """
    logger.info(f"测试镜像: {tag}")

    # 优先使用用户指定的工具列表
    test_tools = user_specified_tools or tools

    if not test_tools:
        logger.warning("未检测到可测试的工具")
        return True

    # 如果是用户指定的工具，显示全部；否则只显示前3个
    tools_to_test = test_tools if user_specified_tools else test_tools[:3]

    test_table = Table(title="镜像测试", box=box.ROUNDED)
    test_table.add_column("工具", style="cyan")
    test_table.add_column("状态", style="green")
    test_table.add_column("路径", style="dim")

    all_passed = True

    for tool in tools_to_test:
        try:
            # 使用 command -v 代替 which，通常更快更可靠
            result = subprocess.run(
                ["docker", "run", "--rm", tag, "sh", "-c", f"command -v " + tool],
                capture_output=True,
                text=True,
                timeout=60,  # 增加超时时间到 60 秒
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                test_table.add_row(tool, "[green]✓[/green]", path)
                logger.debug(f"工具 {tool} 测试通过: {path}")
            else:
                test_table.add_row(tool, "[red]✗[/red]", "未找到")
                logger.warning(f"工具 {tool} 测试失败")
                all_passed = False
        except Exception as e:
            test_table.add_row(tool, "[red]✗[/red]", str(e))
            logger.error(f"工具 {tool} 测试异常: {e}")
            all_passed = False

    console.print(test_table)
    return all_passed


def batch_build(
    env_dir: Path, registry: Optional[str] = None, push: bool = False
) -> List[BuildResult]:
    """
    批量构建目录中的所有yaml文件
    """
    yaml_files = sorted(list(env_dir.glob("*.yaml")) + list(env_dir.glob("*.yml")))

    if not yaml_files:
        logger.warning(f"在 {env_dir} 中没有找到YAML文件")
        return []

    console.print(f"\n[bold cyan]批量构建模式[/bold cyan]")
    console.print(f"找到 {len(yaml_files)} 个环境文件\n")

    results: List[BuildResult] = []

    for idx, yaml_file in enumerate(yaml_files, 1):
        console.print(
            f"\n[bold]「{idx}/{len(yaml_files)}」处理: {yaml_file.name}[/bold]"
        )
        console.print("─" * 60)

        start_time = datetime.now()
        env_name = get_env_name(yaml_file)
        tag = f"rnaflow-{env_name}:0.1.9"
        tools = detect_main_tools(yaml_file)

        config = BuildConfig(env_file=yaml_file, tag=tag, registry=registry, push=push)

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                dockerfile_path = generate_dockerfile(config, Path(tmpdir))
                success, _ = build_image(config, dockerfile_path)

                duration = (datetime.now() - start_time).total_seconds()

                if success:
                    # 测试镜像
                    full_tag = f"{registry}{tag}" if registry else tag
                    test_image(full_tag, tools, user_specified_tools=None)

                    # 获取镜像信息
                    info = show_image_info(full_tag)

                    # 推送镜像
                    if push:
                        push_image(tag, registry)

                    results.append(
                        BuildResult(
                            env_name=env_name,
                            tag=tag,
                            status="success",
                            duration=duration,
                            image_size=info.get("size"),
                            image_id=info.get("id"),
                            tools_detected=tools,
                        )
                    )
                else:
                    results.append(
                        BuildResult(
                            env_name=env_name,
                            tag=tag,
                            status="failed",
                            duration=duration,
                            error_msg="构建失败",
                            tools_detected=tools,
                        )
                    )
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"处理 {yaml_file.name} 时出错: {e}")
            results.append(
                BuildResult(
                    env_name=env_name,
                    tag=tag,
                    status="failed",
                    duration=duration,
                    error_msg=str(e),
                    tools_detected=tools,
                )
            )

    return results


def print_summary(results: List[BuildResult]):
    """打印构建摘要"""
    console.print("\n")
    console.print("=" * 60)
    console.print("[bold cyan]构建摘要[/bold cyan]")
    console.print("=" * 60)

    table = Table(box=box.ROUNDED)
    table.add_column("环境", style="cyan")
    table.add_column("标签", style="dim")
    table.add_column("状态", style="bold")
    table.add_column("耗时", justify="right")
    table.add_column("大小", justify="right")

    success_count = sum(1 for r in results if r.status == "success")
    failed_count = sum(1 for r in results if r.status == "failed")

    for r in results:
        status_str = {
            "success": "[green]✓ 成功[/green]",
            "failed": "[red]✗ 失败[/red]",
            "skipped": "[yellow]⊘ 跳过[/yellow]",
        }.get(r.status, r.status)

        size_str = r.image_size or "-"
        duration_str = f"{r.duration:.1f}s"

        table.add_row(r.env_name, r.tag, status_str, duration_str, size_str)

    console.print(table)

    # 统计信息
    total_duration = sum(r.duration for r in results)
    console.print(
        f"\n[bold]统计:[/bold] 成功: {success_count}, 失败: {failed_count}, 总计: {len(results)}"
    )
    console.print(f"[bold]总耗时:[/bold] {total_duration:.1f}秒")

    # 保存JSON报告
    LOG_DIR = Path(__file__).parent / "logs"
    LOG_DIR.mkdir(exist_ok=True)
    report_path = (
        LOG_DIR / f"build_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    report_data = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": len(results),
            "success": success_count,
            "failed": failed_count,
        },
        "results": [
            {
                "env_name": r.env_name,
                "tag": r.tag,
                "status": r.status,
                "duration": r.duration,
                "image_size": r.image_size,
                "image_id": r.image_id,
                "error_msg": r.error_msg,
                "tools": r.tools_detected,
            }
            for r in results
        ],
    }

    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2)

    logger.info(f"详细报告已保存: {report_path}")


def print_beautiful_help(parser):
    """使用 Rich 打印美观的帮助信息"""
    console.print(
        Panel.fit(
            "[bold cyan]RNAFlow Container Builder[/bold cyan]\n"
            "[dim]自动从Conda环境构建Docker镜像[/dim]",
            box=box.ROUNDED,
            border_style="cyan",
        )
    )

    console.print("\n[bold]使用方法:[/bold]")
    console.print(f"  python build_image.py [选项]\n")

    # 创建选项表格
    table = Table(show_header=True, header_style="bold magenta", box=box.ROUNDED)
    table.add_column("选项", style="cyan")
    table.add_column("说明", style="dim")

    # 添加所有选项
    table.add_row("-h, --help", "显示此帮助信息并退出")
    table.add_row("-e, --env, --env-file <PATH>", "Conda环境yaml文件路径")
    table.add_row("-t, --tag <TAG>", "镜像标签 (例如: rnaflow-bwa:0.1.9)")
    table.add_row("-r, --registry <REGISTRY>", "镜像仓库前缀 (例如: registry.io/)")
    table.add_row("--push", "构建后推送镜像")
    table.add_row("--no-cache", "不使用Docker缓存")
    table.add_row("--batch <DIR>", "批量构建目录中的所有yaml文件")
    table.add_row("--template <PATH>", "自定义Dockerfile模板路径")
    table.add_row(
        "--health-check <CMD>", "自定义健康检查命令 (例如: 'mytool --version')"
    )
    table.add_row(
        "--test-tools <TOOL1> <TOOL2>",
        "指定要测试的工具名称列表 (例如: 'rsem-calculate-expression' 'samtools')",
    )
    table.add_row("--log-level, -l <LEVEL>", "控制台日志级别 (默认: INFO)")
    table.add_row("--file-log-level <LEVEL>", "文件日志级别 (默认: DEBUG)")
    table.add_row("--verbose, -v", "显示详细日志 (相当于 --log-level DEBUG)")

    console.print(table)

    # 示例部分
    console.print("\n[bold]示例:[/bold]")

    # 直接用 console.print 打印示例，避免表格换行问题
    console.print("  [dim]# 构建单个环境[/dim]")
    console.print(
        "  [green]python build_image.py -e ../envs/bwa2.yaml -t bwa-mem2:test[/green]"
    )
    console.print()
    console.print("  [dim]# 构建并推送[/dim]")
    console.print(
        "  [green]python build_image.py -e ../envs/fastqc.yaml -t fastqc:0.1.9 --push --registry registry.io/[/green]"
    )
    console.print()
    console.print("  [dim]# 批量构建[/dim]")
    console.print(
        "  [green]python build_image.py --batch ../envs/ --registry registry.io/[/green]"
    )
    console.print()
    console.print("  [dim]# 自定义日志级别[/dim]")
    console.print(
        "  [green]python build_image.py -e ../envs/bwa2.yaml -t test:latest --log-level DEBUG[/green]"
    )
    console.print()
    console.print("  [dim]# 使用自定义健康检查命令[/dim]")
    console.print(
        "  [green]python build_image.py -e ../envs/mytool.yaml -t mytool:latest --health-check 'mytool --version'[/green]"
    )
    console.print()
    console.print("  [dim]# 自定义要测试的工具名称[/dim]")
    console.print(
        "  [green]python build_image.py -e ../envs/rsem.yaml -t rsem:latest --test-tools 'rsem-calculate-expression' 'samtools'[/green]"
    )


def main():
    parser = argparse.ArgumentParser(
        description="RNAFlow自动容器镜像构建工具 - 支持Rich日志和详细追踪",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    # 添加自定义 help 选项
    parser.add_argument(
        "-h", "--help", action="store_true", help="显示此帮助信息并退出"
    )

    parser.add_argument(
        "-e", "--env", "--env-file", type=Path, help="Conda环境yaml文件路径"
    )
    parser.add_argument("-t", "--tag", help="镜像标签 (例如: rnaflow-bwa:0.1.9)")
    parser.add_argument("-r", "--registry", help="镜像仓库前缀 (例如: registry.io/)")
    parser.add_argument("--push", action="store_true", help="构建后推送镜像")
    parser.add_argument("--no-cache", action="store_true", help="不使用Docker缓存")
    parser.add_argument(
        "--batch", type=Path, metavar="DIR", help="批量构建目录中的所有yaml文件"
    )
    parser.add_argument("--template", type=Path, help="自定义Dockerfile模板路径")
    parser.add_argument(
        "--health-check", type=str, help="自定义健康检查命令 (例如: 'mytool --version')"
    )
    parser.add_argument(
        "--test-tools",
        type=str,
        nargs="+",
        help="指定要测试的工具名称列表 (例如: 'rsem-calculate-expression' 'samtools')",
    )
    parser.add_argument(
        "--log-level",
        "-l",
        type=str,
        choices=["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="控制台日志级别 (默认: INFO)",
    )
    parser.add_argument(
        "--file-log-level",
        type=str,
        choices=["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"],
        default="DEBUG",
        help="文件日志级别 (默认: DEBUG)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="显示详细日志 (相当于 --log-level DEBUG)",
    )

    # 先检查是否有 help 参数，手动处理
    if "-h" in sys.argv or "--help" in sys.argv:
        print_beautiful_help(parser)
        sys.exit(0)

    args = parser.parse_args()

    # 如果没有提供任何必需参数，显示帮助信息
    if not args.env and not args.batch:
        print_beautiful_help(parser)
        sys.exit(0)

    # 设置日志级别
    console_level = args.log_level
    if args.verbose:
        console_level = "DEBUG"

    setup_logging(console_level=console_level, file_level=args.file_log_level)

    # 加载流程特有配置
    pipeline_config = load_pipeline_config()
    pipeline_name = pipeline_config.get("pipeline_name", "BioPipeline")

    print_header(pipeline_name)

    # 批量构建模式
    if args.batch:
        if not args.batch.exists():
            logger.error(f"目录不存在: {args.batch}")
            sys.exit(1)

        results = batch_build(args.batch, args.registry, args.push)
        print_summary(results)

        # 如果有失败，返回非零退出码
        if any(r.status == "failed" for r in results):
            sys.exit(1)
        return

    # 单文件构建模式
    if not args.env:
        logger.error("请指定 -e/--env-file 或使用 --batch 模式")
        parser.print_help()
        sys.exit(1)

    if not args.env.exists():
        logger.error(f"文件不存在: {args.env}")
        sys.exit(1)

    # 自动生成标签（如果未指定）
    tag = args.tag
    if not tag:
        env_name = get_env_name(args.env)
        tag = f"rnaflow-{env_name}:0.1.9"
        logger.info(f"自动生成标签: {tag}")

    config = BuildConfig(
        env_file=args.env,
        tag=tag,
        registry=args.registry,
        push=args.push,
        no_cache=args.no_cache,
        template_file=args.template,
        health_check=args.health_check,
        test_tools=args.test_tools,
    )

    # 创建临时目录并构建
    start_time = datetime.now()

    with tempfile.TemporaryDirectory() as tmpdir:
        dockerfile_path = generate_dockerfile(config, Path(tmpdir))

        # 显示生成的 Dockerfile（调试用）
        if args.verbose:
            console.print("\n[bold]生成的 Dockerfile:[/bold]")
            with open(dockerfile_path, "r") as f:
                content = f.read()
            syntax = Syntax(content, "dockerfile", theme="monokai", line_numbers=True)
            console.print(syntax)
            console.print()

        success, _ = build_image(config, dockerfile_path)

        if success:
            # 测试镜像
            tools = detect_main_tools(args.env)
            full_tag = f"{args.registry}{tag}" if args.registry else tag
            test_image(full_tag, tools, user_specified_tools=args.test_tools)

            # 推送镜像
            if args.push:
                push_image(tag, args.registry)

            duration = (datetime.now() - start_time).total_seconds()
            console.print(f"\n[green]✓ 构建完成！耗时: {duration:.1f}秒[/green]")
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
