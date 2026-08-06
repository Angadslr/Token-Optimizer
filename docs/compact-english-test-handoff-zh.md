# 给 Cursor Agent 的紧凑英文路由技术测试交接

## 零、给执行代理的任务指令

你正在 SlashToken 仓库中执行一次范围严格受限的验证任务。请先完整阅读本文件，再开始检查代码或运行命令。不要把下面五个产品需求当成要实现的产品；它们只是用于验证“长篇中文开发提示词转换为紧凑英文提示词”的合成测试输入。每个输入都明确假设另一个完全空白的代码库，以模拟开发者真实地要求 Cursor 从零规划新产品的场景。

你的职责如下：

1. 阅读 `README.md`、`PROJECT_OBJECTIVE.md`、仓库根目录的 `AGENTS.md`、`docs/codex-setup.md`，以及与优化链路直接相关的源代码和测试。
2. 检查当前工作树，保留所有现有改动；不得重置、覆盖、清理或提交不属于本任务的文件。
3. 先运行不消耗 NVIDIA API 额度的确定性测试，确认当前基线。
4. 在得到已配置的 `NVIDIA_API_KEY` 后，使用本文的五个中文输入逐一运行真实 NVIDIA 优化测试。
5. 每个真实测试必须经过 GUI 使用的同一个 `POST /api/optimize` 路径。不得绕过 API 直接调用转换器，也不得调用 Codex 或目标模型生成答案。
6. 验证候选是否为完整、紧凑、可执行的英文提示词，并且仍以英文要求最终开发代理使用简体中文回答。
7. 检查受保护内容、语言检测、语义验证、Token 经济性、阶段用量、延迟、回退原因和协议错误。
8. 把结果写入一个新的中文 Markdown 报告。报告必须包含可复现命令、逐案例结果、失败证据和明确结论。
9. 除非任务发起人另行授权，不要修改生产代码来掩盖失败，也不要批准或提交任何候选提示词。如果发现缺陷，先报告最小复现、根因位置和建议修复，不要把失败测试改成通过。

执行完成的定义：确定性测试结果已记录，五个真实案例都已到达终态，每个断言都有证据，报告不含密钥或私人内容，并能明确回答当前“无限转换输出上限”是否解决长输入的 `ProviderProtocolError`。

## 一、测试目标

本交接用于指导 Cursor Agent 验证 SlashToken 在真实、长篇、中文开发提示词上的完整输入优化链路：

```text
中文开发提示词
  -> DeepSeek 提示词转换
  -> 本地英文检测
  -> 受保护内容恢复
  -> 目标模型分词统计
  -> DeepSeek 语义验证
  -> 可审批的紧凑英文候选
```

五个合成测试任务都假设其目标目录是一个完全空白的代码库，后续开发代理需要从零规划产品和技术实现。Cursor Agent 本次只验证提示词转换与路由决策，不批准候选，不启动 Codex，不创建这些产品的项目文件，也不执行提示词要求的实际开发工作。

本轮需要回答以下问题：

1. 超长中文提示词是否仍会触发 `ProviderProtocolError`。
2. DeepSeek 是否返回完整的英文提示词，而不是中文改写或任务答案。
3. 本地检测器是否把候选可靠识别为 `en`。
4. 名称、数字、URL、代码标识符、JSON 字段和明确约束是否完整保留。
5. 候选是否仍然要求后续模型用简体中文回答。
6. 英文候选是否减少目标模型输入 Token。
7. 转换与验证开销是否明显高于目标输入节省。

## 二、测试前准备

在新的终端中进入 SlashToken 仓库并激活虚拟环境：

```bash
cd "/Users/angadsrivastava/Documents/Token Optimizer"
source .venv/bin/activate
```

确认 `NVIDIA_API_KEY` 已设置，但不要打印密钥值：

```bash
test -n "$NVIDIA_API_KEY" && echo "NVIDIA_API_KEY 已设置"
```

先记录工作树状态并运行确定性基线：

```bash
git status --short
python -m pytest -q
```

