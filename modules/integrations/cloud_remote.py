from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


class CloudRemoteError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CloudRemoteConfig:
    base_url: str = ""
    device_id: str = ""
    device_token: str = ""

    @property
    def configured(self) -> bool:
        return (
            self.base_url.startswith("https://")
            and bool(self.device_id)
            and len(self.device_token) >= 16
        )

    @classmethod
    def from_env(cls) -> "CloudRemoteConfig":
        return cls(
            base_url=os.getenv("RYNNE_CLOUD_REMOTE_URL", "").strip().rstrip("/"),
            device_id=os.getenv("RYNNE_CLOUD_DEVICE_ID", "").strip(),
            device_token=os.getenv("RYNNE_CLOUD_DEVICE_TOKEN", "").strip(),
        )


class RynneCloudRemoteClient:
    def __init__(self, config: CloudRemoteConfig, *, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    @classmethod
    def from_env(cls) -> "RynneCloudRemoteClient":
        return cls(CloudRemoteConfig.from_env())

    @property
    def configured(self) -> bool:
        return self.config.configured

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.device_token}"}

    def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise CloudRemoteError("Rynne Cloud Remote is not configured")
        try:
            response = self.session.request(
                method,
                self.config.base_url + path,
                headers=self.headers,
                json=payload,
                timeout=(5, 20),
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CloudRemoteError(str(exc)) from exc
        if not isinstance(data, dict):
            raise CloudRemoteError("Cloud returned an invalid response")
        return data

    def heartbeat(self, *, name: str, version: str, status: str, current_task_id: str = "", permission_mode: str = "") -> None:
        self._request(
            "POST",
            f"/v1/devices/{self.config.device_id}/heartbeat",
            payload={
                "name": name,
                "version": version,
                "status": status,
                "current_task_id": current_task_id,
                "permission_mode": permission_mode,
            },
        )

    def next_task(self) -> dict[str, Any] | None:
        task = self._request("POST", f"/v1/devices/{self.config.device_id}/tasks/next").get("task")
        return task if isinstance(task, dict) else None

    def next_wake(self) -> bool:
        return bool(self._request("POST", f"/v1/devices/{self.config.device_id}/wake/next").get("wake"))

    def task_status(self, task_id: str) -> dict[str, Any] | None:
        task = self._request("GET", f"/v1/devices/{self.config.device_id}/tasks/{task_id}").get("task")
        return task if isinstance(task, dict) else None

    def event(self, task_id: str, status: str, *, message: str = "", result: str = "") -> None:
        self._request(
            "POST",
            f"/v1/devices/{self.config.device_id}/tasks/{task_id}/events",
            payload={"status": status, "message": message, "result": result},
        )

    def request_approval(self, *, task_id: str, operation_id: str, title: str, description: str, details: str = "", risk: str = "execute") -> None:
        self._request(
            "POST", f"/v1/devices/{self.config.device_id}/approvals",
            payload={"task_id": task_id, "operation_id": operation_id, "title": title,
                     "description": description, "details": details, "risk": risk},
        )

    def approval_decisions(self) -> list[dict[str, Any]]:
        items = self._request("POST", f"/v1/devices/{self.config.device_id}/approvals/decisions").get("approvals")
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def timeline_event(self, task_id: str, *, event_type: str, title: str, message: str = "", tool_name: str = "", operation_id: str = "", success: bool | None = None, duration_ms: int = 0) -> None:
        self._request(
            "POST", f"/v1/devices/{self.config.device_id}/tasks/{task_id}/timeline",
            payload={"event_type": event_type, "title": title, "message": message,
                     "tool_name": tool_name, "operation_id": operation_id,
                     "success": success, "duration_ms": duration_ms},
        )
