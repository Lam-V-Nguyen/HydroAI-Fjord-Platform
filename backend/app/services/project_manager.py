import traceback, asyncio, os, shutil, json, msgpack
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from config import PROJECT_ROOT
from services import functions
import numpy as np


router = APIRouter()

@router.post("/auth_check")
async def auth_check(user=Depends(functions.basic_auth)):
    output = 'ok' if user == 'admin' else 'error'
    return {"user": user, "output": output}