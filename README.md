# us-stock-quant

美股量化研究工具（学习项目）：把交易想法写成规则，用历史数据回测验证，
并和买入持有基准对比。只做研究与回测，不做实盘下单；投资决策由使用者本人作出。

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
- `run_backtest.py` — 命令行入口

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
- [ ] 接入选股因子（价值/质量/动量打分）
- [ ] 模拟盘（paper trading）记录
