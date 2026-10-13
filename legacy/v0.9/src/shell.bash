#!/usr/bin/env bash
# Historical shell injection is retired in V1. No aliases/functions are defined.
printf '%s\n' 'mihomoctl: shell injection is retired; use mihomoctl exec -- COMMAND or env export.' >&2
return 2 2>/dev/null || exit 2
