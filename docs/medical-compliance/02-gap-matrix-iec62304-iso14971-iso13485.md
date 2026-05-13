# YY-0054 合规差距矩阵（IEC 62304 / ISO 14971 / ISO 13485）

## 1. 使用说明
- 目的：识别当前实现与医疗器械软件工程常见要求的差距，并给出优先级改进方向。
- 分级规则：
  - `高`：可能直接影响安全性、正确性、可追溯性或监管审评可接受性。
  - `中`：影响质量体系完整性、发布可控性或验证充分性。
  - `低`：影响效率或文档一致性，但短期内不直接构成高风险。
- 本矩阵基于仓库现状，不替代正式法规符合性审计。

## 2. IEC 62304（软件生命周期）差距

### 62304-GAP-01（高）
- 现状：
  - 未见软件开发计划、架构设计说明、单元/集成/系统验证计划与记录的受控工件。
  - 代码层仅有局部测试：`backend/tests/*`。
- 证据：
  - `backend/tests/test_api_integration.py`
  - `backend/README.md`（仅运行说明）
- 风险：
  - 生命周期活动不可证明，软件安全分类与验证深度无法追溯。
- 建议：
  - 建立最小生命周期文档集合：SDP、SRS、SAD、SVP/SVR、问题管理、变更影响评估。

### 62304-GAP-02（高）
- 现状：
  - 需求-风险-测试未形成双向追溯；模型字段和算法参数缺少需求编号映射。
- 证据：
  - `backend/app/models.py`
  - `backend/app/services/reading_assist_service.py`
- 风险：
  - 变更后难以证明每一条需求已被验证且风险控制有效。
- 建议：
  - 建立 RTM（Requirements Traceability Matrix），将需求、风险控制、测试用例、代码提交关联。

### 62304-GAP-03（高）
- 现状：
  - 错误处理策略不统一，多个接口直接回传 `detail=str(exc)`。
- 证据：
  - `backend/app/main.py` 中 `open_session`、`light_on/off`、`camera settings` 等接口。
- 风险：
  - 运行故障不可控且可能泄露内部实现细节，影响安全与可维护性。
- 建议：
  - 建立统一错误码规范与异常分层（用户可见错误/内部诊断错误分离）。

### 62304-GAP-04（中）
- 现状：
  - `motion_controller` 为占位模块，未定义其生命周期状态与后续验证入口。
- 证据：
  - `backend/app/services/motion_controller.py`
- 风险：
  - 模块边界不清，后续引入功能时容易绕过既定验证流程。
- 建议：
  - 在架构文档中标注为“预留、未启用”，并建立启用门禁条件。

## 3. ISO 14971（风险管理）差距

### 14971-GAP-01（高）
- 现状：
  - 支持 `force_mock` 与自动 mock 回退，且可进入完整测量与保存流程。
- 证据：
  - `backend/app/models.py`（`force_mock`、`use_mock_when_unavailable`）
  - `backend/app/services/session_manager.py`
  - `frontend/src/pages/DevicesPage.jsx`
- 风险：
  - 真实设备缺失时仍可产生“看似有效”的结果，存在临床误用风险。
- 建议：
  - 生产模式默认禁用 mock；仅授权调试角色可启用并强制审计记录。

### 14971-GAP-02（高）
- 现状：
  - 读数输出以 `tick_delta`、`pixel_delta` 为主，缺少物理量换算、误差界限与适用声明。
- 证据：
  - `backend/app/models.py`（`ReadingRecord`）
  - `backend/app/services/reading_assist_service.py`
- 风险：
  - 指标语义与临床判定边界不清，可能导致错误解释和错误决策。
- 建议：
  - 建立“测量语义规范”：单位、换算、不确定度、适用条件、失效条件。

### 14971-GAP-03（高）
- 现状：
  - 保存结果时若某 `camera_id` 无最新帧会被跳过，流程不报错。
- 证据：
  - `backend/app/services/result_store.py`（`if frame is None: continue`）
- 风险：
  - 图像证据与测量记录不一致，数据完整性受损。
- 建议：
  - 保存前完整性校验（测量记录-相机帧一致性），失败返回明确错误并拒绝入库。

### 14971-GAP-04（中）
- 现状：
  - 关键算法参数为经验阈值，未绑定风险控制验证数据集与漂移监控。
- 证据：
  - `backend/app/services/reading_assist_service.py`（阈值与置信度逻辑）
- 风险：
  - 算法性能可能随图像条件变化漂移，且无法持续证明风险可接受。
- 建议：
  - 引入受控数据集、阈值基线、回归统计报告与发布阻断门槛。

## 4. ISO 13485（质量管理体系）差距

### 13485-GAP-01（高）
- 现状：
  - 缺乏可审计的系统日志与事件追踪机制。
- 证据：
  - `backend/app/main.py`、`backend/app/services/*` 中未形成结构化审计日志输出。
- 风险：
  - 问题追溯、CAPA、投诉调查与现场复盘困难。
- 建议：
  - 建立审计日志策略（会话启停、模式切换、测量、保存、参数变更、异常）。

### 13485-GAP-02（高）
- 现状：
  - 访问控制缺失：API 与 WebSocket 无认证授权，且 CORS 全开。
- 证据：
  - `backend/app/main.py`（`allow_origins=["*"]`）
- 风险：
  - 未授权访问与误操作风险显著，不符合受控医疗环境预期。
- 建议：
  - 引入认证鉴权与角色权限模型，按环境收紧 CORS。

### 13485-GAP-03（中）
- 现状：
  - 结果文件直接写盘，缺少原子写、完整性校验与损坏告警机制。
- 证据：
  - `backend/app/services/result_store.py`（`write_text` 直接落盘）
- 风险：
  - 异常中断时可能形成损坏记录，影响记录可靠性。
- 建议：
  - 使用临时文件+替换的原子写策略；引入校验摘要与损坏检测。

### 13485-GAP-04（中）
- 现状：
  - SOUP 管理证据不足（海康 SDK 与运行环境依赖缺少受控清单与已知问题处理策略）。
- 证据：
  - `Python/MvImport/`
  - `backend/app/services/mvs_loader.py`
  - `backend/pyproject.toml`、`backend/uv.lock`
- 风险：
  - 第三方组件变更影响难评估，版本漂移导致验证失效。
- 建议：
  - 建立 SOUP 台账：版本、来源、已知缺陷、验证证据、升级审批流程。

## 5. 横向问题（跨标准）

### X-GAP-01（高）
- 现状：
  - `operator`/`note` 在前端保存时固定为 `null`，记录元信息不完整。
- 证据：
  - `frontend/src/App.jsx`（`saveResult` 入参）
- 风险：
  - 电子记录审计价值不足，难以支持责任追溯。
- 建议：
  - 在 UI 强制采集操作员身份与必要上下文，后端校验非空策略（按角色/场景）。

### X-GAP-02（中）
- 现状：
  - 文档与实现存在不一致，README 仍提及 calibration。
- 证据：
  - `backend/README.md`
  - `backend/app/main.py`（`/api/calibration` 返回 410）
- 风险：
  - 用户认知偏差、测试与运维误配置。
- 建议：
  - 建立“文档一致性检查”作为发布门禁之一。

## 6. 优先级汇总（实施顺序建议）
- 第一优先（立即）：访问控制、mock 生产隔离、数据完整性校验、错误码规范、审计日志。
- 第二优先（短期）：追溯矩阵、SOUP 台账、算法回归基线、文档一致性治理。
- 第三优先（中期）：生命周期全套文档闭环与发布过程质量指标化。
