# 航运舱单拆并箱与重量守恒

给货代单证员使用。主提单与分提单拆并形成有向无环关系，件数和净毛重逐层守恒。

七个业务模块：舱单采信、包装映射、拆并编组、危险品检查、净毛重核验、报关对账、版本封存。

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

访问 http://localhost:18241 。启动直接载入现场脏批。切换干净样例和旧编码样例可对照核验。干净批42个节点、6个主单，件数240、净重2400kg、毛重2640kg；现场脏批包含父级缺失、依赖环、危险品不相容及1kg毛重差异，封存状态为待处理。

各模块页面对应 `/<模块英文名>`，各模块执行入口为 `POST /api/<模块英文名>`，不传参即可独立演示。完整运行 `POST /api/runs` 支持 `dataset`（dirty/clean/legacy）、`csv_text` 与 `overrides` 参数。批次历史 `GET /api/runs`，详情 `GET /api/runs/{run_id}`。

同输入与规则版本生成相同批号，只保留一条批次。复核入口 `POST /api/runs/{run_id}/review` 提交当前 `revision`，陈旧提交409。归档包只有一个下载入口 `GET /api/export/{run_id}`，含证据和运行摘要。原始隔离在页面同屏显示。

SQLite使用命名卷，容器重启后保留历史。要重建演示可在Compose中改用新的卷名称，保留旧卷。

源码在 `app/`，样例在 `sample_data/`，测试在 `tests/`；定义见 `docs/DATA-DICTIONARY.md`，模块和边界测试对应关系见 `docs/DEPTH.md`。输入上限2MB，属于离线复核工具。

采信页支持上传或粘贴CSV。完整源字节与参数随批次持久化，跨页通过run_id读取同一结果。`POST /api/runs/{run_id}/rerun` 读取该批不可变输入快照重新计算，规则未变时批号不变。切换另一示例则创建或复用另一批次。

## 截关前补正

截关前同一票舱单常收到多份只声明改动字段的补正。补偿入口 `POST /api/runs/{run_id}/corrections`，正文为 `package_id` 加 `rows`（或 `csv_text`）与可选的 `declaration`（`pieces`/`net_kg`/`gross_kg`）。独立演示入口 `POST /api/corrections`，可在同一请求里带 `dataset`/`csv_text` 与 `corrections` 列表。

- 补正行只覆盖自己声明的字段，其余字段继承当前已采用的完整版本，所以前一份修正件重、后一份只改箱号时两项改动都保留。
- 每条补正必须紧接当前版本（`revision` = 当前 + 1）。跳版、回退、在同一版本上分叉都整包退回，合并结果因此始终对应唯一一条申报依据。
- 补正包整包采用或整包退回；退回时旧版结果保持为当前结果，不会被半成品覆盖。同一补正包重试复用已生成批次。
- 申报汇总随补正一起提交；只改件重而不更新申报汇总的主单会被阻断。
- 原始采信行留在 `intake_evidence`，证据包 `GET /api/export/{run_id}` 里含 `intake_source.json`，可完整追回。
- 只有全部主单一致时才可封存；`GET /api/export/{run_id}?sealed=1` 在阻断时返回409，一致时附 `seal.json`。
- 版本封存页逐张主单列出采用的补正来源、件重变化和阻断原因。

补正规则见 `app/corrections.py`，测试见 `tests/test_corrections.py`。
