# Critique ignore list
# Each non-comment line is a finding to NOT re-raise on future `impeccable critique` runs.
# Match is case-insensitive substring against the rule name or snippet.

# False positive: detector pairs bg-emerald-600 (active ternary branch) with
# text-zinc-300 (inactive branch) on the same line in ConfigCard analyst pills.
# They never apply together — the active state is text-black. Not a real contrast issue.
text-zinc-300 on bg-emerald-600
# Same false positive on the start button: disabled:text-zinc-400 paired against
# the non-disabled bg-emerald-500. Disabled and active states never co-apply.
text-zinc-400 on bg-emerald-500
