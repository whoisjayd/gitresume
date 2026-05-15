import pytest
from fakeredis.aioredis import FakeRedis

from gitresume.schemas.generation import GenerationCreateRequest, GenerationStatus
from gitresume.services.generation_state_service import RedisGenerationStateService


@pytest.mark.asyncio
async def test_generation_state_service_appends_and_replays_redis_stream_events() -> None:
    redis = FakeRedis(decode_responses=True)
    service = RedisGenerationStateService(redis)
    request = GenerationCreateRequest(
        repo_url="https://github.com/example/project",
        job_description="Backend role",
    )

    state = await service.create_generation("gen-123", request)
    event = await service.append_event(
        "gen-123",
        event_type="status",
        status=GenerationStatus.GENERATING,
        message="Token-aware analysis started",
        data={"tool": "repomix"},
    )
    replayed = await service.replay_events("gen-123")
    current = await service.get_generation("gen-123")

    assert state.status is GenerationStatus.QUEUED
    assert event.sequence == 2
    assert [item.message for item in replayed] == [
        "Generation queued",
        "Token-aware analysis started",
    ]
    assert replayed[-1].data == {"tool": "repomix"}
    assert current is not None
    assert current.status is GenerationStatus.GENERATING


@pytest.mark.asyncio
async def test_generation_state_service_stores_terminal_result() -> None:
    redis = FakeRedis(decode_responses=True)
    service = RedisGenerationStateService(redis)
    request = GenerationCreateRequest(repo_url="https://github.com/example/project")

    await service.create_generation("gen-456", request)
    await service.complete_generation("gen-456", {"projectTitle": "Project", "bulletPoints": []})

    state = await service.get_generation("gen-456")
    replayed = await service.replay_events("gen-456")

    assert state is not None
    assert state.status is GenerationStatus.SUCCEEDED
    assert state.result == {"projectTitle": "Project", "bulletPoints": []}
    assert replayed[-1].event_type == "completed"


@pytest.mark.asyncio
async def test_generation_state_service_persists_model_and_provider_key_id() -> None:
    redis = FakeRedis(decode_responses=True)
    service = RedisGenerationStateService(redis)
    request = GenerationCreateRequest(
        repo_url="https://github.com/example/project",
        model="openai/gpt-4o-mini",
        provider_key_id="key-123",
    )

    await service.create_generation("gen-model", request)

    state = await service.get_generation("gen-model")
    raw = await redis.hgetall(service._state_key("gen-model"))
    task_payload = {"generation_id": "gen-model"}

    assert state is not None
    assert state.model == "openai/gpt-4o-mini"
    assert state.provider_key_id == "key-123"
    assert "secret" not in str(raw).lower()
    assert "key-123" not in str(task_payload)


@pytest.mark.asyncio
async def test_generation_state_service_replays_events_with_stream_ids_after_last_id() -> None:
    redis = FakeRedis(decode_responses=True)
    service = RedisGenerationStateService(redis)
    request = GenerationCreateRequest(repo_url="https://github.com/example/project")

    await service.create_generation("gen-replay", request)
    await service.append_event(
        "gen-replay",
        event_type="generating",
        status=GenerationStatus.GENERATING,
        message="Generating resume",
    )
    all_events = await service.replay_events_with_ids("gen-replay")
    last_seen_id = all_events[0][0]

    replayed = await service.replay_events_with_ids("gen-replay", after_id=last_seen_id)

    assert [(event_id, event.event_type) for event_id, event in replayed] == [
        (all_events[1][0], "generating")
    ]


@pytest.mark.asyncio
async def test_generation_state_service_streams_events_with_stream_ids_after_replay() -> None:
    redis = FakeRedis(decode_responses=True)
    service = RedisGenerationStateService(redis)
    request = GenerationCreateRequest(repo_url="https://github.com/example/project")

    await service.create_generation("gen-stream", request)
    await service.complete_generation("gen-stream", {"projectTitle": "Project"})
    all_events = await service.replay_events_with_ids("gen-stream")
    last_seen_id = all_events[0][0]

    streamed = []
    async for stream_id, event in service.stream_events_with_ids(
        "gen-stream", after_id=last_seen_id, block_ms=1
    ):
        streamed.append((stream_id, event.event_type))

    assert streamed == [(all_events[1][0], "completed")]


@pytest.mark.asyncio
async def test_generation_state_service_stores_and_pops_github_token_with_ttl() -> None:
    redis = FakeRedis(decode_responses=True)
    service = RedisGenerationStateService(redis, generation_ttl_seconds=60)

    await service.store_github_token("gen-token", "secret-token")
    ttl = await redis.ttl(service._credential_key("gen-token"))
    popped = await service.pop_github_token("gen-token")

    assert ttl > 0
    assert popped == "secret-token"
    assert await service.pop_github_token("gen-token") is None


@pytest.mark.asyncio
async def test_generation_state_service_pops_github_token_atomically() -> None:
    class AtomicOnlyRedis:
        def __init__(self) -> None:
            self.values = {"generation:gen-token:github-token": "secret-token"}

        async def getdel(self, key: str) -> str | None:
            return self.values.pop(key, None)

        async def get(self, key: str) -> str | None:
            del key
            raise AssertionError("pop_github_token must use atomic getdel")

        async def delete(self, key: str) -> None:
            del key
            raise AssertionError("pop_github_token must not delete after get")

    service = RedisGenerationStateService(AtomicOnlyRedis())

    popped = await service.pop_github_token("gen-token")

    assert popped == "secret-token"
    assert await service.pop_github_token("gen-token") is None


@pytest.mark.asyncio
async def test_generation_state_service_applies_ttl_and_bounded_event_stream() -> None:
    redis = FakeRedis(decode_responses=True)
    service = RedisGenerationStateService(
        redis, generation_ttl_seconds=60, generation_event_max_len=2
    )
    request = GenerationCreateRequest(repo_url="https://github.com/example/project")

    await service.create_generation("gen-retention", request)
    await service.append_event(
        "gen-retention",
        event_type="validating",
        status=GenerationStatus.VALIDATING,
        message="Validating repository",
    )
    await service.append_event(
        "gen-retention",
        event_type="generating",
        status=GenerationStatus.GENERATING,
        message="Generating resume",
    )

    assert await redis.ttl(service._state_key("gen-retention")) > 0
    assert await redis.ttl(service._sequence_key("gen-retention")) > 0
    assert await redis.ttl(service._stream_key("gen-retention")) > 0
    assert await redis.xlen(service._stream_key("gen-retention")) <= 2
