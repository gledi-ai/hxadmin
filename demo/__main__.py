import uvicorn

uvicorn.run("demo.app:app", port=8001, reload=True, reload_dirs=["demo", "src"])
