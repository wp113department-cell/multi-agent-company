# AI Developer Agent System — Documentation Suite
### Index & Reading Guide

**Project:** Gridiron AI — Developer Department (the first application built on Gridiron's eventual multi-department AI Workforce, per `ai-developer-agent-blueprint.md`)
**Status:** Pre-build / Stage 0
**Last updated:** This document set is the source of truth. If anything in conversation history conflicts with these files, these files win.

---

## How to read this suite

**If you're the client:** read `01`, `03`, and `15` first. That gives you the business case, the timeline, and what you'll actually see on screen. Everything else is engineering detail you can dip into as needed.

**If you're an engineer joining the project:** read in numeric order. Each document assumes the ones before it. By the end of `09` you can start writing code. `10` onward covers subsystems you'll build into starting at Stage 3.

**If you're using these files to actually build the system:** every document below is self-contained enough to hand to an engineer (human or AI-assisted) as a spec for their piece of the system, but cross-references the others so nothing contradicts.

---

## A note on scope, before you read further

The original 20-document proposal called for each document to run 20–50 pages of enterprise-depth content. That would mean writing detailed Kubernetes scaling policies, formal compliance documentation, and multi-region disaster recovery plans for infrastructure that doesn't exist yet, for a system that hasn't shipped Stage 0. We're not doing that, for the same reason the architecture itself isn't being over-built ahead of need (see `05_Architecture_Decision_Records.md`, ADR-009): writing speculative enterprise documentation now produces content that looks impressive but will be wrong by the time it's relevant, and it would have taken time away from documentation that's actually usable today.

Every document below covers everything in the original 20-document list — nothing is missing. Where a topic is genuinely premature (multi-region infra, formal compliance certification, a dedicated Kubernetes scheduler), the document says so explicitly, explains what's right-sized for now instead, and states the trigger condition for when to expand it. That's a deliberate choice, not an omission.

---

## Document Tree

| # | Document | Covers | Primary Audience |
|---|---|---|---|
| 01 | [Vision & Product Requirements](01_Vision_Product_Requirements.md) | Why this exists, what success looks like, what's in/out of scope | Client + Engineers |
| 02 | [System Architecture Blueprint](02_System_Architecture_Blueprint.md) | Full technical architecture, tech stack, platform diagram | Engineers |
| 03 | [Technical Execution Roadmap](03_Technical_Execution_Roadmap.md) | Stage-by-stage build plan, team size, timeline | Client + Engineers |
| 04 | [Engineering Standards & Conventions](04_Engineering_Standards_Conventions.md) | Coding rules, folder structure, git workflow, definition of done | Engineers |
| 05 | [Architecture Decision Records](05_Architecture_Decision_Records.md) | Why each major technical choice was made | Engineers |
| 06 | [Agent SDK Specification](06_Agent_SDK_Specification.md) | The interface every agent (Backend, QA, Reviewer, etc.) must implement | Engineers |
| 07 | [Tool / MCP Specification](07_Tool_MCP_Specification.md) | How agents access filesystem, git, database, web — via MCP | Engineers |
| 08 | [API Specification](08_API_Specification.md) | Every REST endpoint, request/response shape, auth | Engineers |
| 09 | [Database Design Specification](09_Database_Design_Specification.md) | Every table, relationship, index, migration approach | Engineers |
| 10 | [Repository Intelligence Specification](10_Repository_Intelligence_Specification.md) | The codebase-understanding subsystem (AST graph, Context Builder) | Engineers |
| 11 | [Memory System Specification](11_Memory_System_Specification.md) | Short-term task state vs. long-term Engineering Memory | Engineers |
| 12 | [Event Bus Specification](12_Event_Bus_Specification.md) | Event types, schema, how agents communicate | Engineers |
| 13 | [Policy Engine Specification](13_Policy_Engine_Specification.md) | Approval rules, safety rules, as executable config | Engineers |
| 14 | [Scheduler Specification](14_Scheduler_Specification.md) | How tasks get queued, prioritized, and concurrency-capped | Engineers |
| 15 | [Mission Control Dashboard Specification](15_Mission_Control_Dashboard_Specification.md) | Every screen, widget, and what each stage adds to the UI | Client + Engineers |
| 16 | [Observability Specification](16_Observability_Specification.md) | Logging, error tracking, metrics | Engineers |
| 17 | [Security Handbook](17_Security_Handbook.md) | Secrets, auth, sandboxing, audit, incident response | Engineers |
| 18 | [Deployment & Infrastructure Guide](18_Deployment_Infrastructure_Guide.md) | How and where the system runs | Engineers |
| 19 | [Operations Runbook](19_Operations_Runbook.md) | What to do when something goes wrong, day to day | Engineers (on-call) |
| 20 | [Testing Strategy](20_Testing_Strategy.md) | Unit, integration, agent-evaluation, and E2E testing approach | Engineers |

---

## Cross-reference map

Every document references the stage (0–7) at which it first becomes relevant, using the stage numbers defined in `03_Technical_Execution_Roadmap.md`. If a document mentions a component (Event Bus, Policy Engine, Agent Registry, etc.), that component is fully specified in its own numbered document — nothing is defined in two places with two different answers.

## Source of truth

These 20 documents formalize and supersede the standalone `ai-developer-agent-blueprint.md` delivered earlier — that file's content has been split and expanded across `01`, `02`, and `03` here. Keep `ai-developer-agent-blueprint.md` as a historical reference; treat this folder as current.
