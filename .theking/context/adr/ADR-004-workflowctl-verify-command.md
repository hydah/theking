# ADR-004: workflowctl verify — 把"亲勘实证"的命令执行与证据落盘从主 agent 手里收回

## Context

Phase 4 步骤 5（亲勘实证）目前由主 agent 手工编排四件事：

1. **想验证命令**——按画像（web.browser / backend.http / backend.cli / backend.job）
   挑一条或几条命令。
2. **跑命令**——在 shell 里执行。
3. **把 stdout/stderr 复制粘贴**到 `verification/<profile>/evidence.md`，
   通常套一段 `## <acceptance-section>` 的 markdown 骨架（骨架见
   `templates/skills/skill_workflow_governance.md.tmpl` Phase 4 步骤 5
   的「证据合并（推荐模式）」块）。
4. **命令输出 2–5 KB 原始文本**流进主 agent 的 context，占掉后续推理
   的 token 预算。

观察到的问题：

- **Context 污染**：voiceagent / sprint-004 这种 backend.http × 多 task 的 sprint，
  一个 sprint 跑下来光 verify 命令的 stdout 就能吃掉 20–40 KB 主 agent context，
  把叩阙 / 内阁奏对阶段的有效信息挤出窗口。
- **格式漂移**：evidence.md 的骨架是文档推荐模式、不是强制契约。sprint-001/002/003
  的 evidence 文件已经出现 `### acceptance-N` vs `## ...` vs 纯 fenced block 三种
  形态。`has_substantive_verification_evidence` 只看字符数，不看结构，导致审计时
  grep `^## ` 聚不齐。
- **agent-runs.jsonl 形同虚设**：该 ledger 规定了 7 个必填字段
  （timestamp/agent/purpose/input_artifact/output_artifact/status/notes，见
  `validation.py::AGENT_RUN_LEDGER_REQUIRED_FIELDS`），但没有一条写入路径是
  工具自动产生的——主 agent 不会在跑完一条命令后主动 append；sprint-001..004
  的所有 task ledger 要么不存在要么是人肉补的。Phase 5 审计链缺这一环。
- **失败事实被吞**：命令 exit≠0 时，主 agent 经常只记录"失败了"一句话就开始
  debug，原始 stderr 要么只进 context 不落盘、要么被下一轮 tool call 冲掉。
  fresh verification evidence 的可追溯性破防。

相关工件：

- `scripts/workflowctl.py`（子命令 dispatcher、`handle_check` /
  `handle_sprint_smoke` 模式）
- `scripts/validation.py`（`has_substantive_verification_evidence`、
  `substantive_text_length`、`AGENT_RUN_LEDGER_REQUIRED_FIELDS`、
  `SUBSTANTIVE_EVIDENCE_MIN_CHARS = 40`）
- `templates/skills/skill_workflow_governance.md.tmpl` Phase 4 步骤 5
  「证据合并（推荐模式）」
- ADR-003 硬规则 #9（substantive evidence gate） — 本 ADR 的父契约

## Decision

新增 `workflowctl verify` 子命令，**一次调用 = 跑一条命令 + 写一段
substantive evidence + 记一条 ledger**。主 agent 不再触碰 evidence.md 的
markdown 骨架，也不再把命令原始输出带进 context。

### 1. 命令形态

```
{theking_cmd} verify \
    --task-dir <T> \
    --profile <P> \
    --command "<CMD>" \
    --evidence-section <NAME> \
    [--shell /bin/bash] \
    [--cwd <PATH>] \
    [--timeout <SECS>] \
    [--tail-lines <N>] \
    [--head-lines <M>]
```

**采用**这个形态，理由：

- `--task-dir` + `--profile` 是 theking 既有坐标系，和 `check` / `advance-status`
  / `init-review-round` 完全一致，没有新的身份概念。
- `--command` 用单字符串（通过 `--shell` 指定的 shell 解析），而不是 argv 数组。
  主 agent 本来就是"想一条 shell 命令"，argv 形态会强迫它二次拆分，徒增错误面。
