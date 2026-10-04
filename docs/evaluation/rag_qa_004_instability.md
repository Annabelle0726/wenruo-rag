# QA-004 instability diagnostic (read-only)

- question: 标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求
- captured at: 2026-10-02T01:26:15Z (UTC)
- knowledge base: 9463d93eb97511f1938f2592e9bc6fe4; assistant: 5c8c249eb8e411f180e20bf412cbc55e
- parameters (unchanged, read from the assistant row): {"similarity_threshold": 0.55, "vector_similarity_weight": 0.5, "final_top_n": 12, "knn_top_k": 1024, "rerank_candidates_count": 30}

## Errors encountered (reported, not hidden)

- rerank: TypeError: object tuple can't be used in 'await' expression
- rerank: TypeError: object tuple can't be used in 'await' expression
- rerank: TypeError: object tuple can't be used in 'await' expression

## P1 embedding determinism

- runs: 3; dims: [3072, 3072, 3072]
- byte-identical across runs: **True**; max |Δ| component: 0.0

## P2 decomposition stability (the deployed pipeline asks the chat model for sub-queries)

- sub-query counts across 6 runs: {2: 6}
- distinct route lists: **1** (stable: True)

  - run 1: 标准对电缆附件（终端与接头）的设计使用寿命有何要求 | 标准对电缆附件（终端与接头）的结构有何要求
  - run 2: 标准对电缆附件（终端与接头）的设计使用寿命有何要求 | 标准对电缆附件（终端与接头）的结构有何要求
  - run 3: 标准对电缆附件（终端与接头）的设计使用寿命有何要求 | 标准对电缆附件（终端与接头）的结构有何要求
  - run 4: 标准对电缆附件（终端与接头）的设计使用寿命有何要求 | 标准对电缆附件（终端与接头）的结构有何要求
  - run 5: 标准对电缆附件（终端与接头）的设计使用寿命有何要求 | 标准对电缆附件（终端与接头）的结构有何要求
  - run 6: 标准对电缆附件（终端与接头）的设计使用寿命有何要求 | 标准对电缆附件（终端与接头）的结构有何要求

## P3 retrieval stability (identical question, repeated production calls)

- runs: 5; distinct windows: **1**; identical order in all runs: **True**
- pairwise window Jaccard: mean **1.0**, min 1.0
- runs whose window held BOTH halves (design life AND structure): **0/5**
- design-life passages per run: [0, 0, 0, 0, 0]
- structure passages per run: [4, 4, 4, 4, 4]
- distinct route-sets reaching the window: 1

| run | n | design-life | structure | both | voltage mix | docs (110/220) |
|---|---|---|---|---|---|---|
| 1 | 12 | 0 | 4 | False | {"110kV": 6, "220kV": 6} | 6 |
| 2 | 12 | 0 | 4 | False | {"110kV": 6, "220kV": 6} | 6 |
| 3 | 12 | 0 | 4 | False | {"110kV": 6, "220kV": 6} | 6 |
| 4 | 12 | 0 | 4 | False | {"110kV": 6, "220kV": 6} | 6 |
| 5 | 12 | 0 | 4 | False | {"110kV": 6, "220kV": 6} | 6 |

## P4 rerank determinism (one fixed set of passages, re-scored)

- passages re-scored: 12; runs: 0
- identical scores across runs: **None**; max |Δ|: None
- top-3 order stable: None; per-run top-3: None

## P5 controlled scope variants

### original

- question: 标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求
- runs: 3; distinct windows: 1; mean pairwise Jaccard: 1.0
- runs holding BOTH halves: **0/3**
- design-life passages per run: [0, 0, 0]
- structure passages per run: [4, 4, 4]
- voltage mix per run: [{"110kV": 6, "220kV": 6}, {"110kV": 6, "220kV": 6}, {"110kV": 6, "220kV": 6}]
- documents touched: 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf; 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电力电缆系统专用技术规范; 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电力电缆系统专用技术规范; 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf; 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范; 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用技术规范

| # | chunk id | voltage | designation | section | page | design-life | structure | rerank | fused | routes |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `d445cd023c8bb822` | 110kV | Q/GDW 13285.1-2019 | 5.1.12 外被层 | 10 |  |  | 0.844674 | 0.557755 | 1 |
| 2 | `109c57a8471be6fa` | 220kV | Q/GDW 73286.1 | 5.2.3 修理接头 | 10 |  |  | 0.687449 | 0.59306 | 3 |
| 3 | `7a8dca9e22d2bce1` | 110kV | Q/GDW 13285.1-2019 | 5.1.12 外被层 | 10 |  |  | 0.676314 | 0.604638 | 3 |
| 4 | `0eb621e18881e734` | 220kV | Q/GDW 73286.2 | 5 组件材料配置表 | 18 |  | Y | 0.760998 | 0.606618 | 3 |
| 5 | `5f81fce4a4628ebf` | 220kV | Q/GDW 73286.3 | 4 标准技术参数表 | 17 |  | Y | 0.720652 | 0.607223 | 3 |
| 6 | `96910118fe4e3fda` | 220kV | Q/GDW 73286.1 | 5.2.3 修理接头 | 10 |  |  | 0.593575 | 0.555773 | 1 |
| 7 | `2bd4a61a1cc33692` | 110kV | GB/T 21429-2008 | 6.4 型式试验 | 14 |  |  | 0.484793 | 0.585525 | 2 |
| 8 | `c910968a4a1cbc53` | 110kV | Q/GDW 73285.2-2026 | - | 17 |  | Y | 0.532761 | 0.572829 | 3 |
| 9 | `5d52c3f6cbe9e4c5` | 220kV | Q/GDW 73286.1 | 6.6.12 局部放电试验 | 17 |  |  | 0.239407 | 0.57865 | 2 |
| 10 | `6d9ec190a4f4179d` | 110kV | Q/GDW 13285.1-2019 | - | 4 |  |  | 0.215679 | 0.596505 | 3 |
| 11 | `0cd7b74071f4c9b1` | 110kV | (no prefix) | - | 17 |  | Y | 0.225151 | 0.575945 | 3 |
| 12 | `ea4a0fbc49651bc5` | 220kV | Q/GDW 73286.1 | - | 4 |  |  | 0.15258 | 0.594891 | 3 |

