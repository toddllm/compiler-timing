#!/bin/bash
# Toggle propagate_layouts.py line 1910 between pre-fix (_all_constant_layouts)
# and post-fix ([generic_layout(op)]).
#
# Usage:
#   toggle_layout_fix.sh pre        # pre-#3812 state
#   toggle_layout_fix.sh post       # post-#3812 state
#   toggle_layout_fix.sh status     # show current state

set -euo pipefail

CHECKOUT=${TORCH_SPYRE_CHECKOUT:-$HOME/pr3806/torch-spyre}
F="$CHECKOUT/torch_spyre/_inductor/propagate_layouts.py"

case "${1:-status}" in
    status)
        line=$(sed -n '1910p' "$F")
        case "$line" in
            *"_all_constant_layouts"*) echo "state: PRE-FIX";;
            *"generic_layout"*)         echo "state: POST-FIX";;
            *) echo "state: UNKNOWN — line 1910: $line";;
        esac
        ;;
    pre)
        # Restore pre-fix form.
        sed -i "1910s|op.layouts = \[generic_layout(op)\]|op.layouts = _all_constant_layouts(op)|" "$F"
        echo "toggled to PRE-FIX"
        sed -n '1910p' "$F"
        ;;
    post)
        # Apply the 1-line fix from PR #3812.
        sed -i "1910s|op.layouts = _all_constant_layouts(op)|op.layouts = [generic_layout(op)]|" "$F"
        echo "toggled to POST-FIX"
        sed -n '1910p' "$F"
        ;;
    *)
        echo "usage: $0 {pre|post|status}" >&2
        exit 2
        ;;
esac
