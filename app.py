import streamlit as st
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
from textwrap import dedent
from dotenv import load_dotenv; load_dotenv()
import os
import os, json
from anthropic import Anthropic

API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
api_key = os.getenv("ANTHROPIC_API_KEY")

if not api_key:
    raise ValueError("ANTHROPIC_API_KEY not found in environment variables")
anthropic_client = Anthropic(api_key=api_key)


# ---------- Page config ----------
st.set_page_config(page_title="Optimum ISP Wizard", layout="wide")


# ---------- Simple CSS ----------
st.markdown("""
<style>
/* --- shell --- */
.navbar { background:#0072C6; padding:.5rem 2rem; color:#fff; font-size:16px; display:flex; justify-content:space-between; }
.nav-links { display:flex; gap:2rem; }
.nav-links a { color:#fff; text-decoration:none; }

/* --- plan cards --- */
.plan-card{
  background:#fff;
  padding:16px 20px;
  border-radius:12px;
  border:1px solid #e5e7eb;
  box-shadow:0 2px 10px rgba(0,0,0,.06);
}
.plan-card.best{
  border:2px solid #22c55e;         /* full green enclosure */
  background:#f6fffb;               /* soft green */
  box-shadow:0 6px 20px rgba(34,197,94,.12);
}
.plan-title{ margin:0 0 6px 0; font-weight:700; font-size:20px; }
.plan-badge{ display:inline-block; font-size:12px; font-weight:700; color:#065f46;
             border:2px solid #22c55e; background:#eafff3; padding:4px 10px; border-radius:999px; margin-bottom:8px;}
.plan-price{ font-size:28px; font-weight:800; margin:.25rem 0 .75rem 0; }
.plan-meta li { line-height:1.5; margin:.3rem 0; }
.divider{ height:1px; background:#e5e7eb; margin:18px 0; }
.reason-title{ font-weight:700; margin-bottom:6px; }
</style>
""", unsafe_allow_html=True)



# ---------- Session state ----------
if "step" not in st.session_state:
    st.session_state.step = 0
if "responses" not in st.session_state:
    st.session_state.responses = {}

TOTAL_STEPS = 11  # welcome + 9 Q steps + results

def header(step_number: int, title: str):
    display_idx = step_number + 1
    st.markdown(f"<div class='step-caption'>Step {display_idx} of {TOTAL_STEPS}</div>", unsafe_allow_html=True)
    st.progress(min(display_idx / TOTAL_STEPS, 1.0))
    st.title(title)

def next_step(n: int):
    st.session_state.step = n
    st.rerun()


# =========================
# Data Model (random but realistic)
# =========================
@dataclass
class Plan:
    id: str
    name: str
    tech: str             # 'fiber' or 'hybrid'
    down_mbps: int
    up_mbps: int
    includes_tv: bool
    tv_packs: List[str]   # e.g., ['sports', 'premium', 'kids', 'intl', 'news', 'entertainment']
    mobile_lines_included: int
    base_price: int       # $/mo (first 12 months, illustrative)
    includes_router: bool
    dvr_included: bool
    notes: List[str]

PLAN_CATALOG: List[Plan] = [
    Plan("S100",  "Internet 100",         "hybrid", 100, 10, False, [],                        0, 40, True,  False, ["Good for 1–2 users, light use"]),
    Plan("S300",  "Internet 300",         "hybrid", 300, 20, False, [],                        0, 55, True,  False, ["Solid for HD streaming + calls"]),
    Plan("S500M", "500 Mbps + Mobile 1",  "hybrid", 500, 25, False, [],                        1, 95, True,  False, ["Bundle saves vs. separate"]),
    Plan("S500T", "500 Mbps Triple Play", "hybrid", 500, 25, True,  ["entertainment","premium","news"], 0, 150, True, True,  ["HBO/Showtime offers included"]),
    Plan("G1000","1 Gig Fiber",           "fiber", 1000, 100, False, [],                       0, 85, True,  False, ["Low-latency fiber for WFH/gaming"]),
    Plan("G1000M","1 Gig Fiber + 2 Lines","fiber", 1000, 100, False, [],                      2, 120, True,  False, ["Mobile bundle discount"]),
    Plan("G1000T","1 Gig Fiber Triple",   "fiber", 1000, 100, True, ["sports","entertainment","kids","news"], 0, 185, True, True, ["Great for households with TV"]),
    Plan("G2000","2 Gig Fiber",           "fiber", 2000, 200, False, [],                       0, 125, True, False, ["Power users & heavy downloads"]),
]

# Mesh add-on guidance (not pricing—just advice)
MESH_GUIDE = {
    "Small (1–2 bedrooms)": {"nodes": 1, "copy": "Single router should cover a small apartment."},
    "Medium (3 bedrooms)":  {"nodes": 2, "copy": "Consider a 2-node mesh for stable coverage."},
    "Large (4+ bedrooms)":  {"nodes": 3, "copy": "We recommend a 3-node mesh for consistent speeds."},
    "Multi-story":          {"nodes": 3, "copy": "Mesh with one node per floor is ideal."},
}
# ----- Pricing assumptions for à la carte (tweak as needed) -----
INTERNET_STANDALONE_BRACKETS = [
    (0, 150, 40),     # up to 150 Mbps
    (150, 400, 55),   # 150–399
    (400, 800, 80),   # 400–799
    (800, 1200, 85),  # 800–1199 (1 Gig)
    (1200, 10000, 125) # 1.2–10 Gig
]

