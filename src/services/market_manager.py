"""股市/物资市场生命周期管理。"""
from astrbot.api import logger

from ..markets.stock import StockMarket
from ..markets.goods import GoodsMarket


class MarketManager:
    def __init__(self, plugin):
        self.plugin = plugin

    def _set_raw_config_value(self, section: str, key: str, value):
        section_data = self.plugin._raw_config.setdefault(section, {})
        if isinstance(section_data, dict):
            section_data[key] = value

    def enable_stock(self, update_config: bool = True):
        if self.plugin.stock_market:
            return False, "股市模块已启用"
        if update_config:
            self.plugin.config.stock.stock_enabled = True
            self._set_raw_config_value("stock", "stock_enabled", True)
        self.plugin.stock_market = StockMarket(
            self.plugin.db,
            stock_config=self.plugin.config.stock,
            news_config=self.plugin.config.stock_news,
        )
        self.plugin.stock_market.start()
        logger.info("Stock market started")
        return True, "✅ 股市模块已启用"

    def disable_stock(self, update_config: bool = True):
        if not self.plugin.stock_market:
            if update_config:
                self.plugin.config.stock.stock_enabled = False
                self._set_raw_config_value("stock", "stock_enabled", False)
            return False, "股市模块已禁用"
        self.plugin.stock_market.stop()
        self.plugin.stock_market = None
        if update_config:
            self.plugin.config.stock.stock_enabled = False
            self._set_raw_config_value("stock", "stock_enabled", False)
        logger.info("Stock market stopped")
        return True, "✅ 股市模块已禁用"

    def enable_goods(self, update_config: bool = True):
        if self.plugin.goods_market:
            return False, "物资模块已启用"
        if update_config:
            self.plugin.config.goods.goods_enabled = True
            self._set_raw_config_value("goods", "goods_enabled", True)
        self.plugin.goods_market = GoodsMarket(
            self.plugin.db,
            config=self.plugin.config.goods,
        )
        self.plugin.goods_market.start()
        logger.info("Goods market started")
        return True, "✅ 物资模块已启用"

    def disable_goods(self, update_config: bool = True):
        if not self.plugin.goods_market:
            if update_config:
                self.plugin.config.goods.goods_enabled = False
                self._set_raw_config_value("goods", "goods_enabled", False)
            return False, "物资模块已禁用"
        self.plugin.goods_market.stop()
        self.plugin.goods_market = None
        if update_config:
            self.plugin.config.goods.goods_enabled = False
            self._set_raw_config_value("goods", "goods_enabled", False)
        logger.info("Goods market stopped")
        return True, "✅ 物资模块已禁用"

    def stop_all(self):
        if self.plugin.stock_market:
            self.plugin.stock_market.stop()
            self.plugin.stock_market = None
            logger.info("Stock market stopped")
        if self.plugin.goods_market:
            self.plugin.goods_market.stop()
            self.plugin.goods_market = None
            logger.info("Goods market stopped")