context: 10171 chars

```
根据知识库中的标准文件，关于海底电力电缆附件（终端与接头）的设计使用寿命和结构方面，有下面这些要求：

**一、关于设计使用寿命**

知识库中的标准文本并没有直接给出电缆附件设计使用寿命的具体年限数值。不过，在专用技术规范中要求投标人提供一系列与寿命相关的计算资料，包括：海缆的**短期过载能力曲线**，并且要说明**全年过载时间为多少不至于影响海缆寿命**，同时还需要提供**载流量计算书**等。这些资料虽然是针对海缆本体的，但附件作为海缆系统的一部分，其设计也需要与之匹配。

如果您需要明确的使用寿命年限要求，建议查阅招标技术文件或与设计方确认，标准文本中暂未查到具体年限规定。

**二、关于结构要求**

结构方面的要求还是比较丰富的，我按终端和接头分别来说：

**1. 电缆终端**

- **电气与防水性能**：110kV和220kV标准都明确规定，电缆附件的电气和防水性能**不低于海缆本体**。
- **户外终端型式**：一般采用**瓷套管终端**，产品应符合JB/T 11167.3的要求，污秽等级为**e级或更严**（最小统一爬电比距53.7 mm/kV）。人员密集区域可采用**复合套管终端**，以玻璃纤维增强环氧管为衬芯。
- **底座绝缘子**：户外终端应具有使终端底座与支架相绝缘的底座绝缘子，而且安装方式宜设计成更换该绝缘子时**不需吊起或拆卸终端**。
- **配套要求**：附件应采用与其电缆型式试验时配套的附件。

**2. 工厂接头**

- 导体焊接抗拉强度：截面800 mm²及以下**不小于180 MPa**，800 mm²以上**不小于170 MPa**。
- 工厂接头的铅套外径**不超过电缆铅套外径的10%**。
- 恢复绝缘厚度不应超过本体绝缘厚度的10%。
- 导体屏蔽和绝缘屏蔽的体积电阻率应与海缆本体相同，恢复表面要求光滑、平整。
- 接头外应有醒目的永久标志，长度不小于5 m。

**3. 修理接头**

修理接头分两种结构型式：

- **软接头型**：内部设计类似于工厂接头，外径近似于电缆外径。需要特别注意的是，金属铠装线的恢复处理要保证接头处**柔性连接并具备足够强度**，避免铠装线松弛导致敷设时电缆芯受到过度张力。
- **刚性修理接头**：内部通常采用预模制或预装配结构，也可采用类似工厂接头的设计。外部设计应具有良好的机械性能和**防海水腐蚀性能**，能耐受敷设和运行时的机械弯曲、机械张力和扭转要求，金属保护盒宜采用**高强度不锈钢材料**制成。

另外，修理接头应具有完善的**防水密封结构件**，并做好防水浇注剂灌封工艺措施。如果是光纤复合海底电缆，修理接头的整体水密封构件中还应包含**光纤单元接线盒**，并做防水灌封处理，接线盒应符合YD/T 814.3的规定。

**三、需要提醒的一点**

知识库中关于附件结构的技术要求，在110kV和220kV标准中内容基本一致，主要引用的是JB/T 11167.3（110kV及以下）和GB/T 32346.3（220kV）这两个附件标准。如果涉及特殊工况或有其他协商约定，标准中也留有一定的弹性空间，比如"允许采用其他合适结构的外被层"等表述，附件方面同样可以参考供需双方协商确定的原则来灵活处理。
```

### 110kV_scoped

- question: Q/GDW 73285-2026（110kV）标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求
- runs: 3; distinct windows: 1; mean pairwise Jaccard: 1.0
- runs holding BOTH halves: **0/3**
- design-life passages per run: [4, 4, 4]
- structure passages per run: [0, 0, 0]
- voltage mix per run: [{"110kV": 12}, {"110kV": 12}, {"110kV": 12}]
- documents touched: 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf; 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电力电缆系统专用技术规范; 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电力电缆系统专用技术规范

| # | chunk id | voltage | designation | section | page | design-life | structure | rerank | fused | routes |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `ed742b19b80b251d` | 110kV | Q/GDW 73285.3-2026 | - | 4 |  |  | 0.978862 | 0.531725 | 4 |
| 2 | `3df858bab875a115` | 110kV | Q/GDW 73285.3-2026 | - | 1 |  |  | 0.966917 | 0.483791 | 4 |
| 3 | `32ef913fd4027af4` | 110kV | Q/GDW 73285.2-2026 | - | 1 |  |  | 0.963567 | 0.484046 | 4 |
| 4 | `01341cbc098d1623` | 110kV | Q/GDW 73285.2-2026 | - | 4 |  |  | 0.961713 | 0.532131 | 4 |
| 5 | `17c6e2e594f11092` | 110kV | Q/GDW 73285.2-2026 | 5 组件材料配置表 | 23 |  |  | 0.946069 | 0.477032 | 1 |
| 6 | `86447dd7f1a32c57` | 110kV | Q/GDW 73285.3-2026 | - | 25 |  |  | 0.872554 | 0.426163 | 1 |
| 7 | `ae68372e5f12d35a` | 110kV | Q/GDW 73285.2-2026 | - | 25 |  |  | 0.85116 | 0.426438 | 1 |
| 8 | `a4aed09c03dd7e82` | 110kV | Q/GDW 13285.1-2019 | 5.1.12 外被层 | 11 |  |  | 0.972242 | 0.461542 | 1 |
| 9 | `33d9ed9c442fc7bf` | 110kV | Q/GDW 73285.2-2026 | - | 13 | Y |  | 0.98961 | 0.455553 | 2 |
| 10 | `849de5e320d793e3` | 110kV | Q/GDW 73285.2-2026 | - | 12 | Y |  | 0.984469 | 0.503109 | 3 |
| 11 | `e1bc17a6b9889f6a` | 110kV | Q/GDW 73285.2-2026 | - | 15 | Y |  | 0.984238 | 0.501006 | 3 |
| 12 | `43eafd18169c0208` | 110kV | Q/GDW 73285.2-2026 | - | 16 | Y |  | 0.976087 | 0.454042 | 2 |