# ---------- Bundle add-on pricing (discounted vs à-la-carte) ----------
# Extra mobile lines when you already have our Internet:
BUNDLE_MOBILE_PER_LINE = 35  # flat per extra line (typical "with internet" rate)

# TV when bundled with Internet:
BUNDLE_TV_BASE_PRICE = 50
BUNDLE_TV_ADDON_PRICES = {
    'sports': 12,
    'premium': 15,
    'kids': 8,
    'intl': 8,
    'news': 6,
    'entertainment': 8,
}
BUNDLE_DVR_PRICE = 7

# Optional credits on Internet when adding other services to an internet-only plan:
BUNDLE_INTERNET_CREDIT_WITH_MOBILE = 10
BUNDLE_INTERNET_CREDIT_WITH_TV = 10
BUNDLE_INTERNET_CREDIT_MAX = 15  # cap combined credit


def internet_standalone_price(down_mbps: int) -> int:
    for lo, hi, price in INTERNET_STANDALONE_BRACKETS:
        if lo <= down_mbps < hi:
            return price
    return 125

def mobile_alacarte_total(n: int) -> int:
    # Tiered per-line pricing
    if n <= 1: rate = 55
    elif n == 2: rate = 45
    elif n == 3: rate = 40
    else: rate = 35
    return n * rate

TV_BASE_PRICE = 60
TV_ADDON_PRICES = {'sports':15, 'premium':20, 'kids':10, 'intl':10, 'news':8, 'entertainment':10}
DVR_PRICE = 10

def map_tv_prefs_to_codes(prefs: set) -> set:
    codes = set()
    if "Live Sports (ESPN, Fox Sports, etc.)" in prefs: codes.add('sports')
    if "Premium channels (HBO, Showtime, Starz)" in prefs: codes.add('premium')
    if "Kids & Family (Disney, Nickelodeon, Cartoon Network)" in prefs: codes.add('kids')
    if "International/Spanish language" in prefs: codes.add('intl')
    if "News (CNN, Fox News, MSNBC, etc.)" in prefs: codes.add('news')
    if "Movies & Entertainment (TNT, USA, TBS, etc.)" in prefs: codes.add('entertainment')
    return codes

def tv_alacarte_total(prefs: set, want_dvr: bool = True) -> int:
    total = TV_BASE_PRICE
    for c in map_tv_prefs_to_codes(prefs):
        total += TV_ADDON_PRICES.get(c, 0)
    if want_dvr:
        total += DVR_PRICE
    return total

def bundle_vs_alacarte(plan: Plan, demand: Dict[str, Any]) -> Dict[str, Any]:
    """Compare 'as configured' bundle total for this plan vs buying services à la carte."""

    n_lines = demand.get('mobile_lines_need', 1)
    want_tv = demand.get('tv_interest') in ["Yes, definitely", "Maybe, show me options"]
    prefs = demand.get('tv_prefs', set())

    # À LA CARTE (buy everything separately)
    # Use the minimal internet tier that meets the user's estimated need.
    need_speed = demand.get('required_down', plan.down_mbps)
    internet_price = internet_standalone_price(need_speed)
    mobile_price = mobile_alacarte_total(n_lines)
    tv_price = tv_alacarte_total(prefs) if want_tv else 0
    alacarte_total = internet_price + mobile_price + tv_price

    # BUNDLE (what you'd pay with this specific plan)
    # IMPORTANT: no separate "internet credit" — the discount is already reflected
    # in the bundle mobile per-line rate and (if applicable) bundle TV pricing.
    bundle_total = plan.base_price

    # Extra mobile lines beyond the plan's included lines → use bundle rate
    extra_lines = max(0, n_lines - plan.mobile_lines_included)
    bundle_extra_mobile = extra_lines * BUNDLE_MOBILE_PER_LINE
    bundle_total += bundle_extra_mobile

    # TV at bundle pricing
    bundle_tv_addons = 0
    if want_tv:
        requested = map_tv_prefs_to_codes(prefs)
        if plan.includes_tv:
            missing = requested - set(plan.tv_packs)
            bundle_tv_addons += sum(BUNDLE_TV_ADDON_PRICES.get(m, 0) for m in missing)
            if not plan.dvr_included:
                bundle_tv_addons += BUNDLE_DVR_PRICE
        else:
            bundle_tv_addons += BUNDLE_TV_BASE_PRICE
            bundle_tv_addons += sum(BUNDLE_TV_ADDON_PRICES.get(m, 0) for m in requested)
            bundle_tv_addons += BUNDLE_DVR_PRICE
        bundle_total += bundle_tv_addons

    savings = alacarte_total - bundle_total
    return {
        "internet_price": internet_price,
        "mobile_price": mobile_price,
        "tv_price": tv_price,
        "alacarte_total": alacarte_total,
        "bundle_total": bundle_total,
        "bundle_extra_mobile": bundle_extra_mobile,
        "bundle_tv_addons": bundle_tv_addons,
        "bundle_internet_credit": 0,   # removed (avoid double counting)
        "savings": savings
    }




