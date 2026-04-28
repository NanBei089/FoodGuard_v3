# FoodGuard

FoodGuard 是一个面向预包装食品标签场景的智能分析系统。项目通过图像识别、OCR、配料提取、营养成分解析、知识检索和大模型推理，对食品标签进行结构化分析，并生成更易理解的健康报告。

## 功能概览

- 上传食品标签图片并创建异步分析任务
- 自动识别配料表与营养成分表
- 结合用户偏好输出个性化健康评分、风险摘要和建议
- 支持历史报告查看、删除与再次追溯
- 支持报告级问答与快捷追问
- 提供账号注册、登录、偏好设置、密码修改等基础用户能力

## 仓库结构

```text
FoodGuard/
├─ food-label-analyzer/     FastAPI 后端服务
├─ food-label-frontend/     React 前端应用
├─ train_yolo26s/           YOLO26-OBB 模型训练与导出
├─ docs/                    项目深度说明文档
├─ images/                  演示与联调图片样例
├─ output/                  调试输出目录
├─ AGENTS.md                仓库协作约束
└─ README.md
```

## 技术栈

后端：

- FastAPI
- SQLAlchemy + Alembic
- PostgreSQL
- Redis + Celery
- MinIO
- ChromaDB
- YOLO / PaddleOCR / Ollama / DeepSeek

前端：

- React 19
- TypeScript
- Vite
- React Router
- Zustand
- Axios
- Tailwind CSS
- Vitest + Testing Library

## 快速启动

### 1. 后端

```powershell
conda activate foodguard-env
cd food-label-analyzer
pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -m alembic upgrade head
uvicorn app.main:app --reload
```

默认地址：

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

### 2. Celery Worker

```powershell
conda activate foodguard-env
cd food-label-analyzer
celery -A app.tasks.celery_app.celery_app worker -Q analysis --loglevel=info
```

### 3. 前端

```powershell
cd food-label-frontend
npm install
npm run dev
```

默认地址：

- Web: `http://localhost:5173`

开发环境下，Vite 会把 `/api` 代理到本地后端。

## 常用命令

后端测试：

```powershell
cd food-label-analyzer
conda run -n foodguard-env python -m pytest
```

前端测试：

```powershell
cd food-label-frontend
npm test
```

前端静态检查：

```powershell
cd food-label-frontend
npm run lint
```

前端生产构建：

```powershell
cd food-label-frontend
npm run build
```

## 文档入口

- [后端 README](food-label-analyzer/README.md)
- [前端 README](food-label-frontend/README.md)
- [后端 API 文档](food-label-analyzer/API_DOCUMENTATION.md)
- [分析链路说明](food-label-analyzer/ANALYSIS_PIPELINE.md)
- [后端深度说明](docs/backend-codebase-deep-dive.md)
- [前端深度说明](docs/frontend-codebase-deep-dive.md)

## 运行说明

- 完整分析链路依赖 PostgreSQL、Redis、MinIO、PaddleOCR 远程服务、Ollama、ChromaDB 和 DeepSeek。
- 若只做前后端页面联调，可把后端 `.env` 中的 `SKIP_STARTUP_CHECKS` 设为 `true`，避免启动时阻塞在依赖探活。
- `images/` 目录可用于本地演示与答辩准备。
