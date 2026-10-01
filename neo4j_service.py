from __future__ import annotations

from typing import Any

import streamlit as st
from neo4j import GraphDatabase, RoutingControl


def _config() -> tuple[str, str, str, str | None]:
    cfg = st.secrets["neo4j"]
    # database เป็น optional: ถ้าไม่ระบุ driver จะใช้ home database ของ instance
    return cfg["uri"], cfg["username"], cfg["password"], cfg.get("database")


@st.cache_resource(show_spinner=False)
def get_driver():
    """Create one thread-safe Neo4j Driver for the Streamlit process."""
    uri, username, password, _ = _config()
    driver = GraphDatabase.driver(uri, auth=(username, password))
    driver.verify_connectivity()
    return driver


def query(cypher: str, parameters: dict[str, Any] | None = None, *, write: bool = False) -> list[dict[str, Any]]:
    """Execute parameterized Cypher and return rows as dictionaries."""
    _, _, _, database = _config()
    records, _, _ = get_driver().execute_query(
        cypher,
        parameters_=parameters or {},
        database_=database,
        routing_=RoutingControl.WRITE if write else RoutingControl.READ,
    )
    return [record.data() for record in records]


def ping() -> bool:
    rows = query("RETURN 1 AS ok")
    return bool(rows and rows[0]["ok"] == 1)


# ---------------------------------------------------------------- schema / seed
def create_schema() -> None:
    for stmt in [
        "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE",
        "CREATE CONSTRAINT sandal_id_unique IF NOT EXISTS FOR (a:Sandal) REQUIRE a.sandal_id IS UNIQUE",
    ]:
        query(stmt, write=True)


def seed_demo_data() -> None:
    """Idempotent sample dataset from the README: safe to run more than once."""
    create_schema()

    users = [
        {"user_id": f"U{i:03d}", "name": n}
        for i, n in enumerate(
            ["Kong", "Fah", "Ploy", "Beam", "Now", "Gap", "Ohm", "Tar", "Mild", "Ice"], start=1
        )
    ]
    sandals = [
        {"sandal_id": f"A{i:03d}", "brand": b}
        for i, b in enumerate(
            ["Havaianas", "Birkenstock", "Crocs", "Teva", "Rainbow Sandals",
             "Reef", "Ipanema", "Chaco", "OluKai", "Fitflop"],
            start=1,
        )
    ]
    friendships = [
        ["U001", "U002"], ["U001", "U003"], ["U001", "U004"], ["U002", "U005"],
        ["U002", "U006"], ["U003", "U007"], ["U003", "U008"], ["U004", "U009"],
        ["U004", "U010"], ["U005", "U006"], ["U007", "U008"], ["U009", "U010"],
    ]
    watched = [
        ["U001", "A001", "2026-09-01"], ["U001", "A003", "2026-09-02"],
        ["U002", "A002", "2026-09-03"], ["U002", "A003", "2026-09-04"],
        ["U003", "A003", "2026-09-05"], ["U003", "A004", "2026-09-06"],
        ["U004", "A005", "2026-09-07"], ["U005", "A006", "2026-09-08"],
        ["U006", "A007", "2026-09-09"], ["U007", "A008", "2026-09-10"],
        ["U008", "A009", "2026-09-11"], ["U009", "A010", "2026-09-12"],
        ["U010", "A001", "2026-09-13"],
    ]

    query(
        "UNWIND $rows AS row MERGE (u:User {user_id: row.user_id}) SET u.name = row.name",
        {"rows": users}, write=True,
    )
    query(
        "UNWIND $rows AS row MERGE (a:Sandal {sandal_id: row.sandal_id}) SET a.brand = row.brand",
        {"rows": sandals}, write=True,
    )
    query(
        """
        UNWIND $rows AS row
        MATCH (a:User {user_id: row[0]}), (b:User {user_id: row[1]})
        MERGE (a)-[:FRIEND_OF]->(b)
        """,
        {"rows": friendships}, write=True,
    )
    query(
        """
        UNWIND $rows AS row
        MATCH (u:User {user_id: row[0]}), (a:Sandal {sandal_id: row[1]})
        MERGE (u)-[r:WATCHED]->(a)
        SET r.watch_date = date(row[2])
        """,
        {"rows": watched}, write=True,
    )


