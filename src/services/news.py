"""股市新闻生成器模块

提供基于模板和 LLM 的新闻事件生成功能。
所有数据库操作通过 session_scope() 上下文管理器进行。
接受类型化的 StockNewsConfig 配置对象。
"""
import random
import re
import enum

from ..core.database import DB, StockNews, StockEventState, StockCompany, get_china_time
from ..config import StockNewsConfig


class StockEventType(enum.Enum):
    MAJOR_POSITIVE = "major_positive"
    POSITIVE = "positive"
    SLIGHT_POSITIVE = "slight_positive"
    NEUTRAL = "neutral"
    SLIGHT_NEGATIVE = "slight_negative"
    NEGATIVE = "negative"
    MAJOR_NEGATIVE = "major_negative"
    VOLATILITY = "volatility"


EVENT_IMPACTS = {
    StockEventType.MAJOR_POSITIVE: {"trend_shift": 2, "immediate_jump": (0.05, 0.15), "duration": 5},
    StockEventType.POSITIVE: {"trend_shift": 1, "immediate_jump": (0.02, 0.05), "duration": 3},
    StockEventType.SLIGHT_POSITIVE: {"trend_shift": 0, "immediate_jump": (0.005, 0.02), "duration": 2},
    StockEventType.NEUTRAL: {"trend_shift": 0, "immediate_jump": (-0.005, 0.005), "duration": 1},
    StockEventType.SLIGHT_NEGATIVE: {"trend_shift": 0, "immediate_jump": (-0.02, -0.005), "duration": 2},
    StockEventType.NEGATIVE: {"trend_shift": -1, "immediate_jump": (-0.05, -0.02), "duration": 3},
    StockEventType.MAJOR_NEGATIVE: {"trend_shift": -2, "immediate_jump": (-0.15, -0.05), "duration": 5},
    StockEventType.VOLATILITY: {"trend_shift": 0, "immediate_jump": (-0.03, 0.03), "duration": 2, "volatility_boost": 2.0},
}

NEWS_TEMPLATES = [
    "{name}宣布与神秘财团达成战略合作，市场情绪高涨！",
    "据传{name}创始团队正在大量抛售，引发市场恐慌。",
    "业内分析师指出{name}技术面出现金叉，未来可期。",
    "监管部门对{name}展开反垄断调查，前景不明。",
    "{name}社区发起回购提案，市场信心增强。",
    "著名投资人公开看好{name}，称其为下一个百倍股。",
    "黑客攻击导致{name}系统短暂瘫痪，用户体验下降。",
    "{name}发布重磅更新路线图，包含AI生态布局。",
    "受宏观经济影响，资金正在撤离{name}板块。",
    "{name}获得顶级风投机构千万级融资。",
    "某知名机构暗示即将增持{name}，引发抢筹热潮。",
    "{name}首席执行官在社交媒体发布神秘消息，社区猜测是重大利好。",
    "由于系统升级失败，{name}服务暂停1小时。",
    "第三方安全机构完成对{name}的审计，评分高于预期。",
    "{name}宣布进军AI算力领域，试图蹭上热点。",
    "数据显示，某巨鲸地址刚刚大量买入{name}。",
    "{name}官方频道遭黑客入侵，发布虚假信息。",
    "受政策调整影响，{name}跟随大盘波动。",
    "{name}推出回馈股东活动，年化收益率高达50%。",
    "竞争对手爆出丑闻，资金回流至{name}。",
    "{name}核心开发者宣布离职，引发对前景的担忧。",
    "神秘买家以溢价20%场外收购大量{name}。",
    "{name}将与知名工作室合作开发新项目。",
    "监管机构澄清{name}合规风险解除。",
    "{name}粉丝见面会现场火爆，信仰充值成功。",
]

