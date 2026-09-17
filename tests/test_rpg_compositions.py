"""Independent combinations of minds, messages, inventory, content and recovery."""
from copy import deepcopy
import json
import unittest

from mythfall.simulation import ActionError, Simulation, new_world
from mythfall.simulation.actions import apply_action
from mythfall.simulation.catalog import starting_catalog
from mythfall.simulation.characters import choose_class, instantiate, copy_spell
from mythfall.simulation.combat import start, begin_turn
from mythfall.simulation.effects import apply_effect, damage, expire_effects
from mythfall.simulation.minds import relationship_change, has_condition
from mythfall.simulation.objects import load
from mythfall.simulation.state import PLAYER
from mythfall.world_agent import knowledge, converse
from test_simulation import finish
import test_world_agent as fixtures


class CompositionsTests(unittest.TestCase):
    def world(self):
        world = new_world()
        for actor in world['actors'].values():
            actor.update(interest='none', ready_at=100000)
        return world

    def test_authored_item_and_power_share_sound_effect_with_observer_and_intervention_variants(self):
        from mythfall.simulation.authoring import author
        from mythfall.simulation.schedules import install_schedule
        from mythfall.simulation.state import emit
        # These content definitions are independent of the shipped adventure.
        # Sound -> perception -> investigation -> movement trigger -> condition.
        for source, aid, point, variant in (
            ('item', 'char.old_nessa', [22, 24], 'normal'),
            ('power', 'char.tommen_ash', [25, 26], 'normal'),
            ('item', 'char.old_nessa', [22, 24], 'deaf'),
            ('power', 'char.tommen_ash', [25, 26], 'cancelled'),
        ):
            with self.subTest(source=source, observer=aid, variant=variant):
                world = self.world()
                actor = world['actors'][aid]
                actor.update(position=point[:], work=point[:], ready_at=world['tick'])
                origin = [point[0] + 2, point[1]]
                threshold = [point[0] + 1, point[1]]
                world['actors'][PLAYER]['position'] = origin[:]
                sound = {'kind': 'sound', 'volume': 5, 'position': origin}
                spec = {'type': 'item', 'name': 'Resonant Chip', 'kind': 'potion', 'weight': 1,
                        'consumable': True, 'effects': [sound]} if source == 'item' else {
                    'type': 'ability', 'name': 'Call of the Hollow', 'level': 0, 'classes': [], 'economy': 'action',
                    'range': 0, 'target': 'self', 'max_targets': 1, 'resolution': 'automatic', 'effects': [sound],
                    'spell': False, 'components': []}
                key = author(world, {'kind': 'define', 'slug': 'hollow_signal', 'definition': spec, 'reason': 'An acoustic signal taught by a local artisan.'})
                cause = emit(world, 'training', PLAYER, text='The artisan completes a practical lesson.')['sequence']
                if source == 'item':
                    iid = author(world, {'kind': 'place', 'definition': key, 'position': origin, 'owner': PLAYER, 'cause': cause, 'reason': 'The artisan hands over the physical demonstration chip.'})
                    apply_action(world, PLAYER, {'kind': 'take', 'target': iid})
                    intent = {'kind': 'use', 'target': iid}
                else:
                    author(world, {'kind': 'grant', 'definition': key, 'actor': PLAYER, 'cause': cause, 'reason': 'The completed lesson teaches the signal.'})
                    intent = {'kind': 'ability', 'ability': key}
                sid = install_schedule(world, {'name': 'Startling dust', 'source': PLAYER, 'remaining': 1,
                    'trigger': {'kind': 'enter', 'position': threshold, 'actor': aid},
                    'effects': [{'kind': 'condition', 'condition': 'blinded', 'duration': 3, 'target': '$actor'}]})
                if variant == 'deaf':
                    apply_effect(world, PLAYER, aid, {'kind': 'condition', 'condition': 'deafened', 'duration': 10})
                apply_action(world, PLAYER, intent)
                sound_event = next(event for event in reversed(world['events']) if event['kind'] == 'sound')
                self.assertIsInstance(sound_event['cause'], int)
                if variant == 'cancelled':
                    author(world, {'kind': 'cancel_schedule', 'schedule': sid, 'reason': 'The observer clears the loose dust before crossing.'})
                sim = Simulation(json.loads(json.dumps(world)))
                sim.command({'kind': 'wait', 'ticks': 1}, 'observe')
                if variant == 'deaf':
                    self.assertEqual(sim.world['actors'][aid]['position'], point)
                    self.assertNotIn(str(sound_event['sequence']), [str(m['sequence']) for m in sim.world['actors'][aid]['memories']])
                else:
                    self.assertEqual(sim.world['actors'][aid]['position'], threshold)
                self.assertEqual(has_condition(sim.world, aid, 'blinded'), variant == 'normal')
                if variant == 'normal':
                    movement = next(event for event in sim.world['events'] if event['kind'] == 'move' and event['actor'] == aid)
                    self.assertTrue(any(event.get('cause') == movement['sequence'] and event.get('effect_kind') == 'condition' for event in sim.world['events']))
                if source == 'item':
                    self.assertEqual(sim.world['items'][iid]['place'], {'consumed': True})

    def test_magic_items_have_real_consumption_attunement_detection_and_charge_recovery(self):
        from mythfall.simulation.characters import armor_class
        from mythfall.simulation.checks import check
        from mythfall.simulation.objects import tick_objects
        from mythfall.simulation.perception import observe
        world = self.world()
        choose_class(world, PLAYER, {'class': 'fighter'})
        player = world['actors'][PLAYER]
        player['hp'] = 1
        potion = instantiate(world, 'itemdef.healing_potion@1', {'carrier': PLAYER}, PLAYER)
        sim = Simulation(world)
        result = sim.command({'kind': 'use', 'target': potion['id']}, 'potion')
        self.assertGreater(sim.world['actors'][PLAYER]['hp'], 1)
        self.assertEqual(sim.world['items'][potion['id']]['place'], {'consumed': True})
        after = deepcopy(sim.world)
        self.assertEqual(sim.command({'kind': 'use', 'target': potion['id']}, 'potion'), result)
        self.assertEqual(sim.world, after)
        world = sim.world
        cloak = instantiate(world, 'itemdef.protection_cloak@1', {'carrier': PLAYER}, PLAYER)
        ac = armor_class(world, PLAYER)
        world['actors'][PLAYER]['rpg']['short_rest_at'] = world['tick']
        original_roll = deepcopy(world)
        unprotected = check(original_roll, PLAYER, stat='wis', saving=True)
        apply_action(world, PLAYER, {'kind': 'attune', 'target': cloak['id']})
        self.assertEqual(armor_class(world, PLAYER), ac + 1)
        protected = check(world, PLAYER, stat='wis', saving=True)
        self.assertEqual(protected['total'], unprotected['total'] + 1)
        wand = instantiate(world, 'itemdef.detection_wand@1', {'carrier': PLAYER}, PLAYER)
        apply_action(world, PLAYER, {'kind': 'use', 'target': wand['id']})
        self.assertEqual(wand['charges'], 2)
        self.assertTrue(has_condition(world, PLAYER, 'detect_magic'))
        self.assertTrue(next(item for item in observe(world, PLAYER)['items'] if item['id'] == cloak['id'])['magical_aura'])
        world['tick'] = 14400 + 3600
        tick_objects(world)
        self.assertEqual(wand['charges'], 3)

    def test_legacy_duel_migrates_without_rolling_and_resumes_a_saved_turn(self):
        from mythfall.simulation.migration import upgrade_world
        world = self.world()
        world['version'] = 1
        world['actors']['char.brakka']['position'] = [24, 25]
        world['combat'] = {'opponent': 'char.brakka', 'round': 2, 'started_at': world['tick'] - 1}
        before = deepcopy(world)
        upgraded = upgrade_world(world)
        self.assertEqual(upgraded['rng'], before['rng'])
        self.assertEqual(upgraded['items'], before['items'])
        self.assertEqual(upgrade_world(upgraded), upgraded)
        sim = Simulation(json.loads(json.dumps(upgraded)))
        sim.command({'kind': 'end_turn'}, 'legacy-end')
        self.assertEqual(sim.world['combat']['awaiting'], 'char.brakka')

    def test_named_travel_uses_an_observed_fixture_and_stops_within_reach(self):
        world = self.world()
        world['fixtures']['fixture.bench'] = {'id': 'fixture.bench', 'name': 'Workbench', 'position': [26, 25]}
        sim = Simulation(world)
        sim.command({'kind': 'travel', 'target': 'fixture.bench', 'adjacent': True}, 'approach')
        self.assertEqual(sum(abs(a-b) for a,b in zip(sim.world['actors'][PLAYER]['position'], [26, 25])), 1)
        sim.world['fixtures']['fixture.unknown'] = {'id': 'fixture.unknown', 'name': 'Hidden bench', 'position': [60, 40]}
        before = deepcopy(sim.world)
        with self.assertRaises(ActionError):
            sim.command({'kind': 'travel', 'target': 'fixture.unknown'}, 'hidden')
        self.assertEqual(sim.world, before)

    def test_party_follows_a_shared_journey_around_corners_without_remote_knowledge(self):
        from mythfall.simulation.adventure import install
        from mythfall.simulation.state import distance
        world = install(new_world())
        world['actors'][PLAYER]['position'] = [24, 37]
        world['actors']['char.ellis_crow']['position'] = [24, 37]
        world['actors']['char.ellis_crow']['join_offer_until'] = world['tick'] + 10
        sim = Simulation(world)
        sim.command({'kind': 'recruit', 'target': 'char.ellis_crow'}, 'recruit')
        finish(sim, {'kind': 'travel', 'target': 'mine'}, 'journey')
        self.assertLessEqual(distance(sim.world['actors'][PLAYER]['position'], sim.world['actors']['char.ellis_crow']['position']), 1)
        self.assertEqual(sim.world['actors']['char.ellis_crow']['journey']['destination'], sim.world['map']['places']['mine']['center'])
        self.assertNotIn('journey', sim.world['actors']['char.brakka'])

    def test_ordinary_bag_keeps_weight_and_magic_bag_retains_physical_contents(self):
        world = self.world()
        bag = instantiate(world, 'itemdef.satchel@1', {'carrier': PLAYER}, PLAYER)
        original = load(world, PLAYER)
        apply_action(world, PLAYER, {'kind': 'put', 'target': 'item.sword', 'recipient': bag['id']})
        self.assertEqual(load(world, PLAYER), original)
        apply_action(world, PLAYER, {'kind': 'take', 'target': 'item.sword'})
        magic = instantiate(world, 'itemdef.holding_bag@1', {'carrier': PLAYER}, PLAYER)
        original = load(world, PLAYER)
        apply_action(world, PLAYER, {'kind': 'put', 'target': 'item.sword', 'recipient': magic['id']})
        self.assertEqual(load(world, PLAYER), original - 3)
        apply_action(world, PLAYER, {'kind': 'drop', 'target': magic['id']})
        world['actors']['char.old_nessa']['position'] = [23, 24]
        apply_action(world, 'char.old_nessa', {'kind': 'take', 'target': magic['id']})
        self.assertEqual(world['items']['item.sword']['place'], {'container': magic['id']})
        self.assertEqual(world['items'][magic['id']]['place'], {'carrier': 'char.old_nessa'})

    def test_memory_removes_derived_relationship_but_not_independent_contribution(self):
        world = self.world()
        _, event = apply_action(world, PLAYER, {'kind': 'speak', 'text': 'FORGOTTEN_ACCUSATION'})
        aid = 'char.old_nessa'
        relationship_change(world, aid, PLAYER, -5, event['sequence'])
        relationship_change(world, aid, PLAYER, 2, 0)
        apply_effect(world, PLAYER, aid, {'kind': 'memory', 'sequences': [event['sequence']], 'text': 'We discussed the weather.'})
        self.assertEqual(world['actors'][aid]['relationships'][PLAYER], 2)
        self.assertNotIn('FORGOTTEN_ACCUSATION', json.dumps(knowledge(world, aid)))
        self.assertIn('FORGOTTEN_ACCUSATION', json.dumps(world['events']))

    def test_telepathic_reply_needs_an_active_connection_and_has_no_bystander(self):
        world = self.world()
        aid = 'char.old_nessa'
        apply_effect(world, PLAYER, PLAYER, {'kind': 'condition', 'condition': 'telepathy', 'duration': 3})
        apply_action(world, PLAYER, {'kind': 'speak', 'target': aid, 'channel': 'telepathy', 'text': 'PRIVATE_CONNECTION'})
        apply_action(world, aid, {'kind': 'speak', 'target': PLAYER, 'channel': 'telepathy', 'text': 'PRIVATE_REPLY'})
        self.assertNotIn('PRIVATE_', json.dumps(world['actors']['char.tommen_ash']['memories']))
        world['tick'] += 3
        expire_effects(world)
        with self.assertRaises(ActionError):
            apply_action(world, aid, {'kind': 'speak', 'target': PLAYER, 'channel': 'telepathy', 'text': 'Too late'})

    def test_stabilized_companion_recovers_and_critical_damage_resumes_death_saves(self):
        world = self.world()
        aid = 'char.old_nessa'
        world['party']['members'].append(aid)
        damage(world, PLAYER, aid, world['actors'][aid]['hp'])
        apply_effect(world, PLAYER, aid, {'kind': 'condition', 'condition': 'stable', 'duration': 2})
        recovered = deepcopy(world)
        recovered['tick'] += 2
        expire_effects(recovered)
        self.assertEqual((recovered['actors'][aid]['life'], recovered['actors'][aid]['hp']), ('alive', 1))
        damage(world, PLAYER, aid, 1, critical=True)
        self.assertFalse(has_condition(world, aid, 'stable'))
        self.assertEqual(world['actors'][aid]['rpg']['death_saves']['failure'], 2)
        self.assertEqual(world['actors'][aid]['life'], 'unconscious')

    def test_copying_a_spell_requires_source_ink_and_completed_time(self):
        world = self.world()
        choose_class(world, PLAYER, {'class': 'wizard'})
        player = world['actors'][PLAYER]
        player['rpg']['xp'] = 300
        choose_class(world, PLAYER, {'class': 'wizard'})
        from mythfall.simulation.authoring import author
        spec = deepcopy(world['definitions']['ability.burning_hands@1'])
        spec['name'] = 'Ember Fan'
        spell = author(world, {'kind': 'define', 'slug': 'ember_fan', 'definition': spec, 'reason': 'A local variation described in the borrowed notes.'})
        source = {'id': 'item.lesson', 'name': 'Borrowed spell notes', 'kind': 'book', 'weight': 1, 'damage': 0, 'condition': 100,
                  'owner': PLAYER, 'place': {'carrier': PLAYER}, 'spell': spell}
        world['items'][source['id']] = source
        ink = instantiate(world, 'itemdef.spell_ink@1', {'carrier': PLAYER}, PLAYER)
        sim = Simulation(world)
        ticks = copy_spell(world, PLAYER, {'item': source['id']})
        result = sim.command({'kind': 'copy_spell', 'item': source['id']}, 'copy', chunk_ticks=5)
        self.assertEqual(result['reason'], 'yielded')
        sim.command({'kind': 'cancel', 'wait_id': 'copy'}, 'cancel')
        self.assertNotIn(spell, sim.world['actors'][PLAYER]['rpg']['spellbook'])
        self.assertEqual(sim.world['items'][ink['id']]['ink_gp'], 50)
        before = sim.world['tick']
        finish(sim, {'kind': 'copy_spell', 'item': source['id']}, 'complete')
        self.assertEqual(sim.world['tick'], before + ticks)
        self.assertIn(spell, sim.world['actors'][PLAYER]['rpg']['spellbook'])

    def test_every_starting_spell_and_feature_reaches_installed_resolution(self):
        for key, spec in starting_catalog().items():
            if spec['type'] != 'ability' or spec['economy'] == 'reaction':
                continue  # Shield's interrupted-hit cases are in test_rpg_boundaries.
            with self.subTest(ability=key):
                world = self.world()
                name = (spec['classes'] or ['rogue' if spec.get('mechanic') in {'dash', 'disengage', 'hide', 'fast_hands'} else 'cleric' if spec.get('mechanic') in {'turn_undead', 'preserve_life'} else 'wizard' if spec.get('mechanic') == 'arcane_recovery' else 'fighter'])[0]
                for _ in range(3):
                    world['actors'][PLAYER]['rpg']['xp'] = 900
                    choose_class(world, PLAYER, {'class': name})
                player = world['actors'][PLAYER]
                player['rpg']['abilities'].append(key)
                player['rpg'].update(armor=None, shield=None, offhand=None)
                player['equipped'] = None
                target = 'char.brakka'
                world['actors'][target].update(position=[24, 25], hp=100, max_hp=100)
                world['map']['concealment_tiles'] = [[24, 24]]
                if spec.get('mechanic') == 'turn_undead':
                    world['actors'][target]['species'] = 'undead'
                intent = {'kind': 'ability', 'ability': key, 'target': target}
                if spec['target'] == 'object':
                    intent['target'] = 'item.sword'
                    if spec.get('mechanic') == 'fast_hands':
                        world['fixtures']['fixture.box'] = {'id': 'fixture.box', 'name': 'Box', 'position': [24, 25], 'open': False}
                        intent['target'] = 'fixture.box'
                if spec['target'] in {'point', 'cone', 'cube'}:
                    intent['position'] = [24, 25]
                if spec.get('mechanic') == 'restoration':
                    apply_effect(world, target, target, {'kind': 'condition', 'condition': 'poisoned', 'duration': 10})
                    intent['condition'] = 'poisoned'
                if spec.get('mechanic') == 'command':
                    intent['command'] = 'halt'
                if spec.get('mechanic') == 'spiritual_strike':
                    player['rpg']['spiritual_weapon'] = {'position': [24, 25], 'ends_at': world['tick'] + 10, 'stat': 'wis'}
                if spec['economy'] == 'rest':
                    player['rpg']['short_rest_at'] = world['tick']
                    player['rpg']['resources']['slot_1']['current'] = 0
                else:
                    start(world, PLAYER, [target])
                    world['combat']['turn'] = next(n for n, entry in enumerate(world['combat']['participants']) if entry['id'] == PLAYER)
                    begin_turn(world)
                sim = Simulation(world)
                result = sim.command(intent, 'activate')
                self.assertTrue(any(event['kind'] == 'ability' and event['ability'] == key for event in sim.world['events']))
                self.assertEqual(result['elapsed_ticks'], 0)


