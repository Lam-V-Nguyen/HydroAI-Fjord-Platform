import uvicorn, os, sys
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
    

# Import internally backend modules
from config import SOURCE_BACKEND, SOURCE_FRONTEND, lifespan
from services import route_page, project_manager, data_download, \
    grid_preparation, hyd_functions, process_manager, sim_manager, \
    waq_funtions
    # flow_preparation
# , wq_process, \
#     run_simulation, flow_preparation

app = FastAPI(lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Mount common static files for Mobirise (frontend)
app.mount("/src_frontend", StaticFiles(directory=SOURCE_FRONTEND), name="src_frontend")
app.mount("/src_backend", StaticFiles(directory=SOURCE_BACKEND), name="src_backend")

# Mount routes
all_routers = [
    route_page.router, project_manager.router, data_download.router, 
    grid_preparation.router, hyd_functions.router, process_manager.router,
    sim_manager.router, waq_funtions.router, 
    # flow_preparation.router
]
for router in all_routers:
    app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload_dirs=['.'], reload=True) # Remove reload=True for production