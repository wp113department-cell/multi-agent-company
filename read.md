# AI ENGINEERING MASTERY PROGRAM — v2
### Master Plan (All 6 Volumes, Date-Wise) + Cross-Cutting Tracks + Complete Volume 1 Curriculum
**Student start date: Tuesday, 14 July 2026**
**Schedule: Mon–Thu = Learning | Friday = Revision + Assessment + Mock Interview | Sat–Sun = OFF**
**Daily time: 1 hr theory + 1–2 hrs practical (after work)**

---

# PART 1 — MASTER PLAN (VOLUME-WISE, DATE-WISE)

| Volume | Title | Duration | Dates | Exit Test (taken with me) |
|---|---|---|---|---|
| **1** | AI Engineering Foundations (Python, CS, Linux, Git, SQL, Math) | 4 weeks | **Tue 14 Jul – Fri 7 Aug 2026** | Volume 1 Test: Python + CS fundamentals + coding round |
| **2** | Machine Learning & Data Science | 8 weeks | **Mon 10 Aug – Fri 2 Oct 2026** | ML theory + from-scratch coding + Kaggle project review |
| **3** | Deep Learning & Neural Networks | 8 weeks | **Mon 5 Oct – Fri 27 Nov 2026** | Backprop derivation + PyTorch coding + DL theory round |
| **4** | NLP, Transformers & Large Language Models | 8 weeks | **Mon 30 Nov 2026 – Fri 22 Jan 2027** | Transformer from scratch defense + LLM interview round |
| **5** | RAG, AI Agents, Multi-Agent Systems & MLOps | 8 weeks | **Mon 25 Jan – Fri 19 Mar 2027** | System build review + MLOps + agent design round |
| **6** | Production AI, System Design, Cloud, Scaling & Interview Mastery | 8 weeks | **Mon 22 Mar – Fri 14 May 2027** | Full FAANG-style loop: DSA + system design + behavioral |
| — | Buffer / revision / job applications | 2 weeks | **17 May – 28 May 2027** | Final mock interview marathon |

**Total: ~10.5 months. Target: interview-ready by end of May 2027.**

### How this program works between us
1. You follow each day exactly as written. No skipping. No AI code assistants for the practical work (this is the whole point — you rebuild independent coding ability).
2. Every Friday you self-assess using the Friday checklist.
3. **At the end of every volume, you come back to me and say "Take my Volume X test."** I will run a real interview-style test (theory + live coding + explanation). If you pass, I generate the next volume in full daily detail. If gaps show up, I give you a 2–3 day patch plan first.
4. Each new volume starts with a scorecard: skills mastered, weak areas, adjustments.

### Volume topic map (so you know where you're going)

**Volume 2 — ML & Data Science (8 wks):** NumPy & Pandas mastery, EDA, statistics & hypothesis testing, linear/logistic regression *from scratch*, decision trees, random forests, gradient boosting (XGBoost), SVMs, KNN, clustering, PCA, feature engineering, model evaluation & cross-validation, bias/variance, scikit-learn pipelines, one full Kaggle competition, advanced SQL.

**Volume 3 — Deep Learning (8 wks):** Calculus for backprop, computational graphs, build an autograd engine from scratch (micrograd-style), MLPs, PyTorch deeply, CNNs, RNNs/LSTMs, optimization (SGD, Adam), regularization (dropout, batchnorm), weight init, learning-rate schedules, training diagnostics, GPU basics, one image + one sequence project.

**Volume 4 — NLP & LLMs (8 wks):** Tokenization (BPE from scratch), embeddings (word2vec from scratch), attention mechanism derived by hand, build a GPT from scratch (nanoGPT-style), positional encodings, pretraining vs SFT vs RLHF, fine-tuning & LoRA/QLoRA, quantization, evaluation of LLMs, reading "Attention Is All You Need" + GPT/BERT/LLaMA papers.

**Volume 5 — RAG, Agents & MLOps (8 wks):** Rebuild RAG with zero frameworks (raw embeddings + your own retriever), vector DB internals (HNSW), chunking strategies, hybrid search & reranking, RAG evaluation, agents from scratch (tool use loop without LangGraph), then LangGraph properly, MCP, multi-agent patterns, Docker deeply, CI/CD, experiment tracking, model serving (FastAPI + vLLM concepts), monitoring & observability.

**Volume 6 — Production & Interview Mastery (8 wks):** AI system design (design a RAG platform, design a recommendation system, design an LLM serving infra), scaling & caching, cost optimization, security & guardrails, cloud (AWS/GCP essentials), Kubernetes basics, portfolio polish (3 flagship projects), resume, then a 3-week interview grind: DSA patterns, ML theory rapid-fire, system design mocks, behavioral (STAR stories).

---

# PART 1.5 — CROSS-CUTTING TRACKS (run through ALL volumes)

These tracks run in parallel with the daily curriculum. They are not optional. Fridays audit them.

### Track A — DSA, every learning week, all volumes ⭐
Weekly quota: **2 LeetCode + 1 NeetCode + 1 HackerRank** (≈20–30 min/day spread across Mon–Thu, or one 90-min block).
- Difficulty ladder: V1 = Easy · V2 = Easy→Medium · V3 = Medium · V4 = Medium · V5 = Medium + pattern revision · V6 = Medium/Hard under mock-interview conditions (timed, talking aloud).
- Pattern order across the year: arrays & hashing → two pointers → sliding window → stack → binary search → linked list → trees → heaps → backtracking → graphs → 1-D dynamic programming.
- Rules: 25-minute cap before you may read hints; every failed problem gets re-solved from scratch the following week; always state time/space complexity aloud before submitting.
- Volume tests with me will ALWAYS include one live DSA problem.

### Track B — System Design (starts Volume 2, every 2nd Friday)
45-minute exercises, always drawn on paper, using the ritual: requirements → back-of-envelope estimates → API → data model → high-level diagram → bottlenecks → trade-offs.
- **V2:** Design a URL shortener · Design a notification system
- **V3:** Design a file upload service · Design an image-classification API
- **V4:** Design a chatbot · Design web search
- **V5:** Design a RAG platform · Design an AI assistant with tools
- **V6:** Full mock loops — LLM serving infrastructure, multi-agent platform, recommendation system

### Track C — Research Paper Track (structured, one paper/week from Volume 3)
For EVERY paper, write a 1-page note answering exactly 7 things: (1) why it was written, (2) what problem it solved, (3) the main idea, (4) limitations, (5) how it changed AI, (6) 3 interview questions on it, (7) one implementation idea.
- **V2 (light start):** Random Forests (Breiman) · XGBoost
- **V3:** AlexNet · ResNet · Adam · Batch Normalization · Dropout
- **V4:** Attention Is All You Need · BERT · GPT-3 · LLaMA · LoRA · QLoRA · InstructGPT
- **V5:** RAG (Lewis et al.) · ReAct · Toolformer · MemGPT · DSPy
- **V6:** Flash Attention · vLLM / PagedAttention
Reading depth: abstract + intro + method figure + conclusions first pass; full read only for the starred core papers (Attention, ResNet, RAG, LoRA, ReAct).

### Track D — AI Engineering Internals Module (distributed V3–V6)
- **V3:** How GPUs work, memory hierarchy (registers→SRAM→VRAM→RAM→disk), tensor cores, CUDA mental model, mixed precision training.
- **V4:** KV cache (derive why it exists from the attention formula), Flash Attention concept, quantization (fp16/int8/4-bit), ONNX.
- **V5:** vLLM & PagedAttention, TensorRT, continuous batching, throughput vs latency trade-offs.
- **V6:** Serving economics & cost optimization (tokens/sec/$, when to quantize vs scale out).

