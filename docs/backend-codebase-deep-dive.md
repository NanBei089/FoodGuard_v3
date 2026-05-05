# FoodGuard 后端深度说明

## 1. 后端定位

FoodGuard 后端承担三类职责：

- 提供用户、偏好、分析任务、报告、报告问答相关 HTTP API
- 调度并执行食品标签分析异步任务
- 集成对象存储、OCR、向量检索和大模型等外部能力

后端主体基于 FastAPI，长耗时分析链路通过 Celery 异步执行，最终结果落库到 PostgreSQL。

## 2. 分层结构

### API 层

目录：`app/api/v1/`

职责：

- 接收 HTTP 请求
- 做依赖注入
- 返回统一响应包
- 调用服务层，不直接编写业务逻辑

### Service 层

目录：`app/services/`

职责：

- 编排业务流程
- 组织数据库读写
- 拼装接口响应结构

典型模块：

- `auth_service.py`：注册、登录、刷新令牌、退出登录、找回密码
- `task_service.py`：上传校验、任务并发控制、状态查询
- `report_service.py`：报告列表、详情、产物链接解析、删除
- `report_chat_service.py`：报告问答会话、快捷提问、SSE 流式回答

### Task / Worker 层

目录：

- `app/tasks/`
- `app/workers/`

职责：

- 执行完整分析流水线
- 封装 OCR、YOLO、RAG、LLM 等外部能力
- 将 HTTP 请求和长耗时任务解耦

## 3. 核心业务流

### 3.1 用户认证

核心能力：

- 注册验证码发送
- 用户注册
- JWT 登录
- refresh token 刷新
- 主动登出撤销 refresh token
- 忘记密码与重置密码

相关模块：

- `app/api/v1/auth.py`
- `app/services/auth_service.py`
- `app/core/security.py`

### 3.2 图片上传与分析

这是系统主链路：

1. 前端上传食品标签图片
2. 后端校验文件并写入 MinIO
3. 创建 `analysis_tasks`
4. 投递 `analysis.process_image` Celery 任务
5. 前端轮询任务状态
6. 任务完成后生成 `reports`
7. 前端跳转到报告详情页

### 3.3 报告查看与问答

报告详情接口会：

- 读取结构化分析结果
- 解析原图与中间产物的临时访问链接
- 组织营养表、配料风险、建议和检索摘要

报告问答接口会：

- 按 `report_id` 绑定单报告会话
- 支持读取已有消息
- 支持生成快捷提问
- 通过 SSE 流式返回回答

## 4. 分析流水线说明

当前异步分析流程为：

1. 从 MinIO 下载原图
2. 使用 YOLO 定位营养成分表区域
3. 根据是否检测到区域，选择双路 OCR 或整图 OCR
4. 提取配料和营养结构
5. 用 Ollama Embedding + ChromaDB 做知识检索
6. 把 OCR、RAG、营养结果交给 DeepSeek 生成分析结论
7. 用规则评分器重新计算最终健康分
8. 保存中间产物并写入报告

关键入口：

- `app/tasks/analysis_task.py`
- `app/tasks/analysis/`
- `app/workers/`

## 5. 评分策略

系统不是直接使用 LLM 返回的分数，而是采用“LLM 解释 + 规则评分兜底”的方式。

当前规则评分器主要考虑：

- 营养均衡
- 钠含量
- 糖含量
- 添加剂风险
- 过敏原风险

这样做的好处：

- 分数波动更小
- 结果更容易解释
- 更适合论文和答辩中说明评分依据

相关模块：

- `app/services/score_calculator.py`

## 6. 数据持久化

后端当前把主业务实体和半结构化分析结果分开处理。

结构化主实体：

- `users`
- `analysis_tasks`
- `reports`
- `user_preferences`
- `refresh_tokens`
- `report_conversations`
- `report_conversation_messages`

半结构化字段主要集中在 `reports` 表：

- `nutrition_json`
- `rag_results_json`
- `llm_output_json`
- `artifact_urls`

这样做的目的：

- 主业务关系保持清晰
- AI 中间结果保留足够灵活性
- 避免为高度不稳定的中间输出过早拆过细表

## 7. 外部依赖与失败处理

关键依赖包括：

- PostgreSQL：用户、任务、报告、会话数据
- Redis：Celery broker / result backend 与认证冷却控制
- MinIO：原图和分析产物对象存储
- PaddleOCR：文字识别和表格识别
- Ollama：Embedding
- ChromaDB：配料和标准知识检索
- DeepSeek：最终分析与问答生成

当前代码中的处理策略：

- 上传失败时清理已写入对象
- OCR / LLM / Embedding / Storage 错误支持有限重试
- 超时或不可恢复异常会把任务显式标记为 `failed`
- 启动阶段支持依赖探活，也允许通过配置跳过探活

## 8. 可观测性与工程质量

后端提供三类观测接口：

- `/health`：整体健康状态
- `/metrics`：Prometheus 原始指标
- `/api/v1/metrics`：认证后的进程内聚合指标快照

当前监控重点：

- 分析任务总耗时
- 各步骤耗时
- 外部依赖错误计数

测试覆盖重点包括：

- 配置校验
- 核心模块和基础设施模块
- 认证与偏好
- 分析任务接口与主流程
- 报告详情
- 报告问答

## 9. 答辩时适合重点说明的点

1. 为什么上传分析采用 Celery 异步任务
2. 为什么用 YOLO 先定位营养表，再做 OCR
3. 为什么报告分数要用规则评分兜底，而不是直接采用 LLM 输出
4. 为什么报告详情既返回结构化结果，也返回产物链接
5. 为什么报告问答按单报告建会话，而不是全局聊天

