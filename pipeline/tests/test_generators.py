"""Tests for the generator registry: endpoint ids, price rules, host policy and input checks.

Nothing here touches the network. The registry under test is the real `pipeline/generators.toml`,
so a price or an endpoint id edited there without the research behind it fails here.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from m3_pipeline.stages.lib.generators import (
    VIEW_ALIASES,
    GeneratorRefused,
    PriceUnknown,
    check_endpoint_allowed,
    check_inputs,
    check_policy,
    load_generators,
    price_usd,
    request_fields,
    with_derived_options,
)

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "generators.toml"
GENERATORS = load_generators(REGISTRY_PATH)

RESEARCH_ENDPOINTS = {
    "rodin-fast": "fal-ai/hyper3d/rodin/v2.5/fast",
    "rodin-2.5": "fal-ai/hyper3d/rodin/v2.5",
    "tripo-h3.1": "tripo3d/h3.1/multiview-to-3d",
    "meshy-7.1": "fal-ai/meshy/v7.1/multi-image-to-3d",
    "hunyuan-3.1-pro": "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d",
    "trellis-2": "fal-ai/trellis-2",
    "tripo-segment": "tripo3d/tripo/segment",
}


def write_registry(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "generators.toml"
    path.write_text(text, "utf-8")
    return path


# --- the registry ---


def test_registry_endpoint_ids_match_the_research() -> None:
    # A later `image-edit` entry is allowed; the seven research ids are fixed, verbatim.
    registered = {key: gen.endpoint for key, gen in GENERATORS.items() if gen.kind != "image-edit"}
    assert registered == RESEARCH_ENDPOINTS


def test_the_image_edit_fallback_stays_off() -> None:
    assert not [gen for gen in GENERATORS.values() if gen.kind == "image-edit"]


def test_only_hunyuan_is_experiment_only_and_needs_a_host_country() -> None:
    assert {key for key, gen in GENERATORS.items() if gen.experiment_only} == {"hunyuan-3.1-pro"}
    assert {key for key, gen in GENERATORS.items() if gen.requires_host_country} == {
        "hunyuan-3.1-pro"
    }


def test_registry_field_names_match_the_live_schemas_read_on_2026_11_23() -> None:
    # Field names from each endpoint's llms.txt page, read 2026-11-23. A rename on fal's side
    # shows up as a failed call, so this pins what the client sends.
    shape = {
        key: (gen.image_field, gen.mesh_field, gen.result_field, dict(gen.slot_fields))
        for key, gen in GENERATORS.items()
    }
    assert shape["rodin-fast"] == ("image_urls", None, "model_mesh", {})
    assert shape["rodin-2.5"] == ("image_urls", None, "model_mesh", {})
    assert shape["tripo-h3.1"] == ("image_urls", None, "model_mesh", {})
    assert shape["meshy-7.1"] == ("image_urls", None, "model_glb", {})
    assert shape["trellis-2"] == (None, None, "model_glb", {"front_34": "image_url"})
    assert shape["tripo-segment"] == (None, "mesh_url", "model_mesh", {})
    assert shape["hunyuan-3.1-pro"] == (
        None,
        None,
        "model_glb",
        {
            "front": "input_image_url",
            "back": "back_image_url",
            "left": "left_image_url",
            "right": "right_image_url",
            "top": "top_image_url",
            "bottom": "bottom_image_url",
            "left-front 45": "left_front_image_url",
            "right-front 45": "right_front_image_url",
        },
    )


def test_every_entry_records_where_and_when_it_was_read() -> None:
    for gen in GENERATORS.values():
        assert gen.source.startswith("https://fal.ai/models/")
        assert gen.source.endswith("/llms.txt")
        assert gen.checked == "2026-11-23"


def test_slot_tables_match_the_plan() -> None:
    assert GENERATORS["rodin-2.5"].slot_order == ("front_34", "rear_34", "side", "front", "rear")
    assert GENERATORS["rodin-fast"].slot_order == GENERATORS["rodin-2.5"].slot_order
    assert GENERATORS["tripo-h3.1"].slot_order == ("front", "side", "rear")
    assert GENERATORS["meshy-7.1"].slot_order == ("front", "side", "rear", "front_34")
    assert GENERATORS["trellis-2"].slot_order == ("front_34",)
    assert GENERATORS["hunyuan-3.1-pro"].slot_order[:4] == (
        "front",
        "back",
        "left",
        "left-front 45",
    )
    assert dict(GENERATORS["hunyuan-3.1-pro"].view_slots) == {
        "rear": "back",
        "side": "left",
        "front_34": "left-front 45",
    }


def test_view_aliases_fold_the_real_views_into_slots() -> None:
    assert dict(VIEW_ALIASES) == {
        "front_34_left": "front_34",
        "front_34_right": "front_34",
        "rear_34_left": "rear_34",
        "rear_34_right": "rear_34",
        "side_left": "side",
        "side_right": "side",
        "front": "front",
        "rear": "rear",
    }


def test_loading_the_registry_twice_gives_equal_entries() -> None:
    assert load_generators(REGISTRY_PATH) == GENERATORS


# --- the price table ---


@pytest.mark.parametrize(
    ("key", "options", "usd"),
    [
        ("rodin-fast", {}, "0.10"),
        ("rodin-2.5", {}, "0.40"),
        ("rodin-2.5", {"highpack": True}, "1.20"),
        ("tripo-h3.1", {"texture": "none"}, "0.20"),
        ("tripo-h3.1", {"texture": "standard"}, "0.30"),
        ("tripo-h3.1", {"texture": "hd"}, "0.40"),
        ("tripo-h3.1", {"texture": "hd", "detailed_geometry": True, "quad": True}, "0.65"),
        ("meshy-7.1", {"textured": False}, "0.80"),
        ("meshy-7.1", {"textured": True}, "1.20"),
        ("hunyuan-3.1-pro", {}, "0.375"),
        ("hunyuan-3.1-pro", {"pbr": True, "multi_view": True}, "0.675"),
        (
            "hunyuan-3.1-pro",
            {"pbr": True, "multi_view": True, "face_count": 400000},
            "0.825",
        ),
        ("trellis-2", {"resolution": 512}, "0.25"),
        ("trellis-2", {"resolution": 1024}, "0.30"),
        ("trellis-2", {"resolution": 1536}, "0.35"),
        ("tripo-segment", {}, "0.40"),
    ],
)
def test_price_table_matches_the_research(key: str, options: dict[str, object], usd: str) -> None:
    price = price_usd(GENERATORS[key], options)
    assert price == Decimal(usd)
    assert isinstance(price, Decimal)


@pytest.mark.parametrize(
    ("key", "usd"),
    [("tripo-h3.1", "0.30"), ("meshy-7.1", "1.20"), ("trellis-2", "0.30"), ("rodin-2.5", "0.40")],
)
def test_an_option_left_out_is_priced_at_fals_default(key: str, usd: str) -> None:
    # Pricing `{}` as the cheapest tier would authorize less than fal charges: Tripo textures,
    # Meshy textures and TRELLIS at 1024 are all on by default.
    assert price_usd(GENERATORS[key], {}) == Decimal(usd)


def test_unpriced_option_is_refused() -> None:
    # The research found Meshy's fal price for 2k geometry unconfirmed, so it has no rule.
    with pytest.raises(PriceUnknown, match="geometry_resolution"):
        price_usd(GENERATORS["meshy-7.1"], {"geometry_resolution": "2k"})


def test_the_priced_standard_geometry_is_accepted() -> None:
    assert price_usd(GENERATORS["meshy-7.1"], {"geometry_resolution": "standard"}) == Decimal(
        "1.20"
    )


@pytest.mark.parametrize(
    ("key", "options"),
    [
        ("rodin-fast", {"highpack": True}),  # the fast schema has no HighPack field
        ("meshy-7.1", {"enable_rigging": True}),  # priced on fal, unlisted here
        ("meshy-7.1", {"enable_animation": True}),
        ("rodin-2.5", {"hd_texture": True}),  # not in fal's price text, so not known free
        ("tripo-segment", {"seed": 1}),
        ("rodin-2.5", {"enable_safety_checker": False}),
        ("hunyuan-3.1-pro", {"generate_type": "Geometry"}),
        # Rodin's quality levers are absent from fal's price text, which names only HighPack, and
        # nothing has confirmed they are free: they fail closed until a live invoice does.
        ("rodin-2.5", {"tier": "Gen-2.5-Extreme-High"}),
        ("rodin-2.5", {"quality_mesh_option": "2M Triangle"}),
        ("rodin-2.5", {"texture_mode": "high"}),
        ("rodin-2.5", {"material": "PBR"}),
        ("rodin-fast", {"tier": "Gen-2.5-Low"}),
        ("rodin-fast", {"quality_mesh_option": "Auto"}),
        ("rodin-fast", {"texture_mode": "low"}),
        ("rodin-fast", {"material": "Shaded"}),
    ],
)
def test_an_option_with_no_price_rule_is_refused(key: str, options: dict[str, object]) -> None:
    with pytest.raises(PriceUnknown, match=next(iter(options))):
        price_usd(GENERATORS[key], options)


@pytest.mark.parametrize(
    ("key", "options"),
    [
        ("tripo-h3.1", {"texture": "ultra"}),
        ("tripo-h3.1", {"texture": True}),
        ("trellis-2", {"resolution": 2048}),
        ("trellis-2", {"resolution": "1024"}),
        ("trellis-2", {"resolution": True}),  # True == 1 in Python; not a resolution
        ("trellis-2", {"resolution": 1024.0}),
        ("rodin-2.5", {"highpack": 1}),  # 1 == True in Python; not a bool
        ("rodin-2.5", {"highpack": "yes"}),
        ("hunyuan-3.1-pro", {"face_count": 39999}),
        ("hunyuan-3.1-pro", {"face_count": 1500001}),
        ("hunyuan-3.1-pro", {"face_count": True}),
        ("hunyuan-3.1-pro", {"face_count": "400000"}),
    ],
)
def test_a_value_outside_the_priced_values_is_refused(key: str, options: dict[str, object]) -> None:
    with pytest.raises(PriceUnknown, match=next(iter(options))):
        price_usd(GENERATORS[key], options)


def test_free_options_do_not_change_the_price() -> None:
    free = {"seed": 7, "geometry_file_format": "glb", "use_original_alpha": True}
    assert price_usd(GENERATORS["rodin-2.5"], free) == Decimal("0.40")
    assert price_usd(GENERATORS["rodin-fast"], free) == Decimal("0.10")


# --- the request fields ---


def test_option_names_become_fals_field_names() -> None:
    fields = request_fields(
        GENERATORS["tripo-h3.1"], {"texture": "hd", "detailed_geometry": True, "quad": True}
    )
    assert fields == {
        "texture": True,
        "texture_quality": "detailed",
        "geometry_quality": "detailed",
        "quad": True,
    }


def test_rodin_highpack_is_fals_addons_object_not_a_list() -> None:
    assert request_fields(GENERATORS["rodin-2.5"], {"highpack": True}) == {
        "addons": {"high_pack": True}
    }
    assert request_fields(GENERATORS["rodin-2.5"], {}) == {}


def test_a_default_is_sent_as_well_as_priced() -> None:
    # The price covers exactly what is sent: if fal moved a default tomorrow, the priced value
    # would still be the one requested.
    assert request_fields(GENERATORS["trellis-2"], {}) == {"resolution": 1024}
    assert request_fields(GENERATORS["meshy-7.1"], {}) == {
        "should_texture": True,
        "geometry_resolution": "standard",
    }
    assert request_fields(GENERATORS["tripo-h3.1"], {}) == {
        "texture": True,
        "texture_quality": "standard",
        "geometry_quality": "standard",
        "quad": False,
    }


def test_no_texture_turns_pbr_off_too() -> None:
    # fal: `pbr` defaults to true and "if true, texture is also enabled".
    fields = request_fields(GENERATORS["tripo-h3.1"], {"texture": "none"})
    assert fields["texture"] is False
    assert fields["pbr"] is False


def test_an_option_that_contradicts_another_is_refused() -> None:
    with pytest.raises(GeneratorRefused, match="pbr"):
        request_fields(GENERATORS["tripo-h3.1"], {"texture": "none", "pbr": True})


def test_free_options_pass_through_unchanged() -> None:
    fields = request_fields(GENERATORS["trellis-2"], {"seed": 3, "remesh": False})
    assert fields == {"resolution": 1024, "seed": 3, "remesh": False}


def test_a_free_option_must_be_a_json_scalar() -> None:
    with pytest.raises(GeneratorRefused, match="seed"):
        request_fields(GENERATORS["trellis-2"], {"seed": [1, 2]})


def test_face_count_is_sent_only_when_set() -> None:
    assert "face_count" not in request_fields(GENERATORS["hunyuan-3.1-pro"], {})
    fields = request_fields(GENERATORS["hunyuan-3.1-pro"], {"face_count": 400000})
    assert fields["face_count"] == 400000


def test_request_fields_refuses_what_price_usd_refuses() -> None:
    with pytest.raises(PriceUnknown):
        request_fields(GENERATORS["meshy-7.1"], {"geometry_resolution": "2k"})


# --- multi-view is derived from the image count ---


def test_a_multi_image_hunyuan_call_is_priced_as_multi_view() -> None:
    options = with_derived_options(GENERATORS["hunyuan-3.1-pro"], {"pbr": True}, image_count=4)
    assert options == {"pbr": True, "multi_view": True}
    assert price_usd(GENERATORS["hunyuan-3.1-pro"], options) == Decimal("0.675")


def test_a_single_image_hunyuan_call_is_not_multi_view() -> None:
    options = with_derived_options(GENERATORS["hunyuan-3.1-pro"], {}, image_count=1)
    assert options == {"multi_view": False}
    assert price_usd(GENERATORS["hunyuan-3.1-pro"], options) == Decimal("0.375")


def test_a_multi_view_option_that_disagrees_with_the_image_count_is_refused() -> None:
    with pytest.raises(GeneratorRefused, match="multi_view"):
        with_derived_options(GENERATORS["hunyuan-3.1-pro"], {"multi_view": False}, image_count=2)
    with pytest.raises(GeneratorRefused, match="multi_view"):
        with_derived_options(GENERATORS["hunyuan-3.1-pro"], {"multi_view": True}, image_count=1)


def test_generators_without_a_derived_option_keep_their_options() -> None:
    options = {"highpack": True}
    assert with_derived_options(GENERATORS["rodin-2.5"], options, image_count=5) == options


# --- policy: Hunyuan and the host country ---


def test_hunyuan_needs_an_explicit_host_country() -> None:
    for missing in (None, "", "   "):
        with pytest.raises(GeneratorRefused, match="M3_HOST_COUNTRY"):
            check_policy(GENERATORS["hunyuan-3.1-pro"], host_country=missing)


@pytest.mark.parametrize("country", ["DE", "FR", "GB", "KR", "de", " fr ", "UK", "EL", "IE", "SE"])
def test_hunyuan_is_refused_in_eu_uk_and_south_korea(country: str) -> None:
    with pytest.raises(GeneratorRefused, match="EU, UK or South Korea"):
        check_policy(GENERATORS["hunyuan-3.1-pro"], host_country=country)


@pytest.mark.parametrize("country", ["US", "us", "CA", "JP", "AU"])
def test_hunyuan_is_allowed_in_the_us(country: str) -> None:
    check_policy(GENERATORS["hunyuan-3.1-pro"], host_country=country)


def test_all_27_eu_members_are_refused() -> None:
    members = [
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
    ]
    assert len(members) == 27
    for country in members:
        with pytest.raises(GeneratorRefused):
            check_policy(GENERATORS["hunyuan-3.1-pro"], host_country=country)


@pytest.mark.parametrize("country", ["USA", "U", "1", "United States", "U S"])
def test_a_host_country_that_is_not_a_two_letter_code_is_refused(country: str) -> None:
    with pytest.raises(GeneratorRefused, match="two-letter"):
        check_policy(GENERATORS["hunyuan-3.1-pro"], host_country=country)


def test_other_generators_need_no_host_country() -> None:
    for key, gen in GENERATORS.items():
        if key != "hunyuan-3.1-pro":
            check_policy(gen, host_country=None)
            check_policy(gen, host_country="DE")


# --- policy: which endpoints may be called ---


@pytest.mark.parametrize("endpoint", sorted(RESEARCH_ENDPOINTS.values()))
def test_every_registry_endpoint_is_allowed(endpoint: str) -> None:
    check_endpoint_allowed(endpoint, GENERATORS)


@pytest.mark.parametrize(
    "endpoint",
    [
        "fal-ai/hunyuan3d/v2/multi-view",
        "fal-ai/hunyuan3d/v2",
        "fal-ai/hunyuan3d/v2.1",
        "hitem3d/hi3d/v3.0/multi-view-to-3d",
        "hitem3d/hi3d/split",
    ],
)
def test_open_weights_hunyuan_v2_and_hi3d_endpoints_are_refused(endpoint: str) -> None:
    with pytest.raises(GeneratorRefused) as refused:
        check_endpoint_allowed(endpoint, GENERATORS)
    message = str(refused.value)
    assert "hunyuan3d/v2" in message
    assert "hitem3d/" in message


@pytest.mark.parametrize(
    "endpoint",
    [
        "fal-ai/flux/dev",
        "fal-ai/hyper3d/rodin/v2.5/",  # near misses are not the registry's endpoint
        "fal-ai/hyper3d/rodin/v2.5/../v2",
        "FAL-AI/TRELLIS-2",
        "",
    ],
)
def test_an_endpoint_outside_the_registry_is_refused(endpoint: str) -> None:
    with pytest.raises(GeneratorRefused, match="registry"):
        check_endpoint_allowed(endpoint, GENERATORS)


def test_the_loader_refuses_a_forbidden_endpoint_in_the_file(tmp_path: Path) -> None:
    text = REGISTRY_PATH.read_text("utf-8").replace(
        'endpoint = "fal-ai/trellis-2"', 'endpoint = "fal-ai/hunyuan3d/v2/multi-view"'
    )
    with pytest.raises(GeneratorRefused, match="hunyuan3d/v2"):
        load_generators(write_registry(tmp_path, text))


# --- the loader refuses a malformed registry ---


def test_the_loader_refuses_an_unknown_key(tmp_path: Path) -> None:
    text = REGISTRY_PATH.read_text("utf-8").replace(
        'endpoint = "fal-ai/trellis-2"', 'endpoint = "fal-ai/trellis-2"\nsurprise = 1'
    )
    with pytest.raises(ValueError, match="surprise"):
        load_generators(write_registry(tmp_path, text))


def test_the_loader_refuses_a_missing_endpoint_naming_the_entry(tmp_path: Path) -> None:
    text = REGISTRY_PATH.read_text("utf-8").replace('endpoint = "fal-ai/trellis-2"\n', "")
    with pytest.raises(ValueError, match=r"trellis-2.*endpoint"):
        load_generators(write_registry(tmp_path, text))


def test_the_loader_refuses_two_entries_for_one_endpoint(tmp_path: Path) -> None:
    text = REGISTRY_PATH.read_text("utf-8").replace(
        'endpoint = "fal-ai/trellis-2"', 'endpoint = "fal-ai/hyper3d/rodin/v2.5"'
    )
    with pytest.raises(ValueError, match="twice"):
        load_generators(write_registry(tmp_path, text))


def test_the_loader_refuses_a_price_that_is_not_a_plain_decimal(tmp_path: Path) -> None:
    text = REGISTRY_PATH.read_text("utf-8").replace('base = "0.25"', 'base = "-0.25"')
    with pytest.raises(ValueError, match="base"):
        load_generators(write_registry(tmp_path, text))
    text = REGISTRY_PATH.read_text("utf-8").replace('base = "0.25"', "base = 0.25")
    with pytest.raises(ValueError, match="base"):
        load_generators(write_registry(tmp_path, text))


def test_the_loader_refuses_a_default_that_is_not_one_of_the_values(tmp_path: Path) -> None:
    text = REGISTRY_PATH.read_text("utf-8").replace("default = 1024", "default = 2048")
    with pytest.raises(ValueError, match="default"):
        load_generators(write_registry(tmp_path, text))


def test_the_loader_refuses_a_free_field_that_is_also_priced(tmp_path: Path) -> None:
    text = REGISTRY_PATH.read_text("utf-8").replace(
        'free = ["seed", "texture_size", "decimation_target", "remesh"]',
        'free = ["seed", "resolution"]',
    )
    with pytest.raises(ValueError, match="resolution"):
        load_generators(write_registry(tmp_path, text))


def test_the_loader_refuses_a_slot_field_for_an_unknown_slot(tmp_path: Path) -> None:
    text = REGISTRY_PATH.read_text("utf-8").replace(
        'front_34 = "image_url"', 'sideways = "image_url"'
    )
    with pytest.raises(ValueError, match="sideways"):
        load_generators(write_registry(tmp_path, text))


def test_the_loader_refuses_a_file_that_is_not_toml(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="generators.toml"):
        load_generators(write_registry(tmp_path, "[generators\n"))


# --- inputs: counts, slots and mesh ---


def test_image_count_is_checked_against_the_generator_limits() -> None:
    four = ("front", "side", "rear", "front_34")
    with pytest.raises(GeneratorRefused, match="takes 2 to 4 images"):
        check_inputs(GENERATORS["tripo-h3.1"], slots=(*four, "front"), has_mesh=False)  # 5
    with pytest.raises(GeneratorRefused, match="takes 2 to 4 images"):
        check_inputs(GENERATORS["tripo-h3.1"], slots=("front",), has_mesh=False)  # 1
    with pytest.raises(GeneratorRefused, match="takes 1 image"):
        check_inputs(GENERATORS["trellis-2"], slots=("front_34", "front_34"), has_mesh=False)
    with pytest.raises(GeneratorRefused, match="takes 1 to 5 images"):
        check_inputs(
            GENERATORS["rodin-2.5"],
            slots=("front_34", "rear_34", "side", "front", "rear", "front"),
            has_mesh=False,
        )
    with pytest.raises(GeneratorRefused, match="at least 1|takes 1 to 5"):
        check_inputs(GENERATORS["rodin-2.5"], slots=(), has_mesh=False)


def test_the_limits_allow_the_planned_sets() -> None:
    check_inputs(GENERATORS["rodin-2.5"], slots=GENERATORS["rodin-2.5"].slot_order, has_mesh=False)
    check_inputs(GENERATORS["tripo-h3.1"], slots=("front", "side", "rear"), has_mesh=False)
    check_inputs(
        GENERATORS["meshy-7.1"], slots=("front", "side", "rear", "front_34"), has_mesh=False
    )
    check_inputs(GENERATORS["trellis-2"], slots=("front_34",), has_mesh=False)
    check_inputs(
        GENERATORS["hunyuan-3.1-pro"],
        slots=("front", "back", "left", "left-front 45"),
        has_mesh=False,
    )


def test_a_mesh_generator_takes_one_mesh_and_no_images() -> None:
    gen = GENERATORS["tripo-segment"]
    assert check_inputs(gen, slots=(), has_mesh=True) == ()
    with pytest.raises(GeneratorRefused, match="no images"):
        check_inputs(gen, slots=("front",), has_mesh=True)
    with pytest.raises(GeneratorRefused, match="needs a mesh"):
        check_inputs(gen, slots=(), has_mesh=False)


def test_an_images_generator_refuses_a_mesh() -> None:
    with pytest.raises(GeneratorRefused, match="takes images, not a mesh"):
        check_inputs(GENERATORS["rodin-2.5"], slots=("front_34",), has_mesh=True)


def test_an_unknown_or_repeated_slot_is_refused() -> None:
    with pytest.raises(GeneratorRefused, match="rear_34"):
        check_inputs(GENERATORS["tripo-h3.1"], slots=("front", "rear_34"), has_mesh=False)
    with pytest.raises(GeneratorRefused, match="twice"):
        check_inputs(GENERATORS["rodin-2.5"], slots=("front", "front"), has_mesh=False)


def test_a_required_slot_must_be_present() -> None:
    with pytest.raises(GeneratorRefused, match="front"):
        check_inputs(GENERATORS["hunyuan-3.1-pro"], slots=("back", "left"), has_mesh=False)
    with pytest.raises(GeneratorRefused, match="front"):
        check_inputs(GENERATORS["meshy-7.1"], slots=("side", "rear"), has_mesh=False)


def test_a_positional_list_refuses_a_gap() -> None:
    # fal's Tripo list is [front, left, back, right]: front and rear alone would put the rear
    # image in the left slot.
    with pytest.raises(GeneratorRefused, match="positional"):
        check_inputs(GENERATORS["tripo-h3.1"], slots=("front", "rear"), has_mesh=False)
    check_inputs(GENERATORS["tripo-h3.1"], slots=("front", "side"), has_mesh=False)
    check_inputs(GENERATORS["tripo-h3.1"], slots=("side", "front"), has_mesh=False)  # any order


def test_check_inputs_returns_the_send_order() -> None:
    gen = GENERATORS["rodin-2.5"]
    slots = ("rear", "front_34", "side")
    order = check_inputs(gen, slots=slots, has_mesh=False)
    assert [slots[i] for i in order] == ["front_34", "side", "rear"]


def test_a_gap_in_a_priority_list_is_allowed() -> None:
    check_inputs(GENERATORS["rodin-2.5"], slots=("front_34", "rear"), has_mesh=False)


def test_a_forbidden_endpoint_is_refused_even_when_a_registry_entry_names_it() -> None:
    import dataclasses

    rogue = dataclasses.replace(GENERATORS["rodin-2.5"], endpoint="fal-ai/hunyuan3d/v2/multi-view")
    registry = {**GENERATORS, "rogue": rogue}
    with pytest.raises(GeneratorRefused, match="hitem3d/"):
        check_endpoint_allowed(rogue.endpoint, registry)


@pytest.mark.parametrize(
    "endpoint",
    ["fal-ai/hunyuan-3d/v3.1/pro/image-to-3d", "fal-ai/hunyuan-3d/v3.2/pro/image-to-3d"],
)
def test_the_loader_refuses_a_hunyuan_endpoint_without_the_host_country_flag(
    tmp_path: Path, endpoint: str
) -> None:
    # The territory rule hangs on a data flag, so an entry that names a Hunyuan endpoint without
    # it would run on an EU host. The loader refuses it.
    text = REGISTRY_PATH.read_text("utf-8").replace(
        'endpoint = "fal-ai/trellis-2"', f'endpoint = "{endpoint}"'
    )
    with pytest.raises(GeneratorRefused, match="requires_host_country"):
        load_generators(write_registry(tmp_path, text))


def test_the_loader_accepts_a_hunyuan_endpoint_with_the_flag(tmp_path: Path) -> None:
    text = (
        REGISTRY_PATH.read_text("utf-8")
        .replace(
            'endpoint = "fal-ai/trellis-2"', 'endpoint = "fal-ai/hunyuan-3d/v3.2/pro/image-to-3d"'
        )
        .replace(
            'kind = "image-to-3d"\ninput_kind = "images"\nmin_images = 1\nmax_images = 1\n',
            'kind = "image-to-3d"\ninput_kind = "images"\nmin_images = 1\nmax_images = 1\n'
            "requires_host_country = true\n",
        )
    )
    loaded = load_generators(write_registry(tmp_path, text))
    assert loaded["trellis-2"].requires_host_country
