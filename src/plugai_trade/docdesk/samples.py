"""Fictional sample documents so the Document Desk works offline on first run.

Kaveri Pumps, Example Ltd, Example SME Ltd and Lakeshore Tools are invented
companies; every figure is synthetic and matches the book's worked examples
where the book prints one. ``make_pdf`` writes a small text PDF so the PDF path
(and the tests) exercise real pypdf extraction.
"""

from __future__ import annotations

from .loader import Document

KAVERI_Q4_FY26 = [
    "Kaveri Pumps Limited (fictional). Q4 FY26 earnings conference call transcript. "
    "Synthetic sample for PlugAI-Trade lessons. Participants: CEO, CFO, analysts.",
    "Good evening and welcome to the Q4 FY26 call. We had a strong year across all segments. "
    "Our dealer network added 140 new outlets and farm demand was healthy.",
    "CEO: We are confident of mid-to-high-teens growth in FY27. We are well positioned "
    "on agricultural pumps and residential pumps, and we see strong momentum.",
    "CFO: Revenue for the quarter was ₹448 crore, up 14.6% year on year. "
    "EBITDA margin was 15.6% for the quarter. Net profit was ₹41.0 crore.",
    "CEO: Our order book is at a record. Demand remains robust in the southern states.",
    "CFO: Receivable days were 71 at the end of the year. Trade receivables stood at ₹280 crore.",
    "Analyst: Any change in the auditor? CFO: No. Our statutory auditor gave an unmodified "
    "opinion on the annual accounts. Thank you, everyone.",
]

KAVERI_Q1_FY27 = [
    "Kaveri Pumps Limited (fictional). Q1 FY27 earnings conference call transcript. "
    "Synthetic sample for PlugAI-Trade lessons. Participants: CEO, CFO, analysts.",
    "Good evening and welcome to the Q1 FY27 call. The quarter was shaped by input costs "
    "and a late monsoon in two of our key states.",
    "CEO: Farm demand was slower in May. Residential pumps held up. We may see some volatility "
    "in the next quarter depending on rainfall.",
    "CFO: Revenue for the quarter was ₹412 crore, against ₹365 crore in Q1 last year. "
    "EBITDA margin came in at 14.2%, compared with 15.1% a year ago, mainly on copper prices. "
    "For the full year we continue to guide for mid-teens revenue growth.",
    "Analyst: Can you comment on the promoter pledge? CFO: As disclosed in the shareholding "
    "pattern, 9.5% of promoter shares are pledged as collateral for a group company loan, "
    "up from nil last quarter.",
    "CFO: Receivable days went up to 78 from 71; we expect them to normalise by Q3. "
    "Some of the large agricultural-pump orders came with longer credit terms. "
    "Trade receivables stood at ₹352 crore against ₹280 crore a year ago.",
    "CFO: Purchases from Kaveri Castings, a promoter-owned foundry and a related party, were "
    "₹41 crore in the quarter against ₹29 crore in Q1 last year, on arm's length terms. "
    "Our statutory auditor is unchanged and gave an unmodified opinion in the last annual report.",
    "CFO: Other income includes an exceptional gain of ₹14 crore from a land sale at our old "
    "Coimbatore depot. Profit before tax was ₹59.6 crore.",
    "Analyst: How do you see the rest of the year? CEO: It could be a challenging quarter.",
    "CEO: Our order book remains healthy, but the monsoon is uncertain.",
    "CEO: We would like to see demand hold up, subject to the monsoon, before we change our view. "
    "Thank you, everyone.",
]

KAVERI_Q2_FY27_RESULTS = [
    "Kaveri Pumps Limited (fictional). Q2 FY27 results release. Filed 16:12 IST. Synthetic sample.",
    "Revenue from operations was ₹468 crore against ₹409 crore in Q2 FY26. "
    "EBITDA margin was 13.6% against 14.8% in Q2 FY26. "
    "Net profit was ₹38.2 crore against ₹36.0 crore in Q2 FY26.",
    "Receivable days were 81 against 78 at the end of Q1. There were no exceptional items "
    "in the quarter.",
    "Management commentary: input costs eased in September, and dealer inventory is normal.",
    "Outlook: we now guide for low-to-mid-teens revenue growth for FY27, subject to the monsoon.",
]