普通测试不得设置 `SLASHTOKEN_RUN_LIVE_TESTS=1`，因此不会消耗 NVIDIA API 额度。如果基线失败，先区分既有失败与本任务相关失败，并在报告中保留完整命令、失败测试名称和异常摘要；不要为了继续真实测试而删除或弱化断言。

关闭 SlashToken 自身的转换输出上限：

```bash
export SLASHTOKEN_TRANSFORMATION_MAX_TOKENS=0
```

启动一个全新的 GUI 进程。不要复用修改前已经运行的服务器：

```bash
slashtoken ui --host 127.0.0.1 --port 8765
```

为每个测试创建独立空目录。目录中不得包含现有代码、配置或 Git 历史：

```bash
mkdir -p /tmp/slashtoken-empty-tests/case-01
mkdir -p /tmp/slashtoken-empty-tests/case-02
mkdir -p /tmp/slashtoken-empty-tests/case-03
mkdir -p /tmp/slashtoken-empty-tests/case-04
mkdir -p /tmp/slashtoken-empty-tests/case-05
```

## 三、真实测试的执行方式

优先采用可重复的自动化方式：使用 `fastapi.testclient.TestClient`、`build_runtime` 和 `create_app`，对每个案例向 `POST /api/optimize` 发送以下字段；这与 GUI 使用的是同一条应用路由：

```json
{
  "prompt": "对应案例的完整中文提示词",
  "target_model": "gpt-4o",
  "project_path": "对应的空目录绝对路径",
  "workload_mode": "agentic_coding"
}
```

自动化运行必须满足以下约束：

- 只有显式设置 `SLASHTOKEN_RUN_LIVE_TESTS=1` 时才允许发起真实 NVIDIA 请求。
- 每个案例使用独立的临时 SQLite 数据库，避免历史决策污染结果。
- 在请求进程中设置 `SLASHTOKEN_TRANSFORMATION_MAX_TOKENS=0`，并确认运行时解析结果确实为无限制。
- 设置合理的单案例超时，但不要通过重新引入固定输出 Token 上限来避免等待。
- 仅调用 `/api/optimize`；不得调用 `/api/chat`、候选审批接口、Codex App Server 或目标模型回答接口。
- 响应可以写入本地测试报告，但不得记录请求头、环境变量、密钥或供应商原始调试载荷。
- 如果需要新增可复用的实时集成测试，必须放在 `tests/integration/`，并使用与现有 `test_live_nvidia_translation.py` 相同的显式额度开关。普通 `python -m pytest -q` 必须继续跳过它。

在自动化结果之外，至少选取一个最长案例从 GUI 再执行一次，用于确认用户实际路径显示的状态、语言评估、Token 数和候选审批禁用行为与 API 结果一致。GUI 验证同样不得批准或提交候选。

## 四、单个案例的执行步骤

对下面每个提示词分别执行一次：

1. 使用相同的 `target_model`，整个测试期间不要切换模型。
2. 把 `project_path` 设置为对应的空目录。
3. 确认当前有效设置中的语言优化已开启，自动提交已关闭。
4. 把完整提示词原样放入请求，不要手工删减、翻译或修改。
5. 调用一次 `POST /api/optimize`，等待决策进入终态；协议失败后不要自动重试，以免掩盖首次结果。
6. 不要调用任何候选审批、原文提交或 Codex 执行接口。
7. 保存隐私安全的决策回执、语言检测、Token、耗时和阶段用量。
8. 按本节后面的通过标准执行自动断言。
9. 人工检查完整英文候选是否仍然是给后续开发模型的任务提示词，而不是已经完成的技术方案。
10. 对选定的 GUI 复核案例，再确认界面展示与 API 响应一致，但仍不得点击 `approve(candidate)` 或 `submit(original)`。

如果任一测试失败，保留截图，并记录测试编号、时间、状态、回退原因和安全错误类别。不得把 API 密钥、完整上游响应或私人数据写入报告。

## 五、通过标准

每个测试必须同时满足以下条件才算通过：

