"""Restart and seed point candidates for the wizard: where a failed run may resume, and whether it can
resume safely (a block that already committed something must not run twice). The engine only proposes."""

import flow_match

# action label (lower case) -> commit kind, the kinds the project scan uses for component effects
COMMIT_LABELS = {
    "issue policy": "issue", "issue now": "issue", "issue": "issue",
    "bind only": "bind", "bind options": "bind", "bind policy change": "bind",
    "make payment": "payment", "pay": "payment",
    "cancel now": "cancel", "reinstate": "reinstate", "rewrite": "rewrite",
}
PRIORITY = {"stateChanging": 0, "centerSwitch": 1, "setup": 2}
CREATE_PREFIX = "create"
ACCOUNT_CREATE_TITLES = ("new account", "create account", "enter account information")


def _commit_kind(action: dict):
    """The commit kind an action performs, or None."""
    kind = COMMIT_LABELS.get((action.get("label") or "").strip().lower())
    if kind is None and action.get("wizardAction") == "issue":
        kind = "issue"
    return kind


def _commits_with_later_work(steps: list) -> list:
    """(kind, commit seq, later seqs) for every step holding a commit action that any action or check follows
    anywhere later in the recording (later steps, or checks of the commit step itself, which run after
    its actions)."""
    found = []
    for index, entry in enumerate(steps):
        kinds = [_commit_kind(a) for a in entry.get("actions") or []]
        kinds = [k for k in kinds if k]
        if not kinds:
            continue
        later = [e["seq"] for e in steps[index + 1:] if e.get("actions") or e.get("checks")]
        if entry.get("checks"):
            later.insert(0, entry["seq"])
        if later:
            found.append((kinds[0], entry["seq"], later))
    return found


def _seqs_text(seqs: list) -> str:
    return "seq " + ", ".join(str(s) for s in seqs)


def restart_candidates(plan: dict, sequence: list, effects: list) -> list:
    """Restart points at segment boundaries, one per boundary: stateChanging > centerSwitch > setup."""
    steps = plan.get("steps") or []
    segs = flow_match.segments(plan)
    sequence = sequence if len(sequence) == len(segs) else []
    effect_by_path = {e.get("path"): e for e in effects or [] if e.get("path")}
    found = {}  # afterSeq -> {kind: candidate}

    def add(after, kind, reason, risk="safe", policy=None):
        found.setdefault(after, {})[kind] = {"afterSeq": after, "kind": kind, "reason": reason,
                                             "rerunRisk": risk, "proposePolicy": policy}

    for kind, at, later in _commits_with_later_work(steps):
        add(at, "stateChanging", "%s at seq %d is followed by more work (%s): put a restart point right after "
            "seq %d, or run the block that contains it with DISABLE_ON_FAILURE so a resume never repeats the %s"
            % (kind, at, _seqs_text(later), at, kind), "notResumable", "DISABLE_ON_FAILURE")
    last_setup = None
    for index, segment in enumerate(segs):
        end = segment["seqs"][-1]
        top = (sequence[index].get("candidates") or [None])[0] if sequence else None
        if top and effect_by_path.get(top.get("step"), {}).get("afterCommit"):
            effect = effect_by_path[top["step"]]
            kinds = ", ".join(effect.get("commits") or []) or "a commit"
            add(end, "stateChanging", "%s.%s commits (%s) and then keeps working; a resumed run would commit "
                "it again (%s)" % (top["facade"], top["method"], kinds, _seqs_text(segment["seqs"])),
                "notResumable", "DISABLE_ON_FAILURE")
        if top and (top.get("method") or "").startswith(CREATE_PREFIX) and index < len(segs) - 1:
            last_setup = (end, "%s.%s sets the data up; later blocks can restart from here" %
                          (top["facade"], top["method"]))
    if last_setup:
        add(last_setup[0], "setup", last_setup[1])
    for position, entry in enumerate(steps):
        if entry.get("appSwitch") and position:
            add(steps[position - 1]["seq"], "centerSwitch",
                "the next step (seq %d) switches to %s" % (entry["seq"], (entry.get("app") or "another center").upper()))

    result = []
    for after in sorted(found):
        chosen = sorted(found[after].values(), key=lambda c: PRIORITY[c["kind"]])
        best = dict(chosen[0])
        if len(chosen) > 1:
            best["reason"] += "; also " + ", ".join(c["kind"] for c in chosen[1:])
        result.append(best)
    return result


def _is_create_account(entry: dict) -> bool:
    title = (entry.get("waitTitle") or "").strip().lower()
    return title.startswith(ACCOUNT_CREATE_TITLES)


def _seed_for(entry: dict, created_account: bool):
    """(seed, why) for a step by its title, or None."""
    title = (entry.get("waitTitle") or "").strip()
    if title.startswith("Account Summary") and created_account:
        return "NEW_ACCOUNT", "Account Summary right after an account was created"
    if title.startswith("Pre-Quote Issues"):
        return "PRE_QUOTE", "the Pre-Quote Issues screen is reached"
    if title == "Quote":
        return "QUOTED", "the Quote screen is reached"
    if title.startswith(("Submission Bound", "Policy Change Bound", "Job Complete")):
        return "ISSUED_POLICY", "'%s' shows the policy is issued" % title
    if title.startswith("Claim") and entry.get("app") == "cc":
        return "CLAIM", "a claim is open in ClaimCenter"
    return None


def seed_points(plan: dict) -> list:
    """Steps whose screen a seeded state could stand in for; a run of steps on one seed lists once."""
    result, created, previous = [], False, None
    for entry in plan.get("steps") or []:
        seed = _seed_for(entry, created)
        if seed and seed[0] != previous:
            result.append({"seq": entry["seq"], "seed": seed[0], "why": seed[1]})
        previous = seed[0] if seed else None
        created = created or _is_create_account(entry)
    return result
