import uvicorn

uvicorn.run("demos.tables.app:app", port=8002, reload=True, reload_dirs=["demos/tables", "src"])
