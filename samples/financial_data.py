"""Canonical (ground-truth) financial figures for the two sample applicants.

These dicts are the single source of truth used to RENDER the mock financial
statement PDFs (``generate_mock_financials.py``). The pipeline itself does NOT
import this module — it parses the generated PDFs — but tests may import it to
assert that parsing round-trips correctly.

All figures are in whole USD. Columns are ordered most-recent-year first.

Designed contrast:
  * 1001 Apex Precision (Manufacturing) — healthy, growing, clean approve.
  * 1002 Brightway Retail (Retail)      — weak liquidity, high leverage,
    sub-2.0x interest coverage (policy hard fail) and a most-recent-year net
    loss; should drive a High risk / Refer recommendation.
"""

FINANCIALS = {
    "1001": {
        "company_name": "Apex Precision Components, Inc.",
        "sector_code": "MFG",
        "years": [2025, 2024, 2023],
        "balance_sheet": {
            "Cash and cash equivalents": [1_800_000, 1_500_000, 1_300_000],
            "Accounts receivable": [3_200_000, 2_900_000, 2_600_000],
            "Inventory": [2_600_000, 2_400_000, 2_200_000],
            "Other current assets": [400_000, 350_000, 300_000],
            "Total current assets": [8_000_000, 7_150_000, 6_400_000],
            "Property, plant and equipment, net": [9_500_000, 8_800_000, 8_200_000],
            "Other non-current assets": [500_000, 450_000, 400_000],
            "Total assets": [18_000_000, 16_400_000, 15_000_000],
            "Accounts payable": [1_900_000, 1_750_000, 1_600_000],
            "Short-term debt": [1_300_000, 1_200_000, 1_150_000],
            "Other current liabilities": [1_000_000, 900_000, 850_000],
            "Total current liabilities": [4_200_000, 3_850_000, 3_600_000],
            "Long-term debt": [4_300_000, 4_100_000, 3_900_000],
            "Total liabilities": [8_500_000, 7_950_000, 7_500_000],
            "Total shareholders equity": [9_500_000, 8_450_000, 7_500_000],
            "Total liabilities and equity": [18_000_000, 16_400_000, 15_000_000],
        },
        "income_statement": {
            "Revenue": [24_000_000, 21_500_000, 19_000_000],
            "Cost of goods sold": [16_000_000, 14_500_000, 13_000_000],
            "Gross profit": [8_000_000, 7_000_000, 6_000_000],
            "Operating expenses": [4_800_000, 4_400_000, 4_000_000],
            "Operating income (EBIT)": [3_200_000, 2_600_000, 2_000_000],
            "Interest expense": [480_000, 460_000, 440_000],
            "Pre-tax income": [2_720_000, 2_140_000, 1_560_000],
            "Income tax expense": [680_000, 535_000, 390_000],
            "Net income": [2_040_000, 1_605_000, 1_170_000],
        },
        "cash_flow": {
            "Cash flow from operations": [2_800_000, 2_300_000, 1_900_000],
            "Cash flow from investing": [-1_500_000, -1_300_000, -1_100_000],
            "Cash flow from financing": [-600_000, -500_000, -400_000],
            "Net change in cash": [700_000, 500_000, 400_000],
        },
    },
    "1002": {
        "company_name": "Brightway Retail Group, LLC",
        "sector_code": "RET",
        "years": [2025, 2024, 2023],
        "balance_sheet": {
            "Cash and cash equivalents": [350_000, 480_000, 520_000],
            "Accounts receivable": [600_000, 560_000, 500_000],
            "Inventory": [2_400_000, 2_000_000, 1_700_000],
            "Other current assets": [250_000, 220_000, 200_000],
            "Total current assets": [3_600_000, 3_260_000, 2_920_000],
            "Property, plant and equipment, net": [2_200_000, 1_900_000, 1_600_000],
            "Other non-current assets": [700_000, 700_000, 700_000],
            "Total assets": [6_500_000, 5_860_000, 5_220_000],
            "Accounts payable": [1_800_000, 1_500_000, 1_250_000],
            "Short-term debt": [1_100_000, 850_000, 650_000],
            "Other current liabilities": [550_000, 480_000, 420_000],
            "Total current liabilities": [3_450_000, 2_830_000, 2_320_000],
            "Long-term debt": [1_700_000, 1_500_000, 1_300_000],
            "Total liabilities": [5_150_000, 4_330_000, 3_620_000],
            "Total shareholders equity": [1_350_000, 1_530_000, 1_600_000],
            "Total liabilities and equity": [6_500_000, 5_860_000, 5_220_000],
        },
        "income_statement": {
            "Revenue": [14_000_000, 12_500_000, 11_000_000],
            "Cost of goods sold": [9_100_000, 7_875_000, 6_820_000],
            "Gross profit": [4_900_000, 4_625_000, 4_180_000],
            "Operating expenses": [4_750_000, 4_150_000, 3_650_000],
            "Operating income (EBIT)": [150_000, 475_000, 530_000],
            "Interest expense": [165_000, 140_000, 120_000],
            "Pre-tax income": [-15_000, 335_000, 410_000],
            "Income tax expense": [0, 84_000, 103_000],
            "Net income": [-15_000, 251_000, 307_000],
        },
        "cash_flow": {
            "Cash flow from operations": [180_000, 420_000, 510_000],
            "Cash flow from investing": [-900_000, -700_000, -600_000],
            "Cash flow from financing": [750_000, 200_000, 100_000],
            "Net change in cash": [30_000, -80_000, 10_000],
        },
    },
}