- `status` 为 `candidate`。
- `candidate_language.detected_language` 为 `en`。
- `candidate_language.reliable` 为 `true`。
- 候选主体是英文；只有明确受保护的中文引文可以保留中文。
- 候选中没有任何 `__STP_` 内部占位符。
- 所有要求保留的标识符、金额、日期、URL、代码名称和 JSON 字段均逐字存在。
- `verification.valid` 为 `true`。
- `verification.is_prompt_not_answer` 为 `true`。
- `verification.preserves_requirements` 为 `true`。
- `candidate_tokens.tokens` 小于 `original_tokens.tokens`。
- `token_savings` 大于 `0`。
- 候选用英文表达“最终回答必须使用简体中文”的要求。
- 没有任何提示词被提交给 Codex。

以下结果必须判定为失败：

- `ProviderProtocolError`。
- `wrong_candidate_language`。
- `protected_span_mismatch`。
- `verification_failed`。
- 候选是中文压缩版本。
- 候选直接给出了架构方案、数据库设计或实施计划。
- 候选 JSON 被截断。
- 候选遗漏关键业务规则或把强制要求弱化为建议。
- 候选可以审批，但实际包含错误语言或未恢复的占位符。

注意：`provider_unavailable` 属于托管服务临时不可用，不是长度限制拒绝。此时决策会
回退到原始提示词供审批，回执会记录失败阶段和安全原因（例如 `HTTP 529` 或
`timeout_or_connection`）。如果 `stage_usage` 为空，说明第一个托管调用（提示词转换）
在生成任何候选之前就失败了。对超长中文提示词，可提高
`SLASHTOKEN_PROVIDER_TIMEOUT_SECONDS` 后重试；若返回 429/529，则为上游容量问题，
应稍后重试，而非 SlashToken 因长度拒绝。

注意：`protected_span_mismatch` 表示 SlashToken 已经收到转换结果，但本地校验发现受保护
占位符（`__STP_...__`）被改写、重复、重排或丢失。这是有意的意图保护，不是 NVIDIA HTTP
客户端故障。测试时的处理方式：

- 直接审批并提交原始中文提示词——拒绝本身就意味着候选不可信，Codex 仍可在原文上运行。
- 转换前会自动重试一次；若两次都失败，回执会附带隐私安全的计数（例如
  `expected 164, missing 3, reordered; inline_code missing 2`），可据此判断是哪类占位符
  出问题。
- 占位符过多是主要诱因。当受保护跨度超过 `SLASHTOKEN_PROTECTED_SPAN_SOFT_LIMIT`
  （默认 40）时，SlashToken 会自动放弃保护低价值的短引用与反引号内联标识符，只保留金额、
  ID、URL、邮箱和代码块。测试超长提示词时可减少反引号、引号与内联 JSON，或先用较短的
  中文提示词验证链路。

## 六、测试记录模板

每个案例复制并填写一次：

```text
测试编号：
执行时间：
目标模型：
空目录：
状态：
回退原因：
检测语言：
语言置信度：
检测器：
原始 Token：
候选 Token：
节省 Token：
节省比例：
转换输入 Token：
转换输出 Token：
验证输入 Token：
验证输出 Token：
转换耗时：
验证耗时：
受保护内容是否完整：
候选是否仍为提示词：
是否要求用简体中文回答：
是否出现中文主体：
是否出现 __STP_：
人工结论：通过 / 失败
备注：
```

完成全部案例后，汇总：

- 通过率。
- 错误语言率。
- 协议失败率。
- 受保护内容失败率。
- 语义验证失败率。
- 平均和中位 Token 节省。
- 转换与验证的总 Token 开销。
- 平均和最大端到端优化耗时。
- 是否存在输入 Token 减少但端到端成本增加的案例。

## 七、案例 01：Beaverton 本地多商户电商平台

