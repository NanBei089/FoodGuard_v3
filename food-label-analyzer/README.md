# Food Label Analyzer Backend

`food-label-analyzer` 是 FoodGuard 的后端服务，负责用户认证、图片上传、分析任务调度、报告持久化、报告问答和基础监控接口。

## 当前已实现能力

- 邮箱注册、验证码、登录、刷新令牌、退出登录、找回密码、修改密码
- 用户资料与偏好管理
- 图片上传、任务排队、任务状态轮询
- 分析报告列表、详情、软删除
- 报告级问答、建议问题生成、SSE 流式回复
- 健康检查、Prometheus 指标、受保护的调试指标快照

## 技术与依赖

- Web API: FastAPI
- ORM: SQLAlchemy 2.x
- Migration: Alembic
- Database: PostgreSQL
- Queue: Redis + Celery
- Object Storage: MinIO
- OCR: PaddleOCR 远程 API
- Detection: YOLO ONNX
- Retrieval: Ollama Embedding + ChromaDB
- LLM: DeepSeek

运行前请参考 [.env.example](.env.example) 配置以下依赖：

- PostgreSQL
- Redis
- MinIO
- PaddleOCR 远程服务
- Ollama
- DeepSeek API Key

## 目录说明

- `app/api/v1/`: API 路由层，只负责 HTTP 编排
- `app/core/`: 配置、日志、安全、错误处理、指标
- `app/db/`: 数据库与 Redis 连接管理
- `app/models/`: ORM 模型
- `app/schemas/`: 请求与响应结构
- `app/services/`: 业务服务层
- `app/tasks/`: Celery 应用与异步任务入口
- `app/workers/`: OCR、YOLO、RAG、LLM 等能力适配器
- `tests/`: 后端单元测试与接口测试

## 本地启动

### 1. 安装依赖

```powershell
conda activate foodguard-env
cd food-label-analyzer
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

### 2. 初始化数据库

```powershell
python -m alembic upgrade head
```

### 3. 启动 API

```powershell
uvicorn app.main:app --reload
```

### 4. 启动 Worker

```powershell
celery -A app.tasks.celery_app.celery_app worker -Q analysis --loglevel=info
```

说明：

- Windows 环境下，Celery 已在代码中自动切换为 `solo` 模式。
- 若暂时不接入全部外部依赖，可将 `.env` 中的 `SKIP_STARTUP_CHECKS=true` 用于跳过启动探活。

## 常用命令

运行全部测试：

```powershell
conda run -n foodguard-env python -m pytest
```

聚焦基础模块测试：

```powershell
conda run -n foodguard-env python -m pytest tests/test_config.py tests/test_core_modules.py tests/test_infra_modules.py
```

## 接口与文档

- [API 文档](API_DOCUMENTATION.md)
- [分析流水线文档](ANALYSIS_PIPELINE.md)
- [项目后端深度说明](../docs/backend-codebase-deep-dive.md)

## 开发说明

- 图片上传接口会先校验文件类型和大小，再写入 MinIO，并向 Celery 投递分析任务。
- 报告详情接口会为原图和分析产物生成临时访问链接。
- 报告问答接口使用单报告上下文，支持建议问题与流式回答。
- `/health` 用于整体探活，`/metrics` 输出 Prometheus 指标，`/api/v1/metrics` 提供受保护的进程内指标快照。