# =========================
# Demand Estimation & Scoring
# =========================
def estimate_demand(resp: Dict[str, Any]) -> Dict[str, Any]:
    """Estimate required Mbps with realistic concurrency and device overhead."""
    # People / devices
    people = resp.get("household", {}).get("people", "Just me")
    ppl_map = {"Just me": 1, "2 people": 2, "3–4 people": 4, "5+ people": 5}
    n_people = ppl_map.get(people, 1)

    devices_choice = resp.get("devices", "1–5 devices")
    dev_map = {"1–5 devices": 5, "6–10 devices": 10, "11–15 devices": 15, "15+ devices": 20}
    n_devices = dev_map.get(devices_choice, 5)

    peak = set(resp.get("evening", []))
    reliability_text = resp.get("reliability", "Moderate")
    size = resp.get("home_size", "Small (1–2 bedrooms)")
    tv_interest = resp.get("tv_interest", "No, streaming only")
    tv_prefs = set(resp.get("tv_prefs", []))
    streaming_now = resp.get("streaming", "No")
    lines_choice = resp.get("mobile_lines", "1 line (~$55/month)")

    # Base + device overhead (light traffic)
    est = 3 * n_people + max(0, n_devices - 5) * 0.6

    # Peak activities (concurrent)
    if "Streaming video (Netflix, YouTube, etc.)" in peak:
        est += 7 * min(n_people, 3)                # ~1080p streams
    if "Video calls/conferencing" in peak:
        est += 3 * min(n_people, 2)                # Zoom/Teams 720p
    if "Online gaming" in peak:
        est += 2                                   # bw small; latency matters
    if "Multiple people doing different things at once" in peak:
        est += 6
    if "Downloading large files" in peak:
        est += 15                                  # allowance for bursts
    if "Smart home devices actively used" in peak:
        est += min(6, 0.4 * max(0, n_devices - 5))

    # Reliability / latency flags
    needs_low_latency = ("Online gaming" in peak) or reliability_text.startswith("Critical")
    high_reliability = reliability_text in [
        "Critical (work from home) – I need guaranteed uptime",
        "Very important",
    ]

    # Buffering: more if high reliability
    buffer = 1.4 if high_reliability else 1.2
    required_down = int(max(25, round(est * buffer)))
    required_up = 20 if high_reliability else (10 if "Video calls/conferencing" in peak else 5)

    return {
        "n_people": n_people,
        "n_devices": n_devices,
        "required_down": required_down,
        "required_up": required_up,
        "needs_low_latency": needs_low_latency,
        "high_reliability": high_reliability,
        "size": size,
        "tv_interest": tv_interest,
        "tv_prefs": tv_prefs,
        "streaming_now": streaming_now,
        "mobile_lines_need": int(lines_choice.split()[0].replace("+","").replace("line","").strip()) if lines_choice else 1,
    }

