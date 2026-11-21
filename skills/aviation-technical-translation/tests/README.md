# 原创回归材料

这些材料是原创中性样例，不包含历史文献、译文、机构截图或私人术语库。使用既有兼容 Python 环境，无需安装依赖。普通单元测试使用标准库；完整 DOCX 样稿生成另用现有 `python-docx`。

```text
python -B -m unittest discover -s scripts -p "test*.py" -v
python -B -m unittest discover -s tests -p "test*.py" -v
python -B tests/compare_baseline.py --baseline BASELINE --candidate CANDIDATE --output NEW_RESULT_DIR
python -B tests/make_neutral_pilot.py --output NEW_PILOT_DIR
```

前两条从 Skill 根目录执行。输出目录必须是新的；所有临时文件放到本次测试目录中。基线与候选分别在隔离进程加载。配对探针中的 JSON 是明确标注的合成数据，只检验门禁逻辑，不充当真实独立 QA。

原创 Word 小样包含英文源件和两个不预标答案的译本。独立 QA 应先读源文与译本，再读 `expectations.json` 和生成器。正确译本通过保存前预检后，用既有获准 Word 运行时对新副本执行 UpdateSave；再预检保存结果、查看实际页面。最终稳定性测试从同一冻结副本独立执行两次 ReadOnly。故意错误的译本应先被预检拦下，不必送 Word。

`docx_preflight` 只检查列明的原始字符与 OOXML 属性位置，不是通用 OOXML schema 验证器，也不验证技术语义。PDF 页面的稳定性和 Word 界面检查分别记录；不能把机械通过提升为完整翻译验收。
