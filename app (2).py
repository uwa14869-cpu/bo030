import pandas as pd
import streamlit as st
from neo4j import GraphDatabase

st.set_page_config(page_title="Sandal Recommendation", page_icon="🩴", layout="wide")


# ---------- Neo4j connection ----------
@st.cache_resource
def get_driver():
    driver = GraphDatabase.driver(
        st.secrets["NEO4J_URI"],
        auth=(st.secrets["NEO4J_USERNAME"], st.secrets["NEO4J_PASSWORD"]),
    )
    driver.verify_connectivity()
    return driver


@st.cache_data(ttl=300, show_spinner=False)
def run_query(query: str, params: dict | None = None) -> pd.DataFrame:
    result = get_driver().execute_query(
        query,
        params or {},
        database_=st.secrets.get("NEO4J_DATABASE"),  # None = home database
    )
    return pd.DataFrame([r.data() for r in result.records])


# ---------- Queries ----------
def get_users():
    return run_query(
        "MATCH (u:User) RETURN u.user_id AS user_id, u.name AS name ORDER BY user_id"
    )


def get_recommendations(user_id):
    return run_query(
        """
        MATCH (me:User {user_id:$user_id})-[:FRIEND_OF]-(friend:User)
              -[:WATCHED]->(sandal:Sandal)
        WHERE NOT EXISTS { MATCH (me)-[:WATCHED]->(sandal) }
        RETURN sandal.sandal_id AS sandal_id,
               sandal.brand AS brand,
               count(DISTINCT friend) AS friend_score,
               collect(DISTINCT friend.name) AS friends
        ORDER BY friend_score DESC, brand
        """,
        {"user_id": user_id},
    )


def get_watched(user_id):
    return run_query(
        """
        MATCH (:User {user_id:$user_id})-[r:WATCHED]->(a:Sandal)
        RETURN a.sandal_id AS sandal_id, a.brand AS brand,
               toString(r.watch_date) AS watch_date
        ORDER BY watch_date
        """,
        {"user_id": user_id},
    )


def get_friends(user_id):
    return run_query(
        """
        MATCH (:User {user_id:$user_id})-[:FRIEND_OF]-(f:User)
        OPTIONAL MATCH (f)-[:WATCHED]->(s:Sandal)
        RETURN f.user_id AS friend_id, f.name AS friend,
               s.brand AS sandal
        ORDER BY friend, sandal
        """,
        {"user_id": user_id},
    )


def get_popularity():
    return run_query(
        """
        MATCH (a:Sandal)
        OPTIONAL MATCH (:User)-[w:WATCHED]->(a)
        RETURN a.brand AS brand, count(w) AS watch_count
        ORDER BY watch_count DESC, brand
        """
    )


# ---------- Graph visualisation (Graphviz DOT) ----------
def build_dot(me_name, watched, friends, recs):
    watched_set = set(watched["brand"]) if not watched.empty else set()
    rec_set = set(recs["brand"]) if not recs.empty else set()
    lines = [
        "digraph G {",
        "rankdir=LR; node [fontname=Helvetica];",
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


# ---------- UI ----------
st.title("🩴 Sandal Recommendation System")
st.caption("แนะนำรองเท้าแตะจากยี่ห้อที่เพื่อนเคยดู โดยใช้ Neo4j Graph Database")

try:
    users = get_users()
except Exception as e:
    st.error(f"เชื่อมต่อ Neo4j ไม่สำเร็จ: {e}")
    st.stop()

if users.empty:
    st.warning("ยังไม่มีข้อมูล User ในฐานข้อมูล กรุณารันสคริปต์โหลดข้อมูลใน Colab ก่อน")
    st.stop()

with st.sidebar:
    st.header("เลือกผู้ใช้")
    options = dict(zip(users["user_id"], users["name"]))
    user_id = st.selectbox(
        "User", list(options), format_func=lambda uid: f"{options[uid]} ({uid})"
    )
    top_n = st.slider("จำนวนรายการแนะนำสูงสุด", 1, 10, 5)
    if st.button("🔄 รีเฟรชข้อมูล"):
        st.cache_data.clear()
        st.rerun()

me = options[user_id]
recs = get_recommendations(user_id)
watched = get_watched(user_id)
friends = get_friends(user_id)

c1, c2, c3 = st.columns(3)
c1.metric("เพื่อน", friends["friend_id"].nunique() if not friends.empty else 0)
c2.metric("ยี่ห้อที่เคยดู", len(watched))
c3.metric("รายการแนะนำ", len(recs))

tab_rec, tab_hist, tab_graph, tab_pop = st.tabs(
    ["🎯 แนะนำ", "👀 ประวัติการดู", "🕸️ กราฟ", "📊 ความนิยม"]
)

with tab_rec:
    st.subheader(f"รองเท้าแตะที่แนะนำสำหรับ {me}")
    if recs.empty:
        st.info("ยังไม่มีรายการแนะนำ (เพื่อนยังไม่ได้ดูยี่ห้อที่ผู้ใช้ยังไม่เคยดู)")
    else:
        top = recs.head(top_n)
        for _, r in top.iterrows():
            with st.container(border=True):
                a, b = st.columns([3, 1])
                a.markdown(f"**{r['brand']}**  \nเพื่อนที่เคยดู: {', '.join(r['friends'])}")
                b.metric("friend_score", int(r["friend_score"]))
        st.bar_chart(top.set_index("brand")["friend_score"])

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
    if not friends.empty:
        with st.expander("ดูตารางเพื่อนและรองเท้าที่เพื่อนดู"):
            st.dataframe(friends, use_container_width=True, hide_index=True)

with tab_pop:
    st.subheader("ยี่ห้อที่ถูกดูมากที่สุด")
    pop = get_popularity()
    st.bar_chart(pop.set_index("brand")["watch_count"])
    st.dataframe(pop, use_container_width=True, hide_index=True)