def score_plan(plan: Plan, d: Dict[str, Any], resp: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:  # noqa: D401
    """Return (score, meta). Higher is better."""
    reasons: List[str] = []
    score = 0.0

    # --- Hard requirements ---
    if plan.up_mbps < d["required_up"]:
        return -1e9, {"reasons": ["Upload speed too low for your needs."], "headroom": 0.0}

    headroom = plan.down_mbps / max(1, d["required_down"])
    if headroom < 1.0:
        return -1e9, {"reasons": ["Not enough download speed for your estimated need."], "headroom": headroom}

    # --- Headroom curve: reward ~1.2–2.5×, penalize big overkill ---
    if 1.2 <= headroom <= 2.5:
        score += 38
        reasons.append(f"Speed headroom in the sweet spot (~{headroom:.1f}× of your need).")
    elif headroom < 1.2:
        # 1.0–1.2×: usable but little cushion (0..24 points)
        score += 24 * (headroom - 1.0) / 0.2
        reasons.append(f"Just meets your need (~{headroom:.1f}×).")
    elif headroom <= 3.5:
        # 2.5–3.5×: mild overprovisioning (gently decreasing)
        score += 34 - 8 * (headroom - 2.5)
        reasons.append(f"More headroom than necessary (~{headroom:.1f}×).")
    else:
        # >3.5×: strong penalty (still possible to win via price/features)
        score += 20 - 6 * (headroom - 3.5)
        reasons.append(f"Significantly over-provisioned (~{headroom:.1f}×).")

    # --- Reliability / latency preferences ---
    if d["needs_low_latency"] or d["high_reliability"]:
        if plan.tech == "fiber":
            score += 8
            reasons.append("Fiber helps with latency and reliability.")
        else:
            score -= 5
            reasons.append("Non-fiber may have more variable latency.")
    else:
        # small bump for gig fiber when not strictly required
        if plan.tech == "fiber" and plan.down_mbps >= 1000:
            score += 2

    # --- TV fit ---
    want_tv = d["tv_interest"] in ["Yes, definitely", "Maybe, show me options"]
    if want_tv:
        if plan.includes_tv:
            score += 8
            reasons.append("Includes TV service as requested.")
            prefs = d["tv_prefs"]
            matched = [p for p in plan.tv_packs if (
                (p == "sports" and "Live Sports (ESPN, Fox Sports, etc.)" in prefs) or
                (p == "kids" and "Kids & Family (Disney, Nickelodeon, Cartoon Network)" in prefs) or
                (p == "premium" and "Premium channels (HBO, Showtime, Starz)" in prefs) or
                (p == "intl" and "International/Spanish language" in prefs) or
                (p == "news" and "News (CNN, Fox News, MSNBC, etc.)" in prefs) or
                (p == "entertainment" and "Movies & Entertainment (TNT, USA, TBS, etc.)" in prefs)
            )]
            score += 2 * len(matched)
            if matched:
                reasons.append(f"TV packs aligned: {', '.join(matched)}.")
        else:
            score -= 12
            reasons.append("No TV included, but you asked to see TV options.")
    else:
        if plan.includes_tv:
            score -= 8
            reasons.append("Includes TV you may not need (streaming-only choice).")

    # --- Mobile bundle fit (single weighting) ---
    need_lines = d["mobile_lines_need"]
    if plan.mobile_lines_included >= need_lines and need_lines > 0:
        score += 10
        reasons.append(f"Includes {plan.mobile_lines_included} mobile line(s) you need.")
    elif plan.mobile_lines_included > 0:
        score += 5
        reasons.append("Includes some mobile lines (you can add more).")
    elif need_lines >= 3:
        score -= 8
        reasons.append("Plan includes no mobile lines but you need several.")

    # --- Economics: use the AS-CONFIGURED monthly total for this user ---
    cost = bundle_vs_alacarte(plan, d)
    monthly_total = cost["bundle_total"]

    # single, gentle price anchor on actual monthly total
    score += max(0, 35 - monthly_total / 9.0)
    reasons.append(f"As-configured monthly total about ${monthly_total}/mo.")

    # relative economics vs à la carte (±12 max)
    save = int(round(cost["savings"]))
    score += max(-12, min(12, save / 8.0))
    reasons.append(f"Estimated {save:+.0f}$/mo vs buying separately.")

    return score, {"reasons": reasons, "headroom": headroom}

def rank_plans(resp: Dict[str, Any]) -> Tuple[List[Tuple[Plan, float, Dict[str, Any]]], Dict[str, Any]]:
    demand = estimate_demand(resp)
    scored: List[Tuple[Plan, float, Dict[str, Any]]] = []
    for p in PLAN_CATALOG:
        sc, meta = score_plan(p, demand, resp)
        if sc > -1e8:
            scored.append((p, sc, meta))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored, demand
def role_label(idx: int) -> str:
    return {0: "Best match", 1: "Runner-up", 2: "Also consider"}.get(idx, "Option")

def headroom_phrase(h: float) -> str:
    if h < 1.2:   return "meets your need with a small cushion"
    if h <= 2.5:  return f"gives a comfortable ~{h:.1f}× cushion"
    return f"provides extra headroom (~{h:.1f}×) for busy periods"

def economy_phrase(s: int) -> str:
    if s >= 5:    return f"saves about ${s}/mo versus buying separately"
    if s >= -5:   return "costs about the same as buying separately"
    return f"is within ${abs(s)}/mo of buying separately but consolidates into one bill and includes bundle perks"

def tv_match_count(plan: Plan, prefs: set) -> int:
    wanted = map_tv_prefs_to_codes(prefs)
    return len(set(plan.tv_packs) & wanted)


# =========================
# Optional LLM narration hook
# =========================
def generate_narrative(plan: Plan, demand: Dict[str, Any], reasons: List[str]) -> str:
    """
    Uses Claude for a short consumer-friendly blurb if ANTHROPIC_API_KEY is set.
    Falls back to deterministic copy if not.
    """
    # Fallback path (no key / client)
    def _fallback() -> str:
        bits = []
        if demand.get("high_reliability"):
            bits.append("reliable connection for work-from-home")
        if demand.get("needs_low_latency"):
            bits.append("low-latency performance for gaming/calls")
        bits.append(f"{plan.down_mbps} Mbps download")
        if plan.includes_tv:
            bits.append("TV service included")
        if plan.mobile_lines_included:
            bits.append(f"{plan.mobile_lines_included} mobile line(s) bundled")
        base = ("; ".join(bits) + ". ").capitalize()
        return base + " " + " ".join(reasons[:2])

    if anthropic_client is None:
        return _fallback()

    # Build a compact, structured prompt
    user_payload = {
        "plan": {
            "name": plan.name,
            "tech": plan.tech,
            "down_mbps": plan.down_mbps,
            "up_mbps": plan.up_mbps,
            "includes_tv": plan.includes_tv,
            "tv_packs": plan.tv_packs,
            "mobile_lines_included": plan.mobile_lines_included,
            "price": plan.base_price,
        },
        "demand": {
            "required_down": demand["required_down"],
            "required_up": demand["required_up"],
            "high_reliability": demand["high_reliability"],
            "needs_low_latency": demand["needs_low_latency"],
            "house_size": demand["size"],
            "devices": demand["n_devices"],
            "people": demand["n_people"],
        },
        "reasons": reasons[:6],  # cap to keep prompt short
    }

    system_msg = (
        "You are a concise telecom copywriter. Write clear, compliant, 2–3 sentence blurbs for consumers. "
        "Avoid unverifiable claims, no speed guarantees, no legal or promo jargon. "
        "Mention fit in plain English and reflect the user's needs."
    )
    user_msg = (
        "Write a 2–3 sentence 'Why this fits' paragraph for the plan below, using neutral, factual language. "
        "Do not repeat bullet points verbatim; summarize benefits. "
        "Return plain text only (no markdown, no lists).\n\n"
        f"{json.dumps(user_payload, indent=2)}"
    )

    try:
        resp = anthropic_client.messages.create(
            model=ANTHROPIC_MODEL,                 # e.g. claude-sonnet-4-5-20250929
            max_tokens=220,
            temperature=0.5,
            system=system_msg,
            messages=[{"role": "user", "content": user_msg}],
        )
        # Claude returns a list of content blocks; we want the text part
        if getattr(resp, "content", None):
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    txt = getattr(block, "text", "").strip()
                    if txt:
                        return txt
        return _fallback()
    except Exception:
        # Never break your flow if API fails
        return _fallback()

def generate_narrative_ranked(
    plan: Plan,
    demand: Dict[str, Any],
    savings: int,           # from bundle_vs_alacarte
    headroom: float,        # from score_plan meta
    rank_idx: int,
    alts: list              # [{name, role, price, savings}] for the other two cards
) -> str:
    role = role_label(rank_idx)
    tv_matches = tv_match_count(plan, demand.get("tv_prefs", set()))
    need_lines = demand.get("mobile_lines_need", 1)

    # ---------- deterministic fallback ----------
    def _fallback() -> str:
        bits = []
        bits.append(f"{role}: {plan.name} {headroom_phrase(headroom)}")
        if plan.includes_tv and tv_matches:
            bits.append(f"and includes TV packs that match your interests")
        if plan.mobile_lines_included:
            if plan.mobile_lines_included >= need_lines:
                bits.append(f"with {plan.mobile_lines_included} mobile line(s) included")
            else:
                bits.append(f"with {plan.mobile_lines_included} mobile line(s) included")
        bits.append(f"and {economy_phrase(int(round(savings)))} at ${plan.base_price}/mo.")
        # one short placement cue vs alternatives
        if alts:
            alt = alts[0]
            bits.append(f"It ranks above {alt['name']} because it balances features and total monthly cost better for your selections.")
        return " ".join(bits)

    # If no client/key, keep the friendly fallback
    if anthropic_client is None:
        return _fallback()

    # ---------- Claude prompt ----------
    import json
    system_msg = (
        "You write short plan blurbs for an ISP comparison page. "
        "Your job is to DEFEND the ranking (Best match / Runner-up / Also consider). "
        "Tone: positive, confident, helpful. 1–2 sentences. "
        "NEVER suggest switching to a cheaper/faster plan or to look for another tier. "
        "No markdown, no bullets, no hedging; explain why THIS plan is placed where it is, "
        "referencing speed headroom, features (TV packs, mobile lines), and monthly economics."
    )

    payload = {
        "role": role,
        "plan": {
            "name": plan.name,
            "price": plan.base_price,
            "tech": plan.tech,
            "down_mbps": plan.down_mbps,
            "up_mbps": plan.up_mbps,
            "includes_tv": plan.includes_tv,
            "tv_packs": plan.tv_packs,
            "mobile_lines_included": plan.mobile_lines_included,
        },
        "user_need": {
            "required_down": demand["required_down"],
            "required_up": demand["required_up"],
            "tv_interest": demand["tv_interest"],
            "mobile_lines_need": need_lines,
        },
        "metrics": {
            "headroom": round(headroom, 2),
            "tv_match_count": tv_matches,
            "savings_vs_alacarte": int(round(savings)),
        },
        "alternatives": alts[:2],  # names, roles, prices, savings of others
        "instructions": "Defend this ranking and focus on fit for the user's selections."
    }

    try:
        resp = anthropic_client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=160,
            temperature=0.4,
            system=system_msg,
            messages=[{"role": "user", "content": "Write the blurb for this card:\n" + json.dumps(payload, ensure_ascii=False)}],
        )
        if getattr(resp, "content", None):
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    txt = getattr(block, "text", "").strip()
                    if txt:
                        return txt
        return _fallback()
    except Exception:
        return _fallback()


