# FinCenter 指令文档

所有指令均以 `/fc` 为前缀，通过 `@filter.command_group("fc")` 注册。

---

## 一、账户指令

### `/fc open`

开户。为自己或他人创建金融中心账户。

- **对自己开户**：`/fc open` — 创建账户，获得初始余额
- **代他人开户**：`/fc open @用户` — 支付代开户费，为目标用户创建账户

**Handler**: `src/handlers/account.py` → `AccountHandler.handle_open()`

---

### `/fc me`

查看我的账户信息。

- 显示：余额、累计获得、累计消费、开户时间
- 若股市启用则附加股票持仓
- 若物资启用则附加物资背包

**Handler**: `src/handlers/account.py` → `AccountHandler.handle_me()`

---

### `/fc sign`

每日签到。

- 基础奖励 + 随机浮动
- 连续签到有额外加成（上限由配置控制）
- 每天只能签到一次

**Handler**: `src/handlers/account.py` → `AccountHandler.handle_sign()`

---

### `/fc transfer <@用户> <金额>`

转账。

- 必须 @目标用户，不能转给自己
- 双方必须都已开户
- 金额必须大于0

**Handler**: `src/handlers/account.py` → `AccountHandler.handle_transfer()`

---

### `/fc rank [条数]`

财富排行榜。

- 排名按总财富（余额 + 股票市值 + 物资市值）降序
- 默认显示前20名，可指定5~50条
- 以图片形式返回

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle_rank()`

---

## 二、股市指令 `/fc stock`

> 股市模块启用时可用，否则提示"股市模块未启用"。

### `/fc stock`

无子命令时显示股市帮助（图片），列出所有子命令。

**Handler**: `src/handlers/stock.py` → `StockHandler.handle()`

---

### `/fc stock market`

股市总览（图片）。

- 包含：行情列表、我的持仓、K线小图、今日新闻

**Handler**: `src/handlers/stock.py` → `StockHandler.handle()` sub=`"market"`

---

### `/fc stock buy <代码> <数量>`

买入股票。

- 代码不区分大小写
- 需先开户，余额充足

**Handler**: `src/handlers/stock.py` → `StockHandler.handle()` sub=`"buy"`

---

### `/fc stock sell <代码> <数量>`

卖出股票。

- 代码不区分大小写
- 必须持有该股票

**Handler**: `src/handlers/stock.py` → `StockHandler.handle()` sub=`"sell"`

---

### `/fc stock assets`

查看我的股票持仓。

- 显示：代码、持有量、成本价、现价、市值、盈亏百分比

**Handler**: `src/handlers/stock.py` → `StockHandler.handle()` sub=`"assets"`

---

### `/fc stock kline <代码> [条数]`

查看K线图（图片）。

- 默认显示60条（由配置 `stock_kline_candles` 决定），可指定10~200条
- 含技术分析支撑/阻力位

**Handler**: `src/handlers/stock.py` → `StockHandler.handle()` sub=`"kline"`

---

### `/fc stock news`

查看今日市场新闻。

- 按时间顺序列出新闻事件，带事件类型图标（🚀📈↗➡️↘📉💥⚠️）

**Handler**: `src/handlers/stock.py` → `StockHandler.handle()` sub=`"news"`

---

### `/fc stock event [代码]`

手动触发市场新闻事件（**管理员专用**）。

- 不指定代码则随机选股，指定则针对特定代码触发
- 事件类型随机（major_positive ~ major_negative, volatility）

**Handler**: `src/handlers/stock.py` → `StockHandler.handle()` sub=`"event"`

---

## 三、物资指令 `/fc goods`

> 物资市场模块启用时可用，否则提示"物资市场模块未启用"。

### `/fc goods`

无子命令时显示物资帮助（图片），列出所有子命令。

**Handler**: `src/handlers/goods.py` → `GoodsHandler.handle()`

---

### `/fc goods market`

物资市场总览（图片）。

- 列出所有物资的当前价格、走势
- 显示我的持有量

**Handler**: `src/handlers/goods.py` → `GoodsHandler.handle()` sub=`"market"`

---

### `/fc goods buy <物资ID> <数量>`

买入物资。

- 需开户，余额充足

**Handler**: `src/handlers/goods.py` → `GoodsHandler.handle()` sub=`"buy"`

---

### `/fc goods sell <物资ID> <数量>`

卖出物资。

- 必须持有该物资

**Handler**: `src/handlers/goods.py` → `GoodsHandler.handle()` sub=`"sell"`

---

### `/fc goods backpack`

查看我的物资背包。

- 显示：图标、名称、持有量、单价、市值、总市值

**Handler**: `src/handlers/goods.py` → `GoodsHandler.handle()` sub=`"backpack"`

---

## 四、管理员指令 `/fc admin`

> 仅 `basic.admin_ids` 中的用户可调用，否则提示"仅限管理员使用"。

### `/fc admin`

无子命令时显示管理员帮助（图片），列出所有管理子命令。

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle()`

