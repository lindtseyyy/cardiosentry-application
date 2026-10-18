"""FastAPI app state: record stores, registry and loaded model singletons."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from backend.services.accounts import AccountStore
from backend.services.ecg_gate import EcgGate, load_gate
from backend.services.records import RecordStore
from backend.services.registry import LoadedDescriptor, discover, active
from backend.services.runner import LoadedModel, load_model
from backend.settings import settings


@dataclass
class AppState:
    accounts: AccountStore
    records: RecordStore
    started_monotonic: float = field(default_factory=time.monotonic)
    descriptors: dict[str, LoadedDescriptor] = field(default_factory=dict)
    active_model: LoadedModel | None = None
    ecg_gate: EcgGate | None = None
    _models_cache: dict[str, LoadedModel] = field(default_factory=dict)
    _load_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        self.descriptors = discover()
        active_ld = active(self.descriptors)
        self.active_model = load_model(active_ld)
        self._models_cache[active_ld.id] = self.active_model
        if settings.ecg_gate:
            self.ecg_gate = load_gate(settings.ecg_gate)

    def model(self, model_id: str | None) -> LoadedModel:
        """The active model, or another discovered model (lazily loaded)."""
        if model_id is None or model_id == self.active_model.id:
            return self.active_model
        if model_id not in self.descriptors:
            from backend.errors import ApiError
            raise ApiError(404, "UNKNOWN_MODEL",
                           f"model {model_id!r} not found. Known models: "
                           + ", ".join(sorted(self.descriptors)))
        with self._load_lock:
            if model_id not in self._models_cache:
                self._models_cache[model_id] = load_model(self.descriptors[model_id])
            return self._models_cache[model_id]

    @property
    def uptime_s(self) -> float:
        return time.monotonic() - self.started_monotonic

    def descriptor_snapshot(self, model_id: str | None) -> dict:
        return self.model(model_id).descriptor.model_dump(mode="json")


def get_state(request) -> AppState:
    return request.app.state.csd


def create_state() -> AppState:
    """Load the account store before the model at startup.

    Account-store/model problems refuse startup rather than serving broken state.
    """
    settings.ensure_dirs()
    accounts = AccountStore(settings.data_dir / "accounts.json")
    accounts.ensure_admin()
    return AppState(accounts=accounts, records=RecordStore())
