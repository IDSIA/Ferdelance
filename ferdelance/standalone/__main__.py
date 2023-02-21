from ferdelance.client.arguments import setup_config_from_arguments
from ferdelance.config import conf
from ferdelance.standalone.processes import LocalClient, LocalServer, LocalWorker

from multiprocessing import Queue
from multiprocessing.managers import BaseManager

import logging
import signal
import sys

LOGGER = logging.getLogger(__name__)


if __name__ == "__main__":
    client_conf = setup_config_from_arguments()

    LOGGER.info("standalone application starting")

    conf.STANDALONE = True
    conf.SERVER_MAIN_PASSWORD = (
        "7386ee647d14852db417a0eacb46c0499909aee90671395cb5e7a2f861f68ca1"  # this is a dummy key
    )
    conf.DB_DIALECT = "sqlite"
    conf.DB_HOST = "./sqlite.db"
    conf.SERVER_INTERFACE = "0.0.0.0"
    conf.STANDALONE_WORKERS = 7
    conf.PROJECT_DEFAULT_TOKEN = "58981bcbab77ef4b8e01207134c38873e0936a9ab88cd76b243a2e2c85390b94"

    aggregation_queue = Queue()

    manager = BaseManager(address=("", 14560))
    manager.register("get_queue", callable=lambda: aggregation_queue)
    manager.start()

    server_process = LocalServer()
    worker_process = LocalWorker()
    client_process = LocalClient(client_conf)

    def signal_handler(signum, frame):
        LOGGER.info("stopping main")
        client_process.client.stop_loop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    server_process.start()
    worker_process.start()
    client_process.start()

    client_process.join()
    worker_process.join()
    server_process.join()

    manager.shutdown()

    LOGGER.info("standalone application terminated")