- `--evidence-section` 是必填，对应 evidence.md 里的 `## <NAME>` 节；这是
  把"acceptance 条目 ↔ 证据段落"这条 traceability 落到 CLI 层的唯一办法。
  命名空间由 task 自己管（建议与 spec.md Acceptance 的证据路径一致）。
- `--cwd` / `--timeout` 是操作必需；默认 `--cwd = task-dir 的 repo root`、
  `--timeout = 300s`（命令超时按 exit 124 记录，不挂死 verify 本身）。
- `--tail-lines` / `--head-lines` 控制**返回给主 agent** 的摘要截取长度，
  见 §2。默认 `--head-lines 20 --tail-lines 40`。

**拒绝的分解方案**：`verify-run` + `verify-append` 两段式（主 agent 先跑后记）。
拒绝理由：两段式之间主 agent 仍会看到原始输出，context 污染一分没少，还
多一次 tool call。

**sprint 级坐标**：本 sprint **不**支持 `--sprint-dir` 形式。sprint 级 verify 的
需求（冷启动联调、跨 task 集成）目前由 `sprint-smoke` 承担，它不执行命令、只
核查已有证据。把"跑 sprint 级命令"塞进 verify 会让 verify 同时承担
task/sprint 两种坐标系，违反 `check` / `sprint-check` 的一级切分。若将来
sprint 级需要同等能力，走 `workflowctl sprint-verify` 独立入口，followup 再
起 ADR。

### 2. 输出策略（两层：返回主 agent + 落盘 evidence.md）

**返回给主 agent 的内容（stdout）**：一个 ≤ 400 字符的单行 JSON：

```json
{"status":"ok","exit":0,"duration_ms":1204,"substantive_chars_appended":186,
 "section":"acceptance-1-happy-path","evidence_path":"verification/backend-http/evidence.md",
 "head":"listen on :7123\nREADY\nGET /health 200 ...","tail":"... req_id=abc OK\nexit 0"}
```

- `head` / `tail` 是从命令 **stdout+stderr 合并流** 中截取的前 N 行 / 末 M 行
  （默认 20/40），`\n` 转义后嵌入；若合并流总行数 ≤ N+M，则整段返回、`tail`
  省略。经验值 20/40 在 sprint-001..004 的实际证据里覆盖 >90% 有信息密度的片段
  （启动 banner 在 head，断言/退出在 tail）。
- 失败时 `status="command_failed"` + 附 stderr 的 tail（额外截最后 20 行）。
- verify 本身的错误（路径不存在、profile 非法、写入失败）用 `status="verify_error"`
  + 明确的 reason 字符串，不塞 head/tail。

**不把完整 stdout 返回主 agent**。主 agent 要看详细内容时，读 evidence.md
就行——那本来就是它的写作成果。

**落盘到 evidence.md 的格式**：统一为

```markdown
## <section>

<!-- theking:verify section=<section> run=<iso8601> exit=<N> duration_ms=<N> -->

```shell
$ <command>
```

```text
<stdout+stderr merged, truncated according to §3>
```

exit: <N>
run: <iso8601 UTC>
duration: <ms>
```

选这套格式的理由：

- `##` 节标题与现有「证据合并（推荐模式）」推荐骨架一致，旧手写 evidence 不
  break（见 §Migration path）。
- 机器可读元数据放 HTML 注释里，`substantive_text_length` 会把整行 HTML
  注释剥掉，不污染 40 字符门槛。
- `$ <command>` 前缀是 Unix 传统，人类扫一眼就知道这是执行记录。
- 用 fenced code block 包 shell 和输出，md 渲染友好，grep `^exit: ` 做
  "有多少次验证" 统计也容易。

### 3. 大输出的处理（分层落盘）

命令输出按体积分三档，不做一刀切：