### Track E — Open-Source Reading (one real project per month, 2 evenings)
Method: clone it → find the entry point → trace ONE full request/call path → write a 1-page "how it actually works" note in your repo.
- **Aug:** FastAPI (how routing decorators register endpoints — you built the toy version on Day 3)
- **Sep:** scikit-learn (BaseEstimator, the fit/transform contract)
- **Oct:** NumPy (broadcasting rules, docs + source tour)
- **Nov:** PyTorch (`nn.Module`, what `.backward()` triggers)
- **Dec:** karpathy/nanoGPT + a tokenizer library
- **Jan:** LangGraph (the graph executor)
- **Feb:** Qdrant (HNSW index)
- **Mar:** vLLM (scheduler + paged KV cache)
- **Apr:** LiteLLM (provider abstraction layer)

### Track F — Production Engineering (recurring hands-on labs in V5–V6)
Observability (logs/metrics/traces), Prometheus, Grafana dashboards, OpenTelemetry tracing of your own FastAPI app, rate limiting, retries with exponential backoff + jitter, circuit breakers, feature flags, cost optimization. Each topic = one small lab on your own services, never just reading.

### Track G — Architecture Diagram of the Week (every week, all volumes) ✏️
Rule: **if you can draw it, you understand it.** Draw Thursday, redraw from memory Friday. V1 diagrams are listed in the weekly add-ons below. Later diagrams include: Docker layers, FastAPI request lifecycle, the Transformer, attention, RAG pipeline, LangGraph state machine, MCP, vLLM serving path.

### Track H — Prompt Engineering
Weekly in V1–V3 (15 min Fridays), **daily 10 minutes from Volume 4.** Build a personal `prompt_patterns.md` library in your repo starting today. Cover: prompt patterns, XML-structured prompts, JSON/structured outputs, reasoning prompts, evaluation prompts, agent prompts, reflection prompts.

### Track I — AI Evaluation (core module in Volume 5)
Precision/recall/F1 for retrieval, faithfulness & groundedness, RAGAS, DeepEval, Promptfoo, Langfuse tracing, LLM-as-a-judge (and its biases), designing human evaluation. Your V5 portfolio project ships WITH an eval dashboard — evaluation is the difference between a demo and a product.

### Track J — Portfolio Milestone per Volume (non-negotiable, each polished + README + demo)
| Volume | Flagship project |
|---|---|
| 1 | **LogLens** — professional CLI log analyzer |
| 2 | End-to-end ML prediction system (trained, evaluated, deployed behind FastAPI) |
| 3 | Image classifier trained from scratch, with a proper training report |
| 4 | **Mini-GPT** — a small GPT trained from scratch on your own corpus |
| 5 | **Enterprise RAG** — hybrid search + reranking + eval dashboard + observability |
| 6 | Distributed AI platform capstone (multi-agent + serving + monitoring) |

### Required Book List (across the year)
| Area | Book | When |
|---|---|---|
| Python | *Fluent Python* (primary) + *Effective Python* (dip in) | V1–V2 |
| Algorithms | *Grokking Algorithms* | V1 |
| Math | *Mathematics for Machine Learning* (free PDF) | V1–V3 |
| ML | *Hands-On Machine Learning* (Géron) | V2 |
| Deep Learning | *Deep Learning* (Goodfellow) — reference, not cover-to-cover | V3 |
| Transformers | *Natural Language Processing with Transformers* | V4 |
| System Design | *Designing Data-Intensive Applications* | V5–V6 |
| Engineering craft | *The Pragmatic Programmer* + *Clean Code* (read critically) | ongoing |

### Revised AI-Assistant Rule (v2) ⭐
- **While solving:** no AI coding assistance. Documentation only. First version comes from your head.
- **After your solution works and is committed:** use AI as a *reviewer* — ask it to find bugs, suggest optimizations, and show alternative implementations. Write one lesson per review into `ai_review_log.md` in your repo.
- Never let AI write the first version. Solve first, review after — that's how strong engineers use AI.

---

# PART 2 — VOLUME 1: AI ENGINEERING FOUNDATIONS (FULL DAILY CURRICULUM)

**Dates: Tue 14 Jul – Fri 7 Aug 2026 (4 weeks, 15 learning days + 4 Fridays)**
**Rule for the whole volume: write every line of code yourself first — no Copilot, no AI autocomplete, documentation only. AFTER your code works and is committed, run one AI review pass (bugs, optimizations, alternatives) and log the lesson in `ai_review_log.md`.**

**Goal of Volume 1:** You stop being a framework operator and become an engineer. Deep Python, computer science fundamentals, Linux, Git internals, SQL, and the core math that Volume 2 will need.

---

## WEEK 1 — Python From First Principles (Tue 14 – Fri 17 Jul)

### Day 1 — Tuesday, 14 July 2026 — How Python Actually Executes Your Code

**Objective:** Understand what happens between typing `python file.py` and output appearing. Set up a professional environment. Break the habit of treating Python as magic.

**Theory (1 hr):**
- Interpreter vs compiler; CPython; source → bytecode → PVM. Run `python -m dis` on a small function and read the bytecode.
- Everything is an object: `id()`, `type()`, references vs values.
- Mutability: why `a = b` doesn't copy; `is` vs `==`; small-int caching; shallow vs deep copy.
- Depth required: you should be able to predict the output of tricky reference/mutation snippets without running them.

**Practical (1–2 hrs):**
1. Setup: install `pyenv` (or python.org build), create a project folder `ai-mastery/`, make a venv, `git init`, first commit, push to a new GitHub repo `ai-engineering-mastery`.
2. Write `day01_memory.py`: 10 snippets demonstrating mutability traps (mutable default args, aliased lists, tuple containing a list, `copy` vs `deepcopy`). For each, write your prediction as a comment BEFORE running.
3. Use `dis.dis()` on 3 functions and write 2 lines explaining each bytecode dump.

**Python Practice:** Predict-the-output drills: `x = [1,2]; y = x; y.append(3); print(x)` and 9 similar. Debug task: find why a mutable default argument accumulates across calls.

**Mathematics:** None today (starts Day 12).

**Reading:** *Fluent Python* (Ramalho), Ch. 1 "The Python Data Model" and Ch. 6 "Object References, Mutability, and Recycling" (chapter titles, editions vary). Why: this is THE book that turns intermediate Python users into experts.

**YouTube:**
- "How Python Works" / CPython internals talks by **Anthony Shaw** (PyCon) — see the machine under the language.
- **mCoding** — "Python's default arguments are evil" style videos — short, surgical, senior-level.
(Search these exact titles; prefer official PyCon channels.)

**Free Course:** MIT OCW **6.0001 Introduction to CS and Programming in Python** (ocw.mit.edu) — Lecture 1–2 only, as revision of fundamentals with academic rigor. Free, no certificate.

**Interview Questions (answer aloud, then write):**
1. Is Python interpreted or compiled? Explain precisely. 2. What is the difference between `is` and `==`? 3. Why are mutable default arguments dangerous? 4. What does `id()` return? 5. Explain shallow vs deep copy with an example. 6. What is CPython vs PyPy? 7. Predict: `a=[1,2]; b=a[:]; b.append(3); print(a)`. 8. What is reference counting? 9. Behavioral: "Tell me about yourself" — draft a 60-second version mentioning your 3 years of AI app experience.

**Communication Practice (every day, 10 min):** Record yourself explaining "what happens when Python runs my file" in 2 minutes, in English, as if to an interviewer. Listen back once.

**Daily Notes:** Diagram of source→bytecode→PVM; table of mutable vs immutable types; 3 mutability traps in your own words.

**Deliverables:** GitHub repo live with Day 1 committed; predictions file with your before/after answers; recorded explanation done.

**Bonus:** Interview mistake to avoid: saying "Python is interpreted" with no nuance. Strong answer: "CPython compiles to bytecode, which the virtual machine interprets."

---

### Day 2 — Wednesday, 15 July 2026 — Data Structures Internals & Big-O

**Objective:** Know how list, dict, set, tuple, and str work *internally*, and reason about complexity like an interviewer expects.

