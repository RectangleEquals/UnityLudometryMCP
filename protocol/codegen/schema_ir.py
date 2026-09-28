"""Reads the protocol JSON Schemas into a language-neutral model shared by the code generators.

Python 3.10+ standard library only.

Rules (the schema authoring rules of the protocol README):
- A schema object with `properties` becomes a class named by its `title` (required, unique, PascalCase).
- `{"anyOf": [X, {"type": "null"}]}` is a nullable X. Other unions, untyped values and `prefixItems` arrays are raw JSON;
  objects without `properties` are raw JSON objects.
- Common types with hand-written counterparts: agent-mode → `mode`, error → `error`, value → raw JSON.
- A property that may be null must be required (canonical form: always written; absent optional properties are omitted).
"""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin

PROTOCOL = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_DIR = PROTOCOL / "schema"
BASE = "https://github.com/RectangleEquals/UnityLudometryMCP/protocol/schema/"

SPECIAL = {
    BASE + "common/agent-mode.schema.json#": "mode",
    BASE + "common/error.schema.json#": "error",
    BASE + "common/value.schema.json#": "json",
}


class SchemaError(Exception):
    pass


def load_documents() -> dict[str, dict]:
    docs: dict[str, dict] = {}
    for path in sorted(SCHEMA_DIR.rglob("*.schema.json")):
        rel = path.relative_to(SCHEMA_DIR).as_posix()
        docs[BASE + rel] = json.loads(path.read_text(encoding="utf-8"))
    return docs


DOCS: dict[str, dict] = load_documents()


