"""Gate G2: live registry checks + negative controls (misspelling, impossible strength, bad checksums, error-prone sig)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import registries as r  # noqa: E402


def main():
    m = r.rxnav_drug_match("Amoxicillin")
    assert m["ok"] is True and m["score"] >= 0.95, m
    bad = r.rxnav_drug_match("Amoxicilin")                   # misspelling → still a candidate but flagged suggestions
    assert bad["ok"] is not None and "amoxicillin" in [s.lower() for s in bad.get("suggestions", [])] + [((bad.get("match") or {}).get("name") or "").lower().split(" ")[0]], bad
    junk = r.rxnav_drug_match("Zzxqwv")
    assert junk["ok"] in (False, None) and (junk.get("score") or 0) < 0.85, junk
    assert r.rxnav_strength_exists("Amoxicillin", "500 mg")["ok"] is True
    assert r.rxnav_strength_exists("Levothyroxine", "75 mcg")["ok"] is True
    assert r.rxnav_strength_exists("Amoxicillin", "700 mg")["ok"] is False    # negative control
    n = r.nppes_lookup("John Smith", None, "NY")
    assert n["ok"] in (True, None), n
    assert r.nppes_lookup("", "1234567893")["ok"] in (False, None)            # valid Luhn, nonexistent → not found
    assert r.npi_valid("1234567893") and not r.npi_valid("1234567890")        # 1234567893 is the canonical NPI test number
    assert r.dea_valid("AB1234563")["ok"] and not r.dea_valid("AB1234567")["ok"]
    s = r.parse_sig("1 tab PO q.d. x 10 days")
    assert s["frequency"] == "once daily" and s["error_prone_abbrev"] and s["duration"] == "10 days", s
    s2 = r.parse_sig("1 cap PO TID x 7 days")
    assert s2["frequency"] == "3 times daily" and not s2["error_prone_abbrev"], s2
    assert r.lasa_partner("Hydroxyzine") == "hydralazine" and r.lasa_partner("Amoxicillin") is None
    assert r.dose_in_range("Metformin", "5000 mg")["ok"] is False and r.dose_in_range("Metformin", "500 mg")["ok"] is True
    assert r.norm_strength("0.5 g") == "500 mg" and r.norm_strength("50MCG") == "50 mcg"
    print("rxnav drug/strength, nppes, luhn, dea, sig, lasa, dose-range all behave incl. negative controls")
    print("REGISTRIES OK")


if __name__ == "__main__":
    main()
