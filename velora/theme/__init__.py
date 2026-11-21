"""Theme engine: seed colours -> accessible design tokens (light + dark), CSS, audit and spreadsheet palette."""
from .engine import PRESETS, CompiledTheme, ThemeError, ThemeSpec, compile_theme, list_presets  # noqa: F401


def current_theme() -> CompiledTheme:
    """The compiled theme of the current site/company (its saved setting, or the default)."""
    from ..settings import get_setting
    try:
        return compile_theme(ThemeSpec.from_dict(get_setting("theme", {})))
    except ThemeError:                       # a hand-edited bad setting must never take reports/exports down
        return compile_theme(ThemeSpec())


def current_excel_palette() -> dict:
    return current_theme().excel