context: 7793 chars

```
根据知识库中Q/GDW 73285系列标准的内容，我来帮你梳理一下110kV海缆附件（终端和接头）在设计使用寿命与结构方面的要求。

**一、设计使用寿命**

知识库里的信息很明确，无论是单芯还是三芯系统，终端和接头的设计使用年限要求都是一致的：

- **GIS终端**：不少于30年（见Q/GDW 73285.2-2026表6）
- **接头**（含整体预制绝缘接头、修理接头等）：不少于30年（见Q/GDW 73285.2-2026表7、表8、表9）

这个30年是标准中给出的最低门槛，投标人在技术参数响应表中填写的保证值不能低于这个数。

**二、结构方面的要求**

关于终端结构，知识库中对GIS终端有比较具体的描述（见Q/GDW 13285.1-2019第5.1.12条）：

1. **优先选用干式结构**，性能要满足GB/T 22381和JB/T 11167.3的要求。
2. **密封要求**：GIS终端尾管与电缆之间应密封；顶部也应密封良好，能长期耐受0.7 MPa的SF₆气体压力。
3. **防气体渗透**：要防止外绝缘的SF₆气体进入终端及电缆系统，比如采用死密封结构环氧套管的GIS终端结构。
4. **连接金具**：表面应有合适的镀层。
5. **供货界面**：GIS与海缆终端的供货界面按GB/T 22381的规定执行。

另外，关于接头的绝缘法兰及外护层（仅适用于绝缘接头），标准中还规定了雷电冲击和直流耐压的试验参数，比如两端间雷电冲击峰值75 kV、两端对地雷电冲击峰值37.5 kV、两端对地直流耐压25 kV（1 min），这些属于对接头绝缘配合的结构性验证要求。

**三、需要提醒你留意的地方**

接头和终端的敷设方式，标准中明确为**浸水**工况，适应的环境温度范围在部分表格中标注为“项目单位填写”，也就是说这一项不是标准统一给定的，而是要根据具体工程条件来确定的。另外，GIS终端SF₆气体最小工作压力也是由项目单位填写，同样属于工程定制项。

总的来说，标准对附件寿命的底线是30年，结构上重点抓密封、防气体渗透和绝缘配合这几块。如果你手头有具体的招标技术规范书，建议对照其中的技术参数响应表逐项核对，特别是那些标注“项目单位填写”的条目，确保没有漏项。
```

### 220kV_scoped

- question: Q/GDW 73286-2026（220kV）标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求
- runs: 3; distinct windows: 1; mean pairwise Jaccard: 1.0
- runs holding BOTH halves: **0/3**
- design-life passages per run: [1, 1, 1]
- structure passages per run: [0, 0, 0]
- voltage mix per run: [{"220kV": 12}, {"220kV": 12}, {"220kV": 12}]
- documents touched: 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf; 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范; 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用技术规范

| # | chunk id | voltage | designation | section | page | design-life | structure | rerank | fused | routes |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `109c57a8471be6fa` | 220kV | Q/GDW 73286.1 | 5.2.3 修理接头 | 10 |  |  | 0.9773 | 0.377367 | 1 |
| 2 | `36a52e5e2479fde1` | 220kV | Q/GDW 73286.1 | 6.5.2 局部放电试验 | 15 |  |  | 0.89423 | 0.46342 | 2 |
| 3 | `f8ebc69e5af7d816` | 220kV | Q/GDW 73286.1 | 5.2.4.2 | 10 |  |  | 0.982055 | 0.516882 | 3 |
| 4 | `834c0774c8fad3e2` | 220kV | Q/GDW 73286.1 | 4.3.3.6 | 7 | Y |  | 0.981496 | 0.481125 | 1 |
| 5 | `af74d2eeaaf2c4a4` | 220kV | Q/GDW 73286.1 | 5 技术要求 | 8 |  |  | 0.973757 | 0.5127 | 3 |
| 6 | `1abf6295ae67beae` | 220kV | Q/GDW 73286.2 | 3 与其他标准/文件的关系 | 23 |  |  | 0.970726 | 0.468433 | 2 |
| 7 | `bc2a6dfa54206eab` | 220kV | Q/GDW 73286.1 | 5.1.7 | 9 |  |  | 0.966899 | 0.485687 | 2 |
| 8 | `48f12a5a8ce5eb6c` | 220kV | Q/GDW 73286.1 | - | 1 |  |  | 0.965514 | 0.500923 | 3 |
| 9 | `43e96b415797394b` | 220kV | Q/GDW 73286.2 | - | 1 |  |  | 0.962648 | 0.489696 | 3 |
| 10 | `3970238838496efa` | 220kV | Q/GDW 73286.3 | 3 与其他标准/文件的关系 | 21 |  |  | 0.961509 | 0.446369 | 1 |
| 11 | `8065ad3f4096ca30` | 220kV | Q/GDW 73286.3 | - | 1 |  |  | 0.96031 | 0.352251 | 1 |
| 12 | `1cae0a6bd293e1ef` | 220kV | Q/GDW 73286.1 | 3 与其他标准/文件的关系 | 23 |  |  | 0.956932 | 0.468855 | 2 |