- **≤ 8 KB**：整段进 evidence.md 的 `text` fenced block。
- **8 KB – 100 KB**：evidence.md 里只保留 `head 20 行 + "... (truncated,
  full log: .raw/<section>-<ts>.log) ..." + tail 40 行`；**完整流**落到
  `verification/<profile>/.raw/<section>-<ts>.log`。
- **> 100 KB**：evidence.md 里只保留 head 10 行 + tail 20 行 + 明确警告
  "输出过大，请拆分命令或改用日志文件输出"；完整流仍落 `.raw/`。

`.raw/` 目录**不计入** `has_substantive_verification_evidence` 的字符统计
（validator 要新增 skip `.raw/` 的逻辑；否则一条 80 KB 的日志会让门槛形同虚设，
起不到"实质文字"的意义）。`.raw/` 进 git 还是 `.gitignore`，由项目自选，
theking 默认不碰——它是审计日志，不是可交付物。

### 4. 幂等与重跑：append，不 replace

**同一 `--evidence-section NAME` 反复 verify 一律 append**，每次追加一个带
时间戳的新条目块。理由：

- replace 会丢失历史——而 Phase 4 步骤 5 → 驳回重议分支 d（"重跑基础验证"）
  的正确审计语义就是"能看到前后两次证据的对比"。replace 把 red→green 的
  修复过程抹掉了。
- append 配合 HTML 注释里的 `run=<iso8601>`，审计时能复盘"这个 section
  最后一次跑是什么时候"；replace 只能靠 git log。
- `has_substantive_verification_evidence` 按目录聚合字符数，append 不会
  重复计分导致膨胀——它只 care 实质文字总量。

同一 section 的多次 append 之间**不插入 section 标题**（即不会出现
`## foo` 两次），而是在同一 `## <section>` 下追加 `### run <iso8601>` 子
标题 + 本次 block。保持 section 唯一，便于 grep 定位。

### 5. exit code 传播：verify 本身的成败与被包装命令的成败分开

- 被包装命令成功（exit 0）：verify exit 0，json `status=ok`。
- 被包装命令失败（exit ≠ 0）：**verify exit 0**，json `status=command_failed`
  + 带上被包装命令的 exit code。
- verify 本身出错（路径不存在、写失败、substantive gate 拒绝）：
  **verify exit ≠ 0**，json `status=verify_error`。

选"verify exit 0 / status=command_failed"的理由——这是本 ADR 最容易被误解的
一点：

- verify 的契约是"**把一次命令执行的事实记录下来**"。命令失败是**记录成功**
  的事实之一。evidence.md 已经忠实落盘了失败，这就是 verify 的 happy path。
- 如果 verify 跟随被包装命令 exit，主 agent 会把 verify 的 exit 当作流程
  信号，倾向于"命令失败 = 回避 verify"，结果失败事实不落盘——正是当前痛点。
- 主 agent 的判断依据是 json 的 `status` 字段，不是 verify 的 exit。exit
  只区分"这次 CLI 调用有没有写进文件"。
- 真的想"命令失败就让 CI fail"的场景（极少），调用方显式 `jq -e 'exit == 0'`
  即可；不是 verify 的职责。

### 6. 与 substantive-evidence gate 的关系：verify 内部先校验后 append

verify 在 append 之前**必须**自检"本次写入是否能让 evidence.md 通过
`has_substantive_verification_evidence`"：

- 构造预演：读现有 evidence.md（若有）→ 拼接本次 block → 跑 substantive
  字符数统计 → 若 ≥ 40，append；若 < 40，**仍然 append**，但 json
  `status` 标 `ok_under_threshold`，附 `substantive_chars_total=<N>`。
- **verify 不拒绝 < 40 的写入**。理由：单次命令输出短（如 `curl -sf` 只 fail
  exit code）是正常的，拦在 verify 会鼓励主 agent 用无意义文本凑字数；
  而 `check` 在 `ready_to_merge` / `done` 时本来就会把关。让 verify 做信息
  层反馈（"你现在总共才 23 字符，再补一次"）而不是把关，职责更清。
