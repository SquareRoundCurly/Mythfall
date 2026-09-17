from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from mythfall.simulation.battlemap import ART_PATH, ensure_art, map_mesh
from mythfall.simulation.presentation import dynamic_entities
from mythfall.simulation.seed import new_world


class BattlemapTests(unittest.TestCase):
    def test_class_inventory_and_changed_perception_never_replace_model_sources(self):
        from mythfall.simulation.characters import choose_class, instantiate
        from mythfall.simulation.effects import apply_effect
        from mythfall.simulation.state import PLAYER
        world = new_world()
        initial = {entity['id']: entity.get('model', {}).get('source') for entity in dynamic_entities(world)}
        choose_class(world, PLAYER, {'class': 'rogue'})
        instantiate(world, 'itemdef.healing_potion@1', {'ground': [24, 24]}, PLAYER)
        world['actors'][PLAYER]['position'] = world['actors']['char.tommen_ash']['position'][:]
        revealed = {entity['id']: entity.get('model', {}).get('source') for entity in dynamic_entities(world)}
        self.assertEqual({key: revealed[key] for key in initial}, initial)
        apply_effect(world, PLAYER, PLAYER, {'kind': 'identity', 'subject': 'char.tommen_ash', 'identity': 'char.brakka', 'name': 'Brakka', 'duration': 3})
        changed = dynamic_entities(world)
        self.assertEqual({entity['id']: entity.get('model', {}).get('source') for entity in changed if entity['id'] in initial}, initial)
        base = world['render_slots']['actors']['char.tommen_ash']
        variants = [entity for entity in changed if base < entity['id'] < base + 10 and 'model' in entity]
        self.assertEqual(sum(entity['canvas']['bitmask'] != 0 for entity in variants), 1)

    def test_every_collision_wall_has_a_textured_quad_at_its_exact_cell(self):
        world = new_world()
        before = deepcopy(world)
        vertices = map_mesh(world).groups[("props", 1)][0]
        centers = []
        for offset in range(0, len(vertices), 12):
            quad = vertices[offset:offset + 12]
            if quad[2] == 1:
                centers.append([round((quad[0] + quad[6]) / 2 + 32), round(23 - (quad[1] + quad[7]) / 2)])
        self.assertEqual(sorted(centers), sorted(world["map"]["walls"]))
        self.assertEqual(world, before)

    def test_item_model_moves_with_the_same_item_and_hides_when_carried(self):
        world = new_world()
        eid = 20000 + sorted(world["items"]).index("item.sword") * 5
        entity = next(entity for entity in dynamic_entities(world) if entity["id"] == eid)
        self.assertEqual(entity["canvas"]["bitmask"], 0)
        world["items"]["item.sword"]["place"] = {"ground": [24, 24]}
        entity = next(entity for entity in dynamic_entities(world) if entity["id"] == eid)
        self.assertEqual(entity["canvas"]["bitmask"], 2)
        self.assertEqual(entity["model"]["source"], f"{ART_PATH}/prop-sword.gltf")
        self.assertAlmostEqual(entity["transform"]["position"][0], 24.7 - 32)
        world["items"]["item.sword"]["place"] = {"carrier": "char.old_nessa"}
        entity = next(entity for entity in dynamic_entities(world) if entity["id"] == eid)
        self.assertEqual(entity["canvas"]["bitmask"], 0)

    def test_art_install_and_layout_rebuild_preserve_existing_images(self):
        with tempfile.TemporaryDirectory() as temp:
            world = new_world()
            ensure_art(temp, world)
            directory = Path(temp) / ART_PATH
            image = directory / "terrain.png"
            original_image = image.read_bytes()
            original_time = image.stat().st_mtime_ns
            scene = directory / "village.bin"
            original_scene = scene.read_bytes()
            ensure_art(temp, world)
            self.assertEqual(original_scene, scene.read_bytes())
            world["map"]["walls"].append([10, 20])
            ensure_art(temp, world)
            self.assertNotEqual(original_scene, scene.read_bytes())
            self.assertEqual(original_image, image.read_bytes())
            self.assertEqual(original_time, image.stat().st_mtime_ns)
            for path in directory.glob("*.gltf"):
                document = json.loads(path.read_text())
                for ref in document["images"] + document["buffers"]:
                    self.assertTrue((directory / ref["uri"]).is_file(), ref["uri"])


if __name__ == "__main__":
    unittest.main()