DEFAULT_LLM_PROMPT = """你是财经新闻主播。请根据以下信息，构思并撰写一条虚构的市场新闻：

公司：{name}（代码：{code}）
公司背景：{description}
当前股价：{current_price}
近期趋势：{trend_description}
{history}

请发挥想象力，构思一个有趣、有脑洞的新闻事件，这个事件会导致该公司股价发生变化。新闻要符合该公司的背景设定，内容简洁（不超过80字）。"""


def sample_event_type(config: StockNewsConfig) -> StockEventType:
    """根据配置的概率分布采样事件类型"""
    probs = {
        StockEventType.MAJOR_POSITIVE: config.stock_news_prob_major_positive,
        StockEventType.POSITIVE: config.stock_news_prob_positive,
        StockEventType.SLIGHT_POSITIVE: config.stock_news_prob_slight_positive,
        StockEventType.NEUTRAL: config.stock_news_prob_neutral,
        StockEventType.SLIGHT_NEGATIVE: config.stock_news_prob_slight_negative,
        StockEventType.NEGATIVE: config.stock_news_prob_negative,
        StockEventType.MAJOR_NEGATIVE: config.stock_news_prob_major_negative,
        StockEventType.VOLATILITY: config.stock_news_prob_volatility,
    }
    types = list(probs.keys())
    weights = list(probs.values())
    total = sum(weights)
    if total <= 0:
        return StockEventType.NEUTRAL
    weights = [w / total for w in weights]
    return random.choices(types, weights=weights, k=1)[0]


def parse_event_from_news(news_text):
    match = re.search(r'\[EVENT:\s*(\w+)\]', news_text)
    if match:
        event_type_str = match.group(1)
        try:
            return StockEventType(event_type_str)
        except ValueError:
            pass
    return StockEventType.NEUTRAL


def generate_template_news(company_name, event_type):
    template = random.choice(NEWS_TEMPLATES)
    safe_name = company_name.replace('{', '{{').replace('}', '}}')
    content = template.format(name=safe_name)
    content += f" [EVENT: {event_type.value}]"
    return content


def get_trend_description(trend_level):
    descriptions = {
        3: "强势上涨",
        2: "稳步上涨",
        1: "轻微上涨",
        0: "横盘震荡",
        -1: "轻微下跌",
        -2: "稳步下跌",
        -3: "强势下跌",
    }
    return descriptions.get(trend_level, "横盘震荡")


