import uvicorn

uvicorn.run("demos.orm.app:app", port=8001, reload=True, reload_dirs=["demos/orm", "src"])
