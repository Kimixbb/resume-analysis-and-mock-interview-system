from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def root() -> str:
    return "这只是一个后端测试"

