"""POST /v1/investigations — synchronous, bounded by the investigation deadline (ADR-0001)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent_platform.agent.workflow import InvestigationRun, WorkflowInvestigator

router = APIRouter(prefix="/v1/investigations", tags=["investigations"])


class InvestigationRequest(BaseModel):
    issue: str = Field(min_length=10, max_length=4000)
    service: str | None = Field(default=None, max_length=100)


def get_investigator(request: Request) -> WorkflowInvestigator:
    investigator: WorkflowInvestigator | None = request.app.state.investigator
    if investigator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM provider is not configured (APP_ANTHROPIC_API_KEY)",
        )
    return investigator


Investigator = Annotated[WorkflowInvestigator, Depends(get_investigator)]


@router.post("")
async def create_investigation(
    body: InvestigationRequest, investigator: Investigator
) -> InvestigationRun:
    return await investigator.investigate(body.issue, service=body.service)
