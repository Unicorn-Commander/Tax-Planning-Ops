"""Bracketed-state 2025 configs, registered into the state registry. Bracket
tables fetched from the official 2025 sources (FTB Schedule X/Y, NY IT-201-I,
NJ-1040 schedules, Virginia Tax, and each state's DOR 2025 rate schedule) and
verified to reproduce the adversarially-checked golden vectors.

Original four (CA, NY, NJ, VA) are followed by the TY2025 graduated-state fill
(AL AR CT DE DC HI KS MD ME MN MO MS MT NE NM ND OH OK OR RI VT WI WV) so all 50
states + DC resolve. Most graduated states start from federal AGI; MT and ND
start from federal TAXABLE income (std deduction therefore 0, netting the federal
standard deduction at their starting point).

NY note: NY imposes a mandatory tax-benefit recapture above ~$107,650 NYAGI that
this base-bracket model does NOT apply, so NY tax is UNDERSTATED for high earners
(flagged at runtime). Ohio is modeled with a 0% first bracket up to $26,050
(TY2025 rates per HB 96); Mississippi with a 0% first bracket up to $10,000.
"""

from __future__ import annotations

from decimal import Decimal

from app.engines.form1040 import RateBracket
from app.engines.state_tax import StateSurtax, StateTaxConfig
from app.state_configs import register_bracketed


def _brk(rows: list[tuple[int, int | None, str]]) -> list[RateBracket]:
    return [
        RateBracket(
            lower_bound_cents=lo * 100,
            upper_bound_cents=(None if up is None else up * 100),
            rate=Decimal(rate),
        )
        for lo, up, rate in rows
    ]


CA = StateTaxConfig(
    state="CA",
    brackets_by_status={
        "single": _brk([
            (0, 11079, "0.01"), (11079, 26264, "0.02"), (26264, 41452, "0.04"),
            (41452, 57542, "0.06"), (57542, 72724, "0.08"), (72724, 371479, "0.093"),
            (371479, 445771, "0.103"), (445771, 742953, "0.113"), (742953, None, "0.123"),
        ]),
        "mfj": _brk([
            (0, 22158, "0.01"), (22158, 52528, "0.02"), (52528, 82904, "0.04"),
            (82904, 115084, "0.06"), (115084, 145448, "0.08"), (145448, 742958, "0.093"),
            (742958, 891542, "0.103"), (891542, 1485906, "0.113"), (1485906, None, "0.123"),
        ]),
    },
    standard_deduction_by_status={"single": 570_600, "mfj": 1_141_200},
    taxes_social_security=False, taxes_retirement_income=True,
    surtaxes=[StateSurtax(name="Mental Health Services", threshold_cents=100_000_000,
                          rate=Decimal("0.01"), applies_to="state_taxable_income")],
)

