from fastapi import APIRouter

from gitresume.services.model_catalog import LiteLLMModelCatalog, ModelCatalogResponse

router = APIRouter(prefix="/models")


@router.get("", response_model=ModelCatalogResponse, response_model_by_alias=True)
async def list_models() -> ModelCatalogResponse:
    return ModelCatalogResponse(models=LiteLLMModelCatalog().list_models())
