"""Candidates for the wizard's reuse-first ladder: which facade method may stand for a stretch of the
recording, and which existing tests already run those facades. The engine only proposes."""

MAX_CANDIDATES = 3
MAX_TESTS = 5
POPUP = "Popup"
PAGE_SUFFIX = "Page"


def segments(plan: dict) -> list:
    """The plan's steps cut into stretches on one page: consecutive steps sharing a page, a '...Popup'
    page joining the open stretch, a login step on its own."""
    result = []
    for step in plan.get("steps") or []:
        pages = list(step.get("pages") or [])
        title = step.get("waitTitle")
        current = result[-1] if result else None
        if step.get("login") or current is None or current.get("login"):
            join = False
        elif not pages:
            join = True
        else:
            join = any(p in current["pages"] for p in pages) or all(p.endswith(POPUP) for p in pages)
        if not join:
            current = {"seqs": [], "pages": [], "titles": []}
            if step.get("login"):
                current["login"] = True
            result.append(current)
        current["seqs"].append(step["seq"])
        current["pages"] += [p for p in pages if p not in current["pages"]]
        if title and title not in current["titles"]:
            current["titles"].append(title)
    for segment in result:
        segment.pop("login", None)
    return result


def _plain(page: str) -> str:
    return page[:-len(PAGE_SUFFIX)] if page.endswith(PAGE_SUFFIX) else page


def facade_sequence(plan: dict, facades: list) -> list:
    """Per segment the (at most three) context-only facade methods that list most of its pages and titles."""
    sequence = []
    for segment in segments(plan):
        wanted = {("page", p) for p in segment["pages"]} | {("title", t) for t in segment["titles"]}
        candidates = []
        for entry in facades:
            if not entry.get("contextOnly") or not wanted:
                continue
            listed = {("page", _plain(p)) for p in entry.get("pages") or []} | \
                     {("title", t) for t in entry.get("titles") or []}
            shared = wanted & listed
            if not shared:
                continue
            candidates.append({
                "facade": entry["facade"], "method": entry["method"], "step": entry.get("step"),
                "score": round(len(shared) / len(wanted), 2),
                "why": "lists " + ", ".join(sorted(name for _, name in shared))})
        candidates.sort(key=lambda c: (-c["score"], c["facade"], c["method"]))
        sequence.append(dict(segment, candidates=candidates[:MAX_CANDIDATES]))
    return sequence


def existing_tests(sequence: list, folders: dict, folder) -> list:
    """Tests whose flow runs the segments' top candidates in order; the folder's tests first, at most five."""
    if not any(seg.get("candidates") for seg in sequence):
        return []
    # every segment counts; one without a candidate (call None) can never be covered
    wanted = [(seg["seqs"], "%s.%s" % (seg["candidates"][0]["facade"], seg["candidates"][0]["method"])
               if seg.get("candidates") else None) for seg in sequence]
    found = []
    for name, tests in (folders or {}).items():
        for test in tests:
            flow, at, covered, missing = test.get("flow") or [], 0, [], []
            for seqs, call in wanted:
                # greedy, in order: a flow that runs the facades in another order can be understated;
                # what it misses shows in missingSeqs
                if call and call in flow[at:]:
                    at += flow[at:].index(call) + 1
                    covered += seqs
                else:
                    missing += seqs
            if covered:
                done = len(wanted) - sum(1 for seqs, _ in wanted if seqs[0] in missing)
                found.append({"path": test["path"], "folder": name, "coveredSeqs": covered,
                              "missingSeqs": missing, "score": round(done / len(wanted), 2)})
    found.sort(key=lambda t: (t["folder"] != folder, -t["score"], t["path"]))
    return found[:MAX_TESTS]
