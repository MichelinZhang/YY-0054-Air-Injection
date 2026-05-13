# YY-0054 功能清单（模块、接口、数据流、运行模式）

## 1. 文档目标与边界
- 目标：罗列当前系统已实现功能，作为 IEC 62304/ISO 14971/ISO 13485 差距评估输入。
- 边界：仅基于当前仓库代码与测试结论，不假设未实现能力。
- 代码范围：`backend`、`frontend`、`Python/MvImport`、`scripts`、运行时 `data/results`。

## 2. 系统分层与职责

### 2.1 表现层（Frontend）
- 应用壳层：`frontend/src/App.jsx`
  - 初始化健康状态、会话状态、相机列表。
  - 维护全局状态：`session`、`readings`、`lightState`、`cameraSettings`。
  - 页面导航：设备页、测量页、历史页。
- 设备页：`frontend/src/pages/DevicesPage.jsx`
  - 显示 SDK 状态与设备清单。
  - 展示自动映射预览（单相机映射 1/2/3/4，双相机映射 1/2 与 3/4）。
  - 支持 `Force Mock` 调试选项。
- 测量页：`frontend/src/pages/MeasurePage.jsx`
  - 列选择（1~4），点选上下限点，触发测量接口。
  - 灯光开关、曝光/增益调节、重测、保存结果。
  - 多相机预览与叠加点位可视化。
- 历史页：`frontend/src/pages/HistoryPage.jsx`
  - 拉取历史记录，展示记录元信息与标注图链接。
- API 封装：`frontend/src/api.js`
  - 封装 REST 请求与预览 WebSocket URL 生成。
  - 开发模式下对后端不可达提供提示文本。

### 2.2 应用层（Backend API）
- 主入口：`backend/app/main.py`
  - FastAPI 应用初始化、CORS、中间件与静态结果目录挂载。
  - 暴露健康、设备、会话、灯光、测量、相机参数、结果保存、历史查询接口。
  - 提供 `/ws/preview` WebSocket 实时预览通道。
  - 若存在 `frontend/dist`，支持 SPA 文件回退服务。

### 2.3 领域服务层（Backend Services）
- 会话与采集编排：`backend/app/services/session_manager.py`
  - 枚举相机、选择策略（auto/manual）、mock 回退策略。
  - 启停每相机采集线程，维护 `latest_frame`、FPS、灯光状态。
  - 维护列到相机映射 `column_camera_map`。
- 相机适配：`backend/app/services/camera_adapter.py`
  - 提供抽象设备接口、Mock 相机实现、海康 MVS 实机实现。
  - 实机支持枚举、打开、抓流、像素格式转换、曝光/增益读写、补光控制。
- SDK 装载：`backend/app/services/mvs_loader.py`
  - 从 `Python/MvImport` 动态导入海康 Python 封装。
- 读数算法：`backend/app/services/reading_assist_service.py`
  - ROI 校验、边缘细化、刻度线检测、点位吸附、置信度聚合。
  - 输出 `ReadingRecord`（tick/pixel 差值、点位、置信度、时间戳）。
- 灯光控制：`backend/app/services/light_controller.py`
  - 对会话中相机执行灯光开关。
- 结果持久化：`backend/app/services/result_store.py`
  - 按时间戳创建记录目录，保存 `result.json` 与标注 PNG。
  - 提供历史记录遍历读取。
- 运动控制占位：`backend/app/services/motion_controller.py`
  - 当前为占位实现，未接入主流程。

### 2.4 数据与配置层
- 数据契约：`backend/app/models.py`
  - 请求与响应模型：会话、测量、相机参数、结果保存、错误模型。
- 路径与常量：`backend/app/config.py`
  - `MVS_IMPORT_DIR`、`RESULTS_DIR`、`FRONTEND_DIST_DIR`、`DEFAULT_WS_FPS`。
- 运行数据目录：`data/results/<record_id>/`
  - 每条记录包含 `result.json` 与每相机标注图。

### 2.5 启动与运行脚本
- 开发一键启动：`scripts/start-dev.ps1`、`scripts/start-dev.bat`
  - 后端：`uv sync` 后启动 `uvicorn`。
  - 前端：必要时 `npm install` 后启动 `npm run dev`。

## 3. 对外接口清单

### 3.1 REST 接口（Backend）
- `GET /api/health`：返回服务状态与 SDK 可用性。
- `GET /api/cameras`：返回相机列表、真实相机数、SDK 状态。
- `POST /api/session/open`：打开会话并返回活动相机、列映射、是否 mock。
- `POST /api/session/close`：关闭会话并返回当前状态。
- `GET /api/session/state`：查询当前会话状态。
- `POST /api/light/{camera_id}/on|off`：切换补光状态。
- `POST /api/calibration`：已废弃，固定返回 410。
- `POST /api/measure`：输入上下限点，输出读数记录。
- `GET /api/camera/{camera_id}/settings`：查询曝光/增益与可调范围。
- `POST /api/camera/{camera_id}/settings`：更新曝光/增益。
- `POST /api/result/save`：保存本轮测量与标注图。
- `GET /api/results`：获取历史记录列表。

### 3.2 WebSocket 接口
- `/ws/preview?camera_id=<id>`
  - 周期推送 JPEG Base64 帧、时间戳、帧号、FPS相关状态、曝光/增益等。

## 4. 端到端数据流

### 4.1 典型流程 A：自动会话与预览
1. 前端调用 `/api/health`、`/api/cameras`、`/api/session/state` 完成初始化。
2. 用户在设备页触发 `/api/session/open`。
3. 后端创建会话并启动相机抓流线程，形成 `column_camera_map`。
4. 前端按相机建立 `/ws/preview`，展示实时画面与状态。

### 4.2 典型流程 B：测量与保存
1. 用户在测量页选择列并标注上/下限点。
2. 前端调用 `/api/measure`，后端基于最近帧运行读数算法。
3. 前端缓存每列 `ReadingRecord`，可重测或覆盖。
4. 用户触发 `/api/result/save`，后端写入 `result.json` 与标注图。
5. 历史页调用 `/api/results` 展示记录并可打开标注图。

## 5. 运行模式清单
- 实机模式（Real）：SDK 可用且选中真实相机，走海康采集链路。
- 自动回退模式（Auto Mock Fallback）：无真实相机时可自动使用 mock。
- 强制模拟模式（Force Mock）：忽略真实相机，直接使用 mock。
- 单相机映射：1 台相机对应列 1/2/3/4。
- 双相机映射：第 1 台对应列 1/2，第 2 台对应列 3/4。

## 6. 测试覆盖现状（功能相关）
- 后端有集成与服务测试：`backend/tests/test_api_integration.py` 等。
- 已覆盖：mock 会话流程、测量接口、结果保存、相机参数、calibration 废弃行为。
- 前端未见自动化测试脚本（以运行交互为主）。

## 7. 当前版本功能边界声明
- 系统核心为“图像预览 + 点位辅助读数 + 结果记录”，未见用户认证与权限体系。
- `calibration` 流程已下线，现行测量为 reading-assist 路径。
- `motion_controller` 尚未进入实际业务链路。
