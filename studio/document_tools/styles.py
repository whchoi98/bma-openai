"""Shared visual tokens for the Studio's three supported document styles."""
from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentStyle:
    id: str
    background: str
    surface: str
    ink: str
    muted: str
    accent: str
    secondary: str
    grid: str
    palette: tuple[str, ...]
    title_size: int
    body_size: int
    font_family: str = "NanumSquareOTF"


STYLES = {
    "business": DocumentStyle("business", "#FFFFFF", "#F4F7FB", "#182B49", "#52647B",
                              "#2D5EAA", "#208477", "#DBE3EE",
                              ("#2D5EAA", "#208477", "#E9A64B", "#9276BD", "#647895", "#D77C6A"), 30, 19),
    "aws-desk": DocumentStyle("aws-desk", "#101D2E", "#1B3048", "#F1F7FC", "#B8CBDB",
                              "#43D5C4", "#FFAE52", "#36506B",
                              ("#43D5C4", "#FFAE52", "#65ACF7", "#D6A6EF", "#82D99B", "#EF8594"), 32, 19),
    "presentation": DocumentStyle("presentation", "#F5F0E8", "#FFFFFF", "#281E48", "#675D78",
                                  "#6947C7", "#E55F3D", "#DBD1E5",
                                  ("#6947C7", "#E55F3D", "#159A8C", "#DDA42D", "#AC60A0", "#428EC2"), 38, 21),
}


def get_style(style: str) -> DocumentStyle:
    if not isinstance(style, str) or style not in STYLES:
        raise ValueError("Unknown document style; choose business, aws-desk, or presentation")
    return STYLES[style]
