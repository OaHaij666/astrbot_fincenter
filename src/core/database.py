"""FinCenter 数据库模块

提供 ORM 模型定义和数据库访问层。
所有 Session 操作应通过 session_scope() 上下文管理器进行，
确保异常路径下自动回滚和关闭。
"""
import requests
from contextlib import contextmanager
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta, timezone

Base = declarative_base()

_time_offset = 0


def sync_network_time():
    """同步网络时间，修正本地时钟偏差"""
    global _time_offset
    try:
        resp = requests.head("http://www.baidu.com", timeout=3)
        date_str = resp.headers.get('Date')
        if date_str:
            network_time = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S GMT')
            network_time = network_time.replace(tzinfo=timezone.utc)
            system_time = datetime.utcnow().replace(tzinfo=timezone.utc)
            _time_offset = (network_time - system_time).total_seconds()
            print(f"[FinCenter] Time synced. Offset: {_time_offset:.2f}s")
        else:
            print("[FinCenter] Failed to get Date header")
    except Exception as e:
        print(f"[FinCenter] Time sync failed: {e}")


def get_china_time():
    """获取校准后的中国标准时间"""
    utc_now = datetime.utcnow() + timedelta(seconds=_time_offset)
    return utc_now + timedelta(hours=8)


# ============================================================
#  ORM 模型
# ============================================================

class UserAccount(Base):
    __tablename__ = 'user_accounts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    user_name = Column(String, default='')
    balance = Column(Float, default=0.0)
    total_earned = Column(Float, default=0.0)
    total_spent = Column(Float, default=0.0)
    created_at = Column(DateTime, default=get_china_time)
    last_active = Column(DateTime, default=get_china_time)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class SignInRecord(Base):
    __tablename__ = 'sign_in_records'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    sign_date = Column(String, nullable=False)
    reward_amount = Column(Float, default=0.0)
    consecutive_days = Column(Integer, default=1)


class TransferRecord(Base):
    __tablename__ = 'transfer_records'

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_user = Column(String, nullable=False)
    to_user = Column(String, nullable=False)
    group_id = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    fee = Column(Float, default=0.0)
    created_at = Column(DateTime, default=get_china_time)


class StockCompany(Base):
    __tablename__ = 'stock_companies'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    icon = Column(String, default='')
    description = Column(Text, default='')
    current_price = Column(Float, default=0.0)
    trend_level = Column(Integer, default=0)
    last_update = Column(DateTime, default=get_china_time)


class StockHolding(Base):
    __tablename__ = 'stock_holdings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    code = Column(String, nullable=False)
    amount = Column(Float, default=0.0)
    avg_cost = Column(Float, default=0.0)


class StockHistory(Base):
    __tablename__ = 'stock_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    code = Column(String, nullable=False)
    timestamp = Column(DateTime, default=get_china_time)
    open = Column(Float, default=0.0)
    high = Column(Float, default=0.0)
    low = Column(Float, default=0.0)
    close = Column(Float, default=0.0)
    volume = Column(Float, default=0.0)

    def to_kline_dict(self) -> dict:
        """转换为 K 线图所需的字典格式"""
        return {
            'date': self.timestamp,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
        }


class StockNews(Base):
    __tablename__ = 'stock_news'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    timestamp = Column(DateTime, default=get_china_time)
    company_code = Column(String, nullable=False)
    event_type = Column(String, default='neutral')
    title = Column(String, default='')
    content = Column(Text, default='')
    source = Column(String, default='template')
    trend_shift = Column(Integer, default=0)
    immediate_jump = Column(Float, default=0.0)
    duration = Column(Integer, default=1)
    remaining_duration = Column(Integer, default=1)

    def to_display_dict(self) -> dict:
        """转换为展示所需的字典格式"""
        return {
            'timestamp': self.timestamp,
            'company_code': self.company_code,
            'event_type': self.event_type,
            'title': self.title,
            'content': self.content,
            'source': self.source,
            'trend_shift': self.trend_shift,
            'immediate_jump': self.immediate_jump,
            'duration': self.duration,
            'remaining_duration': self.remaining_duration,
        }