context: 9201 chars

```
根据Q/GDW 73286—2026这套标准，关于220kV海缆附件（终端和接头）的设计使用寿命和结构要求，我帮您梳理一下。

## 一、设计使用寿命

标准在总则部分（4.3.3.6条）有明确规定：**卖方应保证海缆及其附件寿命不少于30年**。

也就是说，不管是工厂接头、修理接头，还是户外终端、GIS终端，整个附件系统的寿命底线就是30年，这是卖方的保证义务。

## 二、结构要求

附件这块内容比较多，我分接头和终端两大类来说。

### 1. 总体原则

附件应采用**与电缆型式试验时配套的附件**，电气和防水性能**不低于海缆本体**。换句话说，附件不能成为整条线路的"短板"。

### 2. 工厂接头

结构上有几个关键点：

- **导体连接强度**：截面800 mm²及以下的，焊接抗拉强度不小于180 MPa；800 mm²以上的，不小于170 MPa。
- **铅套外径**：工厂接头的铅套外径不能超过电缆铅套外径的10%。
- **导体屏蔽**：体积电阻率与本体相同，恢复后的表面要光滑平整，与导体层融合紧密。
- **绝缘部分**：采用挤塑模塑绝缘时，接头绝缘必须用与本体相同的绝缘材料；恢复绝缘厚度不超过本体绝缘厚度的10%。
- **绝缘屏蔽**：体积电阻率与本体相同，表面光滑平整。
- **标志**：接头外要有醒目的永久标志，符合GB/T 6995.2，长度不小于5米。

另外，投标人还得提供工厂接头的技术说明，以及含工厂接头的型式试验报告和预鉴定试验报告。

### 3. 修理接头

修理接头这块，标准要求投标人提供光纤单元的技术说明和试验报告（针对光纤复合缆的情况）。

### 4. 户外终端

- 一般采用**瓷套管终端**，符合GB/T 32346.3，污秽等级**e级或更严**（最小统一爬电比距53.7 mm/kV）。
- 人员密集区域可采用**复合套管终端**，以玻璃纤维增强环氧管为衬芯，污秽等级同样要求e级或更严。
- 终端应具有使底座与支架相绝缘的**底座绝缘子**，而且安装方式宜设计成更换绝缘子时不需要吊起或拆卸整个终端——这个细节考虑得很周到，方便后期运维。

### 5. GIS终端

- 优先选用**干式结构**，性能满足GB/T 22381及GB/T 32346.3。
- 尾管与电缆之间应密封，与GIS组合电器的连接尺寸符合GB/T 22381。
- 顶部密封要能长期耐受**0.7 MPa的SF6气体压力**，连接金具表面应有合适的镀层。
- 要防止外绝缘的SF6气体进入终端及电缆系统，比如采用**死密封结构环氧套管**的GIS终端结构。

### 6. 型式试验的结构验证要求

标准还要求，型式试验系统中应包含**至少一个工厂接头以及终端（GIS和/或户外终端）**，并且电缆和接头必须经受安装、敷设和修理时预期遭遇的**最高机械负荷**的相应机械试验。

---

简单总结一下：寿命底线30年，结构上核心就是"附件性能不低于本体、材料与本体一致、尺寸偏差有上限、密封和绝缘要可靠"。如果您是在做选型或者编写技术规范书，这些条款可以直接对应引用。有需要进一步展开的地方随时说。
```

### design_life_only

- question: 标准对电缆附件终端和接头的设计使用年限有何要求
- runs: 3; distinct windows: 1; mean pairwise Jaccard: 1.0
- runs holding BOTH halves: **0/3**
- design-life passages per run: [10, 10, 10]
- structure passages per run: [0, 0, 0]
- voltage mix per run: [{"110kV": 5, "220kV": 7}, {"110kV": 5, "220kV": 7}, {"110kV": 5, "220kV": 7}]
- documents touched: 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf; 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电力电缆系统专用技术规范; 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电力电缆系统专用技术规范; 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf; 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范; 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用技术规范

| # | chunk id | voltage | designation | section | page | design-life | structure | rerank | fused | routes |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `849de5e320d793e3` | 110kV | Q/GDW 73285.2-2026 | - | 12 | Y |  | 0.940732 | 0.58973 | 2 |
| 2 | `79007bcdc5c36b48` | 110kV | Q/GDW 73285.3-2026 | - | 12 | Y |  | 0.893133 | 0.590005 | 2 |
| 3 | `9b0947b801d49c2d` | 220kV | Q/GDW 73286.2 | 4 标准技术参数表 | 12 | Y |  | 0.868414 | 0.590728 | 2 |
| 4 | `39fd982260d327ed` | 110kV | Q/GDW 73285.2-2026 | - | 11 | Y |  | 0.84518 | 0.607883 | 3 |
| 5 | `5979e5c9399e8a69` | 110kV | Q/GDW 73285.3-2026 | - | 11 | Y |  | 0.806859 | 0.586648 | 1 |
| 6 | `d49e20e1ba5337fd` | 220kV | Q/GDW 73286.3 | 4 标准技术参数表 | 11 | Y |  | 0.774811 | 0.589588 | 2 |
| 7 | `94cf97aa21a0ac1e` | 220kV | Q/GDW 73286.2 | 4 标准技术参数表 | 11 | Y |  | 0.766653 | 0.610962 | 3 |
| 8 | `4f291a3c82619d20` | 220kV | Q/GDW 73286.3 | 4 标准技术参数表 | 13 | Y |  | 0.759289 | 0.584619 | 1 |
| 9 | `9ea7300f4f6f4219` | 220kV | Q/GDW 73286.3 | 4 标准技术参数表 | 16 | Y |  | 0.737287 | 0.588867 | 1 |
| 10 | `d66a18e51bec0e16` | 220kV | Q/GDW 73286.2 | 4 标准技术参数表 | 17 | Y |  | 0.733889 | 0.587815 | 1 |
| 11 | `2bd4a61a1cc33692` | 110kV | GB/T 21429-2008 | 6.4 型式试验 | 14 |  |  | 0.46412 | 0.582177 | 1 |
| 12 | `109c57a8471be6fa` | 220kV | Q/GDW 73286.1 | 5.2.3 修理接头 | 10 |  |  | 0.428647 | 0.603514 | 1 |

