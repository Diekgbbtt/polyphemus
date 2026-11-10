"""Task-owned ASGI process for the isolated hunting-gate HTTP check."""

from __future__ import annotations

from fastapi import FastAPI

from polymerhus.attack.hunting import runtime as hunting_runtime
from polymerhus.project_management import api as project_api


RECORDED: list[dict] = []
REFUSE_NEXT = False


def _fake_start(project_id, **kwargs):
    global REFUSE_NEXT
    REFUSE_NEXT = project_id.startswith("http-refuse-")
    RECORDED.append({"project_id": project_id, **kwargs})

    async def done():
        return kwargs.get("run_id")

    return done()


def _schedule(coro, *, name):
    global REFUSE_NEXT
    coro.close()
    refuse = REFUSE_NEXT
    REFUSE_NEXT = False
    if refuse:
        from polymerhus.app.runtime import ModuleAdmissionRefused

        raise ModuleAdmissionRefused("task-owned runtime refusal")
    return {"scheduled": name}


hunting_runtime.hunting_control_plane_available = lambda: True
hunting_runtime.start_hunting = _fake_start
hunting_runtime.schedule_hunting = _schedule

app = FastAPI()
app.include_router(project_api.router)


@app.get("/recorded")
def recorded():
    return {"calls": RECORDED}
