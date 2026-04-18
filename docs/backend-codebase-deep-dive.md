# FoodGuard 后端深度说明

## 1. 后端定位

FoodGuard 后端承担三类职责：

- 提供用户、报告、偏好、问答相关 HTTP API
- 调度并执行食品标签分析异步任务
- 管理与外部依赖的集成，包括对象存储、OCR、向量检索和大模型

后端主体基于 FastAPI，异步任务由 Celery 执行，最终结果落库到 PostgreSQL。

## 2. 分层结构

### API 层

`app/api/v1/` 中的路由只负责：

- 参数接收与响应序列化
- 依赖注入，如数据库会话和当前用户
- 调用服务层方法

### Service 层

`app/services/` 负责业务编排，例如：

- `auth_service.py`: 注册、登录、刷新令牌、验证码和重置密码
- `task_service.py`: 上传文件校验、任务并发控制、任务状态查询
- `report_service.py`: 报告列表、详情、产物链接组装、删除
- `report_chat_service.py`: 报告问答会话管理与流式回复

### Task / Worker 层

- `app/tasks/analysis_task.py` 是异步分析任务入口
- `app/workers/` 封装 OCR、YOLO、RAG、LLM 等外部能力

这层与 HTTP 解耦，便于后端把一次长耗时分析拆成离线任务处理。

## 3. 核心业务流

### 3.1 用户认证

认证流包括：

- 注册前邮箱验证码发送
- 注册完成后登录签发 access token 与 refresh token
- access token 过期后通过 refresh token 换新
- 主动退出时撤销 refresh token

对应模块：

- `app/api/v1/auth.py`
- `app/services/auth_service.py`
- `app/core/security.py`

### 3.2 图片上传与分析

上传分析是毕业设计中最重要的主链路：

1. 前端上传图片到 `/api/v1/analysis/upload`
2. 后端校验图片类型、大小和完整性
3. 原图写入 MinIO
4. 创建 `analysis_tasks` 记录
5. 向 Celery 队列投递 `analysis.process_image`
6. 前端轮询任务状态
7. 任务完成后生成 `reports` 记录并返回 `report_id`

### 3.3 报告查看与问答

报告详情查询会：

- 读取数据库中的结构化结果
- 为原图和中间产物生成临时访问链接
- 组织营养表、风险摘要和配料解析

报告问答则围绕单份报告建立上下文：

- 支持读取历史会话
- 支持生成快捷追问
- 支持 SSE 流式返回回答

## 4. 分析流水线说明

异步任务大致按以下顺序执行：

1. 从 MinIO 下载原图
2. 使用 YOLO 定位营养成分表区域
3. 通过 PaddleOCR 识别全文和表格内容
4. 从 OCR 文本中提取配料与营养结构
5. 使用 Ollama Embedding + ChromaDB 做知识检索
6. 把 OCR、RAG、营养信息交给 DeepSeek 生成分析结论
7. 持久化报告并更新任务状态

这一链路的代码入口主要在：

- `app/tasks/analysis_task.py`
- `app/tasks/analysis/`
- `app/workers/`

## 5. 外部依赖与失败处理

系统依赖的关键外部服务包括：

- PostgreSQL：存储用户、任务、报告与会话数据
- Redis：Celery broker / backend 以及认证冷却控制
- MinIO：原图与分析产物对象存储
- PaddleOCR：文字识别与表格解析
- Ollama：向量检索 embedding
- ChromaDB：检索配料与标准知识
- DeepSeek：最终健康分析与问答生成

代码中已对多类失败做显式处理：

- 上传失败会清理已写入的对象存储图片
- 外部依赖错误会记录指标并支持有限重试
- 分析任务失败后会把任务标记为 `failed`
- 启动阶段提供健康检查与依赖探活

## 6. 可观测性与工程质量

后端内置了三类可观测能力：

- `/health`：整体探活
- `/metrics`：Prometheus 指标
- `/api/v1/metrics`：认证后的进程内指标快照

测试方面，仓库内已覆盖：

- 配置校验
- 核心模块与基础设施模块
- 认证与用户偏好
- 分析任务相关接口
- 报告与报告问答

## 7. 答辩时可重点说明的点

- 为什么上传分析要用 Celery，而不是同步请求：避免前端阻塞、便于失败重试、适合长耗时链路
- 为什么报告详情要使用临时访问链接：避免对象存储资源直接裸露
- 为什么问答按单报告建会话：保证回答围绕当前食品标签，不和其他报告串上下文
- 为什么前后端都做了状态兜底：外部 OCR / LLM 服务不稳定时，用户仍能得到明确任务状态与错误反馈
