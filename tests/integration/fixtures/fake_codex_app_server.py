from __future__ import annotations

import json
import sys


mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
active_turn = False
approval_index = 0
approval_ids = [900, 901] if mode == "repeated" else [900]


def emit(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def emit_approval() -> None:
    request_id = approval_ids[approval_index]
    if approval_index == 0:
        emit(
            {
                "id": request_id,
                "method": "item/commandExecution/requestApproval",
                "params": {
                    "threadId": "thr_fake",
                    "turnId": "turn_fake",
                    "itemId": "command_fake",
                    "startedAtMs": 1,
                    "command": "python -m unittest",
                    "cwd": "/synthetic/project",
                    "availableDecisions": [
                        "accept",
                        "acceptForSession",
                        "decline",
                        "cancel",
                    ],
                },
            }
        )
    else:
        emit(
            {
                "id": request_id,
                "method": "item/fileChange/requestApproval",
                "params": {
                    "threadId": "thr_fake",
                    "turnId": "turn_fake",
                    "itemId": "file_fake",
                    "startedAtMs": 2,
                    "reason": "Write synthetic fixture output.",
                    "grantRoot": "/synthetic/project",
                },
            }
        )


def emit_usage(total_tokens: int) -> None:
    emit(
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "thr_fake",
                "turnId": "turn_fake",
                "tokenUsage": {
                    "total": {
                        "totalTokens": total_tokens,
                        "inputTokens": total_tokens - 10,
                        "cachedInputTokens": 20,
                        "cacheWriteInputTokens": 0,
                        "outputTokens": 10,
                        "reasoningOutputTokens": 3,
                    },
                    "last": {
                        "totalTokens": 40,
                        "inputTokens": 30,
                        "cachedInputTokens": 20,
                        "cacheWriteInputTokens": 0,
                        "outputTokens": 10,
                        "reasoningOutputTokens": 3,
                    },
                    "modelContextWindow": 258400,
                },
            },
        }
    )


def complete(status: str, error: dict | None = None) -> None:
    global active_turn
    active_turn = False
    turn = {
        "id": "turn_fake",
        "status": status,
        "items": [],
        "itemsView": "full",
        "error": error,
        "startedAt": 1,
        "completedAt": 2,
        "durationMs": 1000,
    }
    emit(
        {
            "method": "turn/completed",
            "params": {"threadId": "thr_fake", "turn": turn},
        }
    )


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")

    if request_id in approval_ids and "result" in message:
        if mode == "unresolved":
            continue
        emit(
            {
                "method": "serverRequest/resolved",
                "params": {"threadId": "thr_fake", "requestId": request_id},
            }
        )
        approval_index += 1
        if approval_index < len(approval_ids):
            emit_usage(100)
            emit_approval()
        else:
            emit_usage(140)
            complete("completed")
        continue

    if request_id is None:
        continue
    if method == "initialize" and mode == "no_initialize_response":
        continue
    if method == "initialize":
        result = {"userAgent": "fake"}
    elif method == "model/list":
        if mode == "id_collision":
            emit(
                {
                    "id": request_id,
                    "method": "item/commandExecution/requestApproval",
                    "params": {
                        "threadId": "thr_collision",
                        "turnId": "turn_collision",
                        "itemId": "collision",
                        "startedAtMs": 1,
                        "command": "collision-test",
                    },
                }
            )
        result = {"data": [{"id": "fake-model", "displayName": "Fake Model"}]}
    elif method in {"thread/start", "thread/resume"}:
        result = {"thread": {"id": message["params"].get("threadId", "thr_fake")}}
    elif method == "turn/start":
        active_turn = True
        result = {
            "turn": {
                "id": "turn_fake",
                "status": "inProgress",
                "items": [],
            }
        }
    elif method == "turn/interrupt":
        result = {}
    else:
        result = {}
    emit({"id": request_id, "result": result})

    if method == "turn/start":
        if mode == "exit_after_turn":
            raise SystemExit(7)
        if mode == "invalid_json":
            print("not-json", flush=True)
            continue
        if mode == "oversized_event":
            emit(
                {
                    "method": "item/fileChange/delta",
                    "params": {
                        "threadId": "thr_fake",
                        "turnId": "turn_fake",
                        "itemId": "file_fake",
                        "content": "x" * 250_000,
                    },
                }
            )
            continue
        if mode == "silent_after_turn":
            emit(
                {
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": "thr_fake",
                        "turnId": "turn_fake",
                        "delta": "working",
                    },
                }
            )
            continue
        if mode == "failed":
            complete(
                "failed",
                {
                    "message": "Synthetic failure",
                    "codexErrorInfo": "serverOverloaded",
                    "additionalDetails": None,
                },
            )
            continue
        emit(
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thr_fake",
                    "turnId": "turn_fake",
                    "delta": "done",
                },
            }
        )
        emit_approval()
    elif method == "turn/interrupt" and active_turn:
        complete("interrupted")