```text
你是一名资深产品架构师和全栈工程负责人。当前目录是一个完全空白的代码库，没有 package.json、README、框架、数据库、环境变量文件或现有架构。请只制定实施计划，不要创建文件、安装依赖、运行命令或声称已经完成任何代码。

请为美国俄勒冈州 Beaverton 及周边社区从零规划一个名为「Cedar & Pine Market」的本地多商户电商平台，项目代号必须保持为 BEA-ECOM-2026。首批服务邮编为 97005、97006、97007、97008 和 97225，后续可能扩展到 Hillsboro、Tigard、Aloha 和 Portland 西区。平台需要支持本地配送、到店自取和普通邮寄，但第一阶段不允许跨境销售，也不允许酒类、烟草、药品、武器或其他受限制商品。

消费者需要能够浏览附近商家、按距离和配送时间筛选、查看商品变体、加入购物车、使用优惠码、选择配送或取货时段、访客结账、使用信用卡、Apple Pay 或 Google Pay 付款，并查看订单历史。商家需要管理资料、商品、SKU、库存、价格、图片、营业时间、配送区域、取货窗口和订单。平台运营人员需要审核商家、下架商品、处理退款争议、冻结异常账户并查看审计记录。

必须明确决定 MVP 是否允许多商家统一结账。如果建议第一阶段每次只结算一个商家，需要说明用户体验影响、数据库设计影响、Stripe Connect 影响以及未来迁移到统一结账的步骤。所有金额使用整数最小货币单位，例如 `$24.99` 存储为 `2499`，货币代码必须是 `USD`。所有数据库时间使用 UTC，界面使用 `America/Los_Angeles` 并正确处理夏令时。税费不得硬编码，需要规划可替换的税务服务，并在上线前验证 Beaverton、Washington County、Oregon 和跨州邮寄的现行规则。

优先评估 Next.js、React、TypeScript、Tailwind CSS、PostgreSQL、Prisma 或 Drizzle、Clerk 或 Auth.js、Stripe、Stripe Connect、S3 兼容对象存储、Postmark 或 Resend、PostHog 和 Vercel。不要默认这些技术一定正确；必须给出明确选择、理由、主要替代方案和迁移成本。架构优先采用模块化单体，领域至少包括 `identity`、`catalog`、`merchant`、`inventory`、`cart`、`checkout`、`orders`、`payments`、`fulfillment`、`promotions`、`notifications`、`admin`、`analytics` 和 `audit`。

数据模型至少覆盖 `users`、`addresses`、`merchants`、`merchant_members`、`stores`、`products`、`product_variants`、`inventory_items`、`inventory_reservations`、`carts`、`cart_items`、`orders`、`order_items`、`payments`、`refunds`、`delivery_zones`、`pickup_windows`、`promotion_codes`、`promotion_redemptions`、`webhook_events` 和 `audit_logs`。解释价格快照、库存预留过期、订单状态与支付状态分离、跨商家数据隔离、软删除、唯一约束和索引。

支付成功后才能把订单标记为 `paid`。Stripe Webhook 必须验证签名，并通过 `provider_event_id` 幂等处理。发生“支付成功但订单更新失败”时必须有恢复流程。客户端不得决定最终价格、税费、折扣、配送费或订单总额。运营人员手工调整订单必须记录 `actor_id`、`reason`、`before_state`、`after_state` 和 `created_at`。统一错误结构必须保留以下字段：

{
  "error": {
    "code": "INVENTORY_UNAVAILABLE",
    "message": "One or more items are no longer available.",
    "request_id": "req_01JBEAVERTON2026"
  }
}

请给出 P0、P1、P2 功能矩阵、系统边界、数据流、数据库设计、API 分组、权限模型、威胁模型、测试金字塔、部署方案、可观察性、分阶段路线图、风险登记表、上线门槛和回滚方案。初始团队为 1 名高级全栈工程师、1 名中级前端工程师、1 名兼职设计师和 1 名兼职产品运营负责人，没有专职 DevOps 和 QA。基础设施预算目标低于每月 `$750`，不包括支付手续费和配送订单费用。首轮试点招募 5–10 家商家，每家至少 10 个商品，邀请 50–100 名消费者，持续 4 周。

最终回答必须使用简体中文。不要输出泛泛的电商功能清单。对每个关键决策必须包含推荐方案、理由、被拒绝的主要替代方案、权衡、失败模式和验证方法。
```

