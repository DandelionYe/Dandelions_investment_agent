# Dandelions 投研智能体 API 测试脚本
# 使用方法：在项目根目录运行 .\scripts\API_Test.ps1

$API_BASE = "http://127.0.0.1:8000"
$Color_Success = "Green"
$Color_Error = "Red"
$Color_Warning = "Yellow"
$Color_Info = "Cyan"

function Write-ColorOutput {
    param(
        [string]$ForegroundColor,
        [string]$Message
    )
    $fc = $host.UI.RawUI.ForegroundColor
    $host.UI.RawUI.ForegroundColor = $ForegroundColor
    Write-Output $Message
    $host.UI.RawUI.ForegroundColor = $fc
}

Write-ColorOutput $Color_Info "`n========================================"
Write-ColorOutput $Color_Info "Dandelions 投研智能体 API 测试"
Write-ColorOutput $Color_Info "========================================`n"

# 1. 测试健康检查
Write-ColorOutput $Color_Info "1. 测试健康检查..."
try {
    $response = Invoke-RestMethod -Uri "$API_BASE/api/v1/health" -Method Get
    
    # 检查 API 和数据库状态（Redis 是可选的）
    $apiOk = ($response.api.status -eq "ok")
    $dbOk = ($response.db.status -eq "ok")
    
    if ($apiOk -and $dbOk) {
        Write-ColorOutput $Color_Success "✓ API 和数据库正常"
        if ($response.redis.status -eq "ok") {
            Write-ColorOutput $Color_Success "✓ Redis 正常"
        } else {
            Write-ColorOutput $Color_Warning "⚠ Redis 未启动 (可选功能，不影响主要功能)"
        }
    } else {
        Write-ColorOutput $Color_Error "✗ 健康检查失败"
        Write-ColorOutput $Color_Error "API 状态: $($response.api.status)"
        Write-ColorOutput $Color_Error "数据库状态: $($response.db.status)"
        Write-ColorOutput $Color_Error "Redis 状态: $($response.redis.status)"
        Write-ColorOutput $Color_Warning "请确保 FastAPI 服务正常启动"
        exit 1
    }
} catch {
    Write-ColorOutput $Color_Error "✗ 无法连接到 API 服务"
    Write-ColorOutput $Color_Error "错误: $_"
    Write-ColorOutput $Color_Warning "请确保 FastAPI 服务已启动: uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload"
    exit 1
}

Write-ColorOutput $Color_Info "`n2. 测试用户登录..."
$loginBody = @{
    username = "admin"
    password = "dandelions2026"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$API_BASE/api/v1/auth/login" -Method Post -Body $loginBody -ContentType "application/json"
    $accessToken = $response.access_token
    $refreshToken = $response.refresh_token
    Write-ColorOutput $Color_Success "✓ 登录成功"
    Write-ColorOutput $Color_Success "  Access Token: $($accessToken.Substring(0, 50))..."
    Write-ColorOutput $Color_Success "  Refresh Token: $($refreshToken.Substring(0, 50))..."
    Write-ColorOutput $Color_Success "  Token 类型: $($response.token_type)"
} catch {
    Write-ColorOutput $Color_Error "✗ 登录失败"
    Write-ColorOutput $Color_Error "错误: $_"
    Write-ColorOutput $Color_Warning "请检查用户名和密码是否正确"
    exit 1
}

# 3. 测试观察池 - 文件夹
Write-ColorOutput $Color_Info "`n3. 测试观察池 - 文件夹列表..."
$headers = @{
    "Authorization" = "Bearer $accessToken"
    "Content-Type" = "application/json"
}

try {
    $response = Invoke-RestMethod -Uri "$API_BASE/api/v1/watchlist/folders" -Method Get -Headers $headers
    Write-ColorOutput $Color_Success "✓ 获取文件夹列表成功"
    if ($response) {
        $response | ConvertTo-Json -Depth 10
    } else {
        Write-ColorOutput $Color_Warning "  暂无文件夹"
    }
} catch {
    Write-ColorOutput $Color_Error "✗ 获取文件夹列表失败"
    Write-ColorOutput $Color_Error "错误: $_"
}

