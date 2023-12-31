from ferdelance.config import config_manager, DataSourceStorage
from ferdelance.logging import get_logger
from ferdelance.schemas.artifacts import Artifact
from ferdelance.schemas.estimators import apply_estimator
from ferdelance.schemas.transformers import apply_transformer
from ferdelance.schemas.tasks import TaskParameters, TaskResult

import pandas as pd

import json
import os

LOGGER = get_logger(__name__)


def setup(artifact: Artifact, job_id: str, iteration: int) -> str:
    if not artifact.id:
        raise ValueError("Invalid Artifact")

    LOGGER.info(f"artifact={artifact.id}: received new task with job={job_id}")

    config = config_manager.get()

    working_folder = os.path.join(config.storage_artifact(artifact.id, iteration), f"{job_id}")

    os.makedirs(working_folder, exist_ok=True)

    path_artifact = os.path.join(working_folder, "descriptor.json")

    with open(path_artifact, "w") as f:
        json.dump(artifact.dict(), f)

    LOGGER.info(f"artifact={artifact.id}: saved to {path_artifact}")

    return working_folder


def apply_transform(
    artifact: Artifact,
    task: TaskParameters,
    data: DataSourceStorage,
    working_folder: str,
) -> pd.DataFrame:
    dfs: list[pd.DataFrame] = []

    datasource_hashes: list[str] = task.content_ids

    LOGGER.debug(f"artifact={artifact.id}: number of transformation queries={len(datasource_hashes)}")

    for ds_hash in datasource_hashes:
        # EXTRACT data from datasource
        LOGGER.info(f"artifact={artifact.id}: execute extraction from datasource_hash={ds_hash}")

        ds = data.datasources.get(ds_hash, None)
        if not ds:
            raise ValueError()

        datasource: pd.DataFrame = ds.get()  # TODO: implemented only for files

        # TRANSFORM using query
        LOGGER.info(f"artifact={artifact.id}: execute transformation on datasource_hash={ds_hash}")

        df = datasource.copy()

        for i, stage in enumerate(artifact.transform.stages):
            if stage.transformer is None:
                continue

            df = apply_transformer(stage.transformer, df, working_folder, artifact.id, i)

        dfs.append(df)

    df_dataset = pd.concat(dfs)

    LOGGER.info(f"artifact={artifact.id}: dataset shape: {df_dataset.shape}")

    path_datasource = os.path.join(working_folder, "dataset.csv.gz")

    df_dataset.to_csv(path_datasource, compression="gzip")

    LOGGER.info(f"artifact={artifact.id}: saved data to {path_datasource}")

    return df_dataset


def run_training(data: DataSourceStorage, task: TaskParameters) -> TaskResult:
    job_id = task.job_id
    artifact: Artifact = task.artifact

    working_folder = setup(artifact, job_id, task.iteration)

    df_dataset = apply_transform(artifact, task, data, working_folder)

    if artifact.model is not None and artifact.plan is None:
        raise ValueError("Invalid artifact training")  # TODO: manage this!

    LOGGER.info(f"artifact={artifact.id}: executing model training")

    # model preparation
    local_model = artifact.get_model()

    # LOAD execution plan
    plan = artifact.get_plan()

    metrics = plan.run(df_dataset, local_model, working_folder, artifact.id)

    if plan.path_model is None:
        raise ValueError("Model path not set!")  # TODO: manage this!

    return TaskResult(
        job_id=job_id,
        result_path=plan.path_model,
        metrics=metrics,
        is_model=True,
    )


def run_estimate(data: DataSourceStorage, task: TaskParameters) -> TaskResult:
    job_id = task.job_id
    artifact: Artifact = task.artifact
    artifact.id = artifact.id

    working_folder = setup(artifact, job_id, task.iteration)

    df_dataset = apply_transform(artifact, task, data, working_folder)

    if artifact.estimator is None:
        raise ValueError("Artifact is not an estimation!")  # TODO: manage this!

    LOGGER.info(f"artifact={artifact.id}: executing estimation")

    path_estimator = apply_estimator(artifact.estimator, df_dataset, working_folder, artifact.id)

    return TaskResult(
        job_id=job_id,
        result_path=path_estimator,
        is_estimate=True,
    )
