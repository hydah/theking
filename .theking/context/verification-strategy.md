# Verification Strategy

## 目标

让 theking 不再把 e2e 简化成“要不要浏览器”一个布尔值，而是按运行环境定义更清晰的验证画像。

## 当前画像

| execution_profile | 适用对象 | 默认验证方式 | review 要求 |
|------|------|------|------|
| `web.browser` | Web 页面、用户路径、前端交互 | 浏览器 / Playwright | 始终需要 code review pair；额外需要 `e2e-review-round-*` |
| `backend.http` | API、服务端接口、HTTP 服务 | 黑盒 HTTP 请求 | 始终需要 code review pair；额外需要 security review pair |
| `backend.cli` | CLI、脚本、批处理入口 | 子进程执行与产物校验 | 始终需要 code review pair |
| `backend.job` | 异步任务、worker、job | 触发任务并验证副作用 | 始终需要 code review pair |

## 当前 contract

- `task_type` 仍表示业务语义，例如 `auth`、`api`、`frontend`
- `execution_profile` 表示运行环境
- `verification_profile` 当前默认与 `execution_profile` 对齐，为单元素列表
- `requires_security_review` 由 `task_type + execution_profile` 共同推导
- `required_agents` 由 `task_type + execution_profile` 共同推导

## 设计边界

- 这一轮只定义目录、字段和校验逻辑
- 不自动创建 Playwright 脚本，也不自动启动后端服务
- task 级证据应落在对应 task 的 `verification/` 目录

## 后续扩展

- 支持一个 task 有多个 verification profile
- 在 `init-task` 或后续命令中生成 profile-specific verification 模板

## backend.http Integration Test Gate (I-014)

`backend.http` 的 code-review + security-review 只审**代码质量**，不验证
**运行时行为**。WebSocket / gRPC / 流式 API 的 bug 几乎都出在连接管理和
协议交互层面，unit test 盖不到。

### 要求

`backend.http` profile 的 task，在 `verification/http/` 下除已有的
smoke.md（冷启动证明）外，还应包含 **integration test 证据**：

| 层级 | 适用范围 | 要求 |
|------|---------|------|
| L1: 连接级 | 所有 backend.http task | 能建连 + 合法响应（200/101）+ 正常断连 |
| L2: 业务级 | 改了核心逻辑的 task | 发真实/mock 请求 → 断言响应内容正确 |

### 最低证据格式

```markdown
## Integration Test Evidence

### Test Setup
- 启动命令: (实际命令)
- 环境: (test server / mock / real upstream)

### Covered Endpoints (至少 1 个)
- [ ] METHOD /path → 状态码 + 响应摘要

### Test Output
(粘贴 test 输出，或引用 test.log 路径)
```

### 工具选择

不要求 Playwright——backend.http 的集成测试用语言原生测试框架：
- Go: `httptest.Server` + `gorilla/websocket` client
- Node: supertest / ws
- Python: pytest + httpx / websockets

### 不做

- 不把 integration test 变成 e2e-runner agent 的职责（e2e-runner 是 Playwright 专用）
- L1 是最低要求；L2 是改核心逻辑时的追加要求，不是所有 task 都必须