## 八、案例 02：建筑承包商现场服务 SaaS

```text
你是一名 Principal Software Engineer 和 B2B SaaS 产品负责人。当前目录完全为空，没有任何代码、依赖、配置、数据库或云资源。请为一个从零开始的现场服务管理平台制定技术实施计划，不要创建代码，不要安装软件，不要执行命令。

产品名为「Northwest FieldOps」，项目标识为 NWF-OPS-2026。目标客户是 Portland、Beaverton、Hillsboro 和 Vancouver 地区拥有 5–75 名员工的电气、暖通、管道和一般建筑承包商。平台需要管理客户、施工地点、报价、工单、调度、技术人员、现场照片、材料、签字、发票和付款。首个版本必须支持 Web 和响应式移动界面，不开发原生移动应用，但技术人员在网络不稳定的施工现场仍然需要查看当天工单、记录工时、填写检查表并暂存照片。

租户之间必须严格隔离。用户角色至少包括 `owner`、`dispatcher`、`technician`、`bookkeeper` 和 `viewer`。所有服务端查询都必须绑定 `tenant_id`，不能只依赖前端过滤。敏感操作需要审计。管理员模拟登录租户账户必须显示明显提示，并记录 `actor_id`、`impersonated_tenant_id`、`reason`、`started_at` 和 `ended_at`。

工单编号格式为 WO-YYYY-000001。报价接受后可以生成工单，但不得静默覆盖原报价。工时记录必须保存开始、暂停、恢复和结束事件，不能只保存一个总时长。照片上传需要处理 HEIC、JPEG 和 PNG，单文件原始大小上限为 25 MB。离线数据重新连接后必须有冲突解决策略，禁止使用简单的“最后写入者覆盖一切”。客户签字、检查清单和现场备注需要形成不可篡改的工单完成快照。

请比较 Next.js 模块化单体与独立 API 服务，PostgreSQL 与 SQLite 同步方案，Prisma 与 Drizzle，Clerk 与 Auth.js，S3 与 Cloudflare R2，Stripe Invoicing 与自建发票模型。第一阶段不需要复杂会计系统，但必须为未来 QuickBooks Online 集成预留适配器边界。不要承诺与任何第三方平台的功能完全兼容。

核心实体至少包括 `tenants`、`users`、`tenant_memberships`、`customers`、`service_locations`、`estimates`、`estimate_items`、`work_orders`、`work_order_events`、`technician_assignments`、`time_entries`、`materials`、`attachments`、`checklists`、`signatures`、`invoices`、`payments`、`webhook_events`、`sync_operations` 和 `audit_logs`。说明唯一约束、索引、状态机、软删除、附件生命周期和数据保留。

需要规划以下 API：`POST /api/estimates`、`POST /api/estimates/{estimate_id}/accept`、`POST /api/work-orders`、`PATCH /api/work-orders/{work_order_id}/status`、`POST /api/time-entries/start`、`POST /api/time-entries/{entry_id}/stop`、`POST /api/attachments/presign`、`POST /api/sync/batch` 和 `POST /api/webhooks/stripe`。所有写操作必须定义身份认证、授权、输入验证、幂等键、事务边界、审计和重试行为。

请提供详细的威胁模型，覆盖跨租户越权、伪造签字、照片恶意文件、离线同步重放、工时篡改、发票金额篡改、Webhook 伪造、管理员账户被盗和日志泄露。测试必须包含两个租户使用相同业务对象 ID 时的隔离测试、并发工时事件、重复同步批次、重复 Stripe 事件、附件扫描失败和离线冲突。

假设团队只有 2 名全栈工程师和 1 名兼职产品设计师，12 周内交付可试点版本。请给出按周拆分的路线图，但不得把未经验证的第三方审批时间写成确定日期。输出必须包括架构决策记录、模块边界、数据模型、API、离线同步策略、测试矩阵、部署、监控、迁移方案、风险登记表和试点验收标准。

最终回答必须使用简体中文，并且只提供计划。不要编写完整实现，不要假装代码已经存在。
```

