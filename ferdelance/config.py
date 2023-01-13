from sqlalchemy.engine import URL
from pydantic import BaseModel
from pytimeparse import parse

from dotenv import load_dotenv

import os

cpu_count = os.cpu_count()

load_dotenv()


class Configuration(BaseModel):
    STANDALONE: bool = 'TRUE' == os.environ.get('STANDALONE', 'False').upper()
    STANDALONE_WORKERS: int = int(os.environ.get('STANDALONE_WORKERS', 1 if cpu_count is None else cpu_count - 1))

    SERVER_MAIN_PASSWORD: str | None = os.environ.get('SERVER_MAIN_PASSWORD', None)
    SERVER_PROTOCOL: str = os.environ.get('SERVER_PROTOCOL', 'http://')
    SERVER_INTERFACE: str = os.environ.get('SERVER_INTERFACE', 'localhost')
    SERVER_PORT: int = int(os.environ.get('SERVER_PORT', 1456))

    WORKER_SERVER_PROTOCOL: str = os.environ.get('WORKER_SERVER_PROTOCOL', SERVER_PROTOCOL)
    WORKER_SERVER_HOST: str = os.environ.get('WORKER_SERVER_HOST', SERVER_INTERFACE)
    WORKER_SERVER_PORT: int = int(os.environ.get('WORKER_SERVER_PORT', SERVER_PORT))

    DB_USER: str | None = os.environ.get('DB_USER', None)
    DB_PASS: str | None = os.environ.get('DB_PASS', None)

    DB_DIALECT: str = os.environ.get('DB_DIALECT', 'postgresql')
    DB_PORT: int = int(os.environ.get('DB_PORT', '5432'))
    DB_HOST: str | None = os.environ.get('DB_HOST', None)

    DB_SCHEMA: str = os.environ.get('DB_SCHEMA', 'ferdelance')

    DB_MEMORY: bool = 'TRUE' == os.environ.get('DB_MEMORY', 'False').upper()

    STORAGE_ARTIFACTS: str = str(os.path.join('.', 'storage', 'artifacts'))
    STORAGE_CLIENTS: str = str(os.path.join('.', 'storage', 'clients'))
    STORAGE_MODELS: str = str(os.path.join('.', 'storage', 'models'))

    FILE_CHUNK_SIZE: int = int(os.environ.get('FILE_CHUNK_SIZE', 4096))

    CLIENT_TOKEN_EXPIRATION = os.environ.get('TOKEN_CLIENT_EXPIRATION', str(parse('90 day')))
    USER_TOKEN_EXPIRATION = os.environ.get('TOKEN_USER_EXPIRATION', str(parse('30 day')))

    def server_url(self) -> str:
        return f"{self.WORKER_SERVER_PROTOCOL}{self.WORKER_SERVER_HOST.rstrip('/')}:{self.WORKER_SERVER_PORT}"

    def db_connection_url(self, sync: bool = False) -> str:
        driver = ''

        if self.DB_MEMORY:
            if not sync:
                driver = '+aiosqlite'

            return f'sqlite{driver}://'

        dialect = self.DB_DIALECT.lower()

        assert self.DB_HOST is not None

        if dialect == 'sqlite':
            if not sync:
                driver = '+aiosqlite'

            # in this case host is an absolute path
            return f'sqlite{driver}:///{self.DB_HOST}'

        if dialect == 'postgresql':
            assert self.DB_USER is not None
            assert self.DB_PASS is not None
            assert self.DB_PORT is not None

            if not sync:
                driver = '+asyncpg'

            return str(URL.create(
                f'postgresql{driver}',
                self.DB_USER,
                self.DB_PASS,
                self.DB_HOST,
                self.DB_PORT,
                self.DB_HOST,
            ))

        raise ValueError(f'dialect {dialect} is not supported')


conf: Configuration = Configuration()

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': True,
    'formatters': {
        'standard': {
            'format': '%(asctime)s %(levelname)8s %(name)32s:%(lineno)-3s %(message)s'
        }
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
            'stream': 'ext://sys.stdout',
        },
        'console_critical': {
            'level': 'ERROR',
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
            'stream': 'ext://sys.stdout',
        },
        'file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'standard',
            'filename': 'ferdelance.log',
            'maxBytes': 100000,
            'backupCount': 5,
        }
    },
    'loggers': {
        '': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'uvicorn': {
            'handlers': ['console_critical', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'aiosqlite': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
