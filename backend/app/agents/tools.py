"""Standard tool definitions and handlers for agent use."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.agents.tool_security import (
    _docker_container_risk_reason as _docker_container_risk_reason,
    _extract_patch_target_paths as _extract_patch_target_paths,
    _is_dangerous_command as _is_dangerous_command,
    _is_protected_path as _is_protected_path,
    _mask_secret_value as _mask_secret_value,
    _redact_secrets_in_text as _redact_secrets_in_text,
    _scan_content_for_secrets as _scan_content_for_secrets,
    _shell_metachar_reason as _shell_metachar_reason,
    _ssrf_denial_reason as _ssrf_denial_reason,
    _summarize_docker_log_patterns as _summarize_docker_log_patterns,
)
from app.agents.monitoring_handlers import (
    make_monitoring_agent_handlers as make_monitoring_agent_handlers,
)
from app.config import get_settings
from app.policy.engine import (
    check_allowlisted_command,
    check_command,
    check_command_stays_in_boundary,
    check_path_in_worktree,
)

# tool_enhance.md productionization pass, tool #1 (bash), 2026-08-15 — the
# FIRST step of this file's own gradual modularization (§7/§8). Real
# migration report: app/tools/execution/bash.py's own module docstring.
# Compatibility shim (§9): every name below still resolves via
# `from app.agents.tools import X` exactly as before this move — owner =
# this productionization pass, reason = avoid a repo-wide mechanical edit
# across every agent file that imports these names for a move that doesn't
# change behavior, migration target = agent files import directly from
# app.tools.execution.bash at a later, separate, per-caller-verified pass,
# removal condition = every real caller individually confirmed migrated.
from app.tools.execution.bash import (
    DEPENDENCY_AUDIT_ALLOWED_PREFIXES as DEPENDENCY_AUDIT_ALLOWED_PREFIXES,
    DEPENDENCY_AUDIT_BASH_TOOL as DEPENDENCY_AUDIT_BASH_TOOL,
    INFRA_DRY_RUN_ALLOWED_PREFIXES as INFRA_DRY_RUN_ALLOWED_PREFIXES,
    INFRA_DRY_RUN_BASH_TOOL as INFRA_DRY_RUN_BASH_TOOL,
    LOAD_TEST_ALLOWED_PREFIXES as LOAD_TEST_ALLOWED_PREFIXES,
    LOAD_TEST_BASH_TOOL as LOAD_TEST_BASH_TOOL,
    TEST_RUNNER_ALLOWED_PREFIXES as TEST_RUNNER_ALLOWED_PREFIXES,
    TEST_RUNNER_BASH_TOOL as TEST_RUNNER_BASH_TOOL,
    _FLEET_BASH_TOOL as _FLEET_BASH_TOOL,
    _run_bash_command as _run_bash_command,
    make_dependency_audit_bash_handler as make_dependency_audit_bash_handler,
    make_infra_dry_run_bash_handler as make_infra_dry_run_bash_handler,
    make_load_test_bash_handler as make_load_test_bash_handler,
    make_scoped_bash_handler as make_scoped_bash_handler,
    make_test_runner_bash_handler as make_test_runner_bash_handler,
)
from app.tools.browser.browser_tools import (
    BROWSER_CLICK_TOOL as _BROWSER_CLICK_TOOL,
    BROWSER_CLOSE_TOOL as _BROWSER_CLOSE_TOOL,
    BROWSER_NAVIGATE_TOOL as _BROWSER_NAVIGATE_TOOL,
    BROWSER_OPEN_TOOL as _BROWSER_OPEN_TOOL,
    BROWSER_READ_DOM_TOOL as _BROWSER_READ_DOM_TOOL,
    BROWSER_SCREENSHOT_TOOL as _BROWSER_SCREENSHOT_TOOL,
    BROWSER_TYPE_TOOL as _BROWSER_TYPE_TOOL,
    browser_click_handler as browser_click_handler,
    browser_close_handler as browser_close_handler,
    browser_navigate_handler as browser_navigate_handler,
    browser_open_handler as browser_open_handler,
    browser_read_dom_handler as browser_read_dom_handler,
    browser_screenshot_handler as browser_screenshot_handler,
    browser_type_handler as browser_type_handler,
)
from app.tools.agents.bhaskar_tool import (
    BHASKAR_TOOL as BHASKAR_TOOL,
    bhaskar_tool_handler as bhaskar_tool_handler,
)
from app.tools.agents.delegate import (
    DELEGATE_TO_AGENT_TOOL as _DELEGATE_TO_AGENT_TOOL,
    make_delegate_to_agent_handler as make_delegate_to_agent_handler,
)
from app.tools.agents.memory_write import (
    MEMORY_WRITE_TOOL as _MEMORY_WRITE_TOOL,
    write_memory_key as write_memory_key,
)
from app.tools.agents.propose_subtask import (
    PROPOSE_SUBTASK_TOOL as PROPOSE_SUBTASK_TOOL,
    make_propose_subtask_handler as make_propose_subtask_handler,
)
from app.tools.agents.record_learning import (
    RECORD_LEARNING_TOOL as RECORD_LEARNING_TOOL,
    make_record_learning_handler as make_record_learning_handler,
)
from app.tools.agents.record_preference import (
    RECORD_PREFERENCE_TOOL as RECORD_PREFERENCE_TOOL,
    make_record_preference_handler as make_record_preference_handler,
)
from app.tools.git.review_diff import (
    REVIEW_DIFF_TOOL,
    build_review_diff_args,
)
from app.tools.agents.submit_ai_result import (
    SUBMIT_AI_RESULT_TOOL,
    submit_ai_result_handler,
)
from app.tools.agents.submit_arch_review import (
    SUBMIT_ARCH_REVIEW_TOOL,
    submit_arch_review_handler,
)
from app.tools.agents.submit_ba_result import (
    SUBMIT_BA_RESULT_TOOL,
    submit_ba_result_handler,
)
from app.tools.agents.submit_cicd_report import (
    SUBMIT_CICD_REPORT_TOOL,
    submit_cicd_report_handler,
)
from app.tools.agents.submit_cleanup import (
    SUBMIT_CLEANUP_TOOL,
    submit_cleanup_handler,
)
from app.tools.agents.submit_dependency_report import (
    SUBMIT_DEPENDENCY_REPORT_TOOL,
    submit_dependency_report_handler,
)
from app.tools.agents.submit_docker_report import (
    SUBMIT_DOCKER_REPORT_TOOL,
    submit_docker_report_handler,
)
from app.tools.agents.submit_health_report import (
    SUBMIT_HEALTH_REPORT_TOOL,
    make_submit_health_report_handler,
)
from app.tools.agents.submit_migration import (
    SUBMIT_MIGRATION_TOOL,
    submit_migration_handler,
)
from app.tools.agents.submit_monitoring_report import (
    SUBMIT_MONITORING_REPORT_TOOL,
)
from app.tools.agents.submit_perf_review import (
    SUBMIT_PERF_REVIEW_TOOL,
    submit_perf_review_handler,
)
from app.tools.agents.submit_qa_result import (
    SUBMIT_QA_RESULT_TOOL,
    make_submit_qa_result_handler,
)
from app.tools.agents.submit_refactor_report import (
    SUBMIT_REFACTOR_REPORT_TOOL,
    submit_refactor_report_handler,
)
from app.tools.agents.submit_research import (
    SUBMIT_RESEARCH_TOOL,
    make_submit_research_handler,
)
from app.tools.agents.submit_result import (
    SUBMIT_RESULT_TOOL,
    submit_result_handler,
)
from app.tools.agents.submit_review import (
    SUBMIT_REVIEW_TOOL,
    make_submit_review_handler,
)
from app.tools.agents.submit_schema import (
    SUBMIT_SCHEMA_TOOL,
    submit_schema_handler,
)
from app.tools.agents.submit_security_report import (
    SUBMIT_SECURITY_REPORT_TOOL,
    submit_security_report_handler,
)
from app.tools.agents.submit_sprint_plan import (
    SUBMIT_SPRINT_PLAN_TOOL,
    submit_sprint_plan_handler,
)
from app.tools.agents.submit_sql_report import (
    SUBMIT_SQL_REPORT_TOOL,
    submit_sql_report_handler,
)
from app.tools.agents.submit_style_review import (
    SUBMIT_STYLE_REVIEW_TOOL,
    submit_style_review_handler,
)
from app.tools.agents.submit_tech_debt import (
    SUBMIT_TECH_DEBT_TOOL,
    submit_tech_debt_handler,
)
from app.tools.agents.request_clarification import (
    REQUEST_CLARIFICATION_TOOL as REQUEST_CLARIFICATION_TOOL,
    make_request_clarification_handler as make_request_clarification_handler,
)
from app.tools.agents.submit_docs import (
    SUBMIT_DOCS_TOOL,
    make_submit_docs_handler,
)
from app.tools.agents.submit_patch import (
    SUBMIT_PATCH_TOOL,
    make_submit_patch_handler,
)
from app.tools.database.migration import (
    RUN_MIGRATION_TOOL as _RUN_MIGRATION_TOOL,
    run_migration_handler as run_migration_handler,
    validate_run_migration_inputs as validate_run_migration_inputs,
)
from app.tools.database.seed import (
    SEED_DATABASE_TOOL as _SEED_DATABASE_TOOL,
    seed_database_handler as seed_database_handler,
    validate_seed_database_script as validate_seed_database_script,
)
from app.tools.execution.parallel import (
    RUN_PARALLEL_COMMANDS_TOOL as _RUN_PARALLEL_COMMANDS_TOOL,
    run_parallel_commands_handler as run_parallel_commands_handler,
)
from app.tools.database.sql import (
    RUN_SQL_TOOL as _RUN_SQL_TOOL,
    run_sql_handler as run_sql_handler,
)
from app.tools.execution.docker_build import (
    DOCKER_BUILD_TOOL as _DOCKER_BUILD_TOOL,
    validate_docker_build_inputs as validate_docker_build_inputs,
)
from app.tools.execution.docker_compose import (
    DOCKER_COMPOSE_TOOL as _DOCKER_COMPOSE_TOOL,
    build_docker_compose_command as build_docker_compose_command,
)
from app.tools.execution.fetch_url import (
    FETCH_URL_TOOL,
    fetch_url_handler,
)
from app.tools.execution.docker_exec import (
    DOCKER_EXEC_TOOL as _DOCKER_EXEC_TOOL,
    build_docker_exec_command as build_docker_exec_command,
)
from app.tools.execution.docker_restart import (
    DOCKER_RESTART_TOOL as _DOCKER_RESTART_TOOL,
    build_docker_restart_command as build_docker_restart_command,
)
from app.tools.execution.kill_process import (
    KILL_PROCESS_TOOL as _KILL_PROCESS_TOOL,
)
from app.tools.execution.npm_install import (
    NPM_INSTALL_TOOL as _NPM_INSTALL_TOOL,
)
from app.tools.execution.npm_run import (
    NPM_RUN_TOOL as _NPM_RUN_TOOL,
)
from app.tools.execution.pip_install import (
    PIP_INSTALL_TOOL as _PIP_INSTALL_TOOL,
)
from app.tools.execution.python_snippet import (
    RUN_PYTHON_SNIPPET_TOOL as _RUN_PYTHON_SNIPPET_TOOL,
    run_python_snippet_handler as run_python_snippet_handler,
)
from app.tools.execution.run_background import (
    RUN_BACKGROUND_TOOL,
    validate_run_background_cwd as validate_run_background_cwd,
)
from app.tools.execution.run_make import (
    RUN_MAKE_TOOL,
    run_make_handler,
)
from app.tools.execution.run_node import (
    RUN_NODE_TOOL,
    run_node_handler,
)
from app.tools.execution.run_script import (
    RUN_SCRIPT_TOOL,
    run_script_handler,
)
from app.tools.execution.run_single_test import (
    RUN_SINGLE_TEST_TOOL,
    run_single_test_handler,
)
from app.tools.execution.run_tests import (
    RUN_TESTS_TOOL as _RUN_TESTS_TOOL,
    run_tests_handler as run_tests_handler,
)
from app.tools.filesystem.append_file import (
    APPEND_FILE_TOOL as _APPEND_FILE_TOOL,
    append_file_handler as append_file_handler,
)
from app.tools.filesystem.list_deploy_artifacts import (
    LIST_DEPLOY_ARTIFACTS_TOOL,
    make_list_deploy_artifacts_handler as make_list_deploy_artifacts_handler,
)
from app.tools.filesystem.list_migrations import (
    LIST_MIGRATIONS_TOOL,
    list_migrations_handler,
)
from app.tools.filesystem.delete_block import (
    DELETE_BLOCK_TOOL as _DELETE_BLOCK_TOOL,
    delete_block_handler as delete_block_handler,
)
from app.tools.filesystem.delete_lines import (
    DELETE_LINES_TOOL as _DELETE_LINES_TOOL,
    delete_lines_handler as delete_lines_handler,
)
from app.tools.filesystem.apply_patch import (
    APPLY_PATCH_TOOL as _APPLY_PATCH_TOOL_DEF,
    apply_patch_handler as apply_patch_handler,
)
from app.tools.filesystem.delete_file import (
    DELETE_FILE_TOOL as _DELETE_FILE_TOOL,
    delete_file_handler as delete_file_handler,
)
from app.tools.filesystem.edit_file import (
    EDIT_FILE_TOOL as _EDIT_FILE_TOOL,
    edit_file_handler as edit_file_handler,
)
from app.tools.filesystem.insert_after import (
    INSERT_AFTER_TOOL as _INSERT_AFTER_TOOL,
    insert_after_handler as insert_after_handler,
)
from app.tools.filesystem.insert_at_line import (
    INSERT_AT_LINE_TOOL as _INSERT_AT_LINE_TOOL,
    insert_at_line_handler as insert_at_line_handler,
)
from app.tools.filesystem.insert_before import (
    INSERT_BEFORE_TOOL as _INSERT_BEFORE_TOOL,
    insert_before_handler as insert_before_handler,
)
from app.tools.filesystem.analyze_file import (
    ANALYZE_FILE_TOOL,
    analyze_file_handler,
)
from app.tools.filesystem.find_api import (
    FIND_API_TOOL as _FIND_API_TOOL,
    find_api_handler,
)
from app.tools.filesystem.find_route import (
    FIND_ROUTE_TOOL as _FIND_ROUTE_TOOL,
    find_route_handler,
)
from app.tools.filesystem.find_sql import (
    FIND_SQL_TOOL as _FIND_SQL_TOOL,
    find_sql_handler,
)
from app.tools.filesystem.call_graph import (
    CALL_GRAPH_TOOL,
    call_graph_handler,
)
from app.tools.filesystem.dead_code_detect import (
    DEAD_CODE_DETECT_TOOL,
    dead_code_detect_handler,
)
from app.tools.filesystem.scan_code_hygiene import (
    SCAN_CODE_HYGIENE_TOOL,
    scan_code_hygiene_handler,
)
from app.tools.filesystem.scan_reliability import (
    SCAN_RELIABILITY_TOOL,
    scan_reliability_handler,
)
from app.tools.filesystem.import_graph import (
    IMPORT_GRAPH_TOOL,
    import_graph_handler,
)
from app.tools.database.inspect_schema import (
    INSPECT_SCHEMA_TOOL,
    inspect_schema_handler,
)
from app.tools.filesystem.circular_dep_detect import (
    CIRCULAR_DEP_DETECT_TOOL,
    circular_dep_detect_handler,
)
from app.tools.database.explain_query import (
    EXPLAIN_QUERY_TOOL,
    explain_query_handler,
)
from app.tools.database.task_history_query import (
    TASK_HISTORY_QUERY_TOOL,
    task_history_query as task_history_query,
)
from app.tools.database.task_progress import (
    TASK_PROGRESS_TOOL,
    task_progress_handler,
)
from app.tools.filesystem.find_config import (
    FIND_CONFIG_TOOL,
    find_config_handler,
)
from app.tools.git.generate_changelog import (
    GENERATE_CHANGELOG_TOOL,
    generate_changelog_handler,
)
from app.tools.execution.run_linter import (
    RUN_LINTER_TOOL,
    run_linter_handler,
)
from app.tools.filesystem.secrets_scan import (
    SECRETS_SCAN_TOOL,
    secrets_scan_handler,
)
from app.tools.execution.check_license_compliance import (
    CHECK_LICENSE_COMPLIANCE_TOOL,
    check_license_compliance_handler,
)
from app.tools.execution.check_target_repo_license_compliance import (
    CHECK_TARGET_REPO_LICENSE_COMPLIANCE_TOOL,
    check_target_repo_license_compliance_handler,
)
from app.tools.execution.coverage_report import (
    COVERAGE_REPORT_TOOL,
    coverage_report_handler,
)
from app.tools.execution.cpu_usage import (
    CPU_USAGE_TOOL,
    cpu_usage_handler,
)
from app.tools.execution.diagnose_deployment_failure import (
    DIAGNOSE_DEPLOYMENT_FAILURE_TOOL,
    gather_deployment_diagnostics,
)
from app.tools.execution.disk_usage import (
    DISK_USAGE_TOOL,
    disk_usage_handler,
)
from app.tools.execution.docker_logs import (
    DOCKER_LOGS_TOOL,
    docker_logs_handler,
)
from app.tools.execution.analyze_error import (
    ANALYZE_ERROR_TOOL,
    analyze_error_handler,
)
from app.tools.execution.check_url_status import (
    CHECK_URL_STATUS_TOOL,
    check_url_status_handler,
)
from app.tools.execution.cpu_profile import (
    CPU_PROFILE_TOOL,
    cpu_profile_handler,
)
from app.tools.execution.deps_outdated import (
    DEPS_OUTDATED_TOOL,
    deps_outdated_handler,
)
from app.tools.execution.find_unused_imports import (
    FIND_UNUSED_IMPORTS_TOOL,
    find_unused_imports_handler,
)
from app.tools.execution.docker_ps import (
    DOCKER_PS_TOOL,
    docker_ps_handler,
)
from app.tools.execution.read_logs import (
    READ_LOGS_TOOL,
    read_logs_handler,
)
from app.tools.execution.estimate_complexity import (
    ESTIMATE_COMPLEXITY_TOOL,
    estimate_complexity_handler,
)
from app.tools.filesystem.find_function_body import (
    FIND_FUNCTION_BODY_TOOL,
    find_function_body_handler,
)
from app.tools.git.generate_release_notes import (
    GENERATE_RELEASE_NOTES_TOOL,
    generate_release_notes_handler,
)
from app.tools.execution.health_check import (
    HEALTH_CHECK_TOOL,
    health_check_handler,
)
from app.tools.execution.memory_usage import (
    MEMORY_USAGE_TOOL,
    memory_usage_handler,
)
from app.tools.filesystem.file_exists import (
    FILE_EXISTS_TOOL,
    file_exists_handler,
)
from app.tools.filesystem.organize_imports import (
    ORGANIZE_IMPORTS_TOOL,
    organize_imports_handler,
)
from app.tools.filesystem.yaml_validate import (
    YAML_VALIDATE_TOOL,
    yaml_validate_handler,
)
from app.tools.filesystem.base64_encode import (
    BASE64_ENCODE_TOOL,
    base64_encode_handler,
)
from app.tools.filesystem.compare_files import (
    COMPARE_FILES_TOOL,
    compare_files_handler,
)
from app.tools.filesystem.copy_file import (
    COPY_FILE_TOOL,
    copy_file_handler,
)
from app.tools.filesystem.count_lines import (
    COUNT_LINES_TOOL,
    count_lines_handler,
)
from app.tools.filesystem.create_directory import (
    CREATE_DIRECTORY_TOOL,
    create_directory_handler,
)
from app.tools.filesystem.csv_preview import (
    CSV_PREVIEW_TOOL,
    csv_preview_handler,
)
from app.tools.filesystem.env_diff import (
    ENV_DIFF_TOOL,
    env_diff_handler,
)
from app.tools.git.explain_merge_conflict import (
    EXPLAIN_MERGE_CONFLICT_TOOL,
    explain_merge_conflict_handler,
)
from app.tools.git.parse_merge_conflicts import (
    PARSE_MERGE_CONFLICTS_TOOL,
    parse_merge_conflicts_handler,
)
from app.tools.git.resolve_merge_conflict import (
    RESOLVE_MERGE_CONFLICT_TOOL,
    resolve_merge_conflict_handler,
)
from app.tools.filesystem.export_markdown import (
    EXPORT_MARKDOWN_TOOL,
    export_markdown_handler,
)
from app.tools.filesystem.find_file import (
    FIND_FILE_TOOL,
    find_file_handler,
)
from app.tools.filesystem.find_queue import (
    FIND_QUEUE_TOOL,
    find_queue_handler,
)
from app.tools.filesystem.find_test import (
    FIND_TEST_TOOL,
    find_test_handler,
)
from app.tools.filesystem.find_worker import (
    FIND_WORKER_TOOL,
    find_worker_handler,
)
from app.tools.filesystem.format_file import (
    FORMAT_FILE_TOOL,
    format_file_handler,
)
from app.tools.filesystem.generate_api_docs_text import (
    GENERATE_API_DOCS_TEXT_TOOL,
    generate_api_docs_text_handler,
)
from app.tools.filesystem.summarize_folder import (
    SUMMARIZE_FOLDER_TOOL,
    summarize_folder_handler,
)
from app.tools.filesystem.summarize_output import (
    SUMMARIZE_OUTPUT_TOOL,
    summarize_output_handler,
)
from app.tools.filesystem.summarize_repo import (
    SUMMARIZE_REPO_TOOL,
    summarize_repo_handler,
)
from app.tools.filesystem.template_render import (
    TEMPLATE_RENDER_TOOL,
    template_render_handler,
)
from app.tools.execution.type_check import (
    TYPE_CHECK_TOOL,
    type_check_handler,
)
from app.tools.filesystem.unzip_files import (
    UNZIP_FILES_TOOL,
    unzip_files_handler,
)
from app.tools.execution.wait_for_port import (
    WAIT_FOR_PORT_TOOL,
    wait_for_port_handler,
)
from app.tools.filesystem.xml_validate import (
    XML_VALIDATE_TOOL,
    xml_validate_handler,
)
from app.tools.filesystem.zip_files import (
    ZIP_FILES_TOOL,
    zip_files_handler,
)
from app.tools.git.generate_commit_msg import (
    GENERATE_COMMIT_MSG_TOOL,
    generate_commit_msg_handler,
)
from app.tools.filesystem.generate_diagram import (
    GENERATE_DIAGRAM_TOOL,
    generate_diagram_handler,
)
from app.tools.filesystem.generate_patch import (
    GENERATE_PATCH_TOOL,
    generate_patch_handler,
)
from app.tools.git.branch import (
    GIT_BRANCH_TOOL,
    git_branch_handler,
)
from app.tools.git.fetch import (
    GIT_FETCH_TOOL,
    git_fetch_handler,
)
from app.tools.git.log_file import (
    GIT_LOG_FILE_TOOL,
    git_log_file_handler,
)
from app.tools.git.stash_list import (
    GIT_STASH_LIST_TOOL,
    git_stash_list_handler,
)
from app.tools.integrations.github_inspect_repo import (
    GITHUB_INSPECT_REPO_TOOL,
    github_inspect_repo_handler,
)
from app.tools.git.github_list_prs import (
    GITHUB_LIST_PRS_TOOL,
    github_list_prs_handler,
)
from app.tools.filesystem.hash_file import (
    HASH_FILE_TOOL,
    hash_file_handler,
)
from app.tools.integrations.http_request import (
    HTTP_REQUEST_TOOL,
    http_request_handler,
)
from app.tools.integrations.check_last_release import (
    CHECK_LAST_RELEASE_TOOL,
    check_last_release_handler,
)
from app.tools.integrations.check_dependency_conflicts import (
    CHECK_DEPENDENCY_CONFLICTS_TOOL,
    check_dependency_conflicts_handler,
)
from app.tools.integrations.inspect_github_repo import (
    INSPECT_GITHUB_REPO_TOOL,
    inspect_github_repo_handler,
)
from app.tools.integrations.inspect_openapi_spec import (
    INSPECT_OPENAPI_SPEC_TOOL,
    inspect_openapi_spec_handler,
)
from app.tools.filesystem.json_query import (
    JSON_QUERY_TOOL,
    json_query_handler,
)
from app.tools.filesystem.json_validate import (
    JSON_VALIDATE_TOOL,
    json_validate_handler,
)
from app.tools.agents.known_issues_read import (
    KNOWN_ISSUES_READ_TOOL,
    known_issues_read_handler,
)
from app.tools.agents.known_issues_write import (
    KNOWN_ISSUES_WRITE_TOOL,
    known_issues_write_handler,
)
from app.tools.execution.list_background_processes import (
    LIST_BACKGROUND_PROCESSES_TOOL,
    list_background_processes_handler,
)
from app.tools.execution.list_env_vars import (
    LIST_ENV_VARS_TOOL,
    list_env_vars_handler,
)
from app.tools.execution.list_open_ports import (
    LIST_OPEN_PORTS_TOOL,
    list_open_ports_handler,
)
from app.tools.execution.list_processes import (
    LIST_PROCESSES_TOOL,
    list_processes_handler,
)
from app.tools.execution.loc_stats import (
    LOC_STATS_TOOL,
    loc_stats_handler,
)
from app.tools.agents.memory_read import (
    MEMORY_READ_TOOL,
    memory_read_handler,
)
from app.tools.database.mermaid_from_schema import (
    MERMAID_FROM_SCHEMA_TOOL,
    mermaid_from_schema_handler,
)
from app.tools.filesystem.openapi_inspect import (
    OPENAPI_INSPECT_TOOL,
    openapi_inspect_handler,
)
from app.tools.filesystem.parse_docker_compose import (
    PARSE_DOCKER_COMPOSE_TOOL,
    parse_docker_compose_handler,
)
from app.tools.filesystem.parse_dockerfile import (
    PARSE_DOCKERFILE_TOOL,
    parse_dockerfile_handler,
)
from app.tools.execution.pip_list import (
    PIP_LIST_TOOL,
    pip_list_handler,
)
from app.tools.execution.read_env_var import (
    READ_ENV_VAR_TOOL,
    read_env_var_handler,
)
from app.tools.filesystem.read_image import (
    READ_IMAGE_TOOL,
    read_image_handler,
)
from app.tools.filesystem.read_notebook import (
    READ_NOTEBOOK_TOOL,
    read_notebook_handler,
)
from app.tools.execution.read_output import (
    READ_OUTPUT_TOOL,
    read_output_handler,
)
from app.tools.filesystem.read_pdf import (
    READ_PDF_TOOL,
    read_pdf_handler,
)
from app.tools.agents.decision_log_append import (
    DECISION_LOG_APPEND_TOOL,
    decision_log_append_handler,
)
from app.tools.agents.memory_search import (
    MEMORY_SEARCH_TOOL,
    memory_search_handler,
)
from app.tools.agents.submit_bug_fix import (
    SUBMIT_BUG_FIX_TOOL,
    submit_bug_fix_handler,
)
from app.tools.agents.capability_gap_scan import (
    CAPABILITY_GAP_SCAN_TOOL,
    capability_gap_scan_handler,
)
from app.tools.agents.fleet_metrics_read import (
    FLEET_METRICS_READ_TOOL,
    fleet_metrics_read_handler,
)
from app.tools.agents.audit_log_read import (
    AUDIT_LOG_READ_TOOL,
    audit_log_read_handler,
)
from app.tools.agents.list_registered_agents import (
    LIST_REGISTERED_AGENTS_TOOL,
    list_registered_agents_handler,
)
from app.tools.agents.memory_curate_read import (
    MEMORY_CURATE_READ_TOOL,
    memory_curate_read_handler,
)
from app.tools.agents.memory_curate_write import (
    MEMORY_CURATE_WRITE_TOOL,
    memory_curate_write_handler,
)
from app.tools.agents.memory_list_draft_lessons import (
    MEMORY_LIST_DRAFT_LESSONS_TOOL,
    memory_list_draft_lessons_handler,
)
from app.tools.agents.memory_promote_lesson import (
    MEMORY_PROMOTE_LESSON_TOOL,
    memory_promote_lesson_handler,
)
from app.tools.agents.submit_enhancement_request import (
    SUBMIT_ENHANCEMENT_REQUEST_TOOL,
    make_submit_enhancement_request_handler as make_submit_enhancement_request_handler,
)
from app.tools.filesystem.file_info import (
    FILE_INFO_TOOL,
    file_info_handler,
)
from app.tools.filesystem.find_references import (
    FIND_REFERENCES_TOOL,
    find_references_handler,
)
from app.tools.filesystem.find_todos import (
    FIND_TODOS_TOOL,
    find_todos_handler,
)
from app.tools.filesystem.search_imports import (
    SEARCH_IMPORTS_TOOL,
    search_imports_handler,
)
from app.tools.filesystem.get_file_tree import (
    GET_FILE_TREE_TOOL,
    get_file_tree_handler,
)
from app.tools.filesystem.list_classes import (
    LIST_CLASSES_TOOL,
    list_classes_handler,
)
from app.tools.filesystem.list_files import (
    LIST_FILES_TOOL,
    list_files_handler,
)
from app.tools.filesystem.list_functions import (
    LIST_FUNCTIONS_TOOL,
    list_functions_handler,
)
from app.tools.filesystem.parse_ast import (
    PARSE_AST_TOOL,
    parse_ast_handler,
)
from app.tools.filesystem.search_code import (
    SEARCH_CODE_TOOL,
    search_code_handler,
)
from app.tools.filesystem.search_symbols import (
    SEARCH_SYMBOLS_TOOL,
    search_symbols_handler,
)
from app.tools.filesystem.read_file import (
    READ_FILE_TOOL,
    read_file_handler,
)
from app.tools.filesystem.read_files import (
    READ_FILES_TOOL,
    read_files_handler,
)
from app.tools.filesystem.move_file import (
    MOVE_FILE_TOOL as _MOVE_FILE_TOOL,
    move_file_handler as move_file_handler,
)
from app.tools.filesystem.rename_file import (
    RENAME_FILE_TOOL as _RENAME_FILE_TOOL,
    rename_file_handler as rename_file_handler,
)
from app.tools.filesystem.replace_class import (
    REPLACE_CLASS_TOOL as _REPLACE_CLASS_TOOL,
    replace_class_handler as replace_class_handler,
)
from app.tools.filesystem.replace_function import (
    REPLACE_FUNCTION_TOOL as _REPLACE_FUNCTION_TOOL,
    replace_function_handler as replace_function_handler,
)
from app.tools.filesystem.semver_bump import (
    SEMVER_BUMP_TOOL,
    semver_bump_handler as semver_bump_handler,
)
from app.tools.filesystem.sync_files import (
    SYNC_FILES_TOOL,
    sync_files_handler,
)
from app.tools.filesystem.write_file import (
    WRITE_FILE_TOOL as _WRITE_FILE_TOOL,
    write_file_handler as write_file_handler,
)
from app.tools.git.blame import (
    GIT_BLAME_TOOL,
    git_blame_handler,
)
from app.tools.git.checkout import (
    GIT_CHECKOUT_TOOL as _GIT_CHECKOUT_TOOL,
    validate_git_checkout_inputs as validate_git_checkout_inputs,
)
from app.tools.git.cherry_pick import (
    GIT_CHERRY_PICK_TOOL as _GIT_CHERRY_PICK_TOOL,
    validate_git_cherry_pick_inputs as validate_git_cherry_pick_inputs,
)
from app.tools.git.commit import (
    GIT_COMMIT_TOOL as _GIT_COMMIT_TOOL,
    stage_and_commit as stage_and_commit,
)
from app.tools.git.commit_change import (
    GIT_COMMIT_CHANGE_TOOL,
    make_git_commit_change_handler as make_git_commit_change_handler,
)
from app.tools.git.create_branch import (
    CREATE_BRANCH_TOOL as _CREATE_BRANCH_TOOL,
    validate_create_branch_inputs as validate_create_branch_inputs,
)
from app.tools.git.diff import (
    GIT_DIFF_TOOL,
    git_diff_handler,
)
from app.tools.git.github_comment import (
    GITHUB_COMMENT_TOOL as _GITHUB_COMMENT_TOOL,
    github_comment_command as github_comment_command,
)
from app.tools.git.github_create_issue import (
    GITHUB_CREATE_ISSUE_TOOL as _GITHUB_CREATE_ISSUE_TOOL,
    github_create_issue_command as github_create_issue_command,
)
from app.tools.git.log import (
    GIT_LOG_TOOL,
    git_log_handler,
)
from app.tools.git.merge import (
    GIT_MERGE_TOOL as _GIT_MERGE_TOOL,
    validate_git_merge_inputs as validate_git_merge_inputs,
)
from app.tools.git.pull import (
    GIT_PULL_TOOL as _GIT_PULL_TOOL,
    validate_git_pull_inputs as validate_git_pull_inputs,
)
from app.tools.git.pull_request import (
    CREATE_PR_TOOL as _CREATE_PR_TOOL,
    GITHUB_CREATE_PR_TOOL as _GITHUB_CREATE_PR_TOOL,
    create_pr_handler as create_pr_handler,
)
from app.tools.git.push import (
    GIT_PUSH_TOOL as _GIT_PUSH_TOOL,
    git_push_handler as git_push_handler,
)
from app.tools.git.rebase import (
    GIT_REBASE_TOOL as _GIT_REBASE_TOOL,
    validate_git_rebase_inputs as validate_git_rebase_inputs,
)
from app.tools.git.reset import (
    GIT_RESET_TOOL as _GIT_RESET_TOOL,
    git_reset_handler as git_reset_handler,
)
from app.tools.git.restore import GIT_RESTORE_TOOL as _GIT_RESTORE_TOOL
from app.tools.git.show import (
    GIT_SHOW_TOOL,
    git_show_handler,
)
from app.tools.git.status import (
    GIT_STATUS_TOOL,
    git_status_handler,
)
from app.tools.git.stash import (
    GIT_STASH_TOOL as _GIT_STASH_TOOL,
    validate_git_stash_action as validate_git_stash_action,
)
from app.tools.git.tag import (
    GIT_TAG_TOOL,
    git_tag_handler as git_tag_handler,
)
from app.tools.git.worktree import (
    GIT_WORKTREE_TOOL as _GIT_WORKTREE_TOOL,
    validate_git_worktree_inputs as validate_git_worktree_inputs,
)
from app.tools.integrations.linear_create_issue import (
    LINEAR_CREATE_ISSUE_TOOL as _LINEAR_CREATE_ISSUE_TOOL,
    create_linear_issue as create_linear_issue,
)
from app.tools.integrations.slack_send_message import (
    SLACK_SEND_MESSAGE_TOOL,
    send_slack_message,
)
from app.tools.integrations.web_search import (
    WEB_SEARCH_TOOL,
    web_search_handler as web_search_handler,
)
from app.tools.refactor.rename_symbol import (
    RENAME_SYMBOL_TOOL as _RENAME_SYMBOL_TOOL,
    validate_rename_symbol_directory as validate_rename_symbol_directory,
)
from app.tools.refactor.batch_edit import (
    BATCH_EDIT_TOOL as _BATCH_EDIT_TOOL,
    batch_edit_handler,
)

logger = logging.getLogger(__name__)

# mypy --strict flags a renaming `as` import (`X as _X`) as not
# "explicitly exported" when another module imports the name directly
# from app.agents.tools. A plain module-level assignment IS recognized
# as a genuine definition here. tool_enhance.md productionization
# pass, tool #86 (2026-08-24) — _LIST_FUNCTIONS_TOOL/_PARSE_AST_TOOL
# were a pre-existing gap from tools #82/#83, caught and fixed
# alongside _FETCH_URL_TOOL's identical issue (missed then because a
# per-file mypy check on the new module alone doesn't follow imports
# to external CONSUMERS of app.agents.tools). Tool #88 (2026-08-24)
# applied the lesson proactively for _WEB_SEARCH_TOOL, then ran a
# COMPREHENSIVE `mypy app/agents/` sweep (not just tools.py) that
# surfaced three more pre-existing instances from even earlier tools:
# _SUBMIT_DOCS_TOOL (tool #85), _GIT_TAG_TOOL (tool #22),
# _SEMVER_BUMP_TOOL (tool #25) — all fixed together here rather than
# left for a future turn to rediscover one at a time.
_FETCH_URL_TOOL = FETCH_URL_TOOL
_LIST_FUNCTIONS_TOOL = LIST_FUNCTIONS_TOOL
_PARSE_AST_TOOL = PARSE_AST_TOOL
_WEB_SEARCH_TOOL = WEB_SEARCH_TOOL
_SUBMIT_DOCS_TOOL = SUBMIT_DOCS_TOOL
_SEMVER_BUMP_TOOL = SEMVER_BUMP_TOOL
_GIT_TAG_TOOL = GIT_TAG_TOOL
# tool #93/#94/#95 (2026-08-25) — architecture_doc_agent.py imports all
# three of these names directly, checked proactively before wiring.
_CALL_GRAPH_TOOL = CALL_GRAPH_TOOL
_DEAD_CODE_DETECT_TOOL = DEAD_CODE_DETECT_TOOL
# T2-B5 (2026-09-22, GRIDIRON_PARTIAL #396) — complements dead_code_detect
# above with the three checks it doesn't cover: broken imports, unused
# files, duplicate/cloned functions.
_SCAN_CODE_HYGIENE_TOOL = SCAN_CODE_HYGIENE_TOOL
_SCAN_RELIABILITY_TOOL = SCAN_RELIABILITY_TOOL
_IMPORT_GRAPH_TOOL = IMPORT_GRAPH_TOOL
_INSPECT_SCHEMA_TOOL = INSPECT_SCHEMA_TOOL
_CIRCULAR_DEP_DETECT_TOOL = CIRCULAR_DEP_DETECT_TOOL
_EXPLAIN_QUERY_TOOL = EXPLAIN_QUERY_TOOL
_FIND_CONFIG_TOOL = FIND_CONFIG_TOOL
_GENERATE_CHANGELOG_TOOL = GENERATE_CHANGELOG_TOOL
_RUN_LINTER_TOOL = RUN_LINTER_TOOL
_SECRETS_SCAN_TOOL = SECRETS_SCAN_TOOL
_CHECK_LICENSE_COMPLIANCE_TOOL = CHECK_LICENSE_COMPLIANCE_TOOL
_CHECK_TARGET_REPO_LICENSE_COMPLIANCE_TOOL = CHECK_TARGET_REPO_LICENSE_COMPLIANCE_TOOL
_COVERAGE_REPORT_TOOL = COVERAGE_REPORT_TOOL
_CPU_USAGE_TOOL = CPU_USAGE_TOOL
_DIAGNOSE_DEPLOYMENT_FAILURE_TOOL = DIAGNOSE_DEPLOYMENT_FAILURE_TOOL
_DISK_USAGE_TOOL = DISK_USAGE_TOOL
_DOCKER_LOGS_TOOL = DOCKER_LOGS_TOOL
_DOCKER_PS_TOOL = DOCKER_PS_TOOL
_ESTIMATE_COMPLEXITY_TOOL = ESTIMATE_COMPLEXITY_TOOL
_FIND_FUNCTION_BODY_TOOL = FIND_FUNCTION_BODY_TOOL
_GENERATE_RELEASE_NOTES_TOOL = GENERATE_RELEASE_NOTES_TOOL
_HEALTH_CHECK_TOOL = HEALTH_CHECK_TOOL
_MEMORY_USAGE_TOOL = MEMORY_USAGE_TOOL
_ORGANIZE_IMPORTS_TOOL = ORGANIZE_IMPORTS_TOOL
_READ_LOGS_TOOL = READ_LOGS_TOOL
_TASK_HISTORY_QUERY_TOOL = TASK_HISTORY_QUERY_TOOL
_TASK_PROGRESS_TOOL = TASK_PROGRESS_TOOL
_YAML_VALIDATE_TOOL = YAML_VALIDATE_TOOL
_ANALYZE_ERROR_TOOL = ANALYZE_ERROR_TOOL
_BASE64_ENCODE_TOOL = BASE64_ENCODE_TOOL
_CHECK_URL_STATUS_TOOL = CHECK_URL_STATUS_TOOL
_CPU_PROFILE_TOOL = CPU_PROFILE_TOOL
_DEPS_OUTDATED_TOOL = DEPS_OUTDATED_TOOL
_FIND_UNUSED_IMPORTS_TOOL = FIND_UNUSED_IMPORTS_TOOL
_COMPARE_FILES_TOOL = COMPARE_FILES_TOOL
_COPY_FILE_TOOL = COPY_FILE_TOOL
_COUNT_LINES_TOOL = COUNT_LINES_TOOL
_CREATE_DIRECTORY_TOOL = CREATE_DIRECTORY_TOOL
_CSV_PREVIEW_TOOL = CSV_PREVIEW_TOOL
_ENV_DIFF_TOOL = ENV_DIFF_TOOL
_EXPLAIN_MERGE_CONFLICT_TOOL = EXPLAIN_MERGE_CONFLICT_TOOL
_EXPORT_MARKDOWN_TOOL = EXPORT_MARKDOWN_TOOL
_FIND_FILE_TOOL = FIND_FILE_TOOL
_FIND_QUEUE_TOOL = FIND_QUEUE_TOOL
_FIND_TEST_TOOL = FIND_TEST_TOOL
_FIND_WORKER_TOOL = FIND_WORKER_TOOL
_FORMAT_FILE_TOOL = FORMAT_FILE_TOOL
_GENERATE_API_DOCS_TEXT_TOOL = GENERATE_API_DOCS_TEXT_TOOL
_GENERATE_COMMIT_MSG_TOOL = GENERATE_COMMIT_MSG_TOOL
_GENERATE_DIAGRAM_TOOL = GENERATE_DIAGRAM_TOOL
_GENERATE_PATCH_TOOL = GENERATE_PATCH_TOOL
_GIT_BRANCH_TOOL = GIT_BRANCH_TOOL
_GIT_FETCH_TOOL = GIT_FETCH_TOOL
_GIT_LOG_FILE_TOOL = GIT_LOG_FILE_TOOL
_GIT_STASH_LIST_TOOL = GIT_STASH_LIST_TOOL
_GITHUB_INSPECT_REPO_TOOL = GITHUB_INSPECT_REPO_TOOL
_GITHUB_LIST_PRS_TOOL = GITHUB_LIST_PRS_TOOL
_HASH_FILE_TOOL = HASH_FILE_TOOL
_HTTP_REQUEST_TOOL = HTTP_REQUEST_TOOL
_INSPECT_GITHUB_REPO_TOOL = INSPECT_GITHUB_REPO_TOOL
_INSPECT_OPENAPI_SPEC_TOOL = INSPECT_OPENAPI_SPEC_TOOL
_JSON_QUERY_TOOL = JSON_QUERY_TOOL
_JSON_VALIDATE_TOOL = JSON_VALIDATE_TOOL
_KNOWN_ISSUES_READ_TOOL = KNOWN_ISSUES_READ_TOOL
_KNOWN_ISSUES_WRITE_TOOL = KNOWN_ISSUES_WRITE_TOOL
_LIST_BACKGROUND_PROCESSES_TOOL = LIST_BACKGROUND_PROCESSES_TOOL
_LIST_ENV_VARS_TOOL = LIST_ENV_VARS_TOOL
_LIST_OPEN_PORTS_TOOL = LIST_OPEN_PORTS_TOOL
_LIST_PROCESSES_TOOL = LIST_PROCESSES_TOOL
_LOC_STATS_TOOL = LOC_STATS_TOOL
_MEMORY_READ_TOOL = MEMORY_READ_TOOL
_MERMAID_FROM_SCHEMA_TOOL = MERMAID_FROM_SCHEMA_TOOL
_OPENAPI_INSPECT_TOOL = OPENAPI_INSPECT_TOOL
_DECISION_LOG_APPEND_TOOL = DECISION_LOG_APPEND_TOOL


# ---------------------------------------------------------------------------
# Cross-platform venv-activation snippet — Stage 4 Tier 3 (2026-08-05,
# answer2.md Q1: "Windows support is real but incomplete... POSIX-only
# shell patterns still hardcoded"). 11 real call sites in this file built
# their own command string as `f"cd {repo_path} && source .venv/bin/
# activate 2>/dev/null || true && <cmd>"` (or the equivalent `activate =
# f"source {repo_path}/.venv/bin/activate ..."` form) — every one of the
# tools that run pytest/ruff/mypy/black. subprocess.run(cmd, shell=True)
# invokes cmd.exe on Windows, not bash, so `source`/`.venv/bin/activate`/
# `2>/dev/null` are all syntactically meaningless there. One prior comment
# in this file (near the run_tests_h handler) already described this as
# "degrades safely on both shells" — true in the sense that it never
# crashed on Windows (`|| true` swallowed the unrecognized-command error),
# but the venv was silently never actually activated there, which is a
# real, different problem (wrong/missing interpreter, wrong installed
# packages) from "crashes."
# ---------------------------------------------------------------------------


def _venv_activate_snippet() -> str:
    """Returns a shell snippet that activates `.venv` in the current
    directory, for the current platform — chain explicitly:
    `f"cd {repo_path} && {_venv_activate_snippet()} && <command>"`.
    Never raises, never blocks: both branches degrade to "activation
    silently skipped" if `.venv` doesn't exist, matching this codebase's
    own established `2>/dev/null || true` degrade-safely convention exactly
    (Windows: `2>nul` is cmd.exe's equivalent null-redirect; `(... || ver
    >nul)` is cmd.exe's equivalent of `|| true` — `ver` always succeeds and
    discards its own output, there being no simpler always-succeeding
    builtin in cmd.exe the way POSIX shells have `true`).
    """
    if sys.platform == "win32":
        return ".venv\\Scripts\\activate.bat 2>nul || ver>nul"
    # POSIX `.` (not the bashism `source`), behind an existence guard:
    # `subprocess.run(shell=True)` runs /bin/sh, which is DASH on Ubuntu/
    # Debian. dash has no `source` builtin, so the previous
    # `source .venv/bin/activate 2>/dev/null || true` silently NEVER
    # activated the venv there (the error and the failure were both
    # swallowed). The guard is required, not cosmetic: in dash `.` is a
    # special builtin, so `. missing-file || true` aborts the whole shell
    # (exit 2) instead of falling through — proved live. As an `if`
    # compound it also evaluates to success when no .venv exists, and (unlike
    # the old `A && activate || true && cmd` chain) a failed preceding `cd`
    # still short-circuits the command that follows.
    return "if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi"


# tool_enhance.md productionization pass, tool #108 (2026-08-25) —
# _DOCKER_LOG_ERROR_PATTERNS / _DOCKER_LOG_WARNING_PATTERNS /
# _DOCKER_LOG_CRASH_PATTERNS / _summarize_docker_log_patterns() moved
# to app/agents/tool_security.py (imported below, re-exported here for
# backward compatibility) so both docker_logs (this tool) and
# diagnose_deployment_failure (tool #106, which also needs this
# function) can import it from a neutral, lower-level module without
# either a circular import or a lazy in-function import.


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH10 §19/§20/§40 — shared LLM-generation helper for tool-level
# "generate X" capabilities (commit messages, PR descriptions, diff reviews,
# conflict explanations, URL summaries, deployment diagnosis). Every prior
# instance of these ("generate_commit_msg" etc.) only returned raw git/log
# data and left the actual generation implicit — delegated to whichever
# agent happened to call the tool next turn, per the audit's own finding.
# This gives each of those tools a REAL, independently-testable generation
# step, reusing the same client/circuit-breaker path run_agent_graph()
# itself uses (_make_client/_call_anthropic in base_graph.py) rather than
# constructing a second, unprotected Anthropic client — matching the
# `_merge_via_llm` pattern already established in app/fleet/versioned_memory.py.
# Every call site treats "" as "generation unavailable" and falls back to
# its own pre-existing, non-LLM behavior — never a fake/invented result.
# ---------------------------------------------------------------------------


def _llm_generate_text(
    prompt: str, *, max_tokens: int = 600, model: str | None = None
) -> str:
    """One-shot LLM text generation. Never raises — returns "" on any failure
    (missing/invalid API key, network error, rate limit) so every caller can
    degrade gracefully instead of crashing the tool call."""
    try:
        from app.agents.base_graph import (
            _call_anthropic,
            _make_client,
            _serialize_content,
            _text_from_content,
        )

        client = _make_client()
        r = _call_anthropic(
            client,
            model=model or get_settings().model_router,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return _text_from_content(_serialize_content(r.content)).strip()
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "_llm_generate_text: generation call failed", exc_info=True
        )
        return ""


def _llm_generate_commit_message(stat: str, diff: str) -> str:
    prompt = (
        "Write a git commit message for the real staged changes below. "
        "Respond with ONLY the commit message text — no preamble, no markdown "
        "code fences, no labels.\n\n"
        "Format: <type>(<scope>): <description>\n"
        "Types: feat, fix, docs, refactor, test, chore, style, perf. Add a body "
        "only if the change needs more than one line of explanation, grounded "
        "strictly in the diff below — never invent changes not shown.\n\n"
        f"=== Changed files ===\n{stat}\n\n=== Diff (truncated) ===\n{diff}"
    )
    return _llm_generate_text(prompt, max_tokens=300)


# _llm_generate_pr_description moved to app/tools/git/pull_request.py as
# generate_pr_description() — tool_enhance.md productionization pass,
# tool #2 (2026-08-15). See that module's TOOL PATH MIGRATION REPORT.


def _llm_review_diff(stat: str, diff: str) -> str:
    prompt = (
        "Review the real git diff below. Produce a concise, structured review "
        "with exactly these sections:\n"
        "1. Summary — what changed, in plain English (2-4 sentences).\n"
        "2. Risk callouts — anything that looks unsafe, untested, or likely to "
        "break something. Only real, specific observations grounded in the "
        "diff below — never an invented issue.\n"
        "3. Notable omissions — e.g. missing tests for new logic, if evident "
        "from the diff alone.\n"
        "Cite actual file names and describe the actual change, not generic "
        "advice.\n\n"
        f"=== Changed files ===\n{stat}\n\n=== Diff ===\n{diff}"
    )
    return _llm_generate_text(prompt, max_tokens=900)


def _llm_explain_conflict_hunks(path: str, hunks: list[dict[str, Any]]) -> str:
    import json as _json

    prompt = (
        f"The file {path} has real, unresolved git merge conflicts. Below is "
        "structured hunk data (ours/theirs text, line ranges) already parsed "
        "from the real conflict markers. Explain, in plain English, what each "
        "hunk's conflict actually is — what 'ours' changed vs what 'theirs' "
        "changed, and why they conflict — grounded strictly in the hunk "
        "content below. Do not recommend a resolution; only explain.\n\n"
        f"{_json.dumps(hunks, indent=2)}"
    )
    result = _llm_generate_text(prompt, max_tokens=700)
    return result or f"[ERROR] Could not generate an explanation for {path}."


def _llm_summarize_url_content(url: str, content: str) -> str:
    prompt = (
        f"Summarize the real page content fetched from {url} below. Focus on "
        "what the page is about and any concrete facts, APIs, or instructions "
        "it contains — 3-6 sentences, grounded strictly in the text below, "
        "never invented.\n\n"
        f"{content[:10000]}"
    )
    return _llm_generate_text(prompt, max_tokens=400)


def _llm_diagnose_deployment_failure(context: str) -> str:
    prompt = (
        "You are diagnosing a real deployment/container failure. Below is "
        "real gathered state (docker ps / docker logs / docker inspect). "
        "Identify:\n"
        "1. What actually failed — cite the exact error line(s).\n"
        "2. The most likely root cause, grounded only in the evidence below.\n"
        "3. A concrete next diagnostic step or fix to try.\n"
        "If the evidence is insufficient to reach a conclusion, say so "
        "explicitly rather than guessing.\n\n"
        f"{context}"
    )
    result = _llm_generate_text(prompt, max_tokens=700)
    return result or "[ERROR] Diagnosis generation failed — see raw state above."


# --- Tool specs (Anthropic input_schema format) ---

# tool_enhance.md productionization pass, tool #65 (2026-08-22) —
# READ_ONLY_TOOLS[0] moved to app/tools/filesystem/read_file.py as
# READ_FILE_TOOL. Kept at the SAME list index deliberately: RESEARCH_TOOLS
# (below) and other bundles index into READ_ONLY_TOOLS positionally.
READ_ONLY_TOOLS = [
    READ_FILE_TOOL,
    # tool_enhance.md productionization pass, tool #68 (2026-08-22) —
    # moved to app/tools/filesystem/list_files.py as LIST_FILES_TOOL.
    # Kept at the SAME list index deliberately: RESEARCH_TOOLS indexes
    # into READ_ONLY_TOOLS positionally.
    LIST_FILES_TOOL,
    # tool_enhance.md productionization pass, tool #69 (2026-08-22) —
    # moved to app/tools/filesystem/search_code.py as SEARCH_CODE_TOOL.
    # Kept at the SAME list index deliberately: RESEARCH_TOOLS indexes
    # into READ_ONLY_TOOLS positionally.
    SEARCH_CODE_TOOL,
    # tool_enhance.md productionization pass, tool #73 (2026-08-22) —
    # moved to app/tools/filesystem/search_symbols.py as
    # SEARCH_SYMBOLS_TOOL. No new vulnerability — see that module's
    # docstring for the full audit.
    SEARCH_SYMBOLS_TOOL,
    # tool_enhance.md productionization pass, tool #67 (2026-08-22) —
    # moved to app/tools/filesystem/get_file_tree.py as GET_FILE_TREE_TOOL.
    # Kept at the SAME list index deliberately: RESEARCH_TOOLS indexes
    # into READ_ONLY_TOOLS positionally (READ_ONLY_TOOLS[4] is expected
    # to be get_file_tree — see the comment near RESEARCH_TOOLS below).
    GET_FILE_TREE_TOOL,
    # tool_enhance.md productionization pass, tool #78 (2026-08-23) —
    # moved to app/tools/git/log.py as GIT_LOG_TOOL. See that module's
    # docstring — an uncaught ValueError/TypeError on a non-numeric
    # `count`, on BOTH real implementations; `file` already safe by
    # construction (`--` separator + git's own outside-repo refusal,
    # both verified live).
    GIT_LOG_TOOL,
    # ---- Enhanced search & analysis tools (non-destructive) ----
    # tool_enhance.md productionization pass, tool #71 (2026-08-22) —
    # moved to app/tools/filesystem/read_files.py as READ_FILES_TOOL.
    READ_FILES_TOOL,
    # tool_enhance.md productionization pass, tool #70 (2026-08-22) —
    # moved to app/tools/filesystem/file_exists.py as FILE_EXISTS_TOOL.
    FILE_EXISTS_TOOL,
    # tool_enhance.md productionization pass, tool #72 (2026-08-22) —
    # moved to app/tools/filesystem/file_info.py as FILE_INFO_TOOL.
    FILE_INFO_TOOL,
    # tool_enhance.md productionization pass, tool #74 (2026-08-22) —
    # moved to app/tools/filesystem/find_references.py as
    # FIND_REFERENCES_TOOL. No new vulnerability — see that module's
    # docstring for the full audit.
    FIND_REFERENCES_TOOL,
    # tool_enhance.md productionization pass, tool #77 (2026-08-23) —
    # moved to app/tools/filesystem/find_todos.py as FIND_TODOS_TOOL.
    # See that module's docstring — like tool #76's analyze_file, the
    # CANONICAL implementation itself, not just chat_agent.py's copy,
    # had the worktree-escape bug.
    FIND_TODOS_TOOL,
    # tool_enhance.md productionization pass, tool #75 (2026-08-22) —
    # moved to app/tools/filesystem/search_imports.py as
    # SEARCH_IMPORTS_TOOL. No new vulnerability — see that module's
    # docstring for the full audit.
    SEARCH_IMPORTS_TOOL,
    # tool_enhance.md productionization pass, tool #79 (2026-08-23) —
    # moved to app/tools/git/status.py as GIT_STATUS_TOOL. See that
    # module's docstring — no security vulnerability (zero-input
    # schema), but a real functionality bug: this implementation
    # silently reported "(clean)" even when `git status` genuinely
    # failed, never checking returncode.
    GIT_STATUS_TOOL,
    # tool_enhance.md productionization pass, tool #80 (2026-08-23) —
    # moved to app/tools/git/show.py as GIT_SHOW_TOOL. See that
    # module's docstring — the MOST SEVERE finding in the low-risk
    # tier so far: `ref` was flag-collision vulnerable to git's own
    # `--output=<path>` flag, a silent arbitrary-file-write primitive,
    # on BOTH real implementations.
    GIT_SHOW_TOOL,
    # tool_enhance.md productionization pass, tool #81 (2026-08-23) —
    # moved to app/tools/git/blame.py as GIT_BLAME_TOOL. See that
    # module's docstring — same flag-collision class as tool #80's
    # git_show (path had no `--` separator), checked and confirmed
    # lower severity here (no --output-equivalent flag exists for git
    # blame), fixed defensively anyway per this initiative's
    # consistent policy.
    GIT_BLAME_TOOL,
    # tool_enhance.md productionization pass, tool #76 (2026-08-22) —
    # moved to app/tools/filesystem/analyze_file.py as ANALYZE_FILE_TOOL.
    # See that module's docstring — this was the first READ_ONLY_TOOLS
    # tool where the CANONICAL implementation itself, not just
    # chat_agent.py's copy, had the worktree-escape bug.
    ANALYZE_FILE_TOOL,
    # Universal "no existing tool fits" fallback — app/tools/agents/
    # bhaskar_tool.py. Deliberately appended LAST: RESEARCH_TOOLS and other
    # bundles index into READ_ONLY_TOOLS positionally (see the comment at
    # the top of this list), so every existing index stays valid.
    # Every agent built on READ_ONLY_TOOLS (the vast majority — see
    # make_read_only_handlers below for the matching handler wiring)
    # inherits it automatically.
    BHASKAR_TOOL,
]

# ---------------------------------------------------------------------------
# record_learning — MASTER_AGENT_v2.md Phase 1.4. A single, explicit,
# agent-controlled write path into shared fleet memory, distinct from the
# automatic post-run hook (app/memory/hooks.py). The automatic hook captures
# every run's outcome regardless of whether anything unusual happened; this
# tool lets an agent flag a *specific* non-obvious finding mid-run — the kind
# of thing a generic outcome summary would not surface (a root cause, a
# workaround, a gotcha another agent working on a similar task would want).
# ---------------------------------------------------------------------------

# moved to app/tools/agents/record_learning.py — tool_enhance.md
# productionization pass, tool #66 (2026-08-22). No fix required (see
# that module's own docstring for the full audit) — pure modularization.
# RECORD_LEARNING_TOOL / make_record_learning_handler imported below,
# same names, so every existing reference in this file keeps working
# unchanged.


# ---------------------------------------------------------------------------
# record_preference — AUDIT_Q_BATCH15 §74/§113 gap-closure (2026-08-11). A
# human-stated coding-style/naming/tooling/testing preference had no
# dedicated write path anywhere — it would have been shoehorned into
# record_learning above (whose embed_learning_signal target is documented as
# a *fleet self-improvement* signal, not a per-project human preference) or
# lost entirely. Chat is the direct human-facing conversational surface
# where a preference is naturally stated ("always use f-strings", "prefer
# pytest fixtures"), so this is wired into CHAT_TOOLS; retrieval
# (memory_hook_node) applies to every agent regardless of which surface
# wrote the preference.
# ---------------------------------------------------------------------------

# moved to app/tools/agents/record_preference.py as
# RECORD_PREFERENCE_TOOL / make_record_preference_handler() —
# tool_enhance.md productionization pass, tool #178 (2026-09-15).
# Real finding: advertised in CHAT_TOOLS but never dispatched by
# chat_agent.py — see that module's own new dispatch branch. No
# security fix needed on the handler logic itself (audited and
# confirmed already safe — see the new module's own docstring).


# moved to app/tools/agents/request_clarification.py — tool_enhance.md
# productionization pass, tool #117 (2026-08-26). No fix required (see
# that module's own docstring for the full audit) — pure
# modularization. REQUEST_CLARIFICATION_TOOL /
# make_request_clarification_handler imported below, same names, so
# every existing reference in this file keeps working unchanged.


CODER_TOOLS = READ_ONLY_TOOLS + [
    # moved to app/tools/filesystem/edit_file.py as EDIT_FILE_TOOL —
    # tool_enhance.md productionization pass, tool #13 (2026-08-17).
    _EDIT_FILE_TOOL,
    # moved to app/tools/filesystem/write_file.py as WRITE_FILE_TOOL —
    # tool_enhance.md productionization pass, tool #12 (2026-08-17).
    _WRITE_FILE_TOOL,
    # tool_enhance.md productionization pass, tool #84 (2026-08-24) —
    # moved to app/tools/git/diff.py as GIT_DIFF_TOOL. See that
    # module's docstring — `file` had no `--` separator in 3 of the 4
    # real implementations (not this agent's own — make_coder_handlers
    # was already safe), a silent arbitrary-file-write via git's own
    # --output=<path> flag, same class as tool #80's git_show.
    GIT_DIFF_TOOL,
    {
        "name": "bash",
        "description": "Run a shell command (allowlisted safe commands only). Use for running tests, typecheck, and lint.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
            },
            "required": ["command"],
        },
    },
    # tool_enhance.md productionization pass, tool #92 (2026-08-24) —
    # moved to app/tools/agents/submit_patch.py as SUBMIT_PATCH_TOOL.
    # See that module's docstring — no vulnerability in this handler
    # itself; files_changed's real downstream consumer (git_add()) was
    # traced and confirmed already safe.
    SUBMIT_PATCH_TOOL,
    RECORD_LEARNING_TOOL,
]

# QA Agent: read + bash (test/build only, no write)
_QA_BASH_TOOL = {
    "name": "bash",
    "description": (
        "Run test or build commands only. Allowed: pytest, mypy, ruff, tsc, npm test/build/lint. "
        "No write operations, no deploy commands."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Test/build command to run"},
        },
        "required": ["command"],
    },
}

# moved to app/tools/agents/submit_qa_result.py as
# SUBMIT_QA_RESULT_TOOL / make_submit_qa_result_handler() —
# tool_enhance.md productionization pass, tool #191 (2026-09-16). Not a
# dead accumulator (unlike sibling tools #180-#186/#188-#190) —
# qa_result is genuinely read by app/agents/qa.py's run_qa() via
# handlers["_qa_result"], on both its success and retry-giveup paths.
# See that module's own docstring.
_SUBMIT_QA_TOOL: dict[str, Any] = SUBMIT_QA_RESULT_TOOL

# QA has read tools + bash (test only) + submit_qa_result. NO write_file, NO edit.
QA_TOOLS = READ_ONLY_TOOLS + [_QA_BASH_TOOL, _SUBMIT_QA_TOOL, RECORD_LEARNING_TOOL]

# moved to app/tools/agents/submit_review.py as
# SUBMIT_REVIEW_TOOL / make_submit_review_handler() —
# tool_enhance.md productionization pass, tool #195 (2026-09-16). Not
# a dead accumulator (unlike sibling tools #180-#186/#188-#190/#192)
# — review_result is genuinely read by app/agents/reviewer.py's
# run_reviewer() via handlers["_review_result"]. See that module's
# own docstring.
_SUBMIT_REVIEW_TOOL: dict[str, Any] = SUBMIT_REVIEW_TOOL

# Reviewer has read tools ONLY + submit_review. NO bash, NO write, NO edit.
REVIEWER_TOOLS = READ_ONLY_TOOLS + [_SUBMIT_REVIEW_TOOL, RECORD_LEARNING_TOOL]

_DEVOPS_BASH_TOOL = {
    "name": "bash",
    "description": (
        "Run read-only health-check commands only. Allowed prefixes come from config DEVOPS_BASH_ALLOWLIST. "
        "No write, no deploy, no remote push, no credential access."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Read-only health check command",
            },
        },
        "required": ["command"],
    },
}

# moved to app/tools/agents/submit_health_report.py as
# SUBMIT_HEALTH_REPORT_TOOL / make_submit_health_report_handler() —
# tool_enhance.md productionization pass, tool #187 (2026-09-16). Not a
# dead accumulator (unlike sibling tools #180-#186) — health_result is
# genuinely read by app/agents/devops.py's run_devops() via
# handlers["_health_result"]. See that module's own docstring.
_SUBMIT_HEALTH_REPORT_TOOL: dict[str, Any] = SUBMIT_HEALTH_REPORT_TOOL

# DevOps: read tools + allowlisted bash + submit_health_report. NO write_file.
DEVOPS_TOOLS = READ_ONLY_TOOLS + [
    _DEVOPS_BASH_TOOL,
    _SUBMIT_HEALTH_REPORT_TOOL,
    RECORD_LEARNING_TOOL,
]

# Allowed QA bash commands (prefix checks)
_QA_ALLOWED_PREFIXES = (
    "pytest",
    "python -m pytest",
    "python -m mypy",
    "python -m ruff",
    "python3 -m pytest",
    "python3 -m mypy",
    "python3 -m ruff",
    "npx tsc",
    "npm test",
    "npm run",
    "cat ",
    "head ",
    "git diff",
    "git log",
    "git status",
)


# test_runner/load_test/dependency_audit/infra_dry_run bash tool specs +
# handlers moved to app/tools/execution/bash.py (tool_enhance.md
# productionization pass, tool #1, 2026-08-15) — imported at the top of
# this file for backward compatibility. See that module's own docstring
# for the full TOOL PATH MIGRATION REPORT.


# --- Tool handlers ---


def make_read_only_handlers(repo_path: str) -> dict[str, Any]:
    base = Path(repo_path)

    # tool_enhance.md productionization pass, tool #65 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch had zero
    # worktree-boundary validation; this implementation already had it)
    # lives in the shared read_file_handler() itself; see that
    # function's own module docstring.
    def read_file(inp: dict[str, Any]) -> str:
        return read_file_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #68 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch could raise an
    # uncaught ValueError that leaked an absolute host file path via the
    # resulting error message) lives in the shared list_files_handler()
    # itself; see that function's own module docstring.
    def list_files(inp: dict[str, Any]) -> str:
        return list_files_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #69 (2026-08-22) — the
    # real fix (a flag-shaped `pattern` reaching grep's own argument
    # parser, on BOTH real implementations) lives in the shared
    # search_code_handler() itself; see that function's own module
    # docstring.
    def search_code(inp: dict[str, Any]) -> str:
        return search_code_handler(base, inp)

    # tool_enhance.md productionization pass, tool #73 (2026-08-22) — no
    # new vulnerability; the shared search_symbols_handler() itself
    # documents the full audit in its own module docstring.
    def search_symbols(inp: dict[str, Any]) -> str:
        return search_symbols_handler(base, inp)

    # tool_enhance.md productionization pass, tool #67 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch had zero
    # worktree-boundary validation; this implementation already had it)
    # lives in the shared get_file_tree_handler() itself; see that
    # function's own module docstring.
    def get_file_tree(inp: dict[str, Any]) -> str:
        return get_file_tree_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #78 (2026-08-23) — the
    # real fix (an uncaught ValueError/TypeError on a non-numeric
    # `count`, on both real implementations) lives in the shared
    # git_log_handler() itself; see that function's own module
    # docstring.
    def git_log(inp: dict[str, Any]) -> str:
        return git_log_handler(base, inp)

    # tool_enhance.md productionization pass, tool #71 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch had zero
    # worktree-boundary validation on any path in the batch) lives in
    # the shared read_files_handler() itself; see that function's own
    # module docstring.
    def read_files(inp: dict[str, Any]) -> str:
        return read_files_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #70 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch had zero
    # worktree-boundary validation, and both implementations had an
    # uncaught PermissionError) lives in the shared file_exists_handler()
    # itself; see that function's own module docstring.
    def file_exists(inp: dict[str, Any]) -> str:
        return file_exists_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #72 (2026-08-22) — the
    # real fix (chat_agent.py's own separate dispatch had zero
    # worktree-boundary validation, and both implementations had an
    # uncaught PermissionError) lives in the shared file_info_handler()
    # itself; see that function's own module docstring.
    def file_info(inp: dict[str, Any]) -> str:
        return file_info_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #74 (2026-08-22) — no
    # new vulnerability; the shared find_references_handler() itself
    # documents the full audit in its own module docstring.
    def find_references(inp: dict[str, Any]) -> str:
        return find_references_handler(base, inp)

    # tool_enhance.md productionization pass, tool #77 (2026-08-23) — the
    # real fix (this implementation itself had ZERO worktree-boundary
    # validation on `directory`, same class as tool #76's analyze_file)
    # lives in the shared find_todos_handler() itself; see that
    # function's own module docstring.
    def find_todos(inp: dict[str, Any]) -> str:
        return find_todos_handler(base, repo_path, inp)

    # tool_enhance.md productionization pass, tool #75 (2026-08-22) — no
    # new vulnerability; the shared search_imports_handler() itself
    # documents the full audit in its own module docstring.
    def search_imports(inp: dict[str, Any]) -> str:
        return search_imports_handler(base, inp)

    # tool_enhance.md productionization pass, tool #79 (2026-08-23) — the
    # real fix (this implementation silently reported "(clean)" even
    # when `git status` genuinely failed) lives in the shared
    # git_status_handler() itself; see that function's own module
    # docstring.
    def git_status(inp: dict[str, Any]) -> str:
        return git_status_handler(base)

    # tool_enhance.md productionization pass, tool #80 (2026-08-23) — the
    # real fix (this implementation had ZERO validation of `ref`,
    # exploitable via git's own --output=<path> flag for a silent
    # arbitrary-file-write) lives in the shared git_show_handler()
    # itself; see that function's own module docstring.
    def git_show(inp: dict[str, Any]) -> str:
        return git_show_handler(base, inp)

    # tool_enhance.md productionization pass, tool #81 (2026-08-23) — the
    # real fix (this implementation had ZERO validation of `path`,
    # same flag-collision class as tool #80's git_show) lives in the
    # shared git_blame_handler() itself; see that function's own
    # module docstring.
    def git_blame(inp: dict[str, Any]) -> str:
        return git_blame_handler(base, inp)

    # tool_enhance.md productionization pass, tool #76 (2026-08-22) — the
    # real fix (this implementation itself had ZERO worktree-boundary
    # validation, an uncaught PermissionError, and chat_agent.py's
    # separate copy had a real functionality-parity gap) lives in the
    # shared analyze_file_handler() itself; see that function's own
    # module docstring.
    def analyze_file(inp: dict[str, Any]) -> str:
        return analyze_file_handler(base, repo_path, inp)

    # Universal fallback — see app/tools/agents/bhaskar_tool.py. agent_name
    # is a generic marker here (make_read_only_handlers has no notion of
    # which specific agent it's building handlers for — it's shared by ~26
    # agent families); only used for the cached-script row's own metadata,
    # not for any authorization decision.
    def bhaskar_tool(inp: dict[str, Any]) -> str:
        return bhaskar_tool_handler(repo_path, inp, agent_name="agent")

    return {
        "read_file": read_file,
        "read_files": read_files,
        "list_files": list_files,
        "search_code": search_code,
        "search_symbols": search_symbols,
        "get_file_tree": get_file_tree,
        "git_log": git_log,
        "file_exists": file_exists,
        "file_info": file_info,
        "find_references": find_references,
        "find_todos": find_todos,
        "search_imports": search_imports,
        "git_status": git_status,
        "git_show": git_show,
        "git_blame": git_blame,
        "analyze_file": analyze_file,
        "bhaskar_tool": bhaskar_tool,
    }


def make_coder_handlers(
    worktree_path: str, repo_path: str, extra_env: dict[str, str] | None = None
) -> dict[str, Any]:
    """extra_env (Day 17 — Credential Vault): custom secrets merged into the
    bash tool's subprocess env — e.g. a third-party API key a task's code
    integrates with. Never database/deploy credentials — see
    docs/DAY17_PLAN.md. Values never appear in tool output or logs; only the
    subprocess itself sees them."""
    handlers = make_read_only_handlers(repo_path)
    wt = Path(worktree_path)
    patch_result: dict[str, Any] = {}

    def write_file(inp: dict[str, Any]) -> str:
        rel_path = inp["path"]
        policy = check_path_in_worktree(rel_path, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        target = wt / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(inp["content"], encoding="utf-8")
        return f"Written: {rel_path}"

    def bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_command(cmd)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        # Gap-closure (Audit 05 fix, SEC-05-005): the denylist alone doesn't
        # stop `cd /outside/the/worktree && <anything>` — cwd= below only
        # sets the *starting* directory. See check_command_stays_in_boundary's
        # own docstring for what this does and doesn't cover.
        boundary_policy = check_command_stays_in_boundary(cmd, worktree_path)
        if not boundary_policy.allowed:
            return f"[POLICY DENIED] {boundary_policy.reason}"
        timeout = get_settings().bash_tool_timeout_seconds.get("coder", 60)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd, worktree_path, timeout=timeout, extra_env=extra_env
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        out = (stdout + stderr)[:4000]
        return out if out else "(no output)"

    def edit_file(inp: dict[str, Any]) -> str:
        rel_path = str(inp["path"])
        old_string = str(inp["old_string"])
        new_string = str(inp["new_string"])
        policy = check_path_in_worktree(rel_path, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        target = wt / rel_path
        if not target.exists():
            return f"[ERROR] File not found: {rel_path}. Use write_file to create a new file."
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            return f"[ERROR] Cannot read {rel_path}: {e}"
        if old_string not in content:
            return f"[ERROR] old_string not found in {rel_path}. The exact text was not present."
        count = content.count(old_string)
        if count > 1:
            return f"[ERROR] old_string appears {count} times in {rel_path}. Provide more context to make it unique."
        target.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        return f"Edited {rel_path}"

    # tool_enhance.md productionization pass, tool #84 (2026-08-24) — this
    # implementation was already safe (already used a `--` separator);
    # unified onto the shared git_diff_handler() anyway for the more
    # complete staged+unstaged output; see that function's own module
    # docstring.
    def git_diff(inp: dict[str, Any]) -> str:
        return git_diff_handler(wt, inp)

    # tool_enhance.md productionization pass, tool #92 (2026-08-24) — the
    # shared, already-correct logic now lives in
    # make_submit_patch_handler(); see that function's own module
    # docstring.
    submit_patch = make_submit_patch_handler(patch_result)

    handlers["edit_file"] = edit_file
    handlers["git_diff"] = git_diff
    handlers["write_file"] = write_file
    handlers["bash"] = bash
    handlers["submit_patch"] = submit_patch
    handlers["_patch_result"] = patch_result  # caller reads this after run
    return handlers


def make_qa_handlers(worktree_path: str, repo_path: str) -> dict[str, Any]:
    """QA agent: read-only + bash (test/build only) + submit_qa_result. No writes."""
    handlers = make_read_only_handlers(repo_path)
    qa_result: dict[str, Any] = {}

    # Prepend venv bin dir so `python`, `pytest`, `mypy`, `ruff` resolve correctly.
    _venv_bin = str(Path(sys.executable).parent)
    _env_with_venv = os.environ.copy()
    _env_with_venv["PATH"] = _venv_bin + ":" + _env_with_venv.get("PATH", "")

    def bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _QA_ALLOWED_PREFIXES)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("qa", 120)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            worktree_path,
            timeout=timeout,
            extra_env=None if settings.bash_sandbox_enabled else _env_with_venv,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("qa"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        out = (stdout + stderr)[:6000]
        return out if out else "(no output)"

    handlers["bash"] = bash
    handlers["submit_qa_result"] = make_submit_qa_result_handler(qa_result)
    handlers["_qa_result"] = qa_result  # caller reads this after run
    return handlers


def make_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Reviewer agent: read-only only + submit_review. No bash, no writes."""
    handlers = make_read_only_handlers(repo_path)
    review_result: dict[str, Any] = {}

    handlers["submit_review"] = make_submit_review_handler(review_result)
    handlers["_review_result"] = review_result  # caller reads this after run
    return handlers


def make_devops_handlers(repo_path: str) -> dict[str, Any]:
    """DevOps agent: read-only + allowlisted bash (health checks only) + submit_health_report. No write."""
    from app.config import get_settings

    handlers = make_read_only_handlers(repo_path)
    health_result: dict[str, Any] = {}

    def bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        settings = get_settings()
        devops_prefixes = settings.devops_bash_allowlist_tuple
        policy = check_allowlisted_command(cmd, devops_prefixes)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        timeout = settings.bash_tool_timeout_seconds.get("devops", 30)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            repo_path,
            timeout=timeout,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("devops"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        out = (stdout + stderr)[:4000]
        return out if out else "(no output)"

    handlers["bash"] = bash
    handlers["submit_health_report"] = make_submit_health_report_handler(health_result)
    handlers["_health_result"] = health_result  # caller reads this after run
    return handlers


# ---- Phase 6 — Research Agent tools ----

# tool_enhance.md productionization pass, tool #88 (2026-08-24) — moved
# to app/tools/integrations/web_search.py as WEB_SEARCH_TOOL (imported
# above, aliased to _WEB_SEARCH_TOOL after the import block). No
# vulnerability found — see that module's docstring.

# moved to app/tools/agents/submit_research.py as
# SUBMIT_RESEARCH_TOOL / make_submit_research_handler() —
# tool_enhance.md productionization pass, tool #193 (2026-09-16). Not
# a dead accumulator (unlike sibling tools #180-#186/#188-#190/#192)
# — research_result is genuinely read by app/agents/research.py's
# run_research() via handlers["_research_result"]. See that module's
# own docstring.
_SUBMIT_RESEARCH_TOOL: dict[str, Any] = SUBMIT_RESEARCH_TOOL

# Research agent: minimal read tools + submit_research only (no AST tools, no web_search placeholder).
# Kept small to stay within free-tier TPM limits — the agent can read files and search code.
# MASTER_AGENT_v2.md Phase 4 Item 1 gap-closure (2026-07-30) — research.py's own role file explicitly
# says "read the codebase, explore existing patterns" (general code exploration), but it was missing 2
# of the 3 tools Phase 4's own checklist names for "read broadly": get_file_tree and find_references.
# Both handlers already existed (make_research_handlers -> make_read_only_handlers wires every
# READ_ONLY_TOOLS handler regardless of schema exposure — same dead-contract shape Step 2 already fixed
# elsewhere), so this is a 2-line schema addition, not new capability — kept minimal, not the full
# READ_ONLY_TOOLS bundle, to respect the original TPM-budget intent above.
RESEARCH_TOOLS = [
    READ_ONLY_TOOLS[0],
    READ_ONLY_TOOLS[1],
    READ_ONLY_TOOLS[2],
    READ_ONLY_TOOLS[4],  # get_file_tree
    READ_ONLY_TOOLS[9],  # find_references
    _WEB_SEARCH_TOOL,
    _SUBMIT_RESEARCH_TOOL,
    RECORD_LEARNING_TOOL,
    BHASKAR_TOOL,
]


def make_research_handlers(repo_path: str) -> dict[str, Any]:
    """Research agent: read-only + web_search placeholder + submit_research. No write, no bash."""
    handlers = make_read_only_handlers(repo_path)
    research_result: dict[str, Any] = {}

    # tool_enhance.md productionization pass, tool #88 (2026-08-24) — the
    # real logic now lives in web_search_handler(); see that
    # function's own module docstring.
    handlers["web_search"] = web_search_handler
    handlers["submit_research"] = make_submit_research_handler(research_result)
    handlers["_research_result"] = research_result  # caller reads this after run
    return handlers


# ---- Phase 6 — Docs Agent tools ----

# tool_enhance.md productionization pass, tool #85 (2026-08-24) — moved
# to app/tools/agents/submit_docs.py as SUBMIT_DOCS_TOOL (imported
# above as _SUBMIT_DOCS_TOOL). See that module's docstring — no
# security vulnerability, no functional bug; all four real
# implementations were already-correct, functionally identical
# in-memory sinks, now unified for maintainability.


# ---------------------------------------------------------------------------
# Gap-closure Day 53 (Stage 2, answers.md Q41: "Architecture docs"/"Agent
# docs"/"Tool docs"/"Migration guides" all NOT FOUND — no generator at all).
# Repo research (repos/aider/aider/repomap.py): aider builds its repo map
# from real tree-sitter-parsed symbols, never from guessing — the same
# "introspect the real thing, don't ask the LLM to guess" principle applies
# here: each of these 3 tools returns real, directly-introspected data
# (the actual capability_registry, the actual tool specs in this very
# module, the actual Alembic migration files' real revision/down_revision
# via AST parsing) for the LLM to write UP, not to invent from scratch.
# ---------------------------------------------------------------------------

# moved to app/tools/agents/list_registered_agents.py as
# LIST_REGISTERED_AGENTS_TOOL / list_registered_agents_handler() —
# tool_enhance.md productionization pass, tool #222 (2026-09-17). No
# security vulnerability and no functional bug found. Re-exported
# under the old name for backward compatibility.
_LIST_REGISTERED_AGENTS_TOOL = LIST_REGISTERED_AGENTS_TOOL

_LIST_TOOL_SPECS_TOOL = {
    "name": "list_all_tool_specs",
    "description": "Real introspection of every distinct tool schema defined in this codebase (name + description), deduplicated by name — not a guess from grepping.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

# moved to app/tools/filesystem/list_migrations.py as
# LIST_MIGRATIONS_TOOL / list_migrations_handler() — tool_enhance.md
# productionization pass, tool #221 (2026-09-17). No security
# vulnerability and no functional bug found. Re-exported under the old
# name for backward compatibility.
_LIST_MIGRATIONS_TOOL = LIST_MIGRATIONS_TOOL


list_registered_agents = list_registered_agents_handler


def _collect_tool_specs_from_module(module: Any, seen: dict[str, str]) -> None:
    for attr_name in dir(module):
        try:
            val = getattr(module, attr_name)
        except Exception:
            continue
        if isinstance(val, dict) and "name" in val and "input_schema" in val:
            seen[str(val["name"])] = str(val.get("description", ""))
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and "name" in item and "input_schema" in item:
                    seen[str(item["name"])] = str(item.get("description", ""))


def list_all_tool_specs(inp: dict[str, Any]) -> str:
    """Real introspection of every distinct tool schema in the codebase.

    tool_enhance.md productionization pass, tool #219 (2026-09-17): real
    finding — this function's own description claims "every distinct
    tool schema defined in this codebase," but it only ever scanned
    this one module (app.agents.tools). Proved live: 2 real tools were
    silently invisible to every real caller (tool_catalog_doc_agent,
    whose whole job is writing an accurate tool catalog doc from this
    output) — `submit_fix` (tool #214's shared schema, re-exported only
    inside the 4 agent files that use it, never into this module) and
    the pre-existing `score_tech_options` (tech_advisor_agent.py-local,
    unrelated to any change in this initiative). Fixed by also scanning
    every other module directly under app/agents/ — closes the root
    cause (any future agent-local-only tool schema is now covered
    automatically) rather than just patching these 2 known instances.
    """
    import importlib
    import json as _json
    import sys
    from pathlib import Path as _Path

    seen: dict[str, str] = {}
    _collect_tool_specs_from_module(sys.modules[__name__], seen)

    agents_dir = _Path(__file__).resolve().parent
    for path in sorted(agents_dir.glob("*.py")):
        if path.stem in ("tools", "__init__"):
            continue
        try:
            mod = importlib.import_module(f"app.agents.{path.stem}")
        except Exception:
            continue
        _collect_tool_specs_from_module(mod, seen)

    data = [{"name": n, "description": d} for n, d in sorted(seen.items())]
    return _json.dumps(data, indent=2)


list_migrations = list_migrations_handler


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH10 §19 "Generate deployment guides for THIS project: NO — no
# deployment_guide_agent.py or equivalent exists". list_deploy_artifacts is
# the real grounding-data tool deployment_guide_doc_agent uses instead of
# guessing which deploy files exist: a real filesystem check against
# repo_path's own actual deployment files (Dockerfiles, compose files, CI
# workflows, systemd units, k8s/terraform if present) — never invented, and
# never a full recursive tree walk (would hit node_modules/.venv/repos/).
# Bound to repo_path via a closure factory, matching this file's own
# established convention (_make_write_file_handler(root) above) rather than
# module-level like list_migrations, because unlike Alembic migrations
# (always this app's own backend/migrations/), deploy artifacts live in
# whichever repo_path the calling agent is scoped to.
# ---------------------------------------------------------------------------

# moved to app/tools/filesystem/list_deploy_artifacts.py as
# LIST_DEPLOY_ARTIFACTS_TOOL / make_list_deploy_artifacts_handler() —
# tool_enhance.md productionization pass, tool #220 (2026-09-17). No
# security vulnerability and no functional bug found — audited and
# confirmed safe (fixed hardcoded globs, no `**` recursion, no crash
# on a nonexistent repo_path, no content-leak risk via symlinks since
# only relative file names are ever returned). Re-exported under the
# old name for backward compatibility.
_LIST_DEPLOY_ARTIFACTS_TOOL = LIST_DEPLOY_ARTIFACTS_TOOL


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH10 §20 "Inspect external GitHub repos: NO — all GitHub tooling
# operates on the local repo's own remote via `gh` CLI, not arbitrary
# external repos". inspect_github_repo is the real gap-fill: real,
# read-only GitHub REST data (via `gh api`, GET only — never a write
# endpoint) for any owner/repo, not just this project's own remote. No
# repo_path needed, so this is a standalone function like list_migrations
# above, not a repo_path-bound closure.
# ---------------------------------------------------------------------------

# moved to app/tools/integrations/inspect_github_repo.py as
# INSPECT_GITHUB_REPO_TOOL / inspect_github_repo_handler() —
# tool_enhance.md productionization pass, tool #156 (2026-09-14).
# NO real bug found (audited thoroughly — see that module's own
# docstring); this is modularization only, same as tool #147's
# generate_patch. `inspect_github_repo` name kept as a thin
# delegating wrapper for backward compatibility — existing tests
# import it directly from app.agents.tools.


def inspect_github_repo(inp: dict[str, Any]) -> str:
    return inspect_github_repo_handler(inp)


# ---------------------------------------------------------------------------
# AUDIT_Q_BATCH10 §20 "Inspect APIs (OpenAPI/Swagger): NO — zero references".
# Real JSON/YAML structural parsing of an OpenAPI/Swagger document (never
# regex/text scraping) — either fetched from a URL (reusing fetch_url's own
# SSRF guard) or supplied directly as spec_text (e.g. already read from a
# local file via read_file, keeping this standalone rather than repo_path-
# bound). Lists real endpoints/methods/schemas from the parsed structure.
# ---------------------------------------------------------------------------

# moved to app/tools/integrations/inspect_openapi_spec.py as
# INSPECT_OPENAPI_SPEC_TOOL / inspect_openapi_spec_handler() —
# tool_enhance.md productionization pass, tool #157 (2026-09-14).
# Real finding — a cross-cutting SSRF-via-redirect bypass, also
# retroactively fixed for fetch_url/check_url_status/http_request
# — see that module's own docstring. `inspect_openapi_spec` name
# kept as a thin delegating wrapper for backward compatibility.


def inspect_openapi_spec(inp: dict[str, Any]) -> str:
    return inspect_openapi_spec_handler(inp)


def make_doc_generator_handlers(repo_path: str) -> dict[str, Any]:
    """Shared base for the 4 gap-closure Day 53 doc-generator agents
    (architecture_doc_agent, agent_roster_doc_agent, tool_catalog_doc_agent,
    migration_guide_doc_agent) — read-only + write_file (*.md / docs/** only,
    mirroring readme_agent's own established write scoping) + submit_docs.
    Each agent adds its own specific real-introspection tool on top of this
    shared base."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    docs_result: dict[str, Any] = {}

    def dg_write_file(inp: dict[str, Any]) -> str:
        from app.policy.engine import check_path_in_worktree

        rel = str(inp["path"])
        if not (rel.endswith(".md") or rel.startswith("docs/")):
            return (
                f"[POLICY DENIED] Doc generator agents may only write .md files "
                f"or paths under docs/. Got: {rel!r}"
            )
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {result.reason}"
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(inp["content"]), encoding="utf-8")
        return f"Written {rel}"

    handlers["write_file"] = dg_write_file
    # tool_enhance.md productionization pass, tool #85 (2026-08-24) —
    # the shared, already-correct logic now lives in
    # make_submit_docs_handler(); see that function's own module
    # docstring.
    handlers["submit_docs"] = make_submit_docs_handler(docs_result)
    handlers["_docs_result"] = docs_result
    return handlers


def make_docs_handlers(worktree_path: str, repo_path: str) -> dict[str, Any]:
    """Docs agent: read-only + write_file (scoped to *.md and docs/**) + submit_docs."""
    from app.policy.engine import check_path_in_worktree

    handlers = make_read_only_handlers(repo_path)
    wt = Path(worktree_path)
    docs_result: dict[str, Any] = {}

    def write_file(inp: dict[str, Any]) -> str:
        rel_path = str(inp["path"])
        # Docs agent: only .md files or docs/** allowed
        is_md = rel_path.endswith(".md")
        is_docs = rel_path.startswith("docs/")
        if not (is_md or is_docs):
            return (
                f"[POLICY DENIED] Docs agent may only write .md files or paths under docs/. "
                f"Got: {rel_path!r}"
            )
        policy = check_path_in_worktree(rel_path, worktree_path)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        try:
            target = wt / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(inp["content"], encoding="utf-8")
            return f"Written: {rel_path}"
        except Exception as e:
            return f"[ERROR] Cannot write {rel_path}: {e}"

    handlers["write_file"] = write_file
    # tool_enhance.md productionization pass, tool #85 (2026-08-24) —
    # the shared, already-correct logic now lives in
    # make_submit_docs_handler(); see that function's own module
    # docstring.
    handlers["submit_docs"] = make_submit_docs_handler(docs_result)
    handlers["_docs_result"] = docs_result
    return handlers


# Docs agent tool list: read tools + write_file + submit_docs. NO bash.
DOCS_TOOLS = READ_ONLY_TOOLS + [
    {
        "name": "write_file",
        "description": "Write content to a markdown file (*.md) or a path under docs/ only. No other file types.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to the worktree root (must be *.md or docs/**)",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    _SUBMIT_DOCS_TOOL,
    RECORD_LEARNING_TOOL,
]

# ---------------------------------------------------------------------------
# CHAT AGENT TOOLS — full unrestricted access (dangerous cmds need confirmation)
# ---------------------------------------------------------------------------

# moved to app/tools/filesystem/delete_file.py as DELETE_FILE_TOOL —
# tool_enhance.md productionization pass, tool #17 (2026-08-17).

# _GIT_PUSH_TOOL moved to app/tools/git/push.py as GIT_PUSH_TOOL —
# tool_enhance.md productionization pass, tool #4 (2026-08-16).

# moved to app/tools/git/create_branch.py as CREATE_BRANCH_TOOL —
# tool_enhance.md productionization pass, tool #32 (2026-08-18).

_CHAT_BASH_TOOL = {
    "name": "bash",
    "description": (
        "Run any shell command in the repository. "
        "Dangerous commands (rm -rf, git push, docker push, kubectl delete, etc.) "
        "will be paused for user confirmation before executing. "
        "Use this for running tests, installs, builds, or any investigation command."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"},
            "cwd": {
                "type": "string",
                "description": "Working directory override (default: repo root)",
            },
        },
        "required": ["command"],
    },
}

# moved to app/tools/agents/submit_result.py as
# SUBMIT_RESULT_TOOL / submit_result_handler() —
# tool_enhance.md productionization pass, tool #194 (2026-09-16). Real
# behavior lives in chat_agent.py's own dispatch — see that module's
# own docstring for the full "two implementations, one genuinely
# unreachable" account.
_SUBMIT_RESULT_TOOL: dict[str, Any] = SUBMIT_RESULT_TOOL

# moved to app/tools/filesystem/append_file.py as APPEND_FILE_TOOL —
# tool_enhance.md productionization pass, tool #26 (2026-08-18).

# moved to app/tools/filesystem/rename_file.py as RENAME_FILE_TOOL — tool_enhance.md productionization pass, tool #56 (2026-08-20).

# moved to app/tools/filesystem/copy_file.py as COPY_FILE_TOOL /
# copy_file_handler() — tool_enhance.md productionization pass, tool
# #128 (2026-08-26).

# moved to app/tools/git/commit.py as GIT_COMMIT_TOOL — tool_enhance.md productionization pass, tool #37 (2026-08-18).

# moved to app/tools/git/branch.py as GIT_BRANCH_TOOL /
# git_branch_handler() — tool_enhance.md productionization pass,
# tool #148 (2026-09-14).

# moved to app/tools/git/checkout.py as GIT_CHECKOUT_TOOL —
# tool_enhance.md productionization pass, tool #35 (2026-08-18).

# moved to app/tools/git/stash.py as GIT_STASH_TOOL — tool_enhance.md productionization pass, tool #42 (2026-08-19).

# moved to app/tools/git/pull.py as GIT_PULL_TOOL — tool_enhance.md productionization pass, tool #39 (2026-08-18).

# moved to app/tools/git/fetch.py as GIT_FETCH_TOOL /
# git_fetch_handler() — tool_enhance.md productionization pass,
# tool #149 (2026-09-14).

# moved to app/tools/git/restore.py as GIT_RESTORE_TOOL — tool_enhance.md productionization pass, tool #41 (2026-08-19).

# moved to app/tools/execution/run_tests.py as RUN_TESTS_TOOL —
# tool_enhance.md productionization pass, tool #16 (2026-08-17).

# tool_enhance.md productionization pass, tool #101 (2026-08-25) —
# moved to app/tools/execution/run_linter.py as RUN_LINTER_TOOL
# (imported above, aliased to _RUN_LINTER_TOOL after the import
# block). Real, severe findings across all 4 real implementations: a
# direct shell-injection RCE on chat_agent.py's dispatch, a
# confirmation-bypass file-rewrite via flag-collision on path (same
# shlex.quote()-is-not-enough class seen repeatedly this window), two
# implementations totally broken by an invalid ruff CLI flag, and a
# documented-but-never-implemented eslint gap. See that module's own
# docstring for the full account.

# _BACKGROUND_PROCESSES used to be a module-level dict (shared across all sessions).
# It is now a per-session dict created inside make_chat_handlers() so that one session
# cannot kill or read output from another session's background process.

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 1: File / Editing extras
# ---------------------------------------------------------------------------

# moved to app/tools/filesystem/find_file.py as FIND_FILE_TOOL /
# find_file_handler() — tool_enhance.md productionization pass, tool
# #138 (2026-09-11).

# moved to app/tools/filesystem/format_file.py as FORMAT_FILE_TOOL /
# format_file_handler() — tool_enhance.md productionization pass, tool
# #143 (2026-09-11).

# moved to app/tools/filesystem/organize_imports.py as
# ORGANIZE_IMPORTS_TOOL — tool_enhance.md productionization pass, tool
# #115 (2026-08-26).

# moved to app/tools/filesystem/insert_at_line.py as INSERT_AT_LINE_TOOL — tool_enhance.md productionization pass, tool #47 (2026-08-19).

# moved to app/tools/filesystem/replace_function.py as
# REPLACE_FUNCTION_TOOL — tool_enhance.md productionization pass, tool
# #24 (2026-08-18).

# moved to app/tools/filesystem/delete_lines.py as DELETE_LINES_TOOL —
# tool_enhance.md productionization pass, tool #34 (2026-08-18).

# moved to app/tools/filesystem/apply_patch.py as APPLY_PATCH_TOOL —
# tool_enhance.md productionization pass, tool #27 (2026-08-18).

# moved to app/tools/filesystem/compare_files.py as
# COMPARE_FILES_TOOL / compare_files_handler() — tool_enhance.md
# productionization pass, tool #127 (2026-08-26).

# AUDIT_Q_BATCH01 §18 "Synchronize files" — no dedicated cross-file
# synchronization tool previously existed (rename_symbol's multi-file
# rewrite is incidental to a rename, not a general sync primitive). "paths"
# (not "targets") deliberately matches _POLICY_PATH_FIELD_NAMES in
# base_graph.py so the shared single-interceptor _policy_check
# automatically path-checks every target here, the same as read_files'
# own "paths" field — no special-casing needed there.
#
# moved to app/tools/filesystem/sync_files.py as SYNC_FILES_TOOL /
# sync_files_handler — tool_enhance.md productionization pass, tool #64
# (2026-08-22). This implementation's own check_path_in_worktree() calls
# were already correct; the real, severe finding was that
# chat_agent.py's own interactive dispatch (a separate code path from
# base_graph.py's interceptor mentioned above) had ZERO such validation
# — see that new module's docstring for the live proof (a real
# combined exfiltration + arbitrary-write via source="/etc/hostname").
_SYNC_FILES_TOOL = SYNC_FILES_TOOL

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 2: Terminal extras
# ---------------------------------------------------------------------------

# moved to app/tools/execution/run_background.py as RUN_BACKGROUND_TOOL /
# validate_run_background_cwd — tool_enhance.md productionization pass,
# tool #58 (2026-08-20). See that module's docstring for the real
# sandboxing finding (fixed in app/fleet/process_manager.py) and the
# retroactive kill_process (tool #49) fix found along the way.
_RUN_BACKGROUND_TOOL_DEF = RUN_BACKGROUND_TOOL

# moved to app/tools/execution/list_background_processes.py as
# LIST_BACKGROUND_PROCESSES_TOOL /
# list_background_processes_handler() — tool_enhance.md
# productionization pass, tool #162 (2026-09-15).

# AUDIT_Q_BATCH01 §58 "Concurrent command execution (fan-out)" — previously
# zero asyncio.gather/TaskGroup usage anywhere in backend/app; every
# bash-shaped tool ran exactly one command at a time even when a caller had
# several genuinely independent commands to run.
# _MAX_PARALLEL_COMMANDS / _RUN_PARALLEL_COMMANDS_TOOL moved to
# app/tools/execution/parallel.py as MAX_PARALLEL_COMMANDS /
# RUN_PARALLEL_COMMANDS_TOOL — tool_enhance.md productionization pass,
# tool #9 (2026-08-16).

# moved to app/tools/execution/kill_process.py as KILL_PROCESS_TOOL — tool_enhance.md productionization pass, tool #49 (2026-08-20).

# moved to app/tools/execution/python_snippet.py as RUN_PYTHON_SNIPPET_TOOL
# — tool_enhance.md productionization pass, tool #14 (2026-08-17).

# moved to app/tools/execution/run_make.py as RUN_MAKE_TOOL /
# run_make_handler — tool_enhance.md productionization pass, tool #59
# (2026-08-22). See that module's docstring for the real findings (a
# classic shell-injection bug in chat_agent.py's own dispatch, a second
# GNU-make-own-flag code-execution primitive affecting BOTH real
# implementations even with list-args, and a directory worktree-escape).
_RUN_MAKE_TOOL = RUN_MAKE_TOOL

# tool_enhance.md productionization pass, tool #86 (2026-08-24) — moved
# to app/tools/execution/fetch_url.py as FETCH_URL_TOOL (imported
# above as _FETCH_URL_TOOL). See that module's docstring — the
# unbounded-timeout finding flagged back in tool #14 is now closed;
# ae_fetch_url (ai_engineer) previously ignored this schema's own
# timeout/summarize fields entirely, now unified onto the same
# shared, fixed handler.

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 3: Git extras
# ---------------------------------------------------------------------------

# moved to app/tools/git/merge.py as GIT_MERGE_TOOL — tool_enhance.md productionization pass, tool #38 (2026-08-18).

# ---------------------------------------------------------------------------
# Gap-closure Day 51 (Stage 2, answers.md Q40 "Merge conflict resolution/
# explanation": NOT FOUND — "git_merge exists but does nothing special on
# conflict — just returns raw stdout/stderr"). Repo research
# (repos/cline/apps/vscode/src/core/controller/worktree/mergeWorktree.ts):
# cline detects a failed merge and lists conflicted files via
# `git diff --name-only --diff-filter=U` rather than scraping stdout text —
# that detection technique is reused in git_merge below. cline stops there
# (aborts the merge and reports file names); actual conflict-marker parsing
# and a resolution-assist tool are this session's own original addition —
# no repo in repos/ implements real git-merge-conflict-marker parsing
# (aider's own `<<<<<<<`/`=======`/`>>>>>>>` hits are its unrelated
# SEARCH/REPLACE edit-block format, not git conflicts).
# ---------------------------------------------------------------------------


# moved to app/tools/git/parse_merge_conflicts.py as
# PARSE_MERGE_CONFLICTS_TOOL / parse_merge_conflicts_handler() —
# tool_enhance.md productionization pass, tool #228 (2026-09-17). Same
# "two real implementations" shape already fixed on sibling tool #136
# (explain_merge_conflict) — BOTH real call sites (this closure AND
# chat_agent.py's own dispatch) now delegate to the shared handler.
_PARSE_MERGE_CONFLICTS_TOOL = PARSE_MERGE_CONFLICTS_TOOL

# moved to app/tools/git/explain_merge_conflict.py as
# EXPLAIN_MERGE_CONFLICT_TOOL / explain_merge_conflict_handler() —
# tool_enhance.md productionization pass, tool #136 (2026-09-11).

# moved to app/tools/git/resolve_merge_conflict.py as
# RESOLVE_MERGE_CONFLICT_TOOL / resolve_merge_conflict_handler() —
# tool_enhance.md productionization pass, tool #229 (2026-09-17). Same
# "two real implementations" shape already fixed on sibling tools #136
# (explain_merge_conflict) and #228 (parse_merge_conflicts) — BOTH
# real call sites now delegate to the shared handler.
_RESOLVE_MERGE_CONFLICT_TOOL = RESOLVE_MERGE_CONFLICT_TOOL

# _GIT_RESET_TOOL moved to app/tools/git/reset.py as GIT_RESET_TOOL —
# tool_enhance.md productionization pass, tool #5 (2026-08-16).

# moved to app/tools/git/worktree.py as GIT_WORKTREE_TOOL — tool_enhance.md productionization pass, tool #43 (2026-08-19).

# _CREATE_PR_TOOL moved to app/tools/git/pull_request.py as CREATE_PR_TOOL
# (imported near the top of this file as _CREATE_PR_TOOL) —
# tool_enhance.md productionization pass, tool #2 (2026-08-15).

# moved to app/tools/git/generate_commit_msg.py as
# GENERATE_COMMIT_MSG_TOOL / generate_commit_msg_handler() —
# tool_enhance.md productionization pass, tool #145 (2026-09-14).

# moved to app/tools/git/review_diff.py as REVIEW_DIFF_TOOL /
# build_review_diff_args() — tool_enhance.md productionization pass,
# tool #179 (2026-09-15).
_REVIEW_DIFF_TOOL: dict[str, Any] = REVIEW_DIFF_TOOL

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 4: Testing extras
# ---------------------------------------------------------------------------

# moved to app/tools/execution/run_single_test.py as
# RUN_SINGLE_TEST_TOOL / run_single_test_handler — tool_enhance.md
# productionization pass, tool #62 (2026-08-22). See that module's
# docstring: chat_agent.py's own dispatch had a real shell-injection bug
# (this implementation was already correctly shlex.quote()'d); the real
# finding shared by BOTH implementations was a `file` worktree-escape —
# pytest collection executes a Python file's module-level code at
# import time, proved live with a real outside-repo file's os.system()
# side effect genuinely running.
_RUN_SINGLE_TEST_TOOL = RUN_SINGLE_TEST_TOOL

# tool_enhance.md productionization pass, tool #104 (2026-08-25) —
# moved to app/tools/execution/coverage_report.py as
# COVERAGE_REPORT_TOOL (imported above, aliased to
# _COVERAGE_REPORT_TOOL after the import block). Real, severe finding:
# pytest-cov was never an installed project dependency at all — 2 of 3
# implementations hard-failed every real call, the 3rd silently
# returned a test-collection list instead of coverage data. Also a
# genuine shell-injection RCE on chat_agent.py's dispatch, plus a
# flag-collision + worktree escape on `path`. See that module's own
# docstring for the full account.

# moved to app/tools/execution/type_check.py as
# TYPE_CHECK_TOOL / type_check_handler() — tool_enhance.md
# productionization pass, tool #205 (2026-09-16).
_TYPE_CHECK_TOOL: dict[str, Any] = TYPE_CHECK_TOOL

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 5: Code Intelligence
# ---------------------------------------------------------------------------

# tool_enhance.md productionization pass, tool #82 (2026-08-24) — moved
# to app/tools/filesystem/list_functions.py as LIST_FUNCTIONS_TOOL
# (imported above as _LIST_FUNCTIONS_TOOL to preserve every existing
# reference). See that module's docstring — this was the widest
# consolidation in the low-risk tier so far: all NINE real
# implementations across 32 agents now delegate to one shared,
# corrected handler.

# tool_enhance.md productionization pass, tool #87 (2026-08-24) — moved
# to app/tools/filesystem/list_classes.py as LIST_CLASSES_TOOL
# (imported above). Sibling tool to tool #82's list_functions, same
# four finding classes proved independently: worktree escape + an
# uncaught PermissionError on the 2 single-file implementations, a
# field-name mismatch (`file` vs schema's `path`) in 3 agent-specific
# ones, a relative-traversal worktree escape in 2 more, and a
# single-file-vs-subtree design mismatch across all 5.
_LIST_CLASSES_TOOL = LIST_CLASSES_TOOL

# tool_enhance.md productionization pass, tool #111 (2026-08-26) —
# moved to app/tools/filesystem/find_function_body.py as
# FIND_FUNCTION_BODY_TOOL (imported above, aliased to
# _FIND_FUNCTION_BODY_TOOL after the import block). Real, severe
# findings: bf_/rf_find_function_body read a nonexistent `name` field
# (schema declares `function_name`) — a 100% KeyError crash rate — and
# also ignored `path`/never extracted a real body; the two already-
# correct implementations had zero worktree-boundary validation,
# proved live to read an arbitrary host file's complete source. See
# that module's own docstring for the full account.

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 6: Debug tools
# ---------------------------------------------------------------------------

# moved to app/tools/execution/read_logs.py as READ_LOGS_TOOL —
# tool_enhance.md productionization pass, tool #116 (2026-08-26).

# moved to app/tools/execution/analyze_error.py as ANALYZE_ERROR_TOOL /
# analyze_error_handler() — tool_enhance.md productionization pass,
# tool #121 (2026-08-26).

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 7: Database tools
# ---------------------------------------------------------------------------

# moved to app/tools/database/sql.py as RUN_SQL_TOOL —
# tool_enhance.md productionization pass, tool #15 (2026-08-17).

# tool_enhance.md productionization pass, tool #96 (2026-08-25) — moved
# to app/tools/database/inspect_schema.py as INSPECT_SCHEMA_TOOL
# (imported above, aliased to _INSPECT_SCHEMA_TOOL after the import
# block). Real, proven SQL injection via `table` on all 5 real
# implementations, same class as tool #15's run_sql — fixed by full
# replacement with real psycopg2 parameter binding, no more psql
# subprocess. See that module's own docstring for the full account.

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 8: Docker tools
# ---------------------------------------------------------------------------

# tool_enhance.md productionization pass, tool #109 (2026-08-26) —
# moved to app/tools/execution/docker_ps.py as DOCKER_PS_TOOL
# (imported above, aliased to _DOCKER_PS_TOOL after the import block
# — app/agents/monitoring_agent.py imports this name directly, checked
# proactively before wiring). Real finding: dk_docker_ps completely
# ignored the `all` field, hiding real stopped/failed containers even
# when explicitly requested. See that module's own docstring.

# tool_enhance.md productionization pass, tool #108 (2026-08-25) —
# moved to app/tools/execution/docker_logs.py as DOCKER_LOGS_TOOL
# (imported above, aliased to _DOCKER_LOGS_TOOL after the import
# block — app/agents/monitoring_agent.py imports this name directly,
# checked proactively before wiring). Real, severe finding: a genuine
# shell-injection RCE on chat_agent.py's dispatch (also missing the
# log-pattern analysis step its siblings have), plus a flag-collision
# on `container` and an uncaught ValueError on `lines`, across all 3
# real implementations. See that module's own docstring for the full
# account.

# moved to app/tools/execution/docker_exec.py as DOCKER_EXEC_TOOL —
# tool_enhance.md productionization pass, tool #20 (2026-08-17).

# moved to app/tools/execution/docker_compose.py as DOCKER_COMPOSE_TOOL —
# tool_enhance.md productionization pass, tool #19 (2026-08-17).

# tool_enhance.md productionization pass, tool #106 (2026-08-25) —
# moved to app/tools/execution/diagnose_deployment_failure.py as
# DIAGNOSE_DEPLOYMENT_FAILURE_TOOL (imported above, aliased to
# _DIAGNOSE_DEPLOYMENT_FAILURE_TOOL after the import block). Real,
# severe finding: a genuine shell-injection RCE on chat_agent.py's
# dispatch, plus a flag-collision on `container` and an uncaught
# ValueError on `lines`, across all 3 real implementations. See that
# module's own docstring for the full account, including why the LLM
# diagnosis step (_llm_diagnose_deployment_failure, below) deliberately
# stays in this file.

# ---------------------------------------------------------------------------
# NEW TOOL SPECS — Batch 9: Security
# ---------------------------------------------------------------------------

# tool_enhance.md productionization pass, tool #102 (2026-08-25) —
# moved to app/tools/filesystem/secrets_scan.py as SECRETS_SCAN_TOOL
# (imported above, aliased to _SECRETS_SCAN_TOOL after the import
# block). Real findings: worktree escape + content disclosure on all
# 3 implementations, PLUS a genuine shell-injection RCE on
# chat_agent.py's own third, independently-drifted implementation
# (never migrated onto the canonical scanner despite AUDIT_Q_BATCH11
# §96 unifying the other two years earlier). See that module's own
# docstring for the full account.

# ---------------------------------------------------------------------------
# DAY 1 TOOL SPECS — Batches 10-16
# ---------------------------------------------------------------------------

# Batch 10 — AST Engine
# tool_enhance.md productionization pass, tool #83 (2026-08-24) — moved
# to app/tools/filesystem/parse_ast.py as PARSE_AST_TOOL (imported
# above as _PARSE_AST_TOOL to preserve every existing reference). See
# that module's docstring — all SEVEN real implementations shared the
# identical worktree-escape + uncaught-PermissionError bug, now
# unified onto one shared parse_ast_handler().

# tool_enhance.md productionization pass, tool #95 (2026-08-25) — moved
# to app/tools/filesystem/import_graph.py as IMPORT_GRAPH_TOOL
# (imported above, aliased to _IMPORT_GRAPH_TOOL after the import
# block). Same worktree-escape + uncaught-PermissionError bug class as
# sibling tool #83's parse_ast, proved live across all 4 real
# implementations.

# tool_enhance.md productionization pass, tool #93 (2026-08-25) — moved
# to app/tools/filesystem/call_graph.py as CALL_GRAPH_TOOL (imported
# above, aliased to _CALL_GRAPH_TOOL after the import block). Sibling
# tool to tool #83's parse_ast, same finding classes (worktree escape
# + uncaught PermissionError) proved independently on all 5 real
# implementations, same underlying ast_engine module.

# tool_enhance.md productionization pass, tool #94 (2026-08-25) — moved
# to app/tools/filesystem/dead_code_detect.py as DEAD_CODE_DETECT_TOOL
# (imported above, aliased to _DEAD_CODE_DETECT_TOOL after the import
# block). Worktree escape on all 4 real implementations, proved live —
# an uncaught PermissionError (the class established by sibling tools
# #83/#93) was checked and confirmed NOT reproducible here, since
# pathlib's rglob() silently swallows PermissionError during traversal.

# tool_enhance.md productionization pass, tool #97 (2026-08-25) — moved
# to app/tools/filesystem/circular_dep_detect.py as
# CIRCULAR_DEP_DETECT_TOOL (imported above, aliased to
# _CIRCULAR_DEP_DETECT_TOOL after the import block). Same worktree-
# escape finding + PermissionError-swallowing shape as sibling tool
# #94's dead_code_detect (same ast_engine module), proved live across
# all 3 real implementations.

# moved to app/tools/refactor/rename_symbol.py as RENAME_SYMBOL_TOOL —
# tool_enhance.md productionization pass, tool #23 (2026-08-18).

# Batch 11 — Git extras
# moved to app/tools/git/rebase.py as GIT_REBASE_TOOL — tool_enhance.md productionization pass, tool #40 (2026-08-18).

# moved to app/tools/git/cherry_pick.py as GIT_CHERRY_PICK_TOOL —
# tool_enhance.md productionization pass, tool #36 (2026-08-18).

# Batch 12 — Terminal extras
# moved to app/tools/execution/read_output.py as READ_OUTPUT_TOOL /
# read_output_handler() — tool_enhance.md productionization pass, tool
# #176 (2026-09-15).
_READ_OUTPUT_TOOL: dict[str, Any] = READ_OUTPUT_TOOL

# moved to app/tools/execution/run_node.py as RUN_NODE_TOOL /
# run_node_handler — tool_enhance.md productionization pass, tool #60
# (2026-08-22). See that module's docstring: `code` was already safely
# shlex.quote()'d on both real call sites; the real finding was an
# unbounded `timeout` on both, same class as run_python_snippet (#14).
_RUN_NODE_TOOL = RUN_NODE_TOOL

# moved to app/tools/execution/run_script.py as RUN_SCRIPT_TOOL /
# run_script_handler — tool_enhance.md productionization pass, tool #61
# (2026-08-22). See that module's docstring for the real findings: a
# classic shell-injection bug in chat_agent.py's own dispatch, a severe
# arbitrary-program-execution primitive via `interpreter` affecting BOTH
# real implementations even with list-args (proved live: interpreter=
# "rm" deleted a real file), and a `path` worktree-escape.
_RUN_SCRIPT_TOOL = RUN_SCRIPT_TOOL

# moved to app/tools/execution/docker_build.py as DOCKER_BUILD_TOOL —
# tool_enhance.md productionization pass, tool #18 (2026-08-17).

# moved to app/tools/execution/docker_restart.py as DOCKER_RESTART_TOOL
# — tool_enhance.md productionization pass, tool #21 (2026-08-17).

# Batch 13 — Smart search
# tool_enhance.md productionization pass, tool #90 (2026-08-24) — moved
# to app/tools/filesystem/find_route.py as FIND_ROUTE_TOOL (imported
# above as _FIND_ROUTE_TOOL). See that module's docstring — a severe
# field-name mismatch (schema declares `path_pattern`, 2 of 4 real
# implementations read a nonexistent `path` field and ignored `method`
# entirely) caused every real, schema-conformant call to those two to
# silently return the wrong (fixed-fallback) results.

# tool_enhance.md productionization pass, tool #89 (2026-08-24) — moved
# to app/tools/filesystem/find_api.py as FIND_API_TOOL (imported above
# as _FIND_API_TOOL). See that module's docstring — `name` was
# flag-injection vulnerable on all 4 real implementations, including
# chat_agent.py's dispatch (its shlex.quote() only protects against
# shell metacharacters, not grep's own argv-level flag parsing).

# tool_enhance.md productionization pass, tool #91 (2026-08-24) — moved
# to app/tools/filesystem/find_sql.py as FIND_SQL_TOOL (imported above
# as _FIND_SQL_TOOL). See that module's docstring — `keyword` was
# flag-injection vulnerable on 4 of 5 real implementations; the 5th
# (pure-Python, no subprocess) had a real functionality bug instead
# (empty keyword searched only "SELECT", not the full SQL keyword set
# the schema promises).

# moved to app/tools/filesystem/find_test.py as FIND_TEST_TOOL /
# find_test_handler() — tool_enhance.md productionization pass, tool
# #140 (2026-09-11).

# tool_enhance.md productionization pass, tool #99 (2026-08-25) — moved
# to app/tools/filesystem/find_config.py as FIND_CONFIG_TOOL (imported
# above, aliased to _FIND_CONFIG_TOOL after the import block). Real
# findings: a flag-collision class (same as tools #69/#89/#90/#91) on
# 2 of 3 implementations, plus sec_find_config ignoring `key` entirely
# and running a fixed hardcoded regex instead. See that module's own
# docstring for the full account.

# Batch 14 — Monitoring
# tool_enhance.md productionization pass, tool #105 (2026-08-25) —
# moved to app/tools/execution/cpu_usage.py as CPU_USAGE_TOOL
# (imported above, aliased to _CPU_USAGE_TOOL after the import block).
# Real finding: a single /proc/stat read was mislabeled as "current"
# CPU usage on 2 of 3 implementations — proved live, a real two-sample
# delta read reported a genuinely different number (9.6% vs 22.4%) at
# the exact same moment. See that module's own docstring for the full
# account.

# tool_enhance.md productionization pass, tool #114 (2026-08-26) —
# moved to app/tools/execution/memory_usage.py as MEMORY_USAGE_TOOL
# (imported above, aliased to _MEMORY_USAGE_TOOL after the import
# block). No LLM-controlled input (empty schema). Real finding:
# mon_memory_usage had no try/except around its free subprocess call
# — an uncaught FileNotFoundError if free is missing — and never
# preferred /proc/meminfo like its siblings. See that module's own
# docstring.

# tool_enhance.md productionization pass, tool #107 (2026-08-25) —
# moved to app/tools/execution/disk_usage.py as DISK_USAGE_TOOL
# (imported above, aliased to _DISK_USAGE_TOOL after the import
# block). Real findings: mon_disk_usage diverged from this tool's own
# documented contract (used `df` instead of the documented
# shutil.disk_usage, defaulted to "/" instead of the documented repo
# root), plus zero worktree-boundary validation on all 3
# implementations. See that module's own docstring for the full
# account.

# tool_enhance.md productionization pass, tool #113 (2026-08-26) —
# moved to app/tools/execution/health_check.py as HEALTH_CHECK_TOOL
# (imported above, aliased to _HEALTH_CHECK_TOOL after the import
# block). Real, severe finding: mon_health_check completely ignored
# `service` (the only documented field) and read an entirely
# undocumented `url` field instead — a real SSRF surface — and never
# checked database connectivity at all. See that module's own
# docstring for the full account.

# moved to app/tools/database/task_progress.py as TASK_PROGRESS_TOOL /
# task_progress_handler() — tool_enhance.md productionization pass,
# tool #119 (2026-08-26).

# Batch 15 — Editing extras
# moved to app/tools/filesystem/replace_class.py as REPLACE_CLASS_TOOL — tool_enhance.md productionization pass, tool #57 (2026-08-20).

_UNDO_CHANGES_TOOL = {
    "name": "undo_changes",
    "description": (
        "Restore a file to its last committed state using `git checkout -- <path>`. "
        "This DISCARDS all uncommitted changes to that file. Requires confirmation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path to restore (relative to repo root)",
            },
        },
        "required": ["path"],
    },
}

# moved to app/tools/filesystem/generate_patch.py as
# GENERATE_PATCH_TOOL / generate_patch_handler() —
# tool_enhance.md productionization pass, tool #147 (2026-09-14).

# Batch 16 — DB extras
# tool_enhance.md productionization pass, tool #98 (2026-08-25) — moved
# to app/tools/database/explain_query.py as EXPLAIN_QUERY_TOOL
# (imported above, aliased to _EXPLAIN_QUERY_TOOL after the import
# block). Real, severe finding: this tool's own schema promises
# "Read-only (EXPLAIN does not modify data)" — proved FALSE two ways
# (statement stacking AND a single non-SELECT statement both genuinely
# mutated real data via EXPLAIN ANALYZE) across all 4 real
# implementations. See that module's own docstring for the full
# account.

# _RUN_MIGRATION_TOOL moved to app/tools/database/migration.py as
# RUN_MIGRATION_TOOL — tool_enhance.md productionization pass, tool #8
# (2026-08-16).

# _SEED_DATABASE_TOOL moved to app/tools/database/seed.py as
# SEED_DATABASE_TOOL — tool_enhance.md productionization pass, tool #10
# (2026-08-16).


# ===========================================================================
# Day 2 Agents — shared tool spec constants, tool lists, handler factories
# ===========================================================================

# moved to app/tools/filesystem/edit_file.py as EDIT_FILE_TOOL —
# tool_enhance.md productionization pass, tool #13 (2026-08-17).
_EDIT_FILE_TOOL_SPEC = _EDIT_FILE_TOOL

# moved to app/tools/filesystem/write_file.py as WRITE_FILE_TOOL —
# tool_enhance.md productionization pass, tool #12 (2026-08-17).
_WRITE_FILE_TOOL_SPEC = _WRITE_FILE_TOOL

# tool_enhance.md productionization pass, tool #84 (2026-08-24) — moved
# to app/tools/git/diff.py as GIT_DIFF_TOOL (imported above as
# git_diff_handler; this alias preserves every existing reference to
# the old name across BUG_FIX_AGENT_TOOLS/REFACTOR_AGENT_TOOLS/
# CHAT_TOOLS).
_GIT_DIFF_TOOL_SPEC = GIT_DIFF_TOOL

# --- Day 2 submit tool specs ---

# moved to app/tools/agents/submit_bug_fix.py as
# SUBMIT_BUG_FIX_TOOL / submit_bug_fix_handler() — tool_enhance.md
# productionization pass, tool #211 (2026-09-16).
_SUBMIT_BUG_FIX_TOOL: dict[str, Any] = SUBMIT_BUG_FIX_TOOL

# moved to app/tools/agents/submit_security_report.py as
# SUBMIT_SECURITY_REPORT_TOOL / submit_security_report_handler() —
# tool_enhance.md productionization pass, tool #197 (2026-09-16).
_SUBMIT_SECURITY_REPORT_TOOL: dict[str, Any] = SUBMIT_SECURITY_REPORT_TOOL

# moved to app/tools/agents/submit_arch_review.py as
# SUBMIT_ARCH_REVIEW_TOOL / submit_arch_review_handler() —
# tool_enhance.md productionization pass, tool #181 (2026-09-15).
# (Retains the Gap-closure Day 48 (Stage 2) schema fix in its new
# home's own docstring — {structure_summary, risks, recommendations,
# blast_radius, import_graph_ran}, matching roles/architecture_reviewer.md
# and run_arch_review()'s own consuming code exactly.)
_SUBMIT_ARCH_REVIEW_TOOL: dict[str, Any] = SUBMIT_ARCH_REVIEW_TOOL

# moved to app/tools/agents/submit_sql_report.py as
# SUBMIT_SQL_REPORT_TOOL / submit_sql_report_handler() —
# tool_enhance.md productionization pass, tool #199 (2026-09-16).
_SUBMIT_SQL_REPORT_TOOL: dict[str, Any] = SUBMIT_SQL_REPORT_TOOL

# moved to app/tools/agents/submit_docker_report.py as
# SUBMIT_DOCKER_REPORT_TOOL / submit_docker_report_handler() —
# tool_enhance.md productionization pass, tool #186 (2026-09-16).
_SUBMIT_DOCKER_REPORT_TOOL: dict[str, Any] = SUBMIT_DOCKER_REPORT_TOOL

# moved to app/tools/agents/submit_cicd_report.py as
# SUBMIT_CICD_REPORT_TOOL / submit_cicd_report_handler() —
# tool_enhance.md productionization pass, tool #183 (2026-09-15).
_SUBMIT_CICD_REPORT_TOOL: dict[str, Any] = SUBMIT_CICD_REPORT_TOOL

# moved to app/tools/agents/submit_refactor_report.py as
# SUBMIT_REFACTOR_REPORT_TOOL / submit_refactor_report_handler() —
# tool_enhance.md productionization pass, tool #192 (2026-09-16).
_SUBMIT_REFACTOR_REPORT_TOOL: dict[str, Any] = SUBMIT_REFACTOR_REPORT_TOOL

# moved to app/tools/agents/submit_dependency_report.py as
# SUBMIT_DEPENDENCY_REPORT_TOOL / submit_dependency_report_handler() —
# tool_enhance.md productionization pass, tool #185 (2026-09-16).
# Pre-existing Gap-closure Day 49 (Stage 2) schema/consumer-mismatch
# history preserved in that module's own docstring.
_SUBMIT_DEPENDENCY_REPORT_TOOL: dict[str, Any] = SUBMIT_DEPENDENCY_REPORT_TOOL

# moved to app/tools/agents/submit_monitoring_report.py as
# SUBMIT_MONITORING_REPORT_TOOL / submit_monitoring_report_handler() —
# tool_enhance.md productionization pass, tool #189 (2026-09-16).
_SUBMIT_MONITORING_REPORT_TOOL: dict[str, Any] = SUBMIT_MONITORING_REPORT_TOOL

_CICD_BASH_TOOL_SPEC = {
    "name": "bash",
    "description": "Run shell command. CI/CD agent limited to: git log/diff/status/show, cat, grep, echo, ls.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_REFACTOR_BASH_TOOL_SPEC = {
    "name": "bash",
    "description": "Run shell command. Refactor agent limited to: python -m pytest, mypy, ruff, black, isort.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_DEPENDENCY_BASH_TOOL_SPEC = {
    "name": "bash",
    "description": "Run dependency commands: pip index versions, pip show/list, npm audit/outdated/list.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

# Stage 4 Tier 3 (2026-08-05, answer2.md Q92) — "abandoned" is a distinct
# signal from "outdated": `pip index versions`/`npm outdated` (the bash
# tool above) only compare the installed version against the latest
# available one, never expose *when* that latest version was actually
# published — a package whose latest release is 4 years old looks
# identical to an actively-maintained one if that's the only version ever
# installed. Real registry API calls (PyPI's/npm's own public JSON APIs,
# verified live against real packages before writing this), not a
# heuristic or the LLM's own training-time guess.
# moved to app/tools/integrations/check_last_release.py as
# CHECK_LAST_RELEASE_TOOL / check_last_release_handler() —
# tool_enhance.md productionization pass, tool #218 (2026-09-17).
# Real finding: datetime.fromisoformat(upload_time...) had no
# try/except at all (one line after a separate, already-closed
# try/except block) — a malformed registry timestamp raised an
# uncaught ValueError. Fixed by wrapping the date-parsing block in its
# own try/except (ValueError, OverflowError, AttributeError).
_CHECK_LAST_RELEASE_TOOL = CHECK_LAST_RELEASE_TOOL

# T2-B5 (2026-09-22, GRIDIRON_PARTIAL #463) — a real resolvelib-backed
# SAT-solver-style conflict check, distinct from check_last_release above
# (that answers "is this ONE package's pinned version stale/abandoned";
# this answers "can this SET of proposed version constraints be satisfied
# simultaneously across their real transitive dependency trees").
_CHECK_DEPENDENCY_CONFLICTS_TOOL = CHECK_DEPENDENCY_CONFLICTS_TOOL

# --- Day 2 Tool Lists ---

BUG_FIX_TOOLS = READ_ONLY_TOOLS + [
    _PARSE_AST_TOOL,
    _CALL_GRAPH_TOOL,
    _FIND_FUNCTION_BODY_TOOL,
    _ANALYZE_ERROR_TOOL,
    _READ_LOGS_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _GIT_DIFF_TOOL_SPEC,
    _SUBMIT_BUG_FIX_TOOL,
    RECORD_LEARNING_TOOL,
]

SECURITY_REVIEWER_TOOLS = READ_ONLY_TOOLS + [
    _SECRETS_SCAN_TOOL,
    _FIND_SQL_TOOL,
    _FIND_CONFIG_TOOL,
    _FIND_API_TOOL,
    _FIND_ROUTE_TOOL,
    _SUBMIT_SECURITY_REPORT_TOOL,
]

ARCH_REVIEWER_TOOLS = READ_ONLY_TOOLS + [
    _IMPORT_GRAPH_TOOL,
    _CIRCULAR_DEP_DETECT_TOOL,
    _DEAD_CODE_DETECT_TOOL,
    _SCAN_CODE_HYGIENE_TOOL,
    _SCAN_RELIABILITY_TOOL,
    _PARSE_AST_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _CALL_GRAPH_TOOL,
    _SUBMIT_ARCH_REVIEW_TOOL,
]

SQL_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    _FIND_SQL_TOOL,
    _EXPLAIN_QUERY_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_SQL_REPORT_TOOL,
]

DOCKER_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _DOCKER_PS_TOOL,
    _DOCKER_LOGS_TOOL,
    _DOCKER_EXEC_TOOL,
    _DOCKER_COMPOSE_TOOL,
    _DOCKER_BUILD_TOOL,
    _DOCKER_RESTART_TOOL,
    _DIAGNOSE_DEPLOYMENT_FAILURE_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_DOCKER_REPORT_TOOL,
]

CICD_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _CICD_BASH_TOOL_SPEC,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_CICD_REPORT_TOOL,
]

REFACTOR_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _FIND_FUNCTION_BODY_TOOL,
    _PARSE_AST_TOOL,
    _CALL_GRAPH_TOOL,
    _IMPORT_GRAPH_TOOL,
    _RENAME_SYMBOL_TOOL,
    _BATCH_EDIT_TOOL,
    _REPLACE_FUNCTION_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _GIT_DIFF_TOOL_SPEC,
    _REFACTOR_BASH_TOOL_SPEC,
    _SUBMIT_REFACTOR_REPORT_TOOL,
]

README_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _PARSE_AST_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_DOCS_TOOL,
]

API_DOCS_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _FIND_ROUTE_TOOL,
    _FIND_API_TOOL,
    _PARSE_AST_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_DOCS_TOOL,
]

DEPENDENCY_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _DEPENDENCY_BASH_TOOL_SPEC,
    _CHECK_LAST_RELEASE_TOOL,
    _CHECK_DEPENDENCY_CONFLICTS_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _SUBMIT_DEPENDENCY_REPORT_TOOL,
]

MONITORING_AGENT_TOOLS = READ_ONLY_TOOLS + [
    _CPU_USAGE_TOOL,
    _MEMORY_USAGE_TOOL,
    _DISK_USAGE_TOOL,
    _HEALTH_CHECK_TOOL,
    _TASK_PROGRESS_TOOL,
    _READ_LOGS_TOOL,
    _SUBMIT_MONITORING_REPORT_TOOL,
]


# --- Day 2 shared sub-factories (reduce duplication) ---


def _make_edit_file_handler(root: Path) -> Any:
    # moved to app/tools/filesystem/edit_file.py as edit_file_handler —
    # tool_enhance.md productionization pass, tool #13 (2026-08-17).
    def edit_file_h(inp: dict[str, Any]) -> str:
        return edit_file_handler(root, str(root), inp)

    return edit_file_h


def _make_write_file_handler(root: Path) -> Any:
    # moved to app/tools/filesystem/write_file.py as write_file_handler —
    # tool_enhance.md productionization pass, tool #12 (2026-08-17).
    def write_file_h(inp: dict[str, Any]) -> str:
        return write_file_handler(root, str(root), inp)

    return write_file_h


# tool_enhance.md productionization pass, tool #84 (2026-08-24) — the
# real fix (ZERO `--` separator before `file` — a silent
# arbitrary-file-write via git's own --output=<path> flag, same class
# as tool #80's git_show) lives in the shared git_diff_handler()
# itself; see that function's own module docstring.
def _make_git_diff_handler(repo_path: str) -> Any:
    root = Path(repo_path)

    def git_diff_h(inp: dict[str, Any]) -> str:
        return git_diff_handler(root, inp)

    return git_diff_h


# --- Day 2 Handler Factories ---


def make_bug_fix_handlers(repo_path: str) -> dict[str, Any]:
    """Bug Fix agent: read-only + AST analysis + direct file writes + submit_bug_fix."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix (ZERO worktree-boundary validation + an uncaught
    # PermissionError, same class shared by all 7 real implementations)
    # lives in the shared parse_ast_handler() itself; see that
    # function's own module docstring.
    def bf_parse_ast(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #93 (2026-08-25) — the
    # real fix lives in the shared call_graph_handler(); see that
    # function's own module docstring.
    def bf_call_graph(inp: dict[str, Any]) -> str:
        return call_graph_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #111 (2026-08-26) — the
    # real fix (this implementation read a nonexistent `name` field —
    # the schema declares `function_name` — a 100% KeyError crash rate
    # on every real, schema-conformant call; it also ignored `path`
    # entirely and never actually extracted a function body, just raw
    # grep match lines) lives in the shared
    # find_function_body_handler(); see that function's own module
    # docstring.
    def bf_find_function_body(inp: dict[str, Any]) -> str:
        return find_function_body_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #121 (2026-08-26) —
    # was a severe field-name mismatch (read `inp.get("traceback",
    # "")` while the schema requires and every real caller sends
    # `error`) causing a 100% functional-failure rate — proved live: a
    # genuine traceback always produced "(no error markers found)".
    # Now delegates to the shared, correct, full-contract handler.
    def bf_analyze_error(inp: dict[str, Any]) -> str:
        return analyze_error_handler(inp)

    # tool_enhance.md productionization pass, tool #116 (2026-08-26) —
    # was a worktree-escape arbitrary file READ (`root / log_path`
    # silently discards `root` when `log_path` is absolute — real
    # pathlib semantics) and silently ignored the schema's own
    # documented `level`/journalctl behavior. Now delegates to the
    # shared, worktree-validated, full-contract handler.
    def bf_read_logs(inp: dict[str, Any]) -> str:
        return read_logs_handler(root, repo_path, inp)

    handlers["parse_ast"] = bf_parse_ast
    handlers["call_graph"] = bf_call_graph
    handlers["find_function_body"] = bf_find_function_body
    handlers["analyze_error"] = bf_analyze_error
    handlers["read_logs"] = bf_read_logs
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["git_diff"] = _make_git_diff_handler(repo_path)
    handlers["submit_bug_fix"] = submit_bug_fix_handler
    return handlers


def make_security_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Security reviewer: read-only + specialized search + submit_security_report. No writes."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)

    # tool_enhance.md productionization pass, tool #102 (2026-08-25) — the
    # real fix (ZERO worktree-boundary validation on `directory`) lives
    # in the shared secrets_scan_handler(); see that function's own
    # module docstring.
    def sec_secrets_scan(inp: dict[str, Any]) -> str:
        return secrets_scan_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #91 (2026-08-24) — the
    # real fix (ZERO validation of `keyword` — a flag-injection bug,
    # same class as tool #69's search_code) lives in the shared
    # find_sql_handler() itself; see that function's own module
    # docstring.
    def sec_find_sql(inp: dict[str, Any]) -> str:
        return find_sql_handler(root, inp)

    # tool_enhance.md productionization pass, tool #99 (2026-08-25) — the
    # real fix (this implementation IGNORED `key` entirely — it read a
    # nonexistent `file_pattern` field and ran a fixed, hardcoded regex)
    # lives in the shared find_config_handler(); see that function's own
    # module docstring.
    def sec_find_config(inp: dict[str, Any]) -> str:
        return find_config_handler(root, inp)

    # tool_enhance.md productionization pass, tool #89 (2026-08-24) — the
    # real fix (ZERO validation of `name` — a flag-injection bug, same
    # class as tool #69's search_code) lives in the shared
    # find_api_handler() itself; see that function's own module
    # docstring.
    def sec_find_api(inp: dict[str, Any]) -> str:
        return find_api_handler(root, inp)

    # tool_enhance.md productionization pass, tool #90 (2026-08-24) — the
    # real fix (this implementation read a nonexistent `path` field —
    # the schema declares `path_pattern` — and ignored `method`
    # entirely) lives in the shared find_route_handler() itself; see
    # that function's own module docstring.
    def sec_find_route(inp: dict[str, Any]) -> str:
        return find_route_handler(root, inp)

    handlers["secrets_scan"] = sec_secrets_scan
    handlers["find_sql"] = sec_find_sql
    handlers["find_config"] = sec_find_config
    handlers["find_api"] = sec_find_api
    handlers["find_route"] = sec_find_route
    handlers["submit_security_report"] = submit_security_report_handler
    return handlers


def make_arch_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Architecture reviewer: read-only + AST analysis + submit_arch_review."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)

    # tool_enhance.md productionization pass, tool #95 (2026-08-25) — the
    # real fix lives in the shared import_graph_handler(); see that
    # function's own module docstring.
    def ar_import_graph(inp: dict[str, Any]) -> str:
        return import_graph_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #97 (2026-08-25) — the
    # real fix lives in the shared circular_dep_detect_handler(); see
    # that function's own module docstring.
    def ar_circular_dep(inp: dict[str, Any]) -> str:
        return circular_dep_detect_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #94 (2026-08-25) — the
    # real fix lives in the shared dead_code_detect_handler(); see that
    # function's own module docstring.
    def ar_dead_code(inp: dict[str, Any]) -> str:
        return dead_code_detect_handler(root, repo_path, inp)

    # T2-B5 (2026-09-22, GRIDIRON_PARTIAL #396) — see
    # app/tools/filesystem/scan_code_hygiene.py's own module docstring.
    def ar_scan_code_hygiene(inp: dict[str, Any]) -> str:
        return scan_code_hygiene_handler(root, repo_path, inp)

    # T2-B9 (2026-09-24, GRIDIRON_PARTIAL #149) — see
    # app/tools/filesystem/scan_reliability.py's own module docstring.
    def ar_scan_reliability(inp: dict[str, Any]) -> str:
        return scan_reliability_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix lives in the shared parse_ast_handler(); see that
    # function's own module docstring.
    def ar_parse_ast(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation read the wrong field — `file`
    # instead of the schema's own `path` — so every real call silently
    # ignored the requested path and grepped the entire repo instead)
    # lives in the shared list_functions_handler() itself; see that
    # function's own module docstring.
    def ar_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix (this implementation read the wrong field — `file`
    # instead of the schema's own `path`) lives in the shared
    # list_classes_handler() itself; see that function's own module
    # docstring.
    def ar_list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #93 (2026-08-25) — the
    # real fix lives in the shared call_graph_handler(); see that
    # function's own module docstring.
    def ar_call_graph(inp: dict[str, Any]) -> str:
        return call_graph_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #181 (2026-09-15) —
    # was write-only dead-code state: `arch_result` was updated but
    # NEVER read anywhere (confirmed via full-codebase grep) — the
    # real result-capture mechanism lives entirely in
    # base_graph.py's generic submit_* handling, which reads the tool
    # call's own arguments directly, independent of this handler.
    # Now delegates to the shared, stateless handler.
    handlers["import_graph"] = ar_import_graph
    handlers["circular_dep_detect"] = ar_circular_dep
    handlers["dead_code_detect"] = ar_dead_code
    handlers["scan_code_hygiene"] = ar_scan_code_hygiene
    handlers["scan_reliability"] = ar_scan_reliability
    handlers["parse_ast"] = ar_parse_ast
    handlers["list_functions"] = ar_list_functions
    handlers["list_classes"] = ar_list_classes
    handlers["call_graph"] = ar_call_graph
    handlers["submit_arch_review"] = submit_arch_review_handler
    return handlers


def make_sql_agent_handlers(repo_path: str) -> dict[str, Any]:
    """SQL agent: read-only + SQL execution + schema inspection + write migrations."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)

    def sq_run_sql(inp: dict[str, Any]) -> str:
        # Delegates to the shared run_sql_handler: real psycopg2 (this used to be
        # `psql <postgresql+asyncpg://...> -c`, which psql reads as a database
        # NAME, so it could never connect) and READ-ONLY by construction — a
        # statement that can modify data is refused (WRITE_BLOCKED); this
        # headless agent run has no human to approve it. The role file's
        # "blocked from DROP/DELETE" used to be enforced by the prompt alone.
        return run_sql_handler(
            str(getattr(get_settings(), "database_url", "") or ""), inp
        )

    # tool_enhance.md productionization pass, tool #96 (2026-08-25) — the
    # real fix lives in the shared inspect_schema_handler(); see that
    # function's own module docstring.
    def sq_inspect_schema(inp: dict[str, Any]) -> str:
        is_db_url = str(getattr(get_settings(), "database_url", "") or "")
        return inspect_schema_handler(is_db_url, inp)

    # tool_enhance.md productionization pass, tool #91 (2026-08-24) — the
    # real fix lives in the shared find_sql_handler(); see that
    # function's own module docstring.
    def sq_find_sql(inp: dict[str, Any]) -> str:
        return find_sql_handler(root, inp)

    # tool_enhance.md productionization pass, tool #98 (2026-08-25) — the
    # real fix lives in the shared explain_query_handler(); see that
    # function's own module docstring.
    def sq_explain_query(inp: dict[str, Any]) -> str:
        eq_db_url = str(getattr(get_settings(), "database_url", "") or "")
        return explain_query_handler(eq_db_url, inp)

    handlers["run_sql"] = sq_run_sql
    handlers["inspect_schema"] = sq_inspect_schema
    handlers["find_sql"] = sq_find_sql
    handlers["explain_query"] = sq_explain_query
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["submit_sql_report"] = submit_sql_report_handler
    return handlers


def make_docker_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Docker agent: read-only + docker CLI inspection + limited docker actions + write_file."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)

    # tool_enhance.md productionization pass, tool #109 (2026-08-26) — the
    # real fix (this implementation completely IGNORED the `all` field
    # — proved live, hiding real stopped/failed containers even when
    # explicitly requested — plus had no try/except around the
    # subprocess call) lives in the shared docker_ps_handler(); see
    # that function's own module docstring.
    def dk_docker_ps(inp: dict[str, Any]) -> str:
        return docker_ps_handler(inp)

    # tool_enhance.md productionization pass, tool #108 (2026-08-25) — the
    # real fix (flag-collision on `container` + uncaught ValueError on a
    # non-numeric `lines`) lives in the shared docker_logs_handler();
    # see that function's own module docstring.
    def dk_docker_logs(inp: dict[str, Any]) -> str:
        return docker_logs_handler(inp)

    def dk_docker_exec(inp: dict[str, Any]) -> str:
        de_container = str(inp["container"])
        de_cmd = str(inp["command"])
        if any(
            d in de_cmd
            for d in ["rm ", "kill", "stop", "restart", "drop", "delete", "truncate"]
        ):
            return f"[POLICY DENIED] Docker exec not allowed: {de_cmd!r}"
        de_risk = _docker_container_risk_reason(de_container)
        if de_risk:
            return f"[POLICY DENIED] {de_risk}"
        r = subprocess.run(
            ["docker", "exec", de_container] + de_cmd.split(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (r.stdout + r.stderr)[:4000] or "(no output)"

    def dk_docker_compose(inp: dict[str, Any]) -> str:
        dc_action = str(inp.get("action", "ps"))
        dc_allowed = {"ps", "logs", "config", "images"}
        if dc_action not in dc_allowed:
            return f"[POLICY DENIED] Only allowed: {sorted(dc_allowed)}. Got: {dc_action!r}"
        r = subprocess.run(
            ["docker", "compose", dc_action],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (r.stdout + r.stderr)[:6000] or "(no output)"

    def dk_docker_build(inp: dict[str, Any]) -> str:
        db_tag = str(inp.get("tag", "app:dev"))
        db_file = str(inp.get("dockerfile", "Dockerfile"))
        db_ctx = str(inp.get("context", "."))
        db_error = validate_docker_build_inputs(db_ctx, db_file, repo_path)
        if db_error:
            return f"[POLICY DENIED] {db_error}"
        r = subprocess.run(
            ["docker", "build", "-t", db_tag, "-f", db_file, db_ctx],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        out = (r.stdout + r.stderr)[:8000]
        return f"Build {'succeeded' if r.returncode == 0 else 'FAILED'}:\n{out}"

    def dk_docker_restart(inp: dict[str, Any]) -> str:
        dr_container = str(inp["container"])
        r = subprocess.run(
            ["docker", "restart", dr_container],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (r.stdout + r.stderr).strip() or f"Restarted {dr_container}"

    # tool_enhance.md productionization pass, tool #106 (2026-08-25) — the
    # real fix (flag-collision on `container` + uncaught ValueError on a
    # non-numeric `lines`) lives in the shared
    # gather_deployment_diagnostics(); see that function's own module
    # docstring. _llm_diagnose_deployment_failure() itself is unchanged
    # and still called here directly — no bug found in the diagnosis
    # step itself, only in how the evidence was gathered.
    def dk_diagnose_deployment_failure(inp: dict[str, Any]) -> str:
        context = gather_deployment_diagnostics(inp)
        if context.startswith("[ERROR]") or context.startswith("[POLICY DENIED]"):
            return context
        diagnosis = _llm_diagnose_deployment_failure(context)
        return f"{context}\n\n=== Diagnosis ===\n{diagnosis}"

    handlers["docker_ps"] = dk_docker_ps
    handlers["docker_logs"] = dk_docker_logs
    handlers["docker_exec"] = dk_docker_exec
    handlers["docker_compose"] = dk_docker_compose
    handlers["diagnose_deployment_failure"] = dk_diagnose_deployment_failure
    handlers["docker_build"] = dk_docker_build
    handlers["docker_restart"] = dk_docker_restart
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["submit_docker_report"] = submit_docker_report_handler
    return handlers


def make_cicd_agent_handlers(repo_path: str) -> dict[str, Any]:
    """CI/CD agent: read-only + limited bash (git/grep only) + file writes + submit."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)

    _CICD_ALLOWED = (
        "git log",
        "git diff",
        "git status",
        "git show",
        "cat ",
        "grep ",
        "echo ",
        "ls ",
    )

    def ci_bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _CICD_ALLOWED)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("cicd", 30)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            repo_path,
            timeout=timeout,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("cicd"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        return (stdout + stderr)[:4000] or "(no output)"

    # tool_enhance.md productionization pass, tool #183 (2026-09-15) —
    # was write-only dead-code state: `cicd_result` was updated but
    # NEVER read anywhere (confirmed via full-codebase grep) — the
    # real result-capture mechanism lives entirely in
    # base_graph.py's generic submit_* handling, which reads the tool
    # call's own arguments directly, independent of this handler.
    # Now delegates to the shared, stateless handler.
    handlers["bash"] = ci_bash
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["submit_cicd_report"] = submit_cicd_report_handler
    return handlers


def make_refactor_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Refactor agent: read-only + AST + write + rename + limited bash (test/lint only)."""
    from app.repo_tools import ast_engine as _ast

    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)

    _RF_ALLOWED = ("python -m pytest", "mypy", "ruff", "black", "isort")

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation read the wrong field — `file`
    # instead of the schema's own `path`) lives in the shared
    # list_functions_handler() itself; see that function's own module
    # docstring.
    def rf_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix lives in the shared list_classes_handler(); see that
    # function's own module docstring.
    def rf_list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #111 (2026-08-26) — the
    # real fix lives in the shared find_function_body_handler(); see
    # that function's own module docstring.
    def rf_find_function_body(inp: dict[str, Any]) -> str:
        return find_function_body_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix lives in the shared parse_ast_handler(); see that
    # function's own module docstring.
    def rf_parse_ast(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #93 (2026-08-25) — the
    # real fix lives in the shared call_graph_handler(); see that
    # function's own module docstring.
    def rf_call_graph(inp: dict[str, Any]) -> str:
        return call_graph_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #95 (2026-08-25) — the
    # real fix lives in the shared import_graph_handler(); see that
    # function's own module docstring.
    def rf_import_graph(inp: dict[str, Any]) -> str:
        return import_graph_handler(root, repo_path, inp)

    def rf_rename_symbol(inp: dict[str, Any]) -> str:
        directory = str(inp.get("directory", ""))
        rsym_error = validate_rename_symbol_directory(directory, repo_path)
        if rsym_error:
            return f"[POLICY DENIED] {rsym_error}"
        return _ast.rename_symbol(
            inp["old_name"],
            inp["new_name"],
            str(root / directory) if directory else str(root),
            str(inp.get("file_pattern", "*.py")),
            confirm_large_batch=bool(inp.get("confirm_large_batch", False)),
        )

    # T2-B8 (2026-09-24, GRIDIRON_PARTIAL #257) — the real fix lives in
    # the shared batch_edit_handler(); see that function's own module
    # docstring.
    def rf_batch_edit(inp: dict[str, Any]) -> str:
        return batch_edit_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/replace_function.py as
    # replace_function_handler — tool_enhance.md productionization pass,
    # tool #24 (2026-08-18). Real bug found+fixed here: this handler
    # previously read inp["new_body"], but REPLACE_FUNCTION_TOOL's own
    # schema (what refactor_agent actually advertises to its LLM)
    # documents the field as "new_code" — every real, schema-conformant
    # call raised an uncaught KeyError. Its own regex also only matched
    # top-level functions, never class methods, unlike the shared
    # handler below (already proven correct via chat_agent.py/
    # make_chat_handlers). See replace_function.py's own docstring for
    # the full real proof.
    def rf_replace_function(inp: dict[str, Any]) -> str:
        return replace_function_handler(root, repo_path, inp)

    def rf_bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _RF_ALLOWED)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("refactor", 60)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            repo_path,
            timeout=timeout,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("refactor"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        return (stdout + stderr)[:6000] or "(no output)"

    handlers["list_functions"] = rf_list_functions
    handlers["list_classes"] = rf_list_classes
    handlers["find_function_body"] = rf_find_function_body
    handlers["parse_ast"] = rf_parse_ast
    handlers["call_graph"] = rf_call_graph
    handlers["import_graph"] = rf_import_graph
    handlers["rename_symbol"] = rf_rename_symbol
    handlers["batch_edit"] = rf_batch_edit
    handlers["replace_function"] = rf_replace_function
    handlers["edit_file"] = _make_edit_file_handler(root)
    handlers["write_file"] = _make_write_file_handler(root)
    handlers["git_diff"] = _make_git_diff_handler(repo_path)
    handlers["bash"] = rf_bash
    handlers["submit_refactor_report"] = submit_refactor_report_handler
    return handlers


def make_readme_agent_handlers(repo_path: str) -> dict[str, Any]:
    """README agent: read-only + AST + write_file (*.md only) + submit_docs."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    docs_result: dict[str, Any] = {}

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix lives in the shared parse_ast_handler(); see that
    # function's own module docstring.
    def rm_parse_ast(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation read the wrong field — `file`
    # instead of the schema's own `path`) lives in the shared
    # list_functions_handler() itself; see that function's own module
    # docstring.
    def rm_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix lives in the shared list_classes_handler(); see that
    # function's own module docstring.
    def rm_list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    def rm_write_file(inp: dict[str, Any]) -> str:
        from app.policy.engine import check_path_in_worktree

        rel = str(inp["path"])
        if not (rel.endswith(".md") or rel.startswith("docs/")):
            return (
                f"[POLICY DENIED] README agent may only write .md files. Got: {rel!r}"
            )
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {result.reason}"
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(inp["content"], encoding="utf-8")
        return f"Written {rel}"

    handlers["parse_ast"] = rm_parse_ast
    handlers["list_functions"] = rm_list_functions
    handlers["list_classes"] = rm_list_classes
    handlers["write_file"] = rm_write_file
    # tool_enhance.md productionization pass, tool #85 (2026-08-24) —
    # the shared, already-correct logic now lives in
    # make_submit_docs_handler(); see that function's own module
    # docstring.
    handlers["submit_docs"] = make_submit_docs_handler(docs_result)
    handlers["_docs_result"] = docs_result
    return handlers


def make_api_docs_agent_handlers(repo_path: str) -> dict[str, Any]:
    """API Docs agent: read-only + route/API finders + AST + write_file (*.md) + submit_docs."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)
    docs_result: dict[str, Any] = {}

    # tool_enhance.md productionization pass, tool #90 (2026-08-24) — the
    # real fix lives in the shared find_route_handler(); see that
    # function's own module docstring.
    def ad_find_route(inp: dict[str, Any]) -> str:
        return find_route_handler(root, inp)

    # tool_enhance.md productionization pass, tool #89 (2026-08-24) — the
    # real fix lives in the shared find_api_handler(); see that
    # function's own module docstring.
    def ad_find_api(inp: dict[str, Any]) -> str:
        return find_api_handler(root, inp)

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix lives in the shared parse_ast_handler(); see that
    # function's own module docstring.
    def ad_parse_ast(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation read the wrong field — `file`
    # instead of the schema's own `path`) lives in the shared
    # list_functions_handler() itself; see that function's own module
    # docstring.
    def ad_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    def ad_write_file(inp: dict[str, Any]) -> str:
        from app.policy.engine import check_path_in_worktree

        rel = str(inp["path"])
        if not (rel.endswith(".md") or rel.startswith("docs/")):
            return (
                f"[POLICY DENIED] API docs agent may only write .md files. Got: {rel!r}"
            )
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {result.reason}"
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(inp["content"], encoding="utf-8")
        return f"Written {rel}"

    handlers["find_route"] = ad_find_route
    handlers["find_api"] = ad_find_api
    handlers["parse_ast"] = ad_parse_ast
    handlers["list_functions"] = ad_list_functions
    handlers["write_file"] = ad_write_file
    # tool_enhance.md productionization pass, tool #85 (2026-08-24) —
    # the shared, already-correct logic now lives in
    # make_submit_docs_handler(); see that function's own module
    # docstring.
    handlers["submit_docs"] = make_submit_docs_handler(docs_result)
    handlers["_docs_result"] = docs_result
    return handlers


def make_dependency_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Dependency agent: read-only + bash (pip/npm audit only) + edit requirements + submit."""
    handlers = make_read_only_handlers(repo_path)
    root = Path(repo_path)

    _DEP_ALLOWED = (
        "pip index versions",
        "pip show",
        "pip list",
        "npm audit",
        "npm outdated",
        "npm list",
        "safety check",
        "pip-audit",
    )
    _DEP_EDITABLE = {
        "requirements.txt",
        "requirements-dev.txt",
        "package.json",
        "pyproject.toml",
    }

    def dep_bash(inp: dict[str, Any]) -> str:
        cmd = inp["command"]
        policy = check_allowlisted_command(cmd, _DEP_ALLOWED)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("dependency_agent", 60)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd,
            repo_path,
            timeout=timeout,
            image=settings.bash_sandbox_toolchain_image,
            network=settings.bash_tool_sandbox_network.get("dependency_agent"),
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        return (stdout + stderr)[:6000] or "(no output)"

    def dep_edit_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if Path(rel).name not in _DEP_EDITABLE:
            return f"[POLICY DENIED] Dependency agent may only edit requirements/package files. Got: {rel!r}"
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Cannot write to protected path: {rel}"
        target = root / rel
        if not target.exists():
            return f"[ERROR] File not found: {rel}"
        text = target.read_text(encoding="utf-8")
        old_s, new_s = inp["old_string"], inp["new_string"]
        count = text.count(old_s)
        if count == 0:
            return f"[ERROR] old_string not found in {rel}"
        if count > 1:
            return f"[ERROR] old_string appears {count} times — must be unique"
        target.write_text(text.replace(old_s, new_s, 1), encoding="utf-8")
        return f"Edited {rel}"

    # T2-B5 (2026-09-22, GRIDIRON_PARTIAL #462 "Abandoned/unmaintained
    # libraries (structured, enforced)") — before this, `abandoned=true`/
    # `last_release_days_ago` were populated purely on the model following
    # roles/dependency_agent.md's own prompt instruction to call
    # check_last_release first, with zero code-level check backing it (the
    # exact "trust the model's claim" gap this codebase's own
    # enforce_in_result convention exists to close elsewhere — but
    # enforce_in_result only overrides a single flat result field with a
    # single verification boolean, and this needs a PER-PACKAGE check
    # against a per-run set of what check_last_release was actually called
    # for, which the graph's generic VerificationConfig has no primitive
    # for). Real per-run state, closure-scoped like dep_bash/dep_edit_file
    # above: dep_check_last_release records every package a real (non-
    # [ERROR]) check actually ran for; dep_submit_report then corrects
    # (never trusts) any `abandoned=true` claim for a package that was
    # never really checked this run — same "the graph's own recorded truth
    # wins over the model's claim" philosophy, just applied per-list-item
    # instead of per-flag.
    _checked_packages: set[str] = set()

    def dep_check_last_release(inp: dict[str, Any]) -> str:
        result = check_last_release_handler(inp)
        if not result.startswith("[ERROR]"):
            pkg = str(inp.get("package", "")).strip().lower()
            if pkg:
                _checked_packages.add(pkg)
        return result

    def dep_submit_report(inp: dict[str, Any]) -> str:
        corrected = 0
        for dep in inp.get("dependencies", []):
            if not isinstance(dep, dict):
                continue
            if (
                dep.get("abandoned")
                and str(dep.get("name", "")).strip().lower() not in _checked_packages
            ):
                dep["abandoned"] = False
                dep.pop("last_release_days_ago", None)
                corrected += 1
        if corrected:
            import logging

            logging.getLogger(__name__).warning(
                "dependency_agent: corrected %d 'abandoned' claim(s) with no "
                "real check_last_release call this run",
                corrected,
            )
        return submit_dependency_report_handler(inp)

    handlers["bash"] = dep_bash
    handlers["check_last_release"] = dep_check_last_release
    handlers["check_dependency_conflicts"] = check_dependency_conflicts_handler
    handlers["edit_file"] = dep_edit_file
    handlers["submit_dependency_report"] = dep_submit_report
    return handlers


# make_monitoring_agent_handlers moved to app/agents/monitoring_handlers.py
# — T2-B6 (2026-09-24, GRIDIRON_PARTIAL #162), same extraction pattern as
# tool_security.py/conflict_resolution.py. Re-exported below for backward
# compatibility with existing callers (app.agents.monitoring_agent, tests).


# ===========================================================================
# Day 3 — Browser, Memory, Planning, External Integration tool specs + Agent
# tool lists + Factories
# ===========================================================================

# moved to app/tools/browser/browser_tools.py as BROWSER_OPEN_TOOL/
# BROWSER_NAVIGATE_TOOL/BROWSER_SCREENSHOT_TOOL/BROWSER_READ_DOM_TOOL/
# BROWSER_CLICK_TOOL/BROWSER_TYPE_TOOL/BROWSER_CLOSE_TOOL —
# tool_enhance.md productionization pass, tools #28-#31 + #123-#125
# (2026-08-18).

# --- Day 3B: Memory tool specs ---

# moved to app/tools/agents/memory_read.py as MEMORY_READ_TOOL /
# memory_read_handler() — tool_enhance.md productionization
# pass, tool #167 (2026-09-15).

# moved to app/tools/agents/memory_write.py as MEMORY_WRITE_TOOL — tool_enhance.md productionization pass, tool #51 (2026-08-20).

# moved to app/tools/agents/decision_log_append.py as
# DECISION_LOG_APPEND_TOOL / decision_log_append_handler() —
# tool_enhance.md productionization pass, tool #133 (2026-09-11).

# moved to app/tools/database/task_history_query.py as
# TASK_HISTORY_QUERY_TOOL / task_history_query() — tool_enhance.md
# productionization pass, tool #118 (2026-08-26).

# moved to app/tools/agents/known_issues_read.py as
# KNOWN_ISSUES_READ_TOOL / known_issues_read_handler() —
# tool_enhance.md productionization pass, tool #160 (2026-09-15).

# moved to app/tools/agents/known_issues_write.py as
# KNOWN_ISSUES_WRITE_TOOL / known_issues_write_handler() —
# tool_enhance.md productionization pass, tool #161 (2026-09-15).

# --- Day 3C: Planning + docs tool specs ---

# tool_enhance.md productionization pass, tool #110 (2026-08-26) —
# moved to app/tools/execution/estimate_complexity.py as
# ESTIMATE_COMPLEXITY_TOOL (imported above, aliased to
# _ESTIMATE_COMPLEXITY_TOOL after the import block). Real finding:
# advertised in CHAT_TOOLS but never dispatched by chat_agent.py —
# same class as tools #4/#6/#22/#25/#33/#44/#45/#46/#48/#100/#103.
# No LLM-controlled input reaches disk or a subprocess (pure word/file
# counting), so no injection/worktree surface exists. See that
# module's own docstring for the full account.

# moved to app/tools/filesystem/summarize_folder.py as
# SUMMARIZE_FOLDER_TOOL / summarize_folder_handler() —
# tool_enhance.md productionization pass, tool #202 (2026-09-16). The
# comment block immediately above this one belongs to the neighboring
# _ESTIMATE_COMPLEXITY_TOOL (tool #110) — NOT this tool; its claim of
# "no injection/worktree surface" does not apply here (see this new
# module's own docstring for a real, proven worktree-escape finding).
_SUMMARIZE_FOLDER_TOOL: dict[str, Any] = SUMMARIZE_FOLDER_TOOL

# moved to app/tools/filesystem/generate_api_docs_text.py as
# GENERATE_API_DOCS_TEXT_TOOL / generate_api_docs_text_handler() —
# tool_enhance.md productionization pass, tool #144 (2026-09-14).

# moved to app/tools/database/mermaid_from_schema.py as
# MERMAID_FROM_SCHEMA_TOOL / mermaid_from_schema_handler() —
# tool_enhance.md productionization pass, tool #168 (2026-09-15).

# --- Day 2 Gap: Smart search tools ---

# moved to app/tools/filesystem/find_queue.py as FIND_QUEUE_TOOL /
# find_queue_handler() — tool_enhance.md productionization pass, tool
# #139 (2026-09-11).

# moved to app/tools/filesystem/find_worker.py as FIND_WORKER_TOOL /
# find_worker_handler() — tool_enhance.md productionization pass, tool
# #142 (2026-09-11).

# --- Day 2 Gap: Advanced editing tools ---

# moved to app/tools/filesystem/insert_before.py as INSERT_BEFORE_TOOL — tool_enhance.md productionization pass, tool #48 (2026-08-20).

# moved to app/tools/filesystem/insert_after.py as INSERT_AFTER_TOOL — tool_enhance.md productionization pass, tool #46 (2026-08-19).

# moved to app/tools/filesystem/delete_block.py as DELETE_BLOCK_TOOL —
# tool_enhance.md productionization pass, tool #33 (2026-08-18).

# --- Day 2 Gap: Documentation generation tools ---

# tool_enhance.md productionization pass, tool #100 (2026-08-25) —
# moved to app/tools/git/generate_changelog.py as
# GENERATE_CHANGELOG_TOOL (imported above, aliased to
# _GENERATE_CHANGELOG_TOOL after the import block). Real, severe
# finding: a silent arbitrary-file-write via `--output=<path>` flag-
# collision on to_ref (same class as tool #80's git_show), PLUS an
# LLM-controlled `repo_path` override disclosing commit history from
# ANY host git repo, PLUS "advertised but never dispatched" (no
# chat_agent.py dispatch existed). See that module's own docstring for
# the full account.

# moved to app/tools/filesystem/summarize_repo.py as
# SUMMARIZE_REPO_TOOL / summarize_repo_handler() —
# tool_enhance.md productionization pass, tool #203 (2026-09-16).
# Closes the deferred item logged in tool #100's own docstring: the
# identical unvalidated repo_path-override pattern reaching os.walk()
# directly. See that new module's own docstring.
_SUMMARIZE_REPO_TOOL: dict[str, Any] = SUMMARIZE_REPO_TOOL

# tool_enhance.md productionization pass, tool #112 (2026-08-26) —
# moved to app/tools/git/generate_release_notes.py as
# GENERATE_RELEASE_NOTES_TOOL (imported above, aliased to
# _GENERATE_RELEASE_NOTES_TOOL after the import block). Same real,
# severe finding class as tool #100's generate_changelog: a silent
# arbitrary-file-write via git log's --output=<path> flag on
# `from_ref`, an LLM-controlled `repo_path` override, and "advertised
# but never dispatched" (no chat_agent.py dispatch existed). See that
# module's own docstring for the full account.

# --- Day 2 Gap: File type tools ---

# moved to app/tools/filesystem/read_pdf.py as READ_PDF_TOOL /
# read_pdf_handler() — tool_enhance.md productionization pass,
# tool #177 (2026-09-15).
_READ_PDF_TOOL: dict[str, Any] = READ_PDF_TOOL

# moved to app/tools/filesystem/read_image.py as READ_IMAGE_TOOL /
# read_image_handler() — tool_enhance.md productionization pass, tool
# #174 (2026-09-15).
_READ_IMAGE_TOOL: dict[str, Any] = READ_IMAGE_TOOL

# --- Day 2 Gap: GitHub PR tool ---
# _GITHUB_CREATE_PR_TOOL moved to app/tools/git/pull_request.py as
# GITHUB_CREATE_PR_TOOL — tool_enhance.md productionization pass, tool #6
# (2026-08-16).

# --- Day 3G: External integration tool specs (GitHub CLI / Linear / Slack
# webhooks — plain REST/CLI wrappers, NOT the Model Context Protocol. See
# AUDIT_Q_BATCH17 §71 gap-closure: this label previously said "MCP", which
# was a naming mismatch — real MCP-protocol-building help now lives in the
# dedicated mcp_developer_agent.py instead. ---

# moved to app/tools/git/github_create_issue.py as GITHUB_CREATE_ISSUE_TOOL — tool_enhance.md productionization pass, tool #45 (2026-08-19).

# moved to app/tools/git/github_list_prs.py as
# GITHUB_LIST_PRS_TOOL / github_list_prs_handler() —
# tool_enhance.md productionization pass, tool #153 (2026-09-14).

# moved to app/tools/git/github_comment.py as GITHUB_COMMENT_TOOL — tool_enhance.md productionization pass, tool #44 (2026-08-19).

# moved to app/tools/integrations/linear_create_issue.py as LINEAR_CREATE_ISSUE_TOOL — tool_enhance.md productionization pass, tool #50 (2026-08-20).

# moved to app/tools/integrations/slack_send_message.py as
# SLACK_SEND_MESSAGE_TOOL / send_slack_message — tool_enhance.md
# productionization pass, tool #63 (2026-08-22). Same "advertised but
# never dispatched" bug class as tool #50's linear_create_issue —
# chat_agent.py had zero dispatch branch despite this being advertised
# via CHAT_TOOLS.
_SLACK_SEND_MESSAGE_TOOL: dict[str, Any] = SLACK_SEND_MESSAGE_TOOL

# --- Day 3 Agent submit tool specs ---

# moved to app/tools/agents/submit_perf_review.py as
# SUBMIT_PERF_REVIEW_TOOL / submit_perf_review_handler() —
# tool_enhance.md productionization pass, tool #190 (2026-09-16).
_SUBMIT_PERF_REVIEW_TOOL: dict[str, Any] = SUBMIT_PERF_REVIEW_TOOL

# moved to app/tools/agents/submit_style_review.py as
# SUBMIT_STYLE_REVIEW_TOOL / submit_style_review_handler() —
# tool_enhance.md productionization pass, tool #200 (2026-09-16).
_SUBMIT_STYLE_REVIEW_TOOL: dict[str, Any] = SUBMIT_STYLE_REVIEW_TOOL

# moved to app/tools/agents/submit_sprint_plan.py as
# SUBMIT_SPRINT_PLAN_TOOL / submit_sprint_plan_handler() —
# tool_enhance.md productionization pass, tool #198 (2026-09-16).
_SUBMIT_SPRINT_PLAN_TOOL: dict[str, Any] = SUBMIT_SPRINT_PLAN_TOOL

# moved to app/tools/agents/submit_ba_result.py as
# SUBMIT_BA_RESULT_TOOL / submit_ba_result_handler() —
# tool_enhance.md productionization pass, tool #182 (2026-09-15).
_SUBMIT_BA_RESULT_TOOL: dict[str, Any] = SUBMIT_BA_RESULT_TOOL

# moved to app/tools/agents/submit_migration.py as
# SUBMIT_MIGRATION_TOOL / submit_migration_handler() —
# tool_enhance.md productionization pass, tool #188 (2026-09-16).
_SUBMIT_MIGRATION_TOOL: dict[str, Any] = SUBMIT_MIGRATION_TOOL

# moved to app/tools/agents/submit_schema.py as
# SUBMIT_SCHEMA_TOOL / submit_schema_handler() —
# tool_enhance.md productionization pass, tool #196 (2026-09-16).
_SUBMIT_SCHEMA_TOOL: dict[str, Any] = SUBMIT_SCHEMA_TOOL

# moved to app/tools/agents/submit_ai_result.py as
# SUBMIT_AI_RESULT_TOOL / submit_ai_result_handler() —
# tool_enhance.md productionization pass, tool #180 (2026-09-15).
_SUBMIT_AI_RESULT_TOOL: dict[str, Any] = SUBMIT_AI_RESULT_TOOL

# moved to app/tools/agents/submit_cleanup.py as
# SUBMIT_CLEANUP_TOOL / submit_cleanup_handler() —
# tool_enhance.md productionization pass, tool #184 (2026-09-16).
_SUBMIT_CLEANUP_TOOL: dict[str, Any] = SUBMIT_CLEANUP_TOOL

# moved to app/tools/agents/submit_tech_debt.py as
# SUBMIT_TECH_DEBT_TOOL / submit_tech_debt_handler() —
# tool_enhance.md productionization pass, tool #201 (2026-09-16).
_SUBMIT_TECH_DEBT_TOOL: dict[str, Any] = SUBMIT_TECH_DEBT_TOOL

# --- Day 3 agent-specific bash specs (restricted allowlists) ---

_MIGRATION_BASH_TOOL_SPEC: dict[str, Any] = {
    "name": "bash",
    "description": "Run migration-related commands: alembic upgrade/downgrade, alembic revision, git diff.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_AI_ENGINEER_BASH_TOOL_SPEC: dict[str, Any] = {
    "name": "bash",
    "description": "Run AI/ML commands: python script execution, pip install packages, model evaluation scripts.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

_CLEANUP_BASH_TOOL_SPEC: dict[str, Any] = {
    "name": "bash",
    "description": "Run cleanup commands: find dead code, check imports, ruff/isort checks.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}

# --- Day 3 Agent Tool Lists ---

PERFORMANCE_REVIEWER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _FIND_SQL_TOOL,
    _RUN_SQL_TOOL,
    _EXPLAIN_QUERY_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _SUBMIT_PERF_REVIEW_TOOL,
]

STYLE_REVIEWER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_LINTER_TOOL,
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _SUBMIT_STYLE_REVIEW_TOOL,
]

SPRINT_PLANNER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _ESTIMATE_COMPLEXITY_TOOL,
    _SUBMIT_SPRINT_PLAN_TOOL,
]

BUSINESS_ANALYST_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _SUBMIT_BA_RESULT_TOOL,
]

MIGRATION_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _MIGRATION_BASH_TOOL_SPEC,
    _SUBMIT_MIGRATION_TOOL,
]

SCHEMA_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    _WRITE_FILE_TOOL_SPEC,
    _SUBMIT_SCHEMA_TOOL,
]

