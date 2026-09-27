# Aviation Translation Core（民航技术翻译与 QA 核心）

[English](README.md)

**公开的预发布源码仓库。** 面向民航技术英中翻译的规则、术语/数字/结构机械检查及 QA 交接轻量核心。现有 Skill 标识为 `aviation-translation-core`；本目录本身并未安装为 Skill，尚未发布带标签的正式 GitHub Release。

面向能够准备独立源文证据、处理语义疑点的翻译人员和审核人员。**脚本不会自动翻译。** 英文及中文 Demo 均为原创合成输入，不是模型性能结果，也不代表实际译文质量。

## 能做什么

- 检查明确配置的术语形式、必需/禁用译文、顺序数字、声明的单位/标识符/符号和标记。
- 核对支持的文本 PDF 与源文单元映射、源译单元完整性、脚注正文引用和表格坐标/内容绑定。
- 核对输入哈希、范围及规则绑定，检查合成 QA 交接和复核/决策记录的一致性。

它不是自动翻译器、权威术语库、Word/PDF 出版系统、通用科学解析器、PDF 安全扫描器或可信独立审核平台。真实宿主 QA 适配器尚未实现。快照只核对其绑定契约，不能代替术语及源译不变量检查；第二份 JSON 不能证明存在独立审核。

## 最短入口

按 [Windows 使用说明](docs/quickstart.md) 选择兼容 Python、创建私有隔离环境、安装锁定依赖，再运行离线原创示例及现有测试。不要求了解 Git。该说明准备好 `$py` 和全新的 `$demo` 目录后，示例入口为：

```powershell
& $py -X utf8 -I -B examples/run_demo.py --output $demo
if ($LASTEXITCODE -ne 0) { throw 'Demo failed; stop and inspect private output.' }
```

Demo 生成四份摘要及私有合成输入。`mechanical_status=PASS`、`completion=BLOCKED_PENDING_REAL_QA`、`human_approved=false` 和 `released=false` 同时出现是当前设计。机械 PASS 不是语义质量、人审或整篇译文发布许可通过。运行源译注册文件及生成 PDF 不应随摘要分享。

## 环境与限制

已记录的 Windows 环境为 CPython 3.12.14、pypdf 6.19.0、jsonschema 4.26.0；全部七项固定依赖见 [requirements.lock](requirements.lock)。锁文件哈希针对特定安装包，不保证任意解释器、架构或平台均可安装。Linux 补充运行不等于此 Windows 锁文件在 Linux 上完成安装验证。

R1 的 Windows 回归记录为 99 项中 98 通过、0 失败、1 项文件符号链接测试因权限不足记为 NOT_TESTED。这是候选的工程验证历史，与原工作流长期自用经历分开。不要为使测试通过而提权。参阅[输入契约与数值限制](docs/input_contract.md)、[人工准备输入](docs/preparing_inputs.md)。超出支持范围的记法或文档层必须保留未解决审核状态，机械 PASS 不能消除此阻断。

## 文档与来源

- [贡献说明](CONTRIBUTING.md)、[安全说明](SECURITY.md)、[未发布变更记录](CHANGELOG.md)、[路线图](ROADMAP.md)。
- [翻译规则](references/translation_policy.md)、[术语规则](references/terminology_disambiguation.md)、[QA 交接](references/dual_agent_workflow.md)、[证据绑定](references/evidence_contract.md)、[QA 政策](references/qa_policy.md)。
- [来源说明](docs/provenance.md)、[第三方依赖来源](docs/dependency_provenance.json)。

来源登记为 `USER_REPORTED_AI_ASSISTED`，不等于排他原创保证。维护者声明无共同作者或权利/保密约定（`USER_DECLARATION`），不是法律审计或第三方权利保证。未附带机构材料、旧机翻及术语库；此前机翻服务仍未知，也未接入本项目。未声称获得官方认可。

## 许可与署名

Copyright (c) 2026 Hug800mhz。项目自有核心、规则/文档及原创示例按根目录标准 [MIT 许可证](LICENSE) 提供。第三方依赖保持各自许可，本授权不授予输入原文或他人材料的权利。按 LICENSE 要求，在所有副本或软件的重要部分中保留版权和许可声明；可选致谢不能替代这些声明。

仓库现已公开，但尚未发布带标签的正式 GitHub Release；这不影响本副本所附 MIT 授权。已核对的纯源码分发依赖范围及各依赖的独立许可见[第三方说明](THIRD_PARTY_NOTICES.md)。

### 致谢（可选）

基于本项目开展工作时，欢迎链接回 Aviation Translation Core。本项致谢完全自愿，不增加或替代 MIT 许可证的要求。
