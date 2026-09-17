"""Atomic, versioned world snapshots inside the existing workspace history."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .engine import Simulation
from .seed import new_world
from .state import ActionError, validate_world
from .migration import upgrade_world


class WorldStore:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.directory = self.workspace / "state"
        self.path = self.directory / "world.json"

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.directory.resolve().parent != self.workspace:
            raise ActionError("World state directory must stay inside this workspace.")
        lock = self.directory / "world.lock"
        if lock.is_symlink():
            raise ActionError("World lock cannot be a symbolic link.")
        with lock.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def read(self):
        if self.path.is_symlink():
            raise ActionError("World state cannot be a symbolic link.")
        if not self.path.exists():
            return new_world(self.workspace)
        return validate_world(upgrade_world(json.loads(self.path.read_text(encoding="utf-8"))))

    def save(self, world):
        validate_world(world)
        temporary = None
        try:
            with NamedTemporaryFile("w", encoding="utf-8", dir=self.directory, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(world, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def ensure(self):
        with self.locked():
            world = self.read()
            if not self.path.exists():
                self.save(world)
            return world

    def execute(self, intent, operation_id, *, expected_revision=None, chunk_ticks=300):
        from ..game_chat import record_result

        with self.locked():
            before = self.read()
            simulation = Simulation(before)
            result = simulation.command(intent, operation_id, expected_revision=expected_revision, chunk_ticks=chunk_ticks)
            record_result(before, simulation.world, intent, operation_id, result)
            self.save(simulation.world)
            return result, simulation.world
