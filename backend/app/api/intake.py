"""Intake guidance: the entity-aware "what documents do I need" surface.

Both endpoints serve the static catalog in ``app.document_checklists`` — there is
no per-tenant data here (the checklist for an S-corp is the same in every
workspace), so this router takes the advisor scope but NOT ``get_tenant_db``. It
answers the "I don't know what's needed" gap so the intake can guide a non-expert
to gather the right records before any planning starts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import require_scopes
from app.document_checklists import checklist_for, entity_types
from app.schemas.auth import AuthContext

router = APIRouter(prefix="/intake", tags=["intake"])


@router.get("/entity-types")
async def get_entity_types(
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
) -> list[dict[str, str]]:
    """The entity types the intake picker offers, each as ``{key, label,
    description}`` in simplest-to-most-complex order. Includes the ``not_sure``
    affordance (it has no checklist of its own — the descriptions help the user
    self-identify)."""
    return entity_types()


@router.get("/document-checklist")
async def get_document_checklist(
    entity_type: str,
    _ctx: AuthContext = Depends(require_scopes(("taxplan:advisor",))),
) -> dict[str, object]:
    """The planning document checklist for ``entity_type`` as ``{entity_type,
    label, required: [...], beneficial: [...]}``.

    Each list item is ``{name, form_or_source, why}``. Returns 422 for an unknown
    or non-planning entity type (e.g. ``not_sure``)."""
    try:
        return checklist_for(entity_type)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown entity_type: {entity_type!r}",
        ) from exc
