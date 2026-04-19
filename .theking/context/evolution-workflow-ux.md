# Evolution · Workflow UX

## 背景

sprint-001-kimi-feedback-optimizations 落地后，在一次与用户的复盘里又浮出
若干未解决、但**尚未成为硬规则违例**的工作流体验痛点。为了避免这些观察散落
在 memory 或 sprint review INFO 里被遗忘，这里单独立一份演进规划。

本文件与 [`evolution-plan.md`](evolution-plan.md) 并列：

- `evolution-plan.md` — 架构与 ownership 主线（`.theking/` 如何分层、
  projection 如何组织、工具本体与项目仓库的责任边界）。
- `evolution-skill-layering.md` — superpowers 精华吸收后的规则落位方案
  （哪些规则进 `workflow-governance`，哪些进 agent prompt，哪些留给
  `workflowctl`）。
- `evolution-workflow-ux.md`（本文件）— 工作流本身的体验与质量主线
  （subagent 调用、并行度、规则与 AI 自由度、测试/调研深度、agent 利用率）。

当两份文件在同一问题上出现冲突时，以 `evolution-plan.md` 为准；本文件只在
不改变架构底线的前提下，谈"怎么用起来更顺"。

## 证据与取证原则

本规划的每一条议题都必须与**真实 sprint 的工件**挂钩，不是凭感觉：

- 议题编号 `I-xxx` 会引用 `.theking/workflows/<project>/sprints/<sprint>/`
  下的具体 task、review、verification 路径
- "现状"与"痛点"小节只写**已观察到的事实**；推断性结论放到"建议改进"
- 任何需要改动 skill / agent / workflowctl 的落地动作，都以 sprint 级 task
  去承接，不在本文件内直接设计实现

---

## 议题清单

### I-001 · subagent 调用门槛过低 ✅ 已落地于 sprint-003 (TASK-004)

**现状（sprint-001 证据）**：

- Phase 3-5 每个 task 都按"planner → tdd-guide → code-reviewer"顺序召
  subagent，即使是 TASK-006 这种"前一个 task 已经覆盖完了"的 pin-only task
  （见 `sprint-code-review-round-001.md` I1）。
- 主 agent 已经持有完整上下文，subagent 召唤会重新加载 prompt body，在
  简单 task 上收益为零，成本是 token + 一次 round-trip。

**痛点**：

- 单 task 轻量流程下 planner 变成橡皮图章。
- Pin-only task 的 tdd-guide 只是走过场。
- code-reviewer 作为"独立人格"仍有价值；security-reviewer 与 e2e-runner
  受画像驱动、必须保留。

**建议改进**：

- 把"调 subagent 的门槛"写进各自 agent 的 `description`，让 AI harness
  能自行跳过。例：planner 的 description 里补一句"单 task 轻量流程下直接
  返回空方略，不拆分"。
- skill 的 Phase 3 轻量分支已写"跳过 planner"；可以进一步把"pin-only
  task 允许主 agent 自证 TDD"作为轻量流程的合法变体，但需要在
  `workflowctl check` 里补一个"前一个 task 的测试覆盖当前 task 的断言"
  的轻量证据约束，防止沦为偷懒出口。

**不做**：

- 不动 code-reviewer / security-reviewer / e2e-runner 的"独立人格"定位，
  这是 sprint-001 review 证据链能成立的关键。

**优先级**：P2（现有流程能运转，价值在省 token）

---

### I-002 · 独立 task 无法真正并行 ✅ A 档已落地于 sprint-003 (TASK-005，文档层)

**现状（sprint-001 证据）**：

- sprint-001 的 6 个 task 彼此几乎独立（TASK-006 依赖 TASK-002，其余互不
  依赖），但实际是串行执行，activate → done 一个接一个。
- 原因：`workflowctl activate` 通过 decree checkpoint 维护单一 active
  task；状态机按 task 推进；AI harness 的 subagent 目前不擅长跨 task 并发。

**痛点**：

- 独立 task 并行化是体感提速最大、也最容易被忽视的一档。
- skill Phase 4 开头那句"无依赖的 task **并行启动**"目前是**文字约束，
  没有工具化**。

**建议改进（按工作量递增三档）**：

- **A 档**（小工作量，skill 文案即可落地，风险几乎无）：同一 session 内主
  agent 依次切换 active task 写代码，但**review 轮并发**——code-reviewer、
  security-reviewer、e2e-runner 同时看同一个 task。
- **B 档**（中工作量，要改 decree checkpoint 结构 + scaffold 脚本，需考
  虑 projection 冲突）：`workflowctl` 支持多 active task
  （`activate --multi`），允许多 AI session / 多 git worktree 并行。
