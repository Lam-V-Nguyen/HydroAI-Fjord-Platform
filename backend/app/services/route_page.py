import os, traceback, msgpack, json
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import SOURCE_FRONTEND, PROJECT_ROOT
# from services import functions

router = APIRouter()
htmls = Jinja2Templates(directory=os.path.normpath(os.path.join(SOURCE_FRONTEND, "htmls")))
print('Route Page', SOURCE_FRONTEND)

# ==================== Routes ====================
# Home page
@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    folder = Jinja2Templates(directory=os.path.dirname(SOURCE_FRONTEND))
    return folder.TemplateResponse(request=request, name="index.html")

# Load widget menu
@router.get("/getWidgetMenu")
def load_widgetMenu(request: Request):
    try: return htmls.TemplateResponse(request=request, name="mainMenu.html")
    except Exception as e:
        print('/getWidgetMenu:\n==============')
        traceback.print_exc()
        return HTMLResponse(f"Error: {e}", status_code=500)