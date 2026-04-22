# 三循环开发工作流（通用模板）

> 本文件定义项目开发/优化/验证工作必须遵循的元流程，设计为可在不同仓库间复用。
> 每次任务由三个自顶向下的循环组成：**设计文档循环 → 实现文档循环 → 开发工作循环**。
> Phase 级别的「开发 ↔ 审查 ↔ 验收 ↔ 修复」四角 subagent 模板内联于 §4.1。
>
> **占位符约定**：文中 `<TEST-CMD>` 指代项目测试命令（Python 项目通常是
> `pytest tests/ -v`、Node 项目 `npm test`、Go 项目 `go test ./...`），
> `<ACCEPT-CMD>` 指代实现文档在每个 Phase 中声明的可验收命令。具体取值
> 由各项目在 `CLAUDE.md` 中声明。

## 0. 适用范围

- 任何对本仓库的**功能性改动**（新 feature、bug 修、优化、对外行为变更）。
- **Load-bearing 流程文档**的任何修改一律视为行为变更，**必须**完整走
  L1 → L2 → L3 三循环 + 独立 agent 审查；至少包括：
  - 本文件
  - `CLAUDE.md`
  - 项目在 `CLAUDE.md` §Load-bearing Docs 中显式声明的其他契约文件
    （典型如 `SKILL.md`、OpenAPI spec、schema 定义、公共 API 合同等）

  这些文件之间的承诺性条款漂移会让后续所有任务失准。
- **过渡条款（transitional clause）**：首次引入或首次回溯为 load-bearing
  的文档（含本文件初版），允许用「retroactive design brief 1 页 + 独立
  agent 审查连续 2 轮全绿」代替完整三循环。后续任何修改必须按正式规则走
  L1→L2→L3。
- 纯文档重排、typo 修正、依赖升级等**非行为变更**不强制走三循环，但仍需
  经过一次独立 agent 审查。
- 每个循环**禁止**让同一个 agent 既写又审；审查必须由一个全新的、只拿到
  相关上下文与 agent skill 的 agent 完成。

## 1. 总览

本文件三循环用 **L1 / L2 / L3** 标记，收尾用 **F**：

```
┌────────────────────────────────────────────────────────────────────────┐
│  一次任务的完整流水线（每个循环结束都必须达到「无新问题」才能进入下一个）          │
└────────────────────────────────────────────────────────────────────────┘

  L1  设计文档循环（§2）
      主 Agent 起草
      docs/design/<task-slug>.md              ─┐
                                                │  ┌── review subagent ─→ issues?
                                                └─→│                        │
                                                   └── fix ←────────────────┘  直到无新问题
                                                         ↓
  L2  实现文档循环（§3）
      主 Agent 依据 design.md 起草
      docs/implementation/<task-slug>.md      ─┐
                                                │  ┌── review subagent ─→ issues?
                                                └─→│                        │
                                                   └── fix ←────────────────┘  直到无新问题
                                                         ↓
  L3  开发工作循环（§4）
      Phase k 调用 §4.1 的四角 subagent（dev ①→review ②→accept ③→fix ④），
      ③ 全绿后进入 Phase k+1。
                                                         ↓
  F   端到端回顾（§5）
      对照 design.md 的「交付目标」逐项打勾；跑 <TEST-CMD> 与实现文档
      声明的 <ACCEPT-CMD>；按 §4.3 条件触发外部进程 smoke test。
```

**文档生成约定**：`docs/design/` 与 `docs/implementation/` 不是预先存在
的知识库，而是**每个任务在 L1/L2 阶段按需创建**。首个任务在仓库根目录
`mkdir -p docs/design docs/implementation` 之后落盘即可，无需事先规划目
录结构，也不为这两个目录维护 README 索引。

## 2. 循环 ① — 设计文档循环

### 2.1 目标
产出一份**自包含**的 `docs/design/<task-slug>.md`，让任何一个全新的 agent
单独阅读该文档 + 它明确引用的上游设计文档（若有），就能完成后续工作；
不需要当前会话的任何上下文。

