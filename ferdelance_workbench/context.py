from typing import Any
from ferdelance_workbench.exceptions import ServerError
from ferdelance_workbench.artifacts import (
    ClientDetails,
    DataSource,
    Artifact,
    ArtifactStatus,
)
from ferdelance_shared.schemas import (
    WorkbenchJoinRequest,
    WorkbenchJoinData,
    WorkbenchDataSourceList,
    WorkbenchDataSourceIdList,
    WorkbenchClientList,
)
from ferdelance_shared.exchange import Exchange

import json
import logging
import requests
import os

LOGGER = logging.getLogger(__name__)

HOME = os.path.expanduser('~')
DATA_DIR = os.environ.get('DATA_HOME', os.path.join(HOME, '.local', 'share', 'ferdelance'))
CONFIG_DIR = os.environ.get('CONFIG_HOME', os.path.join(HOME, '.config', 'ferdelance'))
CACHE_DIR = os.environ.get('CACHE_HOME', os.path.join(HOME, '.cache', 'ferdelance'))


class Context:

    def __init__(self, server: str, ssh_key_path: str | None = None, generate_keys: bool = True) -> None:
        """Connect to the given server, and establish all the requirements for a secure interaction.

        :param server:
            URL of the server to connect to.
        :param ssh_key:
            Path to an existing SSH private keys on local disk.
        :param generate_keys:
            If True and `ssh_key` is None, then a new SSH key will be generated locally. Otherwise
            if False, the key stored in `HOME/.ssh/rsa_id` will be used.
        """
        self.server: str = server.rstrip('/')

        self.exc: Exchange = Exchange()

        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)

        if ssh_key_path is None:
            if generate_keys:
                self.exc.generate_key()
                self.exc.save_private_key(os.path.join(DATA_DIR, 'rsa_id'))

            else:
                self.exc.load_key(os.path.join(HOME, '.ssh', 'rsa_id'))

        else:
            self.exc.load_key(ssh_key_path)

        wjr = WorkbenchJoinRequest(
            public_key=self.exc.transfer_public_key()
        )

        res = requests.post(
            '/workbench/connect',
            data=json.dumps(wjr.dict())
        )

        res.raise_for_status()

        data = WorkbenchJoinData(**res.json())

        self.workbench_id: str = data.id

        self.exc.set_token(data.token)
        self.exc.set_remote_key(data.public_key)

    def list_clients(self) -> list[str]:
        """List all clients available on the server.

        :raises HTTPError:
            If the return code of the response is not a 2xx type.
        :returns:
            A list of client ids.
        """
        res = requests.get(
            f'{self.server}/workbench/client/list',
            headers=self.exc.headers(),
        )

        res.raise_for_status()

        data = WorkbenchClientList(**self.exc.get_payload(res.content))

        return data.client_ids

    def detail_client(self, client_id: str) -> ClientDetails:
        """List the details of a client.

        :param client_id:
            This is one of the ids returned with the `list_clients()` method.
        :raises HTTPError:
            If the return code of the response is not a 2xx type.
        :returns:
            The details for the given client.
        """
        res = requests.get(
            f'{self.server}/workbench/client/{client_id}',
            headers=self.exc.headers(),
        )

        res.raise_for_status()

        return ClientDetails(**self.exc.get_payload(res.content))

    def list_datasources(self) -> list[str]:
        """List all data sources available.

        :raises HTTPError:
            If the return code of the response is not a 2xx type.
        :returns:
            A list of all datasources available.
        """
        res = requests.get(
            f'{self.server}/workbench/datasource/list/',
            headers=self.exc.headers(),
        )

        res.raise_for_status()

        data = WorkbenchDataSourceIdList(**self.exc.get_payload(res.content))

        return data.datasource_ids

    def datasource_by_id(self, datasource_id: str) -> DataSource:
        """Returns the detail, like metadata, of the given datasource.

        :param datasource_id:
            This is one of the ids returned with the `list_datasources()` method.
        :raises HTTPError:
            If the return code of the response is not a 2xx type.
        :returns:
            The details for the given datasource, with also features.
        """
        res = requests.get(
            f'{self.server}/workbench/datasource/{datasource_id}',
            headers=self.exc.headers(),
        )

        res.raise_for_status()

        return DataSource(**self.exc.get_payload(res.content))

    def datasources_by_name(self, datasource_name: str) -> list[DataSource]:
        """Returns the detail, like metadata, of the datasources associated with the
        given name.

        :param datasource_name:
            This is the name of one or more data sources.
        :raises HTTPError:
            If the return code of the response is not a 2xx type.
        :returns:
            A list with all the details of the datasources with the given name,
            with also the features.
        """
        res = requests.get(
            f'{self.server}/workbench/datasource/name/{datasource_name}',
            headers=self.exc.headers(),
        )

        res.raise_for_status()

        data = WorkbenchDataSourceList(**self.exc.get_payload(res.content))

        return [DataSource(**data.__dict__) for data in data.datasources]

    def submit(self, artifact: Artifact) -> Artifact:
        """Submit the query, model, and strategy and start a training task on the remote server.

        :param artifact:
            Artifact to submit to the server for training.
            This object will be updated with the id assigned by the server.
        :raises HTTPError:
            If the return code of the response is not a 2xx type.
        :returns:
            The same input artifact with an assigned artifact_id.
            If the `ret_status` flag is true, the status of the artifact is also returned.
        """
        res = requests.post(
            f'{self.server}/workbench/artifact/submit',
            headers=self.exc.headers(),
            data=self.exc.create_payload(artifact.dict()),
        )

        res.raise_for_status()

        status = ArtifactStatus(**self.exc.get_payload(res.content))
        artifact.artifact_id = status.artifact_id

        return artifact

    def status(self, artifact: Artifact | ArtifactStatus) -> ArtifactStatus:
        """Poll the server to get an update of the status of the given artifact.

        :param artifact:
            Artifact or ArtifactStatus to get an update for.
        :raises HTTPError:
            If the return code of the response is not a 2xx type.
        :returns:
            An ArtifactStatus object with the status of the artifact on the server.
        """
        if artifact.artifact_id is None:
            raise ValueError('submit first the artifact to the server')

        res = requests.get(
            f'{self.server}/workbench/artifact/status/{artifact.artifact_id}',
            headers=self.exc.headers(),
        )

        res.raise_for_status()

        return ArtifactStatus(**self.exc.get_payload(res.content))

    def get_artifact(self, artifact_id: str) -> Artifact:
        """Get the specified artifact from the server.

        :param artifact_id:
            Artifact to get the model from.
        :raises HTTPError:
            If the return code of the response is not a 2xx type.
        :returns:
            The artifact saved on the server and associated with the given artifact_id.
        """
        res = requests.get(
            f'{self.server}/workbench/artifact/{artifact_id}',
            headers=self.exc.headers(),
        )

        res.raise_for_status()

        return Artifact(**self.exc.get_payload(res.content))

    def get_model(self, artifact: Artifact, path: str = '') -> str:
        """Get the trained and aggregated model from the artifact and save it to disk.

        :param artifact:
            Artifact to get the model from.
        :param path:
            Optional, destination path on disk. If none, a UUID will be used to store the downloaded model.
        :raises HTTPError:
            If the return code of the response is not a 2xx type.
        """
        if artifact.artifact_id is None:
            raise ValueError('submit first the artifact to the server')

        if not path:
            path = f'{artifact.artifact_id}.{artifact.model.name}.AGGREGATED.model'

        with requests.get(
            f'{self.server}/workbench/model/{artifact.artifact_id}',
            headers=self.exc.headers(),
            stream=True,
        ) as res:

            res.raise_for_status()

            self.exc.stream_response_to_file(res, path)

        return path

    def get_partial_model(self, artifact: Artifact, client_id: str, path: str = '') -> str:
        """Get the trained partial model from the artifact and save it to disk.

        :param artifact:
            Artifact to get the model from.
        :param client_id:
            The client_it that trained the partial model.
        :param path:
            Optional, destination path on disk. If none, a UUID will be used to store the downloaded model.
        :raises HTTPError:
            If the return code of the response is not a 2xx type.
        """
        if artifact.artifact_id is None:
            raise ValueError('submit first the artifact to the server')

        if not path:
            path = f'{artifact.artifact_id}.{artifact.model.name}.{client_id}.PARTIAL.model'

        with requests.get(
            f'{self.server}/workbench/model/partial/{artifact.artifact_id}/{client_id}',
            headers=self.exc.headers(),
            stream=True,
        ) as res:

            res.raise_for_status()

            self.exc.stream_response_to_file(res, path)

        return path