class StockEventState(Base):
    __tablename__ = 'stock_event_states'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    company_code = Column(String, nullable=False)
    event_type = Column(String, default='neutral')
    trend_shift = Column(Integer, default=0)
    immediate_jump = Column(Float, default=0.0)
    remaining_duration = Column(Integer, default=0)
    volatility_boost = Column(Float, default=1.0)
    created_at = Column(DateTime, default=get_china_time)


class GoodsDefinition(Base):
    __tablename__ = 'goods_definitions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    goods_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    icon = Column(String, default='📦')
    preview_image = Column(String, default='')
    min_price = Column(Float, default=1.0)
    max_price = Column(Float, default=100.0)
    base_price = Column(Float, default=10.0)
    volatility = Column(Float, default=0.1)
    created_at = Column(DateTime, default=get_china_time)


class GoodsMarketPrice(Base):
    """物资市场价格记录（原 GoodsMarket，重命名以区分引擎类）"""
    __tablename__ = 'goods_market'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    goods_id = Column(String, nullable=False)
    current_price = Column(Float, default=0.0)
    previous_price = Column(Float, default=0.0)
    last_refresh = Column(DateTime, default=get_china_time)


class UserBackpack(Base):
    __tablename__ = 'user_backpack'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    goods_id = Column(String, nullable=False)
    amount = Column(Float, default=0.0)


class GoodsTradeRequest(Base):
    __tablename__ = 'goods_trade_requests'

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_user = Column(String, nullable=False)
    to_user = Column(String, nullable=False)
    group_id = Column(String, nullable=False)
    goods_id = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=False)
    status = Column(String, default='pending')
    created_at = Column(DateTime, default=get_china_time)


class ChatRewardState(Base):
    __tablename__ = 'chat_reward_states'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    last_reward_time = Column(DateTime, default=None)
    daily_count = Column(Integer, default=0)
    last_message = Column(String, default='')
    last_reset_date = Column(String, default='')


class PaidCommand(Base):
    __tablename__ = 'paid_commands'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, nullable=False)
    command = Column(String, nullable=False)
    cost = Column(Float, default=0.0)
    description = Column(String, default='')
    enabled = Column(Integer, default=1)


# ============================================================
#  数据库访问层
# ============================================================

class DB:
    """数据库访问层

    提供 Session 上下文管理和用户查询接口。
    迁移逻辑统一由 migrations.migrate 模块负责。
    """

    def __init__(self, db_path: str):
        if not db_path.startswith("sqlite"):
            db_path = f"sqlite:///{db_path}"
        self.engine = create_engine(db_path)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    @contextmanager
    def session_scope(self):
        """提供事务级别的 Session 上下文管理器

        正常退出时自动 commit，异常时自动 rollback，始终关闭 Session。
        用法::

            with db.session_scope() as session:
                user = session.query(UserAccount).filter_by(...).first()
                user.balance += 100
        """
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session(self):
        """获取裸 Session（不推荐，优先使用 session_scope）"""
        return self.Session()

    def get_or_create_user(self, session, group_id, user_id, user_name='', initial_balance=1000.0):
        """查询或创建用户账户

        Args:
            session: SQLAlchemy Session（由调用方通过 session_scope 提供）
            group_id: 群组 ID
            user_id: 用户 ID
            user_name: 用户名
            initial_balance: 初始余额

        Returns:
            UserAccount 实例
        """
        user = session.query(UserAccount).filter_by(
            group_id=str(group_id),
            user_id=str(user_id)
        ).first()

        if not user:
            pending_user = session.query(UserAccount).filter_by(
                group_id='__pending__',
                user_id=str(user_id)
            ).first()
            if pending_user:
                pending_user.group_id = str(group_id)
                if user_name:
                    pending_user.user_name = user_name
                session.flush()
                return pending_user

            user = UserAccount(
                group_id=str(group_id),
                user_id=str(user_id),
                user_name=user_name,
                balance=initial_balance,
                total_earned=initial_balance
            )
            session.add(user)
            session.flush()

        return user
