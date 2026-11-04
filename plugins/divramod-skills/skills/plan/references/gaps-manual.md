# Gaps and manual items

A gap found mid-plan and a thing only the user's hands can do have stores of their own** (plan 0595): a gap is
`hal2-cli-plans gaps add "<title>" --found-in <step>`, then `gaps route <n> servant <NN>|subplan <NN-slug>|plan <NNNN>`
(never a replaced CURRENT_PLAN: record [masterplan-stays-current](../../../../../../../../.adr/masterplan-stays-current.md)) and
`gaps close`; a hands-on step is `hal2-cli-plans manual add "<title>" [--from Q<n>]`, written in the step-by-step guide
form of `~/AGENTS.md` and linked from its question, never a copied question. `/work-manual` lists the open manual items.

