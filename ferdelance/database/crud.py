from sqlalchemy.orm import Session
from .tables import Client, ClientEvent, ClientToken

import os
import logging

LOGGER = logging.getLogger(__name__)


def create_client(db: Session, client: Client) -> Client:
    LOGGER.info(f'creating new client with version={client.version} mac_address={client.machine_mac_address} node={client.machine_node}')

    existing_client_id = (
        db.query(Client.client_id)
            .filter(
                (Client.machine_mac_address == client.machine_mac_address) |
                (Client.machine_node == client.machine_node)
            )
            .first()
    )
    if existing_client_id is not None:
        LOGGER.warning(f'client already exists with id {existing_client_id}')
        raise ValueError('Client already exists')

    db.add(client)
    db.commit()
    db.refresh(client)

    return client


def get_client_by_client_id(db: Session, client_id: str) -> Client:
    return db.query(Client).filter(Client.client_id == client_id).first()


def get_client_by_token(db: Session, token: str) -> Client:
    return db.query(Client)\
        .join(ClientToken, Client.client_id == ClientToken.token_id)\
        .filter(ClientToken.token == token)\
        .first()


def create_client_token(db: Session, token: ClientToken) -> ClientToken:
    LOGGER.info(f'creating new token for client={token.client_id}')

    existing_client_id = db.query(ClientToken.client_id).filter(ClientToken.token == token.token).first()

    if existing_client_id is not None:
        LOGGER.warning(f'token already exists for client_id {existing_client_id}')
        # TODO: check if we have more strong condition for this
        return

    db.add(token)
    db.commit()
    db.refresh(token)

    return token


def get_client_id_by_token(db: Session, token: str) -> str:
    return db.query(ClientToken.client_id).filter(ClientToken.token == token).first()


def get_client_token_by_token(db: Session, token: str) -> ClientToken:
    return db.query(ClientToken).filter(ClientToken.token == token).first()


def get_client_token_by_client_id(db: Session, client_id: str) -> ClientToken:
    return db.query(ClientToken).filter(ClientToken.client_id == client_id).first()


def create_client_event(db: Session, client_id: str, event: str) -> ClientEvent:
    LOGGER.info(f'creating new client_event for client_id={client_id} event="{event}"')

    db_client_event = ClientEvent(
        client_id=client_id,
        event=event
    )

    db.add(db_client_event)
    db.commit()
    db.refresh(db_client_event)

    return db_client_event


def get_all_client_events(db: Session, client: Client) -> list[ClientEvent]:
    LOGGER.info(f'requested all events for client_id={client.client_id}')

    return db.query(ClientEvent).filter(ClientEvent.client_id == client.client_id).all()
