# 🏦 AstrBot 财富中心插件

一个功能丰富的群聊经济系统插件，包含用户账户、签到奖励、股市交易、物资市场等模块。
（项目施工暂未完成）

## ✨ 功能特性

### 👤 用户账户系统
- 开户获得初始资金
- 查询个人账户余额和资产
- 用户间转账功能
- 财富排行榜（HTML图片展示）

### 📝 签到系统
- 每日签到获得奖励
- 连续签到递增奖励
- 随机浮动奖励金额

### 💬 发言奖励
- 聊天消息自动获得奖励
- 可配置冷却时间防止刷屏
- 每日奖励次数上限
- 过滤短消息和重复消息

### 📈 股市系统
- 多只股票实时价格波动
- 七级趋势系统（-3 到 +3）
- **股市总览**：行情+持仓+K线+新闻合并为一张HTML图片
- K线图可视化
- 市场新闻事件影响股价
- 买入/卖出交易
- 持仓管理
- 可选 A 股交易时段限制

### 📦 物资市场
- 每日刷新物资商品
- 物资价格随机波动
- **物资市场**：价格+库存合并为HTML图片展示
- 玩家间物资交易
- 背包管理

### 🔧 群管理功能
- 群白名单/黑名单过滤
- 跨群数据共享或独立
- 自动数据迁移

---

## 📋 指令列表

帮助系统采用分级显示，输入 `/fc` 查看一级目录，输入 `/fc stock`、`/fc goods`、`/fc admin` 查看对应二级指令。

### 一级目录（`/fc`）
| 指令 | 说明 |
|------|------|
| `/fc` | 显示帮助信息（一级目录） |
| `/fc open` | 开户（获得初始资金） |
| `/fc me` | 查看我的账户信息 |
| `/fc sign` | 每日签到 |
| `/fc transfer @用户 金额` | 转账给指定用户 |
| `/fc stock` | 查看股市二级指令 |
| `/fc goods` | 查看物资市场（图片） |
| `/fc rank` | 查看财富排行榜（图片） |
| `/fc admin` | 管理员指令（需权限） |

### 股市指令（`/fc stock`）
| 指令 | 说明 |
|------|------|
| `/fc stock market` | 股市总览（行情+持仓+K线+新闻，图片） |
| `/fc stock buy 代码 数量` | 买入股票 |
| `/fc stock sell 代码 数量` | 卖出股票 |
| `/fc stock assets` | 查看我的持仓 |
| `/fc stock kline 代码` | 查看单只股票K线图 |
| `/fc stock news` | 查看市场新闻 |

### 物资指令（`/fc goods`）
| 指令 | 说明 |
|------|------|
| `/fc goods` | 查看物资市场（价格+库存，图片） |
| `/fc goods buy ID 数量` | 买入物资 |
| `/fc goods sell ID 数量` | 卖出物资 |
| `/fc goods bag` | 查看我的背包 |
| `/fc goods trade @用户 ID 数量 单价` | 发起玩家交易 |
| `/fc goods accept ID` | 接受玩家交易 |

### 管理员指令（`/fc admin`）
| 指令 | 说明 |
|------|------|
| `/fc admin` | 查看管理员指令列表 |
| `/fc admin goods add 名称` | 添加物资 |
| `/fc admin goods setprice ID 最低价 最高价` | 设置价格范围 |
| `/fc admin goods setvolatility ID 波动率` | 设置波动率（0~1） |
| `/fc admin goods remove ID` | 删除物资 |
| `/fc admin stock open` | 开市 |
| `/fc admin stock close` | 休市 |

---

## ⚙️ 可视化配置项

### 群管理配置
| 配置项 | 说明 |
|--------|------|
| `group_filter_enabled` | 是否启用群过滤功能 |
| `group_whitelist` | 群白名单（仅这些群可用功能） |
| `group_blacklist` | 群黑名单（这些群不可用功能） |
| `cross_group_data` | 用户数据是否跨群共享 |

### 基础配置
| 配置项 | 说明 |
|--------|------|
| `currency_name` | 货币名称（如"金币"、"星币"） |
| `currency_icon` | 货币图标（Emoji） |
| `initial_balance` | 新用户初始资金 |
| `admin_ids` | 管理员 ID 列表 |
| `font_path` | 中文字体路径（用于K线图） |

### 签到配置
| 配置项 | 说明 |
|--------|------|
| `signin_reward_base` | 签到基础奖励 |
| `signin_reward_var` | 奖励随机浮动范围 |
| `signin_consecutive_bonus` | 连续签到递增奖励 |
| `signin_max_consecutive` | 连续签到奖励上限天数 |

### 发言奖励配置
| 配置项 | 说明 |
|--------|------|
| `chat_reward_enabled` | 是否启用发言奖励 |
| `chat_reward_amount` | 每条消息奖励金额 |
| `chat_reward_cooldown` | 奖励冷却时间（秒） |
| `chat_reward_daily_limit` | 每日奖励上限次数 |

### 股市配置
| 配置项 | 说明 |
|--------|------|
| `stock_enabled` | 是否启用股市模块 |
| `stock_companies` | 可交易股票列表 |
| `stock_volatility` | 价格波动率 |
| `stock_update_interval` | 价格更新间隔（秒） |
| `stock_fee_rate` | 交易手续费率 |
| `stock_trading_hours` | 是否限制交易时段 |
| `stock_news_enabled` | 是否启用市场新闻 |
| `stock_news_source` | 新闻来源（template/llm/both） |
| `stock_trend_enabled` | 是否启用趋势系统 |
| `stock_tech_analysis_enabled` | 是否启用技术分析 |

### 物资配置
| 配置项 | 说明 |
|--------|------|
| `goods_enabled` | 是否启用物资系统 |
| `goods_refresh_interval` | 市场刷新间隔（秒） |
| `goods_price_volatility` | 价格波动幅度 |
| `goods_user_trade_enabled` | 是否允许玩家交易 |
| `goods_user_trade_tax` | 玩家交易税率 |

---

## 📄 许可证

MIT License
