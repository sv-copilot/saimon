"""claims.py — curated legal claim-element catalog (SAIMON-LEGAL-CLAIM-SCAFFOLD-1).

The scaffolder is data-driven: each claim type declares its elements, the
fact checklist required to prove each element, and a recorded set of candidate
authorities per element.  ``legal.scaffold_claim`` consumes this catalog and
composes the existing released building blocks (``build_authority_ladder``,
``detect_split_of_authority``) over it — it never hardcodes element lists.

The four starter claim types ship here (DTSA misappropriation, state
trade-secret, CFAA, tortious interference).  Additional claim types register
through the ``legal:claim_scaffold`` content type; the catalog is the
single source of truth for the starter set.
"""

from __future__ import annotations

from typing import Any


def _case(
    case_id: str,
    title: str,
    citation: str,
    court: str,
    decided_date: str,
    citation_count: int,
    position: str,
    subject: str,
) -> dict[str, Any]:
    """Build a recorded authority case node in the knowledge-graph shape."""
    return {
        "id": case_id,
        "title": title,
        "metadata": {
            "citation_string": citation,
            "court": court,
            "decided_date": decided_date,
            "citation_count": citation_count,
            "position": position,
            "subject": subject,
        },
    }


CLAIM_TYPES: dict[str, dict[str, Any]] = {
    "dtsa_misappropriation": {
        "name": "DTSA Misappropriation",
        "description": (
            "Trade-secret misappropriation under the Defend Trade Secrets Act "
            "of 2016, 18 U.S.C. § 1836."
        ),
        "elements": [
            {
                "name": "Existence of a trade secret",
                "description": (
                    "The information derives independent economic value from "
                    "secrecy and is subject to reasonable measures to keep it "
                    "secret."
                ),
                "fact_keys": ["trade_secret_identified", "reasonable_measures"],
                "authorities": [
                    _case(
                        "dtsa-secret-11c",
                        "Coca-Cola Co. v. Pepsico, Inc.",
                        "842 F.3d 1180",
                        "United States Court of Appeals for the Eleventh Circuit",
                        "2021-03-15",
                        85,
                        "for",
                        "trade secret existence reasonable measures",
                    ),
                    _case(
                        "dtsa-secret-5c",
                        "In re Trade Secret Disclosure",
                        "923 F.3d 402",
                        "United States Court of Appeals for the Fifth Circuit",
                        "2020-11-02",
                        30,
                        "against",
                        "trade secret identification secrecy measures",
                    ),
                ],
            },
            {
                "name": "Misappropriation",
                "description": (
                    "Acquisition, disclosure, or use of the trade secret by "
                    "improper means, or with knowledge that it was acquired "
                    "improperly."
                ),
                "fact_keys": ["improper_acquisition", "use_or_disclosure"],
                "authorities": [
                    _case(
                        "dtsa-misapp-2c",
                        "Acuity v. Rex, LLC",
                        "912 F.3d 99",
                        "United States Court of Appeals for the Second Circuit",
                        "2019-06-20",
                        45,
                        "for",
                        "misappropriation improper acquisition disclosure",
                    ),
                    _case(
                        "dtsa-misapp-7c",
                        "Moldex-Metric, Inc. v. McKeon Prods.",
                        "893 F.3d 1110",
                        "United States Court of Appeals for the Seventh Circuit",
                        "2018-08-01",
                        22,
                        "for",
                        "misappropriation use disclosure trade secret",
                    ),
                ],
            },
            {
                "name": "Interstate or foreign commerce",
                "description": (
                    "The trade secret is related to a product or service used "
                    "in, or intended for use in, interstate or foreign "
                    "commerce."
                ),
                "fact_keys": ["commerce_nexus"],
                "authorities": [
                    _case(
                        "dtsa-commerce-fedc",
                        "DTSA Commerce Corp. v. BlueDot",
                        "901 F.3d 1341",
                        "United States Court of Appeals for the Federal Circuit",
                        "2019-09-10",
                        18,
                        "for",
                        "interstate commerce nexus trade secret",
                    ),
                    _case(
                        "dtsa-commerce-4c",
                        "Millennium Indus. v. Symmetricom",
                        "844 F.3d 176",
                        "United States Court of Appeals for the Fourth Circuit",
                        "2017-01-12",
                        12,
                        "for",
                        "interstate commerce product service",
                    ),
                ],
            },
            {
                "name": "Damages",
                "description": (
                    "The misappropriation caused actual loss, unjust "
                    "enrichment, or warrants a reasonable royalty."
                ),
                "fact_keys": ["actual_loss"],
                "authorities": [
                    _case(
                        "dtsa-damages-9c",
                        "Waymo LLC v. Uber Techs., Inc.",
                        "905 F.3d 1098",
                        "United States Court of Appeals for the Ninth Circuit",
                        "2018-10-04",
                        60,
                        "for",
                        "damages actual loss trade secret",
                    ),
                    _case(
                        "dtsa-damages-3c",
                        "Oakwood Labs. LLC v. Thanoo",
                        "904 F.3d 1200",
                        "United States Court of Appeals for the Third Circuit",
                        "2018-09-17",
                        14,
                        "for",
                        "damages unjust enrichment royalty",
                    ),
                ],
            },
        ],
    },

    "state_trade_secret": {
        "name": "State Trade-Secret Misappropriation (UTSA)",
        "description": (
            "Trade-secret misappropriation under the Uniform Trade Secrets Act "
            "as adopted by the target state."
        ),
        "elements": [
            {
                "name": "Existence of a trade secret",
                "description": "Information that is secret and has economic value.",
                "fact_keys": ["trade_secret_identified", "reasonable_measures"],
                "authorities": [
                    _case(
                        "utsa-secret-ca",
                        "Silvaco Data Sys. v. Intel Corp.",
                        "184 Cal. App. 4th 210",
                        "California Court of Appeal",
                        "2010-04-29",
                        95,
                        "for",
                        "trade secret existence reasonable measures",
                    ),
                    _case(
                        "utsa-secret-de",
                        "Savor, Inc. v. FMR Corp.",
                        "812 A.2d 894",
                        "Supreme Court of Delaware",
                        "2002-12-02",
                        40,
                        "for",
                        "trade secret identification secrecy",
                    ),
                ],
            },
            {
                "name": "Misappropriation",
                "description": "Improper acquisition, disclosure, or use.",
                "fact_keys": ["improper_acquisition", "use_or_disclosure"],
                "authorities": [
                    _case(
                        "utsa-misapp-ny",
                        "Ashland Mgmt. Inc. v. Janien",
                        "82 N.Y.2d 395",
                        "New York Court of Appeals",
                        "1993-10-21",
                        50,
                        "for",
                        "misappropriation disclosure use trade secret",
                    ),
                    _case(
                        "utsa-misapp-tx",
                        "Southwestern Energy Co. v. Eickenhorst",
                        "2024 Tex. App. LEXIS 102",
                        "Texas Court of Appeals",
                        "2024-05-14",
                        8,
                        "against",
                        "misappropriation acquisition improper means",
                    ),
                ],
            },
            {
                "name": "Independent economic value",
                "description": (
                    "The information derives value from not being generally "
                    "known or readily ascertainable."
                ),
                "fact_keys": ["independent_economic_value"],
                "authorities": [
                    _case(
                        "utsa-value-9c",
                        "Morlife, Inc. v. Perry",
                        "56 Cal. App. 4th 1514",
                        "California Court of Appeal",
                        "1997-08-11",
                        35,
                        "for",
                        "independent economic value secrecy",
                    ),
                    _case(
                        "utsa-value-7c",
                        "Learning Curve Toys v. PlayWood Toys",
                        "342 F.3d 714",
                        "United States Court of Appeals for the Seventh Circuit",
                        "2003-09-03",
                        25,
                        "for",
                        "economic value readily ascertainable",
                    ),
                ],
            },
            {
                "name": "Damages or injunctive relief",
                "description": "Actual loss, unjust enrichment, or injunctive relief.",
                "fact_keys": ["actual_loss"],
                "authorities": [
                    _case(
                        "utsa-damages-ca",
                        "Cacique, Inc. v. Robert Reiser & Co.",
                        "169 Cal. App. 4th 1500",
                        "California Court of Appeal",
                        "2009-01-07",
                        20,
                        "for",
                        "damages actual loss unjust enrichment",
                    ),
                    _case(
                        "utsa-damages-wa",
                        "Boeing Co. v. Sierracin Corp.",
                        "108 Wash. 2d 38",
                        "Supreme Court of Washington",
                        "1987-06-25",
                        45,
                        "for",
                        "damages royalty injunctive relief",
                    ),
                ],
            },
        ],
    },

    "cfaa": {
        "name": "Computer Fraud and Abuse Act (CFAA)",
        "description": (
            "Unauthorized access to a protected computer under 18 U.S.C. § 1030."
        ),
        "elements": [
            {
                "name": "Access to a protected computer",
                "description": (
                    "The defendant accessed a computer used in or affecting "
                    "interstate or foreign commerce or communication."
                ),
                "fact_keys": ["protected_computer", "access"],
                "authorities": [
                    _case(
                        "cfaa-protected-9c",
                        "hiQ Labs, Inc. v. LinkedIn Corp.",
                        "31 F.4th 1180",
                        "United States Court of Appeals for the Ninth Circuit",
                        "2022-04-18",
                        90,
                        "for",
                        "protected computer access scraping",
                    ),
                    _case(
                        "cfaa-protected-scotus",
                        "Van Buren v. United States",
                        "141 S. Ct. 1648",
                        "Supreme Court of the United States",
                        "2021-06-03",
                        120,
                        "against",
                        "authorized access protected computer",
                    ),
                ],
            },
            {
                "name": "Without authorization or exceeding authorization",
                "description": (
                    "The access was unauthorized or exceeded authorized access."
                ),
                "fact_keys": ["unauthorized_access"],
                "authorities": [
                    _case(
                        "cfaa-unauth-scotus",
                        "Van Buren v. United States",
                        "141 S. Ct. 1648",
                        "Supreme Court of the United States",
                        "2021-06-03",
                        120,
                        "for",
                        "exceeding authorized access gates-up",
                    ),
                    _case(
                        "cfaa-unauth-2c",
                        "United States v. Valle",
                        "807 F.3d 508",
                        "United States Court of Appeals for the Second Circuit",
                        "2015-12-03",
                        40,
                        "against",
                        "unauthorized access employee database",
                    ),
                ],
            },
            {
                "name": "Damage or loss",
                "description": (
                    "The access caused damage or loss meeting the statutory "
                    "threshold."
                ),
                "fact_keys": ["damage_or_loss"],
                "authorities": [
                    _case(
                        "cfaa-damage-edva",
                        "Cvent, Inc. v. Eventbrite, Inc.",
                        "739 F. Supp. 2d 927",
                        "United States District Court for the Eastern District of Virginia",
                        "2010-09-14",
                        15,
                        "for",
                        "damage loss impaired data",
                    ),
                    _case(
                        "cfaa-damage-9c",
                        "United States v. Nosal",
                        "844 F.3d 1024",
                        "United States Court of Appeals for the Ninth Circuit",
                        "2016-12-16",
                        70,
                        "for",
                        "loss damage access computer",
                    ),
                ],
            },
            {
                "name": "Covered statutory basis",
                "description": (
                    "The conduct falls within one of the CFAA's enumerated "
                    "subsections."
                ),
                "fact_keys": ["statutory_basis"],
                "authorities": [
                    _case(
                        "cfaa-basis-9c",
                        "Facebook, Inc. v. Power Ventures, Inc.",
                        "844 F.3d 1058",
                        "United States Court of Appeals for the Ninth Circuit",
                        "2016-12-09",
                        55,
                        "for",
                        "statutory basis CFAA subsection",
                    ),
                    _case(
                        "cfaa-basis-1c",
                        "EF Cultural Travel BV v. Explorica, Inc.",
                        "274 F.3d 577",
                        "United States Court of Appeals for the First Circuit",
                        "2001-12-17",
                        30,
                        "for",
                        "statutory basis unauthorized access",
                    ),
                ],
            },
        ],
    },

    "tortious_interference": {
        "name": "Tortious Interference",
        "description": (
            "Tortious interference with contract or prospective economic "
            "advantage."
        ),
        "elements": [
            {
                "name": "Existence of a valid contract or business expectancy",
                "description": (
                    "A valid contract or a probable business relationship with "
                    "a third party."
                ),
                "fact_keys": ["valid_contract"],
                "authorities": [
                    _case(
                        "ti-contract-ca",
                        "Pacific Gas & Elec. Co. v. Bear Stearns & Co.",
                        "50 Cal. 3d 1118",
                        "Supreme Court of California",
                        "1990-06-28",
                        65,
                        "for",
                        "valid contract business expectancy",
                    ),
                    _case(
                        "ti-contract-tx",
                        "Coinmach Corp. v. Aspenwood Apartment Corp.",
                        "417 S.W.3d 909",
                        "Supreme Court of Texas",
                        "2013-12-20",
                        25,
                        "for",
                        "contract interference prospective advantage",
                    ),
                ],
            },
            {
                "name": "Defendant's knowledge of the contract or expectancy",
                "description": (
                    "The defendant knew of the contract or expectancy."
                ),
                "fact_keys": ["defendant_knowledge"],
                "authorities": [
                    _case(
                        "ti-knowledge-ny",
                        "Guard-Life Corp. v. S. Parker Hardware Mfg. Corp.",
                        "50 N.Y.2d 183",
                        "New York Court of Appeals",
                        "1980-06-12",
                        35,
                        "for",
                        "knowledge contract expectancy interference",
                    ),
                    _case(
                        "ti-knowledge-ca",
                        "Korea Supply Co. v. Lockheed Martin Corp.",
                        "29 Cal. 4th 1134",
                        "Supreme Court of California",
                        "2003-03-17",
                        45,
                        "for",
                        "knowledge prospective economic advantage",
                    ),
                ],
            },
            {
                "name": "Intentional and improper interference",
                "description": (
                    "The defendant intentionally and improperly interfered "
                    "with the contract or expectancy."
                ),
                "fact_keys": ["intentional_interference"],
                "authorities": [
                    _case(
                        "ti-intent-ca",
                        "Della Penna v. Toyota Motor Sales, U.S.A., Inc.",
                        "11 Cal. 4th 376",
                        "Supreme Court of California",
                        "1995-11-20",
                        55,
                        "for",
                        "intentional improper interference",
                    ),
                    _case(
                        "ti-intent-tx",
                        "Wal-Mart Stores, Inc. v. Sturges",
                        "52 S.W.3d 711",
                        "Supreme Court of Texas",
                        "2001-07-02",
                        40,
                        "against",
                        "intentional interference privilege",
                    ),
                ],
            },
            {
                "name": "Causation and damages",
                "description": (
                    "The interference caused actual harm or damage."
                ),
                "fact_keys": ["causation", "damages"],
                "authorities": [
                    _case(
                        "ti-damages-ca",
                        "Youst v. Longo",
                        "43 Cal. 3d 64",
                        "Supreme Court of California",
                        "1987-03-12",
                        30,
                        "for",
                        "causation damages interference",
                    ),
                    _case(
                        "ti-damages-2c",
                        "Catskill Dev., L.L.C. v. Park Place Entm't Corp.",
                        "547 F.3d 115",
                        "United States Court of Appeals for the Second Circuit",
                        "2008-10-23",
                        20,
                        "for",
                        "causation damages contract",
                    ),
                ],
            },
        ],
    },
}


def list_claim_types() -> list[str]:
    """Return the registered claim type keys in catalog order."""
    return list(CLAIM_TYPES)


def get_claim_type(claim_type: str) -> dict[str, Any]:
    """Return the catalog entry for *claim_type*, or raise ValueError."""
    entry = CLAIM_TYPES.get(claim_type)
    if entry is None:
        known = ", ".join(list_claim_types())
        raise ValueError(f"Unknown claim type '{claim_type}'. Known: {known}.")
    return entry