## 九、案例 03：餐厅与供应商批发订货平台

```text
当前目录是一个空白代码库。你是一名负责从零设计平台的资深后端架构师和供应链产品负责人。请为一个连接独立餐厅、食品卡车、咖啡店与本地批发供应商的 B2B 订货系统制定完整实施计划。产品名为「Willamette Supply Hub」，内部项目编号为 WSH-B2B-0426。

采购方需要浏览供应商目录、查看按箱、按磅和按件销售的商品、建立常用采购清单、提交订单、选择配送日期、接收缺货替代建议、确认收货并下载发票。供应商需要管理客户专属价格、最小订购量、截单时间、配送路线、批次、库存、替代商品和信用额度。运营人员需要处理供应商审核、争议、退款、目录标准化和异常订单。

该系统不是普通消费者电商。相同 SKU 可能对不同客户具有不同合同价格。商品可能按 `case`、`each`、`lb` 或 `kg` 定价，数量和金额不能统一使用浮点数。请设计明确的精度、舍入和单位换算规则。订单创建时必须保存商品描述、单位、单价、税务分类和合同版本快照。历史发票不得因目录更新而改变。

每个供应商可以设置工作日 14:00 前下单才能次日配送。所有时间必须使用 UTC 存储，并根据供应商配置的 IANA 时区计算截单。默认演示时区为 `America/Los_Angeles`。供应商可以维护邮编配送区，例如 97005、97006、97214 和 97232，但不得在代码中硬编码。订单低于 `$250.00` 时可能收取配送费，但规则必须配置化。

采购订单状态与履约状态、发票状态和付款状态必须分离。请定义允许的状态转换，禁止从 `draft` 直接跳到 `delivered`。提交订单需要幂等键 `Idempotency-Key`。库存不足时，不得由系统未经采购方同意自动替换商品。替代建议必须保留原商品、建议商品、价格差异、数量变化、提出人和确认人。

评估 Next.js、TypeScript、PostgreSQL、Drizzle、Redis、Temporal 或轻量任务队列、Stripe ACH、Plaid、S3 兼容存储和 Postmark。不要为了未来规模提前拆分微服务。请设计模块化单体，并为 `catalog`、`contract_pricing`、`ordering`、`inventory`、`fulfillment`、`invoicing`、`payments`、`notifications` 和 `audit` 定义接口。

核心实体至少包含 `organizations`、`organization_members`、`supplier_customer_accounts`、`products`、`product_units`、`contract_price_lists`、`contract_prices`、`inventory_lots`、`purchase_orders`、`purchase_order_items`、`substitution_requests`、`delivery_routes`、`shipments`、`receipts`、`invoices`、`payments`、`webhook_events` 和 `audit_logs`。解释数据库约束如何防止跨组织访问、重复订单、重复付款事件和失效合同价格被使用。

必须提供真实的失败模式与恢复方案，包括供应商在截单前更新价格、提交订单时库存变化、支付成功但发票状态更新失败、配送路线取消、重复 Webhook、批量目录导入部分失败和单位换算错误。测试计划需要覆盖属性测试、事务集成测试、跨租户授权、并发订单、金额舍入、CSV 导入、Webhook 重放和备份恢复。

初始团队为 1 名高级后端工程师、1 名前端工程师、1 名兼职供应链运营专家。请制定 14 周 MVP 计划，清楚区分 P0、P1 和 P2，并列出每个阶段的验收标准、依赖、风险和回滚条件。

最终回答必须使用简体中文。只输出实施计划，不要创建任何代码，不要运行命令，也不要把尚未验证的税务、食品监管或付款规则描述为确定事实。
```

## 十、案例 04：非营利活动、票务与志愿者平台

