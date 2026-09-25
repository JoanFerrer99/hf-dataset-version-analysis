"""
Tests unitaris per a `notebooks/validate_census_income.py`.

Cobreixen NOMÉS les funcions PURES de comparació contra el ground truth
del paper (`compare_detectability_with_paper`/`summarize_agreement_by_
code`/`compute_agreement_metrics`) -- mai `run_validation` (fa crides de
xarxa reals) ni `download_*` (embolcalls prims d'`hf_hub_download`, ja
coberts indirectament per la resta del projecte).
"""

import pandas as pd

import change_diff as cd
import validate_census_income as vci


def _detectability_row(version: str, true_codes: set[str]) -> dict:
    """Una fila de `detectability_df` amb NOMÉS `true_codes` a True."""
    row = {"version": version, "codes_detected": len(true_codes), "paper_row_total": 0}
    row.update({code: (code in true_codes) for code in cd.TABULAR_CODES})
    return row


class TestCompareDetectabilityWithPaper:
    def test_exact_match_produces_no_fn_or_fp(self):
        # D1 al ground truth real: {C100, C223, C410} -- excloent C100, el
        # nostre motor detectant EXACTAMENT {C223, C410} és una coincidencia perfecta.
        df = pd.DataFrame([_detectability_row("D1", {"C223", "C410"})])
        result = vci.compare_detectability_with_paper(df)

        assert result.iloc[0]["tp"] == 2
        assert result.iloc[0]["fn"] == 0
        assert result.iloc[0]["fp"] == 0
        assert result.iloc[0]["tp_codes"] == "C223,C410"
        assert result.iloc[0]["fn_codes"] == "-"
        assert result.iloc[0]["fp_codes"] == "-"

    def test_c100_is_excluded_from_paper_side(self):
        # El nostre motor mai detecta C100 -- si nomes es detectessin
        # C223/C410, pero NO es passes cap C100 (que no es una columna del
        # detectability_df de totes maneres), no hi ha d'haver cap FN per C100.
        df = pd.DataFrame([_detectability_row("D1", {"C223", "C410"})])
        result = vci.compare_detectability_with_paper(df)
        assert "C100" not in result.iloc[0]["fn_codes"]

    def test_missed_and_extra_codes_are_fn_and_fp(self):
        # D5 real: {C100, C221, C223, C410}. Simulem que el motor NOMES
        # detecta C221 i, a mes, un fals positiu C530.
        df = pd.DataFrame([_detectability_row("D5", {"C221", "C530"})])
        result = vci.compare_detectability_with_paper(df)

        row = result.iloc[0]
        assert row["tp"] == 1 and row["tp_codes"] == "C221"
        assert row["fn"] == 2 and row["fn_codes"] == "C223,C410"
        assert row["fp"] == 1 and row["fp_codes"] == "C530"

    def test_paper_totals_include_c100_but_paper_minus_c100_does_not(self):
        df = pd.DataFrame([_detectability_row("D3", set())])
        result = vci.compare_detectability_with_paper(df)
        row = result.iloc[0]
        assert row["paper_total"] == len(vci.PAPER_GROUND_TRUTH["D3"])
        assert row["paper_minus_c100"] == len(vci.PAPER_GROUND_TRUTH["D3"]) - 1


class TestSummarizeAgreementByCode:
    def test_aggregates_across_multiple_versions(self):
        df = pd.DataFrame([
            _detectability_row("D1", {"C223", "C410"}),   # tots dos TP
            _detectability_row("D5", {"C221", "C530"}),   # C221 TP, C223/C410 FN, C530 FP
        ])
        result = vci.summarize_agreement_by_code(df).set_index("code")

        assert result.loc["C223", "tp"] == 1  # D1
        assert result.loc["C223", "fn"] == 1  # D5
        assert result.loc["C410", "tp"] == 1  # D1
        assert result.loc["C410", "fn"] == 1  # D5
        assert result.loc["C221", "tp"] == 1  # D5
        assert result.loc["C530", "fp"] == 1  # D5

    def test_codes_never_appearing_are_dropped(self):
        df = pd.DataFrame([_detectability_row("D1", {"C223", "C410"})])
        result = vci.summarize_agreement_by_code(df)
        assert "C321" not in set(result["code"])  # mai al ground truth ni detectat


class TestComputeAgreementMetrics:
    def test_perfect_agreement(self):
        comparison_df = pd.DataFrame([{"tp": 5, "fn": 0, "fp": 0}])
        metrics = vci.compute_agreement_metrics(comparison_df)
        assert metrics == {"tp": 5, "fn": 0, "fp": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}

    def test_no_true_positives_gives_zero_metrics_not_division_error(self):
        comparison_df = pd.DataFrame([{"tp": 0, "fn": 3, "fp": 2}])
        metrics = vci.compute_agreement_metrics(comparison_df)
        assert metrics["precision"] == 0.0
        assert metrics["recall"] == 0.0
        assert metrics["f1"] == 0.0

    def test_mixed_agreement_matches_known_real_result(self):
        # Regressio: reprodueix exactament el resultat real verificat
        # manualment sobre data/census_income_diff_report_3.csv (Decisio T-18).
        comparison_df = pd.DataFrame([
            {"tp": 2, "fn": 0, "fp": 0}, {"tp": 2, "fn": 0, "fp": 0},
            {"tp": 4, "fn": 2, "fp": 3}, {"tp": 5, "fn": 1, "fp": 2},
            {"tp": 3, "fn": 0, "fp": 0}, {"tp": 2, "fn": 1, "fp": 4},
            {"tp": 2, "fn": 2, "fp": 4},
        ])
        metrics = vci.compute_agreement_metrics(comparison_df)
        assert metrics["tp"] == 20 and metrics["fn"] == 6 and metrics["fp"] == 13
        assert round(metrics["precision"], 3) == 0.606
        assert round(metrics["recall"], 3) == 0.769
        assert round(metrics["f1"], 3) == 0.678


class TestPaperGroundTruthConsistency:
    def test_row_counts_match_documented_paper_row_totals(self):
        # PAPER_ROW_TOTALS s'ha consolidat dins de PAPER_GROUND_TRUTH
        # (Decisio T-18 seguent) -- aquest test confirma que els totals
        # coneguts (T-08, docs/decisions_tfg.txt) no s'han desviat.
        expected = {"D1": 3, "D2": 3, "D3": 7, "D4": 7, "D5": 4, "D6": 4, "D7": 5}
        for version, total in expected.items():
            assert len(vci.PAPER_GROUND_TRUTH[version]) == total

    def test_every_entry_includes_c100(self):
        # El paper marca C100 (metadada) a TOTES les versions -- si mai no
        # hi fos, seria un indici d'error de transcripcio, no una troballa real.
        for version, codes in vci.PAPER_GROUND_TRUTH.items():
            assert "C100" in codes, f"{version} sense C100 -- revisar transcripció"
