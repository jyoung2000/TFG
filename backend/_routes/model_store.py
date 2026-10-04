"""Route handlers for /api/model-manager: installed models, uninstall, storage (handlers/model_store_handler.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app_handler import AppHandler
from handlers.model_store_handler import InventoryResponse, MoveStatus
from state import get_state_service

router = APIRouter(prefix="/api/model-manager", tags=["model-manager"])


class MoveRequest(BaseModel):
    area: str
    destination: str


@router.get("/installed", response_model=InventoryResponse)
def route_installed(handler: AppHandler = Depends(get_state_service)) -> InventoryResponse:
    return handler.model_store.inventory()


@router.delete("/installed/{model_id:path}", response_model=InventoryResponse)
def route_uninstall(model_id: str, handler: AppHandler = Depends(get_state_service)) -> InventoryResponse:
    return handler.model_store.uninstall(model_id)


@router.post("/storage/move", response_model=MoveStatus)
def route_move(req: MoveRequest, handler: AppHandler = Depends(get_state_service)) -> MoveStatus:
    return handler.model_store.move_area(req.area, req.destination)
