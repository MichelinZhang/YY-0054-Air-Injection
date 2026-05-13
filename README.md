# YY-0054 Air Injection Test System

基于 **YY 0054-2010《血液透析和相关治疗用水》** 标准的空气注入量检测辅助系统。通过海康威视工业相机采集刻度管图像，结合计算机视觉算法自动/半自动读取空气柱高度，辅助医疗器械检测人员完成合规测量与记录。

## 系统架构

```
┌──────────────┐     WebSocket/REST     ┌──────────────┐
│   Frontend   │ ◄────────────────────► │   Backend    │
│  React+Vite  │                        │   FastAPI    │
└──────────────┘                        └──────┬───────┘
                                               │
                                    ┌──────────┼──────────┐
                                    │          │          │
                              Camera SDK  CV Algorithm  Storage
                             (Hikvision MVS)  (OpenCV)  (JSON/Image)
```

## 功能特性

### 核心测量
- 多相机（最多 4 路）实时预览（WebSocket 推流）
- 半自动空气柱上下界标定（点击 + 边缘精炼）
- 自适应刻度线检测（无硬编码阈值）
- 气泡边界自动检测
- 像素→物理量标定体系（tick → mm → mL）
- 低置信度自动告警/拒绝机制

### 合规性 (IEC 62304 / ISO 14971 / ISO 13485)
- 环境隔离配置（development / production）
- 结构化错误码体系
- 审计日志（JSON Lines，按日轮转）
- Token 认证 + 角色权限控制
- Mock 模式隔离（生产环境禁止保存模拟数据）
- 数据完整性保障（SHA-256 校验、原子写入）
- 操作员身份强制（生产环境必填）

### 易用性
- Mock 模式全局醒目标识
- 保存前操作员/备注弹窗确认
- 置信度彩色等级显示 + 低置信度警告
- 物理量（mL/mm）实时换算显示
- 历史记录搜索、筛选、分页、缩略图、CSV 导出
- 全屏预览、操作向导、通知自动消失
- 响应式布局（支持不同屏幕尺寸）

## 快速开始

### 环境要求

- Python 3.12+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/) (Python 包管理)
- 海康威视 MVS SDK（可选，无 SDK 时自动进入 Mock 模式）

### 安装

```bash
# 克隆仓库
git clone https://github.com/MichelinZhang/YY-0054-Air-Injection.git
cd YY-0054-Air-Injection

# 后端
cd backend
uv sync --extra dev
cd ..

# 前端
cd frontend
npm install
cd ..
```

### 启动

**一键启动（PowerShell）：**

```powershell
.\scripts\start-dev.ps1
```

**手动启动：**

```bash
# 终端 1 - 后端
cd backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 2 - 前端
cd frontend
npm run dev
```

启动后访问：
- 前端：http://localhost:5173
- 后端 API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

## 项目结构

```
YY-0054-Air-Injection/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI 主应用
│   │   ├── config.py                # 环境配置
│   │   ├── models.py                # Pydantic 数据模型
│   │   ├── auth.py                  # 认证与授权
│   │   ├── errors.py                # 结构化错误码
│   │   ├── services/
│   │   │   ├── session_manager.py   # 会话与相机管理
│   │   │   ├── camera_adapter.py    # 相机硬件抽象层
│   │   │   ├── reading_assist_service.py  # 测量算法核心
│   │   │   ├── calibration_service.py     # 标定服务
│   │   │   ├── result_store.py      # 结果持久化
│   │   │   ├── audit_logger.py      # 审计日志
│   │   │   └── light_controller.py  # 光源控制
│   │   └── utils/
│   │       └── image_utils.py       # 图像编解码
│   ├── tests/
│   │   ├── test_api_integration.py
│   │   ├── test_p0_compliance.py
│   │   ├── test_golden_regression.py
│   │   ├── test_calibration_service.py
│   │   ├── test_measurement_service.py
│   │   └── golden_data/             # 回归测试图像基线
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── App.jsx                  # 主应用组件
│   │   ├── api.js                   # API 客户端
│   │   ├── pages/
│   │   │   ├── MeasurePage.jsx      # 测量页面
│   │   │   └── HistoryPage.jsx      # 历史记录页
│   │   ├── components/
│   │   │   ├── CameraPreview.jsx    # 相机预览（含全屏）
│   │   │   ├── ColumnCard.jsx       # 测量列卡片
│   │   │   └── AnimatedButton.jsx   # 动画按钮
│   │   └── styles.css               # 全局样式
│   ├── package.json
│   └── vite.config.js
├── scripts/
│   └── start-dev.ps1                # 一键启动脚本
├── docs/
│   └── medical-compliance/          # 合规文档
├── Python/MvImport/                 # 海康 MVS SDK 封装
└── README.md
```

## 测试

```bash
cd backend

# 运行全部测试
uv run pytest tests/ -v

# 仅回归测试
uv run pytest tests/test_golden_regression.py -v

# 合规性测试
uv run pytest tests/test_p0_compliance.py -v
```

### 添加回归测试用例

1. 将真实相机图像放入 `backend/tests/golden_data/`
2. 创建同名 `.json` 文件定义期望值（格式见 `golden_data/README.md`）
3. 运行 `uv run pytest tests/test_golden_regression.py -v`

## 标定流程

系统支持通过已知参考物进行标定：

```bash
# 通过 API 进行标定（需要 ENGINEER 角色）
curl -X POST http://localhost:8000/api/calibration/from-reference \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"known_tick_count": 10, "known_length_mm": 10.0}'
```

或通过 `GET /api/calibration` 查看当前标定参数。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_ENV` | `development` | 运行环境 (`development` / `production`) |
| `AUTH_ENABLED` | `false` | 是否启用认证 |
| `AUTH_SECRET_KEY` | (内置) | Token 签名密钥 |
| `CORS_ALLOWED_ORIGINS` | `*` | 允许的跨域源 |
| `RESULTS_DIR` | `data/results` | 结果存储目录 |
| `AUDIT_LOG_DIR` | `data/audit_logs` | 审计日志目录 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + Vite + Framer Motion |
| 后端 | Python 3.12 + FastAPI + Uvicorn |
| 图像处理 | OpenCV + NumPy |
| 相机 SDK | 海康威视 MVS (MvCameraControl) |
| 包管理 | uv (Python) / npm (Node.js) |

## 合规文档

详见 `docs/medical-compliance/` 目录：
- `01-functional-inventory.md` — 功能清单
- `02-gap-matrix-iec62304-iso14971-iso13485.md` — 合规差距矩阵
- `03-phased-roadmap-p0-p1-p2.md` — 分阶段改进路线图

## License

MIT
