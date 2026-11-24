"""The generator registry: which fal endpoints the spike may call, what each costs, and how its
inputs are laid out.

`pipeline/generators.toml` is the data (endpoint ids, field names and price rules, each dated
and sourced from the endpoint's own `llms.txt` page). This module loads it into frozen values and
holds the rules that read it:

- `price_usd` prices a call from the options a caller sets. An option, or a value of one, with no
  price rule raises `PriceUnknown`, so a call that fal might bill differently is never
  authorized. An option left out takes fal's default, and that default is priced.
- `request_fields` turns the same options into the fal request fields, from the same entries, so
  the price and the request cannot disagree.
- `check_policy` and `check_endpoint_allowed` refuse what the project's terms forbid: Hunyuan 3.1
  Pro on an EU, UK or South Korea host, the open-weights Hunyuan v2 endpoints, Hi3D, and any
  endpoint outside the registry.
- `check_inputs` checks image and mesh counts and slots against a generator's limits.

Money is `Decimal` everywhere.
"""

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast


class PriceUnknown(ValueError):
    """An option or value has no price rule, so the call cannot be priced and is refused."""


class GeneratorRefused(ValueError):
    """The call breaks a rule of the registry, a limit of the generator or a term of use."""


Kind = Literal["image-to-3d", "segment", "image-edit"]
InputKind = Literal["images", "mesh"]
Scalar = bool | int | str

# Real view names to slot names. A real photo's view (`front_34_left`) and a synthesized view
# (`front_34`) both end up in one of these slots.
VIEW_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "front_34_left": "front_34",
        "front_34_right": "front_34",
        "rear_34_left": "rear_34",
        "rear_34_right": "rear_34",
        "side_left": "side",
        "side_right": "side",
        "front": "front",
        "rear": "rear",
    }
)

# Tencent's open-weights licence excludes these territories, and Hunyuan 3.1 Pro is run on a
# host in one of them only by mistake (docs/superpowers/plans: generator terms). EL and UK are
# the codes people type for Greece and the United Kingdom.
_EU27 = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    }
)
_HUNYUAN_EXCLUDED = _EU27 | {"GB", "KR", "UK", "EL"}

_ENDPOINT = re.compile(r"[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)+")
_GENERATOR_KEY = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
_AMOUNT = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_COUNTRY = re.compile(r"[A-Za-z]{2}")


@dataclass(frozen=True)
class OptionValue:
    """One value a caller may set: what it adds to the base price and the fal fields it sends."""

    value: Scalar
    add: Decimal
    fields: Mapping[str, object]


@dataclass(frozen=True)
class ChoiceRule:
    """An option with a fixed set of priced values. `default` applies when the option is left out;
    `derive` names a fact the client sets the option from (the image count)."""

    name: str
    values: tuple[OptionValue, ...]
    default: OptionValue | None
    derive: Literal["multi_image"] | None


@dataclass(frozen=True)
class RangeRule:
    """An integer option that adds a fixed amount whenever it is set, and is sent as `field`."""

    name: str
    field: str
    low: int
    high: int
    add: Decimal


OptionRule = ChoiceRule | RangeRule


@dataclass(frozen=True)
class PriceRules:
    base: Decimal
    options: Mapping[str, OptionRule]
    free: frozenset[str]  # fal request fields that cost nothing extra and pass through


@dataclass(frozen=True)
class Generator:
    key: str
    endpoint: str
    kind: Kind
    input_kind: InputKind
    min_images: int
    max_images: int
    slot_order: tuple[str, ...]  # the slots, in send order
    image_field: str | None  # the one list field of a list endpoint
    mesh_field: str | None
    slot_fields: Mapping[str, str]  # a labeled endpoint: slot -> its own field; empty for lists
    view_slots: Mapping[str, str]  # a view name -> the slot it is sent in, where labels differ
    max_mesh_bytes: int | None
    result_field: str
    experiment_only: bool  # provenance only, never enforced
    price: PriceRules
    requires_host_country: bool
    positional: bool  # a list whose meaning is its position: no gaps
    required_slots: tuple[str, ...]
    source: str
    checked: str