**Theory (1 hr):**
- List = dynamic array: over-allocation, amortized O(1) append, O(n) insert at front.
- Dict = hash table: hashing, buckets, collisions, why keys must be hashable, insertion order guarantee (3.7+).
- Set internals; tuple immutability; string interning & immutability; why `"".join()` beats `+=` in loops.
- Big-O of every common operation on every built-in — memorize the table.

**Practical (1–2 hrs):**
1. Implement `DynamicArray` class from scratch (using a fixed-size list you resize manually): `append`, `get`, `pop`, automatic 2x resize. Print capacity changes to watch over-allocation.
2. Implement `HashMap` from scratch: hash function via `hash() % capacity`, collision handling with chaining (list of buckets), `put/get/delete`, resize at load factor 0.75.
3. Benchmark: time `list.insert(0,x)` vs `append` for 100k ops using `time.perf_counter`.

**Python Practice:** 5 problems: two-sum with dict (O(n)), remove duplicates preserving order, count word frequency, find first non-repeating char, group anagrams. Debug task: why does using a list as a dict key fail?

**Reading:** *Fluent Python* Ch. 2 "An Array of Sequences" + Ch. 3 "Dictionaries and Sets". Why: dict mastery is the single highest-ROI Python interview topic.

**YouTube:**
- **Raymond Hettinger** — "Modern Dictionaries" (PyCon) — core developer explaining dict internals; gold standard.
- **CS Dojo** or **NeetCode** — "Big-O Notation" — interview framing of complexity.

**Free Course:** HackerRank Python track — "Data Structures" section (free, free certificate for Python (Basic) test — take it Friday).

**Interview Questions:** 1. How does a Python dict work internally? 2. Why is `append` O(1) amortized? 3. Big-O of `x in list` vs `x in set`? 4. What makes an object hashable? 5. How does dict handle collisions? 6. Why is string concatenation in a loop O(n²)? 7. Code: two-sum in O(n). 8. When would you use a tuple over a list? 9. What happens when a dict resizes? 10. Behavioral: describe a time you improved the performance of something.

**Communication Practice:** Explain aloud: "How does a hash map work?" — 3 minutes, with an analogy (e.g., library shelves).

**Daily Notes:** Big-O table for list/dict/set/str operations (memorize it); diagram of hash table with a collision.

**Deliverables:** `dynamic_array.py` and `hashmap.py` working with test cases, committed.

**Bonus:** Real-world insight: most production slowness in Python services traces to accidental O(n²) (lookups in lists, string building). Interviewers plant these traps deliberately.

---

### Day 3 — Thursday, 16 July 2026 — Functions Deeply: Scope, Closures, Decorators, Generators

**Objective:** Master the function machinery that powers every framework you've been using (FastAPI's decorators, LangChain's callbacks) so frameworks stop feeling like magic.

**Theory (1 hr):**
- LEGB scope rule; `global` and `nonlocal`.
- First-class functions; closures — what a closure actually captures (cell objects).
- Decorators: plain, with arguments, `functools.wraps`; stacked decorators execution order.
- Iterators vs iterables; generators, `yield`, lazy evaluation, generator pipelines; why generators matter for streaming LLM tokens.

**Practical (1–2 hrs):**
1. Write from scratch: `@timeit` (prints execution time), `@retry(times=3, delay=1)` (decorator with arguments), `@memoize` (your own, then compare with `functools.lru_cache`).
2. Build a generator pipeline: `read_lines(file) -> filter_errors(lines) -> parse(lines)` that processes a 100k-line fake log file lazily. Prove low memory use vs loading the whole file.
3. Recreate a FastAPI-style decorator: `@app.get("/path")` that registers functions in a dict — a 30-line toy router. This demystifies FastAPI.

**Python Practice:** Fibonacci with generator; closure-based counter factory; fix a broken decorator missing `@wraps`; explain output order of two stacked decorators.

**Reading:** *Fluent Python* Ch. 9 "Decorators and Closures" + Ch. 17 "Iterators, Generators". Why: decorators/generators are the top "senior vs junior Python" separator in interviews.

**YouTube:**
- **Corey Schafer** — "Decorators" and "Generators" — clearest explanations on the internet.
- **mCoding** — "Why you should use more generators".

**Free Course:** Kaggle Learn — "Python" course (free, free certificate) — finish any remaining sections as speed-run revision.

**Interview Questions:** 1. What is a closure? 2. Explain LEGB. 3. What does `functools.wraps` fix? 4. Difference between iterator and iterable? 5. What does `yield` do exactly? 6. Write a retry decorator live. 7. Why are generators memory-efficient? 8. What is `nonlocal`? 9. How does FastAPI use decorators? 10. Code: flatten a nested list with a generator.

**Communication Practice:** Explain a decorator to a "non-technical manager" in 90 seconds, then to a "senior engineer" in 90 seconds. Different depth, same clarity.

**Daily Notes:** Decorator template you can write from memory; generator vs list memory diagram.

**Deliverables:** Three working decorators + toy router committed; you can write a decorator from a blank file in under 5 minutes.

**Bonus:** Interview mistake: writing a decorator but forgetting it must *return* the wrapper. Practice until muscle memory.

---