```text
你正在面对一个完全空白的新代码库。请作为资深产品工程负责人，为一个面向 Oregon 和 Washington 小型非营利组织的活动、票务、捐赠和志愿者管理平台制定从零实施计划。产品名为「CivicGather」，项目标识符为 CIVIC-GATHER-2026。

组织需要创建免费或付费活动、设置票种、容量、候补名单、优惠码、捐赠选项、志愿者班次和签到规则。参与者需要浏览活动、购买门票、接收二维码、取消报名、加入候补名单和管理隐私偏好。志愿者需要申请班次、查看任务、签到和记录服务时长。组织管理员需要查看销售、捐赠、出席率、志愿者缺席率和退款，但不同组织之间必须严格隔离。

活动容量必须在高并发报名时保持正确。不能因为两个请求同时读取到剩余 1 个名额而卖出 2 张票。请比较数据库行锁、原子更新、序列化事务和队列方案，并明确推荐。票务预留最多保持 10 分钟，过期后自动释放。重复请求必须通过 `Idempotency-Key` 避免重复订单。二维码载荷不能直接暴露用户邮箱、姓名或订单金额。

候补名单需要保持可解释顺序。名额释放后可以向下一位发送限时邀请，但不能自动扣款。邀请令牌需要过期、单次使用，并且不能被另一个账户认领。志愿者签到需要支持管理员人工修正，但必须记录 `actor_id`、`reason`、`original_value`、`new_value` 和 `created_at`。

支付使用 Stripe，邮件优先使用 Postmark 或 Resend，二维码在服务端生成，数据库使用 PostgreSQL。请评估 Next.js 模块化单体、React、TypeScript、Tailwind CSS、Prisma 与 Drizzle、Clerk 与 Auth.js、Vercel 与容器部署。不得把支付卡数据存入平台数据库。Stripe Webhook 必须验证签名并通过 `provider_event_id` 幂等。

数据模型至少包含 `organizations`、`memberships`、`events`、`ticket_types`、`ticket_inventory`、`reservations`、`orders`、`order_items`、`tickets`、`waitlist_entries`、`waitlist_invitations`、`volunteer_roles`、`volunteer_shifts`、`volunteer_assignments`、`check_ins`、`donations`、`refunds`、`webhook_events` 和 `audit_logs`。请解释状态机、唯一约束、索引、软删除和财务记录保留。

平台需要满足基本无障碍要求，包括键盘购票、清晰焦点、表单标签、错误摘要、屏幕阅读器可理解的剩余票量以及不依赖颜色传达状态。分析工具不得接收完整姓名、邮箱、二维码令牌或付款信息。

测试方案必须包含并发抢最后一张票、预留过期、重复结账、重复 Webhook、候补邀请竞争、二维码重放、跨组织越权、退款失败、邮件供应商不可用和数据库恢复。上线前必须完成一次容量竞争压测和一次支付成功但本地事务失败的恢复演练。

请按 10 周给出 MVP 路线图，团队只有 2 名全栈工程师、1 名兼职设计师和 1 名兼职非营利运营顾问。明确哪些功能必须延期，例如复杂座位图、原生移动应用、多币种和高级营销自动化。

最终回答必须使用简体中文，只生成详细计划。不要编写完整代码，不要运行命令，不要假装已经创建或测试系统。
```

## 十一、案例 05：多租户事件响应与可观察性平台

