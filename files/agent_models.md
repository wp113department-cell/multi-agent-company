Agent Assignment Table
Agent	Primary Work	Provider	Recommended Model	Reason
accessibility_agent	Accessibility audit	OpenAI	GPT-5.5	Great structured analysis
agent_result	Result formatting	OpenAI	GPT-5.5	JSON formatting
ai_engineer	AI system implementation	Claude	Claude Sonnet 4	Strong AI reasoning
api_designer_agent	API architecture	OpenAI	GPT-5.5	Excellent OpenAPI/tool generation
api_docs_agent	API documentation	Claude	Claude Sonnet 4	Better documentation writing
architect	System architecture	Claude	Claude Opus 4.1	Highest reasoning
architecture_reviewer	Review architecture	Claude	Claude Opus 4.1	Deep review
backend_dev	Backend coding	OpenAI	GPT-5.5	Strong coding
base	Shared utilities	OpenAI	GPT-5.5	Simple
base_graph	Graph orchestration	Claude	Claude Sonnet 4	Better graph reasoning
bug_fix	Fix bugs	OpenAI	GPT-5.5	Excellent debugging
business_analyst	Requirement analysis	Claude	Claude Sonnet 4	Business reasoning
changelog_agent	Generate changelog	Claude	Claude Sonnet 4	Better summaries
chat_agent	User conversations	OpenAI	GPT-5.5	Fast responses
cicd_agent	CI/CD pipelines	OpenAI	GPT-5.5	YAML generation
cleanup_agent	Code cleanup	OpenAI	GPT-5.5	Fast refactoring
code_explainer_agent	Explain code	Claude	Claude Sonnet 4	Better explanations
code_quality_agent	Code quality	Claude	Claude Sonnet 4	Better review
coder	Main implementation	OpenAI	GPT-5.5	Strongest coding workflow
compliance_agent	Compliance	Claude	Claude Sonnet 4	Careful reasoning
cost_estimator_agent	Cost estimation	Claude	Claude Sonnet 4	Analytical reasoning
data_pipeline_agent	ETL/Pipeline	OpenAI	GPT-5.5	Data implementation
database_architect	Database design	Claude	Claude Sonnet 4	Schema reasoning
debugger_agent	Debugging	OpenAI	GPT-5.5	Excellent debugging
decomposer	Task decomposition	Claude	Claude Opus 4.1	Complex planning
dependency_agent	Dependency analysis	OpenAI	GPT-5.5	Structured output
dependency_security_agent	Package security	Claude	Claude Sonnet 4	Security reasoning
devex_agent	Developer experience	Claude	Claude Sonnet 4	Workflow optimization
devops	Infrastructure	OpenAI	GPT-5.5	IaC generation
docker_agent	Docker	OpenAI	GPT-5.5	Docker expertise
docs	Documentation	Claude	Claude Sonnet 4	Better writing
env_checker_agent	Environment validation	OpenAI	GPT-5.5	Simple checks
evaluation_agent	Evaluate outputs	Claude	Claude Sonnet 4	Better judgment
executive	Executive decisions	Claude	Claude Opus 4.1	Strategic reasoning
feature_flag_agent	Feature flags	OpenAI	GPT-5.5	Configuration
frontend_dev	Frontend coding	OpenAI	GPT-5.5	React/UI coding
groq_adapter	Adapter	OpenAI	GPT-5.5	Simple implementation
guardrails	Safety rules	Claude	Claude Sonnet 4	Policy reasoning
incident_responder_agent	Incident response	Claude	Claude Sonnet 4	Critical analysis
infra_agent	Infrastructure	OpenAI	GPT-5.5	Terraform/K8s
load_test_agent	Load testing	OpenAI	GPT-5.5	Test generation
localization_agent	Translation	Claude	Claude Sonnet 4	Better multilingual quality
manager	Task manager	Claude	Claude Opus 4.1	Multi-agent coordination
migration_agent	Migration planning	Claude	Claude Sonnet 4	Migration reasoning
monitoring_agent	Monitoring	OpenAI	GPT-5.5	Config generation
onboarding_agent	Onboarding docs	Claude	Claude Sonnet 4	Better writing
pair_programmer_agent	Pair programming	Claude	Claude Sonnet 4	Interactive reasoning
performance_reviewer	Performance review	Claude	Claude Sonnet 4	Optimization analysis
planner	Project planning	Claude	Claude Opus 4.1	Long-horizon planning
pm	Product manager	Claude	Claude Sonnet 4	Product reasoning
qa	QA	OpenAI	GPT-5.5	Test execution
rag_engineer_agent	RAG systems	Claude	Claude Opus 4.1	Retrieval reasoning
readme_agent	README writing	Claude	Claude Sonnet 4	Excellent documentation
refactor_agent	Refactoring	Claude	Claude Sonnet 4	Safer refactoring
release_notes_agent	Release notes	Claude	Claude Sonnet 4	Better summaries
research	Technical research	Claude	Claude Opus 4.1	Deep investigation
reviewer	PR review	Claude	Claude Sonnet 4	Thorough reviews
rollback_agent	Rollback plans	Claude	Claude Sonnet 4	Risk analysis
runbook_generator_agent	Runbooks	Claude	Claude Sonnet 4	Operational documentation
schema_agent	Schema generation	OpenAI	GPT-5.5	Structured generation
security_architect	Security architecture	Claude	Claude Opus 4.1	Deep security reasoning
security_reviewer	Security review	Claude	Claude Sonnet 4	Security auditing
slo_agent	SLO generation	Claude	Claude Sonnet 4	Reliability planning
spike_agent	Technical spikes	Claude	Claude Sonnet 4	Exploratory reasoning
sprint_planner	Sprint planning	Claude	Claude Sonnet 4	Planning
sql_agent	SQL generation	OpenAI	GPT-5.5	SQL generation
style_reviewer	Style review	Claude	Claude Sonnet 4	Better style judgment
tech_debt_agent	Tech debt	Claude	Claude Sonnet 4	Long-term reasoning
test_coverage_agent	Coverage analysis	OpenAI	GPT-5.5	Code analysis
test_writer_agent	Test generation	OpenAI	GPT-5.5	Excellent test creation
tools	Tool execution	OpenAI	GPT-5.5	Function calling
user_story_generator	User stories	Claude	Claude Sonnet 4	Product writing
version_manager_agent	Version management	OpenAI	GPT-5.5	Semantic versioning
Overall Distribution
Provider	Number of Agents	Best Use
Claude	39	Architecture, planning, review, reasoning, documentation, security
OpenAI	29	Coding, APIs, tools, JSON, SQL, implementation, execution
Production Routing Rules

Instead of hardcoding models per agent, define capability-based routing:

Capability	Model
Strategic architecture	Claude Opus 4.1
Multi-agent planning	Claude Opus 4.1
Research	Claude Opus 4.1
Security architecture	Claude Opus 4.1
RAG design	Claude Opus 4.1
Code generation	GPT-5.5
Backend implementation	GPT-5.5
Frontend implementation	GPT-5.5
SQL generation	GPT-5.5
API generation	GPT-5.5
Tool calling	GPT-5.5
Documentation	Claude Sonnet 4
Code review	Claude Sonnet 4
Refactoring	Claude Sonnet 4
Planning	Claude Sonnet 4 (or Opus 4.1 for especially complex tasks)
Debugging	GPT-5.5