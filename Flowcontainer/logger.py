"""
Flowcontainer 日志配置模块
"""
import sys
from pathlib import Path
from typing import Optional

from loguru import logger
from rich.console import Console


def setup_logging(
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    log_dir: Optional[Path] = None,
    retention_days: int = 7,
):
    """
    配置日志系统
    
    Args:
        console_level: 控制台日志级别
        file_level: 文件日志级别
        log_dir: 日志目录
        retention_days: 日志保留天数
    """
    logger.remove()
    
    # 设置环境变量避免生成 __pycache__
    sys.dont_write_bytecode = True
    
    # 使用 Rich 美化输出
    level_colors = {
        "TRACE": "dim",
        "DEBUG": "cyan",
        "INFO": "bright_blue",
        "SUCCESS": "bright_green",
        "WARNING": "bright_yellow",
        "ERROR": "bright_red",
        "CRITICAL": "bold bright_red",
    }
    icon_map = {
        "TRACE": "🔍",
        "DEBUG": "🐛",
        "INFO": "ℹ️ ",
        "SUCCESS": "✔️ ",
        "WARNING": "⚠️ ",
        "ERROR": "✖️ ",
        "CRITICAL": "💥",
    }
    
    def make_rich_sink(console_instance):
        def sink(message):
            console_instance.print(message, end="")
        return sink
    
    def rich_formatter(record):
        color = level_colors.get(record["level"].name, "white")
        icon = icon_map.get(record["level"].name, "•")
        time_str = record["time"].strftime("%H:%M:%S")
        level_str = f"{record['level'].name: <8}"
        msg = record["message"]
        
        return (
            f"[[dim]{time_str}[/dim]] "
            f"[{color}]{level_str}[/{color}] "
            f"{icon} {msg}\n"
        )
    
    # 创建专用的 rich console 实例
    rich_console = Console(stderr=True, force_terminal=True)
    
    logger.add(
        make_rich_sink(rich_console),
        format=rich_formatter,
        level=console_level,
        colorize=False,
    )
    
    # 文件日志
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(exist_ok=True)
        
        logger.add(
            str(log_dir / "flowcontainer_{time:YYYYMMDD}.log"),
            rotation="1 day",
            retention=f"{retention_days} days",
            format="[{time:YYYY-MM-DD HH:mm:ss.SSS}] {level: <8} | {name}:{function}:{line} - {message}",
            level=file_level,
            colorize=False,
        )
    
    return logger


def get_logger():
    """获取 logger 实例"""
    return logger
