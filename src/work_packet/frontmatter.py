"""Markdown files with YAML front matter.

Timestamps are kept as strings: the loader below does not turn
``2026-10-21T18:02:11Z`` into a datetime, so a file reads back exactly as it
was written.
"""

import yaml


class FrontMatterError(ValueError):
    pass


class _Loader(yaml.SafeLoader):
    pass


# Drop the implicit timestamp resolver so times stay strings.
_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_presenter)

_FENCE = "---"


def parse(text):
    """Split ``text`` into (meta, body).

    A file with no opening fence has meta ``None`` and the whole text as
    body. A file with an opening fence but no closing one, YAML that does not
    parse, or YAML that is not a mapping raises FrontMatterError.
    """
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != _FENCE:
        return None, text
    for i in range(1, len(lines)):
        if lines[i].rstrip() == _FENCE:
            break
    else:
        raise FrontMatterError("front matter has no closing '---'")
    src = "\n".join(lines[1:i])
    try:
        meta = yaml.load(src, Loader=_Loader)
    except yaml.YAMLError as e:
        raise FrontMatterError("front matter is not valid YAML: %s" % e) from None
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise FrontMatterError("front matter is not a mapping")
    body = "\n".join(lines[i + 1:])
    return meta, body


def dump(meta, body):
    """Inverse of parse(): ``parse(dump(m, b)) == (m, b)`` for any mapping ``m``."""
    if meta is None:
        return body
    if meta:
        y = yaml.dump(meta, Dumper=_Dumper, sort_keys=False,
                      default_flow_style=False, allow_unicode=True)
    else:
        y = ""
    return _FENCE + "\n" + y + _FENCE + "\n" + body


def load(path):
    with open(path, "r", encoding="utf-8") as fp:
        return parse(fp.read())
