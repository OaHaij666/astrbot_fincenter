"""帮助内容构建器。"""


def build_main_help_sections():
    return [
        {
            'section_name': '👤 账户',
            'commands': [
                {'cmd': '/fc open', 'desc': '开户'},
                {'cmd': '/fc me', 'desc': '我的账户'},
                {'cmd': '/fc sign', 'desc': '每日签到'},
                {'cmd': '/fc transfer <@用户> <金额>', 'desc': '转账'},
                {'cmd': '/fc rank [条数]', 'desc': '财富排行榜'},
            ],
        },
        {
            'section_name': '📈 股市',
            'commands': [
                {'cmd': '/fc stock market', 'desc': '股市总览'},
                {'cmd': '/fc stock buy <代码> <数量>', 'desc': '买入股票'},
                {'cmd': '/fc stock sell <代码> <数量>', 'desc': '卖出股票'},
                {'cmd': '/fc stock assets', 'desc': '我的持仓'},
                {'cmd': '/fc stock kline <代码> [条数]', 'desc': 'K线图'},
                {'cmd': '/fc stock news', 'desc': '市场新闻'},
            ],
        },
        {
            'section_name': '📦 物资',
            'commands': [
                {'cmd': '/fc goods market', 'desc': '物资市场'},
                {'cmd': '/fc goods buy <ID> <数量>', 'desc': '买入物资'},
                {'cmd': '/fc goods sell <ID> <数量>', 'desc': '卖出物资'},
                {'cmd': '/fc goods backpack', 'desc': '我的背包'},
            ],
        },
    ]


def build_main_help_text():
    lines = [
        "💰 财富中心",
        "━━━━━━━━━━━━━━",
        "👤 账户:",
        "  /fc open                    开户",
        "  /fc me                      我的账户",
        "  /fc sign                    每日签到",
        "  /fc transfer <@用户> <金额>   转账",
        "  /fc rank [条数]              财富排行榜",
        "",
        "📈 股市:",
        "  /fc stock market            股市总览",
        "  /fc stock buy <代码> <数量>   买入",
        "  /fc stock sell <代码> <数量>  卖出",
        "  /fc stock assets            我的持仓",
        "  /fc stock kline <代码> [条数] K线图",
        "  /fc stock news              市场新闻",
        "",
        "📦 物资:",
        "  /fc goods market            物资市场",
        "  /fc goods buy <ID> <数量>    买入物资",
        "  /fc goods sell <ID> <数量>   卖出物资",
        "  /fc goods backpack          我的背包",
    ]
    return "\n".join(lines)
