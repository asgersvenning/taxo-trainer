"""Shared theme roles for readable surfaces, controls, and feedback.

Adjust palettes here rather than introducing mode-specific colors in views.
Accent choices affect navigation and emphasis; feedback colors stay consistent.
"""

from nicegui import ui

PALETTES = {
    "light": {
        "page": "#f1f5f9",
        "surface": "#ffffff",
        "raised": "#e2e8f0",
        "main": "#172033",
        "muted": "#475569",
        "border": "#64748b",
        "positive": "#166534",
        "positive-soft": "#dcfce7",
        "negative": "#991b1b",
        "negative-soft": "#fee2e2",
        "warning": "#854d0e",
        "warning-soft": "#fef3c7",
    },
    "dark": {
        "page": "#111827",
        "surface": "#1e293b",
        "raised": "#334155",
        "main": "#f8fafc",
        "muted": "#cbd5e1",
        "border": "#94a3b8",
        "positive": "#bbf7d0",
        "positive-soft": "#14532d",
        "negative": "#fecaca",
        "negative-soft": "#7f1d1d",
        "warning": "#fde68a",
        "warning-soft": "#713f12",
    },
}
ACCENTS = {
    "blue": {
        "label": "Blue",
        "button": "#1d4ed8",
        "light": "#1e40af",
        "dark": "#bfdbfe",
        "soft_light": "#dbeafe",
        "soft_dark": "#1e3a8a",
    },
    "forest": {
        "label": "Forest",
        "button": "#0f766e",
        "light": "#115e59",
        "dark": "#99f6e4",
        "soft_light": "#ccfbf1",
        "soft_dark": "#134e4a",
    },
    "plum": {
        "label": "Plum",
        "button": "#7e22ce",
        "light": "#6b21a8",
        "dark": "#e9d5ff",
        "soft_light": "#f3e8ff",
        "soft_dark": "#581c87",
    },
}

ACCENTS.update({
    "amber": {"label": "Amber", "button": "#92400e", "light": "#78350f",
              "dark": "#fde68a", "soft_light": "#fef3c7", "soft_dark": "#713f12"},
    "rose": {"label": "Rose", "button": "#9f1239", "light": "#881337",
             "dark": "#fecdd3", "soft_light": "#ffe4e6", "soft_dark": "#881337"},
    "slate": {"label": "Slate", "button": "#334155", "light": "#1e293b",
              "dark": "#f1f5f9", "soft_light": "#e2e8f0", "soft_dark": "#334155"},
})
THEME_LABELS = {"standard": "Standard", "warm": "Warm paper", "neutral": "Neutral",
                "contrast": "High contrast"}
THEMES = {
    "standard": PALETTES,
    "warm": {
        "light": PALETTES["light"] | {"page": "#f5f0e5", "surface": "#fffcf5", "raised": "#eee7d9", "main": "#28221a", "muted": "#514638", "border": "#746755"},
        "dark": PALETTES["dark"] | {"page": "#1c1917", "surface": "#292524", "raised": "#38312c", "main": "#fff7ed", "muted": "#e7d9c7", "border": "#b5a48d"},
    },
    "neutral": {
        "light": PALETTES["light"] | {"page": "#f5f5f5", "surface": "#ffffff", "raised": "#e5e5e5", "main": "#171717", "muted": "#404040", "border": "#737373"},
        "dark": PALETTES["dark"] | {"page": "#0a0a0a", "surface": "#171717", "raised": "#262626", "main": "#fafafa", "muted": "#d4d4d4", "border": "#a3a3a3"},
    },
    "contrast": {
        "light": PALETTES["light"] | {"page": "#ffffff", "surface": "#ffffff", "raised": "#f0f0f0", "main": "#000000", "muted": "#202020", "border": "#303030", "positive": "#004500", "negative": "#780000", "warning": "#543500"},
        "dark": PALETTES["dark"] | {"page": "#000000", "surface": "#000000", "raised": "#151515", "main": "#ffffff", "muted": "#f0f0f0", "border": "#dddddd", "positive": "#cfffda", "negative": "#ffdddd", "warning": "#fff0a0"},
    },
}


