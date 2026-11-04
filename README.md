# AUS-NEM-SA1

面向澳大利亚国家电力市场（NEM）南澳区域 `SA1` 的五分钟数据、市场知识与电价预测入门项目。

## 项目范围

- 区域：`SA1`
- 主要时间粒度：5 分钟
- 首版完整归档窗口：2023-07 至 2026-06
- 核心数据：区域现货价格、区域汇总、运营负荷、联络线
- 扩展数据：DUID 级 SCADA、30 分钟 Pre-dispatch、5 分钟 P5MIN、天气
- 核心原则：所有特征必须满足 `available_time <= prediction_cutoff`

## 仓库内容

| 文件 | 用途 |
| --- | --- |
| `download_sa1_nem_data.py` | 按月下载并过滤 AEMO NEMWeb 数据 |
| `sa1_duid_fuel_map.csv` | SA1 DUID 与燃料类型映射 |
| `AEMO_SA1_Data_Dictionary.xlsx` | 字段含义、单位、来源、发布时间、预测可用性和泄漏风险 |
| `NEM_Market_Overview_CN.docx` | 中文 NEM 市场笔记 |
| `NEM_Market_Overview_EN.docx` | English market overview |
| `SA1_core_2023-07_2026-06_QA.csv` | 三年 Core 数据质量检查结果 |
| `SA1_weather_QA.csv` | 天气数据质量检查结果 |

## 快速开始

仅下载 Core 数据：

```bash
python download_sa1_nem_data.py \
  --start 2023-07 \
  --end 2026-06 \
  --profile core \
  --output data_sa1
```

下载完整档位并加入天气：

```bash
python download_sa1_nem_data.py \
  --start 2023-07 \
  --end 2026-06 \
  --profile full \
  --weather both \
  --output data_sa1
```

脚本仅使用 Python 标准库。`full` 档位数据量较大，建议按月增量运行。

## 数据与泄漏控制

1. NEM 自 2021-10-01 起采用五分钟结算，本项目保留五分钟事实层。
2. 未来真实 RRP、真实负荷、真实 SCADA 和真实联络线潮流只能作为标签或事后核验，不能作为预测特征。
3. Pre-dispatch 必须保留目标时刻和发布版本；只选择预测截点之前已发布的版本。
4. 实况再分析天气仅用于探索或回测；正式日前模型应使用历史固定 lead 的天气预报版本。
5. 验证采用滚动时间切分，不进行随机打乱。

## 数据文件说明

本仓库不直接托管三年完整市场数据和天气数据。原因是文件体积大、更新频繁，且 AEMO 原始数据可由下载脚本复现。仓库仅保留代码、映射、QA、说明文档与后续模型成果。

## 官方来源

- [AEMO NEM Data](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem)
- [NEMWeb](https://visualisations.aemo.com.au/aemo/nemweb/)
- [Operational Demand Data](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/operational-demand-data)
- [Pre-dispatch](https://www.aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem/market-management-system-mms-data/pre-dispatch)

## 更新约定

后续新增的数据处理、特征工程、模型、验证结果和文档将继续提交到本仓库。密钥、本地绝对路径、临时文件和完整原始数据不会上传。