AI_ENGINEER_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _RUN_PYTHON_SNIPPET_TOOL,
    _AI_ENGINEER_BASH_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _FETCH_URL_TOOL,
    _SUBMIT_AI_RESULT_TOOL,
]

CLEANUP_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _DEAD_CODE_DETECT_TOOL,
    _SCAN_CODE_HYGIENE_TOOL,
    _ORGANIZE_IMPORTS_TOOL,
    _DELETE_FILE_TOOL,
    _EDIT_FILE_TOOL_SPEC,
    _CLEANUP_BASH_TOOL_SPEC,
    _SUBMIT_CLEANUP_TOOL,
]

TECH_DEBT_AGENT_TOOLS: list[dict[str, Any]] = READ_ONLY_TOOLS + [
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _RUN_LINTER_TOOL,
    _COVERAGE_REPORT_TOOL,
    _SUBMIT_TECH_DEBT_TOOL,
]

# --- Day 3 Handler Factories ---


def make_performance_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Performance Reviewer agent."""
    from app.config import get_settings as _gs

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)

    # tool_enhance.md productionization pass, tool #91 (2026-08-24) — the
    # real fix (empty `keyword` searched only "SELECT", not the full
    # SQL keyword set the schema promises — a real functionality bug,
    # proved live with a real INSERT statement invisible to this
    # implementation) lives in the shared find_sql_handler() itself;
    # see that function's own module docstring.
    def pr_find_sql(inp: dict[str, Any]) -> str:
        return find_sql_handler(root, inp)

    def pr_run_sql(inp: dict[str, Any]) -> str:
        # Delegates to the shared run_sql_handler: real psycopg2 (this used to be
        # `psql <postgresql+asyncpg://...> -c`, which psql reads as a database
        # NAME, so it could never connect) and READ-ONLY by construction — a
        # statement that can modify data is refused (WRITE_BLOCKED); this
        # headless agent run has no human to approve it. The role file's
        # "blocked from DROP/DELETE" used to be enforced by the prompt alone.
        return run_sql_handler(
            str(getattr(get_settings(), "database_url", "") or ""), inp
        )

    # tool_enhance.md productionization pass, tool #98 (2026-08-25) — the
    # real fix lives in the shared explain_query_handler(); see that
    # function's own module docstring.
    def pr_explain_query(inp: dict[str, Any]) -> str:
        db_url = str(getattr(_gs(), "database_url", "") or "")
        return explain_query_handler(db_url, inp)

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation on `path` — a relative `../` traversal genuinely
    # escaped the repo, since the accidental `relative_to(root)`
    # safety net only blocked ABSOLUTE outside-repo paths, not
    # traversal) lives in the shared list_functions_handler() itself;
    # see that function's own module docstring.
    def pr_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    handlers["find_sql"] = pr_find_sql
    handlers["run_sql"] = pr_run_sql
    handlers["explain_query"] = pr_explain_query
    handlers["list_functions"] = pr_list_functions
    handlers["submit_perf_review"] = submit_perf_review_handler
    return handlers


def make_style_reviewer_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Style Reviewer agent."""
    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)

    # tool_enhance.md productionization pass, tool #101 (2026-08-25) — the
    # real fix (this implementation was completely broken for every real
    # call — an invalid ruff --output-format value — AND ignored the
    # tool/fix fields entirely) lives in the shared run_linter_handler();
    # see that function's own module docstring.
    def sr_run_linter(inp: dict[str, Any]) -> str:
        return run_linter_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation on `path`, same relative-traversal-escape finding as
    # pr_list_functions) lives in the shared list_functions_handler()
    # itself; see that function's own module docstring.
    def sr_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation on `path` — a relative `../` traversal genuinely
    # escaped the repo) lives in the shared list_classes_handler()
    # itself; see that function's own module docstring.
    def sr_list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    def sr_find_todos(inp: dict[str, Any]) -> str:
        results: list[str] = []
        for fp in root.rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if "TODO" in line or "FIXME" in line or "HACK" in line:
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:80]) or "(no TODOs found)"

    handlers["run_linter"] = sr_run_linter
    handlers["list_functions"] = sr_list_functions
    handlers["list_classes"] = sr_list_classes
    handlers["find_todos"] = sr_find_todos
    handlers["submit_style_review"] = submit_style_review_handler
    return handlers


