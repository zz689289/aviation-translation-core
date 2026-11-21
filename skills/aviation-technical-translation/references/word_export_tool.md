# Windows Word 导出

入口 `scripts/Export-Word.ps1` 校验随包导出器的文件哈希。PDF 直出流程可独立使用。需要 Word 导出时，先在本机授权的非管理员交互账户建立配置，见 [Word 运行配置](word_runtime_setup.md)。

通过64位 Windows PowerShell 5.1、STA、RemoteSigned及正常单次沙箱审批调用；不设置永久审批前缀。输入是明确DOCX，输出必须全新目录。先运行 `docx_preflight.py`，仅在结构和文本检查通过后导出。

- `UpdateSave`：只改新副本；预审字段和对象依赖，更新允许的内部字段及完整目录、分页、保存、关闭重开再导出。验证磁盘字段缓存及实际正文位置。
- `ReadOnly`：从同一冻结DOCX独立复制，不更新不保存。最终两次运行不能把run1输出作为run2输入；dirty或缓存问题须在冻结前解决。
- 默认Word阶段90秒；恢复时优先复用本篇经验证且仍适用的阶段时限，可显式15–600秒。不要把整个文档所有阶段归入一个超时，也不要每次恢复退回默认。
- 现有运行时只绑定自己的Word实例及精确PID/启动时间/Session，用户其他Word保持打开；正常退出才算成功。意外提示或失败产物保留，不点击未知提示，不修改Office、安全策略或全局设置。

`-CheckRuntimeOnly`只检查依赖，不启动Word，不证明导出能力。实际成功要求退出码0、`Status=PASS`、`NormalExit=true`及最终report；`.work`、`.publish`和失败run中的PDF不是交付件。

只用 `artifacts/` 中成功发布到本地输出目录的文件；这里的运行时“publish”是原子落盘，不代表公开发布授权。保存后的DOCX再次运行原始文本/属性检查，核对源语义样式与实际PDF。两次一致只能证明稳定性，不能替代源文覆盖、视觉检查、用户终校或正式发布授权。

旧 `render_docx.py/word_postprocess.ps1`仅供其既有适用工作流维护，不能因候选桥接失败而自动切换。确实需要Word界面/打印预览验证而工具不可用时记未检；PDF正常不能替代该项。
