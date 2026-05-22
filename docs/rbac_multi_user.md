# RBAC 多用户隔离

## 角色定义

| 角色 | 标识 | 说明 |
|------|------|------|
| 管理员 | `role == "admin"` | 可跨用户访问所有资源，可管理用户 |
| 普通用户 | `role == "user"` | 只能访问自己拥有的资源 |

## 普通用户权限

**可以：**
- 创建、查看、修改、删除自己的观察池文件夹、标签、观察项
- 触发自己观察池内的扫描
- 查看自己的批量扫描进度和扫描历史
- 查看、取消、读取结果、下载报告自己的研究任务
- 订阅自己的任务 WebSocket 和批量扫描 WebSocket

**不可以：**
- 访问其他用户的观察池、任务、报告
- 访问用户管理接口
- 订阅全局事件流 (`/ws/events`)
- 即使知道 task_id 或文件路径也不能访问他人资源（返回 404）

## 管理员权限

**可以：**
- 注册新用户 (`POST /api/v1/auth/register`)
- 列出所有用户 (`GET /api/v1/auth/users`)
- 启用/禁用用户、修改角色 (`PATCH /api/v1/auth/users/{user_id}`)
- 查看和管理所有用户的任务、报告、观察池和批次
- 通过 `?username=` 参数查看指定用户数据
- 订阅全局事件流

**限制：**
- 不能禁用最后一个 enabled admin 账户

## 资源 Owner 字段

| 资源 | Owner 字段 | 说明 |
|------|-----------|------|
| research_tasks | `created_by` | 创建任务的用户名 |
| watchlist_folders | `owner_username` | 创建文件夹的用户名 |
| watchlist_items | `owner_username` | 创建观察项的用户名 |
| watchlist_tags | `owner_username` | 创建标签的用户名 |
| watchlist_batches | `owner_username` | 创建批次的用户名 |
| reports | 通过 task `created_by` 间接授权 | 报告文件归属由任务决定 |

## 唯一约束隔离

- `watchlist_items`: `(owner_username, symbol)` — 不同用户可以观察同一标的
- `watchlist_tags`: `(owner_username, name)` — 不同用户可以创建同名标签
- `watchlist_folders`: owner 隔离（应用层校验，非数据库约束）

## 默认单机自用模式

现有默认 admin 用户仍然可用：
- `.env` 中 `AUTH_ADMIN_USER/AUTH_ADMIN_PASS` 配置不变
- seed admin 行为保留
- 只有一个 admin 用户时，操作体验与之前完全一致
- 不需要额外的租户配置或组织表

## 旧数据迁移策略

项目使用 SQLite，无 Alembic。迁移逻辑在 `WatchlistStore._init_db()` 中实现：

1. `CREATE TABLE IF NOT EXISTS` — 新表定义含 `owner_username` 列
2. `PRAGMA table_info()` — 检测旧表是否缺少 `owner_username` 列
3. `ALTER TABLE ADD COLUMN` — 为旧表补列，默认值 `'default'`

**兼容策略：**
- 旧 watchlist 数据归属到 `'default'` owner
- 旧 research_tasks 的 `created_by` 已有默认值 `'default'`
- 普通用户 `username='default'` 可访问这些旧数据
- 管理员可查看全部

**注意事项：**
- 旧数据库的 `watchlist_items` 保留 `UNIQUE(symbol)` 约束（非 per-owner）
- 新建数据库使用 `UNIQUE(owner_username, symbol)` 约束
- 如需 per-owner 唯一约束，需重建数据库

## Streamlit 本地 Fallback 安全边界

### 报告库 (`2_Report_Library.py`)
- **不再**直接扫描 `storage/reports` 目录
- 改为通过 API (`/api/v1/research/history` + `/api/v1/reports/{task_id}/info`) 获取
- 下载走 `/api/v1/reports/{task_id}/{fmt}`，受 task owner 权限控制

### 观察池 (`3_观察池.py`)
- 默认只通过 API 调用
- 本地 SQLite fallback **默认关闭**
- 启用需设置环境变量：`STREAMLIT_LOCAL_STORE_FALLBACK=true`
- 仅建议单机自用场景启用

### 单票研究 (`1_Single_Asset_Research.py`)
- 默认使用异步 API 模式（任务进入系统，受权限控制）
- 同步本地模式保留但标注"仅适合单机自用"
- 同步模式生成的报告不进入任务系统，其他用户不可见

## WebSocket 权限策略

| 端点 | 普通用户 | 管理员 |
|------|---------|--------|
| `/ws/task/{task_id}` | 仅自己的 task | 任意 task |
| `/ws/batch/{batch_id}` | 仅自己的 batch | 任意 batch |
| `/ws/events` | **禁止** (close code 4003) | 全局事件流 |

权限校验在 WebSocket accept 之前完成。未授权时使用明确 close code 和 reason。

## API 端点汇总

### 认证 (`/api/v1/auth`)
| 方法 | 路径 | 权限 |
|------|------|------|
| POST | `/login` | 公开 |
| POST | `/token` | 公开 |
| POST | `/refresh` | 公开 |
| GET | `/me` | 已认证 |
| POST | `/register` | admin |
| GET | `/users` | admin |
| PATCH | `/users/{user_id}` | admin |

### 研究任务 (`/api/v1/research`)
| 方法 | 路径 | 权限 |
|------|------|------|
| POST | `/single` | 已认证（created_by=当前用户） |
| GET | `/history` | 已认证（普通用户看自己的，admin 看全部） |
| GET | `/{task_id}` | 已认证（owner 或 admin） |
| GET | `/{task_id}/result` | 已认证（owner 或 admin） |
| DELETE | `/{task_id}` | 已认证（owner 或 admin） |

### 报告 (`/api/v1/reports`)
| 方法 | 路径 | 权限 |
|------|------|------|
| GET | `/{task_id}/info` | 已认证（task owner 或 admin） |
| GET | `/{task_id}/{fmt}` | 已认证（task owner 或 admin） |

### 观察池 (`/api/v1/watchlist`)
| 方法 | 路径 | 权限 |
|------|------|------|
| GET | `/folders` | 已认证（owner 过滤） |
| POST | `/folders` | 已认证（归属当前用户） |
| PUT | `/folders/{id}` | 已认证（owner 或 admin） |
| DELETE | `/folders/{id}` | 已认证（owner 或 admin） |
| GET | `/items` | 已认证（owner 过滤） |
| POST | `/items` | 已认证（归属当前用户） |
| GET | `/items/{id}` | 已认证（owner 或 admin） |
| PUT | `/items/{id}` | 已认证（owner 或 admin） |
| DELETE | `/items/{id}` | 已认证（owner 或 admin） |
| GET | `/tags` | 已认证（owner 过滤） |
| POST | `/tags` | 已认证（归属当前用户） |
| PUT | `/tags/{id}` | 已认证（owner 或 admin） |
| DELETE | `/tags/{id}` | 已认证（owner 或 admin） |
| POST | `/scan` | 已认证（owner 过滤） |
| GET | `/scan/{batch_id}` | 已认证（owner 或 admin） |
| GET | `/results` | 已认证（owner 过滤） |
