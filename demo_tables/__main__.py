import uvicorn

uvicorn.run("demo_tables.app:app", port=8002, reload=True, reload_dirs=["demo_tables", "src"])
