# 白嫖雷达 · Free Radar

自动巡检大模型厂商、Harness/Agent 厂商、云 GPU 与云厂商的官方定价/试用页，抽取**当前真实存在**的免费额度与试用条款，生成一个可筛选的静态站点。

## 它解决什么

免费的额度散落在几十个定价页里，且**经常变**：今天免费的模型明天收费、试用金到期、学生计划改条款。人工清单更新不过来，二手汇总又经常编数字。

这个站点的取舍是：**只展示官方原文证据句，不猜额度**。每条 offer 形如

```
Gemini API 有免费层：输入输出均免费，额度按模型区分｜Free of charge
```

前半句是模型抽取的摘要，后半句是**逐字来自官方页面**的证据原文。抽取器会校验 evidence 必须能在抓取到的文本里 substring 命中，否则丢弃——这是防幻觉的硬约束。

## 架构

```
sources.yaml      # 30 个数据源：id / 名称 / 类型(api|harness|agent|gpu|student) / 地区
radar.py          # 抓取 → 正则预筛 → LLM 抽取(带证据校验) → SQLite → docs/data.json
extract_llm.py    # DeepSeek 抽取器，evidence 不在原文就丢
docs/index.html   # 静态站点（原生 JS，无构建）
docs/data.json    # 每次运行重写
radar.db          # 历史：first_seen / last_seen / status，用于变更检测
```

变更检测：同一 (source, snippet) 的记录持续存在就刷新 `last_seen`；14 天没再出现的标 `stale`；首次出现的标 `NEW`。抓取连续失败会在页脚列出。

## 运行

```bash
python3 radar.py          # 需要 ~/.hermes/config.yaml 里有 deepseek provider
```

依赖：`pyyaml`（其余标准库）。

## 部署

GitHub Pages，`main` 分支 `/docs` 目录。每次运行 `radar.py` 后提交 `docs/` 即可。

## 边界（明确不做）

- 不收多账号刷额度、临时邮箱注册、绕过地区限制、账号/Key 买卖——违反 ToS，也会把使用者的身份与凭据置于风险中；
- 不做额度代充、不转售 API key；
- 所有条款以官方页面为准，本站只做索引与变更提醒。