### 2.2 必须包含的章节
1. **任务背景与目的**：为什么做、不做会怎样。
2. **交付目标（Deliverables）**：逐条可打勾的成品清单。
3. **范围边界**：明确「不做什么」，杜绝范围蔓延。
4. **关键设计决策**：每条决策列出「问题 → 候选方案 → 选择与理由」，含
   已废弃方案的否决原因。
5. **依赖与假设**：前置条件、外部系统、数据格式。
6. **与现有设计的关系**：引用既有 `docs/design/*.md` 中的章节与行号
   （若是首个设计文档，注明「无在先设计，术语锚点参照 `CLAUDE.md`
   §Language / Terminology 及项目 README」）；冲突点用 ⚠️ 标注，无法
   判断真相源时按 §6 规则向用户提问。
7. **验收标准（Acceptance Criteria）**：每条必须**可测量、可自动化**，
   避免「代码质量良好」这种无法验证的表述。
8. **风险与回退**：已识别的失败模式 + 回滚手段。

### 2.3 主 Agent 流程
1. 若已有 `docs/design/*.md`，先通读建立设计地图，避免冲突或重复建模；
   首个任务可跳过此步。
2. 读 `CLAUDE.md` 中的 §Language Policy 与 §Load-bearing Docs：确认项目
   对语言、术语一致性、契约文件范围的要求。
3. 遇到**任意**以下信号，**停下来向用户提问**（不要擅自假设）：
   - 交付目标含糊（「改善性能」「提升可读性」）。
   - 多个候选方案的 trade-off 无明显优劣。
   - 与现有设计可能冲突但无法判断「以设计为准」还是「以补丁为准」。
   - 涉及**破坏性变更**：schema / 退出码 / CLI 参数 / 存储布局 /
     对外协议 / 目录结构。

   提问时使用 `AskUserQuestion` 工具，每个问题**必须附候选项 + 推荐项 +
   推荐理由**，避免纯开放式问题。
4. 完成初稿后进入 §2.4。

### 2.4 设计文档 Review subagent 指令模板

```
你是 {{project-name}} 项目的设计评审工程师。

【任务】审视 {{design-doc-path}} 的初稿，找出 issues 与改进建议。

【语言约束】
审查对象若属于 CLAUDE.md §Language Policy 所列的「项目核心契约」范围
（如 SKILL.md / 源码目录 / references / public API 合同），发现违反该
语言规范（如夹杂非指定语言、术语漂移）直接记为严重问题。设计文档本身
的语言由 CLAUDE.md 裁定，但术语须与既有 `docs/design/`、项目 README、
核心契约文件中的用法一致。

【工作步骤】
1. 阅读 {{design-doc-path}} 全文。
2. 阅读它在「与现有设计的关系」中引用的所有 `docs/design/*.md` 章节；
   若为首个设计文档，改读 CLAUDE.md 所指向的契约文件作为术语锚点。
3. 阅读 `CLAUDE.md` 与本 `WORKFLOW.md`。
4. 逐条核对 §2.2 八个章节：
   - 有没有无法自动化验证的验收标准？
   - 交付目标是否可打勾？
   - 有没有与现有设计冲突但未标 ⚠️ 的？
   - 有没有只列出唯一方案、没有对比 trade-off 的决策？
   - 范围边界是否足够紧，有无「顺便」塞进来的扩展？
   - 风险与回退是否覆盖最可能的失败路径？
5. 不修改文档——只输出审查报告。

【输出格式】
## 设计文档审查报告（第 {{round}} 轮）

### 严重问题（阻塞进入实现文档循环）
- [章节] 问题描述 + 建议修复方向

### 一般问题（建议在本轮修复）
- ...

### 澄清项（需主 Agent 回到用户）
- ...

### 总评
通过 / 需修复 / 严重不达标
```

### 2.5 终止条件（L1、L2、L3 共用）
- **通过**：review subagent 本轮「严重问题」为空 + 连续 1 轮「一般问题」
  为空，即可退出当前循环。
- **硬上限（分域计数）**：L1、L2 各自独立计数，上限 3 轮；L3 在每个
  Phase 内独立计数，上限 3 轮。**不做跨域累加**——即便 L1 用满 3 轮才
  通过，L2 仍从 round 1 起算。任一域到 3 轮仍未清零严重问题 → 暂停循环，
  用 `AskUserQuestion` 向用户汇报僵局并请求裁定。
- **占位符递增**：主 Agent 每次 spawn review subagent 前将 `{{round}}`
  计数 +1 填入模板；subagent 禁止收到字面量 `{{round}}`。
- 修复由主 Agent 直接编辑；不为修复单独起 subagent（规模小）。
- 中途若识别出新的用户决策点，必须回到 §2.3 第 3 步提问，不得自决。

## 3. 循环 ② — 实现文档循环

### 3.1 目标
产出 `docs/implementation/<task-slug>.md`（或追加一个新 Phase 文件），让
全新 agent 读完就能进入 TDD 开发，**不回查当前会话**。

### 3.2 必须包含的章节
1. **任务索引**：指向设计文档中对应的「交付目标」与「验收标准」条目。
2. **阶段划分**：每个 Phase 自包含，列明：
   - 入口条件（上一 Phase 必须交付什么）
   - 设计文档引用（文件 + 行号区间）
   - 任务清单（按 TDD 拆分，先测后码）
   - 每个任务的**可验收命令**（pytest 选择器或 shell 命令，在仓库根目录
     直接可运行）
   - 出口条件（什么状态算该 Phase 完成）
3. **工程约束索引**：
   - 项目级工程规范 → `CLAUDE.md` 相应章节（Architecture / What Not to Do 等）
   - 四角 subagent 模板 → 本文件 §4.1
   - 提交规范 → 本文件 §4.2（`fix(phaseN-roundR):` 前缀等）
4. **数据与 fixture 依赖**：哪些已有测试资源可复用、是否需新增。
5. **回归保护**：哪些前序 Phase 测试必须保持绿色。

### 3.3 主 Agent 流程
1. 基于已通过的 design.md 起草，禁止引入 design.md 之外的新需求。
2. 拆分 Phase 的粒度原则：
   - 每个 Phase 约 2–4 天工作量，可独立提交并在 CI 上可验证。
   - 每个 Phase 结束时 `<TEST-CMD>` 全绿。
   - 每个 Phase 必须至少 1 条可在 shell 中独立复现的 `<ACCEPT-CMD>`
     （pytest 选择器、脚本调用或其他确定性命令）。
3. 遇到模糊（例如某个验收标准无法翻译为可执行测试）立刻回到 §2.3 第 3
   步，或把该条打回 design.md 修正后再进入本循环。

### 3.4 实现文档 Review subagent 指令模板

```
你是 {{project-name}} 项目的实现方案评审工程师。

【任务】审视 {{impl-doc-path}}，确认它可以指导一个全新 agent 无歧义开工。

【语言约束】同 §2.4：核心契约文件违反 CLAUDE.md §Language Policy = 严重
问题；实现文档本身遵循 CLAUDE.md 对流程文档语言的规定，但术语须与
`docs/design/` 及契约文件一致。

【工作步骤】
1. 阅读 {{impl-doc-path}} 全文，以及 {{design-doc-path}}。
2. 逐 Phase 回答四个问题（发现「否」即记为严重问题）：
   a. 新 agent 只读本文档 + 其引用的 design.md 章节，能否开始？
   b. 每个任务的「可验收命令」是否真实可运行？（pytest 测试名需在 tests/
      里已定义或文档规定必须新增；shell 命令需在当前仓库可执行）
   c. TDD 顺序是否正确（测试 Task 在实现 Task 之前）？
   d. 回归保护是否覆盖前序 Phase 的关键路径？
3. 核对与 CLAUDE.md / WORKFLOW.md 的一致性（commit message 前缀
   `fix(phaseN-roundR):`、语言策略、load-bearing 文档清单）。
4. 不修改文档——只输出审查报告。

【输出格式】与 §2.4 同，但章节名改为「实现文档审查报告」。
```

### 3.5 终止条件
沿用 §2.5；重点重申：L2 的 3 轮上限独立计数。设计文档若被迫回滚修改，
实现文档循环**必须重启**，已在循环 ③ 产出的 commit 由主 Agent 在
`docs/implementation/<task-slug>.md` 的「已废弃」节显式列出，避免实现漂移。

## 4. 循环 ③ — 开发工作循环

### 4.1 四角 subagent 模板

每个 Phase 至少走一轮 ①→②→③ 循环；③ 报告任何 ❌ 必须经 ④→③ 再循
环，直到全绿。四角职责划分：

| 角色 | 输入 | 产出 | 禁止 |
|------|------|------|------|
| ① **dev**（开发） | 实现文档中该 Phase 的任务清单 + 设计文档引用 | 代码改动（TDD：先测后实现）+ 任务清单打勾 | 修改实现文档；自行扩大范围 |
| ② **review**（代码评审） | dev 的 diff + 设计文档 + 实现文档 + CLAUDE.md | 审查报告（严重 / 一般 / 澄清三档，格式同 §2.4） | 修改代码 |
| ③ **accept**（验收） | 实现文档中该 Phase 的 `<ACCEPT-CMD>` 清单 | 每条命令的退出码与关键输出，标注 ✅ / ❌ | 修改代码或测试 |
| ④ **fix**（修复） | ② 或 ③ 的 ❌ 条目 | 最小范围的代码修正；commit message 前缀 `fix(phaseN-roundR):` | 动结构性重构；引入设计文档之外的新需求 |

**角色隔离硬约束**：同一个 subagent 在同一个 Phase 内只能承担一个角色；
主 Agent 每轮为每个角色 spawn 新的 subagent，避免「自己审自己」。

### 4.2 主 Agent 额外约束
- **每个 Phase** 结束后主 Agent 亲自跑一次 `<TEST-CMD>` 与该 Phase 在
  实现文档中声明的所有 `<ACCEPT-CMD>`，结果作为 Phase commit 的 trailer
  记录。
- 开发 subagent 若上报「设计文档与任务冲突」，**禁止**由 dev agent 自行
  决定，必须回到循环 ① 或 ② 修补源文档。
- **提交规范**：
  - Phase 首提：`feat(phaseN): <一句话摘要>` 或 `fix(phaseN): …`（依改动性质）。
  - Round 内修复：`fix(phaseN-roundR): <失败项关键词>`。
  - Trailer 记录 `<TEST-CMD>` 退出码与关键 `<ACCEPT-CMD>` 的结果。
  - **不得**在 commit message、PR 描述中提及 AI 参与、模型名、agent
    工具名等。

### 4.3 外部进程 / 端到端验证（按需触发）

**触发条件**：仅当任务修改了**对外行为契约**时触发——即
`CLAUDE.md` §Load-bearing Docs 中声明的契约文件（如 SKILL.md / public
API spec）、或被其直接引用的入口脚本/端点。纯内部重构、测试改动、
README 文档更新，以 `<TEST-CMD>` 为准，**不重复**跑外部进程。

> 本节示例以「通过真实 CLI 子进程加载并跑通 skill」为场景（适用于
> agent / skill / CLI 工具项目）。Web 服务项目可把示例替换为「在隔离
> 容器中启动服务 + 跑端到端测试脚本」，保留的通用原则包括：
> **隔离 worktree / ephemeral 沙箱 / 产物归档 / 自动清理**。

#### 4.3.1 前置检查（零成本，不调用付费 API）

```bash
# 以 Claude Code 为例；其他 CLI 请替换为等价的认证探测命令
[ "$(id -u)" = "0" ] && { echo AUTH_FAIL; exit 0; }   # root 常被拒绝

if claude auth status >/dev/null 2>&1; then
  echo AUTH_OK
elif claude --version >/dev/null 2>&1 && [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo AUTH_OK
else
  echo AUTH_FAIL
fi
```

失败即进入降级路径：跳过外部进程 spawn，改用 `<TEST-CMD>` + 一次人工
smoke（按契约文件描述的入口流程手动走一遍），并在最终交付总结 §5 第 3
条写明「§4.3 skipped: <原因>」。

#### 4.3.2 隔离 spawn 流程（示例）

```bash
set -euo pipefail                                # 任一步失败立即中断
TASK_SLUG="<kebab-case-task-id>"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
WT="$(mktemp -d -t e2e-wt-XXXXXX)"               # 隔离 worktree
SANDBOX="$(mktemp -d -t e2e-sandbox-XXXXXX)"     # 一次性沙箱（项目按需使用）
ARTIFACTS="./.e2e-artifacts/${TASK_SLUG}-${STAMP}"        # 需 gitignore
mkdir -p "${ARTIFACTS}"
git worktree add "${WT}" HEAD -b "e2e/${TASK_SLUG}-${STAMP}"

# 示例：以 Claude CLI 子进程加载并执行 skill；其他项目替换为 curl /
# docker compose run / go run 等等价命令。
(
  cd "${WT}"
  claude \
    --print \
    --dangerously-skip-permissions \
    --session-id "${SID}" \
    --output-format stream-json \
    --max-budget-usd 0.50 \
    -p "<按契约文件设计的端到端测试 prompt，参数化 SANDBOX 路径>"
) > "${ARTIFACTS}/stream.jsonl" 2> "${ARTIFACTS}/stderr.log"

# 清理
git worktree remove --force "${WT}"
git branch -D "e2e/${TASK_SLUG}-${STAMP}" 2>/dev/null || true
rm -rf "${SANDBOX}"
# ${ARTIFACTS} 留存归档；需沉淀为测试 fixture 时另起单独 PR 提交。
```

#### 4.3.3 归档与命名
- 活跃产物：`./.e2e-artifacts/<task-slug>-<UTC-ISO8601>/`
  （首次使用时需在 `.gitignore` 中加入 `.e2e-artifacts/`）。
- 沉淀为测试 fixture：仅当归档经人工审阅后，改名为
  `./tests/fixtures/e2e/<descriptive-slug>.<ext>`（目录按需新建）并
  **单独** PR 提交，附 `docs/implementation/` 的更新说明。**禁止**
  在功能 PR 中顺手加 fixture。

### 4.4 终止条件
- 每个 Phase 验收 subagent 全绿。
- 全量 `<TEST-CMD>` 与实现文档声明的所有 `<ACCEPT-CMD>` 退出码 0。
- 若 §4.3 触发，其外部进程产物无契约文件约定之外的错误（由实现文档
  显式列出通过条件，如「lint JSON 的 `clean: true`」「HTTP 200 +
  JSON schema 校验通过」等）。

## 5. 端到端回顾

任务关闭前主 Agent 必须：
1. 对照 design.md 「交付目标」逐条打勾；未完成项需有明确理由与后续 issue。
2. 跑 `<TEST-CMD>` + 实现文档声明的所有 `<ACCEPT-CMD>`，贴结果摘要。
3. 若 §4.3 触发，附上外部进程 smoke test 的关键输出片段；若因认证/
   环境跳过，注明「§4.3 skipped: <原因>」+ `<TEST-CMD>` 汇总作为替代证据。
4. 确认已无残留临时 worktree / 分支（`git worktree list` +
   `git branch --list 'e2e/*'` 抽查）。
5. 按 §4.2 提交规范写 final commit（不得提及 AI 参与）。

## 6. 不确定性上报规则（贯穿三个循环）

任何时刻遇到下列情形，**立刻暂停本循环，向用户提问**：

| 情形 | 动作 |
|------|------|
| 交付目标多解 | `AskUserQuestion` 列候选 + 推荐项 |
| 设计文档内部矛盾且无补丁 | `AskUserQuestion` 请求裁定真相源 |
| 破坏性变更（schema / 退出码 / CLI 参数 / 存储布局 / 对外协议） | `AskUserQuestion` 并说明迁移代价 |
| 凭证 / 网络 / 权限不可用 | 先 `Bash` 实测验证失败原因，再向用户汇报 |
| Magic number / 默认阈值（算法参数、权重、超时、batch 大小等） | 引用既有 `docs/design/` 或源码现有常量；无则 `AskUserQuestion` |
| Schema 向后兼容性裁定（旧字段保留 / 迁移 / 删除） | `AskUserQuestion` 附迁移影响面 |
| 需要超出授权范围的动作（push 到主分支、删除工作区外文件、对外发送消息） | 先向用户申请 |

**禁止**用「合理默认值」绕过提问；宁可延迟交付，不留设计债。
若 `AskUserQuestion` 工具在当前 harness 不可用，降级为在主输出中以
`STOP: QUESTION` 开头的纯文本提问段，并暂停所有 subagent spawn 等待回复。

## 7. 与 CLAUDE.md 的关系

- **`CLAUDE.md`**：项目索引，声明项目**特异性**配置——载入 load-bearing
  文档清单、语言策略、测试命令（`<TEST-CMD>` 的具体取值）、工程规范、
  Architecture 概览等。
- **本文件（`WORKFLOW.md`）**：跨项目通用的元流程——三循环 + 设计/实现
  文档 review 模板 + 四角 subagent 模板 + 提交规范 + 外部进程验证约束。
- **每任务产出**：`docs/design/<task-slug>.md` 与
  `docs/implementation/<task-slug>.md` 在 L1 / L2 阶段按需创建，不作为
  预先存在的库维护；也不为这两个目录单独写 README 索引。

`CLAUDE.md` 与 `WORKFLOW.md` 只读引用彼此，避免内容漂移：流程条款归
`WORKFLOW.md`，项目特异配置归 `CLAUDE.md`。

### 7.1 跨文件一致性 checklist（模板）
修改任一下表**承诺性条款**时，必须同一次 commit 同步其「承诺来源」+
「承诺引用」两处；提交前自查。各项目按此模式在 `CLAUDE.md` 中扩充
项目特异条款。

| 条款类别 | 承诺来源（权威定义） | 必须同步引用 |
|---------|------------------|------------|
| 三循环触发条件（L1/L2/L3） | `WORKFLOW.md` §0 / §1 | `CLAUDE.md` §Working in This Repo |
| 四角 subagent 模板 | `WORKFLOW.md` §4.1 | `WORKFLOW.md` §3.2 工程约束索引 |
| Commit 前缀 `fix(phaseN-roundR)` | `WORKFLOW.md` §4.2 | `WORKFLOW.md` §3.4 review 模板 |
| 外部进程 E2E 触发 | `WORKFLOW.md` §4.3 | `CLAUDE.md` §Working in This Repo（转引一行） |
| Load-bearing 文档清单 | `WORKFLOW.md` §0 + `CLAUDE.md` §Load-bearing Docs | 所有列入清单的契约文件头部应互相引用 |
| 语言 / 术语策略 | `CLAUDE.md` §Language Policy | `WORKFLOW.md` §2.4 / §3.4 review 模板 |
| 测试命令 `<TEST-CMD>` | `CLAUDE.md` §Common Commands | 实现文档的「可验收命令」章节 |

自查命令示例（grep 模式按实际项目调整）：
```bash
# 「承诺来源」和「引用处」两处都应命中
Grep "Load-bearing" CLAUDE.md WORKFLOW.md
Grep "fix\(phaseN-roundR\)" WORKFLOW.md
```
若新增承诺性条款，必须先在本表登记其权威来源与引用处，再修改文件。
