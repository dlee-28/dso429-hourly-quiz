"""DSO 429 Homework 3 - hourly quiz solver.

Downloads questions.csv, answers every round that doesn't have an
answers/round-XXXX.json file yet, and writes those files.
No API key needed: each question type is solved with a formula, then
the option closest to the computed value is chosen.
"""
import csv, io, json, math, os, re, sys, urllib.request
from datetime import datetime, timedelta

QUESTIONS_URL = "https://raw.githubusercontent.com/FaisalXL/dso429-hourly-quiz/main/questions.csv"
ANSWER_DIR = "answers"
LETTERS = "ABCD"


def nums(text):
    """All numbers in a string, ignoring $ and thousands commas."""
    return [float(x.replace(",", "")) for x in re.findall(r"-?\d[\d,]*\.?\d*", text)]


def option_value(opt):
    found = nums(opt)
    return found[0] if found else None


def closest(target, options):
    """Letter of the option whose number is closest to target."""
    best, best_diff = None, float("inf")
    for letter, opt in zip(LETTERS, options):
        v = option_value(opt)
        if v is not None and abs(v - target) < best_diff:
            best, best_diff = letter, abs(v - target)
    return best


def solve(q, options):
    """Return 'A'-'D', or None if the question type isn't recognised."""
    t = q.lower()
    n = nums(q)

    if "settlement period" in t:
        m = re.search(r"signed on (\d{1,2} \w+ \d{4}) has a ([\d,]+)-day", q)
        d = datetime.strptime(m.group(1), "%d %B %Y") + timedelta(days=int(m.group(2).replace(",", "")))
        target = f"{d.day} {d.strftime('%B %Y')}"
        for letter, opt in zip(LETTERS, options):
            if opt.strip() == target:
                return letter
        return None

    if "compounded annually" in t:
        p, r, years = n[0], n[1] / 100, n[2]
        return closest(p * (1 + r) ** years, options)

    if "gross margin" in t:
        rev, cogs = n[0], n[1]
        return closest((rev - cogs) / rev * 100, options)

    if "percentage change" in t:
        old, new = n[0], n[1]
        return closest((new - old) / old * 100, options)

    if "discounted by" in t:
        price, pct = n[0], n[1]
        return closest(price * (1 - pct / 100), options)

    if "euros per us dollar" in t:
        return closest(n[0] * n[1], options)

    if "total revenue" in t and "units at" in t:
        return closest(n[0] * n[1], options)

    if "overall average order value" in t:
        c1, a1, c2, a2 = n[:4]
        return closest((c1 * a1 + c2 * a2) / (c1 + c2), options)

    if "break even" in t:
        fixed, price, var = n[:3]
        return closest(round(fixed / (price - var)), options)

    if "drawn at random" in t:
        m = re.search(r"holds (.*?)\. if one", t)
        counts = re.findall(r"(\d+) (\w+) tickets", m.group(1))
        total = sum(int(c) for c, _ in counts)
        want = re.search(r"probability it is an? (\w+) ticket", t).group(1)
        hit = sum(int(c) for c, kind in counts if kind == want)
        return closest(hit / total * 100, options)

    if "in the ratio" in t:
        budget = n[0]
        a, b = map(float, re.search(r"ratio (\d+):(\d+)", q).groups())
        share = a if "first" in t else b
        return closest(budget * share / (a + b), options)

    if "series runs" in t:
        seq = [float(x) for x in re.search(r"runs ([\d, .-]+?)\. if", t).group(1).split(",")]
        diffs = {seq[i + 1] - seq[i] for i in range(len(seq) - 1)}
        if len(diffs) == 1:
            return closest(seq[-1] + diffs.pop(), options)
        ratios = {seq[i + 1] / seq[i] for i in range(len(seq) - 1) if seq[i]}
        if len(ratios) == 1:
            return closest(seq[-1] * ratios.pop(), options)
        return None

    return None


def llm_fallback(q, options):
    """Used only for unrecognised question types, if ANTHROPIC_API_KEY is set."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        prompt = (q + "\n" + "\n".join(f"{l}) {o}" for l, o in zip(LETTERS, options))
                  + "\n\nWork it out carefully, then end with a final line of exactly: ANSWER: <letter>")
        msg = client.messages.create(model=os.environ.get("MODEL", "claude-sonnet-5-5"),
                                     max_tokens=1500, messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in msg.content if b.type == "text")
        m = re.findall(r"ANSWER:\s*([ABCD])", text)
        return m[-1] if m else None
    except Exception as e:
        print("  LLM fallback failed:", e)
        return None


def answer_question(q, options):
    try:
        ans = solve(q, options)
    except Exception as e:
        print("  solver error:", e)
        ans = None
    if ans is None:
        print("  UNRECOGNISED question, trying fallback:", q[:100])
        ans = llm_fallback(q, options) or "A"
    return ans


def load_rows(path=None):
    if path:
        text = open(path, encoding="utf-8").read()
    else:
        req = urllib.request.Request(QUESTIONS_URL, headers={"Cache-Control": "no-cache"})
        text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def main():
    rows = load_rows(sys.argv[1] if len(sys.argv) > 1 else None)
    rounds = {}
    for r in rows:
        rounds.setdefault(int(r["round_id"]), []).append(r)
    os.makedirs(ANSWER_DIR, exist_ok=True)

    for rid in sorted(rounds):
        path = os.path.join(ANSWER_DIR, f"round-{rid:04d}.json")
        if os.path.exists(path):
            continue
        qs = sorted(rounds[rid], key=lambda r: int(r["q_index"]))
        if len(qs) != 25:
            print(f"round {rid}: only {len(qs)} questions so far, skipping for now")
            continue
        answers = {}
        for r in qs:
            opts = [r["option_a"], r["option_b"], r["option_c"], r["option_d"]]
            answers[f"q{int(r['q_index'])}"] = answer_question(r["question_text"], opts)
        with open(path, "w") as f:
            json.dump({"round_id": rid, "answers": answers}, f, indent=2)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
