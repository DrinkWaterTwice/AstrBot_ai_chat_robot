from loguru import logger
import sys

def log_init():
# 移除默认的处理器
    logger.remove()

    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True
    )
    

    # 添加控制台处理器 - 输出到控制台并启用颜色
    logger.add(
        "app.log",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True  # 启用颜色显示
    )

    logger.add(
        "app.log",
        format="{time:YYYY-MM-DD HH:mm:ss} - {level} - {message}",
        level="DEBUG",
        rotation="10 MB",  # 文件大小达到10MB时轮转
        retention="7 days",  # 保留7天的日志
        encoding="utf-8"
    )

    logger.add(
        "app.log",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="ERROR",
        colorize=True  # 启用颜色显示
    )

    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="WARNING",
        colorize=True  # 启用颜色显示
    )


    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="ERROR",
        colorize=True
    )
    # 记录日志
    logger.info('日志记录初始化完成')