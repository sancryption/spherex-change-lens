"""Shared runtime services, attached to ``app.state.services`` at startup."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from change_lens.archive.base import ArchiveClient
from change_lens.config import Settings
from change_lens.storage.sqlite import Repository


@dataclass
class Services:
    settings: Settings
    repo: Repository
    archive: ArchiveClient
    artifact_roots: list[Path]  # the only folders artifacts may be served from


def get_services(request: Request) -> Services:
    return request.app.state.services


# Use as a route parameter type: `services: ServicesDep`
ServicesDep = Annotated[Services, Depends(get_services)]