- HTML 注释和纯 `##` 标题都会被 `substantive_text_length` 剥掉。`$ <cmd>`
  这行不会被剥（不在剥除规则里），提供基础字符。所以一次真实命令 + 一行输出
  基本稳过 40。

### 7. agent-runs.jsonl 自动写入

每次 verify 成功调用（无论 command 是否成功），**自动 append** 一行到
`<task-dir>/agent-runs.jsonl`：

```json
{"timestamp":"2026-05-10T14:22:03Z",
 "agent":"workflowctl-verify",
 "purpose":"evidence capture: <section>",
 "input_artifact":"<command>",
 "output_artifact":"verification/<profile-dir>/evidence.md#<section>",
 "status":"command_ok|command_failed|command_timeout",
 "notes":"exit=<N> duration_ms=<N> substantive_delta=<N>"}
```

七个字段全覆盖 `AGENT_RUN_LEDGER_REQUIRED_FIELDS`，`validate_agent_runs_ledger`
现成校验。`purpose` / `input_artifact` / `output_artifact` 用固定模板生成，
主 agent 不需要也不应该手写。

verify 自身出错（exit ≠ 0）**不写 ledger**——ledger 的语义是"某 agent 干过
某件事"，verify 都没干成，写了是噪音。

## Consequences

### Positive

- **主 agent context 占用下降**：sprint 级实测估算，把原来 20–40 KB 的
  stdout 回流压到 <2 KB 的 JSON 摘要（head 20 行 + tail 40 行 × N 次），
  下降 ≥ 80%。叩阙 / 内阁阶段的决策密度回升。
- **evidence.md 格式统一**：`## <section>` + HTML 注释元数据 + fenced
  code block 三件套，审计 grep / downstream 工具（如 sprint 报表生成器）
  可靠地解析。
- **agent-runs.jsonl 从死档变活档**：每次 verify 自动留痕，Phase 5 的
  "这个 task 到底跑过哪些命令" 变成 `jq` 一问的事。
- **失败事实不再被吞**：verify 把 command_failed 作为 happy path 落盘，
  主 agent 不再有"回避写失败"的激励。
- **与硬规则 #9 / ADR-003 同向加固**：不是替代 substantive gate，而是把
  "产生 substantive evidence 的动作"本身工具化，降低主 agent 偷懒的便利。
- **Completion 语言纪律（Phase 4 步骤 5 的"🚫 Red flags"）天然对齐**：
  主 agent 报告"should work now"前必须先跑 verify 拿到 fresh evidence，
  而 verify 的 JSON 摘要就是它能复述的"实际输出"。

### Negative

- **CLI surface 扩大**：多一个子命令，agent 目录表、README command index、
  skill 模板的命令映射表都要加一行。**缓解**：本 ADR 一次性定型，不留待
  后续增补的 flag 空位（head/tail 默认值已经给了，不加 `--quiet`
  `--json-only` 这种扩展面）。
- **完整输出沉到 `.raw/`，偶有用户想看"刚才到底完整输出了啥"需要打开日志
  文件**。**缓解**：JSON 摘要里带 `evidence_path` 和（若有）`raw_log_path`，
  主 agent 可直接 `read_file` 读——这本来就是 IDE workflow 友好路径。
- **sprint 级不做**留了口子。**缓解**：当前 sprint-smoke 对跨 task 联调证据
  的覆盖够用；sprint-verify 作为 followup 单独决策（不预占）。
- **幂等策略选 append 而非 replace**，驳回重议轮次多的 task 的 evidence.md
  会变长。**缓解**：每轮 append 有 `### run <iso8601>` 子标题分割，肉眼扫读
  不难；审计对象是"历史对比"本身。

### Neutral

- 已 `done` / `sealed` 的 sprint 不追溯。老 evidence.md 的手写格式继续读得动，
  见 Migration path。
