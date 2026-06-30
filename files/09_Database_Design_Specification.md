# 09 — Database Design Specification

**Applies from:** Stage 1, expanded each stage
**Related:** `02_System_Architecture_Blueprint.md`, `08_API_Specification.md`

---

## Engine

PostgreSQL throughout (see `05`, ADR-005). pgvector extension added at Stage 3 for embeddings, in the same instance until Qdrant is introduced at Stage 3+ scale.

## Core Tables (Stage 1)

```sql
dev_tasks (
  task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  description TEXT,
  priority TEXT CHECK (priority IN ('low','medium','high')),
  status TEXT CHECK (status IN ('pending','planning','coding','testing','blocked','completed','failed')),
  assigned_agent TEXT,
  project TEXT,
  files_touched JSONB DEFAULT '[]',
  plan TEXT,
  final_summary TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

task_logs (
  log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID REFERENCES dev_tasks(task_id) ON DELETE CASCADE,
  category TEXT, -- created, planning, repo_analysis, files_inspected, error, warning, summary
  message TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

agent_runs (
  run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID REFERENCES dev_tasks(task_id) ON DELETE CASCADE,
  agent_type TEXT,
  status TEXT,
  checkpoint_id TEXT,
  started_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ
);
```

## Stage 3 Additions

```sql
embeddings (
  embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type TEXT, -- code_summary, doc, past_task
  source_ref TEXT,
  content TEXT,
  vector VECTOR(1536),
  created_at TIMESTAMPTZ DEFAULT now()
);
```

## Stage 4 Additions

```sql
artifacts (
  artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID REFERENCES dev_tasks(task_id) ON DELETE CASCADE,
  type TEXT, -- plan, patch, test_results, review_findings
  version INT DEFAULT 1,
  storage_path TEXT,
  created_by_agent TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

events (
  event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type TEXT,
  task_id UUID,
  payload JSONB,
  emitted_by TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

## Stage 5 Additions

```sql
epics (
  epic_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  goal TEXT,
  status TEXT,
  estimated_cost NUMERIC,
  actual_cost NUMERIC,
  estimated_tokens INT,
  created_at TIMESTAMPTZ DEFAULT now()
);

policies (
  policy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trigger_pattern TEXT,
  required_approval_role TEXT,
  blocking BOOLEAN DEFAULT true,
  active BOOLEAN DEFAULT true
);
```

## Stage 6 Addition

```sql
agents (
  agent_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT,
  type TEXT,
  version TEXT,
  capabilities TEXT[],
  tools TEXT[],
  prompt_ref TEXT,
  owner TEXT,
  success_rate NUMERIC,
  avg_retries NUMERIC,
  last_updated TIMESTAMPTZ DEFAULT now()
);
```

## Relationships

`dev_tasks` is the central record; `task_logs`, `agent_runs`, and `artifacts` all reference it. `epics` (Stage 5) groups multiple `dev_tasks` together via a `epic_id` foreign key added to `dev_tasks` at that stage. `events` reference `task_id` loosely (nullable, since some events are epic- or system-level, not task-level).

## Indexes

`dev_tasks(status)`, `dev_tasks(project)`, `task_logs(task_id, created_at)`, `agent_runs(task_id)`, `embeddings` uses an IVFFlat or HNSW index on `vector` once row counts justify it (not needed at Stage 3 launch volume).

## Migration Strategy

A single migration tool (e.g., `node-pg-migrate` or Prisma Migrate) with versioned, checked-in migration files — no manual schema changes against any environment. Every stage's "Additions" above corresponds to one migration, run in CI before deploy.

## Backups

Stage 1–6: rely on the hosting provider's (Supabase or equivalent) automated daily backups with point-in-time recovery — sufficient for an internal tool at this scale. A custom backup/disaster-recovery strategy (cross-region replication, formal RPO/RTO targets) is deferred until Stage 7+ production load justifies the operational cost — see `18_Deployment_Infrastructure_Guide.md`.