class HandoffTests(unittest.TestCase):
    setUp = fixtures.WorldAgentTests.setUp
    context = fixtures.WorldAgentTests.context
    def test_rejected_combat_plan_is_returned_only_to_its_actor_without_repeating_inference(self):
        from mythfall.world_agent import combat_decision
        world = self.store.read()
        aid = 'char.old_nessa'
        world['actors'][aid]['position'] = [23, 24]
        start(world, PLAYER, [aid])
        world['combat']['turn'] = next(n for n, entry in enumerate(world['combat']['participants']) if entry['id'] == aid)
        begin_turn(world)
        self.store.save(world)
        model = fixtures.ModelFixture({'actions': [{'kind': 'retreat'}], 'reason': 'Leave the fight.'})
        context = self.context('blocked-retreat', {'kind': 'continue_combat'})
        result = combat_decision(context, world['revision'], client=model)
        after = self.store.read()
        self.assertEqual(result['result']['reason'], 'rejected')
        self.assertEqual(after['rng'], world['rng'])
        self.assertEqual(after['tick'], world['tick'])
        self.assertEqual(after['actors'][aid]['position'], world['actors'][aid]['position'])
        self.assertIn('Break sight', knowledge(after, aid)['self']['decision_feedback']['error'])
        self.assertNotIn('decision_feedback', knowledge(after, 'char.tommen_ash')['self'])
        self.assertEqual(combat_decision(context, world['revision'], client=model)['result'], result['result'])
        self.assertEqual(len(model.calls), 1)
        corrected = fixtures.ModelFixture({'actions': [{'kind': 'offer_truce'}], 'reason': 'I offer to end this conflict.'})
        combat_decision(self.context('revise-retreat', {'kind': 'continue_combat'}), after['revision'], client=corrected)
        self.assertIn('Break sight', corrected.calls[0]['input'])
        self.assertNotIn('decision_feedback', self.store.read()['actors'][aid])

    def test_two_handoffs_have_separate_minds_and_silent_observers_still_remember(self):
        world = self.store.read()
        for aid, point in [('char.old_nessa', [23, 24]), ('char.tommen_ash', [25, 24]), ('char.brakka', [24, 25])]:
            world['actors'][aid].update(position=point, ready_at=100000, interest='none')
        world['actors']['char.old_nessa']['lore'] = 'NESSA_PRIVATE'
        world['actors']['char.tommen_ash']['lore'] = 'TOMMEN_PRIVATE'
        self.store.save(world)
        model = fixtures.ModelFixture({'speech': 'I heard you.', 'actions': [], 'reason': 'Respond to the greeting.', 'promise': None, 'horizon_ticks': 30})
        intent = {'kind': 'talk', 'text': 'A public greeting.'}
        converse(self.context('two-handoffs', intent), intent, world['revision'], client=model, handoffs=['char.old_nessa', 'char.tommen_ash'])
        self.assertEqual(len(model.calls), 2)
        self.assertIn('NESSA_PRIVATE', model.calls[0]['input'])
        self.assertNotIn('TOMMEN_PRIVATE', model.calls[0]['input'])
        self.assertIn('TOMMEN_PRIVATE', model.calls[1]['input'])
        self.assertNotIn('NESSA_PRIVATE', model.calls[1]['input'])
        after = self.store.read()
        self.assertIn('A public greeting.', json.dumps(after['actors']['char.brakka']['memories']))
        self.assertFalse(any(decision['actor'] == 'char.brakka' for decision in after['decisions']))


if __name__ == '__main__':
    unittest.main()
