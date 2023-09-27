from fastapi import FastAPI, HTTPException

from app.routes.main import main_router

app = FastAPI(openapi_url="/pride/archive/xiview/xi-converter/api/openapi.json", docs_url="/pride/archive/xiview/xi-converter/api/docs")


app.include_router(main_router, prefix="/pride/archive/xiview/xi-converter")
