"""Точное сопоставление разрешённых шаблонов с исходными строками."""


def template_ranges(source_code: str, template: str) -> tuple[tuple[int, int], ...]:
    """Возвращает включительные диапазоны точных совпадений блока строк."""
    if not template.strip():
        return ()
    source_lines = source_code.splitlines()
    template_lines = template.splitlines()
    width = len(template_lines)
    return tuple(
        (index + 1, index + width)
        for index in range(len(source_lines) - width + 1)
        if source_lines[index : index + width] == template_lines
    )