- **C 档**（大工作量，当前 AI harness 不成熟，风险高）：真正的 subagent
  并发派单。

**优先级**：P1（A 档可立即落地，B 档作为后续独立 sprint）

---

### I-003 · 编排规则 vs AI "觉得最好路径"

**现状（sprint-001 证据）**：

- Kimi CLI 在 sprint-001 过程中**反复**提出"能不能跳过 planner / 能不能
  一次性把多个 task 合并写"，即使已有 8 条硬规则。
- 硬规则的设计初衷就是防滑槽——没有它，AI 会跳过 spec 直接写代码、跳过
  先红直接实现、把 review 当橡皮图章。

**痛点**：

- 真正的痛点不是"硬规则太死"，而是**轻量流程的出口条件不够明显**：AI
  遇到简单任务时找不到"合法跳过路径"，就会试图违规跳过硬规则。
- sprint 级统一流程假设 vs task 级实际差异（sprint-001 里 TASK-001 是文档
  向，TASK-006 是 pin-only，本应跑不同轻重）。

**建议改进**：

- Phase 2 分流决策里加**正反例对照**：从历史 sprint 里抽出 3 条"这类该
  用轻量"+ 3 条"这类必须完整"的案例。
- 解耦 sprint 流程与 task 流程：允许同一 sprint 内不同 task 走不同流程级
  别（workflowctl 本来就是 task 级，skill 文案要跟上）。
- 硬规则 8 条**不让步**——它们是护身符。

**不做**：

- 不引入"AI 可以自行宣告跳过某条硬规则"的逃生阀，一次破例就会被泛化。

**优先级**：P2（需要积累更多 sprint 证据再精化分流规则）

---

### I-004 · 测试/调研深度不足 ✅ 已落地于 sprint-002

**现状（sprint-001 证据）**：

- sprint-001 所有 task 的测试都通过，但测试数量分布不均：
  TASK-001 (6) / TASK-002 (4) / TASK-003 (2) / TASK-004 (33) /
  TASK-005 (3) / TASK-006 (7)。
- 深层观察：tdd-guide 当前只约束"先红后绿"，不约束**写什么测试**。容易
  发生只测 happy path、不测集成点、不做 edge case 穷举。
- `spec.md` 的 Test Plan / Edge Cases section 是必填，但**填了什么内容
  不校验**，可以敷衍。
- Phase 1 察情只要求"已查看/影响面/风险标签"三项，没有调研深度检查单。

**痛点**：

- 测试充分性目前完全靠 code-reviewer 兜底，而 code-reviewer 的 review
  模板里没有"测试覆盖分析"章节，容易漏。
- 调研不足的典型表现：AI 没先看现有代码的 3 处先例就提新方案；没读外部
  库最新文档就凭训练数据写代码；没复用已有测试辅助工具就重写一套。

**建议改进（sprint-002 候选范围）**：

1. **spec 门禁强化**：`workflowctl check` 在 `planned` 状态检查
   `spec.md` 的 Test Plan 至少 N 条、Edge Cases 至少 M 条（完整流程 N=5
   M=3，轻量流程 N=3 M=1）。
2. **Phase 1 加调研清单**：
   - [ ] 相似功能在现有代码里的 3 处先例（列 file:line）
   - [ ] 依赖的外部库/API 的最新文档是否读过
   - [ ] 测试框架现有的辅助工具是否可复用（列 helper）
   - [ ] 同一 module 已有的 edge case 测试模式（列 test file）
3. **tdd-guide prompt 增加对抗思维**：写测试前先列 10 个能让实现失败的
   输入类别，覆盖至少 5 个。
4. **code-reviewer 模板加"Untested paths"章节**：强制 reviewer 指出哪些
   分支/边界没被测试盖到。

**优先级**：P0（下一个 sprint 候选主题）

---

### I-005 · architect agent 从未被触发 ✅ 已落地于 sprint-002

**现状（sprint-001 证据）**：

- `.theking/agents/architect.md` 已定义（78 行，有 ADR 模板），但
  sprint-001 零调用。
- 原因：sprint-001 全是局部改动，确实没有架构决策；且 skill 里 architect
  被定位为"按需召唤"，没有强触发条件；planner 的 task_type 决策树里也没
  标注"遇到哪些场景就该先请 architect"。

**痛点**：

- architect 的真实价值场景（多 module 重构、新依赖引入、公共接口变更）
  在一个成熟 skill 项目里必然会来，但缺触发规则就会被跳过。
- ADR 产出物当前无落地路径规范（`.theking/context/adr/` 目录存在于
  `evolution-plan.md` 蓝图，但未实装）。

**建议改进（可与 I-004 合并到 sprint-002）**：

