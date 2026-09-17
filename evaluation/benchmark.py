"""Fixed-population advancement benchmark; no provider calls or authored verdict."""
import json
from pathlib import Path
import statistics
import time

from mythfall.simulation import Simulation, new_world
from mythfall.simulation.state import PLAYER, TICKS_PER_DAY


def run_day(seed=1741):
    simulation = Simulation(new_world(seed=seed))
    start_tick = simulation.world['tick']
    target = start_tick + TICKS_PER_DAY
    started = time.perf_counter()
    calls, chunks = 0, []
    while simulation.world['tick'] < target:
        calls += 1
        player = simulation.world['actors'][PLAYER]
        if player['hunger'] >= 6000:
            food = next(item for item in simulation.world['items'].values() if item['kind'] == 'food' and item['place'].get('carrier') == PLAYER)
            intent = {'kind': 'use', 'target': food['id']}
        elif simulation.world['pending'] and simulation.world['pending']['status'] == 'running':
            intent = {'kind': 'resume', 'wait_id': simulation.world['pending']['id']}
        else:
            intent = {'kind': 'wait', 'ticks': target - simulation.world['tick'], 'activity': 'rest'}
        # Food is taken only at a finished activity boundary.
        if simulation.world['pending'] and simulation.world['pending']['status'] == 'running' and intent['kind'] == 'use':
            simulation.command({'kind': 'cancel', 'wait_id': simulation.world['pending']['id']}, f'cancel-{calls}')
        before = time.perf_counter()
        simulation.command(intent, f'benchmark-{calls}')
        chunks.append(time.perf_counter() - before)
    return {'elapsed_seconds': time.perf_counter() - started, 'ticks': simulation.world['tick'] - start_tick,
            'commands': calls, 'max_chunk_seconds': max(chunks), 'p95_chunk_seconds': sorted(chunks)[int(len(chunks) * .95)],
            'event_count': len(simulation.world['events']), 'model_calls': 0}


if __name__ == '__main__':
    results = [run_day() for _ in range(3)]
    report = {'npc_count': 5, 'runs': results, 'median_day_seconds': statistics.median(r['elapsed_seconds'] for r in results)}
    path = Path('artifacts/mythfall-evaluations/benchmark.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    assert all(r['elapsed_seconds'] < 15 for r in results), 'Frozen day-advancement budget exceeded'
