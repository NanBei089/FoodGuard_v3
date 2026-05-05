# Food Label Analyzer API 文档

## 概述

- 基础路径：`/api/v1`
- 认证方式：Bearer Token（JWT）
- 统一响应格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

说明：

- `code=0` 表示成功
- 业务异常会返回项目自定义错误码，如 `40101`、`40901`
- 请求体验证失败时，HTTP 状态码通常为 `422`，响应体中的 `code` 为 `4220`
- `/metrics` 是 Prometheus 原始指标接口，不走统一响应包

---

## 认证接口 `/auth`

### POST `/auth/register/send-code` - 发送注册验证码

请求体：

```json
{
  "email": "user@example.com"
}
```

响应：

```json
{
  "code": 0,
  "message": "验证码已发送",
  "data": {
    "cooldown_seconds": 60
  }
}
```

可能错误：

- `409`：邮箱已注册
- `429`：发送过于频繁
- `503`：邮件服务暂不可用

### POST `/auth/register` - 注册账号

请求体：

```json
{
  "email": "user@example.com",
  "code": "123456",
  "password": "StrongPass123"
}
```

响应：

```json
{
  "code": 0,
  "message": "注册成功",
  "data": null
}
```

密码规则：

- 8 到 32 位
- 必须同时包含大写字母、小写字母和数字

可能错误：

- `400`：验证码无效或密码不符合规则
- `409`：邮箱已注册
- `422`：请求字段校验失败

### POST `/auth/login` - 用户登录

请求体：

```json
{
  "email": "user@example.com",
  "password": "StrongPass123"
}
```

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "Bearer",
    "expires_in": 1800
  }
}
```

可能错误：

- `401`：邮箱或密码错误
- `403`：邮箱未验证

### POST `/auth/refresh` - 刷新令牌

请求体：

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "Bearer",
    "expires_in": 1800
  }
}
```

可能错误：

- `401`：刷新令牌无效、已过期或已撤销

### POST `/auth/logout` - 用户登出

请求体：

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": null
}
```

说明：

- 接口会撤销当前 `refresh_token`
- 重复调用保持幂等

### POST `/auth/forgot-password` - 发送重置密码邮件

请求体：

```json
{
  "email": "user@example.com"
}
```

响应：

```json
{
  "code": 0,
  "message": "如果账号存在，重置邮件已发送",
  "data": null
}
```

说明：

- 不会暴露邮箱是否存在
- 若账号存在，会生成 15 分钟有效的重置令牌

### POST `/auth/reset-password` - 重置密码

请求体：

```json
{
  "token": "reset-token-value",
  "new_password": "NewStrongPass123"
}
```

响应：

```json
{
  "code": 0,
  "message": "密码已重置",
  "data": null
}
```

说明：

- 重置成功后，会撤销该用户所有未失效的 refresh token

---

## 分析接口 `/analysis`

### POST `/analysis/upload` - 上传待分析图片

请求：`multipart/form-data`

- `file`：图片文件，支持 `JPG / PNG / WEBP`

响应：

```json
{
  "code": 0,
  "message": "图片上传成功",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "queued",
    "created_at": "2026-03-25T12:30:00Z"
  }
}
```

说明：

- 外部对用户暴露的初始任务状态是 `queued`
- 数据库内部状态为 `pending`

可能错误：

- `400`：文件为空、格式不支持、图片损坏或超出大小限制
- `401`：未认证
- `429`：当前用户并发分析任务数超限
- `503`：对象存储或任务入队失败

### GET `/analysis/tasks/{task_id}` - 查询任务状态

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "processing",
    "progress_message": "正在分析食品标签...",
    "created_at": "2026-03-25T12:30:00Z",
    "completed_at": null,
    "report_id": null,
    "error_message": null,
    "nutrition_parse_source": null
  }
}
```

状态说明：

| 状态 | 说明 |
|------|------|
| `queued` | 已排队，等待 worker 处理 |
| `processing` | 正在执行分析链路 |
| `completed` | 已完成，可跳转报告详情 |
| `failed` | 已失败，`error_message` 为脱敏后的可见错误 |

`nutrition_parse_source` 仅在任务完成且报告已生成时返回，可能值为：

- `table_recognition`
- `ocr_text`
- `llm_fallback`
- `empty`
- `failed`

---

## 报告接口 `/reports`

### GET `/reports` - 分页查询报告列表

查询参数：

