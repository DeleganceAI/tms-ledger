"""Murdle eval tests. From the repo root:

    uv run python -m evals.test_murdle
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.murdle.agents import MockAgent, OpenAIAgent, ReferenceAgent, ScriptedAgent, build_agent
from evals.murdle.classic import catalog, gallery, terrace, zebra
from evals.murdle.generate import generate
from evals.murdle.harness import make_task, run_eval
from evals.murdle.model import Atom, Category, Clue, Puzzle, dump_puzzle, load_puzzle
from evals.murdle.quote import normalize_quote, quote_in_evidence
from evals.murdle.session import EvalCollection
from evals.murdle.solver import clue_holds, solve
from tms import events as E

SECRET = bytes.fromhex("11" * 32)


class QuoteTests(unittest.TestCase):
    def test_folds_like_the_server(self):
        self.assertEqual(normalize_quote("  Hello   World "), "hello world")
        self.assertEqual(normalize_quote("word—word"), "word-word")
        self.assertEqual(normalize_quote("word — word"), "word-word")
        self.assertEqual(normalize_quote("“Quotes”"), '"quotes"')
        self.assertEqual(normalize_quote("ﬁle"), "file")
        self.assertEqual(normalize_quote("a\u00adb"), "ab")
        self.assertEqual(normalize_quote("a\u00a0b"), "a b")
        self.assertTrue(quote_in_evidence("he said “hello”", "He said \"hello\" today"))
        self.assertFalse(quote_in_evidence("he said hello", "He said \"hello\" today"))


class SolverTests(unittest.TestCase):
    def test_catalog_matches_the_known_grids(self):
        self.assertEqual(zebra().answer_key(), {"water": "Norwegian", "zebra": "Japanese"})
        self.assertEqual(terrace().answer_key(), {"tea": "Ada"})
        self.assertEqual(gallery().answer_key(), {"lens": "Jules", "frame": "studio"})
        for puzzle in catalog().values():
            found = solve(puzzle, limit=2)
            self.assertTrue(found.complete, puzzle.id)
            self.assertEqual(found.solutions, [puzzle.solution], puzzle.id)
            self.assertTrue(all(clue_holds(puzzle, clue) for clue in puzzle.clues))
            bare = puzzle.without_red_herrings()
            self.assertEqual(solve(bare, limit=2).solutions, [puzzle.solution], puzzle.id)

    def test_left_of_chain_is_unique(self):
        puzzle = _hand(
            (Category("house", ("1", "2", "3"), True), Category("person", ("Ada", "Bo", "Cy"))),
            (
                Clue("c1", "relational", "Ada is somewhere left of Bo.",
                     Atom("person", "Ada"), Atom("person", "Bo"), "left_of"),
                Clue("c2", "relational", "Bo is somewhere left of Cy.",
                     Atom("person", "Bo"), Atom("person", "Cy"), "left_of"),
            ),
            (("1", "Ada"), ("2", "Bo"), ("3", "Cy")),
        )
        self.assertEqual(solve(puzzle, limit=2).solutions, [puzzle.solution])

    def test_one_clue_is_not_unique(self):
        puzzle = _hand(
            (
                Category("house", ("1", "2", "3"), True),
                Category("person", ("Ada", "Bo", "Cy")),
                Category("drink", ("tea", "coffee", "juice")),
            ),
            (Clue("c1", "direct", "Ada is in house 1.", Atom("person", "Ada"), Atom("house", "1")),),
            (("1", "Ada", "tea"), ("2", "Bo", "coffee"), ("3", "Cy", "juice")),
        )
        found = solve(puzzle, limit=2)
        self.assertTrue(found.complete)
        self.assertEqual(len(found.solutions), 2)

    def test_contradiction_has_no_solution(self):
        puzzle = _hand(
            (Category("house", ("1", "2"), True), Category("person", ("Ada", "Bo"))),
            (
                Clue("c1", "direct", "Ada is in house 1.", Atom("person", "Ada"), Atom("house", "1")),
                Clue("c2", "direct", "Ada is in house 2.", Atom("person", "Ada"), Atom("house", "2")),
            ),
            (("1", "Ada"), ("2", "Bo")),
        )
        found = solve(puzzle, limit=2)
        self.assertEqual(found.solutions, [])
        self.assertTrue(found.complete)


class GeneratorTests(unittest.TestCase):
    def test_seed_is_deterministic_and_changes_the_grid(self):
        first = generate(dimensions=3, entities=5, clues=14, seed=3)
        second = generate(dimensions=3, entities=5, clues=14, seed=3)
        other = generate(dimensions=3, entities=5, clues=14, seed=4)
        self.assertEqual(dump_puzzle(first), dump_puzzle(second))
        self.assertNotEqual(first.solution, other.solution)
        again = load_puzzle(dump_puzzle(first))
        self.assertEqual(again.solution, first.solution)
        self.assertEqual([clue.text for clue in again.clues], [clue.text for clue in first.clues])
        self.assertEqual(solve(again, limit=2).solutions, [again.solution])

    def test_unique_with_and_without_red_herrings(self):
        puzzle = generate(dimensions=4, entities=4, clues=16, seed=2)
        found = solve(puzzle, limit=2)
        self.assertTrue(found.complete and found.solutions == [puzzle.solution])
        self.assertTrue(any(clue.kind == "red_herring" for clue in puzzle.clues))
        self.assertTrue(all(clue_holds(puzzle, clue) for clue in puzzle.clues))
        bare = puzzle.without_red_herrings()
        self.assertTrue(all(clue.kind != "red_herring" for clue in bare.clues))
        self.assertEqual(solve(bare, limit=2).solutions, [puzzle.solution])
        self.assertLess(len(bare.clues), len(puzzle.clues))

    def test_clue_types_are_honored(self):
        negative = generate(dimensions=3, entities=4, clues=18, clue_types=("negative",), red_herrings=0, seed=1)
        self.assertTrue(all(clue.kind == "negative" for clue in negative.clues))
        self.assertEqual(solve(negative, limit=2).solutions, [negative.solution])
        relational = generate(dimensions=3, entities=4, clues=12, clue_types=("relational",), red_herrings=0, seed=1)
        self.assertTrue(relational.categories[0].ordered)
        self.assertTrue(all(clue.kind == "relational" for clue in relational.clues))
        self.assertEqual(solve(relational, limit=2).solutions, [relational.solution])

    def test_minimal_and_large_grids(self):
        small = generate(dimensions=3, entities=3, clues=None, clue_types=("direct", "negative"),
                         red_herrings=0, seed=0)
        self.assertEqual(solve(small, limit=2).solutions, [small.solution])
        started = time.perf_counter()
        large = generate(dimensions=4, entities=20, clues=60, clue_types=("direct",), red_herrings=0, seed=2)
        self.assertLess(time.perf_counter() - started, 10)
        self.assertEqual(len(large.clues), 60)
        self.assertEqual(solve(large, limit=2).solutions, [large.solution])

    def test_rejects_a_grid_the_solver_cannot_certify(self):
        with self.assertRaises(ValueError):
            generate(dimensions=1, entities=4, seed=0)
        with self.assertRaises(ValueError):
            generate(dimensions=3, entities=90, seed=0)


class SessionTests(unittest.TestCase):
    def test_quotes_batch_and_proof(self):
        collection = EvalCollection("murdle-terrace", secret=SECRET)
        collection.load_puzzle(terrace())
        for event in collection.signed_events():
            E.verify(event)
        evidence = collection.records(E.EVIDENCE)
        self.assertEqual(len(evidence), 6)
        self.assertEqual(len(collection.list_evidence(limit=2, offset=0)), 2)
        self.assertEqual(len(collection.list_evidence(limit=2, offset=4)), 2)
        claim = collection.add_claim("PAIR\tseat\t1\tperson\tAda")
        linked = collection.add_link(evidence[0]["id"], claim["id"], "SUPPORTS", evidence[0]["content"]["text"],
                                     "The clue seats Ada.")
        self.assertEqual(linked["content"]["relation"], "SUPPORTS")
        before = len(collection.records(E.CLAIM))
        bad_claim = E.sign(SECRET, E.CLAIM, {"collection": "murdle-terrace", "text": "a second claim"},
                           created_at=1_900_000_000)
        bad_link = E.sign(SECRET, E.LINK, {
            "collection": "murdle-terrace", "from": evidence[0]["id"], "to": bad_claim["id"],
            "relation": "SUPPORTS", "quote": "this sentence is not in the clue", "reason": "no"},
            created_at=1_900_000_001)
        with self.assertRaises(E.Invalid) as caught:
            collection.publish([bad_claim, bad_link])
        self.assertIn("quote", str(caught.exception))
        self.assertEqual(len(collection.records(E.CLAIM)), before)
        self.assertGreater(collection.rejected_links, 0)
        again = collection.publish([collection.signed_events()[1]])
        self.assertIn(collection.signed_events()[1]["id"], again["skipped"])
        with self.assertRaises(E.Invalid):
            collection.add_link(evidence[0]["id"], evidence[0]["id"], "QUALIFIES",
                                evidence[0]["content"]["text"], "qualifying a document is not allowed")
        proof = {"question": "Who sits in seat 1?", "steps": [
            {"id": "s1", "say": "A clue seats someone.", "from": [evidence[0]["id"]]},
            {"id": "root", "say": "The claim cites that clue.", "from": ["s1", claim["id"]]},
        ]}
        self.assertTrue(collection.check_proof(proof)["ok"])
        self.assertFalse(collection.check_proof(
            {"question": "q", "steps": [{"id": "only", "say": "No grounds.", "from": []}]})["ok"])
        self.assertTrue(collection.check_proof(
            {"question": "q", "steps": [{"id": "only", "say": "I am guessing.", "from": [], "gap": True}]})["ok"])

    def test_curly_quote_is_the_same_citation(self):
        text = "He said \u201chello\u201d and paid 10\u201312."
        puzzle = _hand(
            (Category("seat", ("1", "2"), True), Category("person", ("Ada", "Bo"))),
            (Clue("q1", "direct", text, Atom("seat", "1"), Atom("person", "Ada")),),
            (("1", "Ada"), ("2", "Bo")),
        )
        collection = EvalCollection("murdle-quotes", secret=SECRET)
        evidence_id = collection.load_puzzle(puzzle)[0]
        claim = collection.add_claim("PAIR\tseat\t1\tperson\tAda")
        linked = collection.add_link(evidence_id, claim["id"], "SUPPORTS", 'he said "hello" and paid 10-12.',
                                     "Same sentence, plain punctuation.")
        self.assertEqual(linked["kind_name"], "link")
        with self.assertRaises(E.Invalid):
            collection.add_link(evidence_id, claim["id"], "SUPPORTS", "he said hello and paid 10-12",
                                "The quotation marks were dropped.")


class HarnessTests(unittest.TestCase):
    def test_prompts_hide_clues_until_baseline(self):
        hidden = make_task(terrace(), "tms", formal=False)
        shown = make_task(terrace(), "baseline", formal=False)
        self.assertIsNone(hidden.formal_clues)
        self.assertNotIn("Ada sits in seat 1.", hidden.prompt)
        self.assertIn("Ada sits in seat 1.", shown.prompt)
        self.assertNotIn("solution", {field.name for field in hidden.__dataclass_fields__.values()})

    def test_reference_writes_a_trail_and_the_baseline_does_not(self):
        report = run_eval(terrace(), ReferenceAgent())
        tms, baseline = report["modes"]["tms"], report["modes"]["baseline"]
        self.assertTrue(tms["solved"], tms["error"])
        self.assertTrue(baseline["solved"], baseline["error"])
        self.assertEqual(tms["evidence"], 6)
        self.assertGreaterEqual(tms["links"], 5)
        self.assertGreaterEqual(tms["contradictions_valid"], 1)
        self.assertEqual(tms["unaddressed_false_claims"], 0)
        self.assertEqual(tms["rejected_links"], 0)
        self.assertTrue(tms["proof_ok"])
        self.assertGreater(tms["pair_recall"], 0)
        self.assertEqual(baseline["links"], 0)
        self.assertEqual(baseline["evidence"], 0)
        self.assertIsNone(baseline["trail_score"])
        self.assertEqual(report["comparison"]["accuracy_delta"], 0)
        self.assertTrue(report["agent_sees_formal_clues"])

    def test_zebra_reference_answers(self):
        report = run_eval(zebra(), ReferenceAgent())
        for mode in ("tms", "baseline"):
            metrics = report["modes"][mode]
            self.assertTrue(metrics["solved"], metrics["error"])
            self.assertEqual(metrics["answers"], {"water": "Norwegian", "zebra": "Japanese"})

    def test_mock_scores_without_writing_and_a_wrong_grid_scores_zero_answers(self):
        mock = run_eval(terrace(), MockAgent(), modes=("tms",))["modes"]["tms"]
        self.assertTrue(mock["exact_match"])
        self.assertEqual(mock["claims"], 0)
        self.assertEqual(mock["evidence"], 6)
        wrong = ScriptedAgent(
            solution=[{"seat": "1", "person": "Bo", "drink": "tea"}],
            answers={"tea": "Bo"})
        scored = run_eval(terrace(), wrong, modes=("baseline",))["modes"]["baseline"]
        self.assertEqual(scored["answer_accuracy"], 0)
        self.assertFalse(scored["exact_match"])
        self.assertLess(scored["accuracy"], 1)

    def test_openai_without_credentials_does_not_call_out(self):
        keys = ("TMS_EVAL_API_KEY", "OPENAI_API_KEY", "CHAT_API_KEY", "TMS_EVAL_MODEL", "CHAT_MODEL")
        saved = {key: os.environ.get(key) for key in keys}
        try:
            for key in keys:
                os.environ.pop(key, None)
            report = run_eval(terrace(), OpenAIAgent(), modes=("baseline",))
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.assertIn("key", report["modes"]["baseline"]["error"])
        self.assertFalse(report["modes"]["baseline"]["solved"])
        with self.assertRaises(ValueError):
            build_agent("no-such-agent")


class CliTests(unittest.TestCase):
    def test_list_run_and_generate(self):
        listed = _cli("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("zebra", listed.stdout)
        self.assertIn("terrace", listed.stdout)
        ran = _cli("run", "--puzzle", "terrace", "--agent", "reference", "--json")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        report = json.loads(ran.stdout)
        self.assertTrue(report["modes"]["tms"]["solved"])
        self.assertTrue(report["modes"]["baseline"]["solved"])
        generated = _cli("generate", "--dimensions", "3", "--entities", "3", "--clues", "8",
                         "--seed", "1", "--clue-types", "direct", "--red-herrings", "0")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        puzzle = json.loads(generated.stdout)
        self.assertEqual(len(puzzle["solution"]), 3)
        self.assertTrue(puzzle["clues"])


def _hand(categories, clues, solution) -> Puzzle:
    return Puzzle(
        id="hand", title="hand", source="original", memorization_risk="low",
        categories=categories, clues=clues, solution=solution, question="Who?", asks=())


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "evals.murdle", *args], cwd=ROOT,
                          capture_output=True, text=True, check=False)


if __name__ == "__main__":
    unittest.main()