---

### `/fc admin balance <@用户> <金额>`

为用户增减余额。

- 正数增加，负数减少
- 可通过 @ 或直接输入 QQ 号指定用户

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle()` sub=`"balance"`

---

### `/fc admin setbalance <@用户> <金额>`

直接设置用户余额。

- 将目标用户余额设为指定值

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle()` sub=`"setbalance"`

---

### `/fc admin stock open`

强制开市。

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle()` sub=`"stock"` action=`"open"`

---

### `/fc admin stock close`

强制休市。

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle()` sub=`"stock"` action=`"close"`

---

### `/fc admin stock auto`

恢复股市自动交易模式（取消手动覆盖）。

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle()` sub=`"stock"` action=`"auto"`

---

### `/fc admin goods add <物资ID> <名称> <基准价> [图标] [最低价] [最高价] [波动率]`

添加新物资。

- 必填：物资ID、名称、基准价
- 可选：图标（默认📦）、最低价（默认基准价×0.1）、最高价（默认基准价×10）、波动率（默认使用配置值）

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle()` sub=`"goods"` action=`"add"`

---

### `/fc admin goods remove <物资ID>`

移除物资。

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle()` sub=`"goods"` action=`"remove"`

---

### `/fc admin goods setprice <物资ID> <价格>`

手动设置物资当前价格。

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle()` sub=`"goods"` action=`"setprice"`

---

### `/fc admin goods setvolatility <物资ID> <波动率>`

设置物资价格波动率。

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle()` sub=`"goods"` action=`"setvolatility"`

---

### `/fc admin goods reset`

重置所有物资价格至基准价。

**Handler**: `src/handlers/admin.py` → `AdminHandler.handle()` sub=`"goods"` action=`"reset"`

---

## 五、隐式功能（非指令触发）

### 聊天奖励

群内发言时自动触发，满足条件时（已开户、冷却时间、每日上限）自动发放货币奖励。

实现：`src/main.py` → `FinCenterPlugin._process_chat_reward()`

### 付费指令

匹配配置的付费指令前缀时，自动扣费执行。

实现：`src/main.py` → `FinCenterPlugin._check_paid_command()`

---

## 指令树总览

```
/fc
├── help          # 帮助
├── open          # 开户
├── me            # 我的账户
├── sign          # 每日签到
├── transfer      # 转账
├── rank          # 财富排行榜
├── stock         # 股市帮助
│   ├── market    # 股市总览
│   ├── buy       # 买入股票
│   ├── sell      # 卖出股票
│   ├── assets    # 我的持仓
│   ├── kline     # K线图
│   ├── news      # 市场新闻
│   └── event     # 触发市场事件(管理员)
├── goods         # 物资帮助
│   ├── market    # 物资市场总览
│   ├── buy       # 买入物资
│   ├── sell      # 卖出物资
│   └── backpack  # 我的背包
└── admin         # 管理员帮助(管理员)
    ├── balance           # 增减余额
    ├── setbalance        # 设置余额
    ├── stock open|close|auto  # 股市控制
    └── goods add|remove|setprice|setvolatility|reset  # 物资管理
```
