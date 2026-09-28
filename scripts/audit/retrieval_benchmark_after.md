# Retrieval benchmark AFTER the Phase A canary (lexical leg, read-only)

| query | P@1 | P@3 | P@5 | rank of the first expected passage | Recall@5 | Recall@10 | RR |
|---|---|---|---|---|---|---|---|
| A exact standard number | 2 | 2/3/2 | 0 | - | 0 | 0 | 0.000 |
| B natural language, no number | 1 | 1/1/2 | 1 | 3 | 1 | 1 | 0.333 |
| C three-core | 3 | 3/3/2 | 0 | - | 0 | 0 | 0.000 |
| D generic part | 1 | 1/2/3 | 1 | 1 | 1 | 1 | 1.000 |
| E disambiguation | 2 | 2/2/3 | 1 | 1 | 1 | 1 | 1.000 |
| F blank template | 2 | 2/3/2 | 1 | 5 | 1 | 1 | 0.200 |

**Recall@5 = 4/6 = 0.67; Recall@10 = 4/6 = 0.67; MRR = 0.422** (canary regression suite, NOT a statistical benchmark)

## A. 根据 Q/GDW 73286.2-2026 查找单芯 220kV 海缆参数

class: exact standard number; expected evidence: `标称截面` in part 2

| rank | chunk id | document | part | score | kind | evidence |
|---|---|---|---|---|---|---|
| 1 | 3fb0a03b92cc70d7 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 17.523 | current_prefix |  |
| 2 | 9fa9e164a3e3ca7a | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 15.272 | current_prefix |  |
| 3 | 0eb621e18881e734 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 14.315 | current_prefix |  |
| 4 | e56ec41ad1818b72 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 13.996 | current_prefix |  |
| 5 | 3c3118930a4f6e39 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 12.725 | current_prefix |  |
| 6 | 5f81fce4a4628ebf | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 12.536 | current_prefix |  |
| 7 | 53fc79c470c7775d | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 12.441 | current_prefix |  |
| 8 | 646ab90775aa14a5 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 12.333 | current_prefix |  |
| 9 | 43e96b415797394b | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 12.235 | current_prefix |  |
| 10 | 8065ad3f4096ca30 | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 11.908 | current_prefix |  |

## B. 220kV 单芯海底电缆的导体、内衬层、铠装层技术参数是多少

class: natural language, no number; expected evidence: `内衬层` in part 2

| rank | chunk id | document | part | score | kind | evidence |
|---|---|---|---|---|---|---|
| 1 | ff249ff52cf67152 | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 27.787 | current_prefix | yes |
| 2 | bac8e77cef90c8cf | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 21.011 | current_prefix | yes |
| 3 | a14eb97907268118 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 17.774 | current_prefix | **yes** |
| 4 | cc4443ca2f4783ac | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 15.783 | current_prefix |  |
| 5 | a0bd8a6bde77b17e | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 14.632 | current_prefix |  |
| 6 | 844f7e6b59d9764e | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 14.107 | current_prefix | yes |
| 7 | a6df5b0e1631dff2 | 电缆技术要求.pdf | ? | 14.049 | no_prefix | yes |
| 8 | bc2a6dfa54206eab | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 13.860 | current_prefix |  |
| 9 | c7347587e61a3532 | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 13.397 | current_prefix |  |
| 10 | 0eb621e18881e734 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 13.122 | current_prefix |  |

## C. 220kV 三芯海底电缆结构参数

class: three-core; expected evidence: `3×` in part 3

| rank | chunk id | document | part | score | kind | evidence |
|---|---|---|---|---|---|---|
| 1 | 9fa9e164a3e3ca7a | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 14.949 | current_prefix |  |
| 2 | 07f34402b3cdd4d9 | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 12.337 | current_prefix |  |
| 3 | 3fb0a03b92cc70d7 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 11.994 | current_prefix |  |
| 4 | 5f81fce4a4628ebf | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 11.806 | current_prefix |  |
| 5 | 8065ad3f4096ca30 | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 10.362 | current_prefix |  |
| 6 | 877394408084e1be | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 10.325 | current_prefix |  |
| 7 | 2f93d2671e6d7dfe | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 10.029 | current_prefix |  |
| 8 | b9dfbc5a5c7a6f15 | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 9.825 | current_prefix |  |
| 9 | 3746a7eb6438f7fd | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 9.761 | current_prefix |  |
| 10 | 127b63ce057208eb | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 9.632 | current_prefix |  |

