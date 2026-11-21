# Terminology disambiguation

This is a `CORE_RULE` reference. Project-specific approved terms belong in the project glossary/decision log, not here.

## Governing rule

**短语优先、上下文分流，禁止多义普通单词做无条件全局替换。**

Match the longest approved phrase first. Classify its technical function, inspect the full sentence and nearby heading/table context, then choose the Chinese form. A project glossary may refine the choices below, but it must not erase meaningful distinctions.

## High-risk terms

| English term | Context split | Typical Chinese choices | Dangerous shortcut |
|---|---|---|---|
| Validation | V&V evidence that a model represents intended reality/use; product/process acceptance; ordinary confirmation | 验证 / 有效性确认 / 确认, according to approved domain usage | Translating every occurrence as “确认” |
| test data | Data used to evaluate an ML model; data from a physical/engineering test; generic testing dataset | 测试数据 / 试验数据 / 测试集数据 | Translating every occurrence as “试验数据” |
| Solution | Proposed technical/organizational remedy; numerical solver result; configured system/product | 解决方案 / 解 / 求解结果 / 方案 | Translating every occurrence as “求解” |
| Issue | Document edition/release; a problem/concern; act of issuing | 版本 / 期次 / 问题 / 议题 / 发布 | Translating an issue designator as “问题” |
| qualification | Personnel competence; equipment/process qualification; formal qualification activity | 资质 / 资格 / 鉴定 / 合格评定 | Using one Chinese word across people, equipment, and processes |
| error | Numerical/model error; measurement error; software fault; human mistake | 误差 / 错误 / 差错 / 故障, by mechanism | Converting all `error` to “误差” |
| certification | Aircraft/product approval; certification process/evidence; person credential | 审定 / 认证 / 取证, by aviation context | Treating all aviation certification as generic “认证” |
| Safety | Protection from accidental harm and unacceptable operational risk | 安全性 / 安全 | Collapsing Safety and Security into one undifferentiated term |
| Security | Protection from malicious or unauthorized action, cyber threat, or intentional interference | 安保 / 信息安全 / 网络安全 / 安全防护 | Translating cyber/security controls as ordinary “安全性” |
| MOC / MOCs | Means of Compliance in regulatory/certification context; another expansion only if explicitly defined | 符合性方法（MOC）/ 符合性方法（复数仍保留 MOC 或按项目规则） | Treating `MOCs` as an unrelated acronym or mechanically adding Chinese plural |
| FSM | Preserve the source expansion; it may name a project-specific model rather than a universal term | First occurrence: approved expansion + FSM; later: FSM | Guessing the expansion from the acronym alone |
| high-fidelity | Fidelity/representativeness of a model or simulation | 高保真 / 高逼真度, by glossary | Translating as high-frequency |
| high-frequency | Frequency-domain or sampling/occurrence property | 高频 / 高频率 | Translating as high-fidelity |

## Decision procedure

For each hit:

1. Capture the complete English phrase and one sentence of context.
2. Identify the object: document, model, data, person, equipment, process, regulator, numerical result, or safety/security control.
3. Check the approved glossary for the longest matching phrase.
4. Check parallel uses in headings, tables, captions, abbreviations, and standards.
5. Select the translation and record the context class.
6. If still ambiguous, flag `TERMINOLOGY_REVIEW`; do not perform a replacement.

## Escalation routing

Finding and extracting a term occurrence can be GREEN when its match/count check is deterministic. Choosing among the context splits above is normally AMBER only when a maintained rule and complete local evidence apply. Route the item to RED when it involves a regulator's fixed expression, an official standard term, normative force, rare/undefined airworthiness language, an unknown acronym, a source contradiction, or a choice that can alter a technical conclusion.

An AMBER item with no `rule_id` is RED. Confidence cannot downgrade a RED signal. Under `economy`, unresolved RED proposals from the economical executor are suppressed from the queue's proposed wording; under every cost profile, RED remains OPEN for the reviewer/actions required by [model_escalation_policy.md](model_escalation_policy.md).

## Safe automated checks

Automation may find occurrences and context, enforce an approved exact phrase within a declared context class, reject forbidden source/target pairs, verify expected counts for a specific overlay, and confirm that only allowlisted blocks changed.

Automation must not globally replace an ambiguous single word, infer an acronym expansion absent from the source/glossary, silently rewrite a source technical quirk, or treat plural morphology such as `MOCs` as a different technical concept without evidence.
