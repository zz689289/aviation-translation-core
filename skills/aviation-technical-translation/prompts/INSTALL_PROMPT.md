# 在 Codex 中安装航空技术翻译 Skill

新开一次 Codex 对话，粘贴以下整段。如果从其他电脑复制了安装包，也可连同 SHA256SUMS.txt 一起附上。

```text
请为当前用户安装 GitHub 项目 zz689289/aviation-translation-core 的完整 aviation-technical-translation Skill，版本 1.2.2-rc7。全程使用文件与命令行，禁用 Computer Use、桌面或浏览器控制、剪贴板。不要上传用户文献。

1. 使用我提供的航空翻译 Skill ZIP 和同版 SHA256SUMS.txt，或从以下同一版本的地址下载这两份文件：
https://raw.githubusercontent.com/zz689289/aviation-translation-core/refs/tags/skill-v1.2.2-rc7/downloads/aviation-technical-translation-1.2.2-rc7.zip
https://raw.githubusercontent.com/zz689289/aviation-translation-core/refs/tags/skill-v1.2.2-rc7/downloads/SHA256SUMS.txt
校验 ZIP 的 SHA-256，核对内部路径均属于 aviation-technical-translation，拒绝绝对、越界路径及符号链接。解压到临时目录，确认 SKILL.md 中的名称和版本。也可从同一 Git 标签的 skills/aviation-technical-translation 子目录安装。

2. 确认实际 CODEX_HOME（通常为 ~/.codex），将通过检查的技能安装到其 skills/aviation-technical-translation 子目录。同内容直接复用；现有内容不同时先在技能发现目录以外完整备份。把 templates/aviation_qa.toml 安装至个人 agents 目录；遇到同名自定义角色先备份并保留无关设置。核对执行与验收测试使用 gpt-6.2-sol/high，独立 QA 使用 gpt-6.2-sol/medium，高档仅用于已记录的具体难项。若主机不支持所需模型或档位，报告实际可用设置。保留个人全局模型及审批设置。

3. 优先复用 Codex 的官方 PDF 插件和已有 Python 环境。主机提供插件管理接口且缺少该插件时，通过该接口安装官方 PDF 插件。也可使用等效命令行工具链。缺少依赖时，在独立 Python 3.11+ 虚拟环境安装 PyMuPDF、pypdf、pypdfium2、Pillow、reportlab、PyYAML、jsonschema。CFF 字体编码回读有警告时安装 fontTools 再验证。DOCX 模式另需 python-docx 和 lxml；需要时再启用官方文档插件。Windows Word 权威导出按 references/word_runtime_setup.md 单独配置。扫描输入按需配置本地 OCR。仅安装缺少的工具，优先使用已验证的 PDFium 或 Poppler。运行中若确实需要系统安装授权，使用宿主的正常审批流程。

4. 定位已获授权的宋体 SimSun、黑体 SimHei、Times New Roman 文件或我明确指定的替代字体，核对嵌入与显示。字体缺失时报告具体名称，避免静默替代。使用最终安装目录中的 scripts/install_smoke.py --body 正文字体文件 --heading 标题字体文件 --latin 西文字体文件 做真实 PDF 自检。若我选择其他字体，还应通过 --expect-body、--expect-heading、--expect-latin 指定实际 PostScript 名称。自检须完成 PDF 生成、两种提取器回读、PDFium 渲染、字体和基线距核验。

5. 在安装目录运行 python -m unittest discover -s tests 和 python -m unittest discover -s scripts。运行 scripts/long_job.py --help 核对长文工具。汇报已装版本、位置、备份位置、实测结果和缺项；核验成功后告诉我如何在新对话调用 $aviation-technical-translation。
```

[推荐翻译提示词（中文及英文）](TRANSLATION_PROMPT.md)