1. Phase 3 完整流程加子门禁：planner 方略里出现以下任一信号时，**必须
   先召 architect 出 ADR，再 `init-sprint-plan`**：
   - 新增跨 module 接口
   - 引入新依赖（`package.json` / `pyproject.toml` / `go.mod` 变化）
   - 公共接口变更（已发布 API / CLI flag / 配置 schema）
   - 数据迁移
2. 落地 `.theking/context/adr/ADR-NNN-*.md` 路径规范（和
   `evolution-plan.md` 蓝图一致）。
3. `catalog.md` 里把 architect 从"可选扩展"升到"条件必须"。
4. architect 产出的 ADR 由 code-reviewer 轻审一轮（重点：决策理由、备选
   方案、对现有架构的影响）再合入 context。

**优先级**：P0（下一个 sprint 候选主题）

---

### I-006 · sprint 级全量回归成本随项目膨胀

**现状（sprint-001 证据）**：

- 每个 task 的 `verification/cli/test.log` 只跑自己相关的测试文件
  （0.01-2.5 秒），这点是好的，tdd-guide 本来就这么干。
- Phase 5 步骤 2 的 sprint 级全量回归跑了 290 测试 + 31.9 秒，当前可接受。
- **原始 review 笔记里写的"54+ 分钟纯等待"是 AI 夸张错**——没核对实际
  test.log 就把"假想的坏情况"当成"已发生的事实"写进去了。

**痛点**（预测性，非当前问题）：

- 一旦项目测试体量膨胀到全量 5 分钟+，Phase 5 会跑两遍（regression +
  refactor-cleaner 后再一遍），就会变成真的等待痛点。
- refactor-cleaner 的改动验证当前就要求"完整 build + test"（skill Phase
  5 步骤 4.c），没有增量回归出口。

**建议改进**：

- 短期：不动。当前数据量下不是问题。
- 中期（等有真实痛点再做）：
  - Phase 4 TDD 只跑相关 test file（**现状已如此**，只是 skill 文档里
    没写清楚"只跑相关"）。
  - Phase 5 加可选"受影响测试子集"路径：基于 git diff 推导受影响模块，
    只跑相关 test 作为第一关，全量回归作为第二关。
- **教训**：review 笔记的 INFO 部分也要挂证据引用，不要靠记忆写数字。

**优先级**：P3（观察性，有真实痛点再启动）

---

### I-007 · 已收尾 sprint 的增强与回补没有正式路径 ✅ 已落地于 sprint-003 (TASK-001, TASK-002, TASK-005)

**现状（证据）**：

- sprint.md 模板（`templates/workflow/sprint.md.tmpl`）没有 frontmatter，
  也没有 `status` 字段；sprint 的"结束"只是 Phase 5 跑完 + `deactivate`
  的**惯例**，不是**状态机**。
- `workflowctl` 没有 `close-sprint` / `reopen-sprint` / `seal-sprint` 命令
  （`workflowctl.py` 仅提供 `init-sprint` / `init-sprint-plan` /
  `sprint-check`）。
- sprint-001 所有 task 已 `done`，工件齐备，但**没有任何一条命令可以在
  sprint.md 上落"已封存"印记**。
- 对应两个现实场景（用户在 sprint-001 完结后立刻提出）：

  **场景 A**：sprint-N 已收尾、尚未起 sprint-(N+1)。此时想到新问题、
  或发现问题需要再加强同一批改动。

  **场景 B**：sprint-N 已收尾，又已迭代了多个新 sprint（sprint-(N+1)
  到 sprint-(N+k)）。此时回看 sprint-N 发现遗留问题。

**痛点（分场景）**：

- **场景 A**：容易被误处理成「直接在 sprint-N 里再加 task」。这会污染
  sprint-N 的历史（review 轮数、exit criteria、Task Overview 表格），
  让「这个 sprint 到底做了什么」变得模糊。但又舍不得为一两个小改动单独
  起 sprint-(N+1)。
- **场景 B**：sprint-N 已经是**历史档案**，在上面做任何改动都是"改写
  历史"。但新 sprint 里又可能重复 sprint-N 已经解决过的教训，浪费时间。
  同时 sprint-N 的 review 目录里没有"后续相关改动的反向指针"，审计链断。

**建议惯例（不改工具、当下可执行）**：

明确两条规则，全部按"新起 sprint，不回填旧 sprint"原则走：

1. **sprint 一旦进入 Phase 5 封印（`deactivate` 执行），内容即只读**，
   不再追加 task、不再改 sprint.md 的 Task Overview、不再开 review 轮。
