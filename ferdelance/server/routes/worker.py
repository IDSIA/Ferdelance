from ferdelance.config import conf
from ferdelance.database import get_session, AsyncSession
from ferdelance.database.data import TYPE_WORKER
from ferdelance.schemas.components import Component
from ferdelance.schemas.database import Result
from ferdelance.schemas.errors import TaskError
from ferdelance.schemas.worker import TaskAggregationParameters
from ferdelance.server.security import check_token
from ferdelance.server.services import WorkerService

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from sqlalchemy.exc import NoResultFound

import aiofiles
import json
import logging

LOGGER = logging.getLogger(__name__)


worker_router = APIRouter(prefix="/worker")


async def check_access(component: Component = Depends(check_token)) -> Component:
    try:
        if component.type_name != TYPE_WORKER:
            LOGGER.warning(f"client of type={component.type_name} cannot access this route")
            raise HTTPException(403)

        return component
    except NoResultFound:
        LOGGER.warning(f"worker_id={component.id} not found")
        raise HTTPException(403)


@worker_router.get("/")
async def worker_home():
    return "Worker 🔨"


@worker_router.get("/task/{job_id}", response_model=TaskAggregationParameters)
async def worker_get_task(
    job_id: str, session: AsyncSession = Depends(get_session), worker: Component = Depends(check_access)
):
    LOGGER.info(f"worker_id={worker.id}: requested job_id={job_id}")

    ws: WorkerService = WorkerService(session, worker)

    try:
        task = await ws.get_task(job_id)

        return task

    except ValueError as e:
        LOGGER.error(f"{e}")
        raise HTTPException(404)


@worker_router.post("/result/{job_id}")
async def worker_post_result(
    file: UploadFile,
    job_id: str,
    session: AsyncSession = Depends(get_session),
    worker: Component = Depends(check_access),
):
    LOGGER.info(f"worker_id={worker.id}: send result for job_id={job_id}")

    ws: WorkerService = WorkerService(session, worker)

    try:
        result: Result = await ws.aggregation_completed(job_id)

        async with aiofiles.open(result.path, "wb") as out_file:
            while content := await file.read(conf.FILE_CHUNK_SIZE):
                await out_file.write(content)

        await ws.check_next_iteration(job_id)

    except Exception as e:
        LOGGER.error(f"worker_id={worker.id}: could not save result to disk for job_id={job_id}")
        LOGGER.exception(e)
        raise HTTPException(500)


@worker_router.post("/error")
async def worker_post_error(
    error: TaskError,
    session: AsyncSession = Depends(get_session),
    worker: Component = Depends(check_access),
):
    LOGGER.warn(f"worker_id={worker.id}: job_id={error.job_id} in error={error.message}")

    ws: WorkerService = WorkerService(session, worker)

    try:
        result = await ws.aggregation_failed(error)

        async with aiofiles.open(result.path, "w") as out_file:
            content = json.dumps(error.dict())
            await out_file.write(content)

    except Exception as e:
        LOGGER.error(f"worker_id={worker.id}: could not save result to disk for job_id={error.job_id}")
        LOGGER.exception(e)
        raise HTTPException(500)


@worker_router.get("/result/{result_id}", response_class=FileResponse)
async def worker_get_result(
    result_id: str, session: AsyncSession = Depends(get_session), worker: Component = Depends(check_access)
):
    LOGGER.info(f"worker_id={worker.id}: request result_id={result_id}")

    ws: WorkerService = WorkerService(session, worker)

    try:
        result = await ws.get_result(result_id)

        return FileResponse(result.path)

    except NoResultFound as e:
        LOGGER.exception(e)
        raise HTTPException(404)
