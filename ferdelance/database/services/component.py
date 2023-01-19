from ferdelance.database.schemas import Component, Client, Token
from ferdelance.database.tables import (
    Component as ComponentDB,
    Event,
    Token as TokenDB,
    ComponentType,
)
from ferdelance.database.services.core import AsyncSession, DBSessionService
from ferdelance.database.services.tokens import TokenService
from ferdelance.database.data import TYPE_CLIENT

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound

import logging

LOGGER = logging.getLogger(__name__)


def view(component: ComponentDB) -> Component:
    return Component(**component.__dict__)


def viewClient(component: ComponentDB) -> Client:
    return Client(**component.__dict__)


def viewToken(token: TokenDB) -> Token:
    return Token(**token.__dict__)


class ComponentService(DBSessionService):
    """Service used to manage components."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

        self.ts: TokenService = TokenService(session)

    async def create_types(self, type_names: list[str]):
        dirty: bool = False

        for type_name in type_names:
            try:
                res = await self.session.execute(select(ComponentType).where(ComponentType.type == type_name).limit(1))
                res.scalar_one()
            except NoResultFound:
                tn = ComponentType(type=type_name)
                self.session.add(tn)
                dirty = True

        if dirty:
            await self.session.commit()

    async def create_client(
        self,
        version: str,
        public_key: str,
        machine_system: str,
        machine_mac_address: str,
        machine_node: str,
        ip_address: str,
    ) -> tuple[Client, Token]:
        LOGGER.info(
            f"creating new type={TYPE_CLIENT} version={version} mac_address={machine_mac_address} node={machine_node}"
        )

        res = await self.session.execute(
            select(ComponentDB.component_id)
            .where(
                (ComponentDB.machine_mac_address == machine_mac_address) | (ComponentDB.machine_node == machine_node)
            )
            .limit(1)
        )

        existing_id: ComponentDB | None = res.scalar_one_or_none()

        if existing_id is not None:
            LOGGER.warning(f"A {TYPE_CLIENT} already exists with component_id={existing_id}")
            raise ValueError("Client already exists")

        token: TokenDB = await self.ts.generate_client_token(
            system=machine_system,
            mac_address=machine_mac_address,
            node=machine_node,
        )

        component = ComponentDB(
            component_id=token.component_id,
            version=version,
            public_key=public_key,
            machine_system=machine_system,
            machine_mac_address=machine_mac_address,
            machine_node=machine_node,
            ip_address=ip_address,
            type=TYPE_CLIENT,
        )

        self.session.add(component)

        await self.ts.create_token(token)
        await self.session.commit()
        await self.session.refresh(component)

        return viewClient(component), viewToken(token)

    async def create(self, type_name: str, public_key: str) -> tuple[Component, Token]:
        LOGGER.info(f"creating new component type={type_name}")

        res = await self.session.execute(
            select(ComponentDB.component_id).where(ComponentDB.public_key == public_key).limit(1)
        )
        existing_user_id: ComponentDB | None = res.scalar_one_or_none()

        if existing_user_id is not None:
            LOGGER.warning(f"user_id={existing_user_id}: user already exists")
            raise ValueError("User already exists")

        token: TokenDB = await self.ts.generate_token()

        component = ComponentDB(
            component_id=token.component_id,
            public_key=public_key,
            type=type_name,
        )

        self.session.add(component)

        await self.ts.create_token(token)
        await self.session.commit()
        await self.session.refresh(component)

        return view(component), viewToken(token)

    async def update_client(self, client_id: str, version: str = "") -> None:
        if not version:
            LOGGER.warning("cannot update a version with an empty string")
            return

        client: ComponentDB = await self.session.scalar(
            select(ComponentDB).where(ComponentDB.component_id == client_id)
        )
        client.version = version

        await self.session.commit()

        LOGGER.info(f"client_id={client_id}: updated client version to {version}")

    async def client_leave(self, client_id: str) -> None:
        await self.invalidate_tokens(client_id)

        client: ComponentDB = await self.session.scalar(
            select(ComponentDB).where(ComponentDB.component_id == client_id)
        )
        client.active = False
        client.left = True

        await self.session.commit()

    async def get_by_id(self, component_id: str) -> Component:
        """Can raise NoResultFound"""
        res = await self.session.execute(select(ComponentDB).where(ComponentDB.component_id == component_id))
        return view(res.scalar_one())

    async def get_client_by_id(self, component_id: str) -> Client:
        """Can raise NoResultFound"""
        res = await self.session.execute(select(ComponentDB).where(ComponentDB.component_id == component_id))
        return viewClient(res.scalar_one())

    async def get_by_key(self, public_key: str) -> Component:
        """Can raise NoResultFound"""
        res = await self.session.execute(select(ComponentDB).where(ComponentDB.public_key == public_key))

        component: ComponentDB = res.scalar_one()

        return view(component)

    async def get_by_token(self, token: str) -> Component:
        """Can raise NoResultFound"""
        res = await self.session.execute(
            select(ComponentDB)
            .join(TokenDB, ComponentDB.component_id == TokenDB.token_id)
            .where(TokenDB.token == token)
        )

        component: ComponentDB = res.scalar_one()

        return view(component)

    async def list_all(self) -> list[Component]:
        res = await self.session.scalars(select(ComponentDB))
        return [view(c) for c in res.all()]

    async def list_clients(self):
        res = await self.session.scalars(select(ComponentDB).where(ComponentDB.type == TYPE_CLIENT))
        return [viewClient(c) for c in res]

    async def invalidate_tokens(self, component_id: str) -> None:
        await self.ts.invalidate_tokens(component_id)

    async def update_client_token(self, client: Client) -> Token:
        token = await self.ts.update_client_token(
            client.machine_system,
            client.machine_mac_address,
            client.machine_node,
            client.component_id,
        )
        return viewToken(token)

    async def get_component_id_by_token(self, token_str: str) -> str:
        res = await self.session.scalars(select(TokenDB).where(TokenDB.token == token_str))
        token: TokenDB = res.one()

        return str(token.component_id)

    async def get_token_by_token(self, token: str) -> Token:
        """Can raise NoResultFound"""
        res = await self.session.execute(select(TokenDB).where(TokenDB.token == token))
        return res.scalar_one()

    async def get_token_by_component_id(self, client_id: str) -> Token:
        """Can raise NoResultFound"""
        res = await self.session.execute(
            select(TokenDB).where(TokenDB.component_id == client_id, TokenDB.valid == True)
        )
        return res.scalar_one()

    async def get_token_by_client_type(self, client_type: str) -> str | None:
        # TODO: remove this
        client_token: TokenDB | None = await self.session.scalar(
            select(TokenDB)
            .join(ComponentDB, ComponentDB.component_id == TokenDB.component_id)
            .where(ComponentDB.type == client_type)
            .limit(1)
        )

        if client_token is None:
            return None

        return str(client_token.token)

    async def create_event(self, component_id: str, event: str) -> Event:
        LOGGER.debug(f'component_id={component_id}: creating new event="{event}"')

        session_event = Event(component_id=component_id, event=event)

        self.session.add(session_event)
        await self.session.commit()
        await self.session.refresh(session_event)

        return session_event

    async def get_events(self, component_id: str) -> list[Event]:
        res = await self.session.scalars(select(Event).where(Event.component_id == component_id))
        return res.all()