# 4. 测试观察池 - 观察项
Write-ColorOutput $Color_Info "`n4. 测试观察池 - 观察项列表..."
try {
    $response = Invoke-RestMethod -Uri "$API_BASE/api/v1/watchlist/items?page_size=50" -Method Get -Headers $headers
    Write-ColorOutput $Color_Success "✓ 获取观察项列表成功"
    Write-ColorOutput $Color_Success "  总数: $($response.total)"
    if ($response.items) {
        Write-ColorOutput $Color_Success "  列表: $($response.items.Count) 项"
        # 显示前 3 个观察项
        $response.items | Select-Object -First 3 | ForEach-Object {
            Write-ColorOutput $Color_Info "    - $($_.symbol) ($($_.asset_type))"
        }
        if ($response.items.Count -gt 3) {
            Write-ColorOutput $Color_Warning "    ... 还有 $($response.items.Count - 3) 项"
        }
    } else {
        Write-ColorOutput $Color_Warning "  暂无观察项"
    }
} catch {
    Write-ColorOutput $Color_Error "✗ 获取观察项列表失败"
    Write-ColorOutput $Color_Error "错误: $_"
}

# 5. 测试观察池 - 标签
Write-ColorOutput $Color_Info "`n5. 测试观察池 - 标签列表..."
try {
    $response = Invoke-RestMethod -Uri "$API_BASE/api/v1/watchlist/tags" -Method Get -Headers $headers
    Write-ColorOutput $Color_Success "✓ 获取标签列表成功"
    if ($response) {
        $response | ConvertTo-Json -Depth 10
    } else {
        Write-ColorOutput $Color_Warning "  暂无标签"
    }
} catch {
    Write-ColorOutput $Color_Error "✗ 获取标签列表失败"
    Write-ColorOutput $Color_Error "错误: $_"
}

# 6. 测试研究任务 - 提交任务
Write-ColorOutput $Color_Info "`n6. 测试提交研究任务..."
$researchBody = @{
    symbol = "000001.SZ"
    asset_type = "stock"
    data_source = "mock"
    use_llm = $true
    use_graph = $true
    max_debate_rounds = 3
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$API_BASE/api/v1/research/single" -Method Post -Body $researchBody -Headers $headers
    $submittedTaskId = $response.task_id
    Write-ColorOutput $Color_Success "✓ 提交研究任务成功"
    Write-ColorOutput $Color_Success "  Task ID: $($response.task_id)"
    Write-ColorOutput $Color_Success "  状态: $($response.status)"
} catch {
    Write-ColorOutput $Color_Error "✗ 提交研究任务失败"
    Write-ColorOutput $Color_Error "错误: $_"
}

# 7. 测试研究任务 - 查询任务状态
Write-ColorOutput $Color_Info "`n7. 测试查询任务状态..."
try {
    if (-not $submittedTaskId) {
        Write-ColorOutput $Color_Warning "  跳过（没有已提交的任务）"
    } else {
        $response = Invoke-RestMethod -Uri "$API_BASE/api/v1/research/$submittedTaskId" -Method Get -Headers $headers
        Write-ColorOutput $Color_Success "✓ 查询任务状态成功"
        Write-ColorOutput $Color_Info "  任务 ID: $($response.task_id)"
        Write-ColorOutput $Color_Info "  状态: $($response.status)"
        Write-ColorOutput $Color_Info "  进度: $($response.progress)"
        if ($response.status -eq "completed") {
            Write-ColorOutput $Color_Success "  评分: $($response.score)"
            Write-ColorOutput $Color_Success "  评级: $($response.rating)"
            Write-ColorOutput $Color_Success "  建议: $($response.action)"
        }
    }
} catch {
    Write-ColorOutput $Color_Error "✗ 查询任务状态失败"
    Write-ColorOutput $Color_Error "错误: $_"
}

# 8. 测试获取当前用户信息
Write-ColorOutput $Color_Info "`n8. 测试获取当前用户信息..."
try {
    $response = Invoke-RestMethod -Uri "$API_BASE/api/v1/auth/me" -Method Get -Headers $headers
    Write-ColorOutput $Color_Success "✓ 获取用户信息成功"
    Write-ColorOutput $Color_Success "  用户名: $($response.username)"
    Write-ColorOutput $Color_Success "  角色: $($response.role)"
    if ($response.enabled) {
        Write-ColorOutput $Color_Success "  状态: 启用"
    } else {
        Write-ColorOutput $Color_Success "  状态: 禁用"
    }
} catch {
    Write-ColorOutput $Color_Error "✗ 获取用户信息失败"
    Write-ColorOutput $Color_Error "错误: $_"
}

Write-ColorOutput $Color_Info "`n========================================"
Write-ColorOutput $Color_Success "测试完成！"
Write-ColorOutput $Color_Info "========================================"