def make_sprint_planner_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Sprint Planner agent."""
    handlers = make_read_only_handlers(repo_path)

    # tool_enhance.md productionization pass, tool #110 (2026-08-26) — the
    # real fix (this tool was advertised in CHAT_TOOLS but chat_agent.py
    # had ZERO dispatch — same class as tools #4/#6/#22/#25/#33/#44/
    # #45/#46/#48/#100/#103) lives in the shared
    # estimate_complexity_handler(); see that function's own module
    # docstring.
    def sp_estimate_complexity(inp: dict[str, Any]) -> str:
        return estimate_complexity_handler(inp)

    handlers["estimate_complexity"] = sp_estimate_complexity
    handlers["submit_sprint_plan"] = submit_sprint_plan_handler
    return handlers


def make_business_analyst_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Business Analyst agent."""
    handlers = make_read_only_handlers(repo_path)

    # tool_enhance.md productionization pass, tool #182 (2026-09-15) —
    # was write-only dead-code state: `ba_result` was updated but
    # NEVER read anywhere (confirmed via full-codebase grep) — the
    # real result-capture mechanism lives entirely in
    # base_graph.py's generic submit_* handling, which reads the tool
    # call's own arguments directly, independent of this handler.
    # Now delegates to the shared, stateless handler.
    handlers["submit_ba_result"] = submit_ba_result_handler
    return handlers


