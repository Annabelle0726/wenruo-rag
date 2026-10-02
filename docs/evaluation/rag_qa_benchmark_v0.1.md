# Wenruo-RAG Retrieval QA Benchmark v0.1

## Purpose

This benchmark evaluates retrieval stability and answer grounding after retrieval, rerank, metadata, or indexing changes.

The benchmark is based on the following knowledge sources:

- Q/GDW 73285-2026 海底电力电缆系统采购标准
- Q/GDW 73286-2026 海底电力电缆系统采购标准系列
- 110kV / 220kV 海底电力电缆系统技术规范

## Evaluation principle

The benchmark is frozen as a regression baseline.

Any future retrieval optimization should compare against this set instead of relying on individual QA examples.

Evaluation should record:

- query
- effective query
- retrieval candidates
- final context window
- answer grounding
- missing evidence cases

---

# QA-001 导体规格范围

## Question

根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？

## Expected evidence

- Q/GDW 73286.2-2026 表 1
- Q/GDW 73286.3-2026 表 1

## Expected facts

Single-core:

- 1×400 mm² ～ 1×2000 mm²
- 10 specifications

Three-core:

- 3×400 mm² ～ 3×1600 mm²
- 8 specifications

Category:

- table retrieval
- exact numeric retrieval

---

# QA-002 标准体系结构

## Question

Q/GDW 73285-2026 标准体系由哪些部分构成？各自适用范围是什么？

## Expected evidence

- Part 1 通用技术规范
- Part 2 单芯海底电力电缆系统专用技术规范
- Part 3 三芯海底电力电缆系统专用技术规范

## Expected facts

The answer should explain the relationship between general requirements and dedicated specifications.

Category:

- document hierarchy
- cross-document reasoning

---

# QA-003 新旧版本修订

## Question

2026版标准相比2019旧版标准，主要进行了哪些重要修订？

## Expected facts

- 更改导体结构名称
- 删除绝缘平均厚度要求

Category:

- version comparison
- change detection

---

# QA-004 附件寿命与结构

## Question

标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求？

## Expected evidence

- 终端设计使用年限参数
- 附件结构资料要求

## Expected facts

- 终端设计使用年限不少于30年
- 终端类型包括户外终端、GIS终端、油浸终端
- 接头包括预制直通接头、绝缘接头等结构资料要求

Category:

- mixed retrieval
- missing evidence detection

---

# QA-005 耐压试验

## Question

110kV海缆系统的耐压试验标准（出厂与安装后）是如何规定的？

## Expected facts

Factory test:

- 160kV / 30min

After installation test:

- 128kV / 60min

Category:

- parameter retrieval
- engineering specification

---

# Baseline record template

Image:

- image digest / release tag

Retrieval configuration:

- embedding model:
- rerank:
- top k:
- metadata scope:

Results:

| QA | Result | Notes |
| --- | --- | --- |
| QA-001 | | |
| QA-002 | | |
| QA-003 | | |
| QA-004 | | |
| QA-005 | | |
