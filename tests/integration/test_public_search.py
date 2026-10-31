import base64
import json
import os
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from users_api.api.deps import get_blocks_client
from users_api.infrastructure.database.models import UserModel
from users_api.infrastructure.posts_api.blocks import HttpBlocksClient

pytestmark = pytest.mark.skipif(
    not all(os.getenv(key) for key in ["DATABASE_URL", "REDIS_URL", "RABBITMQ_URL"]),
    reason="requires services",
)


@pytest.fixture
async def blocks(api):
    class Graph:
        excluded = set()
        requests = []
        down = False
        malformed = False

        def answer(self, request):
            body = json.loads(request.content)
            assert request.headers["X-Internal-Token"] == os.environ["INTERNAL_API_TOKEN"]
            assert len(body["user_ids"]) <= 50
            self.requests.append(body)
            if self.down:
                return httpx.Response(503)
            if self.malformed:
                return httpx.Response(200, json={"excluded_ids": ["bad-id"]})
            return httpx.Response(
                200,
                json={
                    "excluded_ids": [value for value in body["user_ids"] if value in self.excluded]
                },
            )

    graph = Graph()
    async with httpx.AsyncClient(
        base_url="http://posts-api",
        headers={"X-Internal-Token": os.environ["INTERNAL_API_TOKEN"]},
        transport=httpx.MockTransport(graph.answer),
    ) as client:
        api.app.dependency_overrides[get_blocks_client] = lambda: HttpBlocksClient(client)
        yield graph
        api.app.dependency_overrides.pop(get_blocks_client)


async def viewer(api):
    user_id = (await api.register()).json()["id"]
    await api.verify_last()
    token = (await api.login()).json()["access_token"]
    return user_id, {"Authorization": f"Bearer {token}"}


async def candidates(api, count, **fields):
    ids = [uuid.UUID(int=1000 + i) for i in range(count)]
    async with api.app.state.session_factory() as session:
        session.add_all(
            [
                UserModel(
                    id=value,
                    email=f"match{i}@example.com",
                    handle=f"@match{i:04}",
                    password_hash="unused",
                    created_at=datetime(2026, 10, 1, tzinfo=UTC),
                    **fields,
                )
                for i, value in enumerate(ids)
            ]
        )
        await session.commit()
    return [str(value) for value in reversed(ids)]


async def test_e2_h10_ca1_searches_display_name_or_handle_and_at_only_handle(api, blocks):
    _, headers = await viewer(api)
    ids = await candidates(api, 1, display_name="Universidad", profile_visibility="protected")
    for query in ["UNIVERSIDAD", " match ", "@match"]:
        response = await api.client.get("/search/users", params={"q": query}, headers=headers)
        assert response.status_code == 200
        assert response.json()["items"] == [
            {"id": ids[0], "handle": "@match0000", "displayName": "Universidad", "isPrivate": True}
        ]
    response = await api.client.get("/search/users", params={"q": "@universidad"}, headers=headers)
    assert response.json()["items"] == []


async def test_e2_h10_ca4_refills_blocked_batches_without_skipping_remaining_candidates(
    api, blocks
):
    user_id, headers = await viewer(api)
    ids = await candidates(api, 86)
    blocks.excluded = set(ids[:60])
    first = (await api.client.get("/search/users", params={"q": "match"}, headers=headers)).json()
    second = (
        await api.client.get(
            "/search/users", params={"q": "match", "cursor": first["nextCursor"]}, headers=headers
        )
    ).json()
    assert len(first["items"]) == 20
    assert len(second["items"]) == 6
    assert second["nextCursor"] is None
    assert [row["id"] for row in first["items"] + second["items"]] == ids[60:]
    assert all(body["viewer_id"] == user_id for body in blocks.requests)


async def test_e2_h10_ca4_exhausts_many_blocked_batches_after_exactly_twenty_visible(api, blocks):
    _, headers = await viewer(api)
    ids = await candidates(api, 126)
    blocks.excluded = set(ids[:-20])

    response = await api.client.get("/search/users", params={"q": "match"}, headers=headers)

    body = response.json()
    assert response.status_code == 200
    assert [row["id"] for row in body["items"]] == ids[-20:]
    assert body["nextCursor"] is None
    assert len(blocks.requests) == 3


