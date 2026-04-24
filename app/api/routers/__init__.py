"""FastAPI router registration."""

from fastapi import APIRouter

from app.api.routers.auth import router as auth_router
from app.api.routers.admin_global_defaults import router as admin_global_defaults_router
from app.api.routers.admin_hosts import router as admin_hosts_router
from app.api.routers.admin_node_allocations import router as admin_node_allocations_router
from app.api.routers.admin_nodes import router as admin_nodes_router
from app.api.routers.email_templates import router as email_templates_router
from app.api.routers.logs import router as logs_router
from app.api.routers.monitoring import router as monitoring_router
from app.api.routers.public import router as public_router
from app.api.routers.resources import router as resources_router
from app.api.routers.servers import router as servers_router
from app.api.routers.settings import router as settings_router
from app.api.routers.system import router as system_router
from app.api.routers.user_account import router as user_account_router
from app.api.routers.user_files import router as user_files_router
from app.api.routers.user_servers import router as user_servers_router
from app.api.routers.users import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(admin_global_defaults_router)
api_router.include_router(admin_hosts_router)
api_router.include_router(admin_node_allocations_router)
api_router.include_router(admin_nodes_router)
api_router.include_router(email_templates_router)
api_router.include_router(logs_router)
api_router.include_router(monitoring_router)
api_router.include_router(public_router)
api_router.include_router(resources_router)
api_router.include_router(servers_router)
api_router.include_router(settings_router)
api_router.include_router(system_router)
api_router.include_router(user_account_router)
api_router.include_router(user_files_router)
api_router.include_router(user_servers_router)
api_router.include_router(users_router)

__all__ = ["api_router"]
