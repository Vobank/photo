"""People get the realism recipe; scenes without people never do (it adds strangers)."""

import pytest

from photo.styles import (
    PEOPLE_REALISM,
    PEOPLE_REALISM_SHORT,
    apply_style,
    get_style,
    mentions_people,
)


@pytest.mark.parametrize(
    "text",
    [
        "an elderly woman cooking soup",
        "a 30-year-old man in a subway car",
        "a family having dinner in the garden",
        "she smiles at the camera",
        "Portrait of a fisherman",
        "девушка пьёт кофе у окна",
        "вечерняя улица, прохожие",
        "семья за столом",
        "портрет мужчины крупным планом",
    ],
)
def test_people_are_recognised(text: str) -> None:
    assert mentions_people(text)


@pytest.mark.parametrize(
    "text",
    [
        "a mountain lake at sunrise",
        "a cup of coffee on a wooden table",
        "a red sports car on a city street",
        "a modern living room interior",
        "manhole cover on the street",
        "a mannequin in a shop window",
        "кот на подоконнике",
        "закат над морем",
    ],
)
def test_scenes_without_people_are_left_alone(text: str) -> None:
    assert not mentions_people(text)


def test_photo_recipe_switches_for_people() -> None:
    photo = get_style("photo")
    with_people = apply_style("an old man reading", photo)
    assert PEOPLE_REALISM in with_people
    without = apply_style("a mountain lake", photo)
    assert "pores" not in without and "skin" not in without


def test_other_photographic_looks_add_the_short_clause_for_people() -> None:
    noir = get_style("noir")
    assert PEOPLE_REALISM_SHORT in apply_style("a woman in the rain", noir)
    assert PEOPLE_REALISM_SHORT not in apply_style("an empty street in the rain", noir)
    # Drawn looks never get skin pores.
    assert "pores" not in apply_style("a girl with a cat", get_style("anime"))
