"""
日志工具类 - 按 PDF UUID 将日志保存到独立文件
"""
import logging
import os
from pathlib import Path
from typing import Optional
from datetime import datetime


class DocumentLogger:
    """
    为每个文档创建独立的日志文件
    日志文件路径: debug_logs/{document_id}.log
    """
    
    def __init__(self, base_dir: str = "debug_logs"):
        """
        初始化文档日志器
        
        Args:
            base_dir: 日志文件保存的根目录
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
        self._loggers = {}  # 缓存已创建的 logger
    
    def get_logger(self, document_id: str, name: str = None) -> logging.Logger:
        """
        获取指定文档的日志记录器
        
        Args:
            document_id: 文档的 UUID
            name: logger 名称（可选）
            
        Returns:
            配置好的 Logger 对象
        """
        # 使用缓存避免重复创建
        cache_key = f"{document_id}_{name or 'default'}"
        if cache_key in self._loggers:
            return self._loggers[cache_key]
        
        # 创建 logger
        logger_name = f"doc.{document_id}.{name}" if name else f"doc.{document_id}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        
        # 避免重复添加 handler
        if logger.handlers:
            return logger
        
        # 创建文件 handler
        log_file = self.base_dir / f"{document_id}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # 创建格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        # 添加 handler 到 logger
        logger.addHandler(file_handler)
        
        # 同时保持控制台输出（可选）
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # 记录日志文件创建信息
        logger.info(f"=" * 80)
        logger.info(f"日志会话开始 - 文档ID: {document_id}")
        logger.info(f"日志文件: {log_file.absolute()}")
        logger.info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"=" * 80)
        
        # 缓存 logger
        self._loggers[cache_key] = logger
        
        return logger
    
    def close_logger(self, document_id: str):
        """
        关闭并清理指定文档的日志记录器
        
        Args:
            document_id: 文档的 UUID
        """
        # 查找所有相关的 logger
        keys_to_remove = [k for k in self._loggers.keys() if k.startswith(f"{document_id}_")]
        
        for key in keys_to_remove:
            logger = self._loggers[key]
            
            # 记录会话结束
            logger.info(f"=" * 80)
            logger.info(f"日志会话结束 - 文档ID: {document_id}")
            logger.info(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"=" * 80)
            
            # 关闭所有 handlers
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)
            
            # 从缓存中移除
            del self._loggers[key]
    
    def cleanup_old_logs(self, days: int = 7):
        """
        清理超过指定天数的旧日志文件
        
        Args:
            days: 保留最近多少天的日志
        """
        import time
        current_time = time.time()
        max_age = days * 24 * 60 * 60  # 转换为秒
        
        for log_file in self.base_dir.glob("*.log"):
            file_age = current_time - log_file.stat().st_mtime
            if file_age > max_age:
                try:
                    log_file.unlink()
                    print(f"已删除旧日志文件: {log_file.name}")
                except Exception as e:
                    print(f"删除日志文件失败 {log_file.name}: {e}")


# 全局单例
_document_logger = None


def get_document_logger(base_dir: str = "debug_logs") -> DocumentLogger:
    """
    获取全局文档日志器实例（单例模式）
    
    Args:
        base_dir: 日志文件保存的根目录
        
    Returns:
        DocumentLogger 实例
    """
    global _document_logger
    if _document_logger is None:
        _document_logger = DocumentLogger(base_dir)
    return _document_logger


def create_document_logger(document_id: str, name: str = None) -> logging.Logger:
    """
    便捷函数：为文档创建日志记录器
    
    Args:
        document_id: 文档的 UUID
        name: logger 名称（可选）
        
    Returns:
        配置好的 Logger 对象
    """
    return get_document_logger().get_logger(document_id, name)
