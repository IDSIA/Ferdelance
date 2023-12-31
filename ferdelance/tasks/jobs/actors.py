from typing import Any

from abc import ABC, abstractmethod

from ferdelance.config import DataSourceConfiguration, DataSourceStorage, config_manager
from ferdelance.logging import get_logger
from ferdelance.schemas.artifacts import Artifact
from ferdelance.schemas.estimators import GenericEstimator, save_estimator
from ferdelance.schemas.models import GenericModel
from ferdelance.schemas.tasks import TaskResult, TaskError
from ferdelance.tasks.jobs.execution import run_estimate, run_training
from ferdelance.tasks.jobs.routes import EncryptRouteService, RouteService, TaskParameters

import ray

import os

LOGGER = get_logger(__name__)


class GenericJob(ABC):
    def __init__(
        self,
        component_id: str,
        artifact_id: str,
        job_id: str,
        node_url: str,
        private_key: str,
        node_public_key: str,
    ) -> None:
        self.component_id: str = component_id
        self.artifact_id: str = artifact_id
        self.job_id: str = job_id

        self.routes_service: RouteService = EncryptRouteService(
            self.component_id,
            node_url,
            private_key,
            node_public_key,
        )

    def __repr__(self) -> str:
        return f"Job artifact={self.artifact_id} job={self.job_id}"

    @abstractmethod
    def run(self):
        raise NotImplementedError()


class LocalJob(GenericJob):
    def __init__(
        self,
        component_id: str,
        artifact_id: str,
        job_id: str,
        server_url: str,
        private_key: str,
        server_public_key: str,
        workdir: str,
        datasources: list[dict[str, Any]],
    ) -> None:
        super().__init__(component_id, artifact_id, job_id, server_url, private_key, server_public_key)

        self.workdir: str = workdir

        self.datasources: list[DataSourceConfiguration] = [DataSourceConfiguration(**d) for d in datasources]

        self.data = DataSourceStorage(self.datasources)


@ray.remote
class TrainingJob(LocalJob):
    def __init__(
        self,
        component_id: str,
        artifact_id: str,
        job_id: str,
        node_url: str,
        private_key: str,
        node_public_key: str,
        workdir: str,
        datasources: list[dict[str, Any]],
    ) -> None:
        super().__init__(
            component_id, artifact_id, job_id, node_url, private_key, node_public_key, workdir, datasources
        )

    def __repr__(self) -> str:
        return f"Training{super().__repr__()}"

    def run(self):
        task: TaskParameters = self.routes_service.get_task_params(artifact_id=self.artifact_id, job_id=self.job_id)

        try:
            if task.artifact.is_model():
                res = self.train(task)

                for m in res.metrics:
                    m.job_id = res.job_id
                    self.routes_service.post_metrics(self.artifact_id, self.job_id, m)

                self.routes_service.post_result(self.artifact_id, self.job_id, path_in=res.result_path)

            else:
                raise ValueError("Artifact is not a model!")

        except Exception as e:
            LOGGER.error(e)
            LOGGER.exception(e)
            self.routes_service.post_error(
                task.job_id,
                task.artifact.id,
                TaskError(
                    job_id=task.job_id,
                    message=f"Malformed artifact: {e}",
                ),
            )

    def train(self, task: TaskParameters) -> TaskResult:
        res: TaskResult = run_training(self.data, task)
        return res


@ray.remote
class EstimationJob(LocalJob):
    def __init__(
        self,
        component_id: str,
        artifact_id: str,
        job_id: str,
        server_url: str,
        private_key: str,
        server_public_key: str,
        workdir: str,
        datasources: list[dict[str, Any]],
    ) -> None:
        super().__init__(
            component_id, artifact_id, job_id, server_url, private_key, server_public_key, workdir, datasources
        )

    def __repr__(self) -> str:
        return f"Estimation{super().__repr__()}"

    def run(self):
        task: TaskParameters = self.routes_service.get_task_params(self.artifact_id, self.job_id)

        if task.artifact.is_estimation():
            res = self.estimate(task)

            self.routes_service.post_result(self.artifact_id, self.job_id, path_in=res.result_path)

        else:
            self.routes_service.post_error(
                task.job_id,
                task.artifact.id,
                TaskError(
                    job_id=task.job_id,
                    message="Malformed artifact",
                ),
            )

    def estimate(self, task: TaskParameters) -> TaskResult:
        res: TaskResult = run_estimate(self.data, task)
        return res


@ray.remote
class AggregatingJob(GenericJob):
    def __init__(
        self,
        component_id: str,
        artifact_id: str,
        job_id: str,
        server_url: str,
        private_key: str,
        server_public_key: str,
    ) -> None:
        super().__init__(component_id, artifact_id, job_id, server_url, private_key, server_public_key)

    def __repr__(self) -> str:
        return f"Aggregating{super().__repr__()}"

    def run(self):
        task: TaskParameters = self.routes_service.get_task_params(self.artifact_id, self.job_id)

        res = self.aggregate(task)

        self.routes_service.post_result(self.artifact_id, self.job_id, path_in=res.result_path)

    def aggregate_estimator(self, artifact: Artifact, result_ids: list[str]) -> GenericEstimator:
        agg = artifact.get_estimator()

        base: Any = None

        for result_id in result_ids:
            partial: GenericEstimator = self.routes_service.get_result(artifact.id, self.job_id, result_id)

            if base is None:
                base = partial
            else:
                base = agg.aggregate(base, partial)

        LOGGER.info(f"artifact={artifact.id}: aggregated {len(result_ids)} estimator(s)")

        return base

    def aggregate_model(self, artifact: Artifact, result_ids: list[str]) -> GenericModel:
        agg = artifact.get_model()
        strategy = artifact.get_strategy()

        base: Any = None

        for result_id in result_ids:
            partial: GenericModel = self.routes_service.get_result(artifact.id, self.job_id, result_id)

            if base is None:
                base = partial
            else:
                base = agg.aggregate(strategy, base, partial)

        LOGGER.info(f"artifact={artifact.id}: aggregated {len(result_ids)} model(s)")

        return base

    def destination_path(self, artifact: Artifact, task: TaskParameters) -> str:
        config = config_manager.get()

        working_folder = os.path.join(config.storage_artifact(artifact.id, task.iteration), f"{task.job_id}")

        os.makedirs(working_folder, exist_ok=True)

        path = os.path.join(working_folder, "aggregate.bin")

        return path

    def aggregate(self, task: TaskParameters) -> TaskResult:
        artifact: Artifact = task.artifact
        result_ids: list[str] = task.content_ids

        is_estimation = artifact.is_estimation()
        is_model = artifact.is_model()

        path: str = config_manager.get().store(
            artifact.id,
            self.job_id,
            task.iteration,
            False,
            True,
            is_model,
            is_estimation,
        )

        base: GenericEstimator | GenericModel

        if is_estimation:
            base = self.aggregate_estimator(artifact, result_ids)

            save_estimator(base, path)

            return TaskResult(
                job_id=task.job_id,
                result_path=None,
                is_estimate=True,
                is_aggregation=True,
            )

        if is_model:
            base = self.aggregate_model(artifact, result_ids)

            base.save(path)

            return TaskResult(
                job_id=task.job_id,
                result_path=None,
                is_model=True,
                is_aggregation=True,
            )

        raise ValueError(f"Unsupported artifact={self.job_id}")