def make_migration_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Migration Agent."""
    from app.config import get_settings as _gs

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)

    _MIGRATION_BASH_ALLOWLIST = (
        "alembic upgrade",
        "alembic downgrade",
        "alembic revision",
        "alembic history",
        "alembic current",
        "alembic heads",
        "git diff",
        "git status",
        "git log",
    )

    def mg_run_sql(inp: dict[str, Any]) -> str:
        # Delegates to the shared run_sql_handler: real psycopg2 (this used to be
        # `psql <postgresql+asyncpg://...> -c`, which psql reads as a database
        # NAME, so it could never connect) and READ-ONLY by construction — a
        # statement that can modify data is refused (WRITE_BLOCKED); this
        # headless agent run has no human to approve it. The role file's
        # "blocked from DROP/DELETE" used to be enforced by the prompt alone.
        return run_sql_handler(
            str(getattr(get_settings(), "database_url", "") or ""), inp
        )

    # tool_enhance.md productionization pass, tool #96 (2026-08-25) — the
    # real fix lives in the shared inspect_schema_handler(); see that
    # function's own module docstring.
    def mg_inspect_schema(inp: dict[str, Any]) -> str:
        db_url = str(getattr(_gs(), "database_url", "") or "")
        return inspect_schema_handler(db_url, inp)

    def mg_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        # Migration agent may only write to migrations/ or backend/migrations/
        if not (
            rel.startswith("migrations/")
            or rel.startswith("backend/migrations/")
            or rel.endswith(".py")
        ):
            return (
                f"[POLICY DENIED] Migration agent may only write migration files: {rel}"
            )
        content = str(inp["content"])
        try:
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Written: {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    def mg_bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, _MIGRATION_BASH_ALLOWLIST)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        settings = get_settings()
        timeout = settings.bash_tool_timeout_seconds.get("migration", 60)
        try:
            # alembic (migrations/env.py) reads DATABASE_URL from the
            # environment — a sandboxed container does NOT inherit the
            # host's env automatically (app.policy.sandbox.run_sandboxed's
            # own docstring), so it must be forwarded explicitly. Reaching
            # the real Postgres instance at all requires network="host"
            # (bash_tool_sandbox_network's own default for this variant) —
            # verified empirically: docker-compose.yml deliberately binds
            # Postgres to 127.0.0.1 only, unreachable from a bridge-network
            # container even via host.docker.internal routing.
            stdout, stderr, _returncode, timed_out = _run_bash_command(
                cmd,
                str(root),
                timeout=timeout,
                extra_env={"DATABASE_URL": settings.database_url},
                image=settings.bash_sandbox_toolchain_image,
                network=settings.bash_tool_sandbox_network.get("migration"),
            )
            if timed_out:
                return f"[ERROR] Command timed out after {timeout}s"
            return (stdout + stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["run_sql"] = mg_run_sql
    handlers["inspect_schema"] = mg_inspect_schema
    handlers["write_file"] = mg_write_file
    handlers["bash"] = mg_bash
    handlers["submit_migration"] = submit_migration_handler
    return handlers


def make_schema_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Schema Agent."""
    from app.config import get_settings as _gs

    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)

    def sa_run_sql(inp: dict[str, Any]) -> str:
        # Delegates to the shared run_sql_handler: real psycopg2 (this used to be
        # `psql <postgresql+asyncpg://...> -c`, which psql reads as a database
        # NAME, so it could never connect) and READ-ONLY by construction — a
        # statement that can modify data is refused (WRITE_BLOCKED); this
        # headless agent run has no human to approve it. The role file's
        # "blocked from DROP/DELETE" used to be enforced by the prompt alone.
        return run_sql_handler(
            str(getattr(get_settings(), "database_url", "") or ""), inp
        )

    # tool_enhance.md productionization pass, tool #96 (2026-08-25) — the
    # real fix lives in the shared inspect_schema_handler(); see that
    # function's own module docstring.
    def sa_inspect_schema(inp: dict[str, Any]) -> str:
        db_url = str(getattr(_gs(), "database_url", "") or "")
        return inspect_schema_handler(db_url, inp)

    def sa_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        content = str(inp["content"])
        try:
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Written: {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["run_sql"] = sa_run_sql
    handlers["inspect_schema"] = sa_inspect_schema
    handlers["write_file"] = sa_write_file
    handlers["submit_schema"] = submit_schema_handler
    return handlers


def make_ai_engineer_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for AI/ML Engineer agent."""
    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)

    # Blocker 6 (audit_v1.md 4.5/4.8): bare "python "/"python3 "/"pip install "
    # prefixes are inherently unrestrictable (any script path/package name
    # satisfies the prefix match; pip install is a supply-chain RCE vector
    # via install-time hooks). Dropped. "python -m "/"python3 -m " restrict
    # execution to installed modules, which is materially narrower, and are
    # kept — same as the rest of this allowlist, they now also run inside
    # the Docker sandbox (see ae_bash below), not directly on the host.
    _AI_BASH_ALLOWLIST = (
        "pip show ",
        "pip list",
        "pytest ",
        "python -m ",
        "python3 -m ",
        "echo ",
        "cat ",
        "ls ",
    )

    def ae_run_python_snippet(inp: dict[str, Any]) -> str:
        import shlex as _shlex

        code = str(inp["code"])
        cmd = f"python -c {_shlex.quote(code)}"
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd, str(root), timeout=30
        )
        if timed_out:
            return "[ERROR] Command timed out after 30s"
        return (stdout + stderr).strip() or "(no output)"

    def ae_bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, _AI_BASH_ALLOWLIST)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        timeout = get_settings().bash_tool_timeout_seconds.get("ai_engineer", 120)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd, str(root), timeout=timeout
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        return (stdout + stderr).strip() or "(no output)"

    def ae_write_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        content = str(inp["content"])
        try:
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Written: {rel}"
        except Exception as e:
            return f"[ERROR] {e}"

    # tool_enhance.md productionization pass, tool #86 (2026-08-24) — this
    # implementation previously ignored its own advertised
    # timeout/summarize schema fields entirely (hardcoded 10s,
    # urllib.request, no summarize support) — a real functionality-
    # parity gap. Now delegates to the shared fetch_url_handler(); see
    # that function's own module docstring.
    def ae_fetch_url(inp: dict[str, Any]) -> str:
        return fetch_url_handler(inp)

    # tool_enhance.md productionization pass, tool #180 (2026-09-15) —
    # was write-only dead-code state: `ai_result` was updated but
    # NEVER read anywhere (confirmed via full-codebase grep) — the
    # real result-capture mechanism lives entirely in
    # base_graph.py's generic submit_* handling, which reads the tool
    # call's own arguments directly, independent of this handler.
    # Now delegates to the shared, stateless handler.
    handlers["run_python_snippet"] = ae_run_python_snippet
    handlers["bash"] = ae_bash
    handlers["write_file"] = ae_write_file
    handlers["fetch_url"] = ae_fetch_url
    handlers["submit_ai_result"] = submit_ai_result_handler
    return handlers


def make_cleanup_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Cleanup Agent."""
    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)

    _CLEANUP_BASH_ALLOWLIST = (
        "python -m ruff",
        "python -m isort",
        "python -m black",
        "find ",
        "grep ",
        "ls ",
        "cat ",
        "echo ",
        "python -m mypy",
    )

    # tool_enhance.md productionization pass, tool #94 (2026-08-25) — the
    # real fix lives in the shared dead_code_detect_handler(); see that
    # function's own module docstring.
    def cu_dead_code_detect(inp: dict[str, Any]) -> str:
        return dead_code_detect_handler(root, repo_path, inp)

    # T2-B5 (2026-09-22, GRIDIRON_PARTIAL #396) — see
    # app/tools/filesystem/scan_code_hygiene.py's own module docstring.
    def cu_scan_code_hygiene(inp: dict[str, Any]) -> str:
        return scan_code_hygiene_handler(root, repo_path, inp)

    def cu_find_todos(inp: dict[str, Any]) -> str:
        results: list[str] = []
        for fp in root.rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if any(t in line for t in ("TODO", "FIXME", "HACK", "XXX")):
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:80]) or "(none found)"

    # tool_enhance.md productionization pass, tool #115 (2026-08-26) —
    # was `isort --diff` (preview-only, diverging from the schema's own
    # promise of an actually-applied `ruff`-based fix). Now delegates
    # to the shared, already-worktree-validated handler.
    def cu_organize_imports(inp: dict[str, Any]) -> str:
        return organize_imports_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/delete_file.py as delete_file_handler
    # — tool_enhance.md productionization pass, tool #17 (2026-08-17).
    def cu_delete_file(inp: dict[str, Any]) -> str:
        return delete_file_handler(root, repo_path, inp)

    def cu_edit_file(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        old_s = inp["old_string"]
        new_s = inp["new_string"]
        fp = root / rel
        if not fp.exists():
            return f"[ERROR] File not found: {rel}"
        text = fp.read_text(encoding="utf-8")
        count = text.count(old_s)
        if count == 0:
            return "[ERROR] old_string not found"
        if count > 1:
            return f"[ERROR] old_string appears {count} times — must be unique"
        fp.write_text(text.replace(old_s, new_s, 1), encoding="utf-8")
        return f"Edited: {rel}"

    def cu_bash(inp: dict[str, Any]) -> str:
        cmd = str(inp["command"])
        policy = check_allowlisted_command(cmd, _CLEANUP_BASH_ALLOWLIST)
        if not policy.allowed:
            return f"[POLICY DENIED] {policy.reason}"
        # Blocker 5 (audit_v1.md 4.5): bare "find " in this allowlist,
        # combined with unsandboxed subprocess.run(shell=True), reproduced
        # the exact `find /workspace -mindepth 1 -delete` case
        # app.policy.sandbox's own docstring cites as the proof case for
        # Docker sandboxing. Route through the same Docker-sandboxed
        # primitive every other bash-shaped tool uses instead of running
        # directly on the host.
        timeout = get_settings().bash_tool_timeout_seconds.get("cleanup", 60)
        stdout, stderr, _returncode, timed_out = _run_bash_command(
            cmd, str(root), timeout=timeout
        )
        if timed_out:
            return f"[ERROR] Command timed out after {timeout}s"
        return (stdout + stderr).strip() or "(no output)"

    handlers["dead_code_detect"] = cu_dead_code_detect
    handlers["scan_code_hygiene"] = cu_scan_code_hygiene
    handlers["find_todos"] = cu_find_todos
    handlers["organize_imports"] = cu_organize_imports
    handlers["delete_file"] = cu_delete_file
    handlers["edit_file"] = cu_edit_file
    handlers["bash"] = cu_bash
    handlers["submit_cleanup"] = submit_cleanup_handler
    return handlers


def make_tech_debt_agent_handlers(repo_path: str) -> dict[str, Any]:
    """Handler factory for Technical Debt Agent."""
    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation on `path`, same relative-traversal-escape finding as
    # pr_/sr_list_functions) lives in the shared
    # list_functions_handler() itself; see that function's own module
    # docstring.
    def td_list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation on `path`, same relative-traversal-escape finding as
    # sr_list_classes) lives in the shared list_classes_handler()
    # itself; see that function's own module docstring.
    def td_list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    def td_find_todos(inp: dict[str, Any]) -> str:
        results: list[str] = []
        for fp in root.rglob("*.py"):
            try:
                for i, line in enumerate(
                    fp.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if any(t in line for t in ("TODO", "FIXME", "HACK", "XXX")):
                        results.append(f"{fp.relative_to(root)}:{i}: {line.strip()}")
            except Exception:
                continue
        return "\n".join(results[:80]) or "(none found)"

    # tool_enhance.md productionization pass, tool #101 (2026-08-25) — the
    # real fix lives in the shared run_linter_handler(); see that
    # function's own module docstring.
    def td_run_linter(inp: dict[str, Any]) -> str:
        return run_linter_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #104 (2026-08-25) — the
    # real fix (this implementation didn't even attempt coverage
    # measurement — it ran `pytest --collect-only`, silently returning a
    # bare test list instead of coverage data, and ignored path/source/
    # min_coverage entirely) lives in the shared
    # coverage_report_handler(); see that function's own module
    # docstring.
    def td_coverage_report(inp: dict[str, Any]) -> str:
        return coverage_report_handler(root, repo_path, inp)

    handlers["list_functions"] = td_list_functions
    handlers["list_classes"] = td_list_classes
    handlers["find_todos"] = td_find_todos
    handlers["run_linter"] = td_run_linter
    handlers["coverage_report"] = td_coverage_report
    handlers["submit_tech_debt"] = submit_tech_debt_handler
    return handlers


# ===========================================================================
# Batch 15 — 34 new tools reaching the 190-tool vision
# ===========================================================================

# -- Git extras --
# moved to app/tools/git/tag.py as GIT_TAG_TOOL —
# tool_enhance.md productionization pass, tool #22 (2026-08-17).
# moved to app/tools/git/log_file.py as GIT_LOG_FILE_TOOL /
# git_log_file_handler() — tool_enhance.md productionization
# pass, tool #150 (2026-09-14).
# moved to app/tools/filesystem/semver_bump.py as SEMVER_BUMP_TOOL —
# tool_enhance.md productionization pass, tool #25 (2026-08-18).
# moved to app/tools/git/stash_list.py as GIT_STASH_LIST_TOOL /
# git_stash_list_handler() — tool_enhance.md productionization
# pass, tool #151 (2026-09-14).

# -- Process / System --
# moved to app/tools/execution/list_processes.py as
# LIST_PROCESSES_TOOL / list_processes_handler() —
# tool_enhance.md productionization pass, tool #165 (2026-09-15).
# moved to app/tools/execution/list_open_ports.py as
# LIST_OPEN_PORTS_TOOL / list_open_ports_handler() —
# tool_enhance.md productionization pass, tool #164 (2026-09-15).
# moved to app/tools/execution/wait_for_port.py as
# WAIT_FOR_PORT_TOOL / wait_for_port_handler() — tool_enhance.md
# productionization pass, tool #207 (2026-09-16).
_WAIT_FOR_PORT_TOOL: dict[str, Any] = WAIT_FOR_PORT_TOOL
# moved to app/tools/execution/check_url_status.py as
# CHECK_URL_STATUS_TOOL / check_url_status_handler() — tool_enhance.md
# productionization pass, tool #126 (2026-08-26).
# moved to app/tools/execution/cpu_profile.py as CPU_PROFILE_TOOL /
# cpu_profile_handler() — tool_enhance.md productionization pass, tool
# #130 (2026-08-26).

# -- File ops --
# moved to app/tools/filesystem/zip_files.py as
# ZIP_FILES_TOOL / zip_files_handler() — tool_enhance.md
# productionization pass, tool #209 (2026-09-16).
_ZIP_FILES_TOOL: dict[str, Any] = ZIP_FILES_TOOL
# moved to app/tools/filesystem/unzip_files.py as
# UNZIP_FILES_TOOL / unzip_files_handler() — tool_enhance.md
# productionization pass, tool #206 (2026-09-16).
_UNZIP_FILES_TOOL: dict[str, Any] = UNZIP_FILES_TOOL
# moved to app/tools/filesystem/move_file.py as MOVE_FILE_TOOL — tool_enhance.md productionization pass, tool #52 (2026-08-20).
# moved to app/tools/filesystem/hash_file.py as HASH_FILE_TOOL /
# hash_file_handler() — tool_enhance.md productionization pass,
# tool #154 (2026-09-14).
# moved to app/tools/filesystem/count_lines.py as COUNT_LINES_TOOL /
# count_lines_handler() — tool_enhance.md productionization pass, tool
# #129 (2026-08-26).

# -- Environment --
# moved to app/tools/execution/read_env_var.py as
# READ_ENV_VAR_TOOL / read_env_var_handler() — tool_enhance.md
# productionization pass, tool #173 (2026-09-15).
_READ_ENV_VAR_TOOL: dict[str, Any] = READ_ENV_VAR_TOOL
# moved to app/tools/execution/list_env_vars.py as
# LIST_ENV_VARS_TOOL / list_env_vars_handler() — tool_enhance.md
# productionization pass, tool #163 (2026-09-15).
# moved to app/tools/filesystem/env_diff.py as ENV_DIFF_TOOL /
# env_diff_handler() — tool_enhance.md productionization pass, tool
# #135 (2026-09-11).

# -- Data format tools --
# moved to app/tools/filesystem/json_query.py as JSON_QUERY_TOOL /
# json_query_handler() — tool_enhance.md productionization pass,
# tool #158 (2026-09-14).
# moved to app/tools/filesystem/yaml_validate.py as
# YAML_VALIDATE_TOOL / yaml_validate_handler() — tool_enhance.md
# productionization pass, tool #120 (2026-08-26).

# moved to app/tools/filesystem/json_validate.py as
# JSON_VALIDATE_TOOL / json_validate_handler() — tool_enhance.md
# productionization pass, tool #159 (2026-09-15).
# moved to app/tools/filesystem/csv_preview.py as CSV_PREVIEW_TOOL /
# csv_preview_handler() — tool_enhance.md productionization pass, tool
# #132 (2026-09-11).
# AUDIT_Q_BATCH09 §16/§79/§80 gap-closure — real, working handlers for file
# types/inspection capabilities that had zero support before, each following
# the exact pattern of the existing PDF/image/CSV/YAML tools above: stdlib or
# already-pinned dependencies only, single self-contained handler, registered
# alongside the tools it extends.
# moved to app/tools/filesystem/xml_validate.py as
# XML_VALIDATE_TOOL / xml_validate_handler() — tool_enhance.md
# productionization pass, tool #208 (2026-09-16).
_XML_VALIDATE_TOOL: dict[str, Any] = XML_VALIDATE_TOOL
# moved to app/tools/filesystem/read_notebook.py as
# READ_NOTEBOOK_TOOL / read_notebook_handler() —
# tool_enhance.md productionization pass, tool #175 (2026-09-15).
_READ_NOTEBOOK_TOOL: dict[str, Any] = READ_NOTEBOOK_TOOL
# moved to app/tools/filesystem/parse_dockerfile.py as
# PARSE_DOCKERFILE_TOOL / parse_dockerfile_handler() —
# tool_enhance.md productionization pass, tool #171 (2026-09-15).
_PARSE_DOCKERFILE_TOOL: dict[str, Any] = PARSE_DOCKERFILE_TOOL
# moved to app/tools/filesystem/parse_docker_compose.py as
# PARSE_DOCKER_COMPOSE_TOOL / parse_docker_compose_handler() —
# tool_enhance.md productionization pass, tool #170 (2026-09-15).
_PARSE_DOCKER_COMPOSE_TOOL: dict[str, Any] = PARSE_DOCKER_COMPOSE_TOOL
# moved to app/tools/integrations/github_inspect_repo.py as
# GITHUB_INSPECT_REPO_TOOL / github_inspect_repo_handler() —
# tool_enhance.md productionization pass, tool #152 (2026-09-14).
# moved to app/tools/filesystem/openapi_inspect.py as
# OPENAPI_INSPECT_TOOL / openapi_inspect_handler() —
# tool_enhance.md productionization pass, tool #169 (2026-09-15).

# -- Code / Docs tools --
# moved to app/tools/filesystem/generate_diagram.py as
# GENERATE_DIAGRAM_TOOL / generate_diagram_handler() —
# tool_enhance.md productionization pass, tool #146 (2026-09-14).
_SUMMARIZE_OUTPUT_TOOL: dict[str, Any] = SUMMARIZE_OUTPUT_TOOL
# moved to app/tools/filesystem/export_markdown.py as
# EXPORT_MARKDOWN_TOOL / export_markdown_handler() — tool_enhance.md
# productionization pass, tool #137 (2026-09-11).
# moved to app/tools/execution/find_unused_imports.py as
# FIND_UNUSED_IMPORTS_TOOL / find_unused_imports_handler() —
# tool_enhance.md productionization pass, tool #141 (2026-09-11).
# moved to app/tools/execution/deps_outdated.py as DEPS_OUTDATED_TOOL
# / deps_outdated_handler() — tool_enhance.md productionization pass,
# tool #134 (2026-09-11).
# tool_enhance.md productionization pass, tool #103 (2026-08-25) —
# moved to app/tools/execution/check_license_compliance.py as
# CHECK_LICENSE_COMPLIANCE_TOOL (imported above, aliased to
# _CHECK_LICENSE_COMPLIANCE_TOOL after the import block). Real
# finding: advertised in CHAT_TOOLS but never dispatched by
# chat_agent.py — same class as tools #4/#6/#22/#25/#33/#44/#45/#46/
# #48/#100. No LLM-controlled input reaches this tool (empty schema),
# so no worktree/injection surface exists. See that module's own
# docstring for the full account.
# moved to app/tools/execution/loc_stats.py as LOC_STATS_TOOL /
# loc_stats_handler() — tool_enhance.md productionization pass,
# tool #166 (2026-09-15).

# -- Package management --
# moved to app/tools/execution/npm_install.py as NPM_INSTALL_TOOL — tool_enhance.md productionization pass, tool #53 (2026-08-20).
# moved to app/tools/execution/npm_run.py as NPM_RUN_TOOL — tool_enhance.md productionization pass, tool #54 (2026-08-20).
# moved to app/tools/execution/pip_install.py as PIP_INSTALL_TOOL — tool_enhance.md productionization pass, tool #55 (2026-08-20).
# moved to app/tools/execution/pip_list.py as PIP_LIST_TOOL /
# pip_list_handler() — tool_enhance.md productionization pass,
# tool #172 (2026-09-15).
_PIP_LIST_TOOL: dict[str, Any] = PIP_LIST_TOOL

# -- Utilities --
# moved to app/tools/filesystem/create_directory.py as
# CREATE_DIRECTORY_TOOL / create_directory_handler() — tool_enhance.md
# productionization pass, tool #131 (2026-08-26).
# moved to app/tools/integrations/http_request.py as
# HTTP_REQUEST_TOOL / http_request_handler() — tool_enhance.md
# productionization pass, tool #155 (2026-09-14).
# moved to app/tools/filesystem/base64_encode.py as
# BASE64_ENCODE_TOOL / base64_encode_handler() — tool_enhance.md
# productionization pass, tool #122 (2026-08-26).
# moved to app/tools/filesystem/template_render.py as
# TEMPLATE_RENDER_TOOL / template_render_handler() —
# tool_enhance.md productionization pass, tool #204 (2026-09-16).
_TEMPLATE_RENDER_TOOL: dict[str, Any] = TEMPLATE_RENDER_TOOL

# AUDIT_Q_BATCH07 §13 gap-closure (2026-08-11) — "Present options (multi-
# choice): NO — not found | Confirmation payload is binary approve/deny
# only." / "Recommend choices: PARTIAL | free-text ... no structured
# recommendation field." _confirm()'s binary approve/deny interrupt() stays
# untouched (every existing dangerous-operation gate keeps working exactly
# as before) — this is a genuinely different decision shape: not "should I
# do this Y/N" but "which of these N valid paths should I take", so it's a
# new tool (ChatAgent._confirm_with_options(), same real interrupt()/
# Command(resume=...) pause primitive as _confirm(), see chat_agent.py) not
# a change to the existing one.
_ASK_HUMAN_TO_CHOOSE_TOOL: dict[str, Any] = {
    "name": "ask_human_to_choose",
    "description": (
        "Use when there are multiple genuinely valid ways to proceed and a human should "
        "pick one — not for a plain yes/no decision (dangerous actions like delete/git push "
        "already pause for approval automatically; don't call this for those). Pauses this "
        "turn until the human selects one option; their choice is returned as this tool's "
        "result so you can act on it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The specific decision the human needs to make.",
            },
            "options": {
                "type": "array",
                "description": "2-5 distinct choices, each with a stable id.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["id", "label"],
                },
                "minItems": 2,
            },
            "recommended_option": {
                "type": "string",
                "description": "id of the option you'd recommend, if any — the human sees this but still decides.",
            },
        },
        "required": ["question", "options"],
    },
}