## D. 220kV 海底电力电缆内衬层厚度要求

class: generic part; expected evidence: `内衬层` in part 1

| rank | chunk id | document | part | score | kind | evidence |
|---|---|---|---|---|---|---|
| 1 | ff249ff52cf67152 | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 14.463 | current_prefix | **yes** |
| 2 | a14eb97907268118 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 12.343 | current_prefix | yes |
| 3 | 844f7e6b59d9764e | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 11.046 | current_prefix | yes |
| 4 | bac8e77cef90c8cf | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 10.338 | current_prefix | **yes** |
| 5 | cc4443ca2f4783ac | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 10.218 | current_prefix |  |
| 6 | bc2a6dfa54206eab | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 8.588 | current_prefix |  |
| 7 | 255c187f4e228542 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 8.166 | current_prefix |  |
| 8 | af74d2eeaaf2c4a4 | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 7.933 | current_prefix |  |
| 9 | a6df5b0e1631dff2 | 电缆技术要求.pdf | ? | 7.873 | no_prefix | yes |
| 10 | 109c57a8471be6fa | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 7.837 | current_prefix |  |

## E. 单芯 220kV 海缆

class: disambiguation; expected evidence: `单芯` in part 2

| rank | chunk id | document | part | score | kind | evidence |
|---|---|---|---|---|---|---|
| 1 | e56ec41ad1818b72 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 10.964 | current_prefix | **yes** |
| 2 | 0eb621e18881e734 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 10.270 | current_prefix | **yes** |
| 3 | 53fc79c470c7775d | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 9.443 | current_prefix |  |
| 4 | 5f81fce4a4628ebf | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 8.828 | current_prefix |  |
| 5 | b327a0201ebabc7d | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 6.553 | current_prefix |  |
| 6 | 455737939ddb4a47 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 6.549 | current_prefix | **yes** |
| 7 | 82de4ff203d987f3 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 6.549 | current_prefix | **yes** |
| 8 | 646ab90775aa14a5 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 6.444 | current_prefix | **yes** |
| 9 | 161e452916ad5a75 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 6.348 | current_prefix | **yes** |
| 10 | 524f505a07c662f2 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 6.311 | current_prefix | **yes** |

## F. 220kV 单芯海缆接头规格 投标人填写

class: blank template; expected evidence: `接头规格` in part 2

| rank | chunk id | document | part | score | kind | evidence |
|---|---|---|---|---|---|---|
| 1 | 0eb621e18881e734 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 15.079 | current_prefix |  |
| 2 | 5f81fce4a4628ebf | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 13.742 | current_prefix |  |
| 3 | 3fb0a03b92cc70d7 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 13.015 | current_prefix |  |
| 4 | af100b79a9e9734d | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 12.621 | current_prefix |  |
| 5 | e518c08d493651a2 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 12.339 | current_prefix | **yes** |
| 6 | 3b9b07af5d882385 | 抽水蓄能电站工程330kV电力电缆系统采购标准++专用技术规范.doc | ? | 11.979 | no_prefix | yes |
| 7 | e56ec41ad1818b72 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 10.964 | current_prefix |  |
| 8 | 9fa9e164a3e3ca7a | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用 | 3 | 10.847 | current_prefix |  |
| 9 | 96910118fe4e3fda | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 1 | 10.836 | current_prefix |  |
| 10 | d66a18e51bec0e16 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用 | 2 | 10.373 | current_prefix |  |

## What this measures and what it does not

* It measures the LEXICAL leg over `content_ltks`, which is exactly what Phase A rewrites.
* The dense leg is NOT measured here and cannot change: Phase A does not touch `q_*_vec`.
* The fused (hybrid) score is therefore expected to move only through its lexical term; the
  after-run repeats this exact script on the same index, so the two tables are comparable.
* `part` comes from the file name (or the header's designation), so a passage with neither shows `?`.