from pathlib import Path
from typing import Any

import pytest
import yaml

DATA_DIR = Path(__file__).parent / "data"


def load_data_file(path: Path) -> tuple[str, dict[str, dict[str, Any]]]:
    """Load a YAML dump export and return (prefix, by_device) in coordinator format.

    The YAML export stores flattened values. This reconstructs the nested
    {"value": {"value": X}} wrapper format that the coordinator stores internally.
    """
    with open(path) as f:
        raw: dict = yaml.safe_load(f)

    prefix = "ebusd"
    by_device: dict[str, dict[str, Any]] = {}

    for topic_path, messages in raw.items():
        parts = topic_path.split("/")
        if len(parts) < 2:
            continue
        prefix = parts[0]
        device_id = parts[1]
        device_msgs: dict[str, Any] = {}
        for msg_name, value in (messages or {}).items():
            if isinstance(value, dict):
                # Multi-field message: {field: val, ...} → {field: {"value": val}, ...}
                device_msgs[msg_name] = {k: {"value": v} for k, v in value.items()}
            else:
                # Simple scalar: val → {"value": {"value": val}}
                device_msgs[msg_name] = {"value": {"value": value}}
        by_device[device_id] = device_msgs

    return prefix, by_device


@pytest.fixture(
    params=sorted(DATA_DIR.glob("*.yml")),
    ids=lambda p: p.stem,
)
def data_file(request) -> tuple[str, dict[str, dict[str, Any]]]:
    """Parametrized fixture over every YAML file in tests/data/."""
    return load_data_file(request.param)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def expected_lingering_timers() -> bool:
    # MQTT mock leaves reconnect timers; suppress the framework's teardown check.
    return True
