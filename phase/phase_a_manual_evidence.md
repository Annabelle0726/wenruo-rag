## Stored section values after the canary

* non-empty: 82 of 155; longest: 19 chars
* longest value: '8.2.9 卖方应向监造者提供以下资料'
* any value containing a sentence terminator: 0

## Manual top-10 evidence (lexical leg, same tokenizer as the benchmark)

### A. 根据 Q/GDW 73286.2-2026 查找单芯 220kV 海缆参数

| rank | chunk id | Part | section | kind | score | template | evidence |
|---|---|---|---|---|---|---|---|
| 1 | 3fb0a03b92cc | 部 |  | current_prefix | 17.523 |  |  |
| 2 | 9fa9e164a3e3 | 部 | 4 标准技术参数表 | current_prefix | 15.272 |  |  |
| 3 | 0eb621e18881 | 部 | 5 组件材料配置表 | current_prefix | 14.315 | yes |  |
| 4 | e56ec41ad181 | 部 | 5 组件材料配置表 | current_prefix | 13.996 |  |  |
| 5 | 3c3118930a4f | 部 | 5 组件材料配置表 | current_prefix | 12.725 |  |  |
| 6 | 5f81fce4a462 | 部 | 4 标准技术参数表 | current_prefix | 12.536 | yes |  |
| 7 | 53fc79c470c7 | 部 | 4 标准技术参数表 | current_prefix | 12.441 |  |  |
| 8 | 646ab90775aa | 部 | 3 与其他标准/文件的关系 | current_prefix | 12.333 |  |  |
| 9 | 43e96b415797 | 部 |  | current_prefix | 12.235 |  |  |
| 10 | 8065ad3f4096 | 部 |  | current_prefix | 11.908 |  |  |

### B. 220kV 单芯海底电缆的导体、内衬层、铠装层技术参数是多少？

| rank | chunk id | Part | section | kind | score | template | evidence |
|---|---|---|---|---|---|---|---|
| 1 | ff249ff52cf6 | 部 |  | current_prefix | 27.787 |  | **yes** |
| 2 | bac8e77cef90 | 部 |  | current_prefix | 21.011 |  | **yes** |
| 3 | a14eb9790726 | 部 |  | current_prefix | 17.774 | yes | **yes** |
| 4 | cc4443ca2f47 | 部 |  | current_prefix | 15.783 |  |  |
| 5 | a0bd8a6bde77 | 部 | 3 与其他标准/文件的关系 | current_prefix | 14.632 |  |  |
| 6 | 844f7e6b59d9 | 部 | 4 标准技术参数表 | current_prefix | 14.107 |  | **yes** |
| 7 | a6df5b0e1631 | ? |  | no_prefix | 14.049 |  | **yes** |
| 8 | bc2a6dfa5420 | 部 |  | current_prefix | 13.860 |  |  |
| 9 | c7347587e61a | 部 |  | current_prefix | 13.397 |  |  |
| 10 | 0eb621e18881 | 部 | 5 组件材料配置表 | current_prefix | 13.122 | yes |  |

### C. 220kV 三芯海底电缆结构参数

| rank | chunk id | Part | section | kind | score | template | evidence |
|---|---|---|---|---|---|---|---|
| 1 | 9fa9e164a3e3 | 部 | 4 标准技术参数表 | current_prefix | 14.949 |  |  |
| 2 | 07f34402b3cd | 部 | 4 标准技术参数表 | current_prefix | 12.337 |  |  |
| 3 | 3fb0a03b92cc | 部 |  | current_prefix | 11.994 |  |  |
| 4 | 5f81fce4a462 | 部 | 4 标准技术参数表 | current_prefix | 11.806 | yes |  |
| 5 | 8065ad3f4096 | 部 |  | current_prefix | 10.362 |  |  |
| 6 | 877394408084 | 部 | 4 标准技术参数表 | current_prefix | 10.325 | yes |  |
| 7 | 2f93d2671e6d | 部 | 3 与其他标准/文件的关系 | current_prefix | 10.029 |  |  |
| 8 | b9dfbc5a5c7a | 部 | 4 标准技术参数表 | current_prefix | 9.825 |  |  |
| 9 | 3746a7eb6438 | 部 | 4 标准技术参数表 | current_prefix | 9.761 |  |  |
| 10 | 127b63ce0572 | 部 | 4 标准技术参数表 | current_prefix | 9.632 | yes |  |

### D. 220kV 海底电力电缆内衬层厚度要求

| rank | chunk id | Part | section | kind | score | template | evidence |
|---|---|---|---|---|---|---|---|
| 1 | ff249ff52cf6 | 部 |  | current_prefix | 14.463 |  | **yes** |
| 2 | a14eb9790726 | 部 |  | current_prefix | 12.343 | yes | **yes** |
| 3 | 844f7e6b59d9 | 部 | 4 标准技术参数表 | current_prefix | 11.046 |  | **yes** |
| 4 | bac8e77cef90 | 部 |  | current_prefix | 10.338 |  | **yes** |
| 5 | cc4443ca2f47 | 部 |  | current_prefix | 10.218 |  |  |
| 6 | bc2a6dfa5420 | 部 |  | current_prefix | 8.588 |  |  |
| 7 | 255c187f4e22 | 部 |  | current_prefix | 8.166 | yes |  |
| 8 | af74d2eeaaf2 | 部 |  | current_prefix | 7.933 |  |  |
| 9 | a6df5b0e1631 | ? |  | no_prefix | 7.873 |  | **yes** |
| 10 | 109c57a8471b | 部 |  | current_prefix | 7.837 |  |  |

### E. 单芯 220kV 海缆

| rank | chunk id | Part | section | kind | score | template | evidence |
|---|---|---|---|---|---|---|---|
| 1 | e56ec41ad181 | 部 | 5 组件材料配置表 | current_prefix | 10.964 |  | **yes** |
| 2 | 0eb621e18881 | 部 | 5 组件材料配置表 | current_prefix | 10.270 | yes | **yes** |
| 3 | 53fc79c470c7 | 部 | 4 标准技术参数表 | current_prefix | 9.443 |  |  |
| 4 | 5f81fce4a462 | 部 | 4 标准技术参数表 | current_prefix | 8.828 | yes |  |
| 5 | b327a0201eba | 部 | 8.2.9 卖方应向监造者提供以下资料 | current_prefix | 6.553 |  |  |
| 6 | 455737939ddb | 部 |  | current_prefix | 6.549 |  | **yes** |
| 7 | 82de4ff203d9 | 部 |  | current_prefix | 6.549 |  | **yes** |
| 8 | 646ab90775aa | 部 | 3 与其他标准/文件的关系 | current_prefix | 6.444 |  | **yes** |
| 9 | 161e452916ad | 部 |  | current_prefix | 6.348 | yes | **yes** |
| 10 | 524f505a07c6 | 部 |  | current_prefix | 6.311 |  | **yes** |
