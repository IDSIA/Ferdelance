from ferdelance.config import config_manager
from ferdelance.exceptions import ConfigError, ErrorClient, UpdateClient
from ferdelance.logging import get_logger
from ferdelance.node.services.scheduling import ScheduleActionService
from ferdelance.node.services.security import SecurityService
from ferdelance.schemas.client import ClientUpdate
from ferdelance.schemas.updates import UpdateData
from ferdelance.shared.actions import Action

from time import sleep

import ray

import json
import requests


LOGGER = get_logger(__name__)


@ray.remote
class Heartbeat:
    def __init__(self, client_id: str, remote_public_key: str) -> None:
        # possible states are: work, exit, update, install
        self.status: Action = Action.INIT

        self.config = config_manager.get()
        self.leave = config_manager.leave()

        self.security_service: SecurityService = SecurityService(remote_public_key)

        if self.config.join.url is None:
            raise ValueError("No remote server available")

        self.remote_url: str = self.config.join.url
        self.remote_public_key: str = remote_public_key

        self.client_id: str = client_id
        self.stop: bool = False

    def _beat(self):
        LOGGER.debug(f"waiting for {self.config.node.heartbeat}")
        sleep(self.config.node.heartbeat)

    def _leave(self) -> None:
        """Send a leave request to the server."""

        headers, payload = self.security_service.create(
            self.client_id,
            "",
            True,
        )

        res = requests.post(
            f"{self.remote_url}/node/leave",
            headers=headers,
            data=payload,
        )

        res.raise_for_status()

        LOGGER.info(f"client left server {self.remote_url}")
        raise ErrorClient()

    def _update(self, content: ClientUpdate) -> UpdateData:
        """Heartbeat command to check for an update from the server."""
        LOGGER.debug("requesting update")

        headers, payload = self.security_service.create(
            self.client_id,
            content.json(),
        )

        res = requests.get(
            f"{self.remote_url}/client/update",
            headers=headers,
            data=payload,
        )

        res.raise_for_status()

        _, res_payload = self.security_service.exc.get_payload(res.content)

        return UpdateData(**json.loads(res_payload))

    def run(self) -> int:
        """Main loop where the client contact the server node for updates.

        :return:
            Exit code to use
        """

        try:
            LOGGER.info("running client")

            if self.leave:
                self._leave()
                return 0

            scheduler = ScheduleActionService(
                self.client_id,
                self.security_service.exc.transfer_private_key(),
                self.config.workdir,
            )

            while self.status != Action.CLIENT_EXIT and not self.stop:
                try:
                    LOGGER.debug("requesting update")

                    update_data = self._update(ClientUpdate(action=self.status.name))

                    LOGGER.debug(f"update: action={update_data.action}")

                    self.status = scheduler.schedule(
                        self.remote_url,
                        self.remote_public_key,
                        update_data,
                        self.config.datasources,
                    )

                    if self.status == Action.CLIENT_UPDATE:
                        raise UpdateClient()

                except UpdateClient as e:
                    raise e

                except ValueError as e:
                    # TODO: discriminate between bad and acceptable exceptions
                    LOGGER.exception(e)

                except requests.HTTPError as e:
                    LOGGER.exception(e)
                    # TODO what to do in this case?

                except requests.exceptions.RequestException as e:
                    LOGGER.error("connection refused")
                    LOGGER.exception(e)
                    # TODO what to do in this case?

                except Exception as e:
                    LOGGER.error("internal error")
                    LOGGER.exception(e)

                    # TODO what to do in this case?
                    raise ErrorClient()

                self._beat()

        except UpdateClient:
            LOGGER.info("update application and dependencies")
            return 1

        except ConfigError as e:
            LOGGER.error("could not complete setup")
            LOGGER.exception(e)
            raise ErrorClient()

        except KeyboardInterrupt:
            LOGGER.info("stopping client")
            self.stop = True

        except Exception as e:
            LOGGER.error("unknown error")
            LOGGER.exception(e)
            raise ErrorClient()

        if self.stop:
            raise ErrorClient()

        return 0