# =========================
# UI Flow (forms so single-click works)
# =========================

# Step 0: Welcome
if st.session_state.step == 0:
    st.title("Welcome to Optimum")
    st.markdown("Fast, reliable internet and mobile services for your home.")

    col1, col2, col3 = st.columns(3)
    for col, title, desc in zip(
        [col1, col2, col3],
        ["⚡ Lightning Fast Internet", "📱 Mobile Plans", "💰 Bundle & Save"],
        [
            "Experience speeds up to **1 Gbps** with our fiber network.",
            "Unlimited data plans starting at just **$25/month**.",
            "Bundle internet, mobile, and TV together for the best price.",
        ],
    ):
        with col:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.subheader(title)
            st.markdown(desc)
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("""
    <div class="card">
      <h3>Not sure which plan is right for you?</h3>
      <p>Let us help you find the perfect bundle for your household. Takes just 2–5 minutes.</p>
    </div>
    """, unsafe_allow_html=True)

    with st.form("start_form"):
        start = st.form_submit_button("🚀 Help Me Decide")
    if start: next_step(1)

# Step 1
elif st.session_state.step == 1:
    header(1, "📡 Help Me Decide: ISP Plan Wizard")
    st.subheader("👨‍👩‍👧‍👦 Household Profile")
    with st.form("household_form"):
        people = st.radio("How many people live in your home?", ["Just me", "2 people", "3–4 people", "5+ people"], key="people")
        hh_type = st.selectbox("What best describes your household?", ["Single/Couple","Family with kids","Roommates","Remote workers","Retired/Light users"], key="hh_type")
        submitted = st.form_submit_button("Continue")
    if submitted:
        st.session_state.responses["household"] = {"people": people, "type": hh_type}
        if people in ["Just me", "2 people"] and hh_type in ["Single/Couple","Retired/Light users"]:
            next_step(3)  # skip deep dive
        else:
            next_step(2)