context: 10220 chars

```
根据我查到的资料，在110kV和220kV海底电力电缆系统的采购标准里，对终端和接头的设计使用年限都有明确规定，要求是**不少于30年**。

具体说一下吧：

**关于终端**——无论是110kV还是220kV，不管是单芯还是三芯，GIS终端或者其他型式终端，标准技术参数表里都明确写着“终端设计使用年限：不少于30年”。

**关于接头**——同样地，在220kV海缆的技术参数表里，接头设计使用年限也是**不少于30年**。

所以总的说来，就是终端和接头这两类附件，设计使用年限的门槛统一都定在**30年及以上**。

另外提醒一句，标准里还顺带提到，GIS终端的尺寸参照IEC 62271有两种规格，投标人需要承诺按招标人要求提供配套的终端，这个和年限要求是配套出现的，做采购技术规范时可以一并留意。
```

### structure_only

- question: 标准对电缆附件终端和接头的结构图纸资料有什么要求
- runs: 3; distinct windows: 1; mean pairwise Jaccard: 1.0
- runs holding BOTH halves: **3/3**
- design-life passages per run: [1, 1, 1]
- structure passages per run: [4, 4, 4]
- voltage mix per run: [{"220kV": 6, "110kV": 6}, {"220kV": 6, "110kV": 6}, {"220kV": 6, "110kV": 6}]
- documents touched: 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf; 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电力电缆系统专用技术规范; 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电力电缆系统专用技术规范; 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf; 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范; 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用技术规范

| # | chunk id | voltage | designation | section | page | design-life | structure | rerank | fused | routes |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `5f81fce4a4628ebf` | 220kV | Q/GDW 73286.3 | 4 标准技术参数表 | 17 |  | Y | 0.926057 | 0.653567 | 3 |
| 2 | `0eb621e18881e734` | 220kV | Q/GDW 73286.2 | 5 组件材料配置表 | 18 |  | Y | 0.924068 | 0.652738 | 3 |
| 3 | `109c57a8471be6fa` | 220kV | Q/GDW 73286.1 | 5.2.3 修理接头 | 10 |  |  | 0.780745 | 0.607347 | 2 |
| 4 | `7a8dca9e22d2bce1` | 110kV | Q/GDW 13285.1-2019 | 5.1.12 外被层 | 10 |  |  | 0.771574 | 0.620974 | 3 |
| 5 | `c910968a4a1cbc53` | 110kV | Q/GDW 73285.2-2026 | - | 17 |  | Y | 0.896054 | 0.616306 | 3 |
| 6 | `2bd4a61a1cc33692` | 110kV | GB/T 21429-2008 | 6.4 型式试验 | 14 |  |  | 0.738851 | 0.582049 | 2 |
| 7 | `c9d9be8eb6196e58` | 220kV | Q/GDW 73286.1 | 4.2.2 | 6 |  |  | 0.73461 | 0.566452 | 1 |
| 8 | `0cd7b74071f4c9b1` | 110kV | (no prefix) | - | 17 |  | Y | 0.838931 | 0.620268 | 3 |
| 9 | `6a6feb4500e626a3` | 110kV | Q/GDW 73285.2-2026 | - | 18 |  |  | 0.809924 | 0.605002 | 3 |
| 10 | `583ae7fa1bc3639b` | 110kV | (no prefix) | - | 18 |  |  | 0.692982 | 0.608366 | 3 |
| 11 | `834c0774c8fad3e2` | 220kV | Q/GDW 73286.1 | 4.3.3.6 | 7 | Y |  | 0.425245 | 0.582377 | 1 |
| 12 | `5d52c3f6cbe9e4c5` | 220kV | Q/GDW 73286.1 | 6.6.12 局部放电试验 | 17 |  |  | 0.384434 | 0.63791 | 3 |

context: 9296 chars

```
根据知识库里的采购标准，不管是220kV还是110kV的海底电缆系统，对电缆附件（终端和接头）的结构图纸资料都有比较明确的要求，我帮你梳理一下：

**需要提供图纸的附件范围**

投标人需要提供以下几类附件的结构图纸：

- **终端类**：电缆户外终端、GIS终端和油浸终端的结构图纸
- **接头类**：组合预制直通接头和绝缘接头结构图纸；整体预制直通接头和绝缘接头结构图纸
- **附属设备**：接头铜壳的结构图纸；直接接地箱、带保护接地箱、接地电缆的结构图纸

**另外还有配套的设计计算资料**

- 过电压限制器参数的计算及选择

**交货时还需补充的资料**

除了上述设计阶段的图纸，交货时投标人还应提供：

- 电缆附件的全部例行试验报告
- 电缆附件安装工艺说明书
- 结构尺寸和详细图纸

这个要求在220kV单芯、220kV三芯、110kV单芯、110kV三芯这几类海缆系统的专用技术规范里是一致的，可以说是一套通用的资料提交要求。简单来说，就是**设计阶段交图纸和计算书，交货阶段交试验报告和安装工艺文件**，形成一个完整的闭环。

如果你是在准备投标文件，建议把这些资料按"设计资料"和"交货资料"两部分分别整理，避免遗漏。
```

## P6 generation stability (one FROZEN context, answered repeatedly)

- frozen window: 12 passages, 10171 chars
- distinct answers from that one context: **3** (identical: False)
- mentions design life per answer: [True, False, False]
- mentions structure per answer: [True, True, True]