2. 新想法 / 新问题一律 **另起一个 sprint**，按以下四种情况选型：

   - **场景 A · 自然延续**：sprint-N 刚收尾，新想法是同一主题的加强。
     命名：`sprint-(N+1)-<theme>-continued`。反向链接建议但非强制。
   - **场景 A · 独立议题**：sprint-N 刚收尾，新想法与原 theme 无关。
     命名：`sprint-(N+1)-<new-theme>`。不需要反向链接。
   - **场景 B · 真 bug / 明确遗留**：已经迭代多个 sprint 后，回看
     sprint-N 发现 bug 或明确遗留。命名：
     `sprint-(N+k+1)-followup-sprint-NNN-<slug>`。**强制反向链接**：
     task spec 里必须引用原 sprint 路径与证据。
   - **场景 B · 演进 / 重构**：回补其实是新阶段的演进，不是原 sprint 的
     错。命名：`sprint-(N+k+1)-<new-theme>`。在 evolution-workflow-ux
     里记一笔即可，sprint.md 不加反向链接。

3. **反向链接机制**：场景 B 的 followup sprint，必须在其
   `sprint.md` 的 `## Theme` 下方加一段 `## Follow-up Source`，明确指
   向被回补的 sprint 路径；同时在被回补 sprint 的目录下新增
   `followups.md`（单文件、附加式），记录"后续 sprint-XXX 因本 sprint
   引出的 task 列表"。`followups.md` 属于**元数据追加**，不算"改写历
   史"，在惯例层允许。

**建议改进（可工具化增量）**：

- `workflowctl seal-sprint --sprint-dir <dir>`：在 sprint 所有 task
  都 `done` 时，在 sprint.md 顶部写入 frontmatter `status: sealed` 和
  `sealed_at`，此后 `init-task --sprint <sealed>` 拒执。
- `workflowctl followup-sprint --source-sprint <path> --new-theme <x>`：
  封装"新起 sprint + 自动注入 `## Follow-up Source` + 自动在源 sprint
  写入 `followups.md` 条目"三步。
- sprint.md 加一个可选 `## Follow-ups` section（模板层面加，不强制），
  类似 task 的 review 目录，让"这个 sprint 后续有哪些延伸"在阅读时即
  可见。

**不做**：

- 不允许"在已封印 sprint 里加 task"——即使提供了 reopen 命令也不做；
  reopen 会破坏"sprint 是 immutable 审计单元"的根基。
- 不把 followup 的范围限定为"修复原 sprint 的 bug"——任何基于原 sprint
  证据的新想法都可以走 followup 通道，重点是**反向链接在**。

**优先级**：P1

- 惯例层（命名 + `followups.md` + Follow-up Source section）：
  **立即生效**，不需要改代码，只要把这条议题的"建议惯例"写进 skill 文
  档即可。
- 工具化层（`seal-sprint` / `followup-sprint`）：排到 sprint-003 或更晚，
  优先级在 I-004/I-005 之后。

---

### I-008 · task.md `flow` 字段端到端整合测试缺失 ✅ 已落地于 sprint-003 (TASK-003，并修复了一个由此发现的 serialize 路径 bug)

**现状（sprint-002 review M1）**：

- TASK-001 落地 `flow: full | lightweight` 为 task.md 的可选 frontmatter，
  `validate_task_dir` 会 `normalize_task_flow(task_data.get("flow"))` 再
  传给 `validate_spec`
- 但 `task.md.tmpl` 没有 `flow:` 的 placeholder（哪怕是注释形式）
- 没有 CLI 集成测试：创建一个 lightweight task → 放一个 lightweight
  门槛恰好够用、full 门槛不够的 spec → `advance-status planned → red`
  验证整条链路

**痛点**：单元测试覆盖函数本身，但"task_data 读取 → flow → validate_spec"
的线没有 end-to-end 断言。未来如果有人改 task_data 的 wiring（例如 YAML
parser 变化），flow 可能会静默消失，不会有告警。

**建议改进**：

- 在 `task.md.tmpl` 加一行注释：`# flow: full  # optional; set to 'lightweight' for reduced spec thresholds`
- 在 `tests/test_init_task.py` 加一个 test：初始化 task → 改 flow →
  写稀疏但合规 spec → advance planned→red → 断言成功；再把 flow 改回
  full → advance 失败

**优先级**：P2（下一个微 sprint 或 I-002A 时顺带）

---

### I-009 · `workflowctl new-adr` helper

**现状（sprint-002 review M2）**：

- `agent_architect.md.tmpl` 现在说 "Pick the next unused NNN (manual for
  now; a `workflowctl new-adr` helper may land later)"
- 这是带前置承诺的 TODO，但没人 tracking
- 并发 sprint 下手动编号易撞号

**建议改进**：

- 加 `workflowctl new-adr --title <t> --slug <s>`：扫描
  `.theking/context/adr/ADR-*.md`、计算下一个 NNN、从 `adr.md.tmpl` 渲染