- `page`：页码，从 `1` 开始
- `page_size`：每页条数，最大 `50`

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "report_id": "550e8400-e29b-41d4-a716-446655440001",
        "task_id": "660e8400-e29b-41d4-a716-446655440000",
        "score": 85,
        "summary": "该食品整体风险中等，主要关注钠和添加糖。",
        "image_url": "https://minio.example.com/signed-url",
        "created_at": "2026-03-25T12:30:00Z"
      }
    ],
    "total": 25,
    "page": 1,
    "page_size": 10,
    "total_pages": 3
  }
}
```

说明：

- 仅返回当前用户自己的、未软删除的报告
- 当请求页码越界时，服务端会自动夹取到最后一页

### GET `/reports/{report_id}` - 查询报告详情

响应示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "report_id": "550e8400-e29b-41d4-a716-446655440001",
    "task_id": "660e8400-e29b-41d4-a716-446655440000",
    "image_url": "https://minio.example.com/signed-url",
    "ingredients_text": "配料：水、白砂糖、食用盐、食品添加剂",
    "nutrition": {
      "能量": "180kJ",
      "蛋白质": "2g",
      "脂肪": "0g",
      "碳水化合物": "8g",
      "钠": "50mg",
      "份量": "每100ml"
    },
    "nutrition_table": {
      "title": "营养成分表",
      "subtitle": "每100毫升 (Per 100ml)",
      "serving_basis": "每100毫升 (Per 100ml)",
      "parse_source": "table_recognition",
      "rows": [
        {
          "nutrient_key": "sodium",
          "name_cn": "钠",
          "name_en": "Sodium",
          "display_name": "钠 / Sodium",
          "amount": "50 mg",
          "nrv_percent": 3,
          "nrv_label": "3%",
          "recommendation": "含量可控，注意整体搭配",
          "level": "neutral",
          "is_child": false,
          "parent_key": null
        }
      ],
      "advice_title": "营养师建议",
      "advice_summary": "当前营养结构整体中性，建议结合配料风险综合判断。"
    },
    "nutrition_parse_source": "table_recognition",
    "analysis": {
      "score": 85,
      "summary": "该食品整体风险中等，主要关注钠和添加糖。",
      "hazards": [
        {
          "level": "medium",
          "desc": "钠含量不低，需控制摄入频率"
        }
      ],
      "benefits": [
        "脂肪负担较轻"
      ],
      "ingredients": [
        {
          "name": "阿斯巴甜",
          "risk": "warning",
          "description": "常见甜味剂，建议关注摄入频率和总量。",
          "function_category": "甜味剂",
          "rules": [
            "GB2760-2024"
          ]
        }
      ],
      "health_advice": [
        {
          "group": "儿童",
          "risk": "warning",
          "advice": "建议减少高甜食品摄入频率，避免形成偏甜口味。",
          "hint": "减少频率"
        }
      ]
    },
    "rag_summary": {
      "total_ingredients": 6,
      "retrieved_count": 4,
      "high_match_count": 3,
      "weak_match_count": 1,
      "empty_count": 2
    },
    "artifact_urls": {
      "source_image_key": "uploads/...",
      "cropped_image_key": "reports/.../images/nutrition_crop.jpg",
      "cropped_image_url": "https://minio.example.com/signed-url",
      "llm_output_key": "reports/.../analysis/llm_output.json",
      "llm_output_url": "https://minio.example.com/signed-url"
    },
    "conversation": null,
    "created_at": "2026-03-25T12:30:00Z"
  }
}
```

说明：

- `nutrition` 是便于直接展示的键值格式
- `nutrition_table` 是更完整的结构化营养表数据
- `analysis.score` 最终以规则评分器为准，不直接信任大模型原始分数
- `artifact_urls` 可能同时包含对象键和已解析出的临时访问链接
- `conversation` 为报告绑定问答会话快照；若尚未开始问答则为 `null`

### DELETE `/reports/{report_id}` - 删除报告

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": null
}
```

说明：

- 这里是软删除
- 删除后列表中不可见，但数据库记录仍保留
- 关联的报告问答会话会一并删除

---

## 报告问答接口 `/reports/{report_id}/chat`

### GET `/reports/{report_id}/chat` - 获取报告专属问答会话

若当前报告尚未开始问答：

```json
{
  "code": 0,
  "message": "ok",
  "data": null
}
```

若已存在会话：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "conversation_id": "77c90d75-28e2-48b0-95fc-bf4cf7ef1111",
    "report_id": "550e8400-e29b-41d4-a716-446655440001",
    "suggested_questions": [
      "这份报告里最需要注意的风险是什么？",
      "这款食品适合高血压人群吗？"
    ],
    "messages": [
      {
        "message_id": "880e8400-e29b-41d4-a716-446655440002",
        "role": "user",
        "content": "这款食品适合高血压人群吗？",
        "created_at": "2026-04-12T00:00:00Z"
      },
      {
        "message_id": "990e8400-e29b-41d4-a716-446655440003",
        "role": "assistant",
        "content": "不太适合长期高频食用，主要原因是钠含量偏高。",
        "created_at": "2026-04-12T00:00:03Z"
      }
    ]
  }
}
```

