from typing import List

import pandas as pd

from ....database import DataBase
from ....database.schemas import Job
from ....database.services import JobService
from ...visualization import show_many


async def list_jobs(artifact_id: str | None = None, client_id: str | None = None) -> List[Job]:
    """Print and return Job List, with or without filters on ARTIFACT_ID, client_id

    Args:
        artifact_id (str, optional): Filter by artifact. Defaults to None.
        client_id (str, optional): Filter by client. Defaults to None.

    Returns:
        List[Job]: List of Job objects
    """

    #

    db = DataBase()

    async with db.async_session() as session:

        js = JobService(session)

        if artifact_id is not None:
            jobs: List[Job] = await js.get_jobs_for_artifact(artifact_id)
        elif client_id is not None:
            jobs: List[Job] = await js.get_jobs_for_client(client_id)
        else:
            jobs: List[Job] = await js.get_jobs_all()

        show_many(jobs)

        return jobs