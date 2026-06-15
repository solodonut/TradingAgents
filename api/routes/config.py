"""GET /api/config/options route."""

from fastapi import APIRouter

from api.config_options import build_config_options
from api.schemas import ConfigOptions

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/options", response_model=ConfigOptions)
def get_config_options() -> ConfigOptions:
    return build_config_options()
