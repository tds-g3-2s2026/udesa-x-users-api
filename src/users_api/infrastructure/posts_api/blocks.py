"""Batch block exclusions through the internal graph endpoint."""

import asyncio
from dataclasses import dataclass
from uuid import UUID

import httpx
from opentelemetry.propagate import inject
from pydantic import BaseModel

from users_api.app.clients.blocks import BlocksClient, BlocksUnavailableError


class BlockExclusions(BaseModel):
    excluded_ids: list[UUID]


@dataclass
class HttpBlocksClient(BlocksClient):
    client: httpx.AsyncClient

    async def excluded_ids(self, viewer_id: UUID, user_ids: list[UUID]) -> set[UUID]:
        headers: dict[str, str] = {}
        inject(headers)
        for attempt in range(2):
            try:
                response = await self.client.post(
                    "/internal/blocks/check",
                    headers=headers,
                    json={
                        "viewer_id": str(viewer_id),
                        "user_ids": [str(value) for value in user_ids],
                    },
                )
                response.raise_for_status()
                return set(BlockExclusions.model_validate(response.json()).excluded_ids)
            except (httpx.HTTPError, ValueError) as error:
                if attempt:
                    raise BlocksUnavailableError from error
                await asyncio.sleep(0.2)