```text
当前目录是全新的空代码库，没有任何现有组件。你是一名资深平台工程师和 SRE 负责人。请从零规划一个面向 20–500 人技术团队的多租户事件响应与可观察性平台。产品名为「SignalHarbor」，内部代号为 SIG-HARBOR-01。

平台需要接收来自应用、云服务和监控工具的告警事件，对事件进行规范化、去重、分组、关联和路由，创建事故，通知值班人员，记录确认、升级、缓解和解决时间，并生成事故时间线和复盘草稿。MVP 支持 HTTP Webhook、电子邮件入口和一个通用 JSON API，不需要一开始实现所有第三方原生集成。

目标吞吐量为普通租户每秒 25 个事件，短时突发每秒 250 个事件，单个请求体最大 1 MB。系统必须实施租户级速率限制、事件大小限制和背压。外部事件通过 `source_event_id` 幂等。相同事件重复发送 100 次不能创建 100 个事故。事件指纹算法必须版本化，并允许未来重新计算，但历史事故不能因算法升级而静默改变。

角色至少包括 `tenant_owner`、`responder`、`viewer` 和 `platform_admin`。所有数据访问都必须绑定 `tenant_id`。平台管理员访问租户事故必须需要原因并创建审计日志。事故时间线事件必须只追加；更正需要创建新的修正事件，不能覆盖原记录。

请明确选择 Python 或 TypeScript 后端，并比较 FastAPI、NestJS 和 Next.js Route Handlers。数据库优先 PostgreSQL。评估 Redis、Kafka、NATS、SQS 或 PostgreSQL 队列表，但 MVP 不得因为理论规模过早采用复杂流平台。需要说明 Webhook 接收路径中哪些步骤同步完成，哪些步骤异步处理，如何实现至少一次交付下的幂等，以及队列积压时如何降级。

核心模块至少包括 `identity`、`tenancy`、`ingestion`、`normalization`、`deduplication`、`routing`、`incidents`、`on_call`、`notifications`、`timeline`、`postmortems`、`audit` 和 `usage_metering`。核心实体至少包括 `tenants`、`memberships`、`api_keys`、`event_sources`、`raw_events`、`normalized_events`、`event_fingerprints`、`incidents`、`incident_events`、`routing_rules`、`on_call_schedules`、`escalation_policies`、`notification_attempts`、`webhook_deliveries` 和 `audit_logs`。

API 密钥只能在创建时显示一次，数据库只保存安全散列和前缀。示例密钥前缀必须保持为 `sh_live_`，但测试环境使用 `sh_test_`。Webhook 请求需要支持 `X-SignalHarbor-Signature`、`X-SignalHarbor-Timestamp` 和 `Idempotency-Key`。签名验证必须抵抗重放。统一错误响应必须包含 `code`、`message` 和 `request_id`，不得返回堆栈或租户内部数据。

必须规划指标与 SLO，包括事件接收成功率、P50/P95/P99 接收延迟、队列积压、去重率、通知成功率、首次确认时间和平均解决时间。不要把客户事件正文默认写入应用日志。需要定义数据保留、租户删除、加密、备份、恢复点目标和恢复时间目标，但不要声称未经演练的目标已经实现。

测试必须覆盖重复事件、乱序事件、时间戳漂移、无效签名、重放、超大请求、突发流量、队列不可用、通知供应商失败、数据库事务回滚、跨租户访问、管理员越权、API 密钥轮换和备份恢复。还需要一个可重复的负载测试计划，使用合成事件，不能使用真实客户事故内容。

初始团队为 2 名后端工程师、1 名前端工程师和 1 名兼职 SRE 顾问。请提供 12 周 MVP 路线图、模块边界、数据流、状态机、API、数据库索引、任务队列选择、部署拓扑、可观察性、安全模型、测试矩阵、容量假设、风险登记表和上线阻断条件。

最终回答必须使用简体中文，并且只制定实施计划。不要生成完整项目，不要运行命令，不要声称任何 SLO、安全属性或容量目标已经通过验证。
```

## 十二、最终交付要求

测试执行人需要提交一份 Markdown 报告，包含：

1. 五个案例各自的完整记录。
2. 每个案例的英文候选全文；这些提示词是合成内容，可以保留用于测试证据。
3. 所有失败截图。
4. 各语言检测结果和 Token 数。
5. 转换与验证阶段用量。
6. 受保护内容逐项检查结果。
7. 是否发生截断或协议错误。
8. 输入 Token 节省与优化器总开销的对比。
9. 是否建议继续保持无限制、恢复固定上限或采用自适应上限。
10. 明确结论：通过、部分通过或失败。

不得仅因为英文候选 Token 更少就判定产品假设成立。最终结论必须同时考虑转换正确性、受保护内容、语义验证、延迟、转换成本和目标模型输入节省。