def theme_css() -> str:
    """Build CSS from shared palette roles and component rules."""
    rules = []
    for mode, palette in PALETTES.items():
        values = ";".join(f"--tt-{key}:{value}" for key, value in palette.items())
        rules.append(f"body.body--{mode} {{{values};color-scheme:{mode};}}")
        for accent, colors in ACCENTS.items():
            # Default blue also applies before the startup script runs.
            selector = f'body.body--{mode}[data-accent="{accent}"]'
            if accent == "blue":
                selector += f",body.body--{mode}:not([data-accent])"
            rules.append(
                f"{selector} {{ --q-primary:{colors['button']} !important; --q-accent:{colors['button']} !important; --tt-primary:{colors[mode]}; --tt-primary-soft:{colors['soft_' + mode]}; }}"
            )
    for theme, modes in THEMES.items():
        for mode, palette in modes.items():
            values = ";".join(f"--tt-{key}:{value}" for key, value in palette.items())
            rules.append(f'body.body--{mode}[data-theme="{theme}"] {{{values};}}')
    for token in (
        "page",
        "surface",
        "raised",
        "positive-soft",
        "negative-soft",
        "warning-soft",
        "primary-soft",
    ):
        rules.append(
            f".bg-tt-{token} {{background-color:var(--tt-{token}) !important;}}"
        )
        rules.append(
            f".hover\\:bg-tt-{token}:hover {{background-color:var(--tt-{token}) !important;}}"
        )
    for token in ("main", "muted", "positive", "negative", "warning", "primary"):
        rules.append(f".text-tt-{token} {{color:var(--tt-{token}) !important;}}")
    for token in ("border", "positive", "negative", "warning", "primary"):
        rules.append(
            f".border-tt-{token} {{border-color:var(--tt-{token}) !important;}}"
        )
        rules.append(
            f".hover\\:border-tt-{token}:hover {{border-color:var(--tt-{token}) !important;}}"
        )
    rules.append("""
body { --q-secondary:#475569 !important; --q-positive:#166534 !important; --q-negative:#991b1b !important;
       --q-warning:#854d0e !important; --q-info:#1e40af !important; --q-dark:var(--tt-surface) !important;
       background:var(--tt-page); color:var(--tt-main); }
html, body, .q-layout, .q-page-container, .q-page {
 margin:0; padding:0; height:100vh; width:100%; overflow:hidden;
}
.nicegui-content {padding:0 !important; margin:0 !important;}
.q-img.object-contain .q-img__image {object-fit:contain !important;}
.q-card, .q-menu, .q-dialog__inner > div {
 background:var(--tt-surface); color:var(--tt-main);
}
.q-field__control {background:var(--tt-surface); color:var(--tt-main);}
.q-field__native, .q-field__input, .q-field__label, .q-field__marginal {
 color:var(--tt-main) !important;
}
.q-field--outlined .q-field__control:before {border-color:var(--tt-border);}
.q-field input::placeholder {color:var(--tt-muted); opacity:1;}
.q-item, .q-tab, .q-radio, .q-toggle {color:var(--tt-main);}
.q-item--active, .q-item.q-manual-focusable--focused {background:var(--tt-primary-soft);}
.q-tab--active {color:var(--tt-primary) !important;}
.q-tab__indicator {background:var(--tt-primary);}
.q-separator {background:var(--tt-border); opacity:.5;}
.q-table, .q-table__top, .q-table__bottom {background:var(--tt-surface); color:var(--tt-main);}
.q-table thead th {background:var(--tt-raised); color:var(--tt-main); font-weight:600;}
.q-table th, .q-table td {border-color:var(--tt-border);}
.q-table tbody tr:hover {background:var(--tt-raised);}
.q-table tbody td {font-size:.875rem;}
/* Foreground roles differ from filled-button colors in dark mode. */
/* NiceGUI puts Quasar's important utilities in a layer. Important rules in
   this earlier layer take precedence; unlayered overrides cannot do so. */
@layer theme {
body .text-primary, body .text-accent {color:var(--tt-primary) !important;}
body .text-positive {color:var(--tt-positive) !important;}
body .text-negative {color:var(--tt-negative) !important;}
body .text-warning {color:var(--tt-warning) !important;}
body .text-secondary {color:var(--tt-muted) !important;}
body .q-btn:not(.q-btn--flat):not(.q-btn--outline), body .q-chip, body .q-badge {
 color:#fff !important;
}
}
.q-btn--flat, .q-btn--outline {background:transparent;}
.q-btn:focus-visible, a:focus-visible, .q-field:focus-within, [tabindex="0"]:focus-visible {
 outline:2px solid var(--tt-primary); outline-offset:3px;
}
.q-linear-progress__track {color:var(--tt-raised); opacity:1;}
.q-notification {color:#fff;}
body[data-theme="contrast"] .q-separator {opacity:1;}
body[data-theme="contrast"] :focus-visible {outline-width:3px;}
""")
    return "\n".join(rules)


def set_accent(accent: str) -> None:
    """Apply a validated accent to the current client without reloading play state."""
    if accent not in ACCENTS:
        accent = "blue"
    ui.run_javascript(f'document.body.dataset.accent = "{accent}"')


def set_surface_theme(theme: str) -> None:
    """Apply a surface palette while preserving appearance mode and quiz state."""
    if theme not in THEMES:
        theme = "standard"
    ui.run_javascript(f'document.body.dataset.theme = "{theme}"')


def install_theme(accent: str = "blue", surface_theme: str = "standard") -> None:
    """Install theme roles once per page and restore its saved accent."""
    ui.add_head_html("<style>" + theme_css() + "</style>")
    ui.timer(0, lambda: set_accent(accent), once=True)
    ui.timer(0, lambda: set_surface_theme(surface_theme), once=True)
