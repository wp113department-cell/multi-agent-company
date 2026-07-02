# SWE-Agent — Architectural Reference Notes

Source: `/repos/swe-agent/sweagent/types.py`

## Core Types

```python
class StepOutput(BaseModel):
    query: str           # what the agent was asked
    thought: str         # agent's reasoning
    action: str          # the tool call / command
    output: str          # raw output from execution
    observation: str     # processed observation returned to agent
    execution_time: float
    done: bool
```

```python
class TrajectoryStep(TypedDict):
    action: str
    observation: str
    response: str
    state: str
    thought: str
```

```python
class HistoryItem(TypedDict):
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    agent: str  # which agent produced this
```

## Trajectory Logging Pattern

- Full trajectory is a list of `TrajectoryStep` dicts saved to JSONL
- Every action + observation pair is recorded — enables replay and debugging
- `HistoryItem` includes `agent` field for multi-agent attribution

## What Gridiron Borrows

- **Per-step structured logging**: our `task_logs` table captures action/result but lacks `thought` field — adding it would improve auditability
- **`done` flag on step output**: our agent loop uses `AgentDoneSignal` exception; a return value flag is cleaner
- **Agent attribution in log entries**: our `task_logs.category` is coarse — an `agent_id` field would support multi-agent tasks
- **JSONL trajectory files**: for long-running tasks, writing a trajectory file alongside DB logs gives a human-readable audit trail

## What We Do Differently

- We use Postgres + structured categories, not JSONL files — better for querying and dashboards
- Our agents are stateless functions (no class with persistent state) — simpler to reason about
- SWE-Agent targets GitHub issue resolution; Gridiron targets arbitrary dev tasks in a live repo
