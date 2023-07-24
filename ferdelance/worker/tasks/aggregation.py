from typing import Any

from ferdelance.schemas.errors import TaskError
from ferdelance.schemas.worker import TaskArguments
from ferdelance.worker.celery import worker
from ferdelance.worker.jobs.routes import MemoryRouteService
from ferdelance.worker.jobs.services import AggregatingJobService
from ferdelance.worker.tasks.generic import GenericTask

import logging
import traceback


@worker.task(
    ignore_result=True,
    bind=True,
    base=GenericTask,
)
def aggregation(self: GenericTask, raw_args: dict[str, Any]) -> None:
    task_id: str = str(self.request.id)
    args = TaskArguments(**raw_args)

    try:
        logging.info(f"worker: beginning aggregation task={task_id}")

        self.artifact_id = args.artifact_id
        self.job_id = args.job_id

        self.job_service = AggregatingJobService()
        self.job_service.setup(args, MemoryRouteService(args))
        self.job_service.run()

    except Exception as e:
        logging.error(f"task_id={task_id}: job_id={self.job_id}: {e}")
        logging.exception(e)

        self.error(
            TaskError(
                job_id=self.job_id,
                message=str(e),
                stack_trace="".join(traceback.TracebackException.from_exception(e).format()),
            )
        )
