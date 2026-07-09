Here's your complete guide to using the Gridiron Developer Department UI.

Is it like Claude Code?
Yes, same concept — but instead of a CLI where you type commands, you get a web dashboard where you submit tasks and AI agents do the coding work, with you approving each step before anything gets committed.

Claude Code: you type → Claude codes → done (all in one shot)
Gridiron: you describe → AI plans → you approve → AI codes → you approve → done

The approval gates are intentional: the client spec says agents should never deploy or commit without human sign-off.

The 5 Pages and What They Do
1. Goals (/goals) — The Top Level
Use this when you have a big business goal, not a specific coding task.

Type something like: "Add a worker queue status dashboard to the admin panel"

The Executive Agent reads it, figures out what epics (big chunks of work) are needed, and creates them automatically. Think of it as your project manager's inbox.

2. Epics (/epics) — Big Feature Groups
An epic groups related tasks together. Example: "Queue Dashboard" epic might contain tasks for the backend endpoint, the frontend component, and the tests.

You can create epics manually here (title + description), or they get auto-created from a Goal.

Each epic shows its cost estimate and status (pending → planning → coding → ready for review → approved).

If an epic costs more than $1.00 (configurable), it pauses and waits for your approval before AI agents spend tokens on it.

3. Tasks (/tasks) — Individual Work Items
This is where the day-to-day action happens. A task is one specific thing: "Add /api/queue-status endpoint".

Filters at the top: all / pending / planning / coding / testing / blocked / completed / failed

Click any task to open the detail page.

4. Task Detail (/tasks/[id]) — The Control Panel
This is where you drive the AI. Here's what each button does:

Button	What it does
"Run Planning Pipeline (PM → Architect → Decompose)"	Full 3-agent planning: PM Agent understands the task, Architect picks the technical approach, Decomposer breaks it into subtasks. Takes ~2-3 min.
"Run Planner Agent (quick)"	Single-agent quick plan. Faster but less detailed. Good for simple tasks.
"Approve Plan & Start Coding"	After planning, you review the plan, then click this. Coder + QA agents start writing code in an isolated git worktree.
"Reject Pipeline Plan"	Plan wasn't right — agents go back to planning.
"Approve & Complete"	Code is done, you've reviewed the diff, mark it complete.
"Reject Diff"	Code wasn't right — agents retry (up to 3 times before it goes blocked).
5. Metrics (/metrics) — Dashboard
Shows token usage, cache hit rates, agent run counts, and per-epic cost breakdown. Useful for monitoring how much the agents are spending.

Step-by-Step Example: Real Task
Say you want to add a new API endpoint. Here's the exact flow:

Go to /tasks → type "Add a GET /api/worker-status endpoint that returns queue depth and active workers" → Submit

Click the task → click "Run Planning Pipeline" → wait ~2 min

Read the plan. Does it make sense? Click "Approve Plan & Start Coding"

Agents write the code in /tmp/gridiron-worktrees/<task-id>/ (isolated, not your main repo). They run tests, fix errors, retry up to 3 times.

Status changes to ready_for_review. You see the diff. If it looks good → "Approve & Complete". The worktree has your changes ready to merge.

You manually git cherry-pick or copy the changes into your main branch. (Deploy is always a human action — by design.)

What the Agents Actually Do (Simplified)

Your task description
        ↓
PM Agent         — "What does this task actually mean?"
        ↓
Architect Agent  — "Which files to touch, what pattern to use"
        ↓
Decomposer       — "Break into 3-5 subtasks"
        ↓
Coder Agent      — "Write the code" (reads real files, uses bash, edits files)
        ↓
QA Agent         — "Run pytest/mypy/ruff, fix failures, retry"
        ↓
Review Agent     — "Check code quality"
        ↓
Docs Agent       — "Update task log"
        ↓
YOU              — Final approve/reject
Right now it runs on Groq/Qwen (free tier, slower). When you add an ANTHROPIC_API_KEY to backend/.env and set USE_GROQ=false, it switches to Claude Sonnet/Haiku (faster, better code quality).





Simple Answer — What Actually Happens
When you type:

"Add a GET /api/worker-status endpoint that returns queue depth and active workers"

Here is exactly what the system does, step by step:

Step 1 — PM Agent reads your request
It figures out: "OK, the user wants a new HTTP endpoint. It should return two things: how many tasks are waiting, and how many agents are currently running."

Step 2 — Architect Agent looks at your code
It opens real files in your project, reads how existing endpoints are written (like /api/tasks), and decides: "We should add this in backend/app/api/ and register it in main.py."

Step 3 — Decomposer breaks it into subtasks
Example subtasks it might create:

Create backend/app/api/worker_status.py
Add the route to backend/app/main.py
Write a test in backend/tests/
Step 4 — Coder Agent actually writes the files
It opens backend/app/api/tasks.py, copies the pattern, and writes new Python code into the new file. Real code, in your real repo.

Step 5 — QA Agent runs your tests
Runs pytest backend/tests/ and mypy. If it fails, it reads the error, fixes the code, and tries again (up to 3 times).

Step 6 — You approve or reject
You see the diff (what changed). If it looks good, you click Approve.

Which Project Does It Edit?
It edits THIS project — /home/pc-117/Documents/CRR2906 — because that's what's set in backend/.env:


TARGET_REPO_PATH=/home/pc-117/Documents/CRR2906
But it does NOT edit the files directly. It makes a copy (called a git worktree) in /tmp/gridiron-worktrees/<task-id>/. The agents work inside that copy. Your main code is untouched until you manually approve and copy the changes over.

Want to point it at a DIFFERENT project?
Change one line in backend/.env:


TARGET_REPO_PATH=/home/pc-117/Documents/your-other-project
Then the agents will read and edit THAT project instead. That's the real use case — you'd point it at a client project, a different app, etc.

So right now it would edit... itself?
Yes — if you run the task right now, the agents will read the Gridiron backend code and add the /api/worker-status endpoint to the Gridiron project itself. That actually makes sense as a first test — it proves the whole pipeline works end to end on a real codebase.


No — it works on a local folder on your machine, not directly from GitHub.

How it actually works:

GitHub repo
    ↓
You clone it to your computer
  git clone https://github.com/yourcompany/your-app
    ↓
You set TARGET_REPO_PATH in backend/.env
  TARGET_REPO_PATH=/home/pc-117/Documents/your-app
    ↓
Agents read and edit files from that local folder
The agents never touch GitHub. They only read/write local files.

The full real-world workflow would be:
Clone your project: git clone <github-url>
Set TARGET_REPO_PATH to that cloned folder
Submit a task in the UI
Agents plan + write code in a temp copy (/tmp/gridiron-worktrees/)
You review the diff in the UI and approve
You manually run git commit + git push to GitHub
Step 6 is always human — the system is designed to never auto-push to GitHub. That's a safety rule in the client spec.

Currently there is no "give it a GitHub URL" feature built yet
That would be a natural next feature — a form where you paste a GitHub URL, it clones it, sets the path, and you're ready to submit tasks. But right now you have to clone it manually and update the .env file.