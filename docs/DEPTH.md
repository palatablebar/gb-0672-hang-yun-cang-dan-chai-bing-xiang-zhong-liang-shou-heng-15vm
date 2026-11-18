# 深度登记 航运舱单拆并箱与重量守恒

规模：中型。使用者：货代单证员。核心规则：主提单与分提单拆并形成有向无环关系，件数和净毛重逐层守恒。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 舱单采信 | 执行并复核舱单采信 | `POST /api/intake` | `app/modules/intake/rules.py` | `tests/test_intake.py` |
| M2 包装映射 | 执行并复核包装映射 | `POST /api/packaging` | `app/modules/packaging/rules.py` | `tests/test_packaging.py` |
| M3 拆并编组 | 执行并复核拆并编组 | `POST /api/grouping` | `app/modules/grouping/rules.py` | `tests/test_grouping.py` |
| M4 危险品检查 | 执行并复核危险品检查 | `POST /api/hazard` | `app/modules/hazard/rules.py` | `tests/test_hazard.py` |
| M5 净毛重核验 | 执行并复核净毛重核验 | `POST /api/weight` | `app/modules/weight/rules.py` | `tests/test_weight.py` |
| M6 报关对账 | 执行并复核报关对账 | `POST /api/reconcile` | `app/modules/reconcile/rules.py` | `tests/test_reconcile.py` |
| M7 版本封存 | 执行并复核版本封存 | `POST /api/archive` | `app/modules/archive/rules.py` | `tests/test_archive.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码回退 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_legacy_source` |
| TRAP-02 | BOM表头 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_bom_source` |
| TRAP-04 | 分段表头 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_segment_header` |
| TRAP-05 | 缺列隔离 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_column_isolation` |
| TRAP-14 | 编号冲突 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_conflict_all_isolated` |
| TRAP-18 | 空态三分 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_three_empty_states` |
| TRAP-15 | 吨与包装换算 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/packaging/rules.py` | `tests/test_packaging.py::test_pallet_real` |
| TRAP-07 | 空值哨兵 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/packaging/rules.py` | `tests/test_packaging.py::test_sentinel_real` |
| TRAP-06 | 全角千分位 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/packaging/rules.py` | `tests/test_packaging.py::test_fullwidth_decimal` |
| TRAP-20 | 拆并依赖环 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/grouping/rules.py` | `tests/test_grouping.py::test_cycle_real` |
| TRAP-21 | 缺失父级 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/grouping/rules.py` | `tests/test_grouping.py::test_missing_parent_real` |
| TRAP-22 | 连续部分补正整行替代 | 后一份只改箱号时丢掉前一份件重修正 | 只覆盖声明字段，其余继承当前完整版本 | `app/corrections.py` | `tests/test_corrections.py::test_sequential_partial_corrections_merge_not_replace` |
| TRAP-23 | 零散合并拼出未申报组合 | 同一版本上的分叉被静默拼成新组合 | 版本须紧接当前版本；分叉后到者整包退回并保留旧版 | `app/corrections.py` | `tests/test_corrections.py::test_branching_same_revision_rejected_as_second_package` |
| TRAP-24 | 补正包重试重复生成 | 同一包重复提交追加版本链 | 按包编号与摘要去重，复用已生成批次 | `app/corrections.py` | `tests/test_corrections.py::test_duplicate_retry_of_same_package_is_idempotent` |
| TRAP-25 | 切换失败覆盖旧版 | 被退回的补正留下半成品 | 候选批不落库，旧版结果继续作为当前结果 | `app/main.py` | `tests/test_e2e.py::test_rejected_correction_restores_previous_run` |
| TRAP-26 | 原始证据被补正覆盖 | 记录被合并后无法追回原始采信 | 补正前留档 `intake_evidence`，证据包含 `intake_source.json` | `app/corrections.py` | `tests/test_corrections.py::test_original_intake_evidence_preserved_after_correction` |

## 补正裁量规则

截关前的补正只声明本次改动字段。合并以当前已采用的完整版本为基线逐字段覆盖，未声明字段继承，因此连续的部分补正不会互相抹掉。每条补正必须紧接当前版本；跳版、回退和同一版本上的分叉整包退回。整包采用或整包退回，退回时旧版结果保持为当前结果。补正后按主单重新核验图关系、逐层件重、危险品和申报汇总，只有全部主单一致才允许封存。逐张主单列出采用来源、件重变化与阻断原因。

## 对账规则

原始逻辑输入=采纳行+隔离行+空行+重复表头+同值重复。业务计算按 DATA-DICTIONARY.md 分别核验，不能把上级与下级重复加总。所有隔离保留编号、原值、原始行号和稳定原因码。

## 已知不覆盖

数据来自仓内样例或用户粘贴文件，不连接外部业务生产系统。平台不执行实际资金划转或行政审批。
