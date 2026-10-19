param(
  [Parameter(Mandatory=$true)][string[]]$Bv,
  [switch]$KeepVideo
)
# 批量提取：每个视频一条命令，OCR 在本机跑，不消耗 token。
# 用法：  .\批量处理.ps1 -Bv BV1NtJi6bEe3,BV1hZax63Efj
$py = 'E:\Desktop\GPT\视频\.venv-ocr\Scripts\python.exe'
$script = 'E:\Desktop\DS\视频\video2text.py'
foreach ($b in $Bv) {
  $extra = @()
  if (-not $KeepVideo) { $extra += '--delete-video' }
  & $py $script $b @extra
  if ($LASTEXITCODE -ne 0) { Write-Warning "失败：$b" } else { Write-Host "完成：$b" -ForegroundColor Green }
}
