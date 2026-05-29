"""Generate docs/options.md and docs/entities.md from source code and translations."""

import ast
import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent

ENTITY_FILES = [
    "climate.py",
    "water_heater.py",
    "sensor.py",
    "switch.py",
    "datetime.py",
]

TRANSLATIONS = REPO / "custom_components" / "ebusd_vaillant" / "translations" / "en.json"
CONST_FILE = REPO / "custom_components" / "ebusd_vaillant" / "const.py"

OPTIONS_MD = REPO / "docs" / "options.md"
ENTITIES_MD = REPO / "docs" / "entities.md"
SERVICES_MD = REPO / "docs" / "services.md"

SERVICES_YAML = REPO / "custom_components" / "ebusd_vaillant" / "services.yaml"
INIT_FILE = REPO / "custom_components" / "ebusd_vaillant" / "__init__.py"

DOMAIN = "ebusd_vaillant"


def _service_link(service_id: str, domain: str) -> str:
    url = f"https://my.home-assistant.io/redirect/developer_call_service/?service={domain}.{service_id}"
    return f"[`{service_id}`]({url})"


HA_BASE_MAP = {
    "ClimateEntity": "climate",
    "WaterHeaterEntity": "water_heater",
    "SensorEntity": "sensor",
    "SwitchEntity": "switch",
    "DateTimeEntity": "datetime",
}

FEATURE_NAMES = {
    # ClimateEntityFeature
    "ClimateEntityFeature.TURN_ON": "TURN_ON",
    "ClimateEntityFeature.TURN_OFF": "TURN_OFF",
    "ClimateEntityFeature.PRESET_MODE": "PRESET_MODE",
    "ClimateEntityFeature.TARGET_TEMPERATURE": "TARGET_TEMPERATURE",
    "ClimateEntityFeature.TARGET_TEMPERATURE_RANGE": "TARGET_TEMPERATURE_RANGE",
    # WaterHeaterEntityFeature
    "WaterHeaterEntityFeature.TARGET_TEMPERATURE": "TARGET_TEMPERATURE",
    "WaterHeaterEntityFeature.OPERATION_MODE": "OPERATION_MODE",
    "WaterHeaterEntityFeature.ON_OFF": "ON_OFF",
    "WaterHeaterEntityFeature.AWAY_MODE": "AWAY_MODE",
}


def _get_entity_type(base_names: list[str]) -> str | None:
    for name in base_names:
        base = name.split(".")[-1]
        if base in HA_BASE_MAP:
            return HA_BASE_MAP[base]
    return None


def _format_feature(attr_name: str) -> str:
    short = FEATURE_NAMES.get(attr_name)
    if short:
        return short
    return attr_name.split(".")[-1]


