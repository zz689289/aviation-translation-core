---
name: aviation-technical-translation
description: "将英文民航技术文献译为中文，审校术语与技术含义，按源文重建 PDF 或可编辑 DOCX，并验证实际页面。适用于航空论文、机构指南及其局部修订。"
metadata:
  version: "1.2.2-rc7"
---

# 航空技术翻译

[推荐翻译提示词（中／英）](prompts/TRANSLATION_PROMPT.md) · [安装提示词](prompts/INSTALL_PROMPT.md)

以本次源文、交付目标和有效决定为准。解析本目录为 `SKILL_ROOT`，脚本用绝对路径调用。现有授权覆盖同范围常规修复；不因换模型、恢复会话或改一个文件名重新请示。

## 按任务加载

| 当前任务 | 读取及执行 |
|---|---|
| 短句、术语问题 | [翻译规则](references/translation_policy.md)；有歧义时读[术语分流](references/terminology_disambiguation.md)。直接答复，不建工程、不查 Word。 |
| 新文档翻译 | [接收与续接](references/intake_workflow.md)、翻译规则；一次明确源文、格式、术语来源、适用样式。 |
| 直接 PDF（含论文） | 首次翻译即加载 [PDF 工作流](references/pdf_workflow.md)、[呈现证据](references/presentation_review.md)和 [QA](references/qa_policy.md)。先读原页确定版式，再用对应译页小样验证。 |
| 可编辑 DOCX | 加载[出版流程](references/publication_workflow.md)、[Word 版式](references/docx_layout_policy.md)及 [QA](references/qa_policy.md)。保留明确要求的 `publication_grade_docx`。 |
| 局部修订或恢复 | 先读现有当前状态和[接收与续接](references/intake_workflow.md)的对应段；再加载目标格式规则。只追查与当前问题有关的历史。 |
| PDF版式证据或交付效果比较 | 加载[呈现证据与交付阶段](references/presentation_review.md)；分别核对源测量、实际输出与用户反馈，勿以内容计数代替样式或复制检查。 |
| 独立 QA | [双线程协作](references/dual_agent_workflow.md)、[QA](references/qa_policy.md)、[证据合同](references/evidence_contract.md)。 |
| 同类问题再现 | 查 [failure_modes.md](references/failure_modes.md) 对应条目。将项目案例、人工意见与运行证据存放在本次工作的私有目录。 |

可用 `scripts/workflow.py plan --spec 请求.json --output 新计划.json`验证路由；小任务无需为调用工具额外建表。

## 排版、长文和核验方式

采用推荐提示词时，把可编辑的中文正文／标题字体、西文字体、字号、行距和疏页调节写入实际生成参数。[排版与非交互验收](references/typography_and_headless_qa.md)列出选区核对方法。本 Skill 全流程禁用 Computer Use、桌面或浏览器 UI 控制以及剪贴板，独立 QA 同样执行。使用 CLI 提取、实际页渲染、字体、文本层及链接检查。

长文、跨批连续段、重复栏目或图集，先读[长文翻译与续接](references/long_translation.md)。一次请求内按实际可审的批次持续执行。目录、书签、正文与图签归到相同语义对象；记录定义、施事、限定范围与依据。只有内容组装、语义审查、图内文字及当前输出核验均完成，才提交正式完整译稿。

## 保真与保护

英文原件控制技术含义、结构、编号与样式意图；已批准的术语不能改变原义，机翻只作句级辅助。保留条件、例外、否定、义务强度、数字、单位大小写、公式、标识符和引用。疑似源文错误先保留，单列依据和待决项，不悄悄勘误。

完整文档须覆盖正文、表格、图中文字、文本框、脚注、公式、目录和前后置内容；有序源 ID、恰好一次消费、合并谱系及 `owner_ref/source_owner_ref` 继续有效。原文、已认可成果与历史证据保持只读，在版本化副本修订。

完整排版默认沿用原文的页面结构。中文可以自然换行、换栏和增减页数；栏数和阅读顺序、对象占栏或跨栏、页边与页底内容的角色随原文。用户指定的改版按其范围执行。先在原页定位这些关系，再将首页和本篇高风险对象的译页小样与原页并排核对；首交前按对象映射对照最终渲染。同一正文样式沿用小样定下的基线距。按中文末行衔接下段与图表组，在小样和最终实际页核对段前、图前和表前净空。个人字体等偏好见 [personal_style.md](references/personal_style.md)。

## 执行与一名独立 QA

文档级翻译、重建和实质修订使用主线程执行与协调，加**最多一名真实独立 QA**；复用同一 QA，不递归、不加调度员或第三审查员。小段和微小确定性编辑不必派发。翻译执行与最终验收测试使用 `gpt-6.2-sol`、`high`。独立 QA 默认明确派发 `gpt-6.2-sol`、`medium`。仅对中档复核后仍难以裁决的具体语义或视觉对象，记录页码、原因和范围后可用同一 Sol 的 `high`，其余仍用中档。QA 先看源文与冻结候选，再看执行者结论，只写自身证据，不改生产文件、不操作 Word。

`workflow.py` 管理快照、路由、覆盖、影响范围与缓存；它不能模拟独立审核。无法派发时记 `INDEPENDENT_QA_UNAVAILABLE`。模型名称或角色标签不能证明实际档位，也不能授予权限。

源证明晰、目标已授权、同根因同范围的缺陷一次查找并修复全部受影响对象；普通工作未完成不记 AMBER，不塞入人工裁决队列。真实技术歧义、源文勘误、已批准术语含义变更、新外部权限或正式发布分别集中交接，继续不依赖这些决定的工作。连续两轮同类修复无实质进展，先查根因或检查器。

## 验证与完成

局部修复检查对象、上下文、实际变化页及必要邻页；全局字体、编号或分页变化扩大检查。复用证据必须同时满足工件绑定、检查内容适用及未被新缺陷推翻。相同像素不能证明旧检查充分，缩略总览图不能代替可读单页或细节观察。

DOCX 在 Word 前及保存后运行 `scripts/docx_preflight.py`；正文内隐藏字符、属性顺序错误不得靠规范化检查掩盖。导出使用[已批准工具](references/word_export_tool.md)。只有最终稳定候选执行适用的双 Word 导出；双导出一致仅证明稳定性。

最终仍须完整源文覆盖、适用的实际全页核验及稳定导出证据。分别记录工程完成、语义 QA、视觉 QA、用户终校和发布状态；未检项目如实保留。用户“继续”不等于整篇签收或发布批准。简洁交付实际成果、范围、未决项与下一动作，不用中间 PASS 代替最终结论。