EXAMPLE_RHP = [
    "Example Ltd (fictional). Red Herring Prospectus. Price band ₹270 to ₹284 per equity share. "
    "Synthetic sample for PlugAI-Trade lessons; every figure is invented.",
    "The Offer comprises a fresh issue of 1,40,00,000 equity shares and an offer for sale of "
    "2,10,00,000 equity shares by the selling shareholders. The promoters offer 1,50,00,000 shares "
    "of their 7,80,00,000 shares; Example Growth Fund (a selling shareholder) offers 60,00,000 of "
    "its 1,20,00,000 shares.",
    "Objects of the issue: debt repayment of ₹180 crore; capital expenditure of ₹120 crore; "
    "general corporate purposes of ₹80 crore; issue expenses of ₹17.6 crore.",
    "Restated financials: revenue from operations was ₹1,120 crore in FY26, ₹948 crore in FY25 and "
    "₹806 crore in FY24. EBITDA was ₹176 crore in FY26. Profit after tax was ₹96 crore in FY26. "
    "Total borrowings were ₹310 crore and net cash from operations was ₹88 crore in FY26.",
    "Capital structure: pre-issue shares outstanding are 10,00,00,000 and post-issue shares "
    "outstanding will be 11,40,00,000. Promoter holding is 78.0% pre-issue and 55.3% post-issue. "
    "No promoter shares are pledged.",
    "Basis for offer price: the listed peers are Peer One Ltd at a P/E of 28.4, Peer Two Ltd at a "
    "P/E of 35.2 and Peer Three Ltd at a P/E of 41.0.",
    "Risk factors: Our top five customers contributed 58% of FY26 revenue. A promoter-group firm "
    "supplies 21% of our raw material. Receivable days rose from 71 in FY24 to 94 in FY26. "
    "A tax demand of ₹38 crore is under appeal. Our business depends on economic conditions.",
    "Related party transactions with the promoter group were ₹236 crore in FY26. Contingent "
    "liabilities not provided for were ₹64 crore, the largest being the tax demand under appeal.",
    "Anchor investors: 1,05,00,000 shares were allotted to anchor investors at ₹284, an anchor book "
    "of ₹298.2 crore. Lock-in: 50% of anchor shares are locked in for 30 days and the rest for "
    "90 days from allotment; pre-IPO shareholders are locked in for six months; the promoters' "
    "minimum contribution of 20% is locked in for 18 months.",
    "Retail portion: 1,22,50,000 shares in lots of 50. Minimum application: one lot.",
]

EXAMPLE_SME_RHP = [
    "Example SME Ltd (fictional). Red Herring Prospectus for an SME IPO on NSE Emerge. "
    "Synthetic sample; every figure is invented. Issue price ₹90 per share; lot size 1,200 shares.",
    "Restated EBITDA was ₹1.2 crore in FY26, ₹0.8 crore in FY25 and ₹1.4 crore in FY24.",
    "The issue comprises a fresh issue of 20,00,000 shares and an offer for sale of 4,40,000 shares, "
    "so the offer for sale is 18.0% of the issue. The selling shareholders are selling 40% of "
    "their holding.",
    "Minimum application: two lots, that is 2,400 shares or ₹2,16,000 at the issue price.",
    "Market maker: Example Market Makers Pvt Ltd (fictional) will act as the market maker for three "
    "years from listing.",
    "Related party transactions: rent paid to a promoter of ₹0.3 crore a year. The company raised "
    "₹4 crore in a private placement 14 months before filing.",
]

LAKESHORE_10K = [
    "Lakeshore Tools Inc. (fictional) Annual Report on Form 10-K. Synthetic sample.",
    "Item 1A. Risk Factors. Our gross margins will be subject to volatility and downward pressure. "
    "Three customers accounted for 41% of net sales.",
    "Item 7. Management's Discussion and Analysis. Net sales were $2,140 million, compared with "
    "$1,985 million in the prior year, driven by professional tools. We expect demand to remain "
    "uncertain in the first half.",
    "Item 7. Accounts receivable were $412 million against $351 million a year earlier.",
    "Item 8. Financial Statements. Our auditor has served as the Company's auditor since 2009 and "
    "issued an unqualified opinion. A one-time gain of $18 million from a warehouse sale is included "
    "in other income.",
]

SAMPLES: dict[str, tuple[list[str], str]] = {
    "Kaveri_Q4-FY26_concall": (KAVERI_Q4_FY26, "IN"),
    "Kaveri_Q1-FY27_concall": (KAVERI_Q1_FY27, "IN"),
    "Kaveri_Q2-FY27_results": (KAVERI_Q2_FY27_RESULTS, "IN"),
    "Example-Ltd_RHP": (EXAMPLE_RHP, "IN"),
    "Example-SME-Ltd_RHP": (EXAMPLE_SME_RHP, "IN"),
    "Lakeshore_10-K": (LAKESHORE_10K, "US"),
}


def sample(name: str) -> Document:
    """One of the fictional sample documents, page-labelled."""
    pages, market = SAMPLES[name]
    return Document(
        name=name, pages=list(pages), source="sample (fictional)", market=market, kind="sample"
    )


def _pdf_escape(line: str) -> str:
    line = (
        line.replace("₹", "Rs ")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
    )
    line = line.encode("latin-1", "replace").decode("latin-1")
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text: str, width: int = 90) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + 1 > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


def make_pdf(pages: list[str]) -> bytes:
    """A minimal text PDF (Helvetica, one text block per page). Empty pages act as scans."""
    objs: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    objs.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    for i, text in enumerate(pages):
        body = (
            "BT /F1 10 Tf 14 TL 50 790 Td "
            + " ".join(f"({_pdf_escape(ln)}) '" for ln in _wrap(text))
            + " ET"
            if text.strip()
            else ""
        )
        stream = body.encode("latin-1")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objs.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for k, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
