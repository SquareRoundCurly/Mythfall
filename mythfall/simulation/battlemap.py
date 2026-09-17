"""Build textured Atlas geometry from the canonical map, without baking actors/items.

The PNG sheets are immutable generated art. UV regions select tiles without
editing the bitmaps. Static scenery is one batched model; moving objects keep
their own entities and are hidden using their canvas mask when unobserved.
"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import struct

ART_PATH = "assets/battlemap-v1"
ART_SEED = Path(__file__).parents[1] / "seed" / ART_PATH
ACTOR_TILES = {"player": 0, "old_nessa": 1, "tommen_ash": 2, "mara_vell": 3, "ellis_crow": 4, "brakka": 5}
ITEM_TILES = {"sword": 8, "lantern": 9, "book": 11}


def sprite(eid, name, x, y, width, height, source, *, z=3, visible=True):
    return {"id": eid, "name": name, "canvas": {"bitmask": 2 if visible else 0},
            "transform": {"position": [x - 32, 23 - y, z], "scale": [width, height, 1]},
            "model": {"source": f"{ART_PATH}/{source}.gltf"}}


class Mesh:
    def __init__(self):
        self.groups = defaultdict(lambda: ([], [], []))

    def quad(self, x, y, width, height, z, sheet, tile, *, columns=4, rows=4, tint=1, crop=None):
        # World coordinates are screen-like (south positive); Atlas XY is north positive.
        vertices, uvs, indices = self.groups[(sheet, tint)]
        base = len(vertices) // 3
        vertices.extend([x - width / 2, y - height / 2, z, x + width / 2, y - height / 2, z,
                         x + width / 2, y + height / 2, z, x - width / 2, y + height / 2, z])
        col, row = tile % columns, tile // columns
        u0, v0, u1, v1 = crop or (col / columns + .001, row / rows + .001,
                                  (col + 1) / columns - .001, (row + 1) / rows - .001)
        uvs.extend([u0, v1, u1, v1, u1, v0, u0, v0])
        indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])

    def map_quad(self, x, y, width, height, z, sheet, tile, **kwargs):
        self.quad(x - 32, 23 - y, width, height, z, sheet, tile, **kwargs)

    def floor(self, x, y, width, height, tile, z, *, size=4, tint=1):
        for row in range(int((height + size - .001) // size)):
            for col in range(int((width + size - .001) // size)):
                w, h = min(size, width - col * size), min(size, height - row * size)
                self.map_quad(x + col * size + w / 2, y + row * size + h / 2, w, h, z,
                              "terrain", tile, columns=2, rows=2, tint=tint)

    def write(self, directory, name):
        document = {"asset": {"version": "2.0", "generator": "Mythfall battlemap v1"},
                    "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
                    "meshes": [{"primitives": []}], "bufferViews": [], "accessors": [],
                    "materials": [], "images": [], "textures": [],
                    "samplers": [{"magFilter": 9729, "minFilter": 9729, "wrapS": 33071, "wrapT": 33071}],
                    "extensionsUsed": ["KHR_materials_unlit"]}
        binary = bytearray()

        def accessor(values, width, integer=False):
            data = struct.pack("<" + ("I" if integer else "f") * len(values), *values)
            index = len(document["accessors"])
            document["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)})
            binary.extend(data)
            record = {"bufferView": index, "componentType": 5125 if integer else 5126,
                      "count": len(values) // width, "type": {1: "SCALAR", 2: "VEC2", 3: "VEC3"}[width]}
            if width == 3:
                record.update(min=[min(values[i::3]) for i in range(3)], max=[max(values[i::3]) for i in range(3)])
            document["accessors"].append(record)
            return index

        sheets = {}
        for (sheet, tint), (vertices, uvs, indices) in self.groups.items():
            if sheet not in sheets:
                sheets[sheet] = len(sheets)
                document["images"].append({"uri": f"{sheet}.png"})
                document["textures"].append({"source": sheets[sheet], "sampler": 0})
            material = len(document["materials"])
            document["materials"].append({
                "doubleSided": True, "alphaMode": "OPAQUE" if sheet == "terrain" else "MASK", "alphaCutoff": .45,
                "extensions": {"KHR_materials_unlit": {}},
                "pbrMetallicRoughness": {"baseColorTexture": {"index": sheets[sheet]},
                                        "baseColorFactor": [tint, tint, tint, 1], "metallicFactor": 0, "roughnessFactor": 1},
            })
            document["meshes"][0]["primitives"].append({"mode": 4, "material": material,
                "attributes": {"POSITION": accessor(vertices, 3), "NORMAL": accessor([0, 0, 1] * (len(vertices) // 3), 3),
                               "TEXCOORD_0": accessor(uvs, 2)}, "indices": accessor(indices, 1, True)})
        document["buffers"] = [{"uri": f"{name}.bin", "byteLength": len(binary)}]
        (directory / f"{name}.bin").write_bytes(binary)
        (directory / f"{name}.gltf").write_text(json.dumps(document, separators=(",", ":")) + "\n")


def map_mesh(world):
    mesh = Mesh()
    width, height = world["map"]["width"], world["map"]["height"]
    mesh.floor(-2, -2, width + 4, height + 4, 0, -4, tint=.8)
    mesh.floor(0, 22.3, width, 3.4, 1, -2, tint=.92)
    mesh.floor(22.3, 2, 3.4, 42, 1, -2.01, tint=.92)
    mesh.floor(54.6, 3, 2.8, 40, 1, -2.01, tint=.92)
    mesh.floor(4.75, 7.5, 2.5, 17, 1, -2.01, tint=.92)
    mesh.floor(17.5, 18.5, 13, 11, 2, -1.8)
    for key, place in world["map"]["places"].items():
        if key in {"square", "road", "mine"}:
            continue
        x, y, w, h = place["bounds"]
        mesh.floor(x + .5, y + .5, w - 1, h - 1, 2 if key in {"watch", "gallery"} else 3, -.8, size=3)
        mesh.map_quad(x + 3, y + 3, 2.6, 2.1, .4, "props", 3)
        mesh.map_quad(x + 3, y + 4.7, .95, .95, .35, "props", 13)
        mesh.map_quad(x + w - 3, y + h - 3, 2.4, 2.6, .4, "props", 5 if key == "inn" else 3)
        mesh.map_quad(x + w - 3, y + 2.6, 1.8, 1.8, .4, "props", 4)
        mesh.map_quad(x + 2, y + h - 2.5, 1.8, 1.8, .4, "props", 6)
    for x, y in world["map"]["walls"]:
        mesh.map_quad(x, y, 1.03, 1.03, 1, "props", 0, crop=(.04, .027, .228, .235))
    mesh.map_quad(27, 21, 2.2, 2.2, 1.2, "props", 2)
    # Keep decorative vegetation away from roads and authored interiors.
    for y in range(1, height - 1, 3):
        for x in range(2, width - 1, 3):
            inside = any(px - 2 <= x <= px + w + 1 and py - 2 <= y <= py + h + 1
                         for px, py, w, h in (p["bounds"] for p in world["map"]["places"].values()))
            if not inside and abs(x - 24) > 3 and abs(x - 56) > 3 and abs(y - 24) > 3:
                if (x * 17 + y * 31) % 7 < 3:
                    mesh.map_quad(x, y, 1.7, 1.7, -.5, "props", 7)
    return mesh


def ensure_art(workspace, world):
    directory = Path(workspace) / ART_PATH
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("terrain.png", "props.png", "characters.png", "prompts.json", "asset.json"):
        destination = directory / name
        if not destination.exists():
            shutil.copy2(ART_SEED / name, destination)
    # Only geometry inputs invalidate this cache; opening a door doesn't rebuild scenery.
    layout = {key: world["map"][key] for key in ("width", "height", "places", "walls")}
    fingerprint = hashlib.sha256(json.dumps(layout, sort_keys=True).encode()).hexdigest()
    stamp = directory / "layout.sha256"
    if not stamp.exists() or stamp.read_text() != fingerprint:
        map_mesh(world).write(directory, "village")
        for name, index in ACTOR_TILES.items():
            mesh = Mesh()
            mesh.quad(0, 0, 1, 1, 0, "characters", index, columns=3, rows=2)
            mesh.write(directory, f"actor-{name}")
        for name, index in {**ITEM_TILES, "door": 1}.items():
            mesh = Mesh()
            mesh.quad(0, 0, 1, 1, 0, "props", index)
            mesh.write(directory, f"prop-{name}")
        stamp.write_text(fingerprint)
