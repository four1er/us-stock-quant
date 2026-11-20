# us-stock-quant

美股量化研究工具（学习项目）：把交易想法写成规则，用历史数据回测验证，
并和买入持有基准对比。回测之外只接 IBKR 模拟盘（代码层面硬锁，无法连实盘，
见下方「模拟盘」）；投资决策由使用者本人作出。

## 快速开始

```bash
pip install -r requirements.txt

# 策略一：双均线趋势过滤（单标的）
python run_backtest.py --strategy sma --tickers SPY

# 策略二：动量轮动（多标的 ETF 池）
python run_backtest.py --strategy momentum --tickers SPY QQQ IWM EFA EEM TLT GLD
```

输出：指标对比表（总收益 / 年化 / 年化波动 / 夏普 / 最大回撤）+ `results/` 下的
净值曲线与回撤图。

## 结构

- `src/data.py` — 从 Nasdaq 公开接口拉取日线收盘价并本地缓存（Yahoo Finance 作备用源）
- `src/strategies.py` — 策略：输入价格，输出每日目标权重
- `src/backtest.py` — 向量化回测引擎
- `src/metrics.py` — 绩效指标
- `src/factors.py` — 横截面因子（价格类）：多窗口动量、低波动、距 52 周高点
- `factor_rank.py` — 给股票池逐只打分排名
- `scan_params.py` — 参数敏感性扫描（含样本内/样本外对比）
- `run_backtest.py` — 命令行入口
- `src/paper_ibkr.py` — IBKR 模拟盘执行层（端口锁 + DU 账户锁 + 整股数量）
- `run_paper.py` — 模拟盘入口（默认 dry-run，只算信号不下单）

## 回测的三条诚实性约定

1. **不用未来数据**：引擎把权重整体后移一天，今天收盘产生的信号只能赚明天的钱。
2. **算交易成本**：每次调仓按换手率收 `cost_bps`（默认单边 5 bps）。
3. **必须跑赢基准才算数**：任何策略都要和等权买入持有对比，跑不赢就没有存在的意义。

## 已知简化（后续迭代再补）

- 现金收益按 0 计；未处理退市股，标的池有幸存者偏差风险
- Nasdaq 收盘价做了拆股复权但未做分红复权，长期总收益略低于全收益口径；且接口最多返回约 10 年历史
- 日线收盘价成交，未建模滑点与盘中价格
- 参数（均线长度、动量窗口）有过拟合风险，换参数结果稳定才可信

## 路线图

- [x] 参数敏感性扫描（看策略对参数是否稳健）—— scan_params.py，含样本内/样本外对比
- [ ] 样本外验证（前半段调参、后半段只验证）
- [x] 因子打分 v1（价格类：动量/低波动/52 周高点）
- [ ] 接入财报数据，补价值（PE/PB/FCF 收益率）与质量（ROE/利润率/杠杆）因子
- [ ] 因子策略回测（按月调仓持有 Top N，对比基准）
- [x] 模拟盘执行层 v1（IBKR paper，dry-run + 安全锁）—— run_paper.py
- [ ] 模拟盘连续记录（每日信号 vs 成交对比，跑满数周再评估）

## 模拟盘（IBKR Paper Trading）

前置设置（只需一次，都在你本地电脑上）：

1. IBKR 官网 Client Portal → 设置 → Paper Trading Account，确认模拟账户已开通，
   记下模拟账户号（以 `DU` 开头）和模拟盘专用密码。模拟账户默认 $1,000,000 虚拟资金，
   本工具用 `--budget` 虚拟资金池做仓位计算，不动用账户全额。
2. 安装 IB Gateway（比 TWS 轻），登录时选 **Paper**，用模拟盘账号登录；
   在 Configure → API → Settings 勾选 Enable ActiveX and Socket Clients，
   端口保持模拟盘默认：Gateway 4002 / TWS 7497。
3. `pip install ib_async`（已在 requirements.txt 中）。

运行：

```bash
# dry-run：只算信号、打印计划订单、写 results/paper_log.csv，不连接不下单
python run_paper.py --ticker SPY --budget 10000

# 真正在模拟盘下单（Gateway 需已登录模拟盘）
python run_paper.py --ticker SPY --budget 10000 --port 4002 --execute
```

安全锁（src/paper_ibkr.py）：

- 只接受模拟盘端口 7497 / 4002，实盘端口 7496 / 4001 直接报错退出；
- 连接后校验所有托管账户都以 `DU` 开头，否则断开且不下单；
- 默认 dry-run，必须显式加 `--execute` 才下单。

注意：IBKR 的 API 不支持碎股（碎股只能在客户端手动下单），所以数量按整股计算：
`qty = floor(budget / price)`。预算小于 1 股价格时目标为 0 股 — 用 `--budget 100`
跑一次 dry-run 就能直观看到这个约束。模拟盘成交是按盘口模拟的，比实盘乐观，
只能验证执行链路，不能证明策略赚钱。