# ---------------------------------------------------------------- reads
def get_users() -> list[dict[str, Any]]:
    return query("MATCH (u:User) RETURN u.user_id AS user_id, u.name AS name ORDER BY user_id")


def get_sandals() -> list[dict[str, Any]]:
    return query("MATCH (a:Sandal) RETURN a.sandal_id AS sandal_id, a.brand AS brand ORDER BY brand")


def get_dashboard_metrics() -> dict[str, int]:
    # COUNT {} subquery: ยังคืนค่า 0 ได้แม้ยังไม่มี relationship (แบบ MATCH ต่อกันจะได้ 0 แถว)
    rows = query(
        """
        RETURN COUNT { (:User) } AS users,
               COUNT { (:Sandal) } AS sandals,
               COUNT { ()-[:WATCHED]->() } AS watches,
               COUNT { ()-[:FRIEND_OF]->() } AS friendships
        """
    )
    return rows[0] if rows else {"users": 0, "sandals": 0, "watches": 0, "friendships": 0}


def get_watched(user_id: str) -> list[dict[str, Any]]:
    return query(
        """
        MATCH (:User {user_id:$user_id})-[r:WATCHED]->(a:Sandal)
        RETURN a.sandal_id AS sandal_id, a.brand AS brand, toString(r.watch_date) AS watch_date
        ORDER BY watch_date
        """,
        {"user_id": user_id},
    )


def get_friends(user_id: str) -> list[dict[str, Any]]:
    """One row per (friend, sandal the friend watched); sandal is None if none."""
    return query(
        """
        MATCH (:User {user_id:$user_id})-[:FRIEND_OF]-(f:User)
        OPTIONAL MATCH (f)-[:WATCHED]->(s:Sandal)
        RETURN f.user_id AS friend_id, f.name AS friend, s.brand AS sandal
        ORDER BY friend, sandal
        """,
        {"user_id": user_id},
    )


def recommend_sandals(user_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """friend_score = จำนวนเพื่อนที่เคยดู; popularity ใช้ตัดสินเมื่อคะแนนเท่ากัน."""
    return query(
        """
        MATCH (me:User {user_id:$user_id})-[:FRIEND_OF]-(friend:User)-[:WATCHED]->(s:Sandal)
        WHERE NOT EXISTS { (me)-[:WATCHED]->(s) }
        WITH s, count(DISTINCT friend) AS friend_score, collect(DISTINCT friend.name) AS friends
        OPTIONAL MATCH (:User)-[w:WATCHED]->(s)
        RETURN s.sandal_id AS sandal_id, s.brand AS brand,
               friend_score, friends, count(w) AS popularity
        ORDER BY friend_score DESC, popularity DESC, brand
        LIMIT $limit
        """,
        {"user_id": user_id, "limit": int(limit)},
    )


def get_popularity() -> list[dict[str, Any]]:
    return query(
        """
        MATCH (a:Sandal)
        OPTIONAL MATCH (:User)-[w:WATCHED]->(a)
        RETURN a.brand AS brand, count(w) AS watch_count
        ORDER BY watch_count DESC, brand
        """
    )


def search_sandals(keyword: str = "") -> list[dict[str, Any]]:
    return query(
        """
        MATCH (a:Sandal)
        WHERE $keyword = '' OR toLower(a.brand) CONTAINS toLower($keyword)
        RETURN a.sandal_id AS sandal_id, a.brand AS brand
        ORDER BY brand
        """,
        {"keyword": keyword.strip()},
    )


# ---------------------------------------------------------------- writes
def record_watch(user_id: str, sandal_id: str, watch_date: str) -> bool:
    """Create/update a WATCHED relationship. Returns False if user or sandal doesn't exist."""
    rows = query(
        """
        MATCH (u:User {user_id:$user_id}), (a:Sandal {sandal_id:$sandal_id})
        MERGE (u)-[r:WATCHED]->(a)
        SET r.watch_date = date($watch_date)
        RETURN count(r) AS n
        """,
        {"user_id": user_id, "sandal_id": sandal_id, "watch_date": watch_date},
        write=True,
    )
    return bool(rows and rows[0]["n"])