- 不做"自动提交" / "自动填内容"，只负责路径和编号

**优先级**：P3（等多 sprint 并发实际遇到冲突再做）

---

### I-010 · Phase 1 缺少"深度代码考古"角色

**现状（ASR 重构 CodeBuddy 对照证据）**：

- 另一个 AI 工具在做 ASR 模块重构时，产出了一份高质量的 336 行 proposal：
  读完 9 个 handler 文件 → 精确到行号定位 3 处 ~200 行重复代码 → 归纳出
  3 种核心能力抽象（流式/一句话/异步文件） → 画清 7 个前端 demo 到后端
  handler 的完整映射矩阵。
- theking 当前没有任何角色负责这种**针对具体重构主题的深度代码考古**：
  - planner 假设你已经理解了代码
  - architect 假设问题空间已经清楚
  - `analyze-project` 是泛项目级 context 填充，不针对具体主题
- Phase 1"察情"只要求"已查看 / 影响面 / 风险标签 / 3 处先例"，没有
  **结构化的分析产出**要求。

**痛点**：

- 没有分析产出就进入 planning → planner 对问题空间的理解全靠 prompt 里
  的口头描述 → 容易遗漏隐性耦合、重复代码、非显式依赖。
- 分析结论（如"ASR 只有 3 种核心能力"）有跨 sprint 复用价值，但当前
  无处沉淀——要么散落在 LLM 对话历史里，要么写在一次性方案文档里。

**建议改进**：

Phase 1 增加可选但强推荐的"Investigate"步骤（大型重构/新特性主题时触发）：

```
Phase 1（改进后）：
  1.1  触发条件检查（轻量 vs 完整）
  1.2  【新增·条件触发】深度代码考古
       触发条件：重构涉及 ≥3 个源文件 或 涉及跨模块依赖
       产出物：.theking/context/<theme>-analysis.md
       内容要求：
         - 能力 / 职责分类（归纳抽象层级）
         - 重复代码定位（file:line × N）
         - 调用关系图（谁调了谁，哪些是复制粘贴）
         - 前后端 / 上下游映射矩阵
         - Open questions（明确列出需要用户确认的未知项）
       → 直接喂给 architect 和 planner 作为输入
  1.3  Open questions 收集 + 用户确认
  1.4  Architect 触发检查（现有逻辑）
```

**关键约束**：

- 产出沉淀到 `.theking/context/`，不是一次性文档。下个 sprint 还能用。
- 不引入新 agent——主 agent 或 architect 均可执行此步骤。
- 当主题简单（单文件 fix、轻量流程）时跳过。

**不做**：

- 不把这一步变成硬规则门禁。它是分析深度的增强，不是流程闸门。

**优先级**：P0（解决"为什么别人的分析比我们深"的根本问题）

---

### I-011 · 编译型语言的 TDD 适配：skeleton → red → green

**现状（ASR 重构对照证据）**：

- ASR 重构的 Stage 1 需要新建 `core/recognizer.go` 包。在 Go 里，测试
  `import core.NewRecognizer()` → core 包不存在 → **编译失败**（不是测试
  失败）。
- 当前硬规则 #4"Red before Green"的语义是"所有测试失败"。但在编译型
  语言（Go/Rust/Java/C++）里，"编译不过"和"测试失败"是完全不同的
  东西。前者意味着测试框架根本无法运行。
- 强行要求"先写测试再写任何代码"在 Go 里不可能字面执行——你必须至少
  有包声明 + 类型定义 + 函数签名，测试才能编译。

**痛点**：

- AI 在 Go 项目里执行 `planned → red` 时，要么违规先写实现（打破 TDD），
  要么写出编译不过的测试文件（无法进入"红"状态，卡死在编译错误）。
- 当前 `workflowctl check` 没有区分"编译失败"和"测试失败"。

**建议改进**：

状态机增加合法的 skeleton 概念，严格限制边界：

```
planned
  ↓ (skeleton: 只有类型定义 + 函数签名 + 零实现体)
red    ← skeleton + 测试都存在，go test 能编译运行，测试全部 FAIL
  ↓ (写实现代码)
green  ← 测试全部 PASS
```

Skeleton 的严格定义（写进 tdd-guide agent prompt）：

```
✅ skeleton 允许：
  - package 声明和 import
  - type / struct / interface 定义
  - 函数签名（参数和返回值类型）
  - return 零值 / return nil, errors.New("not implemented") / panic("not implemented")
  - 常量和枚举定义

❌ skeleton 不允许：
  - 任何业务逻辑（if / for / switch / 函数调用链）
  - 任何非零值 return（return 真实计算结果）
  - 任何对外部包的有意义调用（import 可以有，调用不行）
  - 超过 1 行的函数体（零值 return 那一行之外不能有别的）
```