### POST `/reports/{report_id}/chat/suggestions` - 获取快捷提问

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "suggested_questions": [
      "这份报告里最需要注意的风险是什么？",
      "这款食品适合高血压人群吗？",
      "配料里最值得关注的是哪几项？",
      "这款食品更适合偶尔吃还是长期购买？"
    ]
  }
}
```

说明：

- 若数据库里已有建议问题，优先直接返回
- 若没有，则会基于报告上下文和用户偏好按需调用模型生成

### POST `/reports/{report_id}/chat/stream` - 流式生成报告问答

请求体：

```json
{
  "message": "这款食品适合高血压人群吗？"
}
```

响应类型：`text/event-stream`

事件流格式：

#### `meta`

```text
event: meta
data: {"conversation_id":"...","user_message_id":"..."}
```

#### `delta`

```text
event: delta
data: {"text":"不太适合长期"}
```

#### `done`

```text
event: done
data: {"message_id":"...","role":"assistant","content":"完整回答","created_at":"2026-04-12T00:00:03Z"}
```

#### `error`

```text
event: error
data: {"message":"问答生成失败，请稍后重试"}
```

说明：

- 用户问题会先持久化，再启动流式回答
- 流式完成后，助手消息会写入 `report_conversation_messages`
- 如果模型中断，前端可基于已持久化消息做恢复

---

## 用户接口 `/users`

### GET `/users/me` - 获取当前用户资料

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "display_name": "李雷",
    "avatar_url": "https://example.com/avatar.png",
    "is_verified": true,
    "created_at": "2026-03-26T00:00:00Z"
  }
}
```

### PATCH `/users/me` - 更新当前用户资料

请求体：

```json
{
  "display_name": "新名称",
  "avatar_url": "https://example.com/new-avatar.png"
}
```

说明：

- 两个字段都可选
- 传空白字符串会被标准化为 `null`

### POST `/users/change-password` - 修改当前用户密码

请求体：

```json
{
  "current_password": "OldPass123",
  "new_password": "NewStrongPass123"
}
```

说明：

- 修改成功后会撤销该用户所有 refresh token

### DELETE `/users/me` - 注销当前账号

说明：

- 设置 `is_active=false`
- 写入 `deleted_at`
- 撤销所有 refresh token

---

## 偏好接口 `/preferences`

### GET `/preferences/me` - 获取当前用户偏好

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "focus_groups": ["adult", "fitness"],
    "health_conditions": ["hypertension"],
    "allergies": ["花生", "虾"],
    "updated_at": "2026-03-26T00:00:00Z"
  }
}
```

### PUT `/preferences/me` - 保存当前用户偏好

请求体：

```json
{
  "focus_groups": ["adult", "pregnant"],
  "health_conditions": ["diabetes", "hypertension"],
  "allergies": ["花生", "虾", "牛奶"]
}
```

说明：

- `focus_groups` 可选值：`adult / child / elder / pregnant / fitness`
- `health_conditions` 可选值：`diabetes / hypertension / hyperuricemia / allergy`
- `allergies` 会自动去重
- 只要 `allergies` 非空，服务端会自动补上 `allergy` 健康状况

---

## 指标接口

### GET `/api/v1/metrics` - 获取当前进程指标快照

说明：

- 需要登录
- 返回当前进程聚合后的直方图和计数器快照
- 适合调试和后端可观测性展示

示例响应结构：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "generated_at": "2026-04-17T12:30:00Z",
    "process": {
      "pid": 12345
    },
    "histograms": {
      "analysis_task_total_ms": {
        "count": 12,
        "sum_ms": 3400,
        "min_ms": 120,
        "max_ms": 880,
        "avg_ms": 283.3,
        "p50_ms": 240,
        "p95_ms": 740,
        "p99_ms": 860,
        "buckets": {
          "100": 1,
          "500": 9,
          "1000": 12
        }
      }
    },
    "counters": {
      "external_dependency_errors_total": [
        {
          "labels": {
            "service": "ocr",
            "operation": "parallel",
            "error_type": "OCRServiceError"
          },
          "value": 3
        }
      ]
    }
  }
}
```

### GET `/metrics` - 获取 Prometheus 原始指标

说明：

- 不在 OpenAPI schema 中
- 返回 `text/plain` Prometheus exposition 格式

---

## 健康检查接口

### GET `/health` - 获取应用与依赖健康状态

响应：

```json
{
  "code": 0,
  "message": "健康检查完成",
  "data": {
    "status": "healthy",
    "timestamp": "2026-03-26T00:00:00Z",
    "version": "1.0.0",
    "services": {
      "database": "up",
      "redis": "up",
      "minio": "up",
      "yolo_model": "up",
      "chromadb": "up",
      "ollama_embedding": "up",
      "ocr_remote_api": "up"
    }
  }
}
```

状态说明：

- `healthy`：所有关键依赖可用，或外部依赖被显式禁用
- `degraded`：至少一个关键依赖为 `down`

服务状态值：

- `up`
- `down`
- `disabled`

---

## 验证错误响应示例

```json
{
  "code": 4220,
  "message": "验证码必须是 6 位数字",
  "data": {
    "errors": [
      {
        "field": "code",
        "message": "验证码必须是 6 位数字",
        "type": "string_pattern_mismatch"
      }
    ]
  }
}
```

## 常见业务错误码示例

| HTTP 状态码 | 业务错误码 | 含义 |
|------------|-----------|------|
| 401 | `40101` | 令牌无效 |
| 401 | `40102` | 令牌过期 |
| 401 | `40103` | 邮箱未验证 |
| 404 | `40401` | 资源不存在 |
| 409 | `40901` | 邮箱已注册 |
| 429 | `42901` | 请求过于频繁 |
| 500 | `5001` | 服务器内部错误 |
| 503 | `50301` | 外部服务不可用 |

