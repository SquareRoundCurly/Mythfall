"""Bounded, resumable Fal portrait generation for the authored Emberwick cast."""

import hashlib
import json
from pathlib import Path

from RealmEngine.asset_import import download_asset, sprite_asset
from RealmEngine.media import MediaJobs

SEED = Path(__file__).parents[1] / "mythfall" / "seed"
STYLE = (
    "A polished hand-painted portrait for a grounded medieval fantasy roleplaying game, "
    "bust portrait with face clearly readable at small sizes, softly textured gouache and oil paint, "
    "subtle expressive eyes, warm candlelight and cool misty shadows, muted moss green, brown and aged gold. "
    "Square composition, centered head and shoulders, plain dark desaturated green backdrop, "
    "no frame, no writing, no UI, no extra people. "
)
SUBJECTS = {
    "old_nessa": "Old Nessa, an elderly herbalist with a deeply lined face, knowing gentle smile, silver hair tied back, a faded plum shawl, and dried reeds tucked into her clothes.",
    "tommen_ash": "Tommen Ash, a sturdy middle-aged innkeeper with weathered features, a short dark beard, rolled linen sleeves and a brown apron; warm hospitality over tired worried eyes.",
    "mara_vell": "Mara Vell, a practical middle-aged female village reeve with dark tied-back hair, visibly underslept but determined, a plain blue wool coat and a small brass seal brooch.",
    "ellis_crow": "Ellis Crow, a nervous slender adult male scholar, tousled dark hair, cracked round spectacles, ink-stained fingers holding a weathered notebook, worn green scholar's clothes.",
    "brakka": "Brakka, a tough adult female road-bandit leader with strong stocky build, ruddy weathered face, short unruly auburn hair, patched rust-red leather armor, an intimidating expression with a trace of unease.",
}


def main():
    directory = SEED / "assets" / "portraits"
    directory.mkdir(parents=True, exist_ok=True)
    jobs = MediaJobs(SEED)
    try:
        for slug, subject in SUBJECTS.items():
            destination = directory / slug
            manifest = destination / "asset.json"
            if manifest.exists():
                print(json.dumps({"asset": slug, "status": "installed"}), flush=True)
                continue
            job = jobs.generate(kind="image", name=f"mythfall-portrait-{slug}", prompt=STYLE + subject, wait_seconds=0)
            if job["status"] == "completed":
                result = job["result"]["images"][0]
                url = result["url"] if isinstance(result, dict) else result
                files, metadata = sprite_asset(download_asset(url))
                destination.mkdir(parents=True, exist_ok=True)
                for name, data in files.items():
                    (destination / name).write_bytes(data)
                record = {k: job[k] for k in ("job_id", "request_id", "name", "instruction", "kind", "model")}
                record.update(metadata, sha256={name: hashlib.sha256(data).hexdigest() for name, data in files.items()})
                manifest.write_text(json.dumps(record, indent=2) + "\n")
            print(json.dumps({"asset": slug, "status": job["status"], "job_id": job["job_id"]}), flush=True)
    finally:
        jobs.close()


if __name__ == "__main__":
    main()
