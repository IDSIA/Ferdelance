from sqlalchemy import Column, ForeignKey, String, Float, DateTime, Integer, Boolean, Date
from sqlalchemy.sql.functions import now
from sqlalchemy.orm import relationship

from . import Base


class Setting(Base):
    """Key-value store for settings, parameters, and arguments."""
    __tablename__ = 'settings'
    key = Column(String, primary_key=True, index=True)
    value = Column(String)


class Client(Base):
    """Table used to keep track of current clients."""
    __tablename__ = 'clients'
    client_id = Column(String, primary_key=True, index=True)
    creation_time = Column(DateTime(timezone=True), server_default=now())

    version = Column(String)
    # this is b64+utf8 encoded bytes
    public_key = Column(String)

    # platform.system()
    machine_system = Column(String, nullable=False)
    # from getmac import get_mac_address; get_mac_address()
    machine_mac_address = Column(String, nullable=False, unique=True)
    # uuid.getnode()
    machine_node = Column(String, nullable=False)
    # hash of above values
    # token = Column(String, nullable=False, index=True, unique=True)

    active = Column(Boolean, default= True)
    blacklisted = Column(Boolean, default=False)
    left = Column(Boolean, default=False)
    ip_address = Column(String, nullable=False)


class ClientToken(Base):
    """Table that collect all used tokens for the clients.
    If an invalid token is reused, the client could be blacklisted (or updated).
    """
    __tablename__ = 'client_tokens'

    token_id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    token = Column(String, nullable=False, index=True, unique=True)
    creation_time = Column(DateTime(timezone=True), server_default=now())
    expiration_time = Column(DateTime(timezone=True))
    valid = Column(Boolean, default=True)

    client_id = Column(String, ForeignKey('clients.client_id'))
    client = relationship('Client')


class ClientEvent(Base):
    """Table that collect all the event from the clients."""
    __tablename__ = 'client_events'
    
    event_id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    event_time = Column(DateTime(timezone=True), server_default=now())
    event = Column(String, nullable=False)

    client_id = Column(String, ForeignKey('clients.client_id'))
    client = relationship('Client')
