from . import security
from .. import __version__
from ..config import STORAGE_ARTIFACTS, STORAGE_CLIENTS, STORAGE_MODELS
from ..database.services import DBSessionService, AsyncSession
from ..database.services.client import ClientService
from ..database.services.settings import setup_settings
from ..database.tables import ClientToken
from ..server.services import SecurityService, TokenService

import aiofiles.os
import logging
import platform
import re
import uuid

LOGGER = logging.getLogger(__name__)


class ServerStartup(DBSessionService):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.cs: ClientService = ClientService(session)
        self.ss: SecurityService = SecurityService(session)
        self.ts: TokenService = TokenService(session)

    async def init_directories(self) -> None:
        LOGGER.info('directory initialization')

        await aiofiles.os.makedirs(STORAGE_ARTIFACTS, exist_ok=True)
        await aiofiles.os.makedirs(STORAGE_CLIENTS, exist_ok=True)
        await aiofiles.os.makedirs(STORAGE_MODELS, exist_ok=True)

        LOGGER.info('directory initialization completed')

    async def create_client(self, type: str, ip_address: str = '', system: str = '', node: int | None = None) -> None:
        LOGGER.info(f'creating client {type}')

        if node is None:
            node = uuid.uuid4().int

        node_str: str = str(node)[:12]
        mac_address: str = ':'.join(re.findall('..', f'{node:012x}'[:12]))

        try:
            client_token: ClientToken = await self.ts.generate_client_token(system, mac_address, node_str)

            await self.cs.create_client(
                client_id=client_token.client_id,
                version=__version__,
                public_key='',
                machine_system=system,
                machine_mac_address=mac_address,
                machine_node=node_str,
                ip_address=ip_address,
                type=type
            )
            await self.cs.create_client_token(client_token)

        except ValueError:
            LOGGER.warning(f'client already exists for type={type} ip_address={ip_address} system={system}')
            return

        LOGGER.info(f'client {type} created')

    async def init_security(self) -> None:
        LOGGER.info('setup setting and security keys')
        await setup_settings(self.session)
        await security.generate_keys(self.session)
        LOGGER.info('setup setting and security keys completed')

    async def populate_database(self) -> None:
        await self.create_client(
            'SERVER',
            'localhost',
            platform.system(),
            uuid.getnode(),
        )
        await self.create_client(
            'WORKER',
        )

        await self.session.commit()

    async def startup(self) -> None:
        await self.init_directories()
        await self.init_security()
        await self.populate_database()
