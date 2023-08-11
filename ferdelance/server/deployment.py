from ferdelance.config import Configuration, get_logger
from ferdelance.server.api import api

from ray.serve.handle import RayServeSyncHandle
from ray import serve

LOGGER = get_logger(__name__)


@serve.deployment(
    route_prefix="/",
    name="api",
)
@serve.ingress(api)
class ServerWrapper:
    pass


def start_server(configuration: Configuration, name: str = "Ferdelance_server") -> RayServeSyncHandle | None:
    LOGGER.info(f"Creating server at host={configuration.server.interface} port={configuration.server.port}")

    return serve.run(
        ServerWrapper.bind(),
        host=configuration.server.interface,
        port=configuration.server.port,
        name=name,
    )