def resolve(ref: str, base_uri: str) -> tuple[str, dict]:
    """Returns (absolute uri with fragment, node)."""
    absolute = urljoin(base_uri, ref)
    doc_uri, fragment = urldefrag(absolute)
    if doc_uri not in DOCS:
        raise SchemaError(f"unresolvable $ref {ref} from {base_uri}")
    node = DOCS[doc_uri]
    for part in [p for p in fragment.split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return f"{doc_uri}#{fragment}", node


# ---------------------------------------------------------------- type model
@dataclass
class IrType:
    kind: str                 # string | long | double | bool | mode | json | object | class | error | list
    name: str = ""            # class name
    item: IrType | None = None
    nullable: bool = False     # schema allows JSON null


@dataclass
class Prop:
    json_name: str
    type: IrType
    required: bool
    description: str


@dataclass
class ClassDef:
    name: str
    description: str
    props: list[Prop] = field(default_factory=list)
    origin: str = ""

    @property
    def group(self) -> str:
        """The schema folder the class comes from: common, methods, events, files."""
        return self.origin[len(BASE):].split("#")[0].split("/")[0]


@dataclass
class MethodEntry:
    name: str
    const: str
    meta: dict
    params: IrType
    result: IrType
    job_result: IrType | None
    summary: str


@dataclass
class EventEntry:
    kind: str
    const: str
    params: IrType
    summary: str


@dataclass
class FileEntry:
    schema: str
    rec: str          # NDJSON record kind, or "" for single-document files
    type: IrType


@dataclass
class Model:
    classes: dict[str, ClassDef]
    methods: list[MethodEntry]
    events: list[EventEntry]
    files: list[FileEntry]


def pascal(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


class _Builder:
    def __init__(self) -> None:
        self.classes: dict[str, ClassDef] = {}
        self.node_class: dict[str, str] = {}

    def map_type(self, node: dict, uri: str) -> IrType:
        """uri = the node's own identity (document uri + JSON pointer)."""
        if "$ref" in node:
            target_uri, target = resolve(node["$ref"], uri)
            if target_uri in SPECIAL:
                return IrType(SPECIAL[target_uri])
            return self.map_type(target, target_uri)
        if "allOf" in node and len(node["allOf"]) == 1:
            # A single-ref extension (e.g. NDJSON records adding a `rec` constant): the referenced type.
            return self.map_type(node["allOf"][0], uri + "/allOf/0")
        for union in ("anyOf", "oneOf"):
            if union in node and not (node.get("type") == "object" and "properties" in node):
                options = node[union]
                non_null = [o for o in options if o != {"type": "null"}]
                if len(options) == 2 and len(non_null) == 1:
                    t = self.map_type(non_null[0], f"{uri}/{union}/{options.index(non_null[0])}")
                    t.nullable = True
                    return t
                return IrType("json")
        if "const" in node:
            c = node["const"]
            return IrType("bool" if isinstance(c, bool) else "string" if isinstance(c, str) else "long" if isinstance(c, int) else "double")
        t = node.get("type")
        nullable = False
        if isinstance(t, list):
            types = [x for x in t if x != "null"]
            nullable = "null" in t
            if len(types) != 1:
                return IrType("json")
            t = types[0]
        if t == "string":
            return IrType("string", nullable=nullable)
        if t == "integer":
            return IrType("long", nullable=nullable)
        if t == "number":
            return IrType("double", nullable=nullable)
        if t == "boolean":
            return IrType("bool", nullable=nullable)
        if t == "array":
            if "prefixItems" in node or "items" not in node:
                return IrType("json", nullable=nullable)
            return IrType("list", item=self.map_type(node["items"], uri + "/items"), nullable=nullable)
        if t == "object" or "properties" in node:
            if "properties" in node:
                return IrType("class", name=self.register_class(node, uri), nullable=nullable)
            return IrType("object", nullable=nullable)
        return IrType("json")

    def register_class(self, node: dict, uri: str) -> str:
        if uri in self.node_class:
            return self.node_class[uri]
        title = node.get("title")
        if not title or not re.fullmatch(r"[A-Z][A-Za-z0-9]*", title):
            raise SchemaError(f"object with properties needs a PascalCase title: {uri}")
        if title in self.classes and self.classes[title].origin != uri:
            raise SchemaError(f"duplicate title {title}: {uri} and {self.classes[title].origin}")
        self.node_class[uri] = title
        cls = ClassDef(title, node.get("description", ""), origin=uri)
        self.classes[title] = cls
        required = set(node.get("required", []))
        for json_name, prop_schema in node["properties"].items():
            ptype = self.map_type(prop_schema, f"{uri}/properties/{json_name}")
            is_required = json_name in required
            if not is_required and ptype.nullable and ptype.kind not in ("json", "object"):
                raise SchemaError(f"nullable property must be required (canonical form): {uri}/properties/{json_name}")
            cls.props.append(Prop(json_name, ptype, is_required, prop_schema.get("description", "")))
        return title


def build() -> Model:
    """Reads every method, event and file schema into the neutral model (classes in discovery order)."""
    b = _Builder()
    methods: list[MethodEntry] = []
    events: list[EventEntry] = []
    files: list[FileEntry] = []
    for uri, doc in DOCS.items():
        rel = uri[len(BASE):]
        if rel.startswith("methods/"):
            name = rel[len("methods/"):-len(".schema.json")]
            if doc.get("title") != name:
                raise SchemaError(f"{rel}: title must be the method name")
            defs = doc["$defs"]
            types = {k: b.map_type(defs[k], f"{uri}#/$defs/{k}") for k in defs}
            for k in ("params", "result"):
                if types[k].kind != "class":
                    raise SchemaError(f"{rel}: $defs/{k} must be an object type")
            methods.append(MethodEntry(name, pascal(name), doc["x-method"], types["params"], types["result"], types.get("jobResult"), doc["description"]))
        elif rel.startswith("events/"):
            kind = rel[len("events/"):-len(".schema.json")]
            t = b.map_type(doc["$defs"]["params"], f"{uri}#/$defs/params")
            if t.kind != "class":
                raise SchemaError(f"{rel}: params must be an object type")
            events.append(EventEntry(kind, pascal(kind), t, doc["description"]))
        elif rel.startswith("files/"):
            name = rel[len("files/"):-len(".schema.json")]
            if "properties" in doc:
                files.append(FileEntry(name, "", b.map_type(doc, uri + "#")))
            for def_name, node in doc.get("$defs", {}).items():
                rec = node.get("x-rec") or node.get("properties", {}).get("rec", {}).get("const")
                if rec or name == "ndjson":
                    files.append(FileEntry(name, rec, b.map_type(node, f"{uri}#/$defs/{def_name}")))

    methods.sort(key=lambda m: m.name)
    events.sort(key=lambda e: e.kind)
    files.sort(key=lambda f: (f.schema, f.rec))
    consts = [m.const for m in methods]
    if len(set(consts)) != len(consts):
        raise SchemaError("method constant names collide")
    return Model(b.classes, methods, events, files)
