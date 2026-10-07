# Project owner rule: check every affected feature

Before completing any change, trace the changed identifiers, endpoints and
data relationships through the repository. Update every affected consumer
in the same change, including related pages, project selectors, APIs,
database relationships, background jobs, tests, documentation, the guided
tour and Windows launchers when applicable.

A feature is incomplete if it works on its own page but leaves another
page showing stale data or a broken action. For example, deleting a project
must also remove it from project selectors in Tasks, Roadmap and Chat while
preserving the promised files and task history.

Verify the affected user flows and report what was checked. Distinguish
local or Docker validation from native Windows validation, and simulated
demo actions from real AI execution.
