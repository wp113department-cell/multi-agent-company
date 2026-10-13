from backend.app.tools.integrations.web_search import web_search_handler

# Task for the web search tool
task = {
    "query": "Official LangGraph documentation Python"
}

print("=" * 60)
print("TASK:", task["query"])
print("=" * 60)

result = web_search_handler(task)

print("\nSEARCH RESULTS:\n")
print(result)

print("\n" + "=" * 60)

if result.startswith("[ERROR]"):
    print("STATUS: FAILED")
elif "(no results found" in result:
    print("STATUS: NO RESULTS")
else:
    print("STATUS: CHECK RESULTS ABOVE")