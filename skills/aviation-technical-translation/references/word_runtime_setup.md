# Windows Word 导出运行配置

直接生成中文 PDF 和运行 PDF 自检无需 Microsoft Word。需要验证 Word 导出的 DOCX 时，请在有桌面版 Word 的 Windows 电脑上，以获准运行导出器的普通用户配置一次。使用该用户的 64 位 Windows PowerShell 5.1 和具备 `lxml`、`pypdf` 的 Python。配置文件只保存在该用户的本机应用数据目录。

在已激活相应 Python 环境的 PowerShell 中运行：

```powershell
$ErrorActionPreference = 'Stop'
$operatorSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$python = (Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
& $python -I -B -c 'import lxml.etree, pypdf'
if ($LASTEXITCODE -ne 0) { throw 'Word Python dependencies unavailable' }
$dir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'AviationTranslation'
$file = Join-Path $dir 'word-export.json'
if (Test-Path -LiteralPath $file) { throw 'Existing configuration: inspect before changing it.' }
[void][IO.Directory]::CreateDirectory($dir)
@{UserSid=$operatorSid; Python=$python} | ConvertTo-Json | Out-File -LiteralPath $file -Encoding utf8 -NoClobber
```

两个导出进程分别核对配置中的 SID 与当前 Windows 身份，并沿用原有的非管理员、交互会话、进程归属与超时检查。更换用户或解释器时重新核对本机配置。用 `scripts/Export-Word.ps1 -InputPath sample.docx -OutputDirectory fresh-output -CheckRuntimeOnly` 检查脚本哈希；只有对真实 DOCX 在新的本地输出目录完成导出和成品验页后，才能报告 Word 路径通过。