落地范围：

1. tdd-guide agent prompt：增加"编译型语言 skeleton 阶段"指引
2. workflow-governance skill：Phase 4 步骤 3 增加 skeleton 子步骤说明
3. validation.py：`planned → red` 转换时，skeleton 文件的存在不算违反
   "spec before code"（skeleton 不是 code，是类型签名的代码化表达）
4. 不改状态机本身——skeleton 是 `planned → red` 过程中的内部步骤，不引入新状态

**不做**：

- 不为 Python/JS 等动态语言启用 skeleton——它们不需要。
- 不放松"红"的定义：`go test` 必须能编译运行，输出必须全 FAIL。
  编译不过 ≠ 红。

**优先级**：P0（解决编译型语言 TDD 的根本矛盾）

---

### I-012 · Task Bundle：紧耦合任务的批量实现

**现状（ASR 重构对照证据）**：

- ASR 重构的 Stage 1（core 层抽象）和 Stage 3（service/streaming.go 调用
  core）是紧耦合的。LLM 在写 `core/recognizer.go` 时脑子里已经有
  `service/streaming.go` 怎么用它了。
- 强制 Stage 1 做完 → reset context → 再开 Stage 3，丢失连贯性。
- 更严重：Stage 1 的 core/ 在 Stage 3 用它之前**根本无法被真正验证**——
  没有真实调用方，你验证的只是"单独编译通过 + mock 测试通过"。
- 与 I-002B（多 active task / 并行）不同：这里不是并行问题，是**紧耦合
  任务需要一起实现才有意义**的问题。

**痛点**：

- 逐 task 串行 + 逐 task 完整状态机 = 42 次状态流转（6 task × 7 state）。
  其中大量流转是仪式性的——Stage 1 的 `done` 和 Stage 3 的 `draft` 之间
  没有任何信息增量。
- 紧耦合 task 分开 review 时，reviewer 看不到完整上下文（只看到 core 层
  的实现，不知道调用方怎么用）。合在一起 review 信息密度更高。

**建议改进**：

引入 Task Bundle 概念：

```yaml
# plan.json 中的表达
bundle:
  slug: core-and-streaming
  tasks: [TASK-001-core-layer, TASK-003-streaming-session]
  justification: "core 是 streaming 的唯一调用方，分开验证无意义"
```

Bundle 规则：

| 维度 | 独立 Task | Bundle |
|------|----------|--------|
| spec.md | 每个 task 独立 | 每个 task 独立（scope 不同） |
| 实现 | 逐个 planned → red → green | Bundle 内共享一个 red → green 周期 |
| review | 逐个 in_review | Bundle 整体一次 review（diff 更有上下文） |
| 状态机 | 7 states × N tasks | spec 独立 → 实现合并 → review 合并 → 各自 done |
| 回滚 | 单 task 粒度 | Bundle 粒度 |

Bundle 的状态流：

```
TASK-001: draft → planned ─┐
TASK-003: draft → planned ─┤
                           ↓
              Bundle: red (skeleton + tests for both)
                           ↓
              Bundle: green (implementation for both)
                           ↓
              Bundle: in_review (one review covering both)
                           ↓
TASK-001: ready_to_merge → done
TASK-003: ready_to_merge → done
```

准入约束：
- Bundle 最多 3 个 task（防止变成"什么都塞一起"）
- Bundle 内的 task 必须有 `depends_on` 关系（证明耦合）
- spec 仍然独立——每个 task 的 scope / acceptance / edge cases 不能合并
- planner 在 plan.json 里显式声明 bundle + justification
- 独立 task（如 yui 搬家）不允许入 bundle

**不做**：

- 不在本议题实现——这需要改 workflowctl 状态机、planner 输出格式、
  review pair 匹配逻辑。设计先记录在此，实现排到独立 sprint。
- 不影响现有的独立 task 工作流。

**优先级**：P1（依赖 I-011 skeleton 概念；工作量大，需要独立 sprint）

---

### I-013 · Task 流程三档制：full / lightweight / mechanical

**现状（ASR 重构对照证据）**：

- ASR 重构 6 个 Stage 差异巨大：
  - Stage 1（core 层抽象）= 重构核心，需要完整流程
  - Stage 5（yui 搬家）= 纯文件移动 + import 改
  - Stage 6（目录重组）= 纯 rename + import 调整
- 当前只有 `full` 和 `lightweight` 两档。`lightweight` 降低了 spec 门槛
  （Test Plan ≥3, Edge Cases ≥1），但**状态机步骤完整不变**。
- Stage 5/6 这种纯机械操作，连 `lightweight` 都嫌重：写 3 条 Edge Case
  对一个 `mv` + `sed` 操作毫无意义。

