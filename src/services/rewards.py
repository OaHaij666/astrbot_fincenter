"""聊天奖励服务。"""
from ..core.database import ChatRewardState, UserAccount, get_china_time


class ChatRewardService:
    def __init__(self, db, config):
        self.db = db
        self.config = config

    def process(self, group_id: str, user_id: str, user_name: str):
        cfg = self.config.chat_reward
        if not cfg.chat_reward_enabled:
            return

        with self.db.session_scope() as session:
            user = session.query(UserAccount).filter_by(
                group_id=group_id, user_id=user_id
            ).first()
            if not user:
                return

            now = get_china_time()
            today = now.strftime('%Y-%m-%d')
            state = session.query(ChatRewardState).filter_by(
                group_id=group_id, user_id=user_id
            ).first()

            if not state:
                state = ChatRewardState(
                    group_id=group_id,
                    user_id=user_id,
                    last_reward_time=now,
                    daily_count=1,
                    last_reset_date=today,
                )
                session.add(state)
                session.flush()
            else:
                if state.last_reset_date != today:
                    state.daily_count = 0
                    state.last_reset_date = today
                if state.daily_count >= cfg.chat_reward_daily_limit:
                    return
                if state.last_reward_time:
                    elapsed = (now - state.last_reward_time).total_seconds()
                    if elapsed < cfg.chat_reward_cooldown:
                        return

            user.add_balance(cfg.chat_reward_amount)
            user.add_earned(cfg.chat_reward_amount)
            state.last_reward_time = now
            state.daily_count += 1
