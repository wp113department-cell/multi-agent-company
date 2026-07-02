# AutoGen Architecture Notes — Phase 4 Reference

Source: `/home/pc-117/Documents/CRR2906/repos/autogen/python/packages/autogen-agentchat`

## Agent Messaging Pattern

AutoGen agents communicate exclusively through **typed messages**, not direct function calls:
- `TextMessage`, `ToolCallMessage`, `ToolCallResultMessage`, `HandoffMessage`
- Every agent receives messages and produces messages — no shared mutable state
- This decoupling is what our Event Bus replicates at a higher level

## Group Chat / Team Patterns

AutoGen has three team coordination patterns:
1. **RoundRobinGroupChat** — each agent gets a turn in order (simple, predictable)
2. **SelectorGroupChat** — an LLM selector decides which agent speaks next based on the conversation
3. **MagenticOneGroupChat** — orchestrator plans, delegates, tracks progress of sub-agents

The SelectorGroupChat pattern maps closest to our Dispatcher: given a task type, select the right specialist.

```python
# AutoGen SelectorGroupChat concept (reference only, not ported)
team = SelectorGroupChat(
    participants=[backend_dev, frontend_dev, qa_agent],
    model_client=...,
    selector_prompt="Route to the right specialist based on task type."
)
```

Our Dispatcher is simpler and deterministic: `subtask.type → agent function` (no LLM needed for routing).

## Agent Lifecycle

AutoGen `BaseChatAgent`:
- `on_messages(messages, cancellation_token)` — async, receives message list, returns `Response`
- `on_reset(cancellation_token)` — resets internal state between tasks
- Agents are stateless between `on_messages` calls by default

Maps to our `run_agent()` in `base.py`: stateless, takes messages list, returns `(text, tokens_in, tokens_out)`.

## Event/Message Bus Patterns

AutoGen's core uses `TypeSubscription` pattern:
- Agents subscribe to topic types: `runtime.add_subscription(TypeSubscription("topic_type", "agent_id"))`
- Publisher sends typed messages to topics: `runtime.publish_message(msg, topic=TopicId("topic_type", ...))`
- Subscribers receive all messages for their subscribed topics

This is the architecture behind our `event_bus/bus.py`:
- `subscribe(event_type, handler)` — registers a handler function for an event type
- `publish(event)` — finds all handlers for `event.event_type` and dispatches

## Key Lessons for Gridiron

1. **Message-passing decouples agents** — no agent calls another directly. All communication is via events.
2. **Topic-based routing** — subscribe by event type, not by sender. Makes adding new consumers zero-change.
3. **Stateless agents** — agent functions receive full context each time; state lives in LangGraph checkpointed state.
4. **Cancellation tokens** — AutoGen uses explicit cancellation. Our equivalent: `max_retries=3` cap + `blocked` status.
5. **Event ordering per task** — AutoGen doesn't guarantee global message ordering but task-level ordering is natural since a task's messages flow sequentially through the pipeline. Same as our spec.