def _collect_features(class_node: ast.ClassDef, module_source: str) -> list[str]:
    features: list[str] = []
    seen: set[str] = set()
    local_features_var: str | None = None

    def _visit_expr(expr: ast.expr) -> None:
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
            _visit_expr(expr.left)
            _visit_expr(expr.right)
        elif isinstance(expr, ast.Attribute):
            full = _resolve_attribute(expr)
            if full and full not in seen:
                seen.add(full)
                features.append(full)
        elif isinstance(expr, ast.Name):
            nonlocal local_features_var
            local_features_var = expr.id

    def _resolve_attribute(node: ast.Attribute) -> str | None:
        parts = []
        cur: ast.expr = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        else:
            return None
        return ".".join(reversed(parts))

    def _walk_features_assign(assign_value: ast.expr) -> list[str]:
        nonlocal local_features_var
        saw: list[str] = []

        def _inner(ex: ast.expr) -> None:
            nonlocal local_features_var
            if isinstance(ex, ast.BinOp) and isinstance(ex.op, ast.BitOr):
                _inner(ex.left)
                _inner(ex.right)
            elif isinstance(ex, ast.Attribute):
                full = _resolve_attribute(ex)
                if full:
                    saw.append(full)
            elif isinstance(ex, ast.Name):
                local_features_var = ex.id

        _inner(assign_value)
        return saw

    def _walk_augassign(aug_node: ast.AugAssign) -> list[str]:
        saw: list[str] = []

        def _inner(ex: ast.expr) -> None:
            if isinstance(ex, ast.BinOp) and isinstance(ex.op, ast.BitOr):
                _inner(ex.left)
                _inner(ex.right)
            elif isinstance(ex, ast.Attribute):
                full = _resolve_attribute(ex)
                if full:
                    saw.append(full)

        _inner(aug_node.value)
        return saw

    for node in ast.walk(class_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == "_attr_supported_features":
                    res = _walk_features_assign(node.value)
                    for r in res:
                        if r not in seen:
                            seen.add(r)
                            features.append(r)
                if isinstance(target, ast.Name):
                    val = node.value
                    if isinstance(val, ast.BinOp) and isinstance(val.op, ast.BitOr):
                        res = _walk_features_assign(val)
                        for r in res:
                            if r not in seen:
                                seen.add(r)
                                features.append(r)
        elif isinstance(node, ast.AugAssign):
            if (
                isinstance(node.target, ast.Attribute)
                and node.target.attr == "_attr_supported_features"
            ):
                res = _walk_augassign(node)
                for r in res:
                    if r not in seen:
                        seen.add(r)
                        features.append(r)
            if isinstance(node.target, ast.Name) and node.target.id == local_features_var:
                res = _walk_augassign(node)
                for r in res:
                    if r not in seen:
                        seen.add(r)
                        features.append(r)

    return [_format_feature(f) for f in features]


def _collect_extra_attrs(class_node: ast.ClassDef) -> dict[str, str]:
    extra = {}
    for node in ast.iter_child_nodes(class_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr.startswith("_attr_"):
                    key = target.attr.removeprefix("_attr_")
                    val = ast.unparse(node.value) if node.value else ""
                    extra[key] = val
    return extra


def parse_entities() -> list[dict]:
    entities = []
    for fname in ENTITY_FILES:
        fpath = REPO / "custom_components" / "ebusd_vaillant" / fname
        source = fpath.read_text()
        module_doc = ast.get_docstring(ast.parse(source)) or ""
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = []
            for base in node.bases:
                base_names.append(ast.unparse(base))
            entity_type = _get_entity_type(base_names)
            if entity_type is None:
                continue
            class_doc = ast.get_docstring(node) or ""
            features = _collect_features(node, source)
            extra = _collect_extra_attrs(node)
            entities.append(
                {
                    "name": node.name,
                    "description": class_doc or module_doc,
                    "type": entity_type,
                    "features": features or ["--"],
                    "module_doc": module_doc,
                    "file": fname,
                    "extra": extra,
                }
            )
    return entities


def parse_options() -> list[dict]:
    trans = json.loads(TRANSLATIONS.read_text())

    opt_step = trans.get("options", {}).get("step", {}).get("init", {})
    opt_data = opt_step.get("data", {})
    opt_desc = opt_step.get("data_description", {})

    const_text = CONST_FILE.read_text()
    const_vars = {}
    for m in re.finditer(r"^(\w+)\s*=\s*(.+)", const_text, re.MULTILINE):
        value = m.group(2).strip()
        if value == "True":
            value = "on"
        elif value == "False":
            value = "off"
        const_vars[m.group(1)] = value

    defaults = {}
    for key in opt_data:
        default_var = f"DEFAULT_{key.upper()}"
        if default_var not in const_vars:
            default_var = {
                "prime_poll_values": "DEFAULT_PRIME_VALUES",
            }.get(key)
        if default_var in const_vars:
            defaults[key] = const_vars[default_var]

    options = []
    for key in opt_data:
        raw_desc = opt_desc.get(key, "")
        cleaned = re.sub(r"\s*\(default:\s*[^)]+\)\s*$", "", raw_desc).strip()
        options.append(
            {
                "key": key,
                "label": opt_data.get(key, ""),
                "description": cleaned,
                "default": defaults.get(key, "--"),
            }
        )

    return options


def render_options(options: list[dict]) -> str:
    lines = [
        "---",
        "hide:",
        "  - toc",
        "---",
        "",
        "# Options",
        "",
        "Configuration options available for the ebusd Vaillant integration.",
        "",
        "| Option Name | Description | Default Value |",
        "|---|---|---|",
    ]
    for opt in options:
        desc = opt["description"] or opt["label"]
        lines.append(f"| `{opt['key']}` | {desc} | `{opt['default']}` |")
    lines.append("")
    return "\n".join(lines)


def render_entities(entities: list[dict]) -> str:
    lines = [
        "---",
        "hide:",
        "  - toc",
        "---",
        "",
        "# Entities",
        "",
        "Entities provided by the ebusd Vaillant integration.",
        "",
        "| Entity Name | Description | Type | Supported Features |",
        "|---|---|---|---|",
    ]
    for ent in entities:
        features = ", ".join(ent["features"])
        features = f"`{features}`"
        lines.append(f"| `{ent['name']}` | {ent['description']} | `{ent['type']}` | {features} |")
    lines.append("")
    return "\n".join(lines)


def parse_services() -> list[dict]:
    """Parse custom services from services.yaml and __init__.py."""
    services_defs = yaml.safe_load(SERVICES_YAML.read_text())
    if not services_defs:
        return []

    init_source = INIT_FILE.read_text()
    service_constants = {}
    for m in re.finditer(r"^SERVICE_(\w+)\s*=\s*\"(\w+)\"", init_source, re.MULTILINE):
        service_constants[m.group(2)] = m.group(1)

    services = []
    for service_id, svc in services_defs.items():
        fields = svc.get("fields", {})
        field_list = []
        for field_id, field_info in fields.items():
            required = field_info.get("required", False)
            default = field_info.get("default")
            selector = field_info.get("selector", {})
            sel_type = list(selector.keys())[0] if selector else "string"
            field_desc = f"`{field_id}` ({sel_type}"
            if not required:
                field_desc += ", optional"
            if default is not None:
                field_desc += f", default: {default}"
            field_desc += ")"
            field_list.append(field_desc)

        services.append(
            {
                "id": service_id,
                "name": svc.get("name", service_id),
                "description": svc.get("description", "").strip(),
                "fields": ", ".join(field_list) if field_list else "--",
                "const_name": service_constants.get(service_id, ""),
            }
        )

    return services


def render_services(entities: list[dict], custom_services: list[dict]) -> str:
    """Render services documentation."""
    lines = [
        "---",
        "hide:",
        "  - toc",
        "---",
        "",
        "# Services",
        "",
        "Home Assistant services available via the ebusd Vaillant integration.",
        "",
    ]

    if custom_services:
        lines.append("## Integration Services")
        lines.append("")
        lines.append(
            "These services are provided by the integration itself"
            " and are not tied to a specific entity."
        )
        lines.append("")
        lines.append("| Service | Description | Fields |")
        lines.append("|---|---|---|")
        for svc in custom_services:
            desc = svc["description"].replace("\n", " ").strip()
            lines.append(f"| {_service_link(svc['id'], DOMAIN)} | {desc} | {svc['fields']} |")
        lines.append("")

    # Standard HA service definitions per entity type
    services_by_type: dict[str, list[dict]] = {
        "climate": [
            {
                "service": "set_temperature",
                "description": "Set target temperature.",
                "extra_fields": "`temperature` (float), `preset_mode` (str, optional)",
            },
            {
                "service": "set_preset_mode",
                "description": "Set preset mode.",
                "extra_fields": "`preset_mode` (str)",
            },
            {
                "service": "turn_on",
                "description": "Turn the climate entity on.",
                "extra_fields": "--",
            },
            {
                "service": "turn_off",
                "description": "Turn the climate entity off.",
                "extra_fields": "--",
            },
        ],
        "water_heater": [
            {
                "service": "set_temperature",
                "description": "Set target temperature.",
                "extra_fields": "`temperature` (float)",
            },
            {
                "service": "set_operation_mode",
                "description": "Set operation mode.",
                "extra_fields": "`operation_mode` (str)",
            },
            {
                "service": "turn_on",
                "description": "Turn the water heater on.",
                "extra_fields": "--",
            },
            {
                "service": "turn_off",
                "description": "Turn the water heater off.",
                "extra_fields": "--",
            },
            {
                "service": "turn_away_mode_on",
                "description": "Turn away mode on.",
                "extra_fields": "--",
            },
            {
                "service": "turn_away_mode_off",
                "description": "Turn away mode off.",
                "extra_fields": "--",
            },
        ],
        "sensor": [],
        "switch": [
            {"service": "turn_on", "description": "Turn the switch on.", "extra_fields": "--"},
            {"service": "turn_off", "description": "Turn the switch off.", "extra_fields": "--"},
        ],
        "datetime": [
            {
                "service": "set_value",
                "description": "Set the date/time value.",
                "extra_fields": (
                    "`datetime` (datetime), `date` (date, optional), `time` (time, optional)"
                ),
            },
        ],
    }

    for entity_type in HA_BASE_MAP.values():
        matching = [e for e in entities if e["type"] == entity_type]
        if not matching:
            continue
        svcs = services_by_type.get(entity_type, [])
        if not svcs:
            continue
        entity_names = ", ".join(f"`{e['name']}`" for e in matching)
        lines.append(f"## {entity_type.replace('_', ' ').title()}")
        lines.append("")
        lines.append(f"Available on: {entity_names}")
        lines.append("")
        lines.append("| Service | Description | Extra Fields |")
        lines.append("|---|---|---|")
        for svc in svcs:
            link = _service_link(svc["service"], entity_type)
            line = f"| {link} | {svc['description']} | {svc['extra_fields']} |"
            lines.append(line)
        lines.append("")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    options = parse_options()
    entities = parse_entities()
    custom_services = parse_services()

    OPTIONS_MD.write_text(render_options(options))
    print(f"Wrote {OPTIONS_MD} ({len(options)} options)")

    ENTITIES_MD.write_text(render_entities(entities))
    print(f"Wrote {ENTITIES_MD} ({len(entities)} entities)")

    SERVICES_MD.write_text(render_services(entities, custom_services))
    print(f"Wrote {SERVICES_MD} ({len(custom_services)} custom services)")


if __name__ == "__main__":
    main()
