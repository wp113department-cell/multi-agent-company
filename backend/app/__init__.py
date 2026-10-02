# Production audit 09: every process that imports the app (API server, queue
# workers, scripts, tests) gets the fleet-wide daily LLM spend cap installed
# on the Anthropic SDK before any client is created. See fleet/spend_guard.py.
try:
    from app.fleet.spend_guard import install as _install_spend_guard

    _install_spend_guard()
except Exception as _exc:  # never block import; the failure is logged loudly
    import logging

    logging.getLogger(__name__).error("Spend guard install failed: %s", _exc)