async def test_e2_h10_ca4_returns_the_twenty_first_visible_account_on_next_page(api, blocks):
    _, headers = await viewer(api)
    ids = await candidates(api, 22)
    blocks.excluded = {ids[0]}

    first = (await api.client.get("/search/users", params={"q": "match"}, headers=headers)).json()
    second = (
        await api.client.get(
            "/search/users", params={"q": "match", "cursor": first["nextCursor"]}, headers=headers
        )
    ).json()

    assert [row["id"] for row in first["items"]] == ids[1:-1]
    assert first["nextCursor"] is not None
    assert [row["id"] for row in second["items"]] == ids[-1:]
    assert second["nextCursor"] is None


async def test_e2_h10_ca4_returns_an_empty_exhausted_page_when_all_candidates_are_blocked(
    api, blocks
):
    _, headers = await viewer(api)
    ids = await candidates(api, 5)
    blocks.excluded = set(ids)

    response = await api.client.get("/search/users", params={"q": "match"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["nextCursor"] is None


async def test_e2_h10_ca1_wildcards_are_literal_and_deleted_admins_are_excluded(api, blocks):
    _, headers = await viewer(api)
    ids = await candidates(api, 3, display_name="%_\\ café")
    async with api.app.state.session_factory() as session:
        (await session.get(UserModel, uuid.UUID(ids[0]))).deleted_at = datetime.now(UTC)
        (await session.get(UserModel, uuid.UUID(ids[1]))).role = "moderator"
        await session.commit()
    for query in ["%_\\", "CAFÉ"]:
        body = (await api.client.get("/search/users", params={"q": query}, headers=headers)).json()
        assert [row["id"] for row in body["items"]] == ids[2:]
        assert not {"email", "password_hash", "status"} & body["items"][0].keys()


@pytest.mark.parametrize("query", ["ab", " @ab ", "    ", "abc\x00"])
async def test_e2_h10_ca1_rejects_invalid_normalized_query(api, blocks, query):
    _, headers = await viewer(api)
    response = await api.client.get("/search/users", params={"q": query}, headers=headers)
    assert response.status_code == 422
    assert blocks.requests == []


@pytest.mark.parametrize("malformed", [False, True])
async def test_e2_h10_ca5_failure_to_verify_blocks_is_503_with_one_retry(api, blocks, malformed):
    _, headers = await viewer(api)
    await candidates(api, 1)
    blocks.down = not malformed
    blocks.malformed = malformed
    response = await api.client.get("/search/users", params={"q": "match"}, headers=headers)
    assert response.status_code == 503
    assert len(blocks.requests) == 2
    assert "items" not in response.json()


async def test_e2_h10_ca4_invalid_cursor_and_ca1_session_required(api, blocks):
    _, headers = await viewer(api)
    assert (await api.client.get("/search/users", params={"q": "match"})).status_code == 401
    response = await api.client.get(
        "/search/users", params={"q": "match", "cursor": "invalid"}, headers=headers
    )
    assert response.status_code == 400


async def test_e2_h10_ca5_own_account_can_be_found(api, blocks):
    user_id, headers = await viewer(api)
    body = (await api.client.get("/search/users", params={"q": "@alumno"}, headers=headers)).json()
    assert [row["id"] for row in body["items"]] == [user_id]


async def test_e2_h10_ca4_cursor_without_timezone_is_400(api, blocks):
    _, headers = await viewer(api)
    cursor = base64.urlsafe_b64encode(f"2026-10-25|{uuid.uuid4()}".encode()).decode()
    response = await api.client.get(
        "/search/users", params={"q": "match", "cursor": cursor}, headers=headers
    )
    assert response.status_code == 400


async def test_e2_h10_ca4_cursor_outside_utc_datetime_range_is_400(api, blocks):
    _, headers = await viewer(api)
    cursor = base64.urlsafe_b64encode(f"0001-01-01T00:00:00+23:59|{uuid.uuid4()}".encode()).decode()

    response = await api.client.get(
        "/search/users", params={"q": "match", "cursor": cursor}, headers=headers
    )

    assert response.status_code == 400