# --- policy ---


def check_policy(gen: Generator, *, host_country: str | None) -> None:
    """Refuse a generator whose terms exclude this host. Hunyuan 3.1 Pro needs `M3_HOST_COUNTRY`
    (a two-letter code) and refuses the EU, the UK and South Korea. Others need nothing."""
    if not gen.requires_host_country:
        return
    code = (host_country or "").strip()
    if not code:
        raise GeneratorRefused(
            f"{gen.key} is not offered in the EU, UK or South Korea, so it needs M3_HOST_COUNTRY "
            "set to the host's real two-letter country code (for example US)"
        )
    if not _COUNTRY.fullmatch(code):
        raise GeneratorRefused(
            f"M3_HOST_COUNTRY {code!r} is not a two-letter country code (for example US)"
        )
    if code.upper() in _HUNYUAN_EXCLUDED:
        raise GeneratorRefused(
            f"{gen.key} is not offered in the EU, UK or South Korea (Tencent's territory limit) "
            f"and M3_HOST_COUNTRY is {code.upper()}"
        )


def _forbidden_reason(endpoint: str) -> str | None:
    lowered = endpoint.lower()
    if "hunyuan3d/v2" in lowered or lowered.startswith("hitem3d/") or "/hitem3d/" in lowered:
        return "this endpoint is one of the two families excluded on purpose"
    return None


_EXCLUDED_FAMILIES = (
    "the open-weights Hunyuan v2 endpoints (hunyuan3d/v2: the licence bars showing output in the "
    "EU, UK or South Korea, and this site is public) and Hi3D (hitem3d/*: its terms could not "
    "be read) are never called"
)


def check_endpoint_allowed(endpoint: str, registry: Mapping[str, Generator]) -> None:
    """Refuse any endpoint that is not exactly a registry entry's, and the two families that are
    excluded on purpose (`hunyuan3d/v2` and `hitem3d/*`) even if an entry names one: a hand-built
    entry cannot make them callable. The message names both families."""
    if _forbidden_reason(endpoint) is None and any(
        gen.endpoint == endpoint for gen in registry.values()
    ):
        return
    raise GeneratorRefused(
        f"endpoint {endpoint!r} is not in the generator registry; {_EXCLUDED_FAMILIES}; "
        "to add an endpoint, read its live price on fal, add it to generators.toml and add a "
        "ledger row"
    )


# --- inputs ---


def _images_word(count: int) -> str:
    return "image" if count == 1 else "images"


def check_inputs(gen: Generator, *, slots: Sequence[str], has_mesh: bool) -> tuple[int, ...]:
    """Check what a call sends against the generator's limits.

    Returns the order to send the images in, as indexes into `slots`: by the generator's
    `slot_order`. A mesh generator returns `()`.
    """
    if gen.input_kind == "mesh":
        if slots:
            raise GeneratorRefused(f"{gen.key} takes one mesh and no images, got {len(slots)}")
        if not has_mesh:
            raise GeneratorRefused(f"{gen.key} needs a mesh")
        return ()
    if has_mesh:
        raise GeneratorRefused(f"{gen.key} takes images, not a mesh")

    count = len(slots)
    if count < gen.min_images or count > gen.max_images:
        wanted = (
            f"{gen.min_images} {_images_word(gen.min_images)}"
            if gen.min_images == gen.max_images
            else f"{gen.min_images} to {gen.max_images} images"
        )
        raise GeneratorRefused(f"{gen.key} takes {wanted}, got {count}")
    unknown = [slot for slot in slots if slot not in gen.slot_order]
    if unknown:
        raise GeneratorRefused(
            f"{gen.key} has no slot {unknown[0]!r}; its slots are {', '.join(gen.slot_order)}"
        )
    repeated = [slot for slot in slots if slots.count(slot) > 1]
    if repeated:
        raise GeneratorRefused(f"{gen.key}: slot {repeated[0]!r} is used twice")
    missing = [slot for slot in gen.required_slots if slot not in slots]
    if missing:
        raise GeneratorRefused(f"{gen.key} needs its {missing[0]!r} slot")
    if gen.positional and set(slots) != set(gen.slot_order[:count]):
        raise GeneratorRefused(
            f"{gen.key} takes a positional image list ({', '.join(gen.slot_order)}), so "
            f"the slots sent must be the first {count} of those with no gap, got "
            f"{', '.join(slots)}"
        )
    return tuple(sorted(range(count), key=lambda index: gen.slot_order.index(slots[index])))


