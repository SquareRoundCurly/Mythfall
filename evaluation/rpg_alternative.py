"""Bounded negotiation through the same public actions used by game panels.

Only initial fixture creation writes world data. All play uses the installed
public boundary and real provider decisions; observations and assertions are
read-only and never enter NPC prompts.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import shutil

from dotenv import load_dotenv
from RealmEngine.modules import ModuleActionContext, ModuleSessionContext
from mythfall import SEED_PATH
from mythfall.simulation.store import WorldStore
from mythfall.simulation.state import PLAYER
from mythfall.world_runtime import execute_world_action, setup_world


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--gateway-env', type=Path, required=True)
    parser.add_argument('--resume-from', type=Path, help='Preserve a previous failure and continue from a copied save')
    args = parser.parse_args()
    load_dotenv(args.gateway_env, override=True)
    os.environ['REALM_ENGINE_SESSION_UUID'] = '8ddbb387-851d-44dc-acd1-9285b8c846d5'
    args.evidence.mkdir(parents=True, exist_ok=False)
    workspace = args.evidence / 'workspace'
    if args.resume_from:
        shutil.copytree(args.resume_from / 'workspace', workspace)
    else:
        shutil.copytree(SEED_PATH, workspace)
        (workspace / 'state.json').write_text(json.dumps({'state': 'play', 'active_agent': 'dm', 'player_character_id': PLAYER}))
        (workspace / 'characters/player.md').write_text('---\nid: char.player\nname: Sable\nhp: {current: 20, max: 20}\nstats: {str: 12, dex: 14, con: 12, int: 14, wis: 12, cha: 16}\n---\nA courier who prefers negotiation.\n')
    common = dict(module_id='mythfall', session_uuid=os.environ['REALM_ENGINE_SESSION_UUID'], realm_id='Mythfall',
                  archive_user_id=None, realm_session_id=None, workspace_root=workspace.parent,
                  workspace_path=workspace, logger=logging.getLogger('negotiation'))
    setup_world(ModuleSessionContext(**common))
    store = WorldStore(workspace)
    report = {'actions': [], 'assertions': [], 'model_requests': 0, 'continued_from': str(args.resume_from) if args.resume_from else None}

    def save():
        (args.evidence / 'report.json').write_text(json.dumps(report, indent=2))

    def act(kind, **fields):
        if kind in {'ask', 'talk', 'continue_combat'}:
            report['model_requests'] += 1
            assert report['model_requests'] <= 12, 'Live request budget exhausted'
        assert len(report['actions']) < 70, 'Public action budget exhausted'
        intent = {'kind': kind, **fields}
        context = ModuleActionContext(**common, operation_id=f'{args.evidence.name}.{len(report["actions"])}',
                                      payload={'intent': intent, 'expected_revision': store.read()['revision']})
        result = execute_world_action(context)['result']
        record = {'intent': intent, 'result': result, 'chat': store.read().get('game_chat', {}).get('turns', [])[-1:]}
        report['actions'].append(record)
        save()
        print(json.dumps(record), flush=True)
        while result['reason'] == 'yielded':
            result = act('resume', wait_id=result['wait_id'])
        return result

    def check(value, label):
        assert value, label
        report['assertions'].append(label)
        save()

    def carried(kind, aid=PLAYER):
        return next(item for item in store.read()['items'].values() if item['kind'] == kind and item['place'].get('carrier') == aid)

    try:
        if not args.resume_from:
            act('choose_class', **{'class': 'rogue'})
            act('travel', target='hall')
            paper, ink = carried('paper')['id'], carried('ink')['id']
            act('give', target=paper, recipient='char.mara_vell')
            act('give', target=ink, recipient='char.mara_vell')
            act('talk', target='char.mara_vell', text='I want to recover the survey ledger without fighting. Tovin and Kestrel need a credible written guarantee about their unpaid wages. I gave you parchment and ink. Will you write a promise you can honestly keep, sign it, and give me the letter to show them? No wages have been paid yet.')
            act('wait', ticks=30)
            letter = store.read()['items'][paper]
            if letter.get('message') and letter['place'].get('carrier') == 'char.mara_vell':
                act('talk', target='char.mara_vell', text='Thank you for writing the undertaking. May I have the completed physical letter now so I can take it to the watchkeepers?')
                act('wait', ticks=3)
                letter = store.read()['items'][paper]
            check(bool(letter.get('message')) and letter['place'].get('carrier') == PLAYER, 'Mara writes and transfers an actual signed letter using her NPC plan and supplied materials')
            act('read', target=paper, open=True)
            act('travel', target='office')
            act('travel', target='char.tovin_reed', adjacent=True)
            act('give', target=paper, recipient='char.tovin_reed')
            act('talk', target='char.tovin_reed', text='Mara wrote this guarantee herself. Please read the physical letter I just handed you. I want the village survey reviewed safely and your claim settled. If these terms meet your needs, please open the survey chest, take the ledger and hand it to me so I can deliver it to Mara. I will carry your concerns back too.')
            act('wait', ticks=35)
            if store.read()['items']['item.survey_ledger']['place'].get('carrier') != PLAYER:
                act('talk', target='char.tovin_reed', text='Have you read Mara’s letter, and what remains unresolved? I can wait while you retrieve the ledger if you accept the terms. Please tell me if you cannot agree.')
                act('wait', ticks=35)
        if store.read()['quests']['quest.survey_return']['status'] != 'complete':
            if store.read()['items']['item.survey_ledger']['place'].get('carrier') != PLAYER:
                check(any('payment' in message['text'].lower() for turn in store.read()['game_chat']['turns'] for message in turn['messages'] if message['speaker'] == 'Tovin Reed'), 'The NPC retains his own terms and refuses the insufficient offer')
                # An independent player approach after that refusal: wait for the
                # daily sleep routine, then retrieve the unguarded object quietly.
                for _ in range(3):
                    act('wait', until_hour=23, activity='watch')
                    if store.read()['tick'] % 14400 >= 23 * 600:
                        break
                    food = carried('food')
                    act('use', target=food['id'])
                check(all(store.read()['actors'][aid]['activity'] == 'sleeping' for aid in ('char.tovin_reed', 'char.kestrel_wren')), 'Ordinary daily schedules create an unguarded opportunity without model calls')
                act('travel', target='chest.survey', adjacent=True)
                act('use', target='chest.survey', open=True)
                act('take', target='item.survey_ledger')
            check(store.read()['items']['item.survey_ledger']['place'].get('carrier') == PLAYER, 'The alternate approach retrieves the same physical ledger')
            check(not store.read()['combat'] and not store.read().get('encounters'), 'The alternative route avoids an encounter and causes no deaths')
            act('travel', target='hall')
            act('travel', target='char.mara_vell', adjacent=True)
            act('give', target='item.survey_ledger', recipient='char.mara_vell')
        check(store.read()['quests']['quest.survey_return']['status'] == 'complete', 'The same generic delivery objective accepts the alternative approach')
        def nearby_reward():
            world = store.read()
            position = world['actors'][PLAYER]['position']
            return [item for item in world['items'].values() if item.get('definition') and 'ground' in item['place']
                    and sum(abs(a-b) for a, b in zip(item['place']['ground'], position)) <= 1
                    and world['definitions'][item['definition']].get('effects') == [{'kind': 'heal', 'amount': 3}]]
        custom = nearby_reward()
        if not custom:
            act('ask', text='Now that I completed the ledger delivery, could Mara give me a modest, newly authored reward? Please invent a one-use restorative draught that heals just 3 HP, define it, and place the actual item beside me if that is an appropriate reward for this completed task. Use the quest completion as its reason; do not grant XP or a legendary item.')
            custom = nearby_reward()
        check(len(custom) == 1, 'The live DM defines and places a modest reward grounded in actual quest completion')
        act('take', target=custom[0]['id'])
        act('use', target=custom[0]['id'])
        check(store.read()['items'][custom[0]['id']]['place'] == {'consumed': True}, 'The authored consumable uses the installed effect resolver and retains its consumed identity after reload')
    except Exception as error:
        report['failure'] = repr(error)
        save()
        raise


if __name__ == '__main__':
    main()