class StockNewsGenerator:
    """股市新闻生成器

    接受类型化的 StockNewsConfig 配置对象。
    """

    def __init__(self, db: DB, config: StockNewsConfig):
        self.db = db
        self.config = config
        self.news_source = config.stock_news_source
        self.llm_prompt = config.stock_llm_prompt_template
        self.news_provider_id = config.stock_news_provider_id

    def generate_news(self, group_id, company_code, company_name, current_price, trend_level, description="", history_news=None):
        event_type = sample_event_type(self.config)
        impact = EVENT_IMPACTS[event_type]

        if self.news_source == "llm":
            content = self._generate_llm_news(company_code, company_name, current_price, trend_level, description, history_news)
            parsed_type = parse_event_from_news(content)
            if parsed_type != StockEventType.NEUTRAL:
                event_type = parsed_type
                impact = EVENT_IMPACTS[event_type]
            else:
                event_type = StockEventType.NEUTRAL
                impact = EVENT_IMPACTS[event_type]
        elif self.news_source == "both":
            if random.random() < 0.5:
                content = self._generate_llm_news(company_code, company_name, current_price, trend_level, description, history_news)
                parsed_type = parse_event_from_news(content)
                if parsed_type != StockEventType.NEUTRAL:
                    event_type = parsed_type
                    impact = EVENT_IMPACTS[event_type]
                else:
                    event_type = StockEventType.NEUTRAL
                    impact = EVENT_IMPACTS[event_type]
            else:
                content = generate_template_news(company_name, event_type)
        else:
            content = generate_template_news(company_name, event_type)

        jump_range = impact["immediate_jump"]
        immediate_jump = random.uniform(*jump_range)

        with self.db.session_scope() as session:
            news = StockNews(
                group_id=group_id,
                company_code=company_code,
                event_type=event_type.value,
                title=f"关于{company_name}的市场快讯",
                content=content.replace(f" [EVENT: {event_type.value}]", ""),
                source=self.news_source if self.news_source != "both" else ("llm" if "llm" in content else "template"),
                trend_shift=impact["trend_shift"],
                immediate_jump=immediate_jump,
                duration=impact["duration"],
                remaining_duration=impact["duration"],
            )
            session.add(news)

            volatility_boost = impact.get("volatility_boost", 1.0)
            event_state = StockEventState(
                group_id=group_id,
                company_code=company_code,
                event_type=event_type.value,
                trend_shift=impact["trend_shift"],
                immediate_jump=immediate_jump,
                remaining_duration=impact["duration"],
                volatility_boost=volatility_boost,
            )
            session.add(event_state)
            session.flush()
            news_id = news.id

        return {
            "id": news_id,
            "event_type": event_type,
            "trend_shift": impact["trend_shift"],
            "immediate_jump": immediate_jump,
            "duration": impact["duration"],
            "volatility_boost": impact.get("volatility_boost", 1.0),
            "content": content.replace(f" [EVENT: {event_type.value}]", ""),
        }

    def _generate_llm_news(self, company_code, company_name, current_price, trend_level, description="", history_news=None):
        prompt_template = self.llm_prompt if self.llm_prompt else DEFAULT_LLM_PROMPT
        history_text = ""
        if history_news:
            history_items = []
            for h in history_news:
                history_items.append(f"- {h['event_type']}: {h['content']}")
            history_text = "\n\n近期历史新闻:\n" + "\n".join(history_items)
        safe_name = company_name.replace('{', '{{').replace('}', '}}')
        safe_description = description.replace('{', '{{').replace('}', '}}')
        safe_history = history_text.replace('{', '{{').replace('}', '}}')
        prompt = prompt_template.format(
            name=safe_name,
            code=company_code,
            current_price=current_price,
            trend_description=get_trend_description(trend_level),
            description=safe_description,
            history=safe_history,
        )
        try:
            from astrbot.api.all import llm_tool_call
            if self.news_provider_id:
                result = llm_tool_call(prompt, provider_id=self.news_provider_id)
            else:
                result = llm_tool_call(prompt)
            return result if result else generate_template_news(company_name, StockEventType.NEUTRAL)
        except Exception:
            return generate_template_news(company_name, StockEventType.NEUTRAL)

    def get_active_events(self, group_id, company_code):
        with self.db.session_scope() as session:
            events = session.query(StockEventState).filter_by(
                group_id=group_id,
                company_code=company_code,
            ).filter(StockEventState.remaining_duration > 0).all()
            result = []
            for e in events:
                result.append({
                    "id": e.id,
                    "event_type": e.event_type,
                    "trend_shift": e.trend_shift,
                    "immediate_jump": e.immediate_jump,
                    "remaining_duration": e.remaining_duration,
                    "volatility_boost": e.volatility_boost,
                })
        return result

    def tick_events(self, group_id, company_code):
        with self.db.session_scope() as session:
            events = session.query(StockEventState).filter_by(
                group_id=group_id,
                company_code=company_code,
            ).filter(StockEventState.remaining_duration > 0).all()

            expired_ids = []
            for e in events:
                e.remaining_duration -= 1
                if e.remaining_duration <= 0:
                    expired_ids.append(e.id)

            session.flush()

            for eid in expired_ids:
                expired = session.query(StockEventState).filter_by(id=eid).first()
                if expired:
                    session.delete(expired)

    def apply_event_jump(self, group_id, company_code, jump):
        with self.db.session_scope() as session:
            company = session.query(StockCompany).filter_by(
                group_id=group_id,
                code=company_code,
            ).first()
            if company:
                company.current_price *= (1 + jump)
                company.current_price = max(0.01, company.current_price)
