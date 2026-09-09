"""Contrast checks on the shared palette, including every user-selectable accent."""

import pytest

from taxo_trainer.ui.theme import ACCENTS, PALETTES


def contrast(first: str, second: str) -> float:
    """Calculate relative sRGB luminance contrast for opaque colors."""

    def luminance(value: str) -> float:
        channels = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [
            c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
            for c in channels
        ]
        return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    low, high = sorted([luminance(first), luminance(second)])
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("mode", PALETTES)
def test_text_and_feedback_contrast(mode):
    colors = PALETTES[mode]
    for surface in ("page", "surface", "raised"):
        for text in ("main", "muted", "positive", "negative", "warning"):
            assert contrast(colors[text], colors[surface]) >= 4.5, (mode, text, surface)
        assert contrast(colors["border"], colors[surface]) >= 3, (mode, surface)
    for role in ("positive", "negative", "warning"):
        assert contrast(colors[role], colors[role + "-soft"]) >= 4.5


@pytest.mark.parametrize("accent", ACCENTS)
def test_accent_contrast_in_both_modes(accent):
    colors = ACCENTS[accent]
    assert contrast("#ffffff", colors["button"]) >= 4.5
    for mode, palette in PALETTES.items():
        for surface in ("page", "surface", "raised"):
            assert contrast(colors[mode], palette[surface]) >= 4.5, (
                accent,
                mode,
                surface,
            )
        assert contrast(colors[mode], colors["soft_" + mode]) >= 4.5


@pytest.mark.parametrize("theme", ["standard", "warm", "neutral", "contrast"])
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_surface_palettes_and_accents(theme, mode):
    from taxo_trainer.ui.theme import THEMES

    colors = THEMES[theme][mode]
    for surface in ("page", "surface", "raised"):
        for role in ("main", "muted", "positive", "negative", "warning"):
            assert contrast(colors[role], colors[surface]) >= (7 if theme == "contrast" else 4.5), (theme, mode, role)
        assert contrast(colors["border"], colors[surface]) >= 3
        for accent in ACCENTS.values():
            assert contrast(accent[mode], colors[surface]) >= 4.5
