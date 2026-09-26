"""Training routes: datasets, runs, the LoRA registry, trainer status. Thin."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from api_types import StatusResponse
from app_handler import AppHandler
from film.training_api_types import (
    CaptionRequest,
    CreateDatasetRequest,
    DatasetListResponse,
    ImportDatasetItemsRequest,
    ImportLoraRequest,
    LoraListResponse,
    RunListResponse,
    StartTrainingRequest,
    SuggestConfigRequest,
    TrainingStatusResponse,
    UpdateDatasetRequest,
    UpdateItemRequest,
    UpdateLoraRequest,
)
from film.training_models import Dataset, LoraEntry, TrainingConfig, TrainingRun
from state import get_state_service

router = APIRouter(prefix="/api/training", tags=["training"])


@router.get("/status", response_model=TrainingStatusResponse)
def route_status(handler: AppHandler = Depends(get_state_service)) -> TrainingStatusResponse:
    return handler.training.status()


@router.put("/weights/{target}")
def route_set_weights(target: str, values: dict[str, str], handler: AppHandler = Depends(get_state_service)) -> dict[str, dict[str, str]]:
    return handler.training.set_weights(target, values)


@router.get("/datasets", response_model=DatasetListResponse)
def route_list_datasets(handler: AppHandler = Depends(get_state_service)) -> DatasetListResponse:
    return DatasetListResponse(datasets=handler.training.list_datasets())


@router.post("/datasets", response_model=Dataset)
def route_create_dataset(req: CreateDatasetRequest, handler: AppHandler = Depends(get_state_service)) -> Dataset:
    return handler.training.create_dataset(name=req.name, preset=req.preset, trigger=req.trigger)


@router.get("/datasets/{dataset_id}", response_model=Dataset)
def route_get_dataset(dataset_id: str, handler: AppHandler = Depends(get_state_service)) -> Dataset:
    return handler.training.get_dataset(dataset_id)


@router.put("/datasets/{dataset_id}", response_model=Dataset)
def route_update_dataset(dataset_id: str, req: UpdateDatasetRequest, handler: AppHandler = Depends(get_state_service)) -> Dataset:
    return handler.training.update_dataset(dataset_id, name=req.name, preset=req.preset, trigger=req.trigger)


@router.delete("/datasets/{dataset_id}", response_model=StatusResponse)
def route_delete_dataset(dataset_id: str, handler: AppHandler = Depends(get_state_service)) -> StatusResponse:
    handler.training.delete_dataset(dataset_id)
    return StatusResponse(status="ok")


@router.post("/datasets/{dataset_id}/import", response_model=Dataset)
def route_import_items(dataset_id: str, req: ImportDatasetItemsRequest, handler: AppHandler = Depends(get_state_service)) -> Dataset:
    return handler.training.import_items(dataset_id, req)


@router.post("/datasets/{dataset_id}/caption", response_model=Dataset)
def route_caption(dataset_id: str, req: CaptionRequest, handler: AppHandler = Depends(get_state_service)) -> Dataset:
    return handler.training.caption_dataset(dataset_id, overwrite_edited=req.overwrite_edited)


@router.put("/datasets/{dataset_id}/items/{item_id}", response_model=Dataset)
def route_update_item(dataset_id: str, item_id: str, req: UpdateItemRequest, handler: AppHandler = Depends(get_state_service)) -> Dataset:
    return handler.training.update_item(dataset_id, item_id, req.caption)


@router.delete("/datasets/{dataset_id}/items/{item_id}", response_model=Dataset)
def route_remove_item(dataset_id: str, item_id: str, handler: AppHandler = Depends(get_state_service)) -> Dataset:
    return handler.training.remove_item(dataset_id, item_id)


@router.get("/datasets/{dataset_id}/media")
def route_dataset_media(dataset_id: str, path: str = Query(min_length=1), handler: AppHandler = Depends(get_state_service)) -> FileResponse:
    return FileResponse(handler.training.media_path(dataset_id, path))


@router.get("/runs/{run_id}/media")
def route_run_media(run_id: str, path: str = Query(min_length=1), handler: AppHandler = Depends(get_state_service)) -> FileResponse:
    return FileResponse(handler.training.run_media_path(run_id, path))


@router.post("/suggest", response_model=TrainingConfig)
def route_suggest(req: SuggestConfigRequest, handler: AppHandler = Depends(get_state_service)) -> TrainingConfig:
    return handler.training.suggest_config(req.dataset_id, req.target)


@router.get("/runs", response_model=RunListResponse)
def route_list_runs(handler: AppHandler = Depends(get_state_service)) -> RunListResponse:
    return RunListResponse(runs=handler.training.list_runs())


@router.post("/runs", response_model=TrainingRun)
def route_start(req: StartTrainingRequest, handler: AppHandler = Depends(get_state_service)) -> TrainingRun:
    return handler.training.start(req)


@router.get("/runs/{run_id}", response_model=TrainingRun)
def route_get_run(run_id: str, handler: AppHandler = Depends(get_state_service)) -> TrainingRun:
    return handler.training.get_run(run_id)


@router.post("/runs/{run_id}/cancel", response_model=TrainingRun)
def route_cancel(run_id: str, handler: AppHandler = Depends(get_state_service)) -> TrainingRun:
    return handler.training.cancel(run_id)


@router.delete("/runs/{run_id}", response_model=StatusResponse)
def route_delete_run(run_id: str, handler: AppHandler = Depends(get_state_service)) -> StatusResponse:
    handler.training.delete_run(run_id)
    return StatusResponse(status="ok")


@router.get("/loras", response_model=LoraListResponse)
def route_list_loras(target: str = "", model: str = "", handler: AppHandler = Depends(get_state_service)) -> LoraListResponse:
    if model:
        return LoraListResponse(loras=handler.training.compatible(model))
    return LoraListResponse(loras=handler.training.list_loras(target))


@router.post("/loras/import", response_model=LoraEntry)
def route_import_lora(req: ImportLoraRequest, handler: AppHandler = Depends(get_state_service)) -> LoraEntry:
    return handler.training.import_lora(path=req.path, name=req.name, target=req.target, trigger=req.trigger)


@router.put("/loras/{lora_id}", response_model=LoraEntry)
def route_update_lora(lora_id: str, req: UpdateLoraRequest, handler: AppHandler = Depends(get_state_service)) -> LoraEntry:
    return handler.training.update_lora(lora_id, name=req.name, trigger=req.trigger, default_multiplier=req.default_multiplier)


@router.delete("/loras/{lora_id}", response_model=StatusResponse)
def route_delete_lora(lora_id: str, handler: AppHandler = Depends(get_state_service)) -> StatusResponse:
    handler.training.delete_lora(lora_id)
    return StatusResponse(status="ok")
