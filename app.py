import streamlit as st
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
from textwrap import dedent

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

# =========================
# Demand Estimation & Scoring
# =========================
def estimate_demand(resp: Dict[str, Any]) -> Dict[str, Any]:
    """Roughly estimate required Mbps and flags from responses."""
    # People
    people = resp.get("household", {}).get("people", "Just me")
    ppl_map = {"Just me":1, "2 people":2, "3–4 people":4, "5+ people":5}
    n_people = ppl_map.get(people, 1)

    peak = set(resp.get("evening", []))
    reliability_text = resp.get("reliability", "Moderate")
    devices_choice = resp.get("devices", "1–5 devices")
    size = resp.get("home_size", "Small (1–2 bedrooms)")
    tv_interest = resp.get("tv_interest", "No, streaming only")
    tv_prefs = set(resp.get("tv_prefs", []))
    streaming_now = resp.get("streaming", "No")
    lines_choice = resp.get("mobile_lines", "1 line (~$55/month)")

    # Device counts
    dev_map = {"1–5 devices":5, "6–10 devices":10, "11–15 devices":15, "15+ devices":20}
    n_devices = dev_map.get(devices_choice, 5)

    # Base Mbps per person for typical mixed use (light browsing etc.)
    base_per_person = 5

    # Per-activity estimates (concurrent peak)
    est = base_per_person * n_people
    if "Streaming video (Netflix, YouTube, etc.)" in peak:
        est += 12 * min(n_people, 3)        # assume HD streams at peak
    if "Online gaming" in peak:
        est += 5                            # bandwidth small, but latency matters
    if "Video calls/conferencing" in peak:
        est += 6 * min(n_people, 3)         # 720p calls
    if "Multiple people doing different things at once" in peak:
        est += 10                           # concurrency overhead
    if "Downloading large files" in peak:
        est += 50                           # bursts
    if "Smart home devices actively used" in peak:
        est += 3                            # telemetry overhead

    # Reliability / latency flags
    needs_low_latency = ("Online gaming" in peak) or reliability_text.startswith("Critical")
    high_reliability = reliability_text in ["Critical (work from home) – I need guaranteed uptime", "Very important"]

    # Safety buffer
    required_down = max(50, int(est * 1.25))
    required_up = 10 if high_reliability else 5

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

