from datetime import date

import pandas as pd
import streamlit as st

import neo4j_service as svc

st.set_page_config(page_title="Sandal Recommendation", page_icon="🩴", layout="wide")


@st.cache_data(ttl=300, show_spinner=False)
def load(fn_name: str, *args) -> pd.DataFrame:
    return pd.DataFrame(getattr(svc, fn_name)(*args))


def build_dot(me_name, watched, friends, recs):
    watched_set = set(watched["brand"]) if not watched.empty else set()
    rec_set = set(recs["brand"]) if not recs.empty else set()
    lines = [
        "digraph G {", "rankdir=LR; node [fontname=Helvetica];",
        f'"{me_name}" [shape=ellipse, style=filled, fillcolor="#FFD166"];',
    ]
    for b in watched_set:
        lines.append(f'"{b}" [shape=box, style=filled, fillcolor="#CDE7FF"];')
        lines.append(f'"{me_name}" -> "{b}" [label="WATCHED", color="#1F77B4"];')
    if not friends.empty:
        for fname in friends["friend"].unique():
            lines.append(f'"{fname}" [shape=ellipse, style=filled, fillcolor="#EEEEEE"];')
            lines.append(f'"{me_name}" -> "{fname}" [label="FRIEND_OF", dir=none];')
        for _, row in friends.dropna(subset=["sandal"]).iterrows():
            b = row["sandal"]
            if b not in watched_set:
                color = "#C8F7C5" if b in rec_set else "#FFFFFF"
                lines.append(f'"{b}" [shape=box, style=filled, fillcolor="{color}"];')
            lines.append(f'"{row["friend"]}" -> "{b}" [label="WATCHED", color="#888888"];')
    lines.append("}")
    return "\n".join(lines)


st.title("🩴 Sandal Recommendation System")
st.caption("แนะนำรองเท้าแตะจากยี่ห้อที่เพื่อนเคยดู โดยใช้ Neo4j Graph Database")

try:
    users = load("get_users")
except Exception as e:
    st.error(f"เชื่อมต่อ Neo4j ไม่สำเร็จ: {e}")
    st.stop()

if users.empty:
    st.warning("ยังไม่มีข้อมูลในฐานข้อมูล")
    if st.button("โหลดข้อมูลตัวอย่าง"):
        svc.seed_demo_data()
        st.cache_data.clear()
        st.rerun()
    st.stop()

with st.sidebar:
    st.header("เลือกผู้ใช้")
    options = dict(zip(users["user_id"], users["name"]))
    user_id = st.selectbox("User", list(options), format_func=lambda uid: f"{options[uid]} ({uid})")
    top_n = st.slider("จำนวนรายการแนะนำสูงสุด", 1, 10, 5)

    with st.expander("➕ บันทึกการดูรองเท้าแตะ"):
        sandals = load("get_sandals")
        sid = st.selectbox(
            "ยี่ห้อ", sandals["sandal_id"],
            format_func=lambda x: sandals.set_index("sandal_id").loc[x, "brand"],
        )
        d = st.date_input("วันที่ดู", value=date.today())
        if st.button("บันทึก"):
            if svc.record_watch(user_id, sid, d.isoformat()):
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("ไม่พบ User หรือ Sandal")

    if st.button("🔄 รีเฟรชข้อมูล"):
        st.cache_data.clear()
        st.rerun()

me = options[user_id]
recs = load("recommend_sandals", user_id, top_n)
watched = load("get_watched", user_id)
friends = load("get_friends", user_id)

c1, c2, c3 = st.columns(3)
c1.metric("เพื่อน", friends["friend_id"].nunique() if not friends.empty else 0)
c2.metric("ยี่ห้อที่เคยดู", len(watched))
c3.metric("รายการแนะนำ", len(recs))

tab_rec, tab_hist, tab_graph, tab_pop = st.tabs(["🎯 แนะนำ", "👀 ประวัติการดู", "🕸️ กราฟ", "📊 ความนิยม"])

with tab_rec:
    st.subheader(f"รองเท้าแตะที่แนะนำสำหรับ {me}")
    if recs.empty:
        st.info("ยังไม่มีรายการแนะนำ (เพื่อนยังไม่ได้ดูยี่ห้อที่ผู้ใช้ยังไม่เคยดู)")
    else:
        for _, r in recs.iterrows():
            with st.container(border=True):
                a, b = st.columns([3, 1])
                a.markdown(f"**{r['brand']}**  \nเพื่อนที่เคยดู: {', '.join(r['friends'])}")
                b.metric("friend_score", int(r["friend_score"]))
        st.bar_chart(recs.set_index("brand")["friend_score"])

with tab_hist:
    st.subheader(f"ประวัติการดูของ {me}")
    if watched.empty:
        st.info("ผู้ใช้นี้ยังไม่เคยดูรองเท้าแตะ")
    else:
        st.dataframe(watched, use_container_width=True, hide_index=True)

with tab_graph:
    st.subheader(f"เครือข่ายของ {me}")
    st.caption("ส้ม = ผู้ใช้ | เทา = เพื่อน | ฟ้า = ที่ผู้ใช้เคยดู | เขียว = ที่ระบบแนะนำ")
    st.graphviz_chart(build_dot(me, watched, friends, recs), use_container_width=True)

with tab_pop:
    st.subheader("ยี่ห้อที่ถูกดูมากที่สุด")
    pop = load("get_popularity")
    st.bar_chart(pop.set_index("brand")["watch_count"])
    st.dataframe(pop, use_container_width=True, hide_index=True)