# --- prices and request fields ---


def _same(left: object, right: object) -> bool:
    """Equality that keeps `True`, `1` and `1.0` apart: a bool is not a resolution."""
    return type(left) is type(right) and left == right


def _value_rule(gen: Generator, rule: ChoiceRule, value: object) -> OptionValue:
    for candidate in rule.values:
        if _same(candidate.value, value):
            return candidate
    priced = ", ".join(repr(candidate.value) for candidate in rule.values)
    raise PriceUnknown(
        f"{gen.key} has no price for {rule.name}={value!r}; priced values are {priced}"
    )


def _check_range(gen: Generator, rule: RangeRule, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not rule.low <= value <= rule.high:
        raise PriceUnknown(
            f"{gen.key} has no price for {rule.name}={value!r}; it takes an integer "
            f"from {rule.low} to {rule.high}"
        )
    return value


def _check_names(gen: Generator, options: Mapping[str, object]) -> None:
    for name in options:
        if name not in gen.price.options and name not in gen.price.free:
            raise PriceUnknown(
                f"{gen.key} has no price rule for option {name!r}: add it to generators.toml "
                "with its price from fal, or leave it out"
            )


def price_usd(gen: Generator, options: Mapping[str, object]) -> Decimal:
    """The price of one call with `options`, in USD.

    An option left out counts at its `default` (fal's own), so `{}` is priced as what fal
    would bill for `{}`, never as the cheapest tier. `PriceUnknown` for an option, or a value
    of one, with no rule.
    """
    _check_names(gen, options)
    total = gen.price.base
    for rule in gen.price.options.values():
        if isinstance(rule, RangeRule):
            if rule.name in options:
                _check_range(gen, rule, options[rule.name])
                total += rule.add
        elif rule.name in options:
            total += _value_rule(gen, rule, options[rule.name]).add
        elif rule.default is not None:
            total += rule.default.add
    return total


def _merge(fields: dict[str, object], new: Mapping[str, object], gen: Generator, who: str) -> None:
    for name, value in new.items():
        if name in fields and fields[name] != value:
            raise GeneratorRefused(
                f"{gen.key}: {who} sets the field {name!r} to {value!r}, but another option "
                f"already set it to {fields[name]!r}"
            )
        fields[name] = value


def request_fields(gen: Generator, options: Mapping[str, object]) -> dict[str, object]:
    """The fal request fields for `options`, from the same entries that price them. Defaults
    are sent too, so the priced value is the requested one. `PriceUnknown` as `price_usd`."""
    _check_names(gen, options)
    fields: dict[str, object] = {}
    for rule in gen.price.options.values():
        if isinstance(rule, RangeRule):
            if rule.name in options:
                _merge(
                    fields,
                    {rule.field: _check_range(gen, rule, options[rule.name])},
                    gen,
                    rule.name,
                )
        elif rule.name in options:
            _merge(fields, _value_rule(gen, rule, options[rule.name]).fields, gen, rule.name)
        elif rule.default is not None:
            _merge(fields, rule.default.fields, gen, rule.name)
    for name in gen.price.free:
        if name not in options:
            continue
        value = options[name]
        if not isinstance(value, bool | int | float | str):
            raise GeneratorRefused(
                f"{gen.key}: option {name!r} must be a string, number or boolean, "
                f"got {type(value).__name__}"
            )
        _merge(fields, {name: value}, gen, name)
    return fields


def with_derived_options(
    gen: Generator, options: Mapping[str, object], *, image_count: int
) -> dict[str, object]:
    """`options` plus the ones fal bills from what is sent. Hunyuan's `multi_view` is true when
    more than one image goes, whatever the caller said; a value that disagrees is refused, so a
    multi-view call is never priced (and its ledger row never estimated) as a single image."""
    derived = dict(options)
    for rule in gen.price.options.values():
        if isinstance(rule, ChoiceRule) and rule.derive == "multi_image":
            wanted = image_count > 1
            if rule.name in options and options[rule.name] is not wanted:
                raise GeneratorRefused(
                    f"{gen.key}: {rule.name} must be {wanted} for {image_count} "
                    f"{_images_word(image_count)} (fal bills more than one image as multi-view); "
                    "leave the option out and the client sets it"
                )
            derived[rule.name] = wanted
    return derived


# --- loading ---


def _fail(path: Path, where: str, why: str) -> ValueError:
    return ValueError(f"{path.name}: {where}: {why}")


def _table(path: Path, where: str, value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _fail(path, where, "expected a table")
    return cast(dict[str, object], value)


def _only(path: Path, where: str, table: dict[str, object], allowed: set[str]) -> None:
    for key in table:
        if key not in allowed:
            raise _fail(path, where, f"unknown key {key!r}")


def _get(
    path: Path, where: str, table: dict[str, object], key: str, kind: type, *, need: bool = True
) -> object:
    if key not in table:
        if need:
            raise _fail(path, where, f"missing {key!r}")
        return None
    value = table[key]
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise _fail(path, where, f"{key!r} must be a {kind.__name__}")
    return value


def _text(path: Path, where: str, table: dict[str, object], key: str) -> str:
    return cast(str, _get(path, where, table, key, str))


def _count(path: Path, where: str, table: dict[str, object], key: str) -> int:
    value = cast(int, _get(path, where, table, key, int))
    if value < 0:
        raise _fail(path, where, f"{key!r} must not be negative")
    return value


def _flag(path: Path, where: str, table: dict[str, object], key: str, *, default: bool) -> bool:
    if key not in table:
        return default
    return cast(bool, _get(path, where, table, key, bool))


def _strings(
    path: Path, where: str, table: dict[str, object], key: str, *, need: bool
) -> tuple[str, ...]:
    raw = _get(path, where, table, key, list, need=need)
    if raw is None:
        return ()
    items = cast(list[object], raw)
    if not all(isinstance(item, str) for item in items):
        raise _fail(path, where, f"{key!r} must be a list of strings")
    return tuple(cast(list[str], items))


def _string_map(path: Path, where: str, table: dict[str, object], key: str) -> dict[str, str]:
    if key not in table:
        return {}
    raw = _table(path, f"{where}.{key}", table[key])
    if not all(isinstance(value, str) for value in raw.values()):
        raise _fail(path, f"{where}.{key}", "every value must be a string")
    return cast(dict[str, str], raw)


def _amount(path: Path, where: str, table: dict[str, object], key: str) -> Decimal:
    text = _text(path, where, table, key)
    if not _AMOUNT.fullmatch(text):
        raise _fail(
            path, where, f"{key!r} must be a plain non-negative decimal string, got {text!r}"
        )
    return Decimal(text)


def _scalar(path: Path, where: str, value: object) -> Scalar:
    if isinstance(value, bool | int | str):
        return value
    raise _fail(path, where, "a value must be a boolean, an integer or a string")


def _choice(path: Path, where: str, table: dict[str, object], name: str) -> ChoiceRule:
    _only(path, where, table, {"name", "default", "derive", "values"})
    raw_values = _get(path, where, table, "values", list)
    values: list[OptionValue] = []
    for index, raw in enumerate(cast(list[object], raw_values)):
        here = f"{where}.values[{index}]"
        entry = _table(path, here, raw)
        _only(path, here, entry, {"value", "add", "fields"})
        if "value" not in entry:
            raise _fail(path, here, "missing 'value'")
        fields = _table(path, f"{here}.fields", entry.get("fields", {}))
        values.append(
            OptionValue(
                _scalar(path, here, entry["value"]), _amount(path, here, entry, "add"), fields
            )
        )
    if not values:
        raise _fail(path, where, "an option needs at least one value")
    default: OptionValue | None = None
    if "default" in table:
        wanted = _scalar(path, where, table["default"])
        matches = [value for value in values if _same(value.value, wanted)]
        if not matches:
            raise _fail(path, where, f"default {wanted!r} is not one of the values")
        default = matches[0]
    derive = table.get("derive")
    if derive is not None and derive != "multi_image":
        raise _fail(path, where, f"unknown derive {derive!r}")
    return ChoiceRule(name, tuple(values), default, cast(Literal["multi_image"] | None, derive))


def _range(path: Path, where: str, table: dict[str, object], name: str) -> RangeRule:
    _only(path, where, table, {"name", "field", "min", "max", "add"})
    field = _text(path, where, table, "field")
    if not _FIELD.fullmatch(field):
        raise _fail(path, where, f"field {field!r} is not a field name")
    low, high = _count(path, where, table, "min"), _count(path, where, table, "max")
    if low > high:
        raise _fail(path, where, "min is above max")
    return RangeRule(name, field, low, high, _amount(path, where, table, "add"))


def _price(path: Path, where: str, raw: object) -> PriceRules:
    table = _table(path, where, raw)
    _only(path, where, table, {"base", "free", "options"})
    free = _strings(path, where, table, "free", need=True)
    rules: dict[str, OptionRule] = {}
    for index, item in enumerate(cast(list[object], table.get("options", []))):
        here = f"{where}.options[{index}]"
        entry = _table(path, here, item)
        name = _text(path, here, entry, "name")
        if not _FIELD.fullmatch(name):
            raise _fail(path, here, f"name {name!r} is not an option name")
        if name in rules:
            raise _fail(path, here, f"option {name!r} appears twice")
        rules[name] = (
            _range(path, here, entry, name) if "min" in entry else _choice(path, here, entry, name)
        )
    for name in free:
        if not _FIELD.fullmatch(name) or name in rules:
            raise _fail(path, where, f"free field {name!r} is not a field name, or is also priced")
    return PriceRules(_amount(path, where, table, "base"), MappingProxyType(rules), frozenset(free))


_GENERATOR_KEYS = {
    "endpoint", "kind", "input_kind", "min_images", "max_images", "slot_order", "image_field",
    "mesh_field", "slot_fields", "view_slots", "max_mesh_bytes", "result_field", "experiment_only",
    "price", "requires_host_country", "positional", "required_slots", "source", "checked",
}  # fmt: skip


def _generator(path: Path, key: str, raw: object) -> Generator:
    where = f"[generators.{key}]"
    table = _table(path, where, raw)
    _only(path, where, table, _GENERATOR_KEYS)
    endpoint = _text(path, where, table, "endpoint")
    if not _ENDPOINT.fullmatch(endpoint):
        raise _fail(path, where, f"endpoint {endpoint!r} is not a fal endpoint id")
    if _forbidden_reason(endpoint):
        raise GeneratorRefused(f"{path.name}: {where}: endpoint {endpoint!r}: {_EXCLUDED_FAMILIES}")
    requires_host_country = _flag(path, where, table, "requires_host_country", default=False)
    if "hunyuan" in endpoint.lower() and not requires_host_country:
        # The territory rule hangs on this flag, not on the endpoint, so an entry that names a
        # Hunyuan endpoint without it would run on an EU, UK or South Korea host.
        raise GeneratorRefused(
            f"{path.name}: {where}: a Hunyuan endpoint ({endpoint!r}) must set "
            "requires_host_country = true: Tencent's territory limit applies to it"
        )
    kind = _text(path, where, table, "kind")
    input_kind = _text(path, where, table, "input_kind")
    if kind not in ("image-to-3d", "segment", "image-edit"):
        raise _fail(path, where, f"unknown kind {kind!r}")
    if input_kind not in ("images", "mesh"):
        raise _fail(path, where, f"unknown input_kind {input_kind!r}")

    slot_order = _strings(path, where, table, "slot_order", need=input_kind == "images")
    slot_fields = _string_map(path, where, table, "slot_fields")
    view_slots = _string_map(path, where, table, "view_slots")
    required = _strings(path, where, table, "required_slots", need=False)
    image_field = cast("str | None", _get(path, where, table, "image_field", str, need=False))
    mesh_field = cast("str | None", _get(path, where, table, "mesh_field", str, need=False))
    max_mesh = cast("int | None", _get(path, where, table, "max_mesh_bytes", int, need=False))
    min_images, max_images = (
        _count(path, where, table, "min_images"),
        _count(path, where, table, "max_images"),
    )
    if min_images > max_images:
        raise _fail(path, where, "min_images is above max_images")
    if len(set(slot_order)) != len(slot_order):
        raise _fail(path, where, "slot_order repeats a slot")
    if not set(required) <= set(slot_order) or not set(view_slots.values()) <= set(slot_order):
        raise _fail(path, where, "required_slots and view_slots must name slots in slot_order")
    if input_kind == "mesh":
        if not mesh_field or not max_mesh or image_field or slot_fields or max_images:
            raise _fail(
                path, where, "a mesh generator needs mesh_field and max_mesh_bytes, and no images"
            )
    else:
        if mesh_field or max_mesh or min_images < 1:
            raise _fail(path, where, "an images generator takes at least one image and no mesh")
        if bool(image_field) == bool(slot_fields):
            raise _fail(
                path,
                where,
                "set image_field (a list) or slot_fields (labeled), not both or neither",
            )
        if slot_fields and set(slot_fields) != set(slot_order):
            differing = ", ".join(repr(slot) for slot in sorted(set(slot_fields) ^ set(slot_order)))
            raise _fail(path, where, f"slot_fields and slot_order differ on {differing}")
    for field in (
        image_field,
        mesh_field,
        _text(path, where, table, "result_field"),
        *slot_fields.values(),
    ):
        if field is not None and not _FIELD.fullmatch(field):
            raise _fail(path, where, f"{field!r} is not a field name")

    return Generator(
        key=key,
        endpoint=endpoint,
        kind=kind,
        input_kind=input_kind,
        min_images=min_images,
        max_images=max_images,
        slot_order=slot_order,
        image_field=image_field,
        mesh_field=mesh_field,
        slot_fields=MappingProxyType(slot_fields),
        view_slots=MappingProxyType(view_slots),
        max_mesh_bytes=max_mesh,
        result_field=_text(path, where, table, "result_field"),
        experiment_only=_flag(path, where, table, "experiment_only", default=False),
        price=_price(path, f"{where}.price", table.get("price")),
        requires_host_country=requires_host_country,
        positional=_flag(path, where, table, "positional", default=False),
        required_slots=required,
        source=_text(path, where, table, "source"),
        checked=_text(path, where, table, "checked"),
    )


def load_generators(path: Path) -> dict[str, Generator]:
    """Load `generators.toml`. Anything unexpected raises `ValueError` naming the entry: an
    unknown key, a missing field, an endpoint used twice, a default that is not a value, a price
    that is not a plain decimal string. A forbidden endpoint raises `GeneratorRefused`."""
    try:
        document = tomllib.loads(path.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"{path.name}: could not read the registry: {error}") from error
    top = _table(path, "top level", cast(object, document))
    _only(path, "top level", top, {"generators"})
    entries = _table(path, "[generators]", top.get("generators"))
    registry: dict[str, Generator] = {}
    seen: dict[str, str] = {}
    for key, raw in entries.items():
        if not _GENERATOR_KEY.fullmatch(key):
            raise _fail(path, "[generators]", f"key {key!r} is not a generator key")
        gen = _generator(path, key, raw)
        if gen.endpoint in seen:
            raise _fail(
                path,
                f"[generators.{key}]",
                f"endpoint {gen.endpoint!r} is used twice (also by {seen[gen.endpoint]})",
            )
        seen[gen.endpoint] = key
        registry[key] = gen
    return registry
