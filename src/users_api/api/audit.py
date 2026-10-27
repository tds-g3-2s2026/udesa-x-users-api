from typing import Annotated

from fastapi import APIRouter, Query

from users_api.api.deps import AdministratorDep, AuditRepositoryDep
from users_api.api.schemas.audit import AuditEntryResponse, AuditPage

router = APIRouter(prefix="/admin/audit", tags=["admin"])


@router.get("")
async def list_audit_entries(
    _: AdministratorDep,
    entries: AuditRepositoryDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    page, total = await entries.list_page(limit, offset)
    return AuditPage(
        items=[AuditEntryResponse.model_validate(entry) for entry in page], total=total
    )
