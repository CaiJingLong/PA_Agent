# 各模型在 PA_Agent 场景下的置信度评价

> 调研日期：2026-07-26
> 来源会话：omp `019f9d42-a4af-7000-bdea-eef75d0f64f1`（2026-07-26 07:10）
> 评测模型清单：grok-4.5、gpt5.6-sol、gpt5.6-terra、opus4.8、opus5、glm5.2、deepseek-4-pro、swe-1.7、gpt5.4-mini、gpt5.4、gpt5.5

## PA_Agent 的需求画像

**中文 PA 术语理解 + 严格 JSON schema 遵守 + Brooks 价格行为判断深度 + 长上下文（160 根 K 线表）+ 循环调用成本敏感**。不是纯 coding agent，更偏"结构化领域判断 + 中文长文推理"。

## 架构事实（决定模型敏感度的设计）

两阶段流水线，模型只负责两件事：
- **Stage1 诊断 JSON**：`cycle_position` 9 选 1、`direction`、`gate_trace` 二元决策树、`bar_by_bar_summary` 逐棒 5 根、`key_signals`
- **Stage2 决策 JSON**：`decision`、`decision_trace`、`terminal`、`next_bar_prediction` 概率

### 降低模型差异的兜底（很厚）

- **JSON Schema 强约束** + **1800+ 行 normalizer**（`stage1_normalizer.py` 745 行、`stage2_normalizer.py` 1817 行）：把模型各种别名/中文/拼写错/同义词归一化，仅 `_BAR_ROLE_ALIASES` 就 30+ 条。弱模型输出 `reversal_attempt`/`延续`/`poor` 都能被救回标准枚举。
- **确定性决策节点引擎** `decision_nodes.py` 3072 行：§1.1 数据充分性、§2.3 方向投票（EMA slope + close gravity + HH/HL 结构 + trend-bar dominance + overlap ratio，阈值硬编码）、§2.4 AlwaysIn、§9/§11 信号棒——**这些不靠模型，程序用阈值算**。
- **retry 3 次** + **lenient 归一化**（当前 `settings.json` 配置）+ **策略文件知识注入**（`prompt_engineering/` 20+ 个 Brooks PA 框架 .txt，按 `cycle_position` 路由进 Stage2 prompt）：模型不需要"懂"太多，按框架填表。
- 当前已在用 `glm-5-2`，说明作者把模型当"填表工"，性价比优先。

### 放大模型差异的点（模型仍重要）

- `cycle_position` 9 类分类（尖峰/微通道/窄/正常/宽通道/趋势型TR/交易区间/极端TR）——需要 PA 经验，弱模型易把 `tight_channel` 当 `normal_channel`。
- `gate_trace` 每根 K 线的角色标注（signal/entry/confirmation/trap/climax）——真正的 PA 专业判断。
- `diagnosis_confidence` / `trade_confidence` / `estimated_win_rate` 概率校准——弱模型校准差。
- `bar_by_bar_summary` 逐棒语义——弱模型容易泛泛。

## 置信度评分

| 模型 | 综合置信度 | PA_Agent 适配点 | 风险 |
|---|---|---|---|
| **opus5** | ★★★★★ 95 | SWE-bench Verified 97% 领先，7/24 发布匹配 Fable 5 半价，推理深度顶级，JSON 纪律强 | 价格 $5/$25，循环跑成本高；中文 PA 术语非母语但够用 |
| **gpt5.6-sol** | ★★★★★ 93 | SWE-bench Verified 96.2%，OpenAI 当前旗舰，长任务推理最强 | 慢、贵；网络安全向调优对 PA 判断未必加分 |
| **gpt5.5** | ★★★★☆ 88 | xhigh 在 Terminal-Bench Hard / GDPval-AA 领先，推理强 | SWE-bench Pro 58.6 略低于 GLM-5.2，性价比一般 |
| **opus4.8** | ★★★★☆ 85 | SWE-bench Pro 69.2% 曾领先，结构化输出稳 | 已被 Opus 5 全面超越，无理由再用 |
| **grok-4.5** | ★★★★☆ 82 | Coding Agent Index 76（≈GPT-5.5 xhigh），reasoning low 就很强、省 token | 中文 PA 术语训练量存疑；BridgeBench reasoning 41.2% 中等 |
| **glm5.2** | ★★★★☆ 80 | **当前在用**。SWE-bench Pro 62.1 超 GPT-5.5，1M 上下文，中文母语，MIT 开源便宜，PA 术语最熟 | 开源模型 JSON 边界 case 偶发漂移（已有 normalizer 兜底） |
| **deepseek-4-pro** | ★★★☆☆ 72 | LiveCodeBench 93.5%，中文强，开源 | 1.6T 太重，本地部署慢；Reddit 评"midrange performance"，结构化判断不如 GLM-5.2 聚焦 |
| **gpt5.4** | ★★★☆☆ 70 | SWE-bench Pro 59.1%（xHigh），稳 | 已被 5.5/5.6 超越，无价格优势时没必要 |
| **gpt5.6-terra** | ★★★☆☆ 68 | 5.6 家族中档，平衡速度与深度 | 定位介于 Sol/Luna 之间，对 PA 这种单次中等复杂度任务性价比不如直接 Sol 或降到 5.5 |
| **swe-1.7** | ★★★☆☆ 65 | Cognition 专为 coding agent 调优，256K 上下文，便宜 | **PA_Agent 不是 SWE 任务**，coding-agent 调优反而可能让 JSON/中文 PA 推理偏弱；未验证中文 |
| **gpt5.4-mini** | ★★☆☆☆ 50 | 便宜快 | 结构化判断深度不足，cycle_position 9 分类、gate_trace 角色标注易漂移，靠 normalizer+retry 救一部分但 confidence 校准差 |

## 推荐分档

- **追求判断质量**：`opus5` ≈ `gpt5.6-sol` > `gpt5.5`。顶级之间差异小，都在天花板附近。
- **性价比首选**：继续 `glm5.2`——中文 PA 母语 + SWE-bench Pro 62.1 已超 GPT-5.5 + 开源便宜 + 已验证跑通。**没必要换**。
- **想试顶级又控成本**：`opus5`（半价 Fable 5）> `gpt5.6-sol`（更贵更慢）。
- **不推荐**：`gpt5.4-mini`（判断深度不够）、`swe-1.7`（任务类型不匹配）、`opus4.8`/`gpt5.4`（已被同代超越）。

## 关键提醒

当前 `coherence_checks` 全关 + `lenient` 归一化——这个配置**会压缩顶级模型的优势**，因为弱模型的错误被放行不重试。如果要拉开 glm5.2 vs opus5 的差距，开 `stage1_coherence_checks` + `trace_semantic_checks`，顶级模型稳定性优势才会显现成更少的 retry 和更准的 confidence。否则在当前宽松配置下，glm5.2 和 opus5 的**最终决策差异可能只有 5–10% 边界 case**，不一定值 30 倍价差。

## 顶级 vs mini 的预期分歧

在最终 `gate_result=proceed/wait` 的边界 case 上，顶级与 mini 预计有 **10–20% 分歧率**——对交易是实质性的。顶级之间（Opus5 vs GPT-5.6-Sol vs GPT-5.5）差异较小，都在 PA 判断的"天花板"附近，主要差在边界 case 和 confidence 校准的稳定性。
