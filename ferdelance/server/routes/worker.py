from ferdelance.config import conf
from ferdelance.database import get_session, AsyncSession
from ferdelance.database.data import TYPE_WORKER
from ferdelance.database.repositories import ResultRepository
from ferdelance.schemas.database import Result
from ferdelance.schemas.components import Component
from ferdelance.server.services import JobManagementService
from ferdelance.server.security import check_token
from ferdelance.schemas.artifacts import Artifact, ArtifactStatus

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from sqlalchemy.exc import NoResultFound

import aiofiles
import logging
import os

LOGGER = logging.getLogger(__name__)


worker_router = APIRouter()


async def check_access(component: Component = Depends(check_token)) -> Component:
    try:
        if component.type_name != TYPE_WORKER:
            LOGGER.warning(f"client of type={component.type_name} cannot access this route")
            raise HTTPException(403)

        return component
    except NoResultFound:
        LOGGER.warning(f"worker_id={component.component_id} not found")
        raise HTTPException(403)


@worker_router.post("/worker/artifact", response_model=ArtifactStatus)
async def post_artifact(
    artifact: Artifact, session: AsyncSession = Depends(get_session), worker: Component = Depends(check_access)
):
    LOGGER.info(f"worker_id={worker.component_id}: sent new artifact")

    try:
        jms: JobManagementService = JobManagementService(session)

        status = await jms.submit_artifact(artifact)

        return status

    except ValueError as e:
        LOGGER.error("Artifact already exists")
        LOGGER.exception(e)
        raise HTTPException(403)


@worker_router.get("/worker/artifact/{artifact_id}", response_model=Artifact)
async def get_artifact(
    artifact_id: str, session: AsyncSession = Depends(get_session), worker: Component = Depends(check_access)
):
    LOGGER.info(f"worker_id={worker.component_id}: requested artifact_id={artifact_id}")

    try:
        jms: JobManagementService = JobManagementService(session)
        artifact = await jms.get_artifact(artifact_id)
        return artifact

    except ValueError as e:
        LOGGER.error(f"{e}")
        raise HTTPException(404)


@worker_router.post("/worker/result/{artifact_id}")
async def post_model(
    file: UploadFile,
    artifact_id: str,
    session: AsyncSession = Depends(get_session),
    worker: Component = Depends(check_access),
):
    LOGGER.info(f"worker_id={worker.component_id}: send model for artifact_id={artifact_id}")
    try:
        js: JobManagementService = JobManagementService(session)

        result_db: Result = await js.worker_create_result(artifact_id, worker.component_id)

        async with aiofiles.open(result_db.path, "wb") as out_file:
            while content := await file.read(conf.FILE_CHUNK_SIZE):
                await out_file.write(content)

        await js.aggregation_completed(artifact_id)

    except Exception as e:
        LOGGER.exception(e)
        raise HTTPException(500)


@worker_router.get("/worker/result/{result_id}", response_class=FileResponse)
async def get_result(
    result_id: str, session: AsyncSession = Depends(get_session), worker: Component = Depends(check_access)
):
    LOGGER.info(f"worker_id={worker.component_id}: request result_id={result_id}")
    try:
        rr: ResultRepository = ResultRepository(session)

        result_db: Result = await rr.get_by_id(result_id)

        if not os.path.exists(result_db.path):
            raise NoResultFound()

        return FileResponse(result_db.path)

    except NoResultFound:
        raise HTTPException(404)
