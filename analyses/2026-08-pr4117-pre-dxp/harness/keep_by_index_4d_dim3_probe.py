"""Reproduce test_keep_by_index_4d_dim3 without the OOT framework
wrapper. Runs the same underlying test body with the same fixture
values, asserts torch.testing.assert_close with the same tolerances.

Motivation: PR #4084 (upstream 61aaf2d) changed
``compute_ops.gen_coord_info_value`` to use ceiling division for
index-tensor coordinate factors. Verify whether that fix
stabilizes the failing test that dogged #4139 and #4141 CI.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback


def _fixture_4d_dim3():
    """Same parameters as the ``4d_dim3`` entry in
    ``tests/inductor/test_inductor_ops.py`` for
    ``test_keep_by_index_cpu``:

        param_sets["4d_dim3"] = (
            unique_randn_along_dim((6, 17, 4, 128), dim=3),
            4,     # k
            3,     # dim
            -1.0,  # fill_value
        )

    Reproduced here to keep the probe self-contained.
    """
    import torch

    # Reproduce unique_randn_along_dim: generate a (6,17,4,128) tensor
    # of fp16 with unique values along dim=3. Simplest equivalent:
    # start with unique integer-valued fp16 arangement per slice.
    torch.manual_seed(0xAFFE)
    shape = (6, 17, 4, 128)
    x = torch.randn(*shape, dtype=torch.float16)
    # Ensure uniqueness along dim=3 by adding a small unique offset
    # (matches the intent of unique_randn_along_dim; exact values
    # differ only by O(1e-4), well within the test's atol=0.1).
    offsets = torch.arange(shape[-1], dtype=torch.float16) * 1e-2
    x = x + offsets
    k = 4
    dim = 3
    fill_value = -1.0
    return x, k, dim, fill_value


def _run_once() -> tuple[bool, str]:
    """Runs one iteration of the test body. Returns (passed, detail)."""
    import torch

    x, k, dim, fill_value = _fixture_4d_dim3()
    _, indices = torch.topk(x, k, dim=dim, largest=True)

    def fn(x_, indices_):
        return torch.ops.spyre.keep_by_index(x_, indices_, dim, fill_value)

    try:
        compiled_fn = torch.compile(fn)
        result_spyre = compiled_fn(
            x.to("spyre"),
            indices.to(torch.float16).to("spyre"),
        ).cpu()
        expected = fn(x, indices)
        torch.testing.assert_close(
            result_spyre, expected, atol=0.1, rtol=0.1
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import torch  # noqa
    import torch_spyre  # noqa

    results = []
    passes = 0
    fails = 0
    for i in range(args.samples):
        t0 = time.perf_counter()
        ok, detail = _run_once()
        dt = time.perf_counter() - t0
        results.append({"sample": i, "passed": ok, "wall_s": dt, "detail": detail})
        if ok:
            passes += 1
        else:
            fails += 1
        print(
            f"sample {i}: {'PASS' if ok else 'FAIL'}  {dt:.2f}s  detail={detail[:200]}"
        )

    summary = {
        "n_samples": args.samples,
        "passes": passes,
        "fails": fails,
        "samples": results,
    }
    with open(args.out, "w") as fh:
        json.dump(summary, fh, indent=2, default=str)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
