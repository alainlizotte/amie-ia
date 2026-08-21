# Tests des stades relationnels — miroir de server/relation/stages.py.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.relation.stages import (  # noqa: E402
    STAGE_INSTRUCTIONS,
    STAGE_ORDER,
    can_play_stage,
    clamp_score,
    compute_stage,
    get_stage_instruction,
    stage_index,
)


class TestComputeStage:
    def test_frontieres_exactes(self):
        assert compute_stage(0) == "rejet"
        assert compute_stage(99) == "rejet"
        assert compute_stage(100) == "froid"
        assert compute_stage(199) == "froid"
        assert compute_stage(200) == "reserve"
        assert compute_stage(399) == "reserve"
        assert compute_stage(400) == "neutre"
        assert compute_stage(599) == "neutre"
        assert compute_stage(600) == "chaleureux"
        assert compute_stage(799) == "chaleureux"
        assert compute_stage(800) == "proche"

    def test_hors_limites(self):
        assert compute_stage(-50) == "rejet"
        assert compute_stage(100000) == "proche"


class TestClampScore:
    def test_bornes(self):
        assert clamp_score(-10) == 0
        assert clamp_score(5000) == 1000
        assert clamp_score(450) == 450


class TestStageIndex:
    def test_ordre(self):
        assert stage_index("rejet") == 0
        assert stage_index("proche") == len(STAGE_ORDER) - 1
        assert stage_index("inconnu") == -1


class TestCanPlayStage:
    def test_gate_stricte(self):
        # Un event min_stage "chaleureux" ne sort pas avant ce stade.
        assert not can_play_stage("chaleureux", "neutre")
        assert can_play_stage("chaleureux", "chaleureux")
        assert can_play_stage("chaleureux", "proche")

    def test_tous_stades_couverts(self):
        for st in STAGE_ORDER:
            assert st in STAGE_INSTRUCTIONS
            instr = get_stage_instruction(st)
            assert isinstance(instr, str) and instr
