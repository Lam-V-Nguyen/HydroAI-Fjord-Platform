import os, json, chardet, asyncio, stat, time, re, shapely, shutil, base64
from config import ALLOWED_USERS
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi import Depends, HTTPException, status
from redis.asyncio.lock import Lock
from scipy.spatial import cKDTree
from scipy.ndimage import distance_transform_edt, gaussian_filter
from config import PROJECT_ROOT
from uuid import uuid4
import numpy as np, xarray as xr, pandas as pd
import geopandas as gpd, dask.array as da
from services import constants

variablesNames = constants.variablesNames
units = constants.units

def encoding_detect(file_path: str) -> str:
    """Detect the encoding of a file."""
    encoding = 'utf-8'
    if not os.path.exists(file_path) or not os.path.isfile(file_path): return encoding
    with open(file_path, 'rb') as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        encoding = result['encoding']
    return encoding

USERS = json.load(open(ALLOWED_USERS, "r", encoding=encoding_detect(ALLOWED_USERS)))

def basic_auth(credentials: HTTPBasicCredentials=Depends(HTTPBasic())):
    username, password = credentials.username, credentials.password
    if username not in USERS or USERS[username] != password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authorized", headers={"WWW-Authenticate": "Basic"}
        )
    return username