### 🔁 WEEK 1 ADD-ONS (Tracks A + G + AI review — spread across Tue–Thu, ~20 min/day)
**DSA quota (after Day 2 you have the tools):**
- LeetCode: **Two Sum** (#1), **Valid Anagram** (#242)
- NeetCode: **Contains Duplicate**
- HackerRank: **Nested Lists** (Python)
- Rules: 25-min cap each before hints; state Big-O aloud before submitting; failed problems re-solved next week.

**Diagram of the week:** the Python memory model — names → references → objects, plus source → bytecode → PVM. Draw Thursday, redraw from memory Friday.

**AI review ritual:** after committing each day's code, one AI review pass; log one lesson per day in `ai_review_log.md`.

---

### FRIDAY — 17 July 2026 — Week 1 Revision + Assessment + Mock Interview

0. **Track audit:** ☐ 4 DSA problems attempted ☐ diagram redrawn from memory ☐ `ai_review_log.md` has 3 entries ☐ 15 min prompt-pattern practice (start `prompt_patterns.md` with: role prompts + XML structure).

1. **Revision (30 min):** Re-read your notes Days 1–3. Redo any predict-the-output you got wrong.
2. **Coding assessment (45 min, timed, no docs):** (a) implement a HashMap with chaining; (b) write `@retry` decorator; (c) two-sum; (d) generator that yields batches of size n from any iterable.
3. **Python assessment:** Take HackerRank **Python (Basic)** certification test (free certificate).
4. **Mock interview (20 min):** Record yourself answering: "How does a dict work?", "Explain closures", "Is Python interpreted or compiled?" — speak aloud, then critique your recording.
5. **Flashcards:** Make 20 cards (Anki recommended): Big-O table, mutability rules, decorator template, LEGB.
6. **Weak areas:** Write down the 2 weakest topics; redo 3 exercises on each over the weekend if you want (optional).
7. **Week 1 checklist:** ☐ Can predict mutation/reference outputs ☐ Can implement hashmap from scratch ☐ Can write decorator from memory ☐ Can explain generators aloud ☐ Repo has 4+ commits.

---

## WEEK 2 — OOP, Errors, Testing, Professional Python (Mon 20 – Fri 24 Jul)

### Day 4 — Monday, 20 July 2026 — OOP Part 1: Classes & the Data Model (Dunder Methods)

**Objective:** Understand that Python OOP = the data model. Build classes that feel like built-in types.

**Theory (1 hr):** `__init__` vs `__new__`; instance vs class attributes; `self`; `__repr__` vs `__str__`; operator overloading (`__add__`, `__eq__`, `__len__`, `__getitem__`); `@property`; class methods vs static methods.

**Practical (1–2 hrs):**
1. Build `Vector` class: `+`, `-`, scalar `*`, `==`, `len`, indexing, dot product method, nice `__repr__`. (This directly preps Volume 2 linear algebra.)
2. Build `Money` class with `@property` validation (no negative amounts) and currency-safe addition.
3. Make `Vector` iterable so `for x in v` works.

**Python Practice:** Add `__getitem__` slicing support to Vector; explain why `print(obj)` shows `<object at 0x...>` without `__repr__`; fix a class-attribute-shared-list bug.

**Reading:** *Fluent Python* Ch. 1 again + Ch. 11 "A Pythonic Object". Why: interviewers at top companies ask you to design a class live; dunders are what make it impressive.

**YouTube:** **Corey Schafer** OOP playlist (videos 1–3); **ArjanCodes** — "The Ultimate Guide to Writing Classes".

**Free Course:** Microsoft Learn — "Object-oriented programming in Python" module (free, free badge).

**Interview Questions:** 1. `__repr__` vs `__str__`? 2. What is `self`? 3. Class vs instance attribute? 4. What does `__eq__` change about `==`? 5. `@staticmethod` vs `@classmethod`? 6. What is `@property` for? 7. Live-code a `Vector` with `+`. 8. What is duck typing? 9. Why implement `__len__`? 10. Behavioral: a time you had to learn something quickly.

**Communication Practice:** Explain "what is object-oriented programming" in 2 minutes without buzzwords — use a concrete example (Vector or BankAccount).

**Daily Notes:** Table of the 10 most useful dunder methods with one-line purpose each.

**Deliverables:** `vector.py` with 8+ dunder methods and a demo script, committed.

**Bonus:** Fact: everything you like about NumPy arrays (`a + b`, `a[2:5]`, `len(a)`) is just dunder methods. You now know how NumPy's interface works.

---

### Day 5 — Tuesday, 21 July 2026 — OOP Part 2: Inheritance, Composition, ABCs, Dataclasses

**Objective:** Learn when NOT to use inheritance, and design code the way senior engineers do.

**Theory (1 hr):** Inheritance, `super()`, MRO (method resolution order); composition over inheritance (why); abstract base classes (`abc`), protocols/duck typing; `@dataclass` (fields, defaults, `frozen=True`); brief SOLID principles overview.

**Practical (1–2 hrs):**
1. Build a mini document-processing pipeline: abstract `Processor` ABC with `process()`, concrete `LowercaseProcessor`, `StopwordProcessor`, `StemProcessor`; a `Pipeline` class that *composes* a list of processors. (This is the architecture of every AI preprocessing library.)
2. Refactor: take a badly-designed 3-level inheritance example (write it first) and refactor to composition. Feel the difference.
3. Rewrite `Money` from Day 4 as a frozen dataclass.

**Python Practice:** Predict MRO of a diamond inheritance; when does `super().__init__()` matter; convert a dict-heavy function to a dataclass.

**Reading:** *Fluent Python* Ch. 14 "Inheritance: For Better or for Worse". Why: "composition over inheritance" is a favorite senior-level interview discussion.

**YouTube:** **ArjanCodes** — "Composition over inheritance" and "Dataclasses"; **Raymond Hettinger** — "Super considered super!" (PyCon).

**Free Course:** Continue Microsoft Learn Python path — inheritance module.

**Interview Questions:** 1. What is MRO and how does Python compute it? 2. When do you prefer composition over inheritance? 3. What is an ABC and why use one? 4. What does `@dataclass` generate for you? 5. What is the diamond problem? 6. Explain SOLID's "L" (Liskov) with an example. 7. Design question: "Design a notification system supporting email/SMS/push" — talk through classes. 8. `frozen=True` — why? 9. Protocol vs ABC? 10. Behavioral: describe a design decision you regretted.

**Communication Practice:** Whiteboard-talk (paper is fine): narrate your pipeline design aloud as if in a design interview — "I chose composition here because…".

**Daily Notes:** Decision rule: "inherit for is-a with shared behavior; compose for has-a / uses-a"; dataclass cheat sheet.

**Deliverables:** `pipeline.py` with ABC + 3 processors + composed pipeline + tests-by-hand in `__main__`, committed.

**Bonus:** Real-world insight: LangChain's `Runnable`, scikit-learn's `fit/transform`, PyTorch's `nn.Module` — all the frameworks you know are ABC + composition patterns. You now recognize the skeleton.

---

### Day 6 — Wednesday, 22 July 2026 — Errors, Exceptions, Context Managers, Logging

**Objective:** Write code that fails loudly, safely, and debuggably — the #1 difference between demo code and production code.

**Theory (1 hr):** Exception hierarchy; `try/except/else/finally`; catching specific exceptions (never bare `except:`); raising and re-raising; custom exceptions; exception chaining (`raise ... from e`); context managers — `with`, `__enter__/__exit__`, `contextlib.contextmanager`; `logging` module: levels, handlers, formatters, why `print` is not logging.

**Practical (1–2 hrs):**
1. Build a robust CSV batch processor: reads a folder of files, parses rows, bad rows go to a `errors.log` with full context (file, line no, reason) via `logging`, good rows aggregate. It must never crash on one bad file.
2. Write a custom context manager `Timer()` both ways (class-based and `@contextmanager`).
3. Define custom exceptions `ValidationError`, `ParsingError` and use chaining.

**Python Practice:** Fix code that swallows exceptions with bare `except`; add `finally` cleanup to a file handler; convert prints to proper logging with a formatter showing timestamp+level.

**Reading:** Official Python docs — `logging` HOWTO (docs.python.org). Why: interviewers and code reviewers immediately notice logging maturity.

**YouTube:** **Corey Schafer** — "Logging Basics" + "Logging Advanced"; **mCoding** — "Modern Python logging".

**Free Course:** Cisco Skills for All — "Python Essentials 2" (exceptions module) — free with free certificate.

**Interview Questions:** 1. `else` clause in try/except — when does it run? 2. Why is bare `except:` dangerous? 3. What is exception chaining? 4. How does `with` work under the hood? 5. Write a context manager live. 6. Logging levels in order? 7. Why not `print` in production? 8. What is `finally` guaranteed to do? 9. Design: how would you handle partial failures in a batch job? 10. Behavioral: a production bug you fixed — walk through it.

**Communication Practice:** Explain your CSV processor's failure-handling strategy aloud in 2 minutes — practice the phrase "fail gracefully, log loudly."

**Daily Notes:** Exception-handling patterns cheat sheet; logging setup snippet you'll reuse forever.

**Deliverables:** `batch_processor.py` + generated `errors.log` demonstrating graceful failure, committed.

**Bonus:** Interview mistake: candidates who never mention error handling in design questions get marked junior. Always say what happens when things fail.

---

### Day 7 — Thursday, 23 July 2026 — Testing (pytest), Debugging (pdb), Type Hints (mypy)

**Objective:** Adopt the three habits that define professional engineers: tests, real debugging, and types.

**Theory (1 hr):** Why test; pytest basics: test discovery, asserts, fixtures, parametrize; arrange-act-assert; what to test vs not; TDD in brief; `pdb` (`breakpoint()`, n/s/c/p commands); type hints: `list[int]`, `Optional`, `Union`, `TypedDict`, generics briefly; running `mypy`.

**Practical (1–2 hrs):**
1. Write pytest suites for your Week 1–2 code: `test_hashmap.py`, `test_vector.py`, `test_pipeline.py` — minimum 20 tests total, use `@pytest.mark.parametrize`.
2. Deliberately break your hashmap, then find the bug using ONLY `breakpoint()` + pdb (no prints).
3. Add full type hints to `vector.py` and `pipeline.py`; run `mypy` until clean.

**Python Practice:** TDD kata: write tests FIRST for a `slugify(text)` function, then implement. Fixture exercise: temp file fixture for the CSV processor tests.

**Reading:** pytest official docs — "Get Started" + "Parametrize" pages. Why: pytest is the industry standard; fixtures/parametrize come up in senior screens.

**YouTube:** **ArjanCodes** — "How to test Python code"; **freeCodeCamp** — pytest crash course; **Corey Schafer** — pdb/debugging video.

**Free Course:** freeCodeCamp — relevant testing sections; optional: Harvard **CS50P** (audit free) problem sets for extra drills.

**Interview Questions:** 1. What is a fixture? 2. `parametrize` — why useful? 3. Unit vs integration test? 4. What is TDD? 5. How do you debug without prints? 6. What does `Optional[int]` mean? 7. Does Python enforce type hints at runtime? 8. What is mypy? 9. What would you test in a payment function? 10. Behavioral: how do you make sure your code is correct before shipping?

**Communication Practice:** Explain aloud: "How do you ensure code quality?" — a 2-minute answer covering tests, types, logging, review. This is a guaranteed interview question.

**Daily Notes:** pytest command cheat sheet; pdb command table; your personal "definition of done" checklist.

**Deliverables:** 20+ passing tests, mypy-clean modules, committed. From today, **all future code in this program must ship with tests.**

**Bonus:** Fact: at top companies, code without tests is usually unreviewable. Showing pytest fluency in a take-home assignment massively raises your pass rate.

---

### 🔁 WEEK 2 ADD-ONS (Tracks A + G)
**DSA quota:**
- LeetCode: **Valid Parentheses** (#20 — stack pattern), **Merge Two Sorted Lists** (#21)
- NeetCode: **Best Time to Buy and Sell Stock** (two-pointer/greedy intro)
- HackerRank: one class-based OOP problem (Python track)
- Plus: re-solve anything you failed in Week 1.

**Diagram of the week:** your Day 5 processor pipeline as a class diagram — ABC at the top, three processors, Pipeline composing them. If you can draw it, you designed it.

**AI review ritual continues daily.**

---

### FRIDAY — 24 July 2026 — Week 2 Revision + Assessment + Mock Interview

0. **Track audit:** ☐ 4 DSA problems + Week-1 re-solves ☐ pipeline diagram redrawn from memory ☐ `ai_review_log.md` has 7+ entries ☐ 15 min prompting (JSON/structured outputs pattern added to your library).

1. **Revision (30 min):** Notes Days 4–7; rewrite the dunder table and exception patterns from memory.
2. **Coding assessment (60 min, timed):** Build a `BankAccount` system: `Account` ABC, `Savings`/`Checking` subclasses OR composition (justify your choice aloud), custom `InsufficientFundsError`, full logging, `@dataclass` for transactions, and a pytest suite with 8+ tests. No documentation allowed for the first 40 minutes.
3. **Mock interview (25 min):** Answer aloud & record: MRO, composition vs inheritance, context managers, "design a rate limiter class" (talk through it).
4. **Flashcards:** +20 cards (dunders, SOLID, pytest, logging levels).
5. **Mini project review:** Re-read your pipeline code as if reviewing a stranger's PR; leave yourself 5 written review comments.
6. **Week 2 checklist:** ☐ Can design classes with dunders live ☐ Can argue composition vs inheritance ☐ All code has tests & types ☐ Can debug with pdb ☐ Bank assessment done in time.

**End of Week 2 summary — you should now know:** professional Python: data model, OOP design, error handling, testing, typing. You can now build small systems a senior engineer would approve.

---

## WEEK 3 — CS Fundamentals: Algorithms, Linux, Git (Mon 27 – Fri 31 Jul)

### Day 8 — Monday, 27 July 2026 — Algorithm Analysis & Recursion

**Objective:** Think in complexity and recursion — the two mental tools every coding interview tests.

**Theory (1 hr):** Formal-ish Big-O, Big-Θ intuition; best/average/worst case; space complexity; analyzing loops and nested loops; recursion: base case, recursive case, call stack, stack overflow; recursion vs iteration; memoization; recursion tree method for complexity (e.g., naive fib = O(2^n)).

**Practical (1–2 hrs):**
1. Implement recursively: factorial, fibonacci (naive → memoized → bottom-up; benchmark all three at n=35), sum of nested list (arbitrary depth), binary search (recursive + iterative), reverse a string, power set of a list.
2. For each, write its time & space complexity as a comment and justify in one line.

**Python Practice:** Trace the call stack of `fib(5)` on paper; fix a recursion with a missing base case; convert a recursion to iteration with an explicit stack.

**Mathematics:** Logarithms refresher (why binary search is O(log n)); geometric series intuition for recursion trees. Why it matters: complexity analysis IS applied math.

**Reading:** *Grokking Algorithms* (Bhargava) Ch. 1–3 (Big-O, recursion). Why: the friendliest rigorous intro; readable in one sitting per chapter.

**YouTube:** **freeCodeCamp** — "Recursion in Programming"; **NeetCode** — "Big-O for coding interviews"; **MIT 6.006** Lecture 1 (algorithmic thinking) on MIT OCW.

**Free Course:** Kaggle/HackerRank — "Problem Solving (Basic)" prep (free cert available).

**Interview Questions:** 1. Big-O of nested loop over n and m? 2. Why is memoized fib O(n)? 3. What is the call stack? 4. Recursion vs iteration trade-offs? 5. Space complexity of recursive binary search? 6. Code: power set. 7. Code: nested list sum. 8. What causes stack overflow? 9. What is amortized complexity (recall Day 2)? 10. Behavioral: how do you approach a problem you can't solve immediately?

**Communication Practice:** Practice the interview ritual aloud: restate problem → clarify → brute force → complexity → optimize → code → test. Narrate it on the two-sum problem.

**Daily Notes:** Recursion template; complexity of all today's solutions; the interview ritual steps.

**Deliverables:** `day08_recursion.py` with 6 solved problems + complexities + tests, committed.

**Bonus:** Interview insight: interviewers care more about your *stated reasoning* about complexity than the final code. Always say the Big-O unprompted.

---

### Day 9 — Tuesday, 28 July 2026 — Sorting & Searching From Scratch

**Objective:** Implement the classic algorithms yourself once in your life — this cements complexity intuition permanently.

**Theory (1 hr):** Bubble/insertion sort (O(n²), why); merge sort (divide & conquer, O(n log n), stable, O(n) space); quicksort (partition, average O(n log n), worst O(n²), in-place); binary search variants (first occurrence, insertion point); when Python's Timsort makes all this "unnecessary" — and why you must know it anyway.

**Practical (1–2 hrs):**
1. Implement insertion sort, merge sort, quicksort from scratch with tests (including edge cases: empty, single, duplicates, sorted, reverse-sorted).
2. Benchmark all three + built-in `sorted()` on random lists of 1k/10k/100k; plot or table the results.
3. Binary search variants: exact match, leftmost occurrence, and "search insert position".

**Python Practice:** Sort a list of dicts by key with `sorted(key=...)`; explain `key=lambda` vs `functools.cmp_to_key`; stable-sort demonstration.

**Mathematics:** Master theorem intuition (just the idea: T(n)=2T(n/2)+O(n) → O(n log n)). Why: lets you derive complexity instead of memorizing.

**Reading:** *Grokking Algorithms* Ch. 4 (quicksort/divide & conquer).

**YouTube:** **3Blue1Brown**-style visual sort videos or **Michael Sambol** sorting shorts (crisp 5-min visuals per algorithm); **NeetCode** — binary search patterns.

**Free Course:** MIT OCW 6.006 — sorting lectures (audit free).

**Interview Questions:** 1. Why is comparison sort lower-bounded at O(n log n)? 2. Merge vs quick — trade-offs? 3. What is a stable sort and when does it matter? 4. Quicksort worst case — when and how to avoid? 5. Code: merge two sorted lists. 6. Code: first occurrence via binary search. 7. What algorithm does Python's `sorted` use? 8. Sort 10GB of data that doesn't fit in RAM — approach? (external/merge sort) 9. Big-O of `sorted()`? 10. Behavioral: a time you had to meet a tight deadline.

**Communication Practice:** Explain merge sort aloud with the phone-book analogy in under 3 minutes.

**Daily Notes:** Sorting comparison table (time/space/stable/in-place); binary search template (the `lo, hi = 0, len(a)` version you'll reuse).

**Deliverables:** `sorts.py` + `binary_search.py` with tests and benchmark table, committed.

**Bonus:** The "sort a file bigger than RAM" question appears constantly at data-heavy companies (Databricks, Snowflake). Your answer: chunk → sort chunks → k-way merge.

---

### Day 10 — Wednesday, 29 July 2026 — Linux & the Command Line

**Objective:** Operate a Linux machine like it's home. Every ML job, every server, every Docker container is Linux.

**Theory (1 hr):** Filesystem hierarchy (`/etc`, `/var`, `/usr`, `/home`, `/tmp`); permissions (`rwx`, `chmod`, `chown`, octal notation); processes (`ps`, `top/htop`, signals, `kill`); pipes & redirection (`|`, `>`, `>>`, `2>`); environment variables & `PATH`; `ssh` and `scp` basics; package managers (`apt`).

**Practical (1–2 hrs):**
1. In a terminal (WSL2 if on Windows, or a free cloud shell): 25-command drill — navigate, create nested dirs, `find` files by name/size, `grep -r` a pattern, count matches with `wc -l`, chain 3+ pipes.
2. Text-processing mini-task: given a fake `access.log` (generate one with Python), use `grep`, `awk`, `sort`, `uniq -c` to find the top 5 IPs and count of 500 errors — pure shell, no Python.
3. Write a bash script `backup.sh`: timestamps, copies a folder to `~/backups/`, logs what it did, exits nonzero on failure. Make it executable with `chmod +x`.

**Python Practice:** Rewrite the log analysis in Python using `collections.Counter`; compare with your shell one-liner.

**Reading:** *The Linux Command Line* (Shotts, free at linuxcommand.org) — Ch. 1–6 skim + permissions chapter properly. Why: free, canonical, and the permissions chapter alone covers 80% of Linux interview questions.

**YouTube:** **freeCodeCamp** — "Linux Command Line Full Course" (watch the first 60–90 min, targeted sections); **NetworkChuck** — Linux basics (engaging refresher).

**Free Course:** Cisco Skills for All — "Linux Essentials" style track (free certificate); or Kaggle notebooks terminal for practice.

**Interview Questions:** 1. What does `chmod 755` mean? 2. Difference between `>` and `>>`? 3. What is a process vs a thread? 4. How do you find which process uses port 8000? (`lsof -i :8000`) 5. What does `grep -r "error" . | wc -l` do? 6. What is `PATH`? 7. Kill a hung process — how, and difference between SIGTERM and SIGKILL? 8. Where do logs usually live? 9. What is ssh key-based auth? 10. Follow a growing log file live? (`tail -f`)

**Communication Practice:** Explain aloud: "You deploy a FastAPI app and it won't start on the server — walk me through debugging." (check logs, port, permissions, env vars, process). This exact question appears in AI engineer interviews.

**Daily Notes:** One-page personal Linux cheat sheet — this becomes a lifelong reference.

**Deliverables:** `backup.sh` + shell log-analysis one-liners saved in `linux_notes.md`, committed.

**Bonus:** Real-world insight: candidates who fumble in a terminal during a pairing interview lose credibility instantly, regardless of algorithm skill. Fluency here is cheap to gain and very visible.

---

### Day 11 — Thursday, 30 July 2026 — Git Deeply: Internals & Professional Workflow

**Objective:** Stop using Git as "save button + panic". Understand the object model so no Git situation scares you.

**Theory (1 hr):** Git objects: blob, tree, commit; what a branch actually is (a pointer); HEAD; staging area; merge vs rebase (and when each); `merge --squash`; resolving conflicts calmly; `stash`, `cherry-pick`, `reflog` (the undo of last resort); `reset --soft/--mixed/--hard`; professional flow: feature branches, small commits, good messages, PRs, code review etiquette; `.gitignore` for Python/AI projects.

**Practical (1–2 hrs):**
1. Internals lab: in a scratch repo, make commits then explore `.git/` — use `git cat-file -p <hash>` to walk commit → tree → blob. See with your own eyes that Git is a content-addressed database.
2. Conflict drill: create two branches editing the same line, merge, resolve; then repeat with `rebase` and compare histories with `git log --graph --oneline`.
3. Disaster-recovery drill: "accidentally" `reset --hard` away a commit, recover it via `reflog`.
4. Clean up your `ai-engineering-mastery` repo: proper README, `.gitignore`, and open a PR to yourself with a self-review.

**Python Practice:** Light day — one problem: parse `git log --oneline` output with Python and count commits per day.

**Reading:** *Pro Git* (free at git-scm.com) — Ch. 3 "Git Branching" + Ch. 10.2 "Git Objects". Why: free official book; chapter 10.2 is the single best explanation of Git internals in existence.

**YouTube:** **freeCodeCamp** — "Git Internals" / advanced Git; **The Modern Coder** or **Fireship** — "Git rebase vs merge" (short, sharp).

**Free Course:** GitHub Skills (skills.github.com) — "Introduction to GitHub" + "Review pull requests" (free, hands-on in real repos).

**Interview Questions:** 1. What is a commit, really? 2. What is a branch under the hood? 3. Merge vs rebase — trade-offs, and why never rebase shared branches? 4. `reset` soft vs mixed vs hard? 5. You committed a secret key — what do you do? 6. What is the reflog? 7. What is a detached HEAD? 8. Describe your PR workflow. 9. `fetch` vs `pull`? 10. Behavioral: a time you disagreed in a code review.

**Communication Practice:** Explain rebase vs merge aloud with a drawing — this is a very common screening question for engineers with "3 years experience".

**Daily Notes:** Git internals diagram (commit→tree→blob); recovery commands table; your commit-message convention.

**Deliverables:** Internals lab notes + cleaned-up repo with README and merged PR.

**Bonus:** Fact: `git reflog` has saved more careers than any other command. Nothing committed is ever truly lost for ~90 days.

---

### 🔁 WEEK 3 ADD-ONS (Tracks A + G)
**DSA quota (this week's curriculum feeds these directly):**
- LeetCode: **Binary Search** (#704), **Reverse Linked List** (#206 — first linked-list exposure; learn the node pattern)
- NeetCode: **Last Stone Weight** (heap intro — Python `heapq`)
- HackerRank: one Problem Solving (easy) challenge
- Plus Week-2 re-solves.

**Diagram of the week (two small ones):** (1) Git object model — commit → tree → blob with arrows; (2) hash table with chaining, one collision shown.

**AI review ritual continues daily.**

---

### FRIDAY — 31 July 2026 — Week 3 Revision + Assessment + Mock Interview

0. **Track audit:** ☐ 4 DSA problems + re-solves ☐ both diagrams redrawn from memory ☐ `ai_review_log.md` growing ☐ 15 min prompting (reasoning-prompt pattern added).

1. **Revision (30 min):** Redo one recursion problem, re-derive merge sort complexity, rewrite the Linux and Git cheat sheets from memory.
2. **Coding assessment (60 min):** (a) binary search leftmost-occurrence, from blank file, with tests; (b) merge k sorted lists (use your merge logic); (c) shell one-liner: top 3 most frequent words in a text file; (d) Git scenario quiz: 5 written "what command do you run" situations.
3. **Mock interview (25 min):** Record: "Sort a 10GB file", "rebase vs merge", "walk me through debugging a server that won't start".
4. **Flashcards:** +20 (sorting table, Linux commands, Git commands, master-theorem intuition).
5. **Weak areas:** note them; the weekend is off, but list what Day-8-style problems you'll redo Monday warm-up.
6. **Week 3 checklist:** ☐ Recursion template internalized ☐ Implemented 3 sorts + binary search variants ☐ Comfortable in a terminal ☐ Can explain Git internals ☐ Repo is professional-looking.

---

## WEEK 4 — Math Foundations, SQL & Capstone (Mon 3 – Fri 7 Aug)

### Day 12 — Monday, 3 August 2026 — Linear Algebra I: Vectors & Matrices (From Scratch → NumPy)

**Objective:** Build the geometric intuition and computational fluency that ALL of ML/DL sits on. Embeddings, attention, gradients — all of it is this.

**Theory (1 hr):** Vectors as arrows and as data points; vector addition, scalar multiplication; dot product (algebraic + geometric meaning: projection & similarity); norms (L1, L2); **cosine similarity — and why your vector DB (Qdrant) uses it**; matrices as transformations; matrix-vector and matrix-matrix multiplication (row-times-column, and why the inner dimensions must match).

**Practical (1–2 hrs):**
1. Pure Python (no NumPy): `dot(u,v)`, `norm(v)`, `cosine_similarity(u,v)`, `matvec(M,v)`, `matmul(A,B)` — with tests.
2. Then NumPy: redo all in 1 line each; benchmark pure Python vs NumPy matmul at 200×200 — see the ~100x gap and understand why (C, contiguous memory, vectorization).
3. Mini-demo: take 5 short sentences, make toy "embeddings" (word-count vectors), compute pairwise cosine similarity, and see that similar sentences score higher. **You just built the core of RAG retrieval by hand.**

**Mathematics (today theory = math):** As above. Why it matters: attention scores are dot products; retrieval is cosine similarity; a neural network layer is `Wx + b`.

**Reading:** *Mathematics for Machine Learning* (Deisenroth et al., free PDF at mml-book.github.io) — Ch. 2 "Linear Algebra", sections 2.1–2.4. Why: the free canonical ML-math book; read slowly, it pays off through Volume 4.

**YouTube:** **3Blue1Brown** — "Essence of Linear Algebra" episodes 1–4 (vectors, span, transformations, matmul). Non-negotiable — this playlist builds visual intuition nothing else matches.

**Free Course:** Khan Academy Linear Algebra (free) — vectors unit for extra drills.

**Interview Questions:** 1. Geometric meaning of a dot product? 2. Why cosine similarity instead of Euclidean distance for embeddings? 3. Shape of A(3×4) @ B(4×2)? 4. What is a norm? 5. Why is NumPy faster than a Python loop? 6. What does a matrix "do" to a vector? 7. Code: cosine similarity from scratch. 8. What is broadcasting (preview)? 9. In RAG, what math finds the nearest chunk? 10. What breaks if you compare unnormalized embeddings with dot product?

**Communication Practice:** Explain to a recording: "Why does cosine similarity power semantic search?" in 2 minutes with an example.

**Daily Notes:** Shape-rule diagram for matmul; dot product = |u||v|cosθ; cosine similarity formula from memory.

**Deliverables:** `linalg_scratch.py` + `linalg_numpy.py` + the toy-embedding similarity demo, committed.

**Bonus:** Insight: when you later read the attention formula `softmax(QKᵀ/√d)V`, it will be ~80% today's material. Today you bought Volume 4 at a discount.

---

### Day 13 — Tuesday, 4 August 2026 — Probability & Statistics Essentials

**Objective:** Speak probability fluently — the language of every model's output, every A/B test, every "temperature" parameter.

**Theory (1 hr):** Probability basics: sample space, independence, conditional probability; **Bayes' theorem** (derive it, do the medical-test example by hand); random variables, expectation, variance, standard deviation; distributions: Bernoulli, Binomial, Uniform, **Normal** (and why it's everywhere — CLT intuition); sampling; what "softmax gives a probability distribution" means.

**Practical (1–2 hrs):**
1. Implement from scratch: `mean`, `variance`, `std` (know the n vs n-1 idea), then verify against `statistics` module.
2. Monte Carlo: estimate π by random points in a square; simulate 10k coin-flip sequences and plot/tabulate how sample means concentrate (CLT with your own eyes).
3. Bayes calculator: function `bayes(prior, sensitivity, false_positive_rate)`; run the classic "1% disease, 99% accurate test" example — be shocked by the answer, then explain it.
4. Implement `softmax(logits)` in pure Python and show outputs sum to 1; play with a temperature parameter and watch the distribution sharpen/flatten. **This is what LLM temperature literally is.**

**Mathematics:** As above. Why: interviews at every company on your target list include at least one probability question.

**Reading:** *Think Stats* (free, greenteapress.com) Ch. 1–2, or MML book Ch. 6 sections 6.1–6.2 if you want more rigor.

**YouTube:** **StatQuest** — "Bayes' Theorem", "The Normal Distribution", "Expected Values" — the gold standard for stats intuition; **3Blue1Brown** — "Bayes theorem" visual.

**Free Course:** Kaggle Learn — "Intro to Machine Learning" is NOT yet (Volume 2); instead Khan Academy Statistics & Probability, targeted units (free).

**Interview Questions:** 1. State Bayes' theorem and give a real use. 2. The disease-test question (do it live). 3. Expectation of a die roll? 4. Variance vs std — interpretation? 5. Why does the normal distribution appear so often? 6. Independent vs mutually exclusive? 7. What does temperature do to softmax? 8. Code: softmax with numerical stability (subtract max). 9. P(at least one six in 4 rolls)? 10. What is Monte Carlo simulation?

**Communication Practice:** Explain the disease-test Bayes result aloud to an imaginary non-technical person until it sounds obvious.

**Daily Notes:** Bayes formula + one worked example; distribution table (name, params, mean, example); stable-softmax snippet.

**Deliverables:** `stats_scratch.py`, `monte_carlo.py`, `softmax.py` with tests, committed.

**Bonus:** Interview trap: "99% accurate test, positive result — probability you're sick?" Most candidates say 99%. The real answer (~50% at 1% prevalence) instantly marks you as someone who actually understands probability.

---

### Day 14 — Wednesday, 5 August 2026 — SQL From First Principles

**Objective:** Read and write real SQL confidently — every data/AI role screens SQL, and RAG/analytics work needs it constantly.

**Theory (1 hr):** Relational model: tables, rows, primary/foreign keys; `SELECT/WHERE/ORDER BY/LIMIT`; aggregation: `GROUP BY`, `HAVING`, `COUNT/SUM/AVG`; **JOINs**: inner, left, right, full — with Venn-style mental model; subqueries & CTEs (`WITH`); indexes: what a B-tree index buys you, when it's used, why writes get slower; `NULL` semantics (the classic trap: `= NULL` vs `IS NULL`).

**Practical (1–2 hrs):**
1. Use SQLite (`sqlite3` module or DB Browser). Build a mini e-commerce schema: `customers`, `orders`, `order_items`, `products`. Insert ~50 rows via a Python seeding script (use your Week 2 skills).
2. Write 15 queries of increasing difficulty: top customers by spend, monthly revenue, products never ordered (LEFT JOIN + IS NULL), customers with >2 orders (HAVING), 2nd highest order value, revenue per category with CTE.
3. `EXPLAIN QUERY PLAN` on one query before/after adding an index; observe the difference.

**Data Understanding:** Normalization intuition (why order_items is separate); when denormalization is acceptable (analytics).

**Reading:** SQLBolt (sqlbolt.com) — lessons 1–12 interactively. Why: the fastest hands-on SQL grounding that exists, free.

**YouTube:** **freeCodeCamp** — SQL tutorial (targeted: joins + group by sections); **StatQuest**-adjacent: any visual JOIN explanation with diagrams.

**Free Course:** Kaggle Learn — "Intro to SQL" + "Advanced SQL" (free, free certificate) — do Intro today, Advanced during Volume 2.

**Interview Questions:** 1. INNER vs LEFT JOIN? 2. WHERE vs HAVING? 3. Find duplicates in a table — query? 4. Second-highest salary — query (classic)? 5. Why does `col = NULL` return nothing? 6. What is an index and its trade-off? 7. Primary vs foreign key? 8. What is a CTE and why use it? 9. Products with zero orders — query? 10. When would you denormalize?

**Communication Practice:** Talk through the "second-highest salary" query aloud, explaining your reasoning step-by-step, as in a live SQL screen.

**Daily Notes:** JOIN diagram page; GROUP BY/HAVING rule; index trade-off summary; NULL gotchas.

**Deliverables:** `shop.db` + `seed.py` + `queries.sql` (15 queries with comments), committed.

**Bonus:** Real-world: AI engineers constantly write SQL to build evaluation datasets and analyze model logs. "I only do vectors" doesn't survive contact with a real job.

---

### Day 15 — Thursday, 6 August 2026 — CAPSTONE: Build a Complete Tool, Solo, No AI

**Objective:** Prove to yourself the last 3 weeks worked. One evening, one complete, professional mini-product, entirely from your own head.

**The project — "LogLens": a CLI log analyzer.**
Requirements:
1. Reads a log file (generate a 50k-line fake app log with a helper script: timestamps, levels, endpoints, response-times, some malformed lines).
2. Architecture: `Parser` class, `Analyzer` class, custom exceptions, dataclass `LogRecord`, generator-based file reading (never load the whole file), proper `logging` for its own diagnostics, malformed lines counted not crashed on.
3. Features: count by level; top 5 endpoints; p50/p95 response time (you know stats now); errors-per-hour table; results optionally written to a SQLite table.
4. CLI with `argparse`: `python loglens.py app.log --top 5 --db results.db`.
5. pytest suite (10+ tests), type hints, mypy clean, README with usage, committed via a feature branch + PR to yourself.

**Time-box:** 2.5–3 hrs. If you exceed it, note where the time went — that's your weak spot list.

**Interview Questions (about your own project — practice for "walk me through a project"):** 1. Why generators here? 2. How does it handle bad input? 3. What's the memory profile? 4. How would you extend it to streaming logs (`tail -f`)? 5. Complexity of your top-5 computation — could a heap do better? 6. Why these classes and not one big function? 7. How did you test the parser? 8. What would you change for 10GB files? 9. What would production monitoring of this tool look like? 10. What are you most proud of in it?

**Communication Practice:** Record a 3-minute "project walkthrough" of LogLens: problem → design → key decisions → testing → what you'd improve. This exact format is how you should present projects in interviews forever.

**Daily Notes:** Post-mortem: what was easy, what was hard, what you looked up.

**Deliverables:** Working LogLens with tests + README + merged PR. This is portfolio piece #1.

**Bonus:** This tiny project quietly exercises: OOP, dunders, generators, exceptions, logging, argparse, stats, SQL, testing, typing, Git flow. That's the entire volume in one artifact.

---

### 🔁 WEEK 4 ADD-ONS (Tracks A + G + E)
**DSA quota:**
- LeetCode: **Maximum Subarray** (#53 — Kadane's, your first DP taste), **Top K Frequent Elements** (#347 — pairs perfectly with LogLens's top-5 feature: do it with a heap)
- NeetCode: **Kth Largest Element in a Stream** (heap consolidation)
- HackerRank: one **SQL** challenge (joins) — matches Day 14
- Plus Week-3 re-solves.

**Diagram of the week (two):** (1) LogLens architecture — file → generator → Parser → Analyzer → outputs/SQLite; (2) the cosine-similarity retrieval sketch from Day 12 (query vector vs document vectors).

**Open-source reading (Track E, August project):** this weekend or next week — clone FastAPI, find where `@app.get` registers a route, trace one request. You built the toy version on Day 3; now see the real one. Write your 1-page note.

**AI review ritual continues daily.**

---

### FRIDAY — 7 August 2026 — VOLUME 1 FINAL: Full Revision + Assessment + Mock Interview

0. **Track audit (whole volume):** ☐ 16 DSA problems attempted, failures re-solved ☐ 6 diagrams drawable from memory ☐ `ai_review_log.md` has 12+ lessons ☐ `prompt_patterns.md` has 4 patterns ☐ FastAPI source reading scheduled.

1. **Comprehensive revision (45 min):** All flashcards (should be ~80 by now); redo from memory: hashmap sketch, decorator template, binary search template, Bayes example, JOIN diagram.
2. **Final written self-test (45 min, closed book):**
   - Python: 10 predict-the-output questions from your Week 1 traps.
   - Coding: implement `@memoize`; merge two sorted lists; cosine similarity; softmax.
   - SQL: second-highest order value; products never ordered.
   - Linux/Git: 5 scenario questions each.
3. **Mock interview (30 min, recorded):** "Tell me about yourself" (polished 60s) → "Walk me through LogLens" (3 min) → "How does a dict work?" → "Rebase vs merge?" → "The disease-test Bayes question" → one live-coded problem (two-sum variant).
4. **Volume 1 scorecard — fill this honestly:**
   - Skills mastered (rate 1–5): Python internals ☐ OOP design ☐ Testing ☐ Algorithms ☐ Linux ☐ Git ☐ Linear algebra basics ☐ Probability ☐ SQL ☐ Communication ☐
   - Weak areas (list 3): ______
   - Time discipline: how many days did you complete fully? __/15
5. **Volume 2 readiness checklist:** ☐ LogLens complete ☐ 80+ flashcards ☐ All Friday assessments done ☐ Can pass a Python phone screen today ☐ HackerRank Python (Basic) cert earned ☐ Repo has 15+ meaningful commits.

### ➤ THEN COME BACK TO ME AND SAY: **"Take my Volume 1 test."**
I will run a live interview-style test (theory rapid-fire + a coding problem + you explaining LogLens). Based on your scorecard and test performance, I will generate **Volume 2: Machine Learning & Data Science** in full daily detail, adjusted to your weak areas — same format, dated **Mon 10 Aug – Fri 2 Oct 2026**.

---

## VOLUME 1 QUESTION BANKS (use across all Fridays; I will draw from these in your test)

**Python (sample 25 of the 100 — I'll test the rest live):** mutability traps, `is` vs `==`, GIL basics, list vs tuple, dict internals, hashability, shallow/deep copy, LEGB, closures, decorators, `*args/**kwargs`, generators vs lists, `__repr__` vs `__str__`, MRO, dataclasses, ABCs, context managers, exception chaining, `else` in try, logging levels, fixtures, parametrize, type hints at runtime, GIL & threading vs multiprocessing (concept level), `if __name__ == "__main__"`.

**SQL (sample 12 of 50):** join types, WHERE vs HAVING, NULL semantics, duplicates query, Nth-highest, indexes & trade-offs, CTEs, subquery vs join, GROUP BY rules, keys, normalization, EXPLAIN basics.

**Linux (sample 12 of 50):** chmod octal, pipes/redirection, find vs grep, processes & signals, tail -f, PATH, env vars, ssh keys, lsof/ports, disk usage (du/df), cron basics, package management.

**Git (sample 12 of 50):** object model, branch = pointer, merge vs rebase, reset variants, reflog recovery, detached HEAD, stash, cherry-pick, fetch vs pull, .gitignore, squash, PR etiquette.

**Behavioral (10 of 20 — prepare STAR stories):** tell me about yourself; a hard bug; a disagreement; a deadline; a failure and lesson; learning something fast; receiving tough feedback; a design decision you'd redo; why AI engineering; why our company.

---

## RULES OF THE PROGRAM (read every Monday)

1. **Solve first, AI reviews after.** No AI assistance while solving — documentation only; that dependency is the weakness this program removes. Once your solution works and is committed, use AI as a code reviewer (bugs, optimizations, alternatives) and log one lesson in `ai_review_log.md`.
1b. **The weekly DSA quota (2 LeetCode + 1 NeetCode + 1 HackerRank) never pauses.** It runs every learning week of all 6 volumes. Volume tests always include a live DSA problem.
2. **Ship daily.** A committed, tested, small thing beats an unfinished ambitious thing.
3. **Speak daily.** The 10-minute communication practice is not optional — interviews are won out loud.
4. **Never study on Sat/Sun.** Rest is part of the schedule. Burnout is the #1 program-killer.
5. **If you miss a day**, do NOT double up. Shift the plan by one day and tell me at the volume test so I adjust dates.
6. **Come back after every volume for your test.** That accountability loop is what turns a document into a transformation.

*— Your Curriculum Architect. See you on 7 August for the Volume 1 test.*