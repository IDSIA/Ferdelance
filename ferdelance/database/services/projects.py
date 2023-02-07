from ferdelance.database.services.core import AsyncSession, DBSessionService
from ferdelance.database.services.tokens import TokenService
from ferdelance.database.tables import (
    DataSource as DataSourceDB,
    Project as ProjectDB,
)
from ferdelance.schemas.projects import (
    Metadata,
    Project,
    BaseProject,
    AggregatedDataSource,
)

from sqlalchemy import select
from sqlalchemy.exc import NoReferenceError
from sqlalchemy.orm import selectinload

import uuid


def simpleView(project: ProjectDB) -> BaseProject:
    return BaseProject(
        project_id=project.project_id,
        name=project.name,
        creation_time=project.creation_time,
        token=project.token,
        valid=project.valid,
        active=project.active,
    )


def aggregate_datasource(datasources: list[DataSourceDB]) -> AggregatedDataSource:
    ds = AggregatedDataSource()

    return ds


def view(project: ProjectDB) -> Project:
    return Project(
        project_id=project.project_id,
        name=project.name,
        creation_time=project.creation_time,
        token=project.token,
        valid=project.valid,
        active=project.active,
        n_clients=len(set([ds.component_id for ds in project.datasources])),
        n_datasources=len(project.datasources),
        data=aggregate_datasource(project.datasources),
    )


class ProjectService(DBSessionService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

        self.ts: TokenService = TokenService(session)

    async def create(self, name: str = "", token: str | None = None) -> str:

        if token is None:
            token = await self.ts.project_token(name)

        res = await self.session.scalars(select(ProjectDB).where(ProjectDB.token == token))
        p = res.one_or_none()

        if p is not None:
            raise ValueError("A project with the given token already exists")

        project = ProjectDB(
            project_id=str(uuid.uuid4()),
            name=name,
            token=token,
        )

        self.session.add(project)
        await self.session.commit()

        return token

    async def add_datasource(self, datasource_id: str, project_id: str) -> None:
        """Can raise ValueError."""
        try:
            res = await self.session.scalars(select(DataSourceDB).where(DataSourceDB.datasource_id == datasource_id))
            ds: DataSourceDB = res.one()

            res = await self.session.scalars(select(ProjectDB).where(ProjectDB.project_id == project_id))
            p: ProjectDB = res.one()

            p.datasources.append(ds)

            self.session.add(p)
            await self.session.commit()

        except NoReferenceError:
            raise ValueError()

    async def add_datasources_from_metadata(self, metadata: Metadata) -> None:
        for mdds in metadata.datasources:

            res = await self.session.scalars(
                select(DataSourceDB).where(DataSourceDB.datasource_id == mdds.datasource_id)
            )
            ds: DataSourceDB = res.one()

            if not mdds.tokens:
                continue

            res = await self.session.scalars(select(ProjectDB.project_id).filter(ProjectDB.token.in_(mdds.tokens)))
            project_ids: list[str] = list(res.all())

            if not project_ids:
                # TODO: should this be an error?
                continue

            for project_id in project_ids:
                res = await self.session.scalars(
                    select(ProjectDB)
                    .where(ProjectDB.project_id == project_id)
                    .options(selectinload(ProjectDB.datasources))
                )
                p: ProjectDB = res.one()

                p.datasources.append(ds)
                self.session.add(p)

            await self.session.commit()

    async def get_project_list(self) -> list[BaseProject]:
        res = await self.session.execute(select(ProjectDB))
        project_db_list = res.scalars().all()
        return [simpleView(p) for p in project_db_list]

    async def get_by_id(self, project_id: str) -> Project:
        """Can raise NoResultsException."""
        res = await self.session.scalars(select(ProjectDB).where(ProjectDB.project_id == project_id))

        return view(res.one())

    async def get_by_token(self, token: str) -> Project:
        """Can raise NoResultsException."""
        res = await self.session.scalars(
            select(ProjectDB).where(ProjectDB.token == token).options(selectinload(ProjectDB.datasources))
        )

        return view(res.one())
