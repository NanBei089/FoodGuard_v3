# FoodGuard Frontend

`food-label-frontend` 是 FoodGuard 的 Web 前端，负责账号登录注册、图片上传、分析进度展示、报告浏览、报告问答和个人资料管理。

## 页面与功能

- 登录 / 注册
- 首页上传与图片预览
- 分析中页面与任务轮询
- 历史报告列表、搜索、删除
- 报告详情、配料解析、营养表、健康建议
- 报告问答面板与流式回复
- 个人资料、偏好配置、密码修改、退出登录

## 技术栈

- React 19
- TypeScript
- Vite
- React Router
- Zustand
- Axios
- Tailwind CSS
- Vitest + Testing Library

## 本地开发

```powershell
cd food-label-frontend
npm install
npm run dev
```

默认地址：

- `http://localhost:5173`

## 接口配置

- 默认 API 基地址为 `/api/v1`
- 开发模式下，Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`
- 若需要连到其他后端地址，可设置 `VITE_API_URL`

## 常用命令

运行测试：

```powershell
npm test
```

静态检查：

```powershell
npm run lint
```

生产构建：

```powershell
npm run build
```

## 目录说明

- `src/pages/`: 页面级组件
- `src/components/`: 通用组件、布局组件、业务组件
- `src/api/`: Axios 客户端与请求封装
- `src/store/`: Zustand 状态管理
- `src/lib/`: 鉴权、错误处理、问答流处理等辅助逻辑
- `src/types/`: 前端类型定义

## 工程说明

- 路由页面已做 `React.lazy` 懒加载，报告详情页会按需加载 markdown 渲染与问答面板逻辑。
- Axios 统一处理 JWT 注入与 401 刷新。
- 手动退出登录会显式调用后端 `/auth/logout`，同时保证本地状态一定被清理。
- 历史记录删除后会重新拉取当前页列表，以服务端返回的分页信息为准。

## 相关文档

- [项目根目录说明](../README.md)
- [后端 README](../food-label-analyzer/README.md)
- [前端深度说明](../docs/frontend-codebase-deep-dive.md)
