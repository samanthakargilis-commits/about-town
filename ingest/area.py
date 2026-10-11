"""Keep events in the SF to Palo Alto corridor.

Default area (brief.md leaves it open): San Francisco down the Peninsula to
Palo Alto, Mountain View and Los Altos, plus the coast from Pacifica to Half Moon Bay.
East Bay, North Bay, South Bay past Mountain View, and online events are dropped.
"""
import re

IN_AREA = {
    "san francisco", "sf", "daly city", "colma", "brisbane", "south san francisco", "pacifica",
    "san bruno", "millbrae", "burlingame", "hillsborough", "san mateo", "foster city", "belmont",
    "san carlos", "redwood city", "redwood shores", "atherton", "menlo park", "east palo alto",
    "palo alto", "stanford", "portola valley", "woodside", "los altos", "los altos hills",
    "mountain view", "half moon bay", "montara", "moss beach", "el granada", "treasure island",
}
OUT_OF_AREA = [
    "oakland", "berkeley", "emeryville", "alameda", "albany", "richmond", "el cerrito", "san leandro",
    "hayward", "fremont", "walnut creek", "lafayette", "orinda", "concord", "pleasanton", "livermore",
    "danville", "san ramon", "castro valley", "union city", "newark", "martinez", "vallejo",
    "sausalito", "mill valley", "san rafael", "novato", "tiburon", "larkspur", "corte madera", "marin",
    "petaluma", "sonoma", "napa", "santa rosa", "healdsburg", "san jose", "santa clara", "sunnyvale",
    "cupertino", "campbell", "los gatos", "milpitas", "saratoga", "santa cruz", "sacramento",
    "lake merritt", "jack london square", "temescal", "rockridge", "fruitvale", "chabot space",
    "fox theater", "fox theatre oakland", "paramount theatre", "greek theatre", "freight & salvage",
    "uc theatre", "uc theater", "cornerstone berkeley", "yoshi's", "the new parish", "east bay",
    "online", "virtual", "zoom", "livestream", "webinar",
]
OUT_RE = re.compile(r"\b(" + "|".join(re.escape(x) for x in OUT_OF_AREA) + r")\b", re.I)
# Sources whose listings are SF unless they say otherwise
SF_DEFAULT = {"funcheap", "secretsf", "citylights", "greenapple", "broadwaysf", "partiful", "dothebay",
              "dice", "luma", "sfgirlchronicle", "eddieslist", "sfpl", "jccsf"}


SF_RICHMOND = re.compile(r"\b(inner |outer |the )?richmond( district)?\b(?=.*\b(district|sf|san francisco)\b)|\b(inner|outer) richmond\b|\brichmond district\b", re.I)


def out_of_area(text: str):
    # the Richmond District is in SF; Richmond the city is not
    return OUT_RE.search(SF_RICHMOND.sub(" ", text))


def in_area(ev: dict) -> bool:
    city = (ev.get("city") or "").lower().replace(", ca", "").strip()
    if city in IN_AREA and not out_of_area(ev.get("title", "")):
        return True
    if city and city not in IN_AREA and OUT_RE.search(city):
        return False
    where = " ".join([ev.get("venue", ""), ev.get("address", ""), ev.get("title", ""),
                      ev.get("source_url", "").rsplit("/", 2)[-2] if ev.get("source_url") else ""])
    if out_of_area(where.replace("-", " ")):
        # "Oakland" in an SF venue name is rare; an explicit SF/Peninsula city wins
        if not re.search(r"\b(san francisco|palo alto|menlo park|redwood city|san mateo|mountain view)\b", where, re.I):
            return False
    if city:
        # a named city we don't know: keep only if it's not obviously out of area
        return not OUT_RE.search(city)
    return ev.get("source") in SF_DEFAULT or ev.get("source") in {"keplers", "paloalto", "meetup", "eventbrite"}