def score_plan(plan: Plan, d: Dict[str, Any], resp: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    """Return (score, reasons). Higher is better."""
    reasons = []
    score = 0.0

    # 1) Must roughly meet speed
    headroom = plan.down_mbps / max(1, d["required_down"])
    if headroom < 0.8:
        return -1e9, {"reasons": ["Not enough speed for your household demand."], "headroom": headroom}  # reject
    # speed contribution
    speed_points = min(40, 25 * headroom)  # diminishing returns
    score += speed_points
    reasons.append(f"Speed headroom ~{headroom:.1f}× your estimated need.")

    # 2) Upload & tech preference for low latency / reliability
    if d["needs_low_latency"] or d["high_reliability"]:
        if plan.tech == "fiber":
            score += 15
            reasons.append("Fiber tech helps with low latency & reliability.")
        else:
            score += 5
            reasons.append("Meets needs, though fiber would be even better.")

    # 3) TV fit
    want_tv = d["tv_interest"] in ["Yes, definitely", "Maybe, show me options"]
    if want_tv:
        if plan.includes_tv:
            score += 10
            reasons.append("Includes TV service as requested.")
            # match packs
            prefs = d["tv_prefs"]
            matched = [p for p in plan.tv_packs if (
                (p=="sports" and "Live Sports (ESPN, Fox Sports, etc.)" in prefs) or
                (p=="kids" and "Kids & Family (Disney, Nickelodeon, Cartoon Network)" in prefs) or
                (p=="premium" and "Premium channels (HBO, Showtime, Starz)" in prefs) or
                (p=="intl" and "International/Spanish language" in prefs) or
                (p=="news" and "News (CNN, Fox News, MSNBC, etc.)" in prefs) or
                (p=="entertainment" and "Movies & Entertainment (TNT, USA, TBS, etc.)" in prefs)
            )]
            score += 3 * len(matched)
            if matched:
                reasons.append(f"TV packs lined up with your interests: {', '.join(matched)}.")
        else:
            score -= 10
            reasons.append("Does not include TV; you asked to see TV options.")
    else:
        if plan.includes_tv:
            score -= 6
            reasons.append("Includes TV you may not need (streaming-only choice).")

    # 4) Mobile bundle fit
    need_lines = d["mobile_lines_need"]
    if plan.mobile_lines_included >= 1:
        # modest bonus if lines align
        if plan.mobile_lines_included >= min(need_lines, 2):
            score += 8
            reasons.append(f"Includes {plan.mobile_lines_included} mobile line(s) to offset phone bill.")
        else:
            score += 3
            reasons.append("Includes some mobile lines (you can add more if needed).")

    # 5) Price efficiency
    # Reward cheaper plans that still meet needs
    value_points = max(0, 40 - (plan.base_price / 5))  # cheaper -> more points
    score += value_points
    reasons.append(f"Good value for price (${plan.base_price}/mo).")

    # 6) Router/mesh guidance (informational; not scored heavily)
    mesh = MESH_GUIDE.get(d["size"], {"nodes":1, "copy":""})
    if mesh["nodes"] >= 2 and plan.includes_router:
        reasons.append(f"Consider {mesh['nodes']}-node mesh for {d['size'].lower()}.")

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


# =========================
# Optional LLM narration hook
# =========================
def generate_narrative(plan: Plan, demand: Dict[str, Any], reasons: List[str]) -> str:
    """
    Returns a concise 'why this fits' paragraph using deterministic logic.
    Swap this function to call an LLM later if you want richer copy.
    """
    bits = []
    if demand["high_reliability"]:
        bits.append("reliable connection for work-from-home")
    if demand["needs_low_latency"]:
        bits.append("low-latency performance for gaming/calls")
    bits.append(f"{plan.down_mbps} Mbps download")
    if plan.includes_tv:
        bits.append("TV service included")
    if plan.mobile_lines_included:
        bits.append(f"{plan.mobile_lines_included} mobile line(s) bundled")
    return ("; ".join(bits) + ". ").capitalize() + " " + " ".join(reasons[:2])


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

    # Show Top 3
    top3 = ranked[:3]
    cols = st.columns(3) if len(top3) == 3 else [st.container() for _ in top3]
    for idx, (plan, score, meta) in enumerate(top3):
        is_best = (idx == 0)

        # Badge and list lines
        badge_html = '<div class="plan-badge">BEST MATCH</div>' if is_best else ""
        tv_line    = f"Includes TV ({', '.join(plan.tv_packs)} packs)" if plan.includes_tv else "Internet only"
        dvr_line   = "DVR included" if plan.dvr_included else ""
        lines_line = f"{plan.mobile_lines_included} mobile line(s) included" if plan.mobile_lines_included else ""

        # Build the bullet list as pure HTML (no leading spaces)
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

        narrative = generate_narrative(plan, demand, meta["reasons"])

        # One flat HTML block (no indentation so Markdown won't code-block it)
        card_html = dedent(f"""\
    <div class="plan-card {'best' if is_best else ''}">
    {badge_html}
    <h3 class="plan-title">{plan.name}</h3>
    <div class="plan-price">${plan.base_price}/month <span style="font-size:12px;color:#666">(first 12 months)</span></div>
    {meta_list_html}
    <div class="divider"></div>
    <div class="reason-title">Why this fits:</div>
    <div>{narrative}</div>
    </div>
    """)

        with cols[idx]:
            st.markdown(card_html, unsafe_allow_html=True)

            # Optional details below the card
            with st.expander("Show detailed reasons"):
                for r in meta["reasons"]:
                    st.markdown(f"- {r}")
                st.markdown(f"- Estimated required speed: **~{demand['required_down']} Mbps** (upload ≥ {demand['required_up']} Mbps)")
                mesh = MESH_GUIDE.get(demand["size"])
                if mesh:
                    st.markdown(f"- Wi-Fi coverage tip: {mesh['copy']}")

            if plan.notes:
                with st.expander("What's included / promos"):
                    for n in plan.notes:
                        st.markdown(f"- {n}")


    st.markdown("---")
    st.subheader("💬 Ask the Chatbot")
    user_input = st.chat_input("Ask me anything about your internet needs...")
    if user_input:
        st.chat_message("user").write(user_input)
        st.chat_message("assistant").write("This is a placeholder response. To generate custom marketing copy, wire this to your LLM in `generate_narrative()`.")
