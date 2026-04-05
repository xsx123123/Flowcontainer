#!/usr/bin/env python3
"""
Flowcontainer CLI 入口
"""
import sys
import argparse
from pathlib import Path
from typing import Optional

from loguru import logger

from . import __version__
from .logger import setup_logging
from .config import ConfigManager, get_config
from .docker_client import DockerClient, RegistryChecker
from .builder import (
    ImageBuilder,
    ContainerEnvYaml,
    print_build_summary,
)


ASCII_LOGO = """[bold cyan]
  ███████╗██╗      ██████╗ ██╗    ██╗   ██╗██╗
  ██╔════╝██║     ██╔═══██╗██║    ██║   ██║██║
  █████╗  ██║     ██║   ██║██║    ██║   ██║██║
  ██╔══╝  ██║     ██║   ██║██║    ██║   ██║██║
  ██║     ███████╗╚██████╔╝██║    ╚██████╔╝██║
  ╚═╝     ╚══════╝ ╚═════╝ ╚═╝     ╚═════╝ ╚═╝
[/bold cyan][dim]  Container Image Builder for Bioinformatics Workflows[/dim]
"""


def print_logo():
    """打印 Logo"""
    from rich.console import Console
    console = Console(stderr=True)
    console.print(ASCII_LOGO)


def create_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        prog="flowcontainer",
        description="Flowcontainer - 生物信息学工作流容器镜像构建工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 构建单个环境
  flowcontainer build -e envs/rsem.yaml -t rnaflow-rsem:0.1

  # 构建并推送
  flowcontainer build -e envs/fastqc.yaml --push --registry registry.io/

  # 批量构建
  flowcontainer batch envs/ --push

  # 检查 Docker 和 Registry
  flowcontainer doctor

