from ferdelance import __version__
from ferdelance.config import conf
from ferdelance.database import get_session, AsyncSession
from ferdelance.schemas.database import ServerModel
from ferdelance.schemas.components import Client
from ferdelance.database.repositories import (
    ModelRepository,
    ComponentRepository,
    JobRepository,
)
from ferdelance.database.tables import (
    Application,
    Artifact,
)
from ferdelance.server.schemas.manager import (
    ManagerUploadClientMetadataRequest,
    ManagerUploadClientResponse,
)

from fastapi import (
    APIRouter,
    Depends,
    UploadFile,
    Response,
    HTTPException,
)

from sqlalchemy import select
from uuid import uuid4

import aiofiles
import hashlib
import logging
import os

LOGGER = logging.getLogger(__name__)


manager_router = APIRouter()

# TODO: add safety checks on who can upload data there


@manager_router.post("/manager/upload/client", response_model=ManagerUploadClientResponse)
async def manager_upload_client(file: UploadFile, session: AsyncSession = Depends(get_session)):
    filename = file.filename
    app_id = str(uuid4())

    LOGGER.info(f"app_id={app_id} uploading new client filename={filename}")

    os.makedirs(conf.STORAGE_CLIENTS, exist_ok=True)

    path = os.path.join(conf.STORAGE_CLIENTS, filename)

    checksum = hashlib.sha256()

    async with aiofiles.open(path, "wb") as out_file:
        while content := await file.read(conf.FILE_CHUNK_SIZE):
            checksum.update(content)
            await out_file.write(content)

    client_app: Application = Application(
        app_id=app_id,
        path=path,
        name=filename,
        version=__version__,
        checksum=checksum.hexdigest(),
    )

    session.add(client_app)
    await session.commit()

    return ManagerUploadClientResponse(
        upload_id=app_id,
        filename=filename,
    )


@manager_router.post("/manager/upload/client/metadata")
async def manager_upload_client_metadata(
    metadata: ManagerUploadClientMetadataRequest, session: AsyncSession = Depends(get_session)
):
    app_id = metadata.upload_id
    LOGGER.info(f"app_id={app_id} updating metadata")

    res = await session.execute(select(Application).where(Application.app_id == app_id).limit(1))
    client_app: Application | None = res.scalar_one_or_none()

    if client_app is None:
        LOGGER.info(f"app_id={app_id} not found in database")
        raise HTTPException(404)

    client_app.active = metadata.active

    if metadata.version:
        client_app.version = metadata.version
    if metadata.name:
        client_app.name = metadata.name
    if metadata.desc:
        client_app.description = metadata.desc

    LOGGER.info(f"app_id={app_id} updating with new metadata")

    await session.commit()


@manager_router.post("/manager/upload/artifact")
async def manager_upload_artifact(file: UploadFile, session: AsyncSession = Depends(get_session)):
    os.makedirs(conf.STORAGE_ARTIFACTS, exist_ok=True)

    path = os.path.join(conf.STORAGE_ARTIFACTS, file.filename)

    async with aiofiles.open(path, "wb") as out_file:
        while content := await file.read(conf.FILE_CHUNK_SIZE):
            await out_file.write(content)

    artifact: Artifact = Artifact(
        version="0.0",
        path=path,
        name=file.filename,
        description="",
    )

    session.add(artifact)
    await session.commit()
    await session.refresh(artifact)

    return Response()


@manager_router.get("/manager/client/list")
async def manager_client_list(session: AsyncSession = Depends(get_session)):
    mr: ComponentRepository = ComponentRepository(session)

    clients: list[Client] = await mr.list_clients()

    return [
        {
            "client_id": m.client_id,
            "active": m.active,
            "ip_address": m.ip_address,
        }
        for m in clients
    ]


@manager_router.get("/manager/client/remove/{client_id}")
async def manager_remove_client(client_id: str, session: AsyncSession = Depends(get_session)):
    # TODO: this endpoint need to be made secure!
    cr: ComponentRepository = ComponentRepository(session)

    LOGGER.info(f"client_id={client_id}: MANAGER request to leave")

    client: Client | None = await cr.get_client_by_id(client_id)

    if client is None:
        raise HTTPException(404)

    await cr.client_leave(client_id)
    await cr.create_event(client_id, "left")


@manager_router.get("/manager/jobs/status")
async def manager_jobs_status(session: AsyncSession = Depends(get_session)):
    jr: JobRepository = JobRepository(session)

    jobs = await jr.get_jobs_all()

    return [
        {
            "artifact_id": j.artifact_id,
            "client_id": j.client_id,
            "status": j.status,
        }
        for j in jobs
    ]


@manager_router.get("/manager/jobs/status/{client_id}")
async def manager_client_job_status(client_id: str, session: AsyncSession = Depends(get_session)):
    jr: JobRepository = JobRepository(session)

    jobs = await jr.get_jobs_for_client(client_id)

    return [
        {
            "artifact_id": j.artifact_id,
            "client_id": j.client_id,
            "status": j.status,
        }
        for j in jobs
    ]


@manager_router.get("/manager/models")
async def manager_models_list(session: AsyncSession = Depends(get_session)):
    mr: ModelRepository = ModelRepository(session)

    model_sessions: list[ServerModel] = await mr.get_model_list()

    return [
        {
            "model_id": m.model_id,
            "artifact_id": m.artifact_id,
            "client_id": m.client_id,
            "aggregated": m.aggregated,
            "creation_time": m.creation_time,
        }
        for m in model_sessions
    ]
