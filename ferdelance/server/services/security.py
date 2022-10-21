from fastapi import Request
from fastapi.responses import StreamingResponse, Response

from ferdelance_shared.decode import decode_from_transfer, decrypt, HybridDecrypter
from ferdelance_shared.encode import encode_to_transfer, encrypt, HybridEncrypter
from ferdelance_shared.generate import (
    public_key_from_bytes,
    private_key_from_bytes,
    RSAPublicKey,
    RSAPrivateKey,
)

from ...database.services import DBSessionService, Session, ClientService
from ...database.settings import KeyValueStore, KEY_TOKEN_EXPIRATION
from ...database.tables import Client, ClientToken

from hashlib import sha256
from time import time
from typing import Any, Iterator
from uuid import uuid4

import aiofiles
import json
import logging

LOGGER = logging.getLogger(__name__)


MAIN_KEY = 'SERVER_MAIN_PASSWORD'
PUBLIC_KEY = 'SERVER_KEY_PUBLIC'
PRIVATE_KEY = 'SERVER_KEY_PRIVATE'


class SecurityService(DBSessionService):
    def __init__(self, db: Session, client_id: str | None) -> None:
        super().__init__(db)

        self.kvs: KeyValueStore = KeyValueStore(db)

        if client_id is not None:
            cs: ClientService = ClientService(db)
            self.client: Client = cs.get_client_by_id(client_id)

    def generate_token(self, system: str, mac_address: str, node: str, client_id: str = '') -> ClientToken:
        """Generates a client token with the data received from the client."""
        if client_id == '':
            client_id = str(uuid4())
            LOGGER.info(f'client_id={client_id}: generating new token')
        else:
            LOGGER.info('generating token for new client')

        ms = round(time() * 1000)

        token_b: bytes = f'{client_id}~{system}${mac_address}£{node}={ms};'.encode('utf8')
        token_b: bytes = sha256(token_b).hexdigest().encode('utf8')
        token: str = sha256(token_b).hexdigest()

        exp_time: int = self.kvs.get_int(KEY_TOKEN_EXPIRATION)

        return ClientToken(
            token=token,
            client_id=client_id,
            expiration_time=exp_time,
        )

    def get_server_public_key(self) -> RSAPublicKey:
        """
        :return:
            The server public key in string format.
        """
        public_bytes: bytes = self.kvs.get_bytes(PUBLIC_KEY)
        return public_key_from_bytes(public_bytes)

    def get_server_public_key_str(self) -> str:
        public_str: str = self.kvs.get_str(PUBLIC_KEY)
        return encode_to_transfer(public_str)

    def get_server_private_key(self) -> RSAPrivateKey:
        """
        :param db:
            Current session to the database.
        :return:
            The server public key in string format.
        """
        private_bytes: bytes = self.kvs.get_bytes(PRIVATE_KEY)
        return private_key_from_bytes(private_bytes)

    def get_client_public_key(self) -> RSAPublicKey:
        key_bytes: bytes = decode_from_transfer(self.client.public_key).encode('utf8')
        public_key: RSAPublicKey = public_key_from_bytes(key_bytes)
        return public_key

    def server_encrypt(self, content: str) -> str:
        client_public_key: RSAPublicKey = self.get_client_public_key()
        return encrypt(client_public_key, content)

    def server_decrypt(self, content: str) -> str:
        server_private_key: RSAPrivateKey = self.get_server_private_key()
        return decrypt(server_private_key, content)

    def server_encrypt_content(self, content: str) -> bytes:
        client_public_key: RSAPublicKey = self.get_client_public_key()
        enc = HybridEncrypter(client_public_key)
        return enc.encrypt(content)

    def server_encrypt_response(self, content: dict[str, Any]) -> Response:
        return Response(content=self.server_encrypt_content(json.dumps(content)))

    def server_decrypt_content(self, content: bytes) -> str:
        server_private_key: RSAPrivateKey = self.get_server_private_key()
        enc = HybridDecrypter(server_private_key)
        return enc.decrypt(content)

    def server_decrypt_json_content(self, content: bytes) -> dict[str, Any]:
        return json.loads(self.server_decrypt_content(content))

    def server_stream_encrypt_file(self, path: str) -> StreamingResponse:
        """Used to stream encrypt data from a file, using less memory."""
        client_public_key: RSAPublicKey = self.get_client_public_key()

        enc = HybridEncrypter(client_public_key)

        return StreamingResponse(
            enc.encrypt_file_to_stream(path),
            media_type='application/octet-stream'
        )

    async def server_stream_decrypt_file(self, request: Request, path: str) -> str:
        """Used to stream decrypt data to a file, using less memory."""
        private_key: RSAPrivateKey = self.get_server_private_key()

        dec = HybridDecrypter(private_key)

        async with aiofiles.open(path, 'wb') as f:
            await f.write(dec.start())
            async for content in request.stream():
                await f.write(dec.update(content))
            await f.write(dec.end())

        return dec.get_checksum()

    def server_stream_encrypt(self, content: str) -> Iterator[bytes]:
        """Used to encrypt small data that can be kept in memory."""
        public_key = self.get_client_public_key()

        enc = HybridEncrypter(public_key)

        return enc.encrypt_to_stream(content)

    async def server_stream_decrypt(self, request: Request) -> tuple[str, str]:
        """Used to decrypt small data that can be kept in memory."""
        private_key: RSAPrivateKey = self.get_server_private_key()

        dec = HybridDecrypter(private_key)

        data: bytearray = bytearray()
        data.extend(dec.start())
        async for content in request.stream():
            data.extend(dec.update(content))
        data.extend(dec.end())

        return data.decode(dec.encoding), dec.get_checksum()