更多信息: https://github.com/yourusername/flowcontainer
        """,
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        help="配置文件路径 (默认: 自动搜索 Flowcontainer.yaml)",
    )
    parser.add_argument(
        "--no-logo",
        action="store_true",
        help="不显示 Logo",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # build 命令
    build_parser = subparsers.add_parser(
        "build",
        help="构建单个镜像",
        description="从 Conda 环境文件构建 Docker 镜像",
    )
    build_parser.add_argument(
        "-e", "--env",
        type=Path,
        required=True,
        help="Conda 环境 yaml 文件路径",
    )
    build_parser.add_argument(
        "-t", "--tag",
        help="镜像标签 (例如: rnaflow-rsem:0.1)",
    )
    build_parser.add_argument(
        "-r", "--registry",
        help="镜像仓库地址 (例如: registry.io/)",
    )
    build_parser.add_argument(
        "--push",
        action="store_true",
        help="构建后推送镜像",
    )
    build_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="不使用 Docker 缓存",
    )
    build_parser.add_argument(
        "--health-check",
        help="自定义健康检查命令",
    )
    build_parser.add_argument(
        "--test-tools",
        nargs="+",
        help="指定要测试的工具名称",
    )
    build_parser.add_argument(
        "--output-yaml",
        type=Path,
        default=Path("container_env.yaml"),
        help="输出容器环境配置 (默认: container_env.yaml)",
    )
    
    # batch 命令
    batch_parser = subparsers.add_parser(
        "batch",
        help="批量构建镜像",
        description="批量构建目录中的所有 Conda 环境文件",
    )
    batch_parser.add_argument(
        "env_dir",
        type=Path,
        help="包含 .yaml/.yml 环境文件的目录",
    )
    batch_parser.add_argument(
        "-r", "--registry",
        help="镜像仓库地址",
    )
    batch_parser.add_argument(
        "-t", "--tag",
        help="镜像版本标签 (例如: 1.0.0, v2.1)，将覆盖配置文件中的 default_version",
    )
    batch_parser.add_argument(
        "--push",
        action="store_true",
        help="构建后推送镜像",
    )
    batch_parser.add_argument(
        "--output-yaml",
        type=Path,
        default=Path("container_env.yaml"),
        help="输出容器环境配置",
    )
    batch_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="不使用 Docker 缓存",
    )
    batch_parser.add_argument(
        "--cleanup",
        action="store_true",
        help="构建完成后清理悬空镜像 (<none>:<none>)",
    )
    
    # doctor 命令
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="检查环境配置",
        description="检查 Docker、Registry 等环境配置",
    )
    doctor_parser.add_argument(
        "--registry",
        help="测试特定 Registry 连通性",
    )
    
    # init 命令
    init_parser = subparsers.add_parser(
        "init",
        help="初始化配置文件",
        description="创建默认的 Flowcontainer.yaml 配置文件",
    )
    init_parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("Flowcontainer.yaml"),
        help="输出路径 (默认: ./Flowcontainer.yaml)",
    )
    
    return parser


def cmd_build(args) -> int:
    """执行 build 命令"""
    # 加载配置
    config = get_config(args.config)
    
    # 设置日志
    setup_logging(
        console_level="INFO",
        file_level=config.config.log.file_level,
        log_dir=Path(config.config.log.log_dir),
        retention_days=config.config.log.retention_days,
    )
    
    # 检查 Docker Daemon
    can_connect, msg = RegistryChecker.check_docker_daemon()
    if not can_connect:
        logger.error(f"❌ {msg}")
        return 1
    logger.debug(f"✅ {msg}")
    
    # 检查环境文件
    if not args.env.exists():
        logger.error(f"❌ 环境文件不存在: {args.env}")
        return 1
    
    # 构建镜像
    builder = ImageBuilder(config=config)
    result = builder.build(
        env_file=args.env,
        tag=args.tag,
        registry=args.registry,
        push=args.push,
        no_cache=args.no_cache,
        health_check=args.health_check,
        test_tools=args.test_tools,
    )
    
    # 更新 container_env.yaml
    if result.status == "success":
        env_yaml = ContainerEnvYaml(args.output_yaml)
        env_yaml.update([result])
        logger.success(f"🎉 构建完成！耗时 {result.duration:.1f} 秒 ✨")
        logger.info(f"📝 镜像信息已记录: [cyan]{args.output_yaml}[/cyan]")
        return 0
    else:
        logger.error(f"💔 构建失败: {result.error_msg}")
        return 1


def cmd_batch(args) -> int:
    """执行 batch 命令"""
    # 加载配置
    config = get_config(args.config)
    
    # 设置日志
    setup_logging(
        console_level="INFO",
        file_level=config.config.log.file_level,
        log_dir=Path(config.config.log.log_dir),
        retention_days=config.config.log.retention_days,
    )
    
    # 检查 Docker Daemon
    can_connect, msg = RegistryChecker.check_docker_daemon()
    if not can_connect:
        logger.error(f"❌ {msg}")
        return 1
    logger.debug(f"✅ {msg}")
    
    # 检查目录
    if not args.env_dir.exists():
        logger.error(f"❌ 目录不存在: {args.env_dir}")
        return 1
    
    # 批量构建
    builder = ImageBuilder(config=config)
    results = builder.batch_build(
        env_dir=args.env_dir,
        registry=args.registry,
        push=args.push,
        version_tag=args.tag,
        no_cache=args.no_cache,
        cleanup_dangling=args.cleanup,
    )
    
    # 打印摘要
    print_build_summary(results)
    
    # 更新 container_env.yaml
    env_yaml = ContainerEnvYaml(args.output_yaml)
    env_yaml.update(results)
    
    # 返回状态码
    if any(r.status == "failed" for r in results):
        return 1
    return 0


def cmd_doctor(args) -> int:
    """执行 doctor 命令"""
    from rich.console import Console
    from rich.table import Table
    
    console = Console(stderr=True)
    
    print_logo()
    console.print("\n[bold cyan]🔍 环境检查[/bold cyan]\n")
    
    # 检查 Docker Daemon
    table = Table(title="检查结果", show_header=True)
    table.add_column("检查项", style="cyan")
    table.add_column("状态", style="bold")
    table.add_column("详情", style="dim")
    
    can_connect, msg = RegistryChecker.check_docker_daemon()
    if can_connect:
        table.add_row("Docker Daemon", "[green]✅ 正常[/green]", msg)
    else:
        table.add_row("Docker Daemon", "[red]❌ 异常[/red]", msg)
    
    # 加载配置并检查 Registry
    config = get_config(args.config)
    registry = args.registry or config.get_full_registry_url()
    
    if registry:
        can_connect, msg = RegistryChecker.check_registry(
            registry,
            insecure=config.config.registry.insecure
        )
        if can_connect:
            table.add_row(f"Registry ({registry})", "[green]✅ 可连通[/green]", msg)
        else:
            table.add_row(f"Registry ({registry})", "[red]❌ 不可连通[/red]", msg)
    else:
        table.add_row("Registry", "[yellow]⚠️ 未配置[/yellow]", "未设置默认 Registry")
    
    # 检查配置文件
    if config.config_file:
        table.add_row("配置文件", "[green]✅ 已加载[/green]", str(config.config_file))
    else:
        table.add_row("配置文件", "[yellow]⚠️ 未找到[/yellow]", "使用默认配置")
    
    console.print(table)
    console.print()
    
    return 0


def cmd_init(args) -> int:
    """执行 init 命令"""
    # 为 init 命令设置基本日志
    setup_logging(console_level="INFO")
    
    config_manager = ConfigManager()
    
    if args.output.exists():
        logger.warning(f"⚠️  配置文件已存在: {args.output}")
        overwrite = input("是否覆盖? [y/N]: ").lower().strip() == 'y'
        if not overwrite:
            logger.info("已取消")
            return 0
    
    config_manager.create_default_config(args.output)
    logger.success(f"✅ 配置文件已创建: [cyan]{args.output}[/cyan]")
    logger.info("💡 编辑此文件来自定义 Flowcontainer 配置")
    
    return 0


def main(args: Optional[list] = None) -> int:
    """主入口函数"""
    parser = create_parser()
    parsed_args = parser.parse_args(args)
    
    # 如果没有命令，显示帮助
    if not parsed_args.command:
        if not parsed_args.no_logo:
            print_logo()
        parser.print_help()
        return 0
    
    # 打印 Logo (除了 doctor 和 init)
    if not parsed_args.no_logo and parsed_args.command not in ("doctor", "init"):
        print_logo()
    
    # 执行对应命令
    if parsed_args.command == "build":
        return cmd_build(parsed_args)
    elif parsed_args.command == "batch":
        return cmd_batch(parsed_args)
    elif parsed_args.command == "doctor":
        return cmd_doctor(parsed_args)
    elif parsed_args.command == "init":
        return cmd_init(parsed_args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
