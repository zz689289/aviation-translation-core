# 长文的一次请求与断点续接

一次请求可以有许多内部批次。执行者自行进入下一批，直至合并、全篇复核、修订和 PDF 验收完成。达到上下文边界前把页／对象范围、决策、待核语义及文件路径存盘；恢复后从首个未提交批次继续。若进程被外部强制终止，保留可恢复状态，明确最后完成范围。不得把生成草稿、已渲染页数或已提交批数记为通过审校。

**建立库存。** 以实际物理页编号和阅读顺序稳定分配 ID，登记正文、页眉脚、目录、书签、跨页句、表中单元格、图件组与每个有意义的标签。检查扫描页和轮廓字；真正空页也要说明。结合本篇定义、缩写表和技术层级建立决策表，固定排版参数、翻译范围和版本。工作库的 settings 是冻结的初始设置；期间新增或修改决定应版本化并重查其所有既有出现位置。

**提交和恢复。** 用绝对路径调用以下命令。inventory.jsonl 每行是 `{"id":"p01.a","page":1,"role":"heading","source":"..."}`。settings.json 是存有本次样式、术语及交付范围的 JSON 对象。完整批次按库存顺序提交。重复提交相同回执可重试，冲突、漏项、乱序或输入指纹漂移会被拒绝。

```text
python scripts/long_job.py init --db job.sqlite --pdf source.pdf --inventory inventory.jsonl --settings settings.json --pages-per-batch 8
python scripts/long_job.py next --db job.sqlite --output batch-001.json
python scripts/long_job.py commit --db job.sqlite --input receipt-001.json
python scripts/long_job.py status --db job.sqlite
python scripts/long_job.py export --db job.sqlite --output translated.jsonl
```

回执为 `{"job":"从 next 读取的指纹","batch":1,"results":[{"id":"p01.a","action":"translated","target":"译文"}]}`。原样保留对象用 `preserved`，写明 `basis` 和实际文字或资产定位。图片翻译应指向可复核的本地化资产。导出保留源 ID，可与库存按 ID 合并。next 给出批首与批尾的邻项，遇跨页句或续表要查看前后完整语义组；译文按原 ID 对应，记录合并归属。源文漂移应新建修订库；有问题的已提交译文在新修订层用旧值或哈希作前置条件更改，重新追查全部相关 ID，再绑定最终 PDF。工作库只证明录入顺序与覆盖情况。

**开始下一批之前。** 用原件核对该批所有译文，记录审查者、源译定位与待核项；段落主语、数量基础、限定范围、规范力度和技术术语逐项保真。上一页末的限定与本页句首合并读。对长输入按章节形成语境记录，至少含定义、实体和缩写、适用阶段、前后条款与已采用译法。机翻只作草稿，译回英语或自报评分均不构成语义审校。优先修复同根问题在全书的出现位置。独立 QA 复用一名，分批读源与最终冻结候选。执行者可并行推进其余批次。

**防止术语漂移。** 配对内容每行 `{"id":"...","source":"...","target":"..."}`。用本篇定义和段落确定适用语境，以同一决定核对目录、书签、正文标题、表格和图内对应标签。一个词在不同语境可以有不同译法。将跨页限定、施事、动作对象和基准对象一起复核。检查重复机构名的误展开、机器翻译元数据、同系列标题的编号与统一译名。示例：评估问卷中 Gear #4 为“评估维度 4”，机械系统中的 landing gear 则为“起落架”；不要让词表跨语境串义。

```json
{"rules":[{"id":"问卷目录及对应标题","source_pattern":"Gear\\s*#\\s*4","required_target":["评估维度\\s*4"],"forbidden_target":["号车","齿轮"]},{"id":"跨页限定","groups":[["p17.end","p18.start"]],"source_pattern":"all systems of this kind","required_target":["所有同类系统"]}]}
```

运行 `python scripts/context_check.py --content pairs.jsonl --decisions decisions.json --output context.json`。groups 可将跨页前后项合为一次匹配，或逐个列出目录、书签、标题等预期定位。批准多个译法可用单个正则备选表达式。核对源件存在的条目；未测量或命中异常应审读原句、修订并回放。脚本匹配不能判断数量范围或否定的修饰关系。终检在最终 PDF 再查一遍受影响的出现位置，并实看图中文字。