# #500 (2026-09-25, "Conversational 'do that again'") — the only recall
# mechanism before this was memory_hook_node's implicit semantic-similarity
# retrieval; there was no deterministic way to resolve "do that again"/
# "repeat the last task"/"repeat the previous fix" to a specific real task.
# Two tools, deliberately split: find_repeatable_tasks never itself decides
# which task the user means — it returns real candidates plus an explicit,
# code-generated instruction to use ask_human_to_choose whenever more than
# one plausible candidate exists, so "never silently guess" is enforced by
# the tool's own output, not left to prompt-level judgment alone.
# repeat_previous_task then REQUIRES a specific task_id (no "just repeat
# the most recent one" shortcut exists) — by construction, the model must
# have already resolved which task it means, whether unambiguously from
# find_repeatable_tasks's own result or via a real ask_human_to_choose
# pause, before this tool can be called at all.
_FIND_REPEATABLE_TASKS_TOOL: dict[str, Any] = {
    "name": "find_repeatable_tasks",
    "description": (
        "Look up real past tasks in this repo that the user might mean by 'do that again', "
        "'repeat the last task', or 'repeat the previous fix'. Call this FIRST whenever the "
        "user references a past task without giving its exact id — never guess a task_id "
        "without calling this. Optionally filter by a keyword from what the user said."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "A word or short phrase from the user's own reference (e.g. "
                "'login bug') to filter candidates by title/description. Omit for 'the last "
                "task' with no other description.",
            },
            "limit": {
                "type": "integer",
                "description": "Max candidates to return (default 5).",
            },
        },
        "required": [],
    },
}