**痛点**：

- I-003 已经指出"轻量流程出口条件不够明显"。增加 mechanical 档可以
  更精确地匹配 task 的实际复杂度。
- 当 AI 遇到 Stage 6 级别的机械任务时，如果只有 full/lightweight 两个
  选项，会倾向于：要么勉强塞进 lightweight（敷衍 spec），要么试图违规
  跳过步骤。给它一个合法的 mechanical 出口更健康。

**建议改进**：

| 维度 | full | lightweight | mechanical（新） |
|------|------|------------|-----------------|
| 适用场景 | 新特性、重构核心 | 单文件 fix、pin-only | 纯移动/重命名/import/配置 |
| spec.md | TP≥5, EC≥3 | TP≥3, EC≥1 | 仅 Scope + Acceptance，无 Edge Cases |
| TDD | skeleton → red → green | 可主 agent 自证 | 只需 build green + existing tests green |
| code-reviewer | 必须（独立 agent） | 必须（独立 agent） | 必须（可合并到 bundle review） |
| security-reviewer | 条件触发 | 条件触发 | 跳过（纯移动不改逻辑） |
| verification | smoke.md + 冷启动证明 | smoke.md 精简 | `go build && go test` 输出即可 |
| 状态机 | 7 states 完整 | 7 states 完整 | draft → planned → green → in_review → done（跳 red） |

mechanical 的准入条件（planner 在 plan.json 里标注）：

```
✅ 符合 mechanical：
  - 文件移动 / 重命名 / import path 调整
  - 配置文件修改（不改逻辑）
  - 删除确认已死的代码（refactor-cleaner 的产出）
  - 版本号 / changelog 更新
  - 纯格式化 / lint fix

❌ 不符合 mechanical：
  - 任何新函数 / 新类型的引入
  - 任何业务逻辑变更
  - 任何接口签名变更
  - 任何测试逻辑变更
```

安全阀：code-reviewer 在 review 时如果发现 mechanical task 实际包含了
逻辑变更，有权**升档**到 lightweight 或 full，task 回退到 planned 重走。

落地范围：

1. `constants.py`：`ALLOWED_FLOWS` 增加 `"mechanical"`
2. `validation.py`：
   - `validate_spec` 对 mechanical 放宽：不要求 Test Plan / Edge Cases section
   - `validate_task_metadata` 对 mechanical 允许跳过 `red` 状态
   - `validate_review_requirements` 对 mechanical 不要求 security-review pair
     （除非 execution_profile == backend.http，那永远要）
3. `planner.md`：decision tree 增加 mechanical 分支
4. workflow-governance skill：Phase 2 分流增加第三档

**不做**：

- 不允许 mechanical task 改业务逻辑——这是不可商量的边界。
- 不允许自行声明 mechanical（必须经 planner 标注或 Phase 2 分流决策）。

**优先级**：P1（独立于 I-011/I-012，可单独落地）

---

### I-014 · backend.http 强制 integration test gate

**现状（ASR 重构多轮测试证据）**：

- ASR 模块是 WebSocket 服务端（`execution_profile: backend.http`）。
  用户在多轮测试中发现：没有任何 e2e / integration test 覆盖后端 handler。
- 当前 theking 只对 `web.browser` profile 强制 e2e-runner。
  `backend.http` 只要求 code-review + security-review，**不要求可执行的
  集成测试**。
- Phase 5 的验证手段（smoke.md + verification/ 目录）是**文本证据**，
  不是可执行测试。substantive ≥ 40 chars 的门槛太低——40 个字能写
  "启动成功，请求返回 200"，但不能证明"识别结果正确"。

**痛点**：

- 重构 core 层后，unit test 能保证 `NewRecognizer()` 的参数拼装正确，
  但无法保证"实际建一个 WS 连接、发一段音频、能收到识别结果"。
- WebSocket / gRPC / 流式 API 的 bug 几乎都出在**连接管理和协议交互**
  层面，unit test 盖不到。
- code-reviewer 和 security-reviewer 审的是代码质量，不是运行时行为。

**建议改进**：

`backend.http` profile 增加 integration test gate，分两个层级：

| 层级 | 适用范围 | 要求 |
|------|---------|------|
| L1: 连接级 | 所有 backend.http task | 能建连 + 合法响应（200/101）+ 正常断连 |
| L2: 业务级 | 改了核心逻辑的 task | 发真实/mock 请求 → 断言响应内容正确 |

落地范围：

1. `verification-strategy.md`：`backend.http` 的 required_verification
   增加 `integration-test` 条目
2. workflow-governance skill：Phase 4 步骤 5 和 Phase 5 步骤 3 增加
   `backend.http` 的集成测试要求
