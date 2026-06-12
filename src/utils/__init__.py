import os
import tempfile
import atexit

# 注册退出时清理临时文件
_temp_files: list[str] = []


def _cleanup_temp_files():
    """程序退出时清理所有临时图片文件"""
    for path in _temp_files:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


atexit.register(_cleanup_temp_files)


def save_temp_image(buf) -> str | None:
    """将图片 buffer 保存为临时文件，返回文件路径。

    临时文件会在程序退出时自动清理。
    """
    try:
        fd, path = tempfile.mkstemp(suffix=".png")
        with os.fdopen(fd, 'wb') as f:
            f.write(buf.getvalue())
        _temp_files.append(path)
        return path
    except Exception:
        return None


def cleanup_temp_image(path: str):
    """立即删除指定的临时图片文件"""
    try:
        if os.path.exists(path):
            os.remove(path)
        if path in _temp_files:
            _temp_files.remove(path)
    except Exception:
        pass


from .plotter import (
    plot_kline, render_stock_market_image, render_goods_market_image,
    render_rank_image, render_help_image, set_paths, shutdown
)

__all__ = [
    'save_temp_image', 'cleanup_temp_image',
    'plot_kline', 'render_stock_market_image', 'render_goods_market_image',
    'render_rank_image', 'render_help_image', 'set_paths', 'shutdown',
]
