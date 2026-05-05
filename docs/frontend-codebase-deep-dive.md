# FoodGuard 前端深度说明

## 1. 前端定位

FoodGuard 前端负责把后端较复杂的分析链路转化为用户可理解的交互流程，重点解决：

- 降低食品标签分析的使用门槛
- 展示异步分析过程与最终报告
- 把个性化偏好带入报告解释
- 提供围绕单份报告的后续问答能力

## 2. 应用初始化

入口文件：

- `src/main.tsx`
- `src/App.tsx`

主要职责：

- 挂载 React 根节点
- 初始化 `QueryClientProvider`
- 配置应用路由
- 安装强制登出处理器
- 对页面级路由做 `React.lazy` 懒加载

## 3. 路由与权限控制

前端当前分为两组页面：

- `AuthLayout`：登录、注册
- `AppLayout`：首页、分析中、历史记录、报告详情、个人中心、初始化偏好

当前权限逻辑：

- 未登录：跳转 `/login`
- 已登录但未完成基础偏好：跳转 `/onboarding`
- 已完成初始化：进入主站页面

相关文件：

- `src/components/layout/AuthLayout.tsx`
- `src/components/layout/AppLayout.tsx`

## 4. 鉴权与会话管理

### 4.1 Axios 客户端

`src/api/client.ts` 负责：

- 自动附带 access token
- 统一校验 API 响应包结构
- 401 时自动尝试刷新 token
- 刷新失败后触发强制登出

### 4.2 Zustand 会话状态

`src/store/auth.ts` 负责：

- 用户信息
- 用户偏好
- 是否已登录
- 是否需要 onboarding

### 4.3 手动退出登录

`src/lib/auth-session.ts` 中的手动退出逻辑会：

- 最佳努力调用后端 `/auth/logout`
- 不论网络是否成功，都清理本地 token 和用户状态
- 最终跳回登录页

## 5. 页面主流程

### 5.1 首页上传

页面：`src/pages/Home.tsx`

能力包括：

- 选择图片或拖拽上传
- 本地预览
- 展示当前默认分析偏好
- 提交到 `/analysis/upload`

上传成功后：

- 跳转 `/analyzing/:taskId`
- 使用 `sessionStorage` 暂存分析中的图片预览

### 5.2 分析中页面

页面：`src/pages/Analyzing.tsx`

能力包括：

- 轮询 `/analysis/tasks/{taskId}`
- 根据状态估算前端进度条
- 成功后自动跳转报告页
- 多次轮询失败或超时后停止轮询并提示错误

说明：

- 前端进度条是“估算式进度”，不是后端真实步骤回传
- 设计目标是让用户感知任务仍在进行，而不是长时间空白等待

### 5.3 历史记录

页面：`src/pages/History.tsx`

当前支持：

- 分页加载报告列表
- 本地搜索当前页数据
- 删除报告

删除策略：

- 删除成功后重新请求当前页
- 以后端返回的 `page / total / items` 作为唯一真值
- 这样可以避免删除最后一条记录后的分页错位

### 5.4 报告详情

页面：`src/pages/ReportDetail.tsx`

当前展示：

- 原图
- 综合评分
- 风险摘要
- 配料风险
- 营养成分表
- 人群建议
- 报告专属问答面板

## 6. 报告问答交互

相关文件：

- `src/components/report/ReportChatPanel.tsx`
- `src/lib/report-chat.ts`
- `src/lib/report-chat-recovery.ts`

当前设计思路：

- 问答和单份报告绑定
- 首次进入报告页时读取已有会话
- 若无建议问题，按需请求后端生成
- 提问时通过 SSE 流式消费回答
- 若流式被中断，前端会尝试基于已持久化的会话消息做恢复

这一层的重点不在“通用聊天”，而在“围绕当前食品报告继续追问”。

## 7. 目录划分

前端主要目录：

- `src/pages/`：页面组件
- `src/components/layout/`：布局组件
- `src/components/report/`：报告相关组件
- `src/components/profile/`：个人中心相关组件
- `src/components/ui/`：基础 UI 组件
- `src/api/`：请求客户端
- `src/lib/`：业务辅助逻辑
- `src/store/`：状态管理
- `src/types/`：接口类型定义

这种划分方式比较适合毕业设计展示时从“页面层 -> 业务层 -> 接口层”逐步讲解。

## 8. 测试与工程验证

前端当前使用：

- Vitest
- Testing Library

重点覆盖内容：

- 上传成功后的跳转
- 分析中轮询失败与超时
- 历史记录删除后的重新拉取
- 会话恢复逻辑
- markdown 消息渲染
- 修改密码表单约束
- 手动退出登录

## 9. 答辩时适合重点说明的点

1. 为什么报告详情页和问答面板适合路由级懒加载
2. 为什么 token 刷新集中放在 Axios 拦截器
3. 为什么历史记录删除后重新请求列表，而不是只在前端本地删一条
4. 为什么问答要围绕单报告上下文，而不是做成通用聊天窗口
5. 为什么分析中页面使用估算式进度，而不是空白等待