# Step 2
elif st.session_state.step == 2:
    header(2, "During peak evening hours (6–10pm), what's happening in your home?")
    st.caption("Select all that apply")
    with st.form("peak_form"):
        evening = st.multiselect(
            "Peak hours: 6–10pm",
            [
                "Streaming video (Netflix, YouTube, etc.)",
                "Online gaming",
                "Video calls/conferencing",
                "Multiple people doing different things at once",
                "Downloading large files",
                "Smart home devices actively used",
            ],
            key="evening",
        )
        submitted = st.form_submit_button("Continue")
    if submitted:
        st.session_state.responses["evening"] = evening
        next_step(3)

# Step 3
elif st.session_state.step == 3:
    header(3, "How important is reliability to you?")
    with st.form("reliability_form"):
        reliability = st.radio("", ["Critical (work from home) – I need guaranteed uptime","Very important","Moderate","Basic is fine"], key="reliability")
        submitted = st.form_submit_button("Continue")
    if submitted:
        st.session_state.responses["reliability"] = reliability
        next_step(4)

# Step 4
elif st.session_state.step == 4:
    header(4, "About how many devices connect to your Wi-Fi?")
    st.caption("Include phones, tablets, laptops, smart TVs, smart home devices, etc.")
    with st.form("devices_form"):
        devices = st.radio("", ["1–5 devices","6–10 devices","11–15 devices","15+ devices"], key="devices")
        submitted = st.form_submit_button("Continue")
    if submitted:
        st.session_state.responses["devices"] = devices
        next_step(5)

# Step 5
elif st.session_state.step == 5:
    header(5, "What's the size of your home?")
    st.caption("Helps us recommend Wi-Fi coverage solutions")
    with st.form("home_form"):
        size = st.radio("", ["Small (1–2 bedrooms)","Medium (3 bedrooms)","Large (4+ bedrooms)","Multi-story"], key="home_size")
        submitted = st.form_submit_button("Continue")
    if submitted:
        st.session_state.responses["home_size"] = size
        next_step(6)

# Step 6
elif st.session_state.step == 6:
    header(6, "Are you interested in cable TV service?")
    with st.form("tv_interest_form"):
        tv_interest = st.radio("", ["Yes, definitely","Maybe, show me options","No, streaming only","Not sure"], key="tv_interest")
        submitted = st.form_submit_button("Continue")
    if submitted:
        st.session_state.responses["tv_interest"] = tv_interest
        next_step(7 if tv_interest in ["Yes, definitely","Maybe, show me options"] else 8)

# Step 7
elif st.session_state.step == 7:
    header(7, "What kind of programming matters most to you?")
    st.caption("Select all that apply")
    with st.form("tv_prefs_form"):
        tv_prefs = st.multiselect(
            "",
            [
                "Live Sports (ESPN, Fox Sports, etc.)",
                "News (CNN, Fox News, MSNBC, etc.)",
                "Movies & Entertainment (TNT, USA, TBS, etc.)",
                "Kids & Family (Disney, Nickelodeon, Cartoon Network)",
                "Premium channels (HBO, Showtime, Starz)",
                "International/Spanish language",
            ],
            default=["Movies & Entertainment (TNT, USA, TBS, etc.)","Premium channels (HBO, Showtime, Starz)"],
            key="tv_prefs",
        )
        submitted = st.form_submit_button("Continue")
    if submitted:
        st.session_state.responses["tv_prefs"] = tv_prefs
        next_step(8)

# Step 8
elif st.session_state.step == 8:
    header(8, "Do you currently use streaming services?")
    with st.form("streaming_form"):
        streaming = st.radio("", ["Yes, multiple services (3+)","Yes, 1–2 services","No"], key="streaming")
        submitted = st.form_submit_button("Continue")
    if submitted:
        st.session_state.responses["streaming"] = streaming
        next_step(9)

# Step 9
elif st.session_state.step == 9:
    header(9, "How many mobile lines would you need?")
    with st.form("mobile_lines_form"):
        lines = st.radio("", ["1 line (~$55/month)","2 lines (~$45/line per month)","3 lines (~$40/line per month)","4+ lines (~$35/line per month)"], key="mobile_lines")
        submitted = st.form_submit_button("See My Recommendations")
    if submitted:
        st.session_state.responses["mobile_lines"] = lines
        next_step(10)

