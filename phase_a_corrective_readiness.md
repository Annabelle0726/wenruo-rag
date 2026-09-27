# Corrective migration readiness (read-only; nothing written)

* family chunks: 155 of 481 scanned; outside the family: 326
* would change: **0**; unchanged: 155
* section census over the changed set: {'non_null_to_non_null': 0, 'non_null_to_null': 0, 'null_to_non_null': 0, 'same_section': 0}
* change reasons: section_added 0, section_removed 0, section_changed 0, other 0
* raw-body hash present on every row (proves old and new used the SAME body): 155/155

## Convergence (whole-document sequence, three initial states)

* 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf... legacy: S1==S2: True; S2==S3: True
* 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf... raw: S1==S2: True; S2==S3: True
* 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf... current: S1==S2: True; S2==S3: True
* 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆... legacy: S1==S2: True; S2==S3: True
* 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆... raw: S1==S2: True; S2==S3: True
* 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆... current: S1==S2: True; S2==S3: True
* 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆... legacy: S1==S2: True; S2==S3: True
* 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆... raw: S1==S2: True; S2==S3: True
* 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆... current: S1==S2: True; S2==S3: True

## The changed chunks

| chunk id | document | Part | old section | new section | reason | raw sha |
|---|---|---|---|---|---|---|

## Evidence: section_removed and section_changed


## Verdict: **NOT READY**

* the changed set is 0, not the 60 the canary's dry run reported - the two must agree before an approval