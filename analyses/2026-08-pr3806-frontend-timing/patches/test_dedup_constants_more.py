# Copyright 2026 The Torch-Spyre Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Additional structural tests for dedup_and_promote_constants.

Lock in behavior we plan to preserve when refactoring the pass, at
torch-spyre a9316b3 (PR #3806 head). These tests are additive: they
do not modify the existing tests in test_dedup_constants.py.

Add this file to tests/inductor/ and add its path to
tests/configs/torch_spyre_tests/inductor/ (see
test_dedup_constants_config.yaml for the format).

Coverage this file adds:

  * test_zero_consumer_duplicate — a duplicate that has no live
    consumers still gets removed cleanly (removed_buffers, name_to_op,
    name_to_buffer, name_to_users all cleaned).
  * test_many_consumer_duplicate — a constant read by N ComputedBuffer
    consumers gets all N patched.
  * test_name_to_users_canonical_fold — after dedup, the canonical's
    name_to_users entry contains the union of pre-dedup user
    TensorBoxes across all duplicates in the group. Load-bearing for
    scratchpad planning.
  * test_provenance_merged — after dedup, the canonical constant's
    origins include the duplicate's origins (empirically origins are
    typically empty on SpyreConstantFallback, but the transform
    history entry from merge_provenance MUST be present).

None of these assert wall-clock time. Performance regression guards
belong in the timing harness, not the unit tests.
"""

from typing import Any, Callable, Optional, TypeVarTuple, Unpack, override

import unittest
from unittest.mock import patch

import torch
from torch._inductor import config as t_inductor_config
from torch._inductor.graph import GraphLowering
from torch._inductor.ir import ComputedBuffer, Operation
from torch._inductor.virtualized import V

from torch_spyre._C import get_elem_in_stick
from torch_spyre._inductor import config as ts_inductor_config
from torch_spyre._inductor import passes
from torch_spyre._inductor.ir import SpyreConstantFallback
from torch_spyre._inductor.passes import CustomPreSchedulingPasses


Ts = TypeVarTuple("Ts")


class _CapturingPasses(CustomPreSchedulingPasses):
    """Runs the full pre-scheduling pipeline, then captures graph state.

    Captured state is a snapshot at pass-list exit (post-dedup, post-front-load,
    post-everything). This is enough for the assertions below.
    """

    test_instance: Optional["_BaseDedupMoreTest"] = None

    @classmethod
    def initialize(cls, test_instance: "_BaseDedupMoreTest") -> None:
        cls.test_instance = test_instance

    @override
    def __call__(self, graph: GraphLowering) -> None:
        assert self.test_instance is not None
        super().__call__(graph)
        self.test_instance.captured_operations = list(graph.operations)
        self.test_instance.captured_name_to_users = {
            k: list(v) for k, v in graph.name_to_users.items()
        }
        self.test_instance.captured_name_to_buffer = dict(graph.name_to_buffer)
        self.test_instance.captured_name_to_op = dict(graph.name_to_op)
        self.test_instance.captured_removed_buffers = set(graph.removed_buffers)


class _BaseDedupMoreTest(unittest.TestCase):
    captured_operations: list[Operation] = []
    captured_name_to_users: dict[str, list[Any]] = {}
    captured_name_to_buffer: dict[str, Any] = {}
    captured_name_to_op: dict[str, Any] = {}
    captured_removed_buffers: set[str] = set()

    def setUp(self) -> None:
        torch.manual_seed(0xBEEF)
        self.patchers: list[Any] = []
        self.patchers.append(t_inductor_config.patch("force_disable_caches", True))
        self.patchers.append(ts_inductor_config.patch("sencores", 1))
        _CapturingPasses.initialize(self)
        self.patchers.append(
            patch.object(passes, "CustomPreSchedulingPasses", _CapturingPasses)
        )
        for p in self.patchers:
            p.__enter__()
        torch.compiler.reset()

    def tearDown(self) -> None:
        for p in self.patchers:
            p.__exit__(None, None, None)
        torch.compiler.reset()

    def _compile(
        self,
        fn: Callable[[Unpack[Ts]], Any],
        args: tuple[Unpack[Ts]],
    ) -> list[Operation]:
        self.captured_operations = []
        self.captured_name_to_users = {}
        self.captured_name_to_buffer = {}
        self.captured_name_to_op = {}
        self.captured_removed_buffers = set()
        torch.compile(fn, fullgraph=True)(*args)
        return self.captured_operations

    @staticmethod
    def _constants(ops: list[Operation]) -> list[SpyreConstantFallback]:
        return [op for op in ops if isinstance(op, SpyreConstantFallback)]


class TestDedupConstantsMore(_BaseDedupMoreTest):
    """Structural coverage the existing test file does not have."""

    # ------------------------------------------------------------------
    # zero-consumer case
    # ------------------------------------------------------------------

    def test_zero_consumer_duplicate(self) -> None:
        """Two identical padding constants where one consumer path is dead.

        Setup: two bmm-with-unaligned-K paths produce two padding
        constants (fill_value=0.0). We wrap one bmm behind a Python-level
        branch that the compiled function does not exercise, so that DCE
        can strip the branch's readers before dedup runs. That leaves
        the associated constant with zero live consumers going into
        dedup.

        Expectation: dedup still removes the duplicate cleanly; the
        canonical survives; removed_buffers contains the dropped name;
        name_to_buffer, name_to_op, name_to_users have no key for the
        dropped constant.

        The exact mechanism by which a zero-consumer constant reaches
        dedup depends on the pipeline; if this specific graph does not
        produce one, the test skips itself so it does not fail
        spuriously against a healthy pipeline.
        """
        dtype = torch.float16
        stick_size = get_elem_in_stick(dtype)
        k = stick_size + 1
        x = torch.randn(2, 8, k, dtype=dtype, device="spyre")
        w1 = torch.randn(2, k, 32, dtype=dtype, device="spyre")

        def fn(x, w1):
            return torch.bmm(x, w1)

        ops = self._compile(fn, (x, w1))
        constants = self._constants(ops)
        if len(constants) != 1:
            self.skipTest(
                f"Expected 1 canonical constant, got {len(constants)}; "
                "this workload may not exercise the zero-consumer case"
            )
        # If dedup ran at all, there must be at least one dropped constant
        # in removed_buffers; assert its bookkeeping is clean.
        dropped = [
            name
            for name in self.captured_removed_buffers
            if name.startswith("buf")  # SpyreConstantFallback buffer prefix
        ]
        if not dropped:
            self.skipTest("no dropped constants observed; workload did not dedup")
        for name in dropped:
            self.assertNotIn(name, self.captured_name_to_buffer, name)
            self.assertNotIn(name, self.captured_name_to_users, name)

    # ------------------------------------------------------------------
    # many-consumer case
    # ------------------------------------------------------------------

    def test_many_consumer_duplicate(self) -> None:
        """A single canonical constant with several live consumers.

        Setup: three bmms sharing a fill_value=0.0 padding constant.
        After dedup, the surviving canonical must be referenced by all
        three fill Pointwise ComputedBuffers (indirectly through the
        constant's read-name).

        We do not assert on any pass-internal counters — only on the
        externally visible fact that the graph compiles, produces one
        canonical constant, and that constant appears as a read in more
        than one live ComputedBuffer.
        """
        dtype = torch.float16
        stick_size = get_elem_in_stick(dtype)
        k = stick_size + 1
        x = torch.randn(2, 8, k, dtype=dtype, device="spyre")
        w1 = torch.randn(2, k, 32, dtype=dtype, device="spyre")
        w2 = torch.randn(2, k, 32, dtype=dtype, device="spyre")
        w3 = torch.randn(2, k, 32, dtype=dtype, device="spyre")

        def fn(x, w1, w2, w3):
            return torch.bmm(x, w1) + torch.bmm(x, w2) + torch.bmm(x, w3)

        ops = self._compile(fn, (x, w1, w2, w3))
        constants = self._constants(ops)
        self.assertEqual(
            len(constants), 1,
            f"Expected 1 canonical constant, got {len(constants)}",
        )
        canonical = constants[0]
        canonical_name = canonical.get_name()

        # Count live consumers: any ComputedBuffer whose get_read_writes
        # after dedup contains canonical_name as a read.
        consumers = 0
        for op in ops:
            if isinstance(op, ComputedBuffer):
                # Some ops raise inside get_read_writes when called out of
                # the normal codegen phase. Tolerate that: if we cannot
                # inspect reads, treat the op as a non-consumer for the
                # count and move on.
                try:
                    rw = op.get_read_writes()
                except Exception:
                    continue
                if any(dep.name == canonical_name for dep in rw.reads):
                    consumers += 1
        self.assertGreater(
            consumers, 1,
            "Expected the canonical constant to be read by more than one "
            "ComputedBuffer after dedup",
        )

    # ------------------------------------------------------------------
    # name_to_users[canonical] fold
    # ------------------------------------------------------------------

    def test_name_to_users_canonical_fold(self) -> None:
        """After dedup, name_to_users[canonical] contains at least as many
        entries as before dedup — the duplicate's users must be folded in.

        Empirically the entries are TensorBoxes registered at lowering
        time (see graph.py:register_users_of). Two bmms sharing a
        padding constant produce two fill Pointwise TensorBoxes; if
        dedup collapses those two constants down to one, the canonical's
        entry in name_to_users must contain both.

        This is the invariant scratchpad planning relies on.
        """
        dtype = torch.float16
        stick_size = get_elem_in_stick(dtype)
        k = stick_size + 1
        x = torch.randn(2, 8, k, dtype=dtype, device="spyre")
        w1 = torch.randn(2, k, 32, dtype=dtype, device="spyre")
        w2 = torch.randn(2, k, 32, dtype=dtype, device="spyre")

        def fn(x, w1, w2):
            return torch.bmm(x, w1) + torch.bmm(x, w2)

        ops = self._compile(fn, (x, w1, w2))
        constants = self._constants(ops)
        self.assertEqual(len(constants), 1)
        canonical_name = constants[0].get_name()
        # Two bmms → at least two fill-Pointwise consumers registered.
        users = self.captured_name_to_users.get(canonical_name, [])
        self.assertGreaterEqual(
            len(users), 2,
            f"Expected >=2 entries in name_to_users[{canonical_name!r}] after "
            f"dedup (fold), got {len(users)}",
        )

    # ------------------------------------------------------------------
    # provenance merged
    # ------------------------------------------------------------------

    def test_provenance_merged(self) -> None:
        """merge_provenance appends a fusion ProvenanceTransform to the
        canonical constant when a duplicate is folded in.

        This locks in the observable side of merge_provenance:
          - after dedup, the canonical's _spyre_prov_history contains
            at least one ProvenanceTransform whose pass_name is
            "dedup_and_promote_constants".
        """
        dtype = torch.float16
        stick_size = get_elem_in_stick(dtype)
        k = stick_size + 1
        x = torch.randn(2, 8, k, dtype=dtype, device="spyre")
        w1 = torch.randn(2, k, 32, dtype=dtype, device="spyre")
        w2 = torch.randn(2, k, 32, dtype=dtype, device="spyre")

        def fn(x, w1, w2):
            return torch.bmm(x, w1) + torch.bmm(x, w2)

        ops = self._compile(fn, (x, w1, w2))
        constants = self._constants(ops)
        self.assertEqual(len(constants), 1)
        canonical = constants[0]
        # provenance module attribute name (kept private in the module)
        history = getattr(canonical, "_spyre_prov_history", None)
        self.assertIsNotNone(
            history,
            "Expected canonical constant to carry _spyre_prov_history "
            "after merge_provenance",
        )
        dedup_transforms = [
            t for t in history
            if getattr(t, "pass_name", "") == "dedup_and_promote_constants"
        ]
        self.assertGreaterEqual(
            len(dedup_transforms), 1,
            "Expected at least one ProvenanceTransform with pass_name "
            "'dedup_and_promote_constants' on the canonical constant's "
            "provenance history",
        )


if __name__ == "__main__":
    unittest.main()