_REPEAT_PREVIOUS_TASK_TOOL: dict[str, Any] = {
    "name": "repeat_previous_task",
    "description": (
        "Clone a specific past task (by its real task_id, from find_repeatable_tasks or a "
        "task_id the user stated explicitly) into a new task and dispatch it through the "
        "real planning pipeline — the same 'repeat' a human clicking Repeat in the UI "
        "triggers. Use description_override for 'repeat it but change X' requests; omit it "
        "for an exact repeat."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "The real id of the task to repeat — must come from "
                "find_repeatable_tasks's own results or an id the user stated explicitly, "
                "never guessed.",
            },
            "description_override": {
                "type": "string",
                "description": "Only for 'repeat it but ...' requests — the full, updated "
                "task description. Omitted means an exact, unmodified repeat.",
            },
            "title_override": {"type": "string"},
        },
        "required": ["task_id"],
    },
}

CHAT_TOOLS = READ_ONLY_TOOLS + [
    _EDIT_FILE_TOOL_SPEC,
    _WRITE_FILE_TOOL_SPEC,
    _GIT_DIFF_TOOL_SPEC,
    _CHAT_BASH_TOOL,
    _APPEND_FILE_TOOL,
    _RENAME_FILE_TOOL,
    _COPY_FILE_TOOL,
    _DELETE_FILE_TOOL,
    _GIT_COMMIT_TOOL,
    _GIT_BRANCH_TOOL,
    _GIT_CHECKOUT_TOOL,
    _GIT_STASH_TOOL,
    _GIT_PULL_TOOL,
    _GIT_FETCH_TOOL,
    _GIT_RESTORE_TOOL,
    _GIT_PUSH_TOOL,
    _CREATE_BRANCH_TOOL,
    _RUN_TESTS_TOOL,
    _RUN_LINTER_TOOL,
    _SUBMIT_RESULT_TOOL,
    # Batch 1 — File/Editing extras
    _FIND_FILE_TOOL,
    _FORMAT_FILE_TOOL,
    _ORGANIZE_IMPORTS_TOOL,
    _INSERT_AT_LINE_TOOL,
    _REPLACE_FUNCTION_TOOL,
    _DELETE_LINES_TOOL,
    _APPLY_PATCH_TOOL_DEF,
    _COMPARE_FILES_TOOL,
    _SYNC_FILES_TOOL,
    # Batch 2 — Terminal extras
    _RUN_BACKGROUND_TOOL_DEF,
    _KILL_PROCESS_TOOL,
    _LIST_BACKGROUND_PROCESSES_TOOL,
    _RUN_PARALLEL_COMMANDS_TOOL,
    _RUN_PYTHON_SNIPPET_TOOL,
    _RUN_MAKE_TOOL,
    _FETCH_URL_TOOL,
    # Batch 3 — Git extras
    _GIT_MERGE_TOOL,
    _PARSE_MERGE_CONFLICTS_TOOL,
    _EXPLAIN_MERGE_CONFLICT_TOOL,
    _RESOLVE_MERGE_CONFLICT_TOOL,
    _GIT_RESET_TOOL,
    _GIT_WORKTREE_TOOL,
    _CREATE_PR_TOOL,
    _GENERATE_COMMIT_MSG_TOOL,
    _REVIEW_DIFF_TOOL,
    _INSPECT_GITHUB_REPO_TOOL,
    _INSPECT_OPENAPI_SPEC_TOOL,
    # Batch 4 — Testing extras
    _RUN_SINGLE_TEST_TOOL,
    _COVERAGE_REPORT_TOOL,
    _TYPE_CHECK_TOOL,
    # Batch 5 — Code Intelligence
    _LIST_FUNCTIONS_TOOL,
    _LIST_CLASSES_TOOL,
    _FIND_FUNCTION_BODY_TOOL,
    # Batch 6 — Debug
    _READ_LOGS_TOOL,
    _ANALYZE_ERROR_TOOL,
    # Batch 7 — Database
    _RUN_SQL_TOOL,
    _INSPECT_SCHEMA_TOOL,
    # Batch 8 — Docker
    _DOCKER_PS_TOOL,
    _DOCKER_LOGS_TOOL,
    _DOCKER_EXEC_TOOL,
    _DOCKER_COMPOSE_TOOL,
    _DIAGNOSE_DEPLOYMENT_FAILURE_TOOL,
    # Batch 9 — Security
    _SECRETS_SCAN_TOOL,
    # Batch 10 — AST Engine
    _PARSE_AST_TOOL,
    _IMPORT_GRAPH_TOOL,
    _CALL_GRAPH_TOOL,
    _DEAD_CODE_DETECT_TOOL,
    _CIRCULAR_DEP_DETECT_TOOL,
    _RENAME_SYMBOL_TOOL,
    _BATCH_EDIT_TOOL,
    # Batch 11 — Git extras
    _GIT_REBASE_TOOL,
    _GIT_CHERRY_PICK_TOOL,
    # Batch 12 — Terminal extras
    _READ_OUTPUT_TOOL,
    _RUN_NODE_TOOL,
    _RUN_SCRIPT_TOOL,
    _DOCKER_BUILD_TOOL,
    _DOCKER_RESTART_TOOL,
    # Batch 13 — Smart search
    _FIND_ROUTE_TOOL,
    _FIND_API_TOOL,
    _FIND_SQL_TOOL,
    _FIND_TEST_TOOL,
    _FIND_CONFIG_TOOL,
    # Batch 14 — Monitoring
    _CPU_USAGE_TOOL,
    _MEMORY_USAGE_TOOL,
    _DISK_USAGE_TOOL,
    _HEALTH_CHECK_TOOL,
    _TASK_PROGRESS_TOOL,
    # Batch 15 — Editing extras
    _REPLACE_CLASS_TOOL,
    _UNDO_CHANGES_TOOL,
    _GENERATE_PATCH_TOOL,
    # Batch 16 — DB extras
    _EXPLAIN_QUERY_TOOL,
    _RUN_MIGRATION_TOOL,
    _SEED_DATABASE_TOOL,
    # Day 3A — Browser tools
    _BROWSER_OPEN_TOOL,
    _BROWSER_NAVIGATE_TOOL,
    _BROWSER_SCREENSHOT_TOOL,
    _BROWSER_READ_DOM_TOOL,
    _BROWSER_CLICK_TOOL,
    _BROWSER_TYPE_TOOL,
    _BROWSER_CLOSE_TOOL,
    # Day 3B — Memory tools
    _MEMORY_READ_TOOL,
    _MEMORY_WRITE_TOOL,
    _DECISION_LOG_APPEND_TOOL,
    _TASK_HISTORY_QUERY_TOOL,
    _KNOWN_ISSUES_READ_TOOL,
    _KNOWN_ISSUES_WRITE_TOOL,
    # AUDIT_Q_BATCH15 §74/§113 gap-closure — preference memory
    RECORD_PREFERENCE_TOOL,
    # Day 3C — Planning + docs tools
    _ESTIMATE_COMPLEXITY_TOOL,
    _SUMMARIZE_FOLDER_TOOL,
    _GENERATE_API_DOCS_TEXT_TOOL,
    _MERMAID_FROM_SCHEMA_TOOL,
    # Day 3G — External integrations (GitHub/Linear/Slack — not MCP protocol)
    _GITHUB_CREATE_ISSUE_TOOL,
    _GITHUB_LIST_PRS_TOOL,
    _GITHUB_COMMENT_TOOL,
    _LINEAR_CREATE_ISSUE_TOOL,
    _SLACK_SEND_MESSAGE_TOOL,
    # Day 2 Gap — Smart search
    _FIND_QUEUE_TOOL,
    _FIND_WORKER_TOOL,
    # Day 2 Gap — Advanced editing
    _INSERT_BEFORE_TOOL,
    _INSERT_AFTER_TOOL,
    _DELETE_BLOCK_TOOL,
    # Day 2 Gap — Documentation generation
    _GENERATE_CHANGELOG_TOOL,
    _SUMMARIZE_REPO_TOOL,
    _GENERATE_RELEASE_NOTES_TOOL,
    # Day 2 Gap — File types
    _READ_PDF_TOOL,
    _READ_IMAGE_TOOL,
    # Day 2 Gap — GitHub PR
    _GITHUB_CREATE_PR_TOOL,
    # Batch 15 — 34 new tools reaching the 190-tool vision
    # Git extras
    _GIT_TAG_TOOL,
    _GIT_LOG_FILE_TOOL,
    _SEMVER_BUMP_TOOL,
    _GIT_STASH_LIST_TOOL,
    # Process / System
    _LIST_PROCESSES_TOOL,
    _LIST_OPEN_PORTS_TOOL,
    _WAIT_FOR_PORT_TOOL,
    _CHECK_URL_STATUS_TOOL,
    _CPU_PROFILE_TOOL,
    # File ops
    _ZIP_FILES_TOOL,
    _UNZIP_FILES_TOOL,
    _MOVE_FILE_TOOL,
    _HASH_FILE_TOOL,
    _COUNT_LINES_TOOL,
    # Environment
    _READ_ENV_VAR_TOOL,
    _LIST_ENV_VARS_TOOL,
    _ENV_DIFF_TOOL,
    # Data format
    _JSON_QUERY_TOOL,
    _YAML_VALIDATE_TOOL,
    _JSON_VALIDATE_TOOL,
    _CSV_PREVIEW_TOOL,
    # AUDIT_Q_BATCH09 §16/§79/§80 — file type + inspection gap-closure
    _XML_VALIDATE_TOOL,
    _READ_NOTEBOOK_TOOL,
    _PARSE_DOCKERFILE_TOOL,
    _PARSE_DOCKER_COMPOSE_TOOL,
    _GITHUB_INSPECT_REPO_TOOL,
    _OPENAPI_INSPECT_TOOL,
    # Code / Docs
    _GENERATE_DIAGRAM_TOOL,
    _SUMMARIZE_OUTPUT_TOOL,
    _EXPORT_MARKDOWN_TOOL,
    _FIND_UNUSED_IMPORTS_TOOL,
    _DEPS_OUTDATED_TOOL,
    _CHECK_LICENSE_COMPLIANCE_TOOL,
    _CHECK_TARGET_REPO_LICENSE_COMPLIANCE_TOOL,
    _LOC_STATS_TOOL,
    # Package management
    _NPM_INSTALL_TOOL,
    _NPM_RUN_TOOL,
    _PIP_INSTALL_TOOL,
    _PIP_LIST_TOOL,
    # Utilities
    _CREATE_DIRECTORY_TOOL,
    _HTTP_REQUEST_TOOL,
    _BASE64_ENCODE_TOOL,
    _TEMPLATE_RENDER_TOOL,
    # AUDIT_Q_BATCH07 §13 — Human interaction
    _ASK_HUMAN_TO_CHOOSE_TOOL,
    # #500 — Conversational "do that again"
    _FIND_REPEATABLE_TASKS_TOOL,
    _REPEAT_PREVIOUS_TASK_TOOL,
]


