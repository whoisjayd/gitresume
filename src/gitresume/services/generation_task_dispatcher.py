from typing import Protocol


class GenerationTaskDispatcher(Protocol):
    async def enqueue(self, generation_id: str) -> str: ...


class TaskiqGenerationTaskDispatcher:
    async def enqueue(self, generation_id: str) -> str:
        from gitresume.workers.generation_tasks import run_generation

        task = await run_generation.kiq(generation_id)
        return task.task_id