NY = StateTaxConfig(
    state="NY",
    brackets_by_status={
        "single": _brk([
            (0, 8500, "0.04"), (8500, 11700, "0.045"), (11700, 13900, "0.0525"),
            (13900, 80650, "0.055"), (80650, 215400, "0.06"), (215400, 1077550, "0.0685"),
            (1077550, 5000000, "0.0965"), (5000000, 25000000, "0.103"), (25000000, None, "0.109"),
        ]),
        "mfj": _brk([
            (0, 17150, "0.04"), (17150, 23600, "0.045"), (23600, 27900, "0.0525"),
            (27900, 161550, "0.055"), (161550, 323200, "0.06"), (323200, 2155350, "0.0685"),
            (2155350, 5000000, "0.0965"), (5000000, 25000000, "0.103"), (25000000, None, "0.109"),
        ]),
    },
    standard_deduction_by_status={"single": 800_000, "mfj": 1_605_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

NJ = StateTaxConfig(
    state="NJ",
    brackets_by_status={
        "single": _brk([
            (0, 20000, "0.014"), (20000, 35000, "0.0175"), (35000, 40000, "0.035"),
            (40000, 75000, "0.05525"), (75000, 500000, "0.0637"), (500000, 1000000, "0.0897"),
            (1000000, None, "0.1075"),
        ]),
        "mfj": _brk([
            (0, 20000, "0.014"), (20000, 50000, "0.0175"), (50000, 70000, "0.0245"),
            (70000, 80000, "0.035"), (80000, 150000, "0.05525"), (150000, 500000, "0.0637"),
            (500000, 1000000, "0.0897"), (1000000, None, "0.1075"),
        ]),
    },
    standard_deduction_by_status={"single": 0, "mfj": 0},
    taxes_social_security=False, taxes_retirement_income=True,
)

_VA_BRACKETS = _brk([(0, 3000, "0.02"), (3000, 5000, "0.03"), (5000, 17000, "0.05"),
                     (17000, None, "0.0575")])
VA = StateTaxConfig(
    state="VA",
    brackets_by_status={"single": _VA_BRACKETS, "mfj": _VA_BRACKETS},
    standard_deduction_by_status={"single": 875_000, "mfj": 1_750_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_AL_SINGLE = _brk([(0,500,"0.02"),(500,3000,"0.04"),(3000,None,"0.05")])
_AL_MFJ = _brk([(0,1000,"0.02"),(1000,6000,"0.04"),(6000,None,"0.05")])
AL = StateTaxConfig(
    state="AL",
    brackets_by_status={"single": _AL_SINGLE, "mfj": _AL_MFJ},
    standard_deduction_by_status={"single":300_000,"mfj":850_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_AR_BRACKETS = _brk([
    (0,5600,"0"),(5600,11200,"0.02"),(11200,16000,"0.03"),(16000,26400,"0.034"),
    (26400,None,"0.039"),
])
AR = StateTaxConfig(
    state="AR",
    brackets_by_status={"single": _AR_BRACKETS, "mfj": _AR_BRACKETS},
    standard_deduction_by_status={"single":247_000,"mfj":494_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_CT_SINGLE = _brk([
    (0,10000,"0.02"),(10000,50000,"0.045"),(50000,100000,"0.055"),(100000,200000,"0.06"),
    (200000,250000,"0.065"),(250000,500000,"0.069"),(500000,None,"0.0699"),
])
_CT_MFJ = _brk([
    (0,20000,"0.02"),(20000,100000,"0.045"),(100000,200000,"0.055"),(200000,400000,"0.06"),
    (400000,500000,"0.065"),(500000,1000000,"0.069"),(1000000,None,"0.0699"),
])
CT = StateTaxConfig(
    state="CT",
    brackets_by_status={"single": _CT_SINGLE, "mfj": _CT_MFJ},
    standard_deduction_by_status={"single":1_500_000,"mfj":2_400_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_DE_BRACKETS = _brk([
    (0,2000,"0"),(2000,5000,"0.022"),(5000,10000,"0.039"),(10000,20000,"0.048"),
    (20000,25000,"0.052"),(25000,60000,"0.0555"),(60000,None,"0.066"),
])
DE = StateTaxConfig(
    state="DE",
    brackets_by_status={"single": _DE_BRACKETS, "mfj": _DE_BRACKETS},
    standard_deduction_by_status={"single":570_000,"mfj":1_140_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_DC_BRACKETS = _brk([
    (0,10000,"0.04"),(10000,40000,"0.06"),(40000,60000,"0.065"),(60000,250000,"0.085"),
    (250000,500000,"0.0925"),(500000,1000000,"0.0975"),(1000000,None,"0.1075"),
])
DC = StateTaxConfig(
    state="DC",
    brackets_by_status={"single": _DC_BRACKETS, "mfj": _DC_BRACKETS},
    standard_deduction_by_status={"single":1_500_000,"mfj":3_000_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_HI_SINGLE = _brk([
    (0,9600,"0.014"),(9600,14400,"0.032"),(14400,19200,"0.055"),(19200,24000,"0.064"),
    (24000,36000,"0.068"),(36000,48000,"0.072"),(48000,125000,"0.076"),(125000,175000,"0.079"),
    (175000,225000,"0.0825"),(225000,275000,"0.09"),(275000,325000,"0.10"),(325000,None,"0.11"),
])
_HI_MFJ = _brk([
    (0,19200,"0.014"),(19200,28800,"0.032"),(28800,38400,"0.055"),(38400,48000,"0.064"),
    (48000,72000,"0.068"),(72000,96000,"0.072"),(96000,250000,"0.076"),(250000,350000,"0.079"),
    (350000,450000,"0.0825"),(450000,550000,"0.09"),(550000,650000,"0.10"),(650000,None,"0.11"),
])
HI = StateTaxConfig(
    state="HI",
    brackets_by_status={"single": _HI_SINGLE, "mfj": _HI_MFJ},
    standard_deduction_by_status={"single":440_000,"mfj":880_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_KS_SINGLE = _brk([(0,23000,"0.052"),(23000,None,"0.0558")])
_KS_MFJ = _brk([(0,46000,"0.052"),(46000,None,"0.0558")])
KS = StateTaxConfig(
    state="KS",
    brackets_by_status={"single": _KS_SINGLE, "mfj": _KS_MFJ},
    # KS standard deduction TY2025: $3,605 single / $8,240 MFJ (HoH $6,180).
    standard_deduction_by_status={"single":360_500,"mfj":824_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_MD_SINGLE = _brk([
    (0,1000,"0.02"),(1000,2000,"0.03"),(2000,3000,"0.04"),(3000,100000,"0.0475"),
    (100000,125000,"0.05"),(125000,150000,"0.0525"),(150000,250000,"0.055"),
    (250000,500000,"0.0575"),(500000,1000000,"0.0625"),(1000000,None,"0.065"),
])
_MD_MFJ = _brk([
    (0,1000,"0.02"),(1000,2000,"0.03"),(2000,3000,"0.04"),(3000,150000,"0.0475"),
    (150000,175000,"0.05"),(175000,225000,"0.0525"),(225000,300000,"0.055"),
    (300000,600000,"0.0575"),(600000,1200000,"0.0625"),(1200000,None,"0.065"),
])
MD = StateTaxConfig(
    state="MD",
    brackets_by_status={"single": _MD_SINGLE, "mfj": _MD_MFJ},
    standard_deduction_by_status={"single":335_000,"mfj":670_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_ME_SINGLE = _brk([(0,26800,"0.058"),(26800,63450,"0.0675"),(63450,None,"0.0715")])
_ME_MFJ = _brk([(0,53600,"0.058"),(53600,126900,"0.0675"),(126900,None,"0.0715")])
ME = StateTaxConfig(
    state="ME",
    brackets_by_status={"single": _ME_SINGLE, "mfj": _ME_MFJ},
    standard_deduction_by_status={"single":1_500_000,"mfj":3_000_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_MN_SINGLE = _brk([
    (0,32570,"0.0535"),(32570,106990,"0.068"),(106990,198630,"0.0785"),(198630,None,"0.0985"),
])
_MN_MFJ = _brk([
    (0,47620,"0.0535"),(47620,189180,"0.068"),(189180,330410,"0.0785"),(330410,None,"0.0985"),
])
MN = StateTaxConfig(
    state="MN",
    brackets_by_status={"single": _MN_SINGLE, "mfj": _MN_MFJ},
    standard_deduction_by_status={"single":1_495_000,"mfj":2_990_000},
    taxes_social_security=True, taxes_retirement_income=True,
)

_MO_BRACKETS = _brk([
    (0,1313,"0"),(1313,2626,"0.02"),(2626,3939,"0.025"),(3939,5252,"0.03"),(5252,6565,"0.035"),
    (6565,7878,"0.04"),(7878,9191,"0.045"),(9191,None,"0.047"),
])
MO = StateTaxConfig(
    state="MO",
    brackets_by_status={"single": _MO_BRACKETS, "mfj": _MO_BRACKETS},
    standard_deduction_by_status={"single":1_575_000,"mfj":3_150_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_MT_SINGLE = _brk([(0,21100,"0.047"),(21100,None,"0.059")])
_MT_MFJ = _brk([(0,42200,"0.047"),(42200,None,"0.059")])
MT = StateTaxConfig(
    state="MT",
    brackets_by_status={"single": _MT_SINGLE, "mfj": _MT_MFJ},
    standard_deduction_by_status={"single":0,"mfj":0},
    taxes_social_security=True, taxes_retirement_income=True, starts_from="federal_taxable_income",
)

_NE_SINGLE = _brk([
    (0,4030,"0.0246"),(4030,24120,"0.0351"),(24120,38870,"0.0501"),(38870,None,"0.052"),
])
_NE_MFJ = _brk([
    (0,8040,"0.0246"),(8040,48250,"0.0351"),(48250,77730,"0.0501"),(77730,None,"0.052"),
])
NE = StateTaxConfig(
    state="NE",
    brackets_by_status={"single": _NE_SINGLE, "mfj": _NE_MFJ},
    standard_deduction_by_status={"single":860_000,"mfj":1_720_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_NM_SINGLE = _brk([
    (0,5500,"0.015"),(5500,16500,"0.032"),(16500,33500,"0.043"),(33500,66500,"0.047"),
    (66500,210000,"0.049"),(210000,None,"0.059"),
])
_NM_MFJ = _brk([
    (0,8000,"0.015"),(8000,25000,"0.032"),(25000,50000,"0.043"),(50000,100000,"0.047"),
    (100000,315000,"0.049"),(315000,None,"0.059"),
])
NM = StateTaxConfig(
    state="NM",
    brackets_by_status={"single": _NM_SINGLE, "mfj": _NM_MFJ},
    standard_deduction_by_status={"single":1_575_000,"mfj":3_150_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_ND_SINGLE = _brk([(0,48475,"0"),(48475,244825,"0.0195"),(244825,None,"0.025")])
_ND_MFJ = _brk([(0,80975,"0"),(80975,298075,"0.0195"),(298075,None,"0.025")])
ND = StateTaxConfig(
    state="ND",
    brackets_by_status={"single": _ND_SINGLE, "mfj": _ND_MFJ},
    standard_deduction_by_status={"single":0,"mfj":0},
    taxes_social_security=False, taxes_retirement_income=True, starts_from="federal_taxable_income",
)

_OK_SINGLE = _brk([
    (0,1000,"0.0025"),(1000,2500,"0.0075"),(2500,3750,"0.0175"),(3750,4900,"0.0275"),
    (4900,7200,"0.0375"),(7200,None,"0.0475"),
])
_OK_MFJ = _brk([
    (0,2000,"0.0025"),(2000,5000,"0.0075"),(5000,7500,"0.0175"),(7500,9800,"0.0275"),
    (9800,14400,"0.0375"),(14400,None,"0.0475"),
])
OK = StateTaxConfig(
    state="OK",
    brackets_by_status={"single": _OK_SINGLE, "mfj": _OK_MFJ},
    standard_deduction_by_status={"single":635_000,"mfj":1_270_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_OR_SINGLE = _brk([
    (0,4400,"0.0475"),(4400,11050,"0.0675"),(11050,125000,"0.0875"),(125000,None,"0.099"),
])
_OR_MFJ = _brk([
    (0,8800,"0.0475"),(8800,22100,"0.0675"),(22100,250000,"0.0875"),(250000,None,"0.099"),
])
OR = StateTaxConfig(
    state="OR",
    brackets_by_status={"single": _OR_SINGLE, "mfj": _OR_MFJ},
    # OR taxable income = federal AGI − OR std deduction ($2,835/$5,670 TY2025).
    # (NOT federal taxable income — that would double-count the std deduction.)
    standard_deduction_by_status={"single":283_500,"mfj":567_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_RI_BRACKETS = _brk([(0,79900,"0.0375"),(79900,181650,"0.0475"),(181650,None,"0.0599")])
RI = StateTaxConfig(
    state="RI",
    brackets_by_status={"single": _RI_BRACKETS, "mfj": _RI_BRACKETS},
    standard_deduction_by_status={"single":1_090_000,"mfj":2_180_000},
    taxes_social_security=True, taxes_retirement_income=True,
)

_VT_SINGLE = _brk([
    (0,49400,"0.0335"),(49400,119700,"0.066"),(119700,249700,"0.076"),(249700,None,"0.0875"),
])
_VT_MFJ = _brk([
    (0,82500,"0.0335"),(82500,199450,"0.066"),(199450,304000,"0.076"),(304000,None,"0.0875"),
])
VT = StateTaxConfig(
    state="VT",
    brackets_by_status={"single": _VT_SINGLE, "mfj": _VT_MFJ},
    standard_deduction_by_status={"single":765_000,"mfj":1_530_000},
    taxes_social_security=True, taxes_retirement_income=True,
)

_WI_SINGLE = _brk([
    (0,14680,"0.035"),(14680,50480,"0.044"),(50480,323290,"0.053"),(323290,None,"0.0765"),
])
_WI_MFJ = _brk([
    (0,19580,"0.035"),(19580,67300,"0.044"),(67300,431060,"0.053"),(431060,None,"0.0765"),
])
WI = StateTaxConfig(
    state="WI",
    brackets_by_status={"single": _WI_SINGLE, "mfj": _WI_MFJ},
    standard_deduction_by_status={"single":1_356_000,"mfj":2_511_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

_WV_BRACKETS = _brk([
    (0,10000,"0.0222"),(10000,25000,"0.0296"),(25000,40000,"0.0333"),(40000,60000,"0.0444"),
    (60000,None,"0.0482"),
])
WV = StateTaxConfig(
    state="WV",
    brackets_by_status={"single": _WV_BRACKETS, "mfj": _WV_BRACKETS},
    standard_deduction_by_status={"single":200_000,"mfj":400_000},
    taxes_social_security=False, taxes_retirement_income=True,
)

# Ohio: 0% on the first $26,050 of Ohio taxable income, 2.75% to $100,000, 3.125%
# above (TY2025 per HB 96; a flat 2.75% begins TY2026). Same schedule for every
# filing status. Ohio's official "$2,033.13 + 3.125% of the excess over $100,000"
# top tier IS the cumulative bracket walk, so the marginal table reproduces it.
# SS is exempt; Ohio's ~$2,400–$2,600 personal exemption is not modeled (the 0%
# bracket is the dominant low-income shelter) → OH taxable income slightly high.
_OH_BRACKETS = _brk([(0, 26050, "0"), (26050, 100000, "0.0275"), (100000, None, "0.03125")])
OH = StateTaxConfig(
    state="OH",
    brackets_by_status={"single": _OH_BRACKETS, "mfj": _OH_BRACKETS},
    standard_deduction_by_status={"single": 0, "mfj": 0},
    taxes_social_security=False, taxes_retirement_income=True,
)

# Mississippi: 0% on the first $10,000 of MS taxable income, 4.4% above (TY2025;
# phasing toward 4.0% by 2026). MS grants BOTH a standard deduction ($2,300/
# $4,600) AND a personal exemption ($6,000/$12,000) — combined here as the
# subtraction ($8,300/$16,600). SS + qualified retirement are exempt.
_MS_BRACKETS = _brk([(0, 10000, "0"), (10000, None, "0.044")])
MS = StateTaxConfig(
    state="MS",
    brackets_by_status={"single": _MS_BRACKETS, "mfj": _MS_BRACKETS},
    standard_deduction_by_status={"single": 830_000, "mfj": 1_660_000},
    taxes_social_security=False, taxes_retirement_income=False,
)

register_bracketed({
    "CA": CA, "NY": NY, "NJ": NJ, "VA": VA,
    "AL": AL, "AR": AR, "CT": CT, "DE": DE, "DC": DC, "HI": HI, "KS": KS,
    "MD": MD, "ME": ME, "MN": MN, "MO": MO, "MS": MS, "MT": MT, "NE": NE,
    "NM": NM, "ND": ND, "OH": OH, "OK": OK, "OR": OR, "RI": RI, "VT": VT,
    "WI": WI, "WV": WV,
})