def make_chat_handlers(repo_path: str, session: Any = None) -> dict[str, Any]:
    """
    Full-access handlers for the interactive chat agent.
    session: ChatSession instance — used to request user confirmation for dangerous ops.
    If session is None, dangerous commands are blocked rather than confirmed.
    """
    root = Path(repo_path)
    handlers = make_read_only_handlers(repo_path)
    # Per-session background process registry — isolated so one session cannot
    # kill or read output from a different session's background process.
    _session_bg_procs: dict[int, "subprocess.Popen[str]"] = {}

    # ---- edit_file ----
    # moved to app/tools/filesystem/edit_file.py as edit_file_handler —
    # tool_enhance.md productionization pass, tool #13 (2026-08-17).
    def edit_file(inp: dict[str, Any]) -> str:
        return edit_file_handler(root, repo_path, inp)

    # ---- write_file ----
    # moved to app/tools/filesystem/write_file.py as write_file_handler —
    # tool_enhance.md productionization pass, tool #12 (2026-08-17).
    def write_file(inp: dict[str, Any]) -> str:
        return write_file_handler(root, repo_path, inp)

    # ---- git_diff ----
    # tool_enhance.md productionization pass, tool #84 (2026-08-24) — the
    # real fix (ZERO `--` separator before `file` — a silent
    # arbitrary-file-write via git's own --output=<path> flag, same
    # class as tool #80's git_show) lives in the shared
    # git_diff_handler() itself; see that function's own module
    # docstring.
    def git_diff(inp: dict[str, Any]) -> str:
        return git_diff_handler(root, inp)

    # ---- bash (with confirmation for dangerous commands) ----
    def bash(inp: dict[str, Any]) -> str:
        command = inp["command"]
        # Gap-closure (Audit 05 fix, SEC-05-006): this used to accept an
        # LLM-controlled cwd override (`inp.get("cwd") or repo_path`) with no
        # validation it stayed inside repo_path — widening the escape
        # surface beyond even the `cd &&` chaining issue (SEC-05-005),
        # since the tool call itself could just set cwd directly. Every
        # other bash-capable handler in this file hardcodes its working
        # directory; this one now does too.
        cwd = repo_path

        # Gap-closure (Audit 05 fix, SEC-05-005): rejected before the
        # confirmation flow below — a command trying to leave the sandbox
        # entirely is a different, non-overridable class of problem from a
        # destructive-but-in-scope command a human can knowingly approve.
        boundary_policy = check_command_stays_in_boundary(command, repo_path)
        if not boundary_policy.allowed:
            return f"[POLICY DENIED] {boundary_policy.reason}"

        if _is_dangerous_command(command):
            # Gap-closure (Audit 05 fix, SEC-05-007): a human "approve" click
            # used to be able to run ANY denylisted command, including
            # irreversible/catastrophic ones (rm -rf, dd if=, mkfs, a fork
            # bomb) — no different from an unconfirmed one once approved.
            # These now stay hard-blocked regardless of confirmation.
            from app.policy.engine import is_command_override_eligible

            if not is_command_override_eligible(command):
                return (
                    f"[BLOCKED] This command is irreversible/catastrophic and "
                    f"cannot be run even with confirmation: {command!r}"
                )
            # tool_enhance.md productionization pass, tool #4 (2026-08-16) —
            # real gap found: the session.request_confirmation() plumbing
            # below this used to exist for the case where session IS
            # provided, but `session` is never non-None for any real
            # caller of make_chat_handlers() (grepped every real call
            # site in the repo — none pass one). Unlike git_push/
            # undo_changes/etc. below, "bash" genuinely IS reachable by
            # many real one-shot agents (bug_fix, backend_dev, ...), so
            # this fail-closed behavior is real, live, and correct — a
            # one-shot agent must never autonomously run a flagged-
            # dangerous command with no human present to ask. Simplified
            # to state that plainly instead of dead async plumbing that
            # could never execute.
            return (
                f"[BLOCKED] This command is potentially destructive: {command!r}\n"
                "No interactive confirmation channel is available in this "
                "execution context. Refusing to run."
            )

        try:
            timeout = get_settings().bash_tool_timeout_seconds.get("chat", 120)
            stdout, stderr, returncode, timed_out = _run_bash_command(
                command, cwd, timeout=timeout
            )
            if timed_out:
                return f"[ERROR] Command timed out after {timeout}s"
            output = stdout + (("\n[stderr]\n" + stderr) if stderr else "")
            if returncode != 0:
                output += f"\n[exit code: {returncode}]"
            return output.strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- delete_file ----
    # moved to app/tools/filesystem/delete_file.py as delete_file_handler
    # — tool_enhance.md productionization pass, tool #17 (2026-08-17).
    def delete_file(inp: dict[str, Any]) -> str:
        return delete_file_handler(root, repo_path, inp)

    # git_push moved to app/tools/git/push.py as git_push_handler —
    # tool_enhance.md productionization pass, tool #4 (2026-08-16).

    # ---- create_branch ----
    def create_branch(inp: dict[str, Any]) -> str:
        name = str(inp["name"])
        checkout = inp.get("checkout", True)
        from_branch = str(inp.get("from_branch", ""))
        cb_error = validate_create_branch_inputs(name, from_branch)
        if cb_error:
            return cb_error

        # Create the branch
        create_cmd = ["git", "branch", name]
        if from_branch:
            create_cmd.append(from_branch)

        try:
            result = subprocess.run(
                create_cmd, cwd=repo_path, capture_output=True, text=True
            )
            if result.returncode != 0:
                return f"[ERROR] {result.stderr.strip()}"
        except Exception as e:
            return f"[ERROR] {e}"

        if checkout:
            try:
                result = subprocess.run(
                    ["git", "checkout", name],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    return (
                        f"Branch created but checkout failed: {result.stderr.strip()}"
                    )
            except Exception as e:
                return f"Branch created but checkout failed: {e}"
            # T2-B6 (2026-09-24, GRIDIRON_PARTIAL #361) — same active_branch
            # persistence as this module's own git_checkout handler; the
            # checkout above already confirmed returncode == 0, so `name`
            # is trusted directly rather than re-deriving via rev-parse.
            try:
                from app.db.repository import set_repo_active_branch_by_path_sync

                set_repo_active_branch_by_path_sync(repo_path, name)
            except Exception:
                pass
            return f"Created and switched to branch: {name}"

        return f"Created branch: {name}"

    # ---- append_file ----
    # moved to app/tools/filesystem/append_file.py as append_file_handler
    # — tool_enhance.md productionization pass, tool #26 (2026-08-18).
    def append_file(inp: dict[str, Any]) -> str:
        return append_file_handler(root, repo_path, inp)

    # ---- rename_file ----
    # moved to app/tools/filesystem/rename_file.py — this now delegates to the shared rename_file_handler()
    def rename_file(inp: dict[str, Any]) -> str:
        return rename_file_handler(root, repo_path, inp)

    # ---- copy_file ----
    # tool_enhance.md productionization pass, tool #128 (2026-08-26) —
    # worktree validation was already correct here; the real fix
    # (chat_agent.py's sibling dispatch had no try/except) lives in
    # the shared copy_file_handler(); see that module's own docstring.
    def copy_file(inp: dict[str, Any]) -> str:
        return copy_file_handler(root, repo_path, inp)

    # ---- git_commit ---- (moved to app/tools/git/commit.py — this now delegates to the shared, hardened stage_and_commit())
    def git_commit(inp: dict[str, Any]) -> str:
        message = str(inp["message"])
        files: list[str] = inp.get("files", [])
        return stage_and_commit(repo_path, message, files)

    # ---- git_branch ----
    # tool_enhance.md productionization pass, tool #148 (2026-09-14) —
    # was a flag-collision bug on the `create` action (same class as
    # tools #5/#32): a flag-shaped `name` (e.g. "--list") silently ran
    # a completely different git-branch subcommand with no error,
    # proved live. Now delegates to the shared, validated handler.
    def git_branch(inp: dict[str, Any]) -> str:
        return git_branch_handler(repo_path, inp)

    # ---- git_checkout ----
    def git_checkout(inp: dict[str, Any]) -> str:
        target = str(inp["target"])
        file_path = str(inp.get("file", ""))
        gc_error = validate_git_checkout_inputs(target, file_path)
        if gc_error:
            return gc_error
        cmd = ["git", "checkout", target]
        if file_path:
            cmd = ["git", "checkout", target, "--", file_path]
        try:
            r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
            out = (r.stdout + r.stderr).strip()
            # T2-B6 (2026-09-22, GRIDIRON_PARTIAL #361) — a whole-branch
            # switch (not a single-file restore) genuinely changed which
            # branch this repo is on; read the REAL post-checkout branch via
            # git itself (never trust `target` literally — it can be a tag/
            # remote ref/commit that leaves HEAD detached, where the real
            # value is "HEAD") rather than assuming target==branch.
            if r.returncode == 0 and not file_path:
                try:
                    branch_r = subprocess.run(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    real_branch = branch_r.stdout.strip()
                    if branch_r.returncode == 0 and real_branch:
                        from app.db.repository import (
                            set_repo_active_branch_by_path_sync,
                        )

                        set_repo_active_branch_by_path_sync(repo_path, real_branch)
                except Exception:
                    logger.warning(
                        "git_checkout: best-effort step failed", exc_info=True
                    )  # best-effort — the checkout itself already succeeded
            return out or f"Checked out {target}"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_stash ----
    # moved to app/tools/git/stash.py — this now calls the shared validate_git_stash_action() first
    def git_stash(inp: dict[str, Any]) -> str:
        action = str(inp.get("action", "push"))
        stash_error = validate_git_stash_action(action)
        if stash_error:
            return stash_error
        message = inp.get("message", "")
        cmd = ["git", "stash"]
        if action == "push":
            if message:
                cmd += ["push", "-m", message]
        elif action == "pop":
            cmd.append("pop")
        elif action == "list":
            cmd.append("list")
        elif action == "drop":
            cmd.append("drop")
        try:
            r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
            return (r.stdout + r.stderr).strip() or f"git stash {action} complete"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_pull ---- (moved to app/tools/git/pull.py — this now calls the shared validate_git_pull_inputs() first)
    def git_pull(inp: dict[str, Any]) -> str:
        remote = str(inp.get("remote", "origin"))
        branch = str(inp.get("branch", ""))
        pull_error = validate_git_pull_inputs(remote, branch)
        if pull_error:
            return pull_error
        rebase = bool(inp.get("rebase", False))
        cmd = ["git", "pull"]
        if rebase:
            cmd.append("--rebase")
        cmd.append(remote)
        if branch:
            cmd.append(branch)
        try:
            r = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True, timeout=60
            )
            return (r.stdout + r.stderr).strip() or "Pull complete"
        except subprocess.TimeoutExpired:
            return "[ERROR] git pull timed out after 60s"
        except Exception as e:
            return f"[ERROR] {e}"

    # ---- git_fetch ----
    # tool_enhance.md productionization pass, tool #149 (2026-09-14) —
    # was a flag-collision bug (same class as tools #5/#32/#148): a
    # flag-shaped `remote` (e.g. "--all") silently fetched from every
    # configured remote instead of just the one named, proved live.
    # Now delegates to the shared, validated handler.
    def git_fetch(inp: dict[str, Any]) -> str:
        return git_fetch_handler(repo_path, inp)

    # ---- git_restore ----
    # moved to app/tools/git/restore.py — like undo_changes_h, this has no real,
    # safely-confirmable one-shot caller (grepped: git_restore is in zero
    # agent's allowed_tools), so it's blocked outright instead of silently
    # executing an unconfirmed irreversible discard.
    def git_restore(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        if _is_protected_path(rel, repo_path):
            return f"[POLICY DENIED] Protected path: {rel}"
        return (
            "[BLOCKED] git_restore requires interactive session for safety confirmation"
        )

    # ---- run_tests ----
    # moved to app/tools/execution/run_tests.py as run_tests_handler —
    # tool_enhance.md productionization pass, tool #16 (2026-08-17).
    def run_tests(inp: dict[str, Any]) -> str:
        return run_tests_handler(
            repo_path, inp, activate_snippet=_venv_activate_snippet()
        )

    # ---- run_linter ----
    # tool_enhance.md productionization pass, tool #101 (2026-08-25) — the
    # real fix lives in the shared run_linter_handler(); see that
    # function's own module docstring. Real, severe finding: `path` was
    # protected only by shlex.quote() (shell-safety, not ruff's-own-
    # flag-parser-safety) — path="--fix" bypassed the fix=False default
    # and genuinely rewrote a real file on disk, proved live.
    def run_linter(inp: dict[str, Any]) -> str:
        return run_linter_handler(root, repo_path, inp)

    # =========================================================================
    # BATCH 1 — File / Editing extras
    # =========================================================================

    # tool_enhance.md productionization pass, tool #138 (2026-09-11) —
    # was a worktree-escape filename/directory-structure disclosure
    # oracle via `directory` (`root / ff_dir` never validated). Now
    # delegates to the shared, worktree-validated handler.
    def find_file(inp: dict[str, Any]) -> str:
        return find_file_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #143 (2026-09-11) —
    # was a worktree-escape ARBITRARY FILE WRITE (`root / rel` never
    # validated — formatters mutate their target in place, proved live
    # in an isolated /tmp directory). Now delegates to the shared,
    # list-args, worktree-validated handler.
    def format_file(inp: dict[str, Any]) -> str:
        return format_file_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #115 (2026-08-26) —
    # was a worktree-escape arbitrary-write (`root / rel` never
    # validated, so an absolute `rel` discarded `root` entirely) via
    # `shell=True` (shlex.quote on the target only protects against
    # shell metacharacters, not a path that resolves outside the
    # worktree). Now delegates to the shared, list-args,
    # worktree-validated handler.
    def organize_imports(inp: dict[str, Any]) -> str:
        return organize_imports_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/insert_at_line.py — this now delegates to the shared insert_at_line_handler()
    def insert_at_line(inp: dict[str, Any]) -> str:
        return insert_at_line_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/replace_function.py as
    # replace_function_handler — tool_enhance.md productionization pass,
    # tool #24 (2026-08-18).
    def replace_function(inp: dict[str, Any]) -> str:
        return replace_function_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/delete_lines.py as
    # delete_lines_handler — tool_enhance.md productionization pass,
    # tool #34 (2026-08-18).
    def delete_lines(inp: dict[str, Any]) -> str:
        return delete_lines_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/apply_patch.py as apply_patch_handler
    # — tool_enhance.md productionization pass, tool #27 (2026-08-18).
    def apply_patch(inp: dict[str, Any]) -> str:
        return apply_patch_handler(repo_path, inp)

    # tool_enhance.md productionization pass, tool #127 (2026-08-26) —
    # was a worktree-escape TWO-FILE ARBITRARY READ (`root / path_a`/
    # `root / path_b` never validated) and had an uncaught crash on a
    # non-numeric `context`. Now delegates to the shared,
    # worktree-validated handler.
    def compare_files(inp: dict[str, Any]) -> str:
        return compare_files_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #64 (2026-08-22) — the
    # real fix (chat_agent.py's own dispatch had zero worktree-boundary
    # validation, this implementation already had it) lives in the
    # shared sync_files_handler() itself; see that function's own module
    # docstring.
    def sync_files(inp: dict[str, Any]) -> str:
        return sync_files_handler(root, repo_path, inp)

    # =========================================================================
    # BATCH 2 — Terminal extras
    # =========================================================================

    # tool_enhance.md productionization pass, tool #58 (2026-08-20) — the
    # real fix (Docker sandboxing) lives in process_manager.spawn() itself,
    # already the shared implementation this call delegates to; see that
    # function's own docstring, including a retroactive kill_process
    # (tool #49) fix found along the way. `cwd` is now validated here
    # since it gets bind-mounted read-write into the sandbox.
    def run_background(inp: dict[str, Any]) -> str:
        from app.fleet import process_manager as _pm

        rb_command = str(inp["command"])
        rb_cwd = str(inp.get("cwd") or repo_path)
        rb_policy = check_command(rb_command)
        if not rb_policy.allowed:
            return f"[POLICY DENIED] {rb_policy.reason}"
        rb_cwd_error = validate_run_background_cwd(rb_cwd, repo_path)
        if rb_cwd_error:
            return rb_cwd_error
        rb_wait_for = inp.get("wait_for_pids")
        rb_wait_pids = [int(p) for p in rb_wait_for] if rb_wait_for else None
        return _pm.spawn(
            rb_command, rb_cwd, _session_bg_procs, wait_for_pids=rb_wait_pids
        )

    # tool_enhance.md productionization pass, tool #49 (2026-08-20) — the
    # real fix (an ownership gate) lives in process_manager.kill() itself,
    # already the shared implementation this call delegates to; see that
    # function's own docstring.
    def kill_process(inp: dict[str, Any]) -> str:
        from app.fleet import process_manager as _pm

        kp_pid = int(inp["pid"])
        kp_sig_name = str(inp.get("signal", "TERM"))
        return _pm.kill(kp_pid, kp_sig_name, _session_bg_procs)

    # tool_enhance.md productionization pass, tool #162 (2026-09-15) —
    # no real bug found (empty schema, no LLM-controlled input; both
    # real implementations were already correctly dispatched and
    # already delegated to the same shared format_tracked()); this is
    # modularization only, matching the "no bug, still extracted"
    # precedent from tools #147/#156.
    def list_background_processes_h(inp: dict[str, Any]) -> str:
        return list_background_processes_handler(_session_bg_procs)

    # run_parallel_commands_h removed — tool_enhance.md productionization
    # pass, tool #9 (2026-08-16). Now registered directly against
    # run_parallel_commands_handler (app/tools/execution/parallel.py),
    # which also closes a real cwd-boundary-escape finding (see that
    # module's docstring) shared with the generic bash tool.

    # moved to app/tools/execution/python_snippet.py as
    # run_python_snippet_handler — tool_enhance.md productionization pass,
    # tool #14 (2026-08-17).
    def run_python_snippet(inp: dict[str, Any]) -> str:
        return run_python_snippet_handler(
            repo_path, inp, activate_snippet=_venv_activate_snippet()
        )

    # tool_enhance.md productionization pass, tool #59 (2026-08-22) — the
    # real fix lives in the shared run_make_handler() itself; see that
    # function's own module docstring.
    def run_make(inp: dict[str, Any]) -> str:
        return run_make_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #86 (2026-08-24) — the
    # real fix (an unbounded LLM-controlled timeout, flagged back in
    # tool #14, plus an uncaught ValueError on a non-numeric timeout)
    # lives in the shared fetch_url_handler() itself; see that
    # function's own module docstring.
    def fetch_url(inp: dict[str, Any]) -> str:
        return fetch_url_handler(inp)

    # =========================================================================
    # BATCH 3 — Git extras
    # =========================================================================

    # moved to app/tools/git/merge.py — this now calls the shared validate_git_merge_inputs() first
    def git_merge(inp: dict[str, Any]) -> str:
        gm_branch = str(inp["branch"])
        gm_error = validate_git_merge_inputs(gm_branch)
        if gm_error:
            return gm_error
        gm_no_ff = bool(inp.get("no_ff", False))
        gm_squash = bool(inp.get("squash", False))
        gm_msg = str(inp.get("message", ""))
        gm_cmd = ["git", "merge"]
        if gm_no_ff:
            gm_cmd.append("--no-ff")
        if gm_squash:
            gm_cmd.append("--squash")
        if gm_msg:
            gm_cmd += ["-m", gm_msg]
        gm_cmd.append(gm_branch)
        try:
            r = subprocess.run(
                gm_cmd, cwd=repo_path, capture_output=True, text=True, timeout=30
            )
            output = (r.stdout + r.stderr).strip() or f"Merged {gm_branch}"
            if r.returncode == 0:
                return output
            # Gap-closure Day 51 — repo research
            # (repos/cline/apps/vscode/.../mergeWorktree.ts): detect real
            # conflicted files via `git diff --name-only --diff-filter=U`
            # rather than trusting stdout text alone, so a caller has an
            # exact file list to run parse_merge_conflicts against.
            diff_r = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=15,
            )
            conflicted = [f for f in diff_r.stdout.strip().split("\n") if f]
            if conflicted:
                files_list = ", ".join(conflicted)
                return (
                    f"[CONFLICT] Merge of {gm_branch} has real conflicts in "
                    f"{len(conflicted)} file(s): {files_list}. Use "
                    f"parse_merge_conflicts on each, then resolve_merge_conflict "
                    f"to resolve, then git_commit to finish the merge.\n{output}"
                )
            return f"[ERROR] {output}"
        except Exception as e:
            return f"[ERROR] {e}"

    def parse_merge_conflicts(inp: dict[str, Any]) -> str:
        return parse_merge_conflicts_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #136 (2026-09-11) —
    # worktree validation was already correct here; the real fix
    # (missing try/except around the file read, proved live via a real
    # chmod 000 file) lives in the shared handler; see that module's
    # own docstring.
    def explain_merge_conflict(inp: dict[str, Any]) -> str:
        return explain_merge_conflict_handler(
            root, repo_path, inp, _llm_explain_conflict_hunks
        )

    def resolve_merge_conflict(inp: dict[str, Any]) -> str:
        return resolve_merge_conflict_handler(root, repo_path, inp)

    # git_reset moved to app/tools/git/reset.py as git_reset_handler —
    # tool_enhance.md productionization pass, tool #5 (2026-08-16).

    # moved to app/tools/git/worktree.py — validates inputs and blocks the
    # unconfirmable "add" action (like undo_changes_h/git_restore, this has no
    # real, safely-confirmable one-shot caller for a destructive/impactful action)
    def git_worktree(inp: dict[str, Any]) -> str:
        gw_action = str(inp.get("action", "list"))
        gw_path = str(inp.get("path", ""))
        gw_branch = str(inp.get("branch", ""))
        gw_error = validate_git_worktree_inputs(gw_action, gw_path, gw_branch)
        if gw_error:
            return gw_error
        try:
            if gw_action == "list":
                r = subprocess.run(
                    ["git", "worktree", "list"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return r.stdout or "(no worktrees)"
            elif gw_action == "add":
                return (
                    "[BLOCKED] git_worktree add requires interactive session "
                    "for safety confirmation — it writes a new checkout to "
                    "an arbitrary filesystem path."
                )
            elif gw_action == "remove":
                r = subprocess.run(
                    ["git", "worktree", "remove", "--", gw_path],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                return (r.stdout + r.stderr).strip() or f"Removed worktree at {gw_path}"
            return f"[ERROR] Unknown action: {gw_action}"
        except Exception as e:
            return f"[ERROR] {e}"

    def create_pr(inp: dict[str, Any]) -> str:
        # Moved to app/tools/git/pull_request.py::create_pr_handler —
        # tool_enhance.md productionization pass, tool #2 (2026-08-15).
        # This thin wrapper is what keeps every existing
        # `handlers["create_pr"](...)` call site (all real tests, every
        # agent) working unchanged. See that module's TOOL PATH MIGRATION
        # REPORT for the full consumer audit.
        return create_pr_handler(repo_path, inp)

    # tool_enhance.md productionization pass, tool #145 (2026-09-14) —
    # was a message-accuracy bug (the "no changes" error always said
    # "No staged changes" even in staged_only=False mode, proved live
    # against a real clean repo). Now delegates to the shared, fixed
    # handler.
    def generate_commit_msg(inp: dict[str, Any]) -> str:
        return generate_commit_msg_handler(repo_path, inp, _llm_generate_commit_message)

    # tool_enhance.md productionization pass, tool #179 (2026-09-15) —
    # was a SEVERE flag-collision bug on `base`: git diff's own
    # `--output=<path>` flag, reachable via base, wrote the real diff
    # content to an attacker-chosen file path — proved live. Now
    # rejects flag-shaped `base` outright via the shared arg builder,
    # closing the vulnerability on BOTH real call sites (this one and
    # chat_agent.py's own separate, previously-identically-vulnerable
    # dispatch).
    def review_diff(inp: dict[str, Any]) -> str:
        diff_args = build_review_diff_args(inp)
        if isinstance(diff_args, str):
            return diff_args
        r_stat = subprocess.run(
            ["git"] + diff_args + ["--stat"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        r_diff = subprocess.run(
            ["git"] + diff_args, cwd=repo_path, capture_output=True, text=True
        )
        stat = r_stat.stdout.strip()
        diff = r_diff.stdout[:6000]
        if not stat:
            return "[ERROR] No changes to review for the given scope."
        review = _llm_review_diff(stat, diff)
        if review:
            return f"=== Changed files ===\n{stat}\n\n=== Review ===\n{review}"
        return (
            f"[ERROR] Review generation unavailable — raw diff below.\n\n"
            f"=== Changed files ===\n{stat}\n\n=== Diff ===\n{diff}"
        )

    # =========================================================================
    # BATCH 4 — Testing extras
    # =========================================================================

    # tool_enhance.md productionization pass, tool #62 (2026-08-22) — the
    # real fix (a `file` worktree-escape validator, shared with
    # chat_agent.py's dispatch which also had a real shell-injection bug)
    # lives in the shared run_single_test_handler() itself; see that
    # function's own module docstring.
    def run_single_test(inp: dict[str, Any]) -> str:
        return run_single_test_handler(
            repo_path, inp, activate_snippet=_venv_activate_snippet()
        )

    # tool_enhance.md productionization pass, tool #104 (2026-08-25) — the
    # real fix lives in the shared coverage_report_handler(); see that
    # function's own module docstring. Real, severe findings: pytest-cov
    # was never an installed dependency (every real call hard-failed
    # with a usage error), `path` was protected only by shlex.quote()
    # (shell-safety, not pytest's-own-flag-parser-safety), and no
    # worktree-boundary check existed at all.
    def coverage_report(inp: dict[str, Any]) -> str:
        return coverage_report_handler(root, repo_path, inp)

    def type_check(inp: dict[str, Any]) -> str:
        return type_check_handler(root, repo_path, inp)

    # =========================================================================
    # BATCH 5 — Code Intelligence
    # =========================================================================

    # tool_enhance.md productionization pass, tool #82 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation and an uncaught PermissionError, same class as tool
    # #76's analyze_file) lives in the shared list_functions_handler()
    # itself; see that function's own module docstring.
    def list_functions(inp: dict[str, Any]) -> str:
        return list_functions_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #87 (2026-08-24) — the
    # real fix (this implementation had ZERO worktree-boundary
    # validation and an uncaught PermissionError, same class as tool
    # #76's analyze_file/tool #82's list_functions) lives in the
    # shared list_classes_handler() itself; see that function's own
    # module docstring.
    def list_classes(inp: dict[str, Any]) -> str:
        return list_classes_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #111 (2026-08-26) — the
    # real fix (ZERO worktree-boundary validation on `path`) lives in
    # the shared find_function_body_handler(); see that function's own
    # module docstring.
    def find_function_body(inp: dict[str, Any]) -> str:
        return find_function_body_handler(root, repo_path, inp)

    # =========================================================================
    # BATCH 6 — Debug tools
    # =========================================================================

    # tool_enhance.md productionization pass, tool #116 (2026-08-26) —
    # was a worktree-escape arbitrary file READ (explicitly bypassed
    # `root` for any absolute `path`) and was missing try/except +
    # timeout around its file-tail subprocess call. Now delegates to
    # the shared, worktree-validated handler.
    def read_logs(inp: dict[str, Any]) -> str:
        return read_logs_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #121 (2026-08-26) —
    # the real fix lives in the shared analyze_error_handler(); see
    # that function's own module docstring.
    def analyze_error(inp: dict[str, Any]) -> str:
        return analyze_error_handler(inp)

    # =========================================================================
    # BATCH 7 — Database tools
    # =========================================================================

    # moved to app/tools/database/sql.py as run_sql_handler —
    # tool_enhance.md productionization pass, tool #15 (2026-08-17).
    def run_sql(inp: dict[str, Any]) -> str:
        rs_settings = get_settings()
        rs_db_url = str(getattr(rs_settings, "database_url", "") or "")
        return run_sql_handler(rs_db_url, inp)

    # tool_enhance.md productionization pass, tool #96 (2026-08-25) — the
    # real fix lives in the shared inspect_schema_handler(); see that
    # function's own module docstring.
    def inspect_schema(inp: dict[str, Any]) -> str:
        is_db_url = str(getattr(get_settings(), "database_url", "") or "")
        return inspect_schema_handler(is_db_url, inp)

    # =========================================================================
    # BATCH 8 — Docker tools
    # =========================================================================

    # tool_enhance.md productionization pass, tool #109 (2026-08-26) — the
    # real fix lives in the shared docker_ps_handler(); see that
    # function's own module docstring.
    def docker_ps(inp: dict[str, Any]) -> str:
        return docker_ps_handler(inp)

    # tool_enhance.md productionization pass, tool #108 (2026-08-25) — the
    # real fix lives in the shared docker_logs_handler(); see that
    # function's own module docstring.
    def docker_logs(inp: dict[str, Any]) -> str:
        return docker_logs_handler(inp)

    def docker_exec(inp: dict[str, Any]) -> str:
        de_container = str(inp["container"])
        de_command = str(inp["command"])
        de_policy = check_command(de_command)
        if not de_policy.allowed:
            return f"[POLICY DENIED] {de_policy.reason}"
        de_risk = _docker_container_risk_reason(de_container)
        if de_risk:
            return f"[POLICY DENIED] {de_risk}"
        try:
            r = subprocess.run(
                ["docker", "exec", de_container, "sh", "-c", de_command],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout + r.stderr)[:5000] or "(no output)"
        except FileNotFoundError:
            return "[ERROR] docker not found"
        except subprocess.TimeoutExpired:
            return "[ERROR] Command timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def docker_compose(inp: dict[str, Any]) -> str:
        dc_action = str(inp["action"])
        dc_services: list[str] = list(inp.get("services") or [])
        dc_detach = bool(inp.get("detach", True))
        dc_cmd = ["docker", "compose"]
        if dc_action == "up":
            # "up" creates/starts containers from whatever docker-compose.yml
            # currently sits in the repo — including one this same agent
            # could have just written via write_file, with no restriction on
            # privileged:/pid: host/cap_add/host mounts. docker_exec's own
            # risk-inspection guard only ever sees a container *after* it
            # exists; this is the actual creation step.
            #
            # tool_enhance.md productionization pass, tool #4 (2026-08-16) —
            # real gap found: the confirmation attempt here used
            # session.request_confirmation(), but `session` is never
            # non-None for any real caller of make_chat_handlers() (grepped
            # every real call site in the repo — none pass one; only tests
            # construct a fake session). docker_agent, a real, registered
            # one-shot agent, genuinely has docker_compose in its
            # allowed_tools — so 'up' was a live, permanently-broken dead
            # end for it (every other action still worked). Fixed with the
            # same fail-closed, config-driven gate as create_pr_require_approval
            # (tool #2's second pass) — the honest fix for this handler
            # tier, which has no per-call human-approval channel at all,
            # rather than an unreachable pseudo-confirmation.
            if get_settings().docker_compose_up_require_approval:
                return (
                    "[POLICY DENIED] docker_compose('up') requires human "
                    "approval, and this execution context has no per-call "
                    "approval channel available (see Settings."
                    "docker_compose_up_require_approval). Use the "
                    "interactive chat agent instead, which gates this "
                    "behind a real confirmation prompt."
                )

            dc_cmd.append("up")
            if dc_detach:
                dc_cmd.append("-d")
        elif dc_action in ("down", "restart", "build", "ps", "pull"):
            dc_cmd.append(dc_action)
        elif dc_action == "logs":
            dc_cmd += ["logs", "--tail=50"]
        else:
            return f"[ERROR] Unknown action: {dc_action}"
        dc_cmd.extend(dc_services)
        try:
            r = subprocess.run(
                dc_cmd, cwd=repo_path, capture_output=True, text=True, timeout=120
            )
            return (r.stdout + r.stderr)[
                :5000
            ] or f"docker compose {dc_action} complete"
        except FileNotFoundError:
            return "[ERROR] docker not found"
        except subprocess.TimeoutExpired:
            return f"[ERROR] docker compose {dc_action} timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    # tool_enhance.md productionization pass, tool #106 (2026-08-25) — the
    # real fix lives in the shared gather_deployment_diagnostics(); see
    # that function's own module docstring. _llm_diagnose_deployment_
    # failure() itself is unchanged and still called here directly.
    def diagnose_deployment_failure(inp: dict[str, Any]) -> str:
        context = gather_deployment_diagnostics(inp)
        if context.startswith("[ERROR]") or context.startswith("[POLICY DENIED]"):
            return context
        diagnosis = _llm_diagnose_deployment_failure(context)
        return f"{context}\n\n=== Diagnosis ===\n{diagnosis}"

    # =========================================================================
    # BATCH 9 — Security tools
    # =========================================================================

    # tool_enhance.md productionization pass, tool #102 (2026-08-25) — the
    # real fix lives in the shared secrets_scan_handler(); see that
    # function's own module docstring.
    def secrets_scan(inp: dict[str, Any]) -> str:
        return secrets_scan_handler(root, repo_path, inp)

    handlers["edit_file"] = edit_file
    handlers["write_file"] = write_file
    handlers["git_diff"] = git_diff
    handlers["bash"] = bash
    handlers["append_file"] = append_file
    handlers["rename_file"] = rename_file
    handlers["copy_file"] = copy_file
    handlers["delete_file"] = delete_file
    handlers["git_commit"] = git_commit
    handlers["git_branch"] = git_branch
    handlers["git_checkout"] = git_checkout
    handlers["git_stash"] = git_stash
    handlers["git_pull"] = git_pull
    handlers["git_fetch"] = git_fetch
    handlers["git_restore"] = git_restore
    handlers["git_push"] = git_push_handler
    handlers["create_branch"] = create_branch
    handlers["run_tests"] = run_tests
    handlers["run_linter"] = run_linter
    handlers["submit_result"] = submit_result_handler
    # Batch 1
    handlers["find_file"] = find_file
    handlers["format_file"] = format_file
    handlers["organize_imports"] = organize_imports
    handlers["insert_at_line"] = insert_at_line
    handlers["replace_function"] = replace_function
    handlers["delete_lines"] = delete_lines
    handlers["apply_patch"] = apply_patch
    handlers["compare_files"] = compare_files
    handlers["sync_files"] = sync_files
    # Batch 2
    handlers["run_background"] = run_background
    handlers["kill_process"] = kill_process
    handlers["list_background_processes"] = list_background_processes_h
    handlers["run_parallel_commands"] = lambda inp: run_parallel_commands_handler(
        repo_path, inp
    )
    handlers["run_python_snippet"] = run_python_snippet
    handlers["run_make"] = run_make
    handlers["fetch_url"] = fetch_url
    # AUDIT_Q_BATCH09 §79/80 gap-closure — web_search is standalone (see its
    # own docstring: "so any agent can reuse it, not just the research
    # agent"), but was only ever wired into make_research_handlers. Any
    # agent built on make_chat_handlers (e.g. spike_agent) can now declare
    # it in allowed_tools and get a real handler, matching fetch_url above.
    handlers["web_search"] = web_search_handler
    # Batch 3
    handlers["git_merge"] = git_merge
    handlers["parse_merge_conflicts"] = parse_merge_conflicts
    handlers["explain_merge_conflict"] = explain_merge_conflict
    handlers["resolve_merge_conflict"] = resolve_merge_conflict
    handlers["git_reset"] = lambda inp: git_reset_handler(repo_path, inp)
    handlers["git_worktree"] = git_worktree
    handlers["create_pr"] = create_pr
    handlers["generate_commit_msg"] = generate_commit_msg
    handlers["review_diff"] = review_diff
    handlers["inspect_github_repo"] = inspect_github_repo
    handlers["inspect_openapi_spec"] = inspect_openapi_spec
    # Batch 4
    handlers["run_single_test"] = run_single_test
    handlers["coverage_report"] = coverage_report
    handlers["type_check"] = type_check
    # Batch 5
    handlers["list_functions"] = list_functions
    handlers["list_classes"] = list_classes
    handlers["find_function_body"] = find_function_body
    # Batch 6
    handlers["read_logs"] = read_logs
    handlers["analyze_error"] = analyze_error
    # Batch 7
    handlers["run_sql"] = run_sql
    handlers["inspect_schema"] = inspect_schema
    # Batch 8
    handlers["docker_ps"] = docker_ps
    handlers["docker_logs"] = docker_logs
    handlers["docker_exec"] = docker_exec
    handlers["docker_compose"] = docker_compose
    handlers["diagnose_deployment_failure"] = diagnose_deployment_failure
    # Batch 9
    handlers["secrets_scan"] = secrets_scan

    # =========================================================================
    # BATCH 10 — AST Engine (parse_ast, import_graph, call_graph, dead_code_detect,
    #             circular_dep_detect, rename_symbol)
    # =========================================================================

    # tool_enhance.md productionization pass, tool #83 (2026-08-24) — the
    # real fix lives in the shared parse_ast_handler(); see that
    # function's own module docstring.
    def parse_ast_h(inp: dict[str, Any]) -> str:
        return parse_ast_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #95 (2026-08-25) — the
    # real fix lives in the shared import_graph_handler(); see that
    # function's own module docstring.
    def import_graph_h(inp: dict[str, Any]) -> str:
        return import_graph_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #93 (2026-08-25) — the
    # real fix lives in the shared call_graph_handler(); see that
    # function's own module docstring.
    def call_graph_h(inp: dict[str, Any]) -> str:
        return call_graph_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #94 (2026-08-25) — the
    # real fix lives in the shared dead_code_detect_handler(); see that
    # function's own module docstring.
    def dead_code_detect_h(inp: dict[str, Any]) -> str:
        return dead_code_detect_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #97 (2026-08-25) — the
    # real fix lives in the shared circular_dep_detect_handler(); see
    # that function's own module docstring.
    def circular_dep_detect_h(inp: dict[str, Any]) -> str:
        return circular_dep_detect_handler(root, repo_path, inp)

    def rename_symbol_h(inp: dict[str, Any]) -> str:
        from app.repo_tools.ast_engine import rename_symbol as _rsym

        rs_d = str(inp.get("directory", ""))
        rsym_error = validate_rename_symbol_directory(rs_d, repo_path)
        if rsym_error:
            return f"[POLICY DENIED] {rsym_error}"
        return _rsym(
            str(inp["old_name"]),
            str(inp["new_name"]),
            str(root / rs_d) if rs_d else repo_path,
            str(inp.get("file_pattern", "*.py")),
            confirm_large_batch=bool(inp.get("confirm_large_batch", False)),
        )

    handlers["parse_ast"] = parse_ast_h
    handlers["import_graph"] = import_graph_h
    handlers["call_graph"] = call_graph_h
    handlers["dead_code_detect"] = dead_code_detect_h
    handlers["circular_dep_detect"] = circular_dep_detect_h
    handlers["rename_symbol"] = rename_symbol_h
    handlers["batch_edit"] = lambda inp: batch_edit_handler(root, repo_path, inp)

    # =========================================================================
    # BATCH 11 — Git extras (git_rebase, git_cherry_pick)
    # =========================================================================

    # moved to app/tools/git/rebase.py — this now calls the shared validate_git_rebase_inputs() first
    def git_rebase_h(inp: dict[str, Any]) -> str:
        grb_onto = str(inp["onto"])
        grb_error = validate_git_rebase_inputs(grb_onto)
        if grb_error:
            return grb_error
        if bool(inp.get("interactive", False)):
            return "[BLOCKED] Interactive rebase requires a TTY. Run 'git rebase -i' manually in a terminal."
        try:
            r = subprocess.run(
                ["git", "rebase", grb_onto],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] git rebase timed out"
        except Exception as e:
            return f"[ERROR] {e}"

    def git_cherry_pick_h(inp: dict[str, Any]) -> str:
        gcp_hash = str(inp["commit_hash"])
        gcp_error = validate_git_cherry_pick_inputs(gcp_hash)
        if gcp_error:
            return gcp_error
        gcp_cmd = ["git", "cherry-pick"]
        if bool(inp.get("no_commit", False)):
            gcp_cmd.append("--no-commit")
        gcp_cmd.append(gcp_hash)
        try:
            r = subprocess.run(
                gcp_cmd, cwd=repo_path, capture_output=True, text=True, timeout=30
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["git_rebase"] = git_rebase_h
    handlers["git_cherry_pick"] = git_cherry_pick_h

    # =========================================================================
    # BATCH 12 — Terminal extras (read_output, run_node, run_script, docker_build, docker_restart)
    # =========================================================================

    def _read_stream_nonblocking(stream: Any, max_bytes: int = 8192) -> str | None:
        """Best-effort non-blocking read of up to max_bytes from a pipe.

        fcntl-based O_NONBLOCK (the POSIX approach) doesn't exist on Windows
        pipe file descriptors — found via real execution (ModuleNotFoundError:
        'fcntl'), which broke every test that reaches this handler. On
        Windows, run the blocking read() in a daemon thread and give it a
        short timeout instead: if data arrives in time we return it, if not
        we abandon the thread (harmless — it's a daemon thread that will
        simply finish, its result unused, whenever the target process next
        writes or exits) and report no output yet, matching this function's
        existing "(no output yet ...)" behavior for an idle process.
        """
        if sys.platform != "win32":
            import fcntl as _fcntl

            fd = stream.fileno()
            fl = _fcntl.fcntl(fd, _fcntl.F_GETFL)
            _fcntl.fcntl(fd, _fcntl.F_SETFL, fl | os.O_NONBLOCK)
            try:
                chunk: str | None = stream.read(max_bytes)
                return chunk
            except (IOError, BlockingIOError, TypeError):
                return None

        import threading

        result: dict[str, str | None] = {"data": None}

        def _reader() -> None:
            try:
                result["data"] = stream.read(max_bytes)
            except Exception:
                pass

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        t.join(timeout=0.1)
        return result["data"]

    # tool_enhance.md productionization pass, tool #176 (2026-09-15) —
    # was an uncaught crash on malformed pid/lines (missing pid,
    # non-numeric pid, non-numeric lines — all proved live); the
    # underlying process_manager.read_output() was already safe. Now
    # delegates to the shared, input-validated handler.
    def read_output_h(inp: dict[str, Any]) -> str:
        return read_output_handler(inp, _session_bg_procs, _read_stream_nonblocking)

    # tool_enhance.md productionization pass, tool #60 (2026-08-22) — the
    # real fix (an unbounded timeout clamp) lives in the shared
    # run_node_handler() itself; see that function's own module docstring.
    def run_node_h(inp: dict[str, Any]) -> str:
        return run_node_handler(repo_path, inp)

    # tool_enhance.md productionization pass, tool #61 (2026-08-22) — the
    # real fix lives in the shared run_script_handler() itself; see that
    # function's own module docstring.
    def run_script_h(inp: dict[str, Any]) -> str:
        return run_script_handler(root, repo_path, inp)

    def docker_build_h(inp: dict[str, Any]) -> str:
        dbld_tag = str(inp["tag"])
        dbld_context = str(inp.get("context", "."))
        dbld_df = inp.get("dockerfile")
        dbld_error = validate_docker_build_inputs(
            dbld_context, str(dbld_df) if dbld_df else None, repo_path
        )
        if dbld_error:
            return f"[POLICY DENIED] {dbld_error}"
        dbld_ctx_path = str(root / dbld_context) if dbld_context != "." else repo_path
        dbld_cmd = ["docker", "build", "-t", dbld_tag]
        if dbld_df:
            dbld_cmd += ["-f", str(root / str(dbld_df))]
        dbld_cmd.append(dbld_ctx_path)
        try:
            r = subprocess.run(
                dbld_cmd, cwd=repo_path, capture_output=True, text=True, timeout=600
            )
            result = (r.stdout + r.stderr).strip()
            if r.returncode != 0:
                result += f"\n[exit {r.returncode}]"
            return result or "(no output)"
        except subprocess.TimeoutExpired:
            return "[ERROR] docker build timed out after 600s"
        except Exception as e:
            return f"[ERROR] {e}"

    def docker_restart_h(inp: dict[str, Any]) -> str:
        drst_name = str(inp["container"])
        try:
            r = subprocess.run(
                ["docker", "restart", drst_name],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return (r.stdout + r.stderr).strip() or f"Restarted {drst_name}"
        except Exception as e:
            return f"[ERROR] {e}"

    handlers["read_output"] = read_output_h
    handlers["run_node"] = run_node_h
    handlers["run_script"] = run_script_h
    handlers["docker_build"] = docker_build_h
    handlers["docker_restart"] = docker_restart_h

    # =========================================================================
    # BATCH 13 — Smart search (find_route, find_api, find_sql, find_test, find_config)
    # =========================================================================

    # tool_enhance.md productionization pass, tool #90 (2026-08-24) — this
    # implementation was already correct; unified onto the shared
    # find_route_handler() for maintainability (2 sibling
    # implementations elsewhere had a severe field-name mismatch); see
    # that function's own module docstring.
    def find_route_h(inp: dict[str, Any]) -> str:
        return find_route_handler(root, inp)

    # tool_enhance.md productionization pass, tool #89 (2026-08-24) — the
    # real fix (ZERO validation of `name` — a flag-injection bug, same
    # class as tool #69's search_code) lives in the shared
    # find_api_handler() itself; see that function's own module
    # docstring.
    def find_api_h(inp: dict[str, Any]) -> str:
        return find_api_handler(root, inp)

    # tool_enhance.md productionization pass, tool #91 (2026-08-24) — the
    # real fix (ZERO validation of `keyword` — a flag-injection bug)
    # lives in the shared find_sql_handler() itself; see that
    # function's own module docstring.
    def find_sql_h(inp: dict[str, Any]) -> str:
        return find_sql_handler(root, inp)

    # tool_enhance.md productionization pass, tool #140 (2026-09-11) —
    # this implementation was already correct; the real fix (a
    # separately-drifted, narrower reimplementation in
    # chat_agent.py's dispatch) lives in the shared handler; see that
    # module's own docstring.
    def find_test_h(inp: dict[str, Any]) -> str:
        return find_test_handler(repo_path, inp)

    # tool_enhance.md productionization pass, tool #99 (2026-08-25) — the
    # real fix lives in the shared find_config_handler(); see that
    # function's own module docstring.
    def find_config_h(inp: dict[str, Any]) -> str:
        return find_config_handler(root, inp)

    handlers["find_route"] = find_route_h
    handlers["find_api"] = find_api_h
    handlers["find_sql"] = find_sql_h
    handlers["find_test"] = find_test_h
    handlers["find_config"] = find_config_h

    # =========================================================================
    # BATCH 14 — Monitoring (cpu_usage, memory_usage, disk_usage, health_check, task_progress)
    # =========================================================================

    # tool_enhance.md productionization pass, tool #105 (2026-08-25) — the
    # real fix (a single /proc/stat read was mislabeled as "current"
    # CPU usage — it can only ever measure the average since boot,
    # proved live: 22.4% single-read vs 9.6% real delta-based usage at
    # the exact same moment) lives in the shared cpu_usage_handler();
    # see that function's own module docstring.
    def cpu_usage_h(inp: dict[str, Any]) -> str:
        return cpu_usage_handler()

    # tool_enhance.md productionization pass, tool #114 (2026-08-26) — the
    # real fix lives in the shared memory_usage_handler(); see that
    # function's own module docstring.
    def memory_usage_h(inp: dict[str, Any]) -> str:
        return memory_usage_handler()

    # tool_enhance.md productionization pass, tool #107 (2026-08-25) — the
    # real fix (zero worktree-boundary validation on `path`) lives in
    # the shared disk_usage_handler(); see that function's own module
    # docstring.
    def disk_usage_h(inp: dict[str, Any]) -> str:
        return disk_usage_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #113 (2026-08-26) — the
    # real fix lives in the shared health_check_handler(); see that
    # function's own module docstring.
    def health_check_h(inp: dict[str, Any]) -> str:
        settings = get_settings()
        return health_check_handler(
            inp,
            port=getattr(settings, "port", 8000),
            database_url=str(getattr(settings, "database_url", "") or ""),
        )

    # tool_enhance.md productionization pass, tool #119 (2026-08-26) —
    # was completely non-functional wherever `psql` isn't installed.
    # Now delegates to the shared, psycopg2-backed handler.
    def task_progress_h(inp: dict[str, Any]) -> str:
        return task_progress_handler(inp)

    handlers["cpu_usage"] = cpu_usage_h
    handlers["memory_usage"] = memory_usage_h
    handlers["disk_usage"] = disk_usage_h
    handlers["health_check"] = health_check_h
    handlers["task_progress"] = task_progress_h

    # =========================================================================
    # BATCH 15 — Editing extras (replace_class, undo_changes, generate_patch)
    # =========================================================================

    # moved to app/tools/filesystem/replace_class.py — this now delegates to the shared replace_class_handler()
    def replace_class_h(inp: dict[str, Any]) -> str:
        return replace_class_handler(root, repo_path, inp)

    def undo_changes_h(inp: dict[str, Any]) -> str:
        undo_rel = str(inp["path"])
        if _is_protected_path(undo_rel, repo_path):
            return f"[POLICY DENIED] Protected path: {undo_rel}"

        settings = get_settings()
        if settings.sentry_environment == "production":
            return (
                "[BLOCKED] undo_changes is disabled in the production environment. "
                "Run migrations in a non-production environment only."
            )

        # tool_enhance.md productionization pass, tool #4 (2026-08-16) —
        # real gap found: `session` is never non-None for any real caller
        # of make_chat_handlers() (grepped every real call site in the
        # repo — none pass one; undo_changes isn't in any one-shot agent's
        # allowed_tools either). The interactive chat agent has its own
        # separate, real, working undo_changes dispatch with a genuine
        # self._confirm() gate. Simplified to state that plainly instead
        # of dead async plumbing that could never execute.
        return "[BLOCKED] undo_changes requires interactive session for safety confirmation"

    # tool_enhance.md productionization pass, tool #147 (2026-09-14) —
    # no real bug found (no filesystem access, no subprocess — pure
    # in-memory difflib); consolidated the two independently-hand-
    # maintained duplicate implementations into one shared handler per
    # the mandatory modularization rule.
    def generate_patch_h(inp: dict[str, Any]) -> str:
        return generate_patch_handler(inp)

    handlers["replace_class"] = replace_class_h
    handlers["undo_changes"] = undo_changes_h
    handlers["generate_patch"] = generate_patch_h

    # =========================================================================
    # BATCH 16 — DB extras (explain_query, run_migration, seed_database)
    # =========================================================================

    # tool_enhance.md productionization pass, tool #98 (2026-08-25) — the
    # real fix lives in the shared explain_query_handler(); see that
    # function's own module docstring.
    def explain_query_h(inp: dict[str, Any]) -> str:
        expq_db = str(getattr(get_settings(), "database_url", "") or "")
        return explain_query_handler(expq_db, inp)

    # run_migration_h removed — tool_enhance.md productionization pass,
    # tool #8 (2026-08-16). Now registered directly against
    # run_migration_handler (app/tools/database/migration.py), which
    # also closes a real shell-injection finding (see that module's
    # docstring) that this handler was never actually reachable enough
    # to be exploitable through, but shares the same validation as the
    # real, reachable chat_agent.py dispatch for defense-in-depth.

    # seed_database_h removed — tool_enhance.md productionization pass,
    # tool #10 (2026-08-16). Now registered directly against
    # seed_database_handler (app/tools/database/seed.py), which also
    # closes a real shell-injection + path-boundary-escape finding (see
    # that module's docstring).

    handlers["explain_query"] = explain_query_h
    handlers["run_migration"] = lambda inp: run_migration_handler(repo_path, inp)
    handlers["seed_database"] = lambda inp: seed_database_handler(repo_path, inp)

    # =========================================================================
    # DAY 3A — Browser tools (Playwright)
    # =========================================================================

    # moved to app/tools/browser/browser_tools.py — tool_enhance.md
    # productionization pass, tools #28-#31 + #123-#125 (2026-08-18).
    def _browser_sid() -> str:
        return getattr(session, "session_id", None) or "__default__"

    def browser_open_h(inp: dict[str, Any]) -> str:
        return browser_open_handler(inp, session_id=_browser_sid())

    def browser_navigate_h(inp: dict[str, Any]) -> str:
        return browser_navigate_handler(inp, session_id=_browser_sid())

    def browser_screenshot_h(inp: dict[str, Any]) -> str:
        return browser_screenshot_handler(inp, session_id=_browser_sid())

    def browser_read_dom_h(inp: dict[str, Any]) -> str:
        return browser_read_dom_handler(inp, session_id=_browser_sid())

    def browser_click_h(inp: dict[str, Any]) -> str:
        return browser_click_handler(inp, session_id=_browser_sid())

    def browser_type_h(inp: dict[str, Any]) -> str:
        return browser_type_handler(inp, session_id=_browser_sid())

    def browser_close_h(inp: dict[str, Any]) -> str:
        return browser_close_handler(inp, session_id=_browser_sid())

    handlers["browser_open"] = browser_open_h
    handlers["browser_navigate"] = browser_navigate_h
    handlers["browser_screenshot"] = browser_screenshot_h
    handlers["browser_read_dom"] = browser_read_dom_h
    handlers["browser_click"] = browser_click_h
    handlers["browser_type"] = browser_type_h
    handlers["browser_close"] = browser_close_h

    # =========================================================================
    # DAY 3B — Memory tools (flat JSON files per repo slug)
    # =========================================================================

    # tool_enhance.md productionization pass, tool #167 (2026-09-15) —
    # incidental cleanup: `_mem_lock`/`_mem_unlock` (the cross-platform
    # advisory file lock), `_json_mem`, `_mem_slug`/`_mem_dir`, and
    # `_mem_decisions_path` all became fully dead code as of this
    # tool's fix — their last real callers (`_read_mem_store`/
    # `_write_mem_store`, just removed above) were already unreachable
    # leftovers from tools #51/#133's earlier fixes (both delegate to
    # their own shared modules now), but stayed defined until this
    # turn finally removed the one still-live caller
    # (`memory_read_h`). Confirmed via grep: zero remaining references
    # to any of these five names anywhere else in this file before
    # removing them.

    # tool_enhance.md productionization pass, tool #167 (2026-09-15) —
    # no worktree-escape or injection surface exists (`key` reaches
    # only a pure in-memory dict lookup against a fixed,
    # deterministic store path); the real fix was a missing
    # chat_agent.py dispatch (this tool was never reachable from
    # interactive chat at all, proved live). Now delegates to the
    # shared handler.
    def memory_read_h(inp: dict[str, Any]) -> str:
        return memory_read_handler(repo_path, inp)

    # moved to app/tools/agents/memory_write.py — this now calls the shared, atomic write_memory_key()
    # (real, empirically-proven lost-update race condition fixed there; see that module's own docstring)
    def memory_write_h(inp: dict[str, Any]) -> str:
        key = str(inp["key"])
        value = str(inp["value"])
        return write_memory_key(repo_path, key, value)

    # tool_enhance.md productionization pass, tool #133 (2026-09-11) —
    # no vulnerability in this handler itself (no LLM-controlled path,
    # fixed deterministic target file); the real fix (chat_agent.py had
    # zero dispatch) lives in the shared handler; see that module's own
    # docstring.
    def decision_log_append_h(inp: dict[str, Any]) -> str:
        return decision_log_append_handler(repo_path, inp)

    task_history_query_h = task_history_query

    # tool_enhance.md productionization pass, tool #160 (2026-09-15) —
    # no worktree-escape or injection surface exists (empty schema,
    # fixed deterministic path); the real fix was a missing
    # chat_agent.py dispatch (this tool was never reachable from
    # interactive chat at all, proved live). Now delegates to the
    # shared handler.
    def known_issues_read_h(inp: dict[str, Any]) -> str:
        return known_issues_read_handler(repo_path)

    # tool_enhance.md productionization pass, tool #161 (2026-09-15) —
    # no worktree-escape or injection surface exists (destination path
    # is fixed, derived from repo_path alone, never from `issue`/
    # `severity`); the real fix was a missing chat_agent.py dispatch
    # (this tool was never reachable from interactive chat at all,
    # proved live). Now delegates to the shared handler.
    def known_issues_write_h(inp: dict[str, Any]) -> str:
        return known_issues_write_handler(repo_path, inp)

    handlers["memory_read"] = memory_read_h
    handlers["memory_write"] = memory_write_h
    handlers["decision_log_append"] = decision_log_append_h
    handlers["task_history_query"] = task_history_query_h
    handlers["known_issues_read"] = known_issues_read_h
    handlers["known_issues_write"] = known_issues_write_h
    # AUDIT_Q_BATCH15 §74/§113 gap-closure (2026-08-11).
    handlers["record_preference"] = make_record_preference_handler(
        task_id=f"chat-{session.session_id}" if session is not None else "chat"
    )

    # =========================================================================
    # DAY 3C — Planning + docs tools
    # =========================================================================

    # tool_enhance.md productionization pass, tool #110 (2026-08-26) — the
    # real fix lives in the shared estimate_complexity_handler(); see
    # that function's own module docstring.
    def estimate_complexity_h(inp: dict[str, Any]) -> str:
        return estimate_complexity_handler(inp)

    def summarize_folder_h(inp: dict[str, Any]) -> str:
        return summarize_folder_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #144 (2026-09-14) —
    # was a worktree-escape route/function-name disclosure oracle
    # (`root / route_path` never validated, proved live to disclose
    # real route + function names from a file outside the worktree).
    # Now delegates to the shared, worktree-validated handler.
    def generate_api_docs_text_h(inp: dict[str, Any]) -> str:
        return generate_api_docs_text_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #168 (2026-09-15) —
    # was SEVERE: the tool has never actually worked in real
    # production use (shelled out to the `psql` CLI, which the real
    # runtime does not have installed — proved live inside the real
    # backend container: every real call genuinely raised
    # FileNotFoundError). A theorized SQL-injection risk via `table`
    # (matching sibling tool #96's finding) was investigated and
    # empirically REFUTED for this tool's specific `\d`-meta-command
    # construction — see the new module's own docstring. Also a
    # missing chat_agent.py dispatch. Now delegates to the shared
    # handler, which uses real psycopg2 parameter binding instead of
    # shelling out to psql at all — the tool genuinely works for the
    # first time.
    def mermaid_from_schema_h(inp: dict[str, Any]) -> str:
        mfs_db_url = str(getattr(get_settings(), "database_url", "") or "")
        return mermaid_from_schema_handler(mfs_db_url, inp)

    handlers["estimate_complexity"] = estimate_complexity_h
    handlers["summarize_folder"] = summarize_folder_h
    handlers["generate_api_docs_text"] = generate_api_docs_text_h
    handlers["mermaid_from_schema"] = mermaid_from_schema_h

    # =========================================================================
    # DAY 3G — External integrations (GitHub/Linear/Slack — not MCP protocol)
    # =========================================================================

    import subprocess as _sp_mcp
    import os as _os_mcp

    # moved to app/tools/git/github_create_issue.py — command-building now shared via github_create_issue_command()
    def github_create_issue_h(inp: dict[str, Any]) -> str:
        title = str(inp["title"])
        body = str(inp["body"])
        labels = [str(lbl) for lbl in inp.get("labels", [])]
        cmd = github_create_issue_command(title, body, labels)
        try:
            r = _sp_mcp.run(
                cmd, capture_output=True, text=True, cwd=str(root), timeout=30
            )
            return (r.stdout + r.stderr).strip() or "(no output)"
        except FileNotFoundError:
            return "[ERROR] gh CLI not found — install GitHub CLI"
        except Exception as e:
            return f"[ERROR] {e}"

    # tool_enhance.md productionization pass, tool #153 (2026-09-14) —
    # `state`'s flag-collision resistance checked and confirmed
    # already safe (proved live: `gh`'s own CLI strictly enforces a
    # hard enum on --state); the real fix was a missing chat_agent.py
    # dispatch (this tool was never reachable from interactive chat at
    # all, proved live). Now delegates to the shared handler.
    def github_list_prs_h(inp: dict[str, Any]) -> str:
        return github_list_prs_handler(root, inp)

    # moved to app/tools/git/github_comment.py — command-building now shared via github_comment_command()
    def github_comment_h(inp: dict[str, Any]) -> str:
        number = int(inp["number"])
        body = str(inp["body"])
        kind = str(inp.get("kind", "issue"))
        try:
            r = _sp_mcp.run(
                github_comment_command(number, body, kind),
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=30,
            )
            return (r.stdout + r.stderr).strip() or "Comment posted"
        except FileNotFoundError:
            return "[ERROR] gh CLI not found"
        except Exception as e:
            return f"[ERROR] {e}"

    # moved to app/tools/integrations/linear_create_issue.py — this now calls the shared create_linear_issue()
    def linear_create_issue_h(inp: dict[str, Any]) -> str:
        api_key = _os_mcp.environ.get("LINEAR_API_KEY", "")
        if not api_key:
            return "[ERROR] LINEAR_API_KEY not set"
        title = str(inp["title"])
        description = str(inp["description"])
        team_key = str(inp["team_key"])
        return create_linear_issue(api_key, title, description, team_key)

    # tool_enhance.md productionization pass, tool #63 (2026-08-22) —
    # the real fix (a new chat_agent.py dispatch, since this was
    # advertised but never dispatched there) lives in
    # send_slack_message() itself; see that function's own module
    # docstring.
    def slack_send_message_h(inp: dict[str, Any]) -> str:
        webhook_url = _os_mcp.environ.get("SLACK_WEBHOOK_URL", "")
        if not webhook_url:
            return "[ERROR] SLACK_WEBHOOK_URL not set"
        return send_slack_message(webhook_url, str(inp["text"]))

    handlers["github_create_issue"] = github_create_issue_h
    handlers["github_list_prs"] = github_list_prs_h
    handlers["github_comment"] = github_comment_h
    handlers["linear_create_issue"] = linear_create_issue_h
    handlers["slack_send_message"] = slack_send_message_h

    # ── Day 2 Gap handlers ─────────────────────────────────────────────────────

    # tool_enhance.md productionization pass, tool #139 (2026-09-11) —
    # was a worktree-escape FULL FILE CONTENT disclosure oracle
    # (`repo_path` used completely unanchored/unvalidated, proved live
    # to disclose real content lines from a directory outside the
    # worktree). Now delegates to the shared, worktree-validated
    # handler.
    def find_queue_h(inp: dict[str, Any]) -> str:
        return find_queue_handler(repo_path, inp)

    # tool_enhance.md productionization pass, tool #142 (2026-09-11) —
    # same finding class as sibling tool #139's find_queue: was a
    # worktree-escape FULL FILE CONTENT disclosure oracle (`repo_path`
    # used completely unanchored/unvalidated, proved live to disclose
    # real content lines from a directory outside the worktree). Now
    # delegates to the shared, worktree-validated handler.
    def find_worker_h(inp: dict[str, Any]) -> str:
        return find_worker_handler(repo_path, inp)

    # moved to app/tools/filesystem/insert_before.py — this now delegates to the shared insert_before_handler()
    def insert_before_h(inp: dict[str, Any]) -> str:
        return insert_before_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/insert_after.py — this now delegates to the shared insert_after_handler()
    def insert_after_h(inp: dict[str, Any]) -> str:
        return insert_after_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/delete_block.py as
    # delete_block_handler — tool_enhance.md productionization pass,
    # tool #33 (2026-08-18).
    def delete_block_h(inp: dict[str, Any]) -> str:
        return delete_block_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #100 (2026-08-25) — the
    # real fix lives in the shared generate_changelog_handler(); see
    # that function's own module docstring.
    def generate_changelog_h(inp: dict[str, Any]) -> str:
        return generate_changelog_handler(root, inp)

    def summarize_repo_h(inp: dict[str, Any]) -> str:
        return summarize_repo_handler(root, inp)

    # tool_enhance.md productionization pass, tool #112 (2026-08-26) — the
    # real fix lives in the shared generate_release_notes_handler(); see
    # that function's own module docstring. Real, severe finding
    # (same class as tool #100's generate_changelog): a silent
    # arbitrary-file-write via git log's generic --output=<path> flag
    # on from_ref, PLUS an LLM-controlled repo_path override
    # disclosing commit history from ANY host git repo.
    def generate_release_notes_h(inp: dict[str, Any]) -> str:
        return generate_release_notes_handler(root, inp)

    # tool_enhance.md productionization pass, tool #177 (2026-09-15) —
    # was a SEVERE worktree-escape ARBITRARY PDF FILE READ oracle
    # (explicitly bypassed `root` for absolute paths, proved live) and
    # a missing chat_agent.py dispatch. Now delegates to the shared,
    # worktree-validated handler.
    def read_pdf_h(inp: dict[str, Any]) -> str:
        return read_pdf_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #174 (2026-09-15) —
    # was a SEVERE worktree-escape ARBITRARY IMAGE FILE READ oracle
    # (explicitly bypassed `root` for absolute paths, AND relative
    # traversal was never validated, both proved live) and a missing
    # chat_agent.py dispatch. Now delegates to the shared,
    # worktree-validated handler.
    def read_image_h(inp: dict[str, Any]) -> str:
        return read_image_handler(root, repo_path, inp)

    # github_create_pr_h removed — tool_enhance.md productionization
    # pass, tool #6 (2026-08-16). It was a second, separately-maintained,
    # far less hardened implementation of the exact same action as
    # create_pr (both just run `gh pr create`) — no repo/branch/base
    # identity verification, no no-diff guard, no duplicate-PR check, no
    # approval gate at all. Now registered directly against the already-
    # hardened create_pr_handler below.

    handlers["find_queue"] = find_queue_h
    handlers["find_worker"] = find_worker_h
    handlers["insert_before"] = insert_before_h
    handlers["insert_after"] = insert_after_h
    handlers["delete_block"] = delete_block_h
    handlers["generate_changelog"] = generate_changelog_h
    handlers["summarize_repo"] = summarize_repo_h
    handlers["generate_release_notes"] = generate_release_notes_h
    handlers["read_pdf"] = read_pdf_h
    handlers["read_image"] = read_image_h
    handlers["github_create_pr"] = lambda inp: create_pr_handler(repo_path, inp)

    # ---- Batch 15 handlers ----

    # moved to app/tools/git/tag.py as git_tag_handler —
    # tool_enhance.md productionization pass, tool #22 (2026-08-17).
    def git_tag_h(inp: dict[str, Any]) -> str:
        return git_tag_handler(repo_path, inp)

    # tool_enhance.md productionization pass, tool #150 (2026-09-14) —
    # was a worktree-escape COMMIT-HISTORY DISCLOSURE oracle (`path`
    # never validated, proved live) and a missing chat_agent.py
    # dispatch. Now delegates to the shared, worktree-validated
    # handler.
    def git_log_file_h(inp: dict[str, Any]) -> str:
        return git_log_file_handler(repo_path, inp)

    # moved to app/tools/filesystem/semver_bump.py as semver_bump_handler
    # — tool_enhance.md productionization pass, tool #25 (2026-08-18).
    def semver_bump_h(inp: dict[str, Any]) -> str:
        return semver_bump_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #151 (2026-09-14) —
    # was a missing chat_agent.py dispatch (this tool was never
    # reachable from interactive chat at all, proved live). Now
    # delegates to the shared handler.
    def git_stash_list_h(inp: dict[str, Any]) -> str:
        return git_stash_list_handler(repo_path)

    # tool_enhance.md productionization pass, tool #165 (2026-09-15) —
    # no worktree-escape or injection surface exists (`filter` reaches
    # only a pure in-memory Python string containment check, never a
    # subprocess/shell command); the real fix was a missing
    # chat_agent.py dispatch (this tool was never reachable from
    # interactive chat at all, proved live). Now delegates to the
    # shared handler.
    def list_processes_h(inp: dict[str, Any]) -> str:
        return list_processes_handler(inp)

    # tool_enhance.md productionization pass, tool #164 (2026-09-15) —
    # no worktree-escape or injection surface exists (empty schema,
    # fixed argv lists only); the real fix was a missing
    # chat_agent.py dispatch (this tool was never reachable from
    # interactive chat at all, proved live). Now delegates to the
    # shared handler.
    def list_open_ports_h(inp: dict[str, Any]) -> str:
        return list_open_ports_handler()

    def wait_for_port_h(inp: dict[str, Any]) -> str:
        return wait_for_port_handler(inp)

    # tool_enhance.md productionization pass, tool #126 (2026-08-26) —
    # was a genuine, live SSRF with zero protection (proved live:
    # connected to a real local server on 127.0.0.1). Now delegates to
    # the shared handler, gated by the same _ssrf_denial_reason()
    # guard fetch_url already uses.
    def check_url_status_h(inp: dict[str, Any]) -> str:
        return check_url_status_handler(inp)

    # tool_enhance.md productionization pass, tool #130 (2026-08-26) —
    # was silently broken for any `command` not literally prefixed
    # with the word "python" (unconditionally dropped the first
    # token, destroying the target script's own name for any other
    # input) and had an uncaught crash on a non-numeric `top`. Now
    # delegates to the shared, fixed handler.
    def cpu_profile_h(inp: dict[str, Any]) -> str:
        return cpu_profile_handler(repo_path, inp)

    def zip_files_h(inp: dict[str, Any]) -> str:
        return zip_files_handler(root, repo_path, inp)

    def unzip_files_h(inp: dict[str, Any]) -> str:
        return unzip_files_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/move_file.py — this now calls the shared, hardened move_file_handler()
    def move_file_h(inp: dict[str, Any]) -> str:
        return move_file_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #154 (2026-09-14) —
    # was a worktree-escape SHA-256 HASH DISCLOSURE oracle (`path`
    # never validated, proved live) and a missing chat_agent.py
    # dispatch. Now delegates to the shared, worktree-validated
    # handler.
    def hash_file_h(inp: dict[str, Any]) -> str:
        return hash_file_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #129 (2026-08-26) —
    # was a worktree-escape arbitrary file/directory READ (`root /
    # path` never validated). Now delegates to the shared,
    # worktree-validated handler.
    def count_lines_h(inp: dict[str, Any]) -> str:
        return count_lines_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #173 (2026-09-15) —
    # audited and confirmed already safe (values already routed
    # through _mask_secret_value(), proved live); the real fix was a
    # missing chat_agent.py dispatch. Now delegates to the shared
    # handler.
    def read_env_var_h(inp: dict[str, Any]) -> str:
        return read_env_var_handler(inp)

    # tool_enhance.md productionization pass, tool #163 (2026-09-15) —
    # no worktree-escape or injection surface exists (empty schema);
    # checked and confirmed the implementation already respects its
    # own "names only, never values" safety contract, proved live.
    # The real fix was a missing chat_agent.py dispatch (this tool
    # was never reachable from interactive chat at all, proved live).
    # Now delegates to the shared handler.
    def list_env_vars_h(inp: dict[str, Any]) -> str:
        return list_env_vars_handler()

    # tool_enhance.md productionization pass, tool #135 (2026-09-11) —
    # was a worktree-escape env-variable-NAME disclosure oracle on
    # both `example`/`actual` (`root / ...` never validated) and had
    # an uncaught crash on a real permission error. Now delegates to
    # the shared, worktree-validated handler.
    def env_diff_h(inp: dict[str, Any]) -> str:
        return env_diff_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #158 (2026-09-14) —
    # was a worktree-escape ARBITRARY FILE CONTENT DISCLOSURE oracle
    # (`path` never validated, proved live to disclose real file
    # content from outside the worktree), a flag-collision bug on
    # `query` (same class as tools #5/#32/#148/#149, proved live), and
    # a missing chat_agent.py dispatch. Now delegates to the shared,
    # validated handler.
    def json_query_h(inp: dict[str, Any]) -> str:
        return json_query_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #120 (2026-08-26) —
    # was a worktree-escape arbitrary file READ on both `path` and
    # `schema_path` (`root / ...` never validated). Now delegates to
    # the shared, worktree-validated handler.
    def yaml_validate_h(inp: dict[str, Any]) -> str:
        return yaml_validate_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #159 (2026-09-15) —
    # was a worktree-escape arbitrary file READ on both `path` and
    # `schema_path` (`root / ...` never validated, same bug already
    # fixed for sibling yaml_validate) and a missing chat_agent.py
    # dispatch. The old private `_load_schema_doc`/
    # `_validate_against_schema` closures that used to live here were
    # removed — their logic now lives once, shared, in
    # app/tools/filesystem/json_schema_validation.py. Now delegates to
    # the shared, worktree-validated handler.
    def json_validate_h(inp: dict[str, Any]) -> str:
        return json_validate_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #132 (2026-09-11) —
    # was a worktree-escape arbitrary file READ (`root / path` never
    # validated) and had an uncaught crash on a non-numeric `rows`.
    # Now delegates to the shared, worktree-validated handler.
    def csv_preview_h(inp: dict[str, Any]) -> str:
        return csv_preview_handler(root, repo_path, inp)

    def xml_validate_h(inp: dict[str, Any]) -> str:
        return xml_validate_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #175 (2026-09-15) —
    # was a worktree-escape STRUCTURED FILE CONTENT DISCLOSURE oracle
    # (`path` never validated, proved live) and a missing
    # chat_agent.py dispatch. Now delegates to the shared,
    # worktree-validated handler.
    def read_notebook_h(inp: dict[str, Any]) -> str:
        return read_notebook_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #171 (2026-09-15) —
    # was a worktree-escape STRUCTURED FILE CONTENT DISCLOSURE oracle
    # (`path` never validated, proved live) and a missing
    # chat_agent.py dispatch. Now delegates to the shared,
    # worktree-validated handler.
    def parse_dockerfile_h(inp: dict[str, Any]) -> str:
        return parse_dockerfile_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #170 (2026-09-15) —
    # was a worktree-escape STRUCTURED FILE CONTENT DISCLOSURE oracle
    # (`path` never validated, proved live) and a missing
    # chat_agent.py dispatch. Now delegates to the shared,
    # worktree-validated handler.
    def parse_docker_compose_h(inp: dict[str, Any]) -> str:
        return parse_docker_compose_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #152 (2026-09-14) —
    # existing owner/repo/path validation checked and confirmed
    # already safe (proved live); the real fix was a missing
    # chat_agent.py dispatch (this tool was never reachable from
    # interactive chat at all, proved live). Now delegates to the
    # shared handler.
    def github_inspect_repo_h(inp: dict[str, Any]) -> str:
        return github_inspect_repo_handler(inp)

    # tool_enhance.md productionization pass, tool #169 (2026-09-15) —
    # was a worktree-escape STRUCTURED FILE CONTENT DISCLOSURE oracle
    # (`path` never validated, proved live) and a missing
    # chat_agent.py dispatch. Now delegates to the shared,
    # worktree-validated handler.
    def openapi_inspect_h(inp: dict[str, Any]) -> str:
        return openapi_inspect_handler(root, repo_path, inp)

    # moved to app/tools/filesystem/summarize_output.py as
    # SUMMARIZE_OUTPUT_TOOL / summarize_output_handler() —
    # tool_enhance.md productionization pass, tool #273 (2026-09-18).
    def summarize_output_h(inp: dict[str, Any]) -> str:
        return summarize_output_handler(inp)

    # tool_enhance.md productionization pass, tool #146 (2026-09-14) —
    # was a worktree-escape CLASS/METHOD/FUNCTION-NAME disclosure
    # oracle (`root / file_path` never validated, proved live) and a
    # missing chat_agent.py dispatch. Now delegates to the shared,
    # worktree-validated handler.
    def generate_diagram_h(inp: dict[str, Any]) -> str:
        return generate_diagram_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #137 (2026-09-11) —
    # was a worktree-escape ARBITRARY FILE WRITE (not just a read) on
    # both `path` and `output` (the default-derived `output` also
    # escaped whenever `path` alone was absolute, proved live). Now
    # delegates to the shared, worktree-validated handler.
    def export_markdown_h(inp: dict[str, Any]) -> str:
        return export_markdown_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #141 (2026-09-11) —
    # was a worktree-escape partial SOURCE CODE disclosure oracle
    # (`root / path` never validated; ruff's diagnostic output
    # includes real surrounding source lines, proved live to disclose
    # real code from a file outside the worktree). Now delegates to
    # the shared, worktree-validated handler.
    def find_unused_imports_h(inp: dict[str, Any]) -> str:
        return find_unused_imports_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #134 (2026-09-11) —
    # was a worktree-escape (`directory` reached a subprocess `cwd`
    # unvalidated, proved live via a fake npm script) and a dead
    # `has_npm` variable causing a misleading "up to date" false
    # positive when no package manager was present. Now delegates to
    # the shared, fixed handler.
    def deps_outdated_h(inp: dict[str, Any]) -> str:
        return deps_outdated_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #103 (2026-08-25) — the
    # real fix (this tool was advertised in CHAT_TOOLS but chat_agent.py
    # had ZERO dispatch — same class as tools #4/#6/#22/#25/#33/#44/
    # #45/#46/#48/#100) lives in the shared
    # check_license_compliance_handler(); see that function's own
    # module docstring.
    def check_license_compliance_h(inp: dict[str, Any]) -> str:
        return check_license_compliance_handler()

    # T2-B10 (2026-09-24, GRIDIRON_PARTIAL #331) — see
    # app/tools/execution/check_target_repo_license_compliance.py's own
    # module docstring.
    def check_target_repo_license_compliance_h(inp: dict[str, Any]) -> str:
        return check_target_repo_license_compliance_handler(repo_path, inp)

    # tool_enhance.md productionization pass, tool #166 (2026-09-15) —
    # was a worktree-escape LINE-COUNT-STATISTICS DISCLOSURE oracle
    # (`directory` never validated, proved live) and a missing
    # chat_agent.py dispatch. Now delegates to the shared,
    # worktree-validated handler.
    def loc_stats_h(inp: dict[str, Any]) -> str:
        return loc_stats_handler(root, repo_path, inp)

    def npm_install_h(inp: dict[str, Any]) -> str:
        # tool_enhance.md productionization pass, tool #4 (2026-08-16) —
        # real gap found: `session` is never non-None for any real caller
        # of make_chat_handlers() (grepped every real call site in the
        # repo — none pass one; npm_install isn't in any one-shot agent's
        # allowed_tools either). npm_install/npm_run/pip_install are
        # advertised to the interactive chat agent via CHAT_TOOLS but had
        # NO dispatch in chat_agent.py at all — a real, separate bug,
        # fixed there in this same pass (see that file). Simplified here
        # to state the real constraint plainly instead of dead async
        # plumbing that could never execute.
        return (
            "[BLOCKED] npm_install requires interactive session for safety confirmation"
        )

    # tool_enhance.md productionization pass, tool #54 (2026-08-20) — real
    # gap found: same shape as npm_install_h/pip_install_h right below
    # (no real one-shot caller, grepped; a real side effect — arbitrary
    # script execution). Unlike those two, this handler had NOT been
    # blocked, and its own directory field was never validated either —
    # proved live, a real malicious package.json script placed outside
    # the repo was genuinely executed via this exact handler, with zero
    # confirmation gate anywhere. Brought in line with its own siblings.
    def npm_run_h(inp: dict[str, Any]) -> str:
        return "[BLOCKED] npm_run requires interactive session for safety confirmation"

    def pip_install_h(inp: dict[str, Any]) -> str:
        # tool_enhance.md productionization pass, tool #4 (2026-08-16) —
        # same real gap as npm_install_h above. Re-audited during tool #55
        # (2026-08-20): still correct, no changes needed — see
        # app/tools/execution/pip_install.py's own docstring.
        return (
            "[BLOCKED] pip_install requires interactive session for safety confirmation"
        )

    # tool_enhance.md productionization pass, tool #172 (2026-09-15) —
    # `filter` audited and confirmed already safe (never reaches a
    # subprocess/shell, pure in-memory substring check, proved live);
    # the real fix was a missing chat_agent.py dispatch. Now delegates
    # to the shared handler.
    def pip_list_h(inp: dict[str, Any]) -> str:
        return pip_list_handler(inp)

    # tool_enhance.md productionization pass, tool #131 (2026-08-26) —
    # worktree validation was already correct here; the real fix
    # (chat_agent.py had zero dispatch) lives in the shared handler;
    # see that module's own docstring.
    def create_directory_h(inp: dict[str, Any]) -> str:
        return create_directory_handler(root, repo_path, inp)

    # tool_enhance.md productionization pass, tool #155 (2026-09-14) —
    # was a real SSRF vector including local-file disclosure via the
    # file:// URL scheme (urlopen() genuinely read a real local file's
    # content, proved live via an isolated urllib call — only an
    # accidental crash in unrelated response-formatting code currently
    # prevents it reaching the caller) plus full exposure to internal-
    # network SSRF (no protection at all, unlike sibling tools
    # fetch_url/check_url_status), and a missing chat_agent.py
    # dispatch. Now delegates to the shared handler, gated by the same
    # _ssrf_denial_reason() guard those siblings already use.
    def http_request_h(inp: dict[str, Any]) -> str:
        return http_request_handler(inp)

    # tool_enhance.md productionization pass, tool #122 (2026-08-26) —
    # was a worktree-escape arbitrary file READ (`root / path` never
    # validated). Now delegates to the shared, worktree-validated
    # handler.
    def base64_encode_h(inp: dict[str, Any]) -> str:
        return base64_encode_handler(root, repo_path, inp)

    def template_render_h(inp: dict[str, Any]) -> str:
        return template_render_handler(root, repo_path, inp)

    handlers["git_tag"] = git_tag_h
    handlers["git_log_file"] = git_log_file_h
    handlers["semver_bump"] = semver_bump_h
    handlers["git_stash_list"] = git_stash_list_h
    handlers["list_processes"] = list_processes_h
    handlers["list_open_ports"] = list_open_ports_h
    handlers["wait_for_port"] = wait_for_port_h
    handlers["check_url_status"] = check_url_status_h
    handlers["cpu_profile"] = cpu_profile_h
    handlers["zip_files"] = zip_files_h
    handlers["unzip_files"] = unzip_files_h
    handlers["move_file"] = move_file_h
    handlers["hash_file"] = hash_file_h
    handlers["count_lines"] = count_lines_h
    handlers["read_env_var"] = read_env_var_h
    handlers["list_env_vars"] = list_env_vars_h
    handlers["env_diff"] = env_diff_h
    handlers["json_query"] = json_query_h
    handlers["yaml_validate"] = yaml_validate_h
    handlers["json_validate"] = json_validate_h
    handlers["csv_preview"] = csv_preview_h
    handlers["xml_validate"] = xml_validate_h
    handlers["read_notebook"] = read_notebook_h
    handlers["parse_dockerfile"] = parse_dockerfile_h
    handlers["parse_docker_compose"] = parse_docker_compose_h
    handlers["github_inspect_repo"] = github_inspect_repo_h
    handlers["openapi_inspect"] = openapi_inspect_h
    handlers["generate_diagram"] = generate_diagram_h
    handlers["summarize_output"] = summarize_output_h
    handlers["export_markdown"] = export_markdown_h
    handlers["find_unused_imports"] = find_unused_imports_h
    handlers["deps_outdated"] = deps_outdated_h
    handlers["check_license_compliance"] = check_license_compliance_h
    handlers["check_target_repo_license_compliance"] = (
        check_target_repo_license_compliance_h
    )
    handlers["loc_stats"] = loc_stats_h
    handlers["npm_install"] = npm_install_h
    handlers["npm_run"] = npm_run_h
    handlers["pip_install"] = pip_install_h
    handlers["pip_list"] = pip_list_h
    handlers["create_directory"] = create_directory_h
    handlers["http_request"] = http_request_h
    handlers["base64_encode"] = base64_encode_h
    handlers["template_render"] = template_render_h

    return handlers


# ---------------------------------------------------------------------------
# Day 9 — Fleet Enhancement Dashboard tools
#
# Shared by the 5 self-improvement agents (agent_performance_reviewer,
# agent_debugger, agent_advisor, knowledge_curator, quality_auditor). These
# agents target the Gridiron project's own codebase (settings.fleet_self_repo_path),
# not a user-connected repo.
#
# SCAN phase (autonomous, read-only): fleet_metrics_read, audit_log_read,
# task_history_query (already exists above), memory_search, memory_curate_read,
# submit_enhancement_request — writes a pending row, nothing else happens.
#
# APPLY phase (only after human approval on a specific request):
# memory_curate_write, git_commit_change — stages only the named files, never `-A`.
# ---------------------------------------------------------------------------


# _new_isolated_db_engine() (the local, less-completely-configured
# duplicate of app.db.session.new_isolated_async_engine() — only
# pool_pre_ping=True, missing the explicit pool_size/max_overflow/
# connect_args the canonical helper sets) was removed here as part of
# tool #227's turn (2026-09-17): its last 4 real callers
# (memory_curate_read #223, memory_curate_write #224,
# memory_list_draft_lessons #225, memory_search #227) have all been
# migrated to the canonical helper, one tool at a time across their
# own turns — confirmed via grep that zero real callers remained
# before deleting it. Genuinely dead code, not a backwards-
# compatibility shim to preserve.

# moved to app/tools/agents/fleet_metrics_read.py as
# FLEET_METRICS_READ_TOOL / fleet_metrics_read_handler() —
# tool_enhance.md productionization pass, tool #215 (2026-09-16).
# Real finding: the original body had zero try/except anywhere, so a
# malformed `n` (e.g. "not-a-number") raised an uncaught ValueError
# straight out of the handler. Fixed by moving the numeric coercion
# into its own try/except (TypeError, ValueError).
_FLEET_METRICS_READ_TOOL: dict[str, Any] = FLEET_METRICS_READ_TOOL
fleet_metrics_read = fleet_metrics_read_handler


# moved to app/tools/agents/audit_log_read.py as
# AUDIT_LOG_READ_TOOL / audit_log_read_handler() —
# tool_enhance.md productionization pass, tool #216 (2026-09-17).
# Real finding, same class as tool #215's fleet_metrics_read: the
# original body had zero try/except anywhere, so a malformed `n`
# raised an uncaught ValueError. Fixed by moving the numeric coercion
# into its own try/except (TypeError, ValueError).
_AUDIT_LOG_READ_TOOL: dict[str, Any] = AUDIT_LOG_READ_TOOL
audit_log_read = audit_log_read_handler


# moved to app/tools/agents/capability_gap_scan.py as
# CAPABILITY_GAP_SCAN_TOOL / capability_gap_scan_handler() —
# tool_enhance.md productionization pass, tool #210 (2026-09-16).
# Re-exported under the old names for backward compatibility.
_CAPABILITY_GAP_SCAN_TOOL: dict[str, Any] = CAPABILITY_GAP_SCAN_TOOL
capability_gap_scan = capability_gap_scan_handler


# moved to app/tools/agents/submit_enhancement_request.py as
# SUBMIT_ENHANCEMENT_REQUEST_TOOL / make_submit_enhancement_request_handler()
# — tool_enhance.md productionization pass, tool #212 (2026-09-16).
# Re-exported under the old names for backward compatibility — all 8
# real consumer files keep importing from here unchanged.
_SUBMIT_ENHANCEMENT_REQUEST_TOOL: dict[str, Any] = SUBMIT_ENHANCEMENT_REQUEST_TOOL


# moved to app/tools/agents/memory_search.py as MEMORY_SEARCH_TOOL /
# memory_search_handler() — tool_enhance.md productionization pass,
# tool #227 (2026-09-17). Two real findings, same class already fixed
# on the rest of this memory-tool family (#223-#225): (1) `top_k` and
# `repo_id` coercions happened before the function's own try/except —
# malformed values raised an uncaught ValueError. Fixed by moving both
# inside the guard. (2) used the local `_new_isolated_db_engine()`
# instead of the canonical `app.db.session.new_isolated_async_engine()`
# — fixed for this tool specifically, closing out the full family.
_MEMORY_SEARCH_TOOL: dict[str, Any] = MEMORY_SEARCH_TOOL
memory_search = memory_search_handler


# moved to app/tools/agents/memory_curate_read.py as
# MEMORY_CURATE_READ_TOOL / memory_curate_read_handler() —
# tool_enhance.md productionization pass, tool #223 (2026-09-17). Two
# real findings: (1) `limit = int(inp.get("limit", 20))` happened
# before the function's own try/except, so a malformed limit raised an
# uncaught ValueError — fixed by moving the coercion inside the guard;
# (2) used the local, less-completely-configured
# `_new_isolated_db_engine()` instead of the canonical
# `app.db.session.new_isolated_async_engine()` — fixed for this tool
# specifically (3 other tools below still use the local duplicate,
# deliberately left for their own future turns, matching tool #212's
# precedent).
_MEMORY_CURATE_READ_TOOL: dict[str, Any] = MEMORY_CURATE_READ_TOOL
memory_curate_read = memory_curate_read_handler


# moved to app/tools/agents/memory_list_draft_lessons.py as
# MEMORY_LIST_DRAFT_LESSONS_TOOL / memory_list_draft_lessons_handler()
# — tool_enhance.md productionization pass, tool #225 (2026-09-17).
# Same 2 findings already fixed on sibling tool #223
# (memory_curate_read): (1) `limit = int(inp.get("limit", 20))`
# happened before the function's own try/except, so a malformed limit
# raised an uncaught ValueError — fixed by moving the coercion inside
# the guard; (2) used the local `_new_isolated_db_engine()` instead of
# the canonical `app.db.session.new_isolated_async_engine()` — fixed
# for this tool specifically.
_MEMORY_LIST_DRAFT_LESSONS_TOOL: dict[str, Any] = MEMORY_LIST_DRAFT_LESSONS_TOOL
memory_list_draft_lessons = memory_list_draft_lessons_handler


# moved to app/tools/agents/memory_curate_write.py as
# MEMORY_CURATE_WRITE_TOOL / memory_curate_write_handler() —
# tool_enhance.md productionization pass, tool #224 (2026-09-17). Two
# real findings, worse than sibling tool #223's equivalent ones:
# (1) `row_id = int(inp["id"])` used bare dict indexing AND happened
# before the function's own try/except — a genuinely missing `id` key
# raised an uncaught KeyError, and a malformed `id` value raised an
# uncaught ValueError. Fixed by moving the coercion inside the guard
# and using `.get("id")` for a clean "[ERROR] id is required" message.
# (2) used the local `_new_isolated_db_engine()` instead of the
# canonical `app.db.session.new_isolated_async_engine()` — fixed for
# this tool specifically (2 other tools — memory_search,
# memory_list_draft_lessons — still use the local duplicate,
# deliberately left for their own future turns).
_MEMORY_CURATE_WRITE_TOOL: dict[str, Any] = MEMORY_CURATE_WRITE_TOOL
memory_curate_write = memory_curate_write_handler


# moved to app/tools/agents/memory_promote_lesson.py as
# MEMORY_PROMOTE_LESSON_TOOL / memory_promote_lesson_handler() —
# tool_enhance.md productionization pass, tool #226 (2026-09-17). Real
# finding: `lesson_id = str(inp["lesson_id"])` used bare dict indexing
# before the function's own try/except — a genuinely missing
# lesson_id key raised an uncaught KeyError. Fixed by using
# `.get("lesson_id")` with an explicit presence check for a clean
# "[ERROR] lesson_id is required" message.
_MEMORY_PROMOTE_LESSON_TOOL: dict[str, Any] = MEMORY_PROMOTE_LESSON_TOOL
memory_promote_lesson = memory_promote_lesson_handler


# delegate_to_agent — plan14 Day 4 (#1 Agent-to-Agent Delegation). Real
# invocation, real safety guards (depth/cycle/policy/budget/timeout) — see
# app/agents/delegation.py's own module docstring for the full design.
# Tool spec + handler factory moved to app/tools/agents/delegate.py —
# tool_enhance.md productionization pass, tool #3 (2026-08-15). See that
# module's TOOL PATH MIGRATION REPORT.

# Appended (not inserted into the list literal above) because BUG_FIX_TOOLS
# is defined earlier in this file, before _DELEGATE_TO_AGENT_TOOL exists —
# module-level code runs top-to-bottom once, so mutating the already-built
# list here takes effect for every importer exactly the same as if it had
# been in the original literal.
BUG_FIX_TOOLS.append(_DELEGATE_TO_AGENT_TOOL)


# PROPOSE_SUBTASK_TOOL / make_propose_subtask_handler moved to
# app/tools/agents/propose_subtask.py — tool_enhance.md productionization
# pass, tool #7 (2026-08-16). See that module's TOOL PATH MIGRATION
# REPORT.


# moved to app/tools/git/commit_change.py as
# GIT_COMMIT_CHANGE_TOOL / make_git_commit_change_handler() —
# tool_enhance.md productionization pass, tool #213 (2026-09-16).
# Re-exported under the old name for backward compatibility — all 4
# real consumer files keep importing from here unchanged.
_GIT_COMMIT_CHANGE_TOOL: dict[str, Any] = GIT_COMMIT_CHANGE_TOOL


def _role_prompt_name(rel: str) -> str | None:
    """Returns the role_name if rel is exactly roles/<role_name>.md, else None."""
    p = Path(rel)
    if len(p.parts) == 2 and p.parts[0] == "roles" and p.suffix == ".md":
        return p.stem
    return None


def _propose_and_deploy_role_prompt(
    role_name: str, content: str, agent_name: str
) -> str:
    """Route a role-prompt change through prompt_registry's real
    propose -> submit_for_review -> approve -> deploy lifecycle instead of a
    raw disk write — gap-closure Day 50 (answers.md Q35/Q36/Phase-6 finding
    #8): this shared handler was the one real production path that touched
    roles/*.md files, and it bypassed the built regression-gated approval
    machinery entirely, leaving prompt_registry.deploy() with no real
    caller. The enclosing enhancement_request is already human-approved
    before this APPLY-phase handler ever runs, so auto-advancing through
    review/approval here reuses oversight that already happened rather than
    skipping it — while still real-checking the regression gate before any
    write reaches disk."""
    from app.fleet.prompt_registry import get_prompt_registry
    from app.fleet.regression_detector import DeploymentBlocked

    registry = get_prompt_registry()
    version = registry.propose(role_name, content, proposed_by=agent_name)
    if version.status == "deployed":
        return (
            f"No change: {role_name}.md content already matches the deployed "
            f"version (v{version.version_number})."
        )
    try:
        registry.submit_for_review(version.id)
        registry.approve(version.id, approved_by=f"{agent_name}-post-human-approval")
        deployed = registry.deploy(version.id)
    except DeploymentBlocked as exc:
        return (
            f"[BLOCKED] Regression gate blocked deploying {role_name}.md "
            f"v{version.version_number}: {exc}"
        )
    return (
        f"Deployed {role_name}.md as v{deployed.version_number} via "
        f"prompt_registry (id={deployed.id})."
    )


def make_fleet_apply_handlers(
    repo_path: str, agent_name: str = "fleet_apply"
) -> dict[str, Any]:
    """Shared APPLY-phase handler set for the 4 write-capable fleet-enhancement
    agents (agent_performance_reviewer, agent_debugger, knowledge_curator,
    quality_auditor) — only ever invoked after a human approves a specific
    enhancement request. read_file + write_file + edit_file + run_tests +
    git_commit_change, all scoped to repo_path (settings.fleet_self_repo_path).

    write_file/edit_file targeting roles/<name>.md are routed through
    prompt_registry (see _propose_and_deploy_role_prompt) instead of a raw
    disk write — gap-closure Day 50."""
    base = Path(repo_path)

    # Non-role-prompt branch moved to app/tools/filesystem/write_file.py as
    # write_file_handler — tool_enhance.md productionization pass, tool #12
    # (2026-08-17).
    def write_file_h(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {rel}: {result.reason}"
        role_name = _role_prompt_name(rel)
        if role_name is not None:
            return _propose_and_deploy_role_prompt(
                role_name, str(inp["content"]), agent_name
            )
        return write_file_handler(base, repo_path, inp)

    def edit_file_h(inp: dict[str, Any]) -> str:
        rel = str(inp["path"])
        result = check_path_in_worktree(rel, repo_path)
        if not result.allowed:
            return f"[POLICY DENIED] {rel}: {result.reason}"
        role_name = _role_prompt_name(rel)
        if role_name is not None:
            # Role-prompt content is authoritatively tracked by
            # prompt_registry (its deployed row), which may live outside
            # repo_path — read the current text from there, not `base / rel`.
            from app.fleet.prompt_registry import get_prompt_registry

            deployed = get_prompt_registry().get_deployed(role_name)
            if deployed is None:
                return f"[ERROR] File not found: {rel}"
            text = deployed.content
        else:
            target = base / rel
            if not target.exists():
                return f"[ERROR] File not found: {rel}"
            text = target.read_text(encoding="utf-8")
        old_s, new_s = str(inp["old_string"]), str(inp["new_string"])
        count = text.count(old_s)
        if count == 0:
            return f"[ERROR] old_string not found in {rel}"
        if count > 1:
            return f"[ERROR] old_string appears {count} times in {rel} — must be unique"
        new_text = text.replace(old_s, new_s, 1)
        if role_name is not None:
            return _propose_and_deploy_role_prompt(role_name, new_text, agent_name)
        target.write_text(new_text, encoding="utf-8")
        return f"Edited {rel}"

    def run_tests_h(inp: dict[str, Any]) -> str:
        import shlex as _shlex

        path = str(inp.get("path", "backend/tests/"))
        flags = str(inp.get("flags", ""))
        flags_reason = _shell_metachar_reason(flags, "flags")
        if flags_reason:
            return f"[POLICY DENIED] {flags_reason}"
        # Gap-closure Day 15: no trailing `| tail -50` — a shell pipeline's
        # exit code is the LAST command's (tail always exits 0), which was
        # silently destroying pytest's real exit code before the check
        # below could ever see it. Output truncation is Python-side only.
        # Gap-closure Day 15: `;` after the activation attempt is a POSIX-only
        # separator — under cmd.exe (Windows' subprocess.run(shell=True)
        # default), it isn't a statement separator at all, so a failed
        # `source` (no such builtin on Windows) aborts the whole line before
        # pytest ever runs. `&& ... || true &&` matches
        # make_chat_handlers.run_tests's already-working pattern, which
        # degrades safely on both shells.
        # Fleet APPLY re-runs the PLATFORM's own suite (human-approved
        # change, isolated worktree): it needs the platform's dependencies
        # and database, so it runs on the host with a scrubbed environment
        # (run_trusted_on_host), not in the job sandbox. The worktree has no
        # .venv of its own, so the platform's interpreter is the default.
        repo_py = Path(repo_path) / ".venv" / "bin" / "python"
        py = _shlex.quote(str(repo_py) if repo_py.exists() else sys.executable)
        cmd = f"cd {_shlex.quote(repo_path)} && {_venv_activate_snippet()} && {py} -m pytest {_shlex.quote(path)} {flags} -q --tb=short 2>&1"
        from app.tools.execution.safe_subprocess import run_trusted_on_host

        try:
            r = run_trusted_on_host(
                cmd, shell=True, capture_output=True, text=True, timeout=180
            )
            out = (r.stdout or r.stderr or "(no output)")[-3000:]
            # Gap-closure Day 15 (Stage 1.2, answers.md) — same fix as
            # make_chat_handlers.run_tests above: agent_debugger/
            # agent_performance_reviewer/quality_auditor all map
            # "run_tests" -> "tests_run"/"tests_passed" in their APPLY-mode
            # VerificationConfig; without this, a real failing test run was
            # indistinguishable from a passing one to that flag.
            if r.returncode != 0:
                return f"[ERROR] Tests failed (exit code {r.returncode}):\n{out}"
            return out
        except subprocess.TimeoutExpired:
            return "[ERROR] tests timed out"

    return {
        "read_file": make_read_only_handlers(repo_path)["read_file"],
        "write_file": write_file_h,
        "edit_file": edit_file_h,
        "run_tests": run_tests_h,
        "git_commit_change": make_git_commit_change_handler(repo_path),
    }


FLEET_APPLY_TOOLS = [
    READ_ONLY_TOOLS[0],
    _WRITE_FILE_TOOL_SPEC,
    _EDIT_FILE_TOOL_SPEC,
    _RUN_TESTS_TOOL,
    _GIT_COMMIT_CHANGE_TOOL,
]

# _FLEET_BASH_TOOL + make_scoped_bash_handler moved to
# app/tools/execution/bash.py (tool_enhance.md productionization pass,
# tool #1, 2026-08-15) — imported at the top of this file for backward
# compatibility.
