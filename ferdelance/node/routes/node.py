from ferdelance.const import TYPE_NODE, TYPE_CLIENT
from ferdelance.logging import get_logger
from ferdelance.node.middlewares import EncodedAPIRoute, SessionArgs, session_args, valid_session_args, ValidSessionArgs
from ferdelance.node.services import NodeService
from ferdelance.schemas.components import dummy
from ferdelance.schemas.metadata import Metadata
from ferdelance.schemas.node import JoinData, NodeJoinRequest, ServerPublicKey
from ferdelance.shared.checksums import str_checksum
from ferdelance.shared.decode import decode_from_transfer

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.exc import SQLAlchemyError, NoResultFound

LOGGER = get_logger(__name__)


node_router = APIRouter(prefix="/node", route_class=EncodedAPIRoute)


async def allow_access(identity: ValidSessionArgs = Depends(valid_session_args)) -> ValidSessionArgs:
    try:
        if identity.component.type_name not in (TYPE_CLIENT, TYPE_NODE):
            LOGGER.warning(
                f"component_id={identity.component.id}: type={identity.component.type_name} cannot access this router"
            )
            raise HTTPException(403, "Access Denied")

        return identity
    except NoResultFound:
        LOGGER.warning(f"component_id={identity.component.id}: not found")
        raise HTTPException(403, "Access Denied")


@node_router.get("/")
async def node_home():
    return "Node 🏙"


@node_router.get("/key", response_model=ServerPublicKey)
async def node_get_public_key(
    args: SessionArgs = Depends(session_args),
):
    pk = args.security_service.get_server_public_key()

    return ServerPublicKey(public_key=pk)


@node_router.post("/join", response_model=JoinData)
async def node_join(
    data: NodeJoinRequest,
    args: SessionArgs = Depends(session_args),
) -> JoinData:
    LOGGER.info("new component joining")

    ns: NodeService = NodeService(args.session, dummy)

    try:
        data_to_sign = f"{data.id}:{data.public_key}"

        data.public_key = decode_from_transfer(data.public_key)
        await args.security_service.setup(data.public_key)

        args.security_service.exc.verify(data_to_sign, data.signature)
        checksum = str_checksum(data_to_sign)

        if data.checksum != checksum:
            raise ValueError("Checksum failed")

        return await ns.connect(data, args.ip_address)

    except SQLAlchemyError as e:
        LOGGER.exception(e)
        LOGGER.exception("Database error")
        raise HTTPException(500, "Internal error")

    except ValueError as e:
        LOGGER.exception(e)
        raise HTTPException(403, "Invalid data")

    except Exception as e:
        LOGGER.exception(e)
        raise HTTPException(403, "Invalid data")


@node_router.post("/leave")
async def node_leave(
    args: ValidSessionArgs = Depends(allow_access),
) -> None:
    """API for existing client to be removed"""
    LOGGER.info(f"component_id={args.component.id}: request to leave")

    ns: NodeService = NodeService(args.session, args.component)

    await ns.leave()


@node_router.post("/metadata", response_model=Metadata)
async def node_metadata(
    metadata: Metadata,
    args: ValidSessionArgs = Depends(allow_access),
):
    """Endpoint used by a client to send information regarding its metadata. These metadata includes:
    - data source available
    - summary (source, data type, min value, max value, standard deviation, ...) of features available
      for each data source
    """
    LOGGER.info(f"component_id={args.component.id}: update metadata request")

    ns: NodeService = NodeService(args.session, args.component)

    return await ns.metadata(metadata)


@node_router.put("/add")
async def node_update_add(
    args: ValidSessionArgs = Depends(allow_access),
):
    LOGGER.info(f"component_id={args.component.id}: adding new node")

    ns: NodeService = NodeService(args.session, args.component)

    # TODO


@node_router.put("/remove")
async def node_update_remove(
    args: ValidSessionArgs = Depends(allow_access),
):
    LOGGER.info(f"component_id={args.component.id}: removing node")

    ns: NodeService = NodeService(args.session, args.component)

    # TODO


@node_router.put("/metadata")
async def node_update_metadata(
    args: ValidSessionArgs = Depends(allow_access),
):
    LOGGER.info(f"component_id={args.component.id}: updating metadata")

    ns: NodeService = NodeService(args.session, args.component)

    # TODO
