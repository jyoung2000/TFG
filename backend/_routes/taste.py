"""Route handlers for /api/taste: thumbs up / thumbs down (film/taste.py)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app_handler import AppHandler
from film.taste import TasteKind, TasteSummary, TasteVote
from state import get_state_service

router = APIRouter(prefix="/api/taste", tags=["taste"])


class VoteRequest(BaseModel):
    kind: TasteKind
    subject: str
    #: 1 = thumbs up, -1 = thumbs down, 0 = take the vote back.
    vote: Literal[1, 0, -1]
    project_id: str = ""
    prompt: str = ""
    model: str = ""
    loras: list[str] = Field(default_factory=list[str])


class VoteResponse(BaseModel):
    vote: TasteVote | None = None


class VotesResponse(BaseModel):
    votes: list[TasteVote] = Field(default_factory=list[TasteVote])


@router.post("/vote", response_model=VoteResponse)
def route_vote(req: VoteRequest, handler: AppHandler = Depends(get_state_service)) -> VoteResponse:
    if req.vote == 0:
        handler.taste.clear(req.kind, req.subject)
        return VoteResponse(vote=None)
    stored = handler.taste.vote(
        TasteVote(kind=req.kind, subject=req.subject, vote=req.vote, project_id=req.project_id, prompt=req.prompt, model=req.model, loras=list(req.loras))
    )
    return VoteResponse(vote=stored)


@router.get("/votes", response_model=VotesResponse)
def route_votes(kind: str = "", handler: AppHandler = Depends(get_state_service)) -> VotesResponse:
    return VotesResponse(votes=handler.taste.votes(kind))


@router.get("/summary", response_model=TasteSummary)
def route_summary(handler: AppHandler = Depends(get_state_service)) -> TasteSummary:
    return handler.taste.summary()