### frozen-context answer 1

```
关于海底电缆附件（终端与接头）的设计使用寿命和结构要求，我帮你从知识库里梳理一下。

**先说设计使用寿命：**

坦白讲，知识库中并没有直接给出附件设计寿命的具体年限数字（比如“30年”“40年”这样的明确要求）。不过标准里有一条很关键的原则性规定——**电缆附件的电气和防水性能应不低于海缆本体**。也就是说，海缆本体设计用多少年，附件就得跟得上，不能成为整条线路的短板。110kV和220kV标准里都有这一条，算是附件设计的“底线要求”。

**再说结构方面的要求：**

标准对附件的结构规定得还是挺细致的，分几块来看：

**一、终端部分**

户外终端一般采用瓷套管终端，要符合JB/T 11167.3的要求，污秽等级为e级或更严，最小统一爬电比距不低于53.7 mm/kV。如果是人员密集区域，可以改用复合套管终端，以玻璃纤维增强环氧管为衬芯，性能要求跟瓷套管一致。

另外有个很贴心的设计细节——户外终端应具有使底座与支架相绝缘的底座绝缘子，而且安装方式最好设计成**更换该绝缘子时不需要吊起或拆卸整个终端**。这个对后期运维来说太重要了。

**二、工厂接头**

工厂接头要求导体焊接的抗拉强度：截面800 mm²及以下不小于180 MPa，800 mm²以上不小于170 MPa。铅套外径不能超过电缆铅套外径的10%。绝缘方面，接头绝缘必须采用与海缆本体相同的绝缘材料，恢复绝缘厚度不超过本体绝缘厚度的10%，导体屏蔽和绝缘屏蔽的体积电阻率都要和本体一致。接头外还要有醒目的永久标志，长度不小于5米。

**三、修理接头**

修理接头分两种：

**软接头型**——内部设计类似于工厂接头，外径近似于电缆外径。特别要注意金属铠装线的恢复处理，必须保证接头处铠装恢复柔性连接并有足够强度，避免铠装线松弛导致敷设时电缆芯受到过度张力。

**刚性接头型**——内部通常采用预模制或预装配结构，也可以类似工厂接头。外部设计要有良好的机械性能和防海水腐蚀性能，能耐受敷设和运行时的机械弯曲、张力和扭转。金属保护盒宜采用高强度不锈钢材料。

修理接头还要求有完善的防水密封结构件，并做好防水浇注剂灌封。如果是光纤复合海底电缆，修理接头的水密封构件中还要包含光纤单元接线盒，接线盒要符合YD/T 814.3的规定。

**四、型式试验的配套要求**

110kV标准明确要求，海缆系统的型式试验中应包含至少一个工厂接头以及终端（GIS和/或户外终端），附件必须采用与电缆型式试验时配套的附件。这说明附件的结构设计不能脱离电缆本体单独考虑，得整体匹配。

**总结一下**：设计寿命上，标准的核心逻辑是“附件不低于本体”；结构上，终端重点在绝缘配合和运维便利性，接头重点在电气性能等同本体、机械强度足够、防水密封可靠。
```

### frozen-context answer 2

```
关于海底电缆附件的设计使用寿命和结构要求，我帮你从知识库里梳理了一下，目前能查到的信息主要集中在结构设计方面，使用寿命这块标准里没有直接给出明确的年限规定。下面分开来说：

**一、关于设计使用寿命**

坦白讲，目前知识库收录的这几份标准（Q/GDW 13285.1、Q/GDW 73286.1等）里，没有找到对电缆附件设计使用寿命给出具体年限的条款。标准更多是从型式试验、预鉴定试验这些角度来间接验证附件的长期可靠性，而不是直接规定"多少年"。如果你手头有具体的项目技术协议或专用技术规范，建议再翻一翻那边有没有补充规定。

**二、关于结构要求**

结构方面的要求还是比较明确的，分接头和终端来说：

**1. 修理接头**

修理接头分两种类型：

- **软接头型**：内部设计类似于工厂接头，外径近似于电缆外径。需要特别注意的是金属铠装线的恢复处理——要保证接头处铠装恢复柔性连接并具备足够强度，避免铠装线松弛导致敷设时电缆芯受到过度张力。

- **刚性接头型**：内部通常采用预模制或预装配结构，也可以采用类似工厂接头的设计。外部要具备良好的机械性能和防海水腐蚀性能，能耐受敷设和运行时的机械弯曲、张力和扭转。金属保护盒宜采用高强度不锈钢材料。

不管哪种修理接头，都要求有完善的防水密封结构件，并做好防水浇注剂灌封。如果是光纤复合海底电缆，接头的水密封构件中还要包含光纤单元接线盒，同样要做灌封处理。

**2. 工厂接头**

工厂接头的要求更细一些：导体焊接的抗拉强度，800 mm²及以下截面不小于180 MPa，800 mm²以上不小于170 MPa；接头铅套外径不超过电缆铅套外径的10%；绝缘须采用与本体相同的材料，恢复绝缘厚度不超过本体绝缘厚度的10%；外表面要有醒目的永久标志，长度不小于5米。

**3. 电缆终端**

户外终端一般采用瓷套管终端，污秽等级要求e级或更严（最小统一爬电比距53.7 mm/kV）。人员密集区域可采用复合套管终端，以玻璃纤维增强环氧管为衬芯。户外终端还应具有使底座与支架相绝缘的底座绝缘子，且安装方式宜设计成更换该绝缘子时不需要吊起或拆卸终端。

**三、一个重要的前提**

110kV和220kV标准都明确了一条基本原则：海底电缆附件应采用与其电缆型式试验时配套的附件，附件的电气和防水性能应不低于海缆本体。也就是说，附件不是随便选的，必须和电缆本体做过配套型式试验。

如果你需要更具体的某类附件（比如GIS终端或绝缘接头）的结构细节，可以再告诉我，我帮你细查。
```

