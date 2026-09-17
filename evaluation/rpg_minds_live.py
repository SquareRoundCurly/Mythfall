"""Bounded live NPC memory evaluation; criteria never enter the agent prompt."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from mythfall.rpg_prompts import NPC
from mythfall.simulation import new_world
from mythfall.simulation.actions import apply_action
from mythfall.simulation.effects import apply_effect
from mythfall.simulation.state import PLAYER
from mythfall.world_agent import knowledge
from mythfall.world_models import NPCDecision, decide


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--gateway-env', type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(args.gateway_env, override=True)
    os.environ['REALM_ENGINE_SESSION_UUID'] = '8ddbb387-851d-44dc-acd1-9285b8c846d5'
    args.evidence.mkdir(parents=True, exist_ok=False)
    world = new_world()
    aid = 'char.old_nessa'
    world['actors'][aid]['position'] = [23, 24]
    _, event = apply_action(world, PLAYER, {'kind': 'speak', 'target': aid, 'text': 'I left the brass key inside the hollow cedar beside the north bridge.'})
    report = {'cases': [], 'assertions': []}
    before = deepcopy(world)
    for label in ('remembered', 'altered'):
        if label == 'altered':
            apply_effect(world, PLAYER, aid, {'kind': 'memory', 'sequences': [event['sequence']], 'text': 'The traveler and I exchanged a greeting about the rain.'})
        view = knowledge(world, aid)
        input = {'observation': view, 'player_words': 'Do you remember where I left my key?', 'received': {'kind': 'speech', 'text': 'Do you remember where I left my key?'}}
        if label == 'altered':
            assert 'hollow cedar' not in json.dumps(input) and 'north bridge' not in json.dumps(input)
            report['assertions'].append('The altered NPC input contains neither removed location nor stale history.')
        (args.evidence / f'{label}-input.json').write_text(json.dumps(input, indent=2))
        decision, receipt = decide(args.evidence / 'workspace', label, NPCDecision, NPC, input)
        report['cases'].append({'case': label, 'output': decision.model_dump(), 'receipt': receipt})
        (args.evidence / 'report.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report['cases'][-1]), flush=True)
    original, altered = (case['output']['speech'].lower() for case in report['cases'])
    assert 'cedar' in original and 'bridge' in original, 'Control NPC did not recall received testimony.'
    assert 'cedar' not in altered and 'north bridge' not in altered, 'Removed memory leaked in the new response.'
    assert 'hollow cedar' in json.dumps(world['events']), 'Canonical history was lost.'
    assert world['tick'] == before['tick'] and world['rng'] == before['rng'], 'Inference advanced the simulation.'
    report['assertions'] += ['The control NPC recalls received testimony.', 'The altered live response does not reconstruct the removed location.', 'The authoritative ledger retains the original event.', 'Inference changes neither time nor random state.']
    (args.evidence / 'report.json').write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