- 本 ADR 不强制主 agent 必须用 verify——它只是强推荐。Phase 4 步骤 5 的
  skill 正文建议"优先使用 `workflowctl verify`，特殊场景（需要交互输入、
  长驻 server、需要截图）再手工落盘"。硬规则 #9 本身管"有没有 substantive
  evidence"，不管是通过 verify 还是手写。

## Alternatives Considered

- **只改 skill 文档，让主 agent 自己规范化 evidence.md 格式，不加 CLI**：
  拒绝。skill 文本已经推荐过 `## <section>` 模板（见 Phase 4 步骤 5「证据
  合并（推荐模式）」），实操里三种以上的变体照样出现。"AI 会按文档来" 和
  "AI 会按代码来" 不是一个量级的保证。ADR-003 已经用过一次同款决策（placeholder
  检测不做 LLM 语义校验而做黑名单）——这是同一条理由。
- **用 pre/post hook 代替独立子命令**（例如 `workflowctl check --before-cmd
  '<CMD>'`）：拒绝。check 的语义是"只读校验"，叠上执行权威会让它不再幂等、
  `make check` 这种循环 CI 调用会产生副作用。坚持动词分工：check 只读 /
  verify 写证据 / advance-status 推状态。
- **让 verify 在 command 失败时 exit 非 0**：拒绝，见 §5 详述。
- **幂等用 replace（单 section 只保留最新一次）**：拒绝。审计要的是
  red→green 的对比，replace 抹掉的正是"我修过什么"这条信号。
- **把 JSON 摘要改成 YAML / 人类可读文本**：拒绝。主 agent 解析 JSON 是
  一等公民能力，YAML 多缩进歧义、人类可读文本要自然语言 parse——两者都
  比 JSON 更容易让主 agent 误读。
- **`--evidence-section` 改为可选、缺省落到 `misc`**：拒绝。acceptance 条目
  ↔ 证据段落的对应是 ADR-003 `validate_acceptance_traceability` 的要求，
  verify 作为产生证据的入口必须强制这层 mapping；默认 `misc` 会让 AI 永远
  不填 section，traceability 即刻失效。

## Migration path

**必须兼容旧手写 evidence.md，不 break 任何已 sealed sprint。**

- `has_substantive_verification_evidence` **不改**：verify 写出的新格式仍然
  按目录聚合 substantive 字符数，等价于旧手写格式。
- `validate_verification_layout` **不改**：继续只看 profile 目录下的
  substantive 字符总数。verify 的存在对 validator 透明。
- 旧 evidence.md（自由格式、只有 fenced block、没有 `## <section>`）
  继续通过校验。verify 遇到"已有 evidence.md 但没有 `## <section>` 标题"
  的文件时：
  - 在文件末尾 append `## <section>` + 本次 block，**不**改写已有内容；
  - JSON 摘要里附 `notes:"appended to legacy-format evidence.md"` 提示。
- `.raw/` 目录是新造产物，旧 sprint 不存在。validator 新增的 "skip `.raw/`"
  对旧 sprint 是 no-op。
- agent-runs.jsonl 的 ledger schema 不变，沿用 `AGENT_RUN_LEDGER_REQUIRED_FIELDS`。
  旧的手写 ledger 和 verify 自动写的 ledger 混存，`validate_agent_runs_ledger`
  已经按行逐条校验，完全兼容。
- skill 模板 Phase 4 步骤 5「证据合并（推荐模式）」正文**保留**，在其下方
  补一段"🛠️ 工具化路径：`workflowctl verify` 自动产出这套骨架，推荐优先使用"，
  手写路径留作 escape hatch（交互命令 / 截图证据 / 长驻 server）。

## Status

Proposed — 实现拆 task 时参考 ADR-003 的闸 1/2/3 切分方式：`verify` 子命令本体
一个 task、`.raw/` skip + validator 兼容一个 task、skill 文案与 agent-runs
ledger 模板一个 task。