### frozen-context answer 3

```
关于海底电缆附件的设计使用寿命和结构要求，我帮您从知识库里梳理一下。

**先说说使用寿命这块**——说实话，知识库里目前没有直接给出"设计使用寿命XX年"这样的明确年限要求。不过从整体采购标准的逻辑来看，附件有个核心原则：**附件的电气和防水性能应不低于海缆本体**（110kV和220kV标准里都有这条）。也就是说，附件是跟着海缆本体走的，海缆设计寿命多少年，附件就得匹配上，不能成为整条线路的短板。具体的年限数字，建议在供需双方技术协议里明确约定。

**再来说结构方面的要求，这个知识库里内容比较丰富：**

**一、接头（分工厂接头和修理接头两类）**

**工厂接头：**
- 导体焊接强度有硬指标——截面800mm²及以下的，抗拉强度不小于180MPa；800mm²以上的，不小于170MPa。
- 绝缘必须用与海缆本体相同的材料，恢复后的绝缘厚度不能超过本体绝缘厚度的10%；铅套外径也不超过本体铅套外径的10%。
- 导体屏蔽和绝缘屏蔽的体积电阻率要与本体一致，恢复表面要求光滑平整、融合紧密。
- 外表面要有醒目的永久标志，长度不小于5米，符合GB/T 6995.2。

**修理接头**分两种结构：
- **软接头型**：内部设计类似工厂接头，外径近似于电缆外径。这里有个关键点——金属铠装线的恢复处理要特别到位，必须保证柔性连接且有足够强度，否则铠装松弛了，敷设时缆芯会受到过度张力。
- **刚性接头型**：内部通常采用预模制或预装配结构，也可类似工厂接头。外部要能耐受敷设和运行时的机械弯曲、张力和扭转，金属保护盒宜用高强度不锈钢。修理接头还得有完善的防水密封结构和浇注剂灌封工艺。

**二、终端（以户外终端为主）**

- 一般采用瓷套管终端，符合JB/T 11167.3，污秽等级e级或更严（最小统一爬电比距53.7 mm/kV）。
- 人员密集区域可以用复合套管终端，衬芯是玻璃纤维增强环氧管，污秽等级要求一样。
- 户外终端要带底座绝缘子，把底座和支架隔开，而且安装方式最好设计成——换这个绝缘子的时候不用把整个终端吊起来或拆掉，这个细节挺人性化的。

**三、型式试验对结构验证的要求**

110kV标准里明确，海缆系统型式试验中必须包含**至少一个工厂接头以及终端**（GIS和/或户外终端）。附件还要额外做这些试验：户外终端淋雨工频电压试验（460kV/1min不闪络不击穿）、无线电干扰试验（140kV下1MHz干扰电压不超500V）、金属套分断绝缘终端试验、复合套管内压力及弯曲试验等。

**总结一下**：知识库对附件结构的要求可以说是相当细致，从材料、尺寸偏差到机械强度、防水密封都有明确规定；但设计使用寿命这一块，标准里没有给出具体年限数字，走的是"不低于海缆本体"这个原则性要求。如果您需要明确的寿命年限，建议在设计联络会或技术协议中跟供应商确认清楚。
```

_sha256 of each frozen-context answer: ['0971bb641917', '23af327d386f', 'accf4a1034ad']_

---

# Root cause

Two follow-up probes localise the loss. Both are read-only and use only deployed functions at the
assistant's own parameters (`tools/scripts/rag_qa_004_stage_localisation.py`,
`tools/scripts/rag_qa_004_term_probe.py`).

## Stage localisation: the evidence is never retrieved

Reproducing the deployed merge + rerank + cut over the routes' OWN candidates:

| stage | passages | design-life | structure |
|---|---|---|---|
| E2 route `(original question)` | 9 | **0** | 4 |
| E2 route `…的设计使用寿命有何要求` (the decomposer's own route) | 10 | **0** | 4 |
| E2 route `…的结构有何要求` | 12 | 0 | 4 |
| E4 merged pool | 13 | **0** | 4 |
| E4 after deployed `rerank_chunks(..., 12)` | 12 | 0 | 4 |
| E4 production `retrieve_multi_route` | 12 | 0 | 4 |

**The design-life passage is lost at route recall, not at the merge and not at the cut.** No route
in this session returned one, so no downstream stage could have kept it.

## The trigger: the question's noun phrase does not exist in the corpus

The corpus says **设计使用年限**. The benchmark question says **设计使用寿命** — the same phrase
with one word swapped.

| term | chunks containing it (of 317) | occurrences |
|---|---|---|
| `设计使用寿命` | **0** | **0** |
| `设计使用年限` | 20 | 20 |
| `寿命` (any context) | 26 | 35 |

The deployed tokenizer makes the mismatch explicit:

```
设计使用寿命 -> ['设计使用寿命', '使用寿命', '使用', '寿命', '设计']   # discriminator: 寿命
设计使用年限 -> ['设计使用年限', '设计', '年限', '使用']              # discriminator: 年限
```

Both terms share only `设计` / `使用`; the token that carries the meaning differs (`寿命` vs
`年限`), and `寿命` occurs in none of the design-life clauses.

Swapping only that one word, keeping the query shape identical, changes the outcome completely:

| probe | question | returned | design-life | structure |
|---|---|---|---|---|
| `term_only_life` | `设计使用寿命` | **0** | 0 | 0 |
| `term_only_annual` | `设计使用年限` | 12 | **12** | 0 |
| `exact_clause` | `终端设计使用年限` | 12 | **12** | 0 |
| `decomposer_route_life` | `标准对电缆附件（终端与接头）的设计使用寿命有何要求` | 10 | **0** | 4 |
| `term_swapped_annual` | `标准对电缆附件（终端与接头）的设计使用年限有何要求` | 12 | **6** | 2 |
| `narrow_terminal_life` | `标准对电缆附件终端的设计使用寿命有何要求` | 12 | 2 | 4 |
| `narrow_terminal_annual` | `标准对电缆附件终端的设计使用年限有何要求` | 12 | **7** | 2 |
| `narrow_connector_life` | `标准对电缆附件接头的设计使用寿命有何要求` | 11 | 1 | 4 |
| `narrow_connector_annual` | `标准对电缆附件接头的设计使用年限有何要求` | 12 | **5** | 2 |
| `original_composite` | the benchmark question | 9 | **0** | 4 |

`term_swapped_annual` returns **6 design-life and 2 structure passages in the same 12-slot window**,
so the window has room for both halves — the two halves competing for slots is not by itself what
loses the design life. The only difference from the failing case is the word.

## Why the two runs differed: the decomposer's granularity decides which routes exist

The decomposer is an LLM call, and its **route count differs between sessions** while being stable
within one:

- this session (12 samples, and the earlier 6): **2 sub-queries** — one composite design-life route
  and one composite structure route → the composite design-life route returns 0 design-life
  passages → window has none → the answer reports "no explicit year in the knowledge base";
- the baseline capture session: **4 sub-queries** — the decomposer split the question into a
  终端/接头 × 设计寿命/结构 matrix → the narrowed routes each get close enough to the table to
  surface the clause.

The narrowed routes reproduce the earlier window exactly:

```
baseline window's design-life passages : 79007bcdc5c36b48, d66a18e51bec0e16, 9b0947b801d49c2d
narrow_terminal_life  returns          : 9b0947b801d49c2d, 79007bcdc5c36b48
narrow_connector_life returns          : d66a18e51bec0e16
                                          2 + 1  =  the 3 in the earlier window
```

So the system has **two stable attractors**, and which one a session lands in is decided by the
decomposer's granularity — not by retrieval noise.

## The three candidate hypotheses, answered

**A. 110kV/220kV document mixing → context drift?** Real but **not causal**. The failing window does
mix (6 × 110kV + 6 × 220kV), and voltage scoping changes the result — but it does not restore both
halves, it only flips which one survives: `110kV_scoped` → 4 design-life / 0 structure,
`220kV_scoped` → 1 design-life / 0 structure, `original` → 0 design-life / 4 structure. Meanwhile
`term_only_annual` carries **no** voltage expression at all and returns 12/12 design-life passages.
The 30-year clause exists in all four dedicated parts (110kV and 220kV, single- and three-core), so
voltage is not what makes it unfindable.

**B. Chunk/table splitting separating the life clause from the structure clause?** Real as a
structural condition, **not the trigger**. Verified over all 317 chunks: **no chunk contains both**
clauses; the design-life clause sits in 20 chunks across 4 documents while the structure-drawing
clause sits in exactly **1 chunk per dedicated document (4 total)**. So the two halves are
mutually exclusive per passage and must be gathered by different routes — which is precisely why
route recall, not the cut, is the failure point. But `term_swapped_annual` gathers both (6 + 2) in
one 12-slot window, so the split alone does not cause the loss.

**C. Query carries no voltage grade → scope ambiguity?** Not causal. Voltage appears only in the
documents' injected text prefix, never as a filterable field, and the failing behaviour is
reproducible with and without a voltage expression. Scoping narrows the candidate pool but leaves
the terminology gap untouched.

## Retrieval / metadata-scope / generation attribution

| layer | verdict | evidence |
|---|---|---|
| **retrieval** | **primary cause** | embedding byte-identical (max abs Δ = 0.0); decomposition stable 12/12 within the session; 5/5 identical windows, Jaccard 1.0 — the loss is a **systematic, reproducible recall gap**, not noise. The clause is reachable (12/12 with its own wording) but not reached by the benchmark's wording. |
| metadata scope | not the cause | scoping to 110kV or 220kV does not restore both halves; the clause is present in every voltage variant, so scope is not the discriminator. |
| **generation synthesis** | **not the cause, but non-deterministic in text** | from one FROZEN context, 3 calls produced **3 distinct answers** (different sha256) — yet **all three** correctly reported "no explicit year in the knowledge base", which is exactly what a context with 0 design-life passages supports. The model faithfully rendered what it was handed; the wording varies, the factual stance does not. |

Two secondary measurements:

- **rerank is not bit-deterministic**: the same 12 passages re-scored 3 times gave `identical_all =
  false`, max |Δ| = **0.0064**. Real, but far too small to flip a 6-versus-0 difference in retrieved
  passages, so it is a margin effect, not the mechanism.
- **the window is otherwise stable**: 5/5 runs at Jaccard 1.0, identical order, identical route set.

## Answers to the three questions

**Query decomposition — already present, already stable, and it is the *variable* that decides the
outcome.** The deployed pipeline decomposes the question, and its 2-route form is what fails. No
decomposition capability is missing; what varies is the granularity the model chooses per session,
and the composite route is the one that cannot reach the table.

**Metadata filtering — would not address this failure.** The evidence is present under both voltage
grades; filtering by voltage changes which half survives but never restores both, and the clause is
unreachable under the benchmark's wording regardless of scope.

**Chunk optimisation — a real structural condition, but not the trigger.** The design-life clause is
split across 20 chunks in 4 documents while the structure clause occupies 1 chunk per document; the
two never co-occur in one passage. That makes the window a competition between halves, but a window
holding both halves is demonstrably achievable (6 + 2) once the wording matches the corpus.

**Conclusion: the instability belongs to the retrieval layer.** The same question is stable within a
session and reproducible; what differs between sessions is the decomposer's granularity, which
decides whether any route ever reaches the design-life clause — a clause the benchmark's own wording
(`设计使用寿命`) cannot match because the corpus states it as `设计使用年限`.