3. `validation.py`：`backend.http` 的 verification 目录下要求有
   `integration-test.md`（或 test.log 引用），substantive 内容必须
   包含至少一个 HTTP/WS 请求的输入-输出对
4. 不要求 Playwright——backend.http 的集成测试用语言原生测试框架
   （Go: `httptest.Server` + WS client; Node: supertest; Python: pytest + httpx）

integration-test.md 最低内容要求：

```markdown
## Integration Test Evidence

### Test Setup
- 启动命令: (实际命令)
- 环境: (test server / mock / real upstream)

### Covered Endpoints (至少 1 个)
- [ ] METHOD /path → 状态码 + 响应摘要

### Test Output
(粘贴 test 输出，或引用 test.log 路径)
```

**不做**：

- 不把 integration test 变成 e2e-runner agent 的职责——e2e-runner 是
  Playwright 专用（web.browser）。backend.http 的集成测试由 tdd-guide
  或主 agent 负责。
- 不要求所有 backend.http task 都达到 L2——L1 是最低要求，L2 是
  改核心逻辑时的追加要求。

**优先级**：P1（独立于其他议题，可单独落地）

---

## 落地路径建议（更新）

按"价值 / 工作量 / 证据充分度"三维排序：

- **I-004 测试/调研深度** ✅ 已落地于 sprint-002
- **I-005 architect 触发** ✅ 已落地于 sprint-002
- **I-007 已收尾 sprint 的增强路径** ✅ 已落地于 sprint-003
  惯例层 + 工具层（`seal-sprint` / `followup-sprint`）+ skill 文档层全部
  完成；约束机制是 `init-task` / `init-sprint-plan` 在 sealed sprint 上
  拒执，并配套 `followup-sprint` 自动反向链接。
- **I-002A Review 轮并发** ✅ 文档层已落地于 sprint-003
  Phase 4 步骤 7 现在显式说"同 round 内 reviewer 并发，跨 round 串行"。
  工具化（自动并发派单）仍是后续议题。
- **I-001 subagent 门槛** ✅ 已落地于 sprint-003
  planner / tdd-guide / refactor-cleaner / doc-updater / perf-optimizer
  的 description 现在带"何时应自跳过"的明示语；code-reviewer /
  security-reviewer / e2e-runner / architect 的独立人格保留不变。
- **I-008 task.md flow 字段集成测试** ✅ 已落地于 sprint-003
  顺手发现并修复了一个 `serialize_task_frontmatter` 静默丢失 `flow:`
  字段的 bug（sprint-002 引入但 sprint-002 没暴露）。集成测试现已锁
  定整条链路。
- **I-011 编译型语言 skeleton TDD** 🆕
  价值 极高 · 工作量 小 · 证据 充分（ASR 重构 Go 实例）
  → P0，下一个 sprint 优先落地
- **I-010 深度代码考古** 🆕
  价值 高 · 工作量 小 · 证据 充分（CodeBuddy proposal 对照）
  → P0，与 I-011 同 sprint 或紧接其后
- **I-013 三档 flow** 🆕
  价值 中高 · 工作量 中 · 证据 充分（ASR Stage 5/6 案例）
  → P1，需改 validation.py + constants.py + planner + skill
- **I-014 backend.http integration test** 🆕
  价值 中高 · 工作量 小 · 证据 充分（ASR 多轮测试无 e2e 暴露）
  → P1，独立落地，不依赖其他议题
- **I-012 Task Bundle** 🆕
  价值 高 · 工作量 大 · 证据 充分（ASR Stage 1+3 耦合案例）
  → P1，依赖 I-011；仅设计文档，实现排独立 sprint
- **I-003 轻量流程正反例**
  价值 中 · 工作量 小 · 证据 需要再积累 1-2 个 sprint → sprint-004 或更晚
- **I-009 `workflowctl new-adr` helper**
  价值 低 · 工作量 小 · 证据 sprint-002 review M2 → 等多 sprint 并发冲突再做
- **I-002B 多 active task**
  价值 高 · 工作量 大 · 证据 充分 → 独立 sprint，需要 workflowctl 设计
  改动
- **I-006 回归成本**
  价值 低 · 工作量 中 · 证据 当前无真实痛点 → 不做，继续观察

## 更新约定

- 每完成一个 sprint，如果涉及本文件议题，必须回本文件更新"现状"与"是否
  已落地"，而不是把结论藏在某个 sprint review 里。
- 新增议题时保留编号连续性（I-007, I-008…），已解决的议题不删除，改为
  标记 `✅ 已落地于 sprint-NNN`。
- 本文件不是 backlog，不做承诺；只做议题追踪。真正的承诺在 sprint plan。