# Step 10: Results
elif st.session_state.step == 10:
    header(10, "Here are your personalized recommendations")

    # place Start Over button in the header row (right aligned)
    top_l, top_spacer, top_r = st.columns([0.6, 0.25, 0.15])
    with top_l:
        st.subheader("Based on your household needs and usage patterns")
    with top_r:
        st.button("⬅️ Start Over", use_container_width=True, on_click=next_step, args=(0,))

    
    ranked, demand = rank_plans(st.session_state.responses)
    top3 = ranked[:3]

    # Precompute per-card cost + a small summary for cross-references
    cards = []
    for (p, sc, meta) in top3:
        c = bundle_vs_alacarte(p, demand)
        cards.append({"plan": p, "score": sc, "meta": meta, "cost": c})

    cols = st.columns(len(cards)) if cards else [st.container()]

    # Build a lightweight alt list for each card
    def alt_overview(exclude_idx: int):
        alts = []
        for j, item in enumerate(cards):
            if j == exclude_idx: 
                continue
            q = item["plan"]
            alts.append({
                "name": q.name,
                "role": role_label(j),
                "price": q.base_price,
                "savings": int(round(item["cost"]["savings"]))
            })
        return alts



    for idx, item in enumerate(cards):
        plan, meta, cost = item["plan"], item["meta"], item["cost"]
        is_best = (idx == 0)

         # pricing bits
        savings = int(round(cost["savings"]))
        as_config = cost["bundle_total"]  # <-- the price users care about
        s_class = "positive" if savings >= 0 else "negative"
        savings_html = f'<div class="savings {s_class}">Estimated savings vs à la carte: <b>${savings}/mo</b></div>'

        # bullets
        badge_html = '<div class="plan-badge">BEST MATCH</div>' if is_best else ""
        tv_line    = f"Includes TV ({', '.join(plan.tv_packs)} packs)" if plan.includes_tv else "Internet only"
        dvr_line   = "DVR included" if plan.dvr_included else ""
        lines_line = f"{plan.mobile_lines_included} mobile line(s) included" if plan.mobile_lines_included else ""

        meta_list_html = (
            '<ul class="plan-meta">'
            f'<li><b>{plan.down_mbps} Mbps</b> download / <b>{plan.up_mbps} Mbps</b> upload</li>'
            f'<li>Technology: <b>{plan.tech.capitalize()}</b></li>'
            f'<li>{tv_line}</li>'
            f'{f"<li>{dvr_line}</li>" if dvr_line else ""}'
            f'{f"<li>{lines_line}</li>" if lines_line else ""}'
            '<li>Free Wi-Fi router</li>'
            '</ul>'
        )

        # ranking-aware narrative (Claude or fallback)
        narrative = generate_narrative_ranked(
            plan=plan,
            demand=demand,
            savings=savings,
            headroom=float(meta.get("headroom", 0.0)),
            rank_idx=idx,
            alts=alt_overview(idx),
        )

        card_html = dedent(f"""
        <div class="plan-card {'best' if is_best else ''}">
          {badge_html}
          <h3 class="plan-title">{plan.name}</h3>
          <div class="plan-price">${as_config}/month <span style="font-size:12px;color:#666">(as configured)</span></div>
          <div style="font-size:12px;color:#6b7280;margin-top:-6px;margin-bottom:6px">
            Base internet ${plan.base_price}/mo{'; includes TV' if plan.includes_tv else ''}{'; ' + str(plan.mobile_lines_included) + ' mobile line(s) included' if plan.mobile_lines_included else ''}.
          </div>
          {meta_list_html}
          {savings_html}
          <div class="divider"></div>
          <div class="reason-title">Why this fits:</div>
          <div>{narrative}</div>
        </div>
        """)

        with cols[idx]:
            st.markdown(card_html, unsafe_allow_html=True)

            # Detailed reasons
            with st.expander("Show detailed reasons"):
                for r in meta["reasons"]:
                    st.markdown(f"- {r}")
                st.markdown(f"- Estimated required speed: **~{demand['required_down']} Mbps** (upload ≥ {demand['required_up']} Mbps)")
                mesh = MESH_GUIDE.get(demand["size"])
                if mesh:
                    st.markdown(f"- Wi-Fi coverage tip: {mesh['copy']}")

            # Cost comparison
            with st.expander("Cost comparison (bundle vs à la carte)"):
                st.markdown(f"**À la carte total:** ${cost['alacarte_total']}/mo")
                st.markdown(
                    f"- Internet ({demand['required_down']} Mbps need): ${cost['internet_price']}/mo  \n"
                    f"- Mobile ({demand['mobile_lines_need']} line(s)): ${cost['mobile_price']}/mo  \n"
                    f"- TV{'' if cost['tv_price'] else ' (not selected)'}: ${cost['tv_price']}/mo"
                )
                st.markdown("---")
                st.markdown(f"**Your bundle total:** ${cost['bundle_total']}/mo")
                st.markdown(
                    f"- Base plan: ${plan.base_price}/mo  \n"
                    f"- Internet bundle credit: -${cost['bundle_internet_credit']}/mo  \n"
                    f"- Extra mobile (bundle rate ${BUNDLE_MOBILE_PER_LINE}/line): ${cost['bundle_extra_mobile']}/mo  \n"
                    f"- TV at bundle pricing: ${cost['bundle_tv_addons']}/mo"
                )
                st.markdown("---")
                st.markdown(f"**Estimated savings:** **${savings}/mo**")


    # -------------------------------
    # Chatbot (hybrid: LLM + math tools)
    # -------------------------------

    POST_PROMO_DELTA = 20  # $/mo placeholder increase after 12 months (tune or load from CMS)

    # Keep a tiny chat history in session (optional)
    if "chat" not in st.session_state:
        st.session_state.chat = []

    def _clone_with_overrides(base: Dict[str, Any], txt: str) -> Dict[str, Any]:
        """Very light NL parser for common 'what-if' tweaks. Returns a new responses dict."""
        out = json.loads(json.dumps(base))  # deep-ish copy
        t = txt.lower()

        # mobile lines
        import re
        m = re.search(r'(\d+)\s*line', t)
        if m:
            n = int(m.group(1))
            if   n <= 1: out["mobile_lines"] = "1 line (~$55/month)"
            elif n == 2: out["mobile_lines"] = "2 lines (~$45/line per month)"
            elif n == 3: out["mobile_lines"] = "3 lines (~$40/line per month)"
            else:        out["mobile_lines"] = "4+ lines (~$35/line per month)"

        # toggle TV
        if any(k in t for k in ["add tv", "include tv", "tv yes", "cable tv"]):
            out["tv_interest"] = "Yes, definitely"
        if any(k in t for k in ["remove tv", "no tv", "streaming only"]):
            out["tv_interest"] = "No, streaming only"

        # you can add more tweaks (devices/rooms) the same way if desired
        return out

    def _format_delta(old_cost: Dict[str, Any], new_cost: Dict[str, Any]) -> str:
        d = int(round(new_cost["bundle_total"] - old_cost["bundle_total"]))
        if d == 0:
            return "The monthly price stays about the same."
        if d > 0:
            return f"The monthly price would increase by **${d}/mo**."
        return f"The monthly price would decrease by **${abs(d)}/mo**."

    def _post_promo_note(plan_price: int) -> str:
        # Simple, explicit placeholder (so we don't overpromise)
        est_after = plan_price + POST_PROMO_DELTA
        return (
            f"Your selections show a **first-12-months** price of **${plan_price}/mo**. "
            f"We don’t have standard rates in this demo, so using a placeholder **+${POST_PROMO_DELTA}/mo** after month 12, "
            f"the bill would be about **${est_after}/mo**. Check the latest official pricing for exact post-promo rates."
        )

    def _policy_note() -> str:
        return (
            "This demo doesn’t include contract or trial policy data. Many ISPs offer promo pricing for the first 12 months; "
            "some plans are month-to-month, others may require a term agreement; trial/return windows vary. "
            "We can show pricing impacts, but for legal terms please check the official plan details or a sales rep."
        )

    def _wrap_with_llm(prompt_text: str) -> str:
        """Optional: polish the reply with Claude; fallback to plain text."""
        if anthropic_client is None:
            return prompt_text
        try:
            resp = anthropic_client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=250,
                temperature=0.3,
                system=(
                    "You are a concise, factual ISP helper. Answer clearly in 1–3 short paragraphs. "
                    "When dollar amounts are given in the prompt, keep them unchanged. "
                    "Avoid making up legal terms or guarantees."
                ),
                messages=[{"role": "user", "content": prompt_text}],
            )
            for blk in getattr(resp, "content", []):
                if getattr(blk, "type", "") == "text":
                    return blk.text.strip() or prompt_text
            return prompt_text
        except Exception:
            return prompt_text

    def answer_chat(user_text: str) -> str:
        """
        Handles (A) 'what if' price changes by re-running the model with overrides,
        and (B) generic policy questions with safe notes.
        """
        t = user_text.lower()

        # Current "best match" baseline (first card)
        base_plan, base_meta, base_cost = cards[0]["plan"], cards[0]["meta"], cards[0]["cost"]

        # (B) Policy questions first
        if "after 12 months" in t or "12 months" in t or "year" in t:
            raw = _post_promo_note(base_plan.base_price)
            return _wrap_with_llm(raw)

        if "lock" in t or "contract" in t or "trial" in t or "cancel" in t or "money back" in t:
            return _wrap_with_llm(_policy_note())

        # (A) What-if tweaks → recompute
        new_responses = _clone_with_overrides(st.session_state.responses, user_text)
        new_ranked, new_demand = rank_plans(new_responses)

        if not new_ranked:
            return "I couldn’t compute that scenario—try rephrasing or changing a single thing at a time."

        new_plan, new_score, new_meta = new_ranked[0]
        new_cost = bundle_vs_alacarte(new_plan, new_demand)

        # Build a crisp, numeric answer we can hand to the LLM to phrase nicely
        delta_text = _format_delta(base_cost, new_cost)
        want_tv = new_demand.get("tv_interest") in ["Yes, definitely", "Maybe, show me options"]

        raw = (
            f"Scenario: {user_text}\n\n"
            f"New best match: **{new_plan.name}** at **${new_plan.base_price}/mo** (first 12 months).\n"
            f"- Estimated bundle total this scenario: **${new_cost['bundle_total']}/mo**\n"
            f"- À la carte estimate: **${new_cost['alacarte_total']}/mo**\n"
            f"- Estimated savings vs à la carte: **${int(round(new_cost['savings']))}/mo**\n"
            f"- TV selected: **{'Yes' if want_tv else 'No'}**; Mobile lines: **{new_demand['mobile_lines_need']}**\n\n"
            f"{delta_text}\n\n"
            f"If you like, I can also compare the top three plans under this scenario."
        )
        return _wrap_with_llm(raw)

    # --- UI ---
    st.markdown("---")
    st.subheader("💬 Ask the Chatbot")

    # show last few messages
    for role, msg in st.session_state.chat[-6:]:
        st.chat_message(role).write(msg)

    user_input = st.chat_input("Ask me anything about your internet needs…")
    if user_input:
        st.session_state.chat.append(("user", user_input))
        reply = answer_chat(user_input)
        st.session_state.chat.append(("assistant", reply))
        st.chat_message("user").write(user_input)
        st.chat_message("assistant").write(reply)
