import json
import math
import os
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components
from geopy.distance import distance as geodesic_distance
from geopy.geocoders import Nominatim
from PIL import Image, ImageEnhance, ImageFilter


def read_secret(name: str, default: str = "") -> str:
    env_value = os.getenv(name)
    if env_value:
        return env_value

    try:
        secret_value = st.secrets.get(name)
    except Exception:
        secret_value = None

    if secret_value in {None, ""}:
        return default

    return str(secret_value)


st.set_page_config(
    page_title="Kevin Chou/SKC Realty Team 樓層真實視野模擬器",
    layout="wide",
)
st.title("🏢 Kevin Chou/SKC Realty Team 獨家：樓層真實視野模擬器")
st.markdown("輸入多倫多地址與樓層，優先輸出清楚可辨識的街景主圖，再附上俯視比例參考。")
st.caption(
    "這個版本不再把扭曲的 3D photogrammetry 當主畫面，而是優先輸出可驗證的靜態街景與俯視圖。"
)

GOOGLE_TILES_API_KEY = read_secret("GOOGLE_TILES_API_KEY", "")
ADMIN_ACCESS_CODE = read_secret("SKC_ADMIN_CODE", "")
DATABASE_URL = read_secret("DATABASE_URL", "")
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CUSTOMERS_FILE = DATA_DIR / "customers.json"
USAGE_LOG_FILE = DATA_DIR / "usage_log.jsonl"


def ensure_local_data_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CUSTOMERS_FILE.exists():
        CUSTOMERS_FILE.write_text("{}\n", encoding="utf-8")
    if not USAGE_LOG_FILE.exists():
        USAGE_LOG_FILE.write_text("", encoding="utf-8")


def read_json_file(path: Path, default: dict | list):
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json_file(path: Path, payload: dict | list) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def sanitize_customer_id(raw_value: str) -> str:
    cleaned = "".join(
        char.lower()
        for char in raw_value.strip()
        if char.isalnum() or char in {"-", "_"}
    )
    return cleaned[:64]


def load_local_customers() -> dict:
    ensure_local_data_store()
    payload = read_json_file(CUSTOMERS_FILE, {})
    return payload if isinstance(payload, dict) else {}


def save_local_customers(customers: dict) -> None:
    ensure_local_data_store()
    write_json_file(CUSTOMERS_FILE, customers)


def upsert_local_customer(customer_id: str, *, customer_name: str = "") -> dict:
    customers = load_local_customers()
    now_iso = datetime.now(timezone.utc).isoformat()
    existing = customers.get(customer_id)

    if not existing:
        customers[customer_id] = {
            "customer_id": customer_id,
            "customer_name": customer_name.strip(),
            "active": True,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        save_local_customers(customers)
        return customers[customer_id]

    updated = False
    cleaned_name = customer_name.strip()
    if cleaned_name and cleaned_name != existing.get("customer_name", ""):
        existing["customer_name"] = cleaned_name
        updated = True

    if updated:
        existing["updated_at"] = now_iso
        customers[customer_id] = existing
        save_local_customers(customers)

    return existing


def set_local_customer_active(customer_id: str, is_active: bool) -> dict | None:
    customers = load_local_customers()
    customer = customers.get(customer_id)
    if not customer:
        return None

    customer["active"] = is_active
    customer["updated_at"] = datetime.now(timezone.utc).isoformat()
    customers[customer_id] = customer
    save_local_customers(customers)
    return customer


def append_local_usage_event(customer_id: str, event_type: str, metadata: dict | None = None) -> None:
    ensure_local_data_store()
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "customer_id": customer_id,
        "event_type": event_type,
        "metadata": metadata or {},
    }
    with USAGE_LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_local_usage_events() -> list[dict]:
    ensure_local_data_store()
    events: list[dict] = []
    for line in USAGE_LOG_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def build_local_usage_rows() -> list[dict]:
    customers = load_local_customers()
    events = load_local_usage_events()
    rows: list[dict] = []

    for customer_id, customer in customers.items():
        customer_events = [event for event in events if event.get("customer_id") == customer_id]
        preview_events = [
            event for event in customer_events if event.get("event_type") == "preview_rendered"
        ]
        blocked_events = [
            event for event in customer_events if event.get("event_type") == "paused_blocked"
        ]
        last_seen = customer_events[-1]["timestamp"] if customer_events else "-"
        rows.append(
            {
                "customer_id": customer_id,
                "customer_name": customer.get("customer_name", ""),
                "status": "active" if customer.get("active", True) else "paused",
                "total_events": len(customer_events),
                "preview_events": len(preview_events),
                "blocked_events": len(blocked_events),
                "last_seen_utc": last_seen,
            }
        )

    rows.sort(key=lambda item: item["customer_id"])
    return rows


def load_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        return None, None
    return psycopg, dict_row


def open_database_connection():
    psycopg, dict_row = load_psycopg()
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    if psycopg is None or dict_row is None:
        raise RuntimeError("psycopg is not installed.")

    connection = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    connection.autocommit = True
    return connection


def ensure_cloud_schema() -> None:
    with open_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id TEXT PRIMARY KEY,
                    customer_name TEXT NOT NULL DEFAULT '',
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id BIGSERIAL PRIMARY KEY,
                    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    customer_id TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_usage_events_customer_time
                ON usage_events (customer_id, occurred_at DESC)
                """
            )


def load_cloud_customers() -> dict:
    customers: dict = {}
    with open_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT customer_id, customer_name, active, created_at, updated_at
                FROM customers
                ORDER BY customer_id
                """
            )
            for row in cursor.fetchall():
                customers[row["customer_id"]] = {
                    "customer_id": row["customer_id"],
                    "customer_name": row["customer_name"] or "",
                    "active": bool(row["active"]),
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat(),
                }
    return customers


def upsert_cloud_customer(customer_id: str, *, customer_name: str = "") -> dict:
    cleaned_name = customer_name.strip()
    with open_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO customers (customer_id, customer_name, active)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (customer_id) DO UPDATE
                SET customer_name = CASE
                        WHEN EXCLUDED.customer_name <> ''
                        AND customers.customer_name <> EXCLUDED.customer_name
                        THEN EXCLUDED.customer_name
                        ELSE customers.customer_name
                    END,
                    updated_at = CASE
                        WHEN EXCLUDED.customer_name <> ''
                        AND customers.customer_name <> EXCLUDED.customer_name
                        THEN NOW()
                        ELSE customers.updated_at
                    END
                RETURNING customer_id, customer_name, active, created_at, updated_at
                """,
                (customer_id, cleaned_name),
            )
            row = cursor.fetchone()

    return {
        "customer_id": row["customer_id"],
        "customer_name": row["customer_name"] or "",
        "active": bool(row["active"]),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def set_cloud_customer_active(customer_id: str, is_active: bool) -> dict | None:
    with open_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE customers
                SET active = %s,
                    updated_at = NOW()
                WHERE customer_id = %s
                RETURNING customer_id, customer_name, active, created_at, updated_at
                """,
                (is_active, customer_id),
            )
            row = cursor.fetchone()

    if not row:
        return None

    return {
        "customer_id": row["customer_id"],
        "customer_name": row["customer_name"] or "",
        "active": bool(row["active"]),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def append_cloud_usage_event(customer_id: str, event_type: str, metadata: dict | None = None) -> None:
    metadata_payload = json.dumps(metadata or {}, ensure_ascii=False)

    with open_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO customers (customer_id, customer_name, active)
                VALUES (%s, '', TRUE)
                ON CONFLICT (customer_id) DO NOTHING
                """,
                (customer_id,),
            )
            cursor.execute(
                """
                INSERT INTO usage_events (customer_id, event_type, metadata_json)
                VALUES (%s, %s, %s::jsonb)
                """,
                (customer_id, event_type, metadata_payload),
            )


def load_cloud_usage_events() -> list[dict]:
    events: list[dict] = []
    with open_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT occurred_at, customer_id, event_type, metadata_json::text AS metadata_text
                FROM usage_events
                ORDER BY occurred_at
                """
            )
            for row in cursor.fetchall():
                try:
                    metadata = json.loads(row["metadata_text"])
                except json.JSONDecodeError:
                    metadata = {}
                events.append(
                    {
                        "timestamp": row["occurred_at"].isoformat(),
                        "customer_id": row["customer_id"],
                        "event_type": row["event_type"],
                        "metadata": metadata,
                    }
                )
    return events


def build_cloud_usage_rows() -> list[dict]:
    rows: list[dict] = []
    with open_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.customer_id,
                    c.customer_name,
                    c.active,
                    COUNT(e.id) AS total_events,
                    COUNT(*) FILTER (WHERE e.event_type = 'preview_rendered') AS preview_events,
                    COUNT(*) FILTER (WHERE e.event_type = 'paused_blocked') AS blocked_events,
                    MAX(e.occurred_at) AS last_seen_utc
                FROM customers c
                LEFT JOIN usage_events e
                    ON e.customer_id = c.customer_id
                GROUP BY c.customer_id, c.customer_name, c.active
                ORDER BY c.customer_id
                """
            )
            for row in cursor.fetchall():
                last_seen = row["last_seen_utc"].isoformat() if row["last_seen_utc"] else "-"
                rows.append(
                    {
                        "customer_id": row["customer_id"],
                        "customer_name": row["customer_name"] or "",
                        "status": "active" if row["active"] else "paused",
                        "total_events": int(row["total_events"] or 0),
                        "preview_events": int(row["preview_events"] or 0),
                        "blocked_events": int(row["blocked_events"] or 0),
                        "last_seen_utc": last_seen,
                    }
                )
    return rows


def seed_cloud_database_from_local_files() -> None:
    if not CUSTOMERS_FILE.exists() and not USAGE_LOG_FILE.exists():
        return

    local_customers = load_local_customers()
    local_events = load_local_usage_events()

    if not local_customers and not local_events:
        return

    with open_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM customers")
            customer_count = int(cursor.fetchone()["count"])
            cursor.execute("SELECT COUNT(*) AS count FROM usage_events")
            event_count = int(cursor.fetchone()["count"])

            if customer_count > 0 or event_count > 0:
                return

            for customer in local_customers.values():
                cursor.execute(
                    """
                    INSERT INTO customers (
                        customer_id,
                        customer_name,
                        active,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (customer_id) DO NOTHING
                    """,
                    (
                        customer.get("customer_id"),
                        customer.get("customer_name", ""),
                        customer.get("active", True),
                        customer.get("created_at") or datetime.now(timezone.utc).isoformat(),
                        customer.get("updated_at") or datetime.now(timezone.utc).isoformat(),
                    ),
                )

            for event in local_events:
                cursor.execute(
                    """
                    INSERT INTO usage_events (
                        occurred_at,
                        customer_id,
                        event_type,
                        metadata_json
                    )
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (
                        event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                        event.get("customer_id"),
                        event.get("event_type"),
                        json.dumps(event.get("metadata", {}), ensure_ascii=False),
                    ),
                )


def initialize_data_backend() -> tuple[str, str | None]:
    if not DATABASE_URL:
        ensure_local_data_store()
        return "local-json", None

    try:
        ensure_cloud_schema()
        seed_cloud_database_from_local_files()
        return "cloud-postgres", None
    except Exception as exc:
        ensure_local_data_store()
        return "local-json", f"Cloud database unavailable, fallback to local JSON: {exc}"


DATA_BACKEND_NAME, DATA_BACKEND_ERROR = initialize_data_backend()

st.caption(
    "Usage store: `cloud-postgres`。"
    if DATA_BACKEND_NAME == "cloud-postgres"
    else "Usage store: `local-json`。"
)
if DATA_BACKEND_ERROR:
    st.warning(DATA_BACKEND_ERROR)


def ensure_data_store() -> None:
    if DATA_BACKEND_NAME == "local-json":
        ensure_local_data_store()


def load_customers() -> dict:
    if DATA_BACKEND_NAME == "cloud-postgres":
        return load_cloud_customers()
    return load_local_customers()


def upsert_customer(customer_id: str, *, customer_name: str = "") -> dict:
    if DATA_BACKEND_NAME == "cloud-postgres":
        return upsert_cloud_customer(customer_id, customer_name=customer_name)
    return upsert_local_customer(customer_id, customer_name=customer_name)


def set_customer_active(customer_id: str, is_active: bool) -> dict | None:
    if DATA_BACKEND_NAME == "cloud-postgres":
        return set_cloud_customer_active(customer_id, is_active)
    return set_local_customer_active(customer_id, is_active)


def append_usage_event(customer_id: str, event_type: str, metadata: dict | None = None) -> None:
    if DATA_BACKEND_NAME == "cloud-postgres":
        append_cloud_usage_event(customer_id, event_type, metadata)
        return
    append_local_usage_event(customer_id, event_type, metadata)


def load_usage_events() -> list[dict]:
    if DATA_BACKEND_NAME == "cloud-postgres":
        return load_cloud_usage_events()
    return load_local_usage_events()


def build_customer_usage_rows() -> list[dict]:
    if DATA_BACKEND_NAME == "cloud-postgres":
        return build_cloud_usage_rows()
    return build_local_usage_rows()


def normalize_address(address: str) -> str:
    normalized = address.strip()
    if not normalized:
        return normalized

    lowered = normalized.lower()
    if "toronto" not in lowered:
        normalized = f"{normalized}, Toronto, Ontario, Canada"
    elif "canada" not in lowered:
        normalized = f"{normalized}, Canada"

    return normalized


@st.cache_data(show_spinner=False, ttl=3600)
def geocode_with_google(address: str) -> dict | None:
    if not GOOGLE_TILES_API_KEY:
        return None

    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "address": normalize_address(address),
                "region": "ca",
                "components": "country:CA",
                "key": GOOGLE_TILES_API_KEY,
            },
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException:
        return None

    if payload.get("status") != "OK" or not payload.get("results"):
        return {
            "source": "google",
            "status": payload.get("status", "ERROR"),
        }

    result = payload["results"][0]
    geometry = result["geometry"]
    location = geometry["location"]
    return {
        "source": "google",
        "status": "OK",
        "formatted_address": result.get("formatted_address", normalize_address(address)),
        "latitude": location["lat"],
        "longitude": location["lng"],
        "location_type": geometry.get("location_type", "UNKNOWN"),
        "partial_match": result.get("partial_match", False),
    }


@st.cache_data(show_spinner=False, ttl=3600)
def geocode_with_nominatim(address: str) -> dict | None:
    geolocator = Nominatim(user_agent="skc_realty_app_pro")
    location = geolocator.geocode(normalize_address(address))
    if not location:
        return None

    return {
        "source": "nominatim",
        "status": "OK",
        "formatted_address": location.address,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "location_type": "STREET_OR_AREA",
        "partial_match": True,
    }


def geocode_address(address: str) -> tuple[dict | None, list[str]]:
    warnings: list[str] = []

    google_result = geocode_with_google(address)
    if google_result and google_result.get("status") == "OK":
        if google_result.get("partial_match"):
            warnings.append("Google geocoding 只做了部分匹配，建議補上 postal code 會更準。")
        if google_result.get("location_type") != "ROOFTOP":
            warnings.append(
                f"Google geocoding 精度是 {google_result.get('location_type')}，可能不是精確門牌。"
            )
        return google_result, warnings

    if google_result and google_result.get("status") not in {None, "OK"}:
        warnings.append(
            f"Google Geocoding API 回傳 {google_result['status']}，暫時改用 Nominatim。"
        )

    nominatim_result = geocode_with_nominatim(address)
    if nominatim_result:
        warnings.append("目前退回 Nominatim 地址解析，這通常只會落在街道中心，不一定是精確門牌。")
        return nominatim_result, warnings

    return None, warnings


@st.cache_data(show_spinner=False, ttl=3600)
def get_ground_elevation(latitude: float, longitude: float) -> tuple[dict | None, list[str]]:
    warnings: list[str] = []

    if GOOGLE_TILES_API_KEY:
        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/elevation/json",
                params={
                    "locations": f"{latitude},{longitude}",
                    "key": GOOGLE_TILES_API_KEY,
                },
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            payload = None

        if payload and payload.get("status") == "OK" and payload.get("results"):
            result = payload["results"][0]
            return (
                {
                    "source": "google",
                    "value_m": round(result["elevation"]),
                    "resolution_m": round(result.get("resolution", 0), 1),
                },
                warnings,
            )

        if payload and payload.get("status") not in {None, "OK"}:
            warnings.append(
                f"Google Elevation API 回傳 {payload['status']}，改用公開高程資料作為備援。"
            )

    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/elevation",
            params={"latitude": latitude, "longitude": longitude},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        elevations = payload.get("elevation", [])
        if elevations:
            return (
                {
                    "source": "open-meteo",
                    "value_m": round(elevations[0]),
                    "resolution_m": None,
                },
                warnings,
            )
    except requests.RequestException:
        pass

    warnings.append("無法取得地面海拔，暫時用 150m 作為多倫多近似基準。")
    return (
        {
            "source": "fallback",
            "value_m": 150,
            "resolution_m": None,
        },
        warnings,
    )


def calculate_bearing(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> int:
    from_lat_rad = math.radians(from_lat)
    to_lat_rad = math.radians(to_lat)
    delta_lon_rad = math.radians(to_lon - from_lon)
    x = math.sin(delta_lon_rad) * math.cos(to_lat_rad)
    y = (
        math.cos(from_lat_rad) * math.sin(to_lat_rad)
        - math.sin(from_lat_rad) * math.cos(to_lat_rad) * math.cos(delta_lon_rad)
    )
    return int(round((math.degrees(math.atan2(x, y)) + 360) % 360))


def enhance_image_bytes(
    image_bytes: bytes,
    *,
    sharpness_factor: float,
    contrast_factor: float,
    color_factor: float,
    brightness_factor: float = 1.0,
) -> bytes:
    with Image.open(BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        image = image.filter(ImageFilter.UnsharpMask(radius=1.6, percent=170, threshold=2))
        image = ImageEnhance.Sharpness(image).enhance(sharpness_factor)
        image = ImageEnhance.Contrast(image).enhance(contrast_factor)
        image = ImageEnhance.Color(image).enhance(color_factor)
        image = ImageEnhance.Brightness(image).enhance(brightness_factor)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=95, optimize=True)
        return buffer.getvalue()


@st.cache_data(show_spinner=False, ttl=3600)
def get_street_view_metadata(latitude: float, longitude: float) -> dict:
    metadata_url = "https://maps.googleapis.com/maps/api/streetview/metadata"
    params = {
        "location": f"{latitude},{longitude}",
        "source": "outdoor",
        "key": GOOGLE_TILES_API_KEY,
    }

    try:
        response = requests.get(metadata_url, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException:
        return {"status": "ERROR"}

    payload["status"] = payload.get("status", "ERROR")
    return payload


@st.cache_data(show_spinner=False, ttl=3600)
def get_street_view_reference(
    latitude: float,
    longitude: float,
    street_fov: int,
    enhancement_level: int,
    *,
    bearing: int | None = None,
    pitch: int | None = None,
) -> dict:
    payload = get_street_view_metadata(latitude, longitude)
    status = payload.get("status", "ERROR")
    if status != "OK":
        return {"status": status}

    pano_location = payload.get("location", {})
    pano_lat = pano_location.get("lat", latitude)
    pano_lon = pano_location.get("lng", longitude)
    auto_heading = calculate_bearing(pano_lat, pano_lon, latitude, longitude)
    resolved_heading = auto_heading if bearing is None else bearing
    resolved_pitch = 4 if pitch is None else pitch
    image_params = {
        "size": "640x640",
        "scale": 2,
        "location": f"{pano_lat},{pano_lon}",
        "heading": resolved_heading,
        "pitch": resolved_pitch,
        "fov": street_fov,
        "source": "outdoor",
        "return_error_code": "true",
        "key": GOOGLE_TILES_API_KEY,
    }
    image_url = requests.Request(
        "GET",
        "https://maps.googleapis.com/maps/api/streetview",
        params=image_params,
    ).prepare().url

    try:
        image_response = requests.get(image_url, timeout=15)
        image_response.raise_for_status()
    except requests.RequestException:
        return {"status": "ERROR"}

    if not image_response.headers.get("Content-Type", "").startswith("image/"):
        return {"status": "ERROR"}

    enhancement_boost = enhancement_level / 100
    enhanced_bytes = enhance_image_bytes(
        image_response.content,
        sharpness_factor=1.2 + (enhancement_boost * 1.0),
        contrast_factor=1.05 + (enhancement_boost * 0.25),
        color_factor=1.08 + (enhancement_boost * 0.35),
        brightness_factor=1.0 + (enhancement_boost * 0.04),
    )

    return {
        "status": "OK",
        "image_url": image_url,
        "image_bytes": enhanced_bytes,
        "location": pano_location,
        "heading": resolved_heading,
        "pitch": resolved_pitch,
        "auto_heading": auto_heading,
        "fov": street_fov,
    }


@st.cache_data(show_spinner=False, ttl=3600)
def get_static_map_reference(
    latitude: float,
    longitude: float,
    line_end_latitude: float,
    line_end_longitude: float,
    map_zoom: int,
    enhancement_level: int,
) -> dict:
    image_params = {
        "center": f"{latitude},{longitude}",
        "zoom": map_zoom,
        "size": "1400x1000",
        "scale": 2,
        "maptype": "hybrid",
        "markers": f"color:red|{latitude},{longitude}",
        "path": (
            "color:0xff5a5f|weight:5|"
            f"{latitude},{longitude}|{line_end_latitude},{line_end_longitude}"
        ),
        "key": GOOGLE_TILES_API_KEY,
    }
    image_url = requests.Request(
        "GET",
        "https://maps.googleapis.com/maps/api/staticmap",
        params=image_params,
    ).prepare().url

    try:
        response = requests.get(image_url, timeout=15)
        response.raise_for_status()
    except requests.RequestException:
        return {"status": "ERROR"}

    if not response.headers.get("Content-Type", "").startswith("image/"):
        return {"status": "ERROR"}

    enhancement_boost = enhancement_level / 100
    enhanced_bytes = enhance_image_bytes(
        response.content,
        sharpness_factor=1.15 + (enhancement_boost * 0.8),
        contrast_factor=1.06 + (enhancement_boost * 0.22),
        color_factor=1.1 + (enhancement_boost * 0.3),
        brightness_factor=1.0 + (enhancement_boost * 0.03),
    )

    return {
        "status": "OK",
        "image_bytes": enhanced_bytes,
        "image_url": image_url,
        "zoom": map_zoom,
    }


def build_preview(
    address: str,
    floor: int,
    bearing: int,
    tilt: int,
    camera_range: int,
    street_zoom: int,
    map_zoom: int,
    enhancement_level: int,
) -> dict:
    geocoded, geocode_warnings = geocode_address(address)
    if not geocoded:
        return {
            "error": "找不到這個地址。請補上更完整的地址，例如門牌、Toronto、ON 或 postal code。",
            "warnings": geocode_warnings,
        }

    elevation, elevation_warnings = get_ground_elevation(
        geocoded["latitude"],
        geocoded["longitude"],
    )
    floor_height_m = int((floor * 3) + 5)
    ground_elevation_m = int(elevation["value_m"]) if elevation else 150
    absolute_altitude_m = ground_elevation_m + floor_height_m
    direction_line_end = geodesic_distance(meters=max(camera_range, 50)).destination(
        (geocoded["latitude"], geocoded["longitude"]),
        bearing,
    )
    dynamic_pitch = min(25, max(-5, int((floor * 1.0) + ((tilt - 30) * 0.18))))
    identify_fov = max(60, 100 - (street_zoom * 8))
    fallback_direction_fov = max(45, 95 - (street_zoom * 8))

    identify_street_view = get_street_view_reference(
        geocoded["latitude"],
        geocoded["longitude"],
        street_fov=identify_fov,
        enhancement_level=enhancement_level,
    )
    directional_street_view = get_street_view_reference(
        geocoded["latitude"],
        geocoded["longitude"],
        street_fov=fallback_direction_fov,
        enhancement_level=enhancement_level,
        bearing=bearing,
        pitch=dynamic_pitch,
    )
    static_map_reference = get_static_map_reference(
        geocoded["latitude"],
        geocoded["longitude"],
        direction_line_end.latitude,
        direction_line_end.longitude,
        map_zoom,
        enhancement_level,
    )

    return {
        "address": geocoded["formatted_address"],
        "latitude": geocoded["latitude"],
        "longitude": geocoded["longitude"],
        "geocode_source": geocoded["source"],
        "geocode_status": geocoded.get("status", "OK"),
        "location_type": geocoded.get("location_type", "UNKNOWN"),
        "floor": int(floor),
        "floor_height_m": floor_height_m,
        "ground_elevation_m": ground_elevation_m,
        "absolute_altitude_m": absolute_altitude_m,
        "direction_line_end_latitude": direction_line_end.latitude,
        "direction_line_end_longitude": direction_line_end.longitude,
        "static_map": static_map_reference,
        "bearing": bearing,
        "tilt": tilt,
        "camera_range": camera_range,
        "street_zoom": street_zoom,
        "street_fov": fallback_direction_fov,
        "map_zoom": map_zoom,
        "enhancement_level": enhancement_level,
        "street_view_identify": identify_street_view,
        "street_view_directional": directional_street_view,
        "warnings": geocode_warnings + elevation_warnings,
        "elevation_source": elevation["source"] if elevation else "fallback",
    }


def build_interactive_reference_html(
    *,
    api_key: str,
    address: str,
    latitude: float,
    longitude: float,
    line_end_latitude: float,
    line_end_longitude: float,
    bearing: int,
    pitch: int,
    street_zoom: int,
    map_zoom: int,
) -> str:
    config = {
        "apiKey": api_key,
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
        "lineEndLatitude": line_end_latitude,
        "lineEndLongitude": line_end_longitude,
        "bearing": bearing,
        "pitch": pitch,
        "streetZoom": street_zoom,
        "mapZoom": map_zoom,
    }

    return f"""
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <style>
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #eef3f8;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}

    * {{
      box-sizing: border-box;
    }}

    .shell {{
      width: 100%;
      height: 100%;
      padding: 12px;
      background: linear-gradient(180deg, #f7fafc 0%, #ebf1f5 100%);
    }}

    .banner {{
      margin-bottom: 12px;
      padding: 12px 14px;
      border-radius: 16px;
      background: #ffffff;
      border: 1px solid rgba(15, 23, 42, 0.08);
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
    }}

    .banner-title {{
      margin: 0 0 6px;
      font-size: 15px;
      font-weight: 700;
      color: #0f172a;
    }}

    .banner-copy {{
      margin: 0;
      font-size: 12px;
      line-height: 1.6;
      color: #475569;
    }}

    .grid {{
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 12px;
      width: 100%;
      height: calc(100% - 126px);
    }}

    .panel {{
      display: flex;
      flex-direction: column;
      min-height: 0;
      background: #ffffff;
      border-radius: 18px;
      border: 1px solid rgba(15, 23, 42, 0.08);
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
      overflow: hidden;
    }}

    .panel-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px 10px;
      border-bottom: 1px solid rgba(15, 23, 42, 0.08);
      background: rgba(248, 250, 252, 0.95);
    }}

    .panel-title {{
      margin: 0;
      font-size: 14px;
      font-weight: 700;
      color: #0f172a;
    }}

    .panel-copy {{
      margin: 4px 0 0;
      font-size: 11px;
      line-height: 1.5;
      color: #64748b;
    }}

    .chip {{
      align-self: flex-start;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      color: #0f172a;
      background: #e2e8f0;
    }}

    .viewport {{
      position: relative;
      flex: 1;
      min-height: 0;
      background: #dbe5f0;
    }}

    #streetview, #map {{
      width: 100%;
      height: 100%;
    }}

    .status {{
      margin-top: 12px;
      padding: 12px 14px;
      border-radius: 16px;
      background: #ffffff;
      border: 1px solid rgba(15, 23, 42, 0.08);
      font-size: 12px;
      line-height: 1.6;
      color: #334155;
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
    }}

    .status strong {{
      color: #0f172a;
    }}

    @media (max-width: 980px) {{
      .grid {{
        grid-template-columns: 1fr;
        height: auto;
      }}

      .panel {{
        min-height: 360px;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="banner">
      <p class="banner-title">{address}</p>
      <p class="banner-copy">
        左邊是可以直接拖曳、縮放、旋轉的互動街景。右邊是互動衛星圖。
        紅點代表地址中心，紅線代表你設定的面向方向，藍點與藍線代表目前街景相機的位置與朝向。
      </p>
    </div>

    <div class="grid">
      <section class="panel">
        <div class="panel-head">
          <div>
            <p class="panel-title">互動街景</p>
            <p class="panel-copy">可以直接用滑鼠拖曳視角，也可以用滾輪放大縮小。</p>
          </div>
          <div class="chip">地面街景</div>
        </div>
        <div class="viewport">
          <div id="streetview"></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <p class="panel-title">互動衛星圖</p>
            <p class="panel-copy">可以直接 zoom in / zoom out，看建物位置、棟距和相對方位。</p>
          </div>
          <div class="chip">平面比例</div>
        </div>
        <div class="viewport">
          <div id="map"></div>
        </div>
      </section>
    </div>

    <div class="status" id="statusBar">
      <strong>載入中：</strong> 正在建立互動街景與衛星參考圖。
    </div>
  </div>

  <script>
    const CONFIG = {json.dumps(config)};

    function setStatus(message) {{
      document.getElementById("statusBar").innerHTML = message;
    }}

    function destinationPoint(lat, lng, bearingDegrees, distanceMeters) {{
      const earthRadius = 6378137;
      const angularDistance = distanceMeters / earthRadius;
      const bearingRadians = bearingDegrees * Math.PI / 180;
      const latRadians = lat * Math.PI / 180;
      const lngRadians = lng * Math.PI / 180;

      const destLat = Math.asin(
        Math.sin(latRadians) * Math.cos(angularDistance) +
        Math.cos(latRadians) * Math.sin(angularDistance) * Math.cos(bearingRadians)
      );

      const destLng = lngRadians + Math.atan2(
        Math.sin(bearingRadians) * Math.sin(angularDistance) * Math.cos(latRadians),
        Math.cos(angularDistance) - Math.sin(latRadians) * Math.sin(destLat)
      );

      return {{
        lat: destLat * 180 / Math.PI,
        lng: destLng * 180 / Math.PI,
      }};
    }}

    function haversineMeters(lat1, lng1, lat2, lng2) {{
      const toRadians = value => value * Math.PI / 180;
      const earthRadius = 6371000;
      const dLat = toRadians(lat2 - lat1);
      const dLng = toRadians(lng2 - lng1);
      const a =
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(toRadians(lat1)) * Math.cos(toRadians(lat2)) *
        Math.sin(dLng / 2) * Math.sin(dLng / 2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
      return Math.round(earthRadius * c);
    }}

    (g => {{
      let h, a, k;
      const p = "The Google Maps JavaScript API";
      const c = "google";
      const l = "importLibrary";
      const q = "__ib__";
      const m = document;
      const b = window;
      b[c] = b[c] || {{}};
      const d = b[c].maps || (b[c].maps = {{}});
      const r = new Set();
      const e = new URLSearchParams();
      const u = () => h || (h = new Promise(async (f, n) => {{
        a = m.createElement("script");
        e.set("libraries", [...r] + "");
        for (k in g) {{
          e.set(k.replace(/[A-Z]/g, t => "_" + t[0].toLowerCase()), g[k]);
        }}
        e.set("callback", c + ".maps." + q);
        a.src = "https://maps.googleapis.com/maps/api/js?" + e.toString();
        d[q] = f;
        a.onerror = () => n(new Error(p + " could not load."));
        a.nonce = m.querySelector("script[nonce]")?.nonce || "";
        m.head.append(a);
      }}));
      if (d[l]) {{
        console.warn(p + " only loads once. Ignoring:", g);
      }} else {{
        d[l] = (f, ...n) => r.add(f) && u().then(() => d[l](f, ...n));
      }}
    }})({{
      key: CONFIG.apiKey,
      v: "weekly",
      language: "zh-TW",
      region: "CA"
    }});

    (async () => {{
      try {{
        await google.maps.importLibrary("maps");

        const propertyPosition = {{ lat: CONFIG.latitude, lng: CONFIG.longitude }};
        const directionEnd = {{ lat: CONFIG.lineEndLatitude, lng: CONFIG.lineEndLongitude }};

        const map = new google.maps.Map(document.getElementById("map"), {{
          center: propertyPosition,
          zoom: CONFIG.mapZoom,
          mapTypeId: "satellite",
          tilt: 0,
          streetViewControl: false,
          mapTypeControl: false,
          fullscreenControl: true,
          gestureHandling: "greedy",
        }});

        const propertyMarker = new google.maps.Marker({{
          map,
          position: propertyPosition,
          title: "地址中心",
          icon: {{
            path: google.maps.SymbolPath.CIRCLE,
            scale: 7,
            fillColor: "#ff5a5f",
            fillOpacity: 1,
            strokeColor: "#ffffff",
            strokeWeight: 2,
          }},
        }});

        const directionLine = new google.maps.Polyline({{
          map,
          path: [propertyPosition, directionEnd],
          geodesic: true,
          strokeColor: "#ff5a5f",
          strokeOpacity: 0.95,
          strokeWeight: 4,
          icons: [{{
            icon: {{
              path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
              scale: 3,
              strokeColor: "#ff5a5f",
              fillColor: "#ff5a5f",
              fillOpacity: 1,
            }},
            offset: "100%",
          }}],
        }});

        const panoMarker = new google.maps.Marker({{
          map,
          title: "街景相機",
          visible: false,
          icon: {{
            path: google.maps.SymbolPath.CIRCLE,
            scale: 6,
            fillColor: "#2563eb",
            fillOpacity: 1,
            strokeColor: "#ffffff",
            strokeWeight: 2,
          }},
        }});

        const cameraLine = new google.maps.Polyline({{
          map,
          geodesic: true,
          strokeColor: "#2563eb",
          strokeOpacity: 0.92,
          strokeWeight: 4,
        }});

        const panorama = new google.maps.StreetViewPanorama(document.getElementById("streetview"), {{
          position: propertyPosition,
          pov: {{
            heading: CONFIG.bearing,
            pitch: CONFIG.pitch,
          }},
          zoom: CONFIG.streetZoom,
          addressControl: true,
          fullscreenControl: true,
          linksControl: true,
          panControl: true,
          zoomControl: true,
          motionTracking: false,
          showRoadLabels: true,
        }});

        const streetViewService = new google.maps.StreetViewService();
        const panoramaResult = await streetViewService.getPanorama({{
          location: propertyPosition,
          radius: 120,
          source: google.maps.StreetViewSource.OUTDOOR,
        }});

        panorama.setPano(panoramaResult.data.location.pano);
        panorama.setPosition(panoramaResult.data.location.latLng);
        panorama.setPov({{
          heading: CONFIG.bearing,
          pitch: CONFIG.pitch,
        }});
        panorama.setZoom(CONFIG.streetZoom);

        function updateCameraOverlay() {{
          const panoramaPosition = panorama.getPosition();
          const currentPov = panorama.getPov();
          if (!panoramaPosition || !currentPov) {{
            return;
          }}

          const lat = panoramaPosition.lat();
          const lng = panoramaPosition.lng();
          const lookEnd = destinationPoint(lat, lng, currentPov.heading || CONFIG.bearing, 75);
          panoMarker.setPosition({{ lat, lng }});
          panoMarker.setVisible(true);
          cameraLine.setPath([
            {{ lat, lng }},
            lookEnd,
          ]);

          const distanceMeters = haversineMeters(lat, lng, CONFIG.latitude, CONFIG.longitude);
          setStatus(
            `<strong>怎麼看：</strong> 左邊是可以直接拖曳與縮放的街景，全程不需要重新 generate。` +
            ` 右邊紅點是地址中心、紅線是你設定的面向；藍點是街景相機、藍線是它目前正看的方向。` +
            ` 目前街景相機距建物約 <strong>${{distanceMeters}} m</strong>。`
          );
        }}

        panorama.addListener("pov_changed", updateCameraOverlay);
        panorama.addListener("position_changed", updateCameraOverlay);
        updateCameraOverlay();

        const bounds = new google.maps.LatLngBounds();
        bounds.extend(propertyPosition);
        bounds.extend(directionEnd);
        bounds.extend(panorama.getPosition());
        map.fitBounds(bounds, 60);
        google.maps.event.addListenerOnce(map, "idle", () => {{
          if (map.getZoom() > CONFIG.mapZoom) {{
            map.setZoom(CONFIG.mapZoom);
          }}
        }});
      }} catch (error) {{
        console.error(error);
        setStatus(
          "<strong>互動模式載入失敗：</strong> 請確認 API Key 已啟用 Maps JavaScript API 與 Street View，" +
          "或先查看下方的靜態備援圖。"
        );
        return;
      }}
    }})();
  </script>
</body>
</html>
"""


ensure_data_store()

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "logged_events" not in st.session_state:
    st.session_state.logged_events = set()

query_customer_id = st.query_params.get("customer_id", "")
linked_customer_id = sanitize_customer_id(str(query_customer_id))
default_customer_id = linked_customer_id or "demo-customer"

with st.sidebar:
    st.header("客戶存取")
    if linked_customer_id:
        raw_customer_id = st.text_input("Customer ID", linked_customer_id, disabled=True)
        customer_id = linked_customer_id
        st.caption("這個連結已綁定專屬 customer_id，客戶不需要修改。")
    else:
        raw_customer_id = st.text_input("Customer ID", default_customer_id)
        customer_id = sanitize_customer_id(raw_customer_id)
        if raw_customer_id and raw_customer_id != customer_id:
            st.warning("Customer ID 已自動轉成小寫，只保留英數字、`-`、`_`。")
        st.caption("建議你每個客戶固定用一個 customer_id，之後就能看 usage，也能單獨 pause。")
    with st.expander("customer_id 命名建議", expanded=False):
        st.markdown(
            "- 一個客戶固定一個 ID，不要每次換新。\n"
            "- 建議格式：`client-a`、`zhangyan`、`plazamidtown-7f-demo`。\n"
            "- 只用英數字、`-`、`_`，避免空格與中文。\n"
            "- 如果是正式客戶，建議用你自己 CRM 裡穩定不變的代號。"
        )
    customer_name = st.text_input("客戶名稱 / email（選填）", "")

    if customer_id:
        st.query_params["customer_id"] = customer_id
    elif "customer_id" in st.query_params:
        del st.query_params["customer_id"]

    admin_unlocked = False
    if ADMIN_ACCESS_CODE:
        admin_code_input = st.text_input("Admin code", type="password")
        admin_unlocked = admin_code_input == ADMIN_ACCESS_CODE
        if admin_code_input and not admin_unlocked:
            st.error("Admin code 不正確。")
    else:
        st.caption("目前未設定 `SKC_ADMIN_CODE`，admin panel 會維持隱藏。")

    st.header("參數設定")
    address = st.text_input("輸入地址", "25 Holly Street, Toronto")
    floor = st.number_input("輸入樓層", min_value=1, max_value=100, value=7)
    bearing = st.slider("面向方向（拖動後街景與紅線會一起轉）", 0, 360, 62)
    tilt = st.slider("參考仰角（只影響方向預覽，不是真實七樓相機）", 0, 90, 30)
    camera_range = st.slider("方向線長度（只影響俯視圖紅線）", 40, 350, 123)
    street_zoom = st.slider("街景縮放（數字越大越放大）", 0, 5, 2)
    map_zoom = st.slider("俯視縮放（數字越大越放大）", 18, 21, 20)
    enhancement_level = st.slider("清晰度與色彩增強", 0, 100, 55)
    st.caption("滑動任何參數後，主畫面會自動更新。互動街景與衛星圖本身也可以直接拖曳、縮放。")

    with st.expander("怎麼看這個工具", expanded=True):
        st.markdown(
            "1. `建物辨識街景`：先讓你看懂這棟樓和街道長什麼樣。\n"
            "2. `互動街景`：可以直接拖曳、旋轉、縮放，不用反覆重新 generate。\n"
            "3. `互動衛星圖`：可以直接 zoom in / zoom out，看紅線方向、棟距和相對位置。\n"
            "4. 目前公開 Google 資料無法保證輸出 `七樓窗外 1:1 真實視角`。"
        )


preview = None
preview_error = None
customer_record = None

if not customer_id:
    preview_error = "請先輸入 customer_id。"
else:
    customer_record = upsert_customer(customer_id, customer_name=customer_name)

    session_marker = f"session_open::{customer_id}"
    if session_marker not in st.session_state.logged_events:
        append_usage_event(
            customer_id,
            "session_open",
            {
                "session_id": st.session_state.session_id,
            },
        )
        st.session_state.logged_events.add(session_marker)

    if not customer_record.get("active", True):
        preview_error = "這個客戶目前已被暫停，系統不會載入地圖。"
        blocked_marker = f"paused_blocked::{customer_id}"
        if blocked_marker not in st.session_state.logged_events:
            append_usage_event(
                customer_id,
                "paused_blocked",
                {
                    "session_id": st.session_state.session_id,
                },
            )
            st.session_state.logged_events.add(blocked_marker)

if not preview_error and not GOOGLE_TILES_API_KEY:
    preview_error = "⚠️ 請先在終端機設定 GOOGLE_TILES_API_KEY，然後重新啟動 Streamlit。"
elif not preview_error and not address.strip():
    preview_error = "請先輸入地址。"
elif not preview_error:
    with st.spinner("正在即時更新街景與俯視參考圖..."):
        preview = build_preview(
            address=address,
            floor=int(floor),
            bearing=bearing,
            tilt=tilt,
            camera_range=camera_range,
            street_zoom=street_zoom,
            map_zoom=map_zoom,
            enhancement_level=enhancement_level,
        )
        if preview.get("error"):
            preview_error = preview["error"]
            preview = None
        else:
            event_signature = (
                f"preview::{customer_id}::{address}::{floor}::{bearing}::{tilt}::"
                f"{camera_range}::{street_zoom}::{map_zoom}"
            )
            if event_signature not in st.session_state.logged_events:
                append_usage_event(
                    customer_id,
                    "preview_rendered",
                    {
                        "session_id": st.session_state.session_id,
                        "address": preview["address"],
                        "floor": int(floor),
                        "bearing": bearing,
                        "tilt": tilt,
                        "camera_range": camera_range,
                        "street_zoom": street_zoom,
                        "map_zoom": map_zoom,
                        "location_type": preview["location_type"],
                    },
                )
                st.session_state.logged_events.add(event_signature)

if preview:
    if customer_record:
        customer_label = customer_record.get("customer_name") or customer_id
        st.caption(f"目前客戶：`{customer_label}` | customer_id: `{customer_id}` | status: `active`")
    st.success(
        f"📍 定位成功：{preview['address']} | 座標 {preview['latitude']:.6f}, {preview['longitude']:.6f}"
    )
    st.info(
        "重要：這不是把相機真的放到第 7 樓窗邊的 1:1 真實窗景。現在輸出的是清楚可辨識的地面街景參考，加上無扭曲的俯視比例圖。"
    )

    for warning in preview["warnings"]:
        st.warning(warning)

    map_col, info_col = st.columns([1.85, 1], gap="large")

    with map_col:
        identify_view = preview["street_view_identify"]
        directional_view = preview["street_view_directional"]
        static_map = preview["static_map"]

        st.subheader("建物辨識街景")
        st.caption("這張圖只負責讓你看得懂是什麼建物、什麼街口，不代表七樓窗外視角。")
        if identify_view.get("status") == "OK":
            st.image(identify_view["image_bytes"], use_container_width=True)
            st.caption(
                f"自動對準建物，heading {identify_view['heading']}°，pitch {identify_view['pitch']}°，fov {identify_view['fov']}。"
            )
        else:
            st.error("建物辨識街景抓取失敗。請確認 API Key 已啟用 Street View Static API。")

        st.subheader("互動檢視器")
        st.caption(
            "左邊是可拖曳的 Street View，全程不需要重新 generate；右邊是可縮放的衛星圖，會同步顯示地址中心、面向方向與街景相機位置。"
        )
        components.html(
            build_interactive_reference_html(
                api_key=GOOGLE_TILES_API_KEY,
                address=preview["address"],
                latitude=preview["latitude"],
                longitude=preview["longitude"],
                line_end_latitude=preview["direction_line_end_latitude"],
                line_end_longitude=preview["direction_line_end_longitude"],
                bearing=preview["bearing"],
                pitch=directional_view["pitch"] if directional_view.get("status") == "OK" else 0,
                street_zoom=preview["street_zoom"],
                map_zoom=preview["map_zoom"],
            ),
            height=760,
        )

        with st.expander("靜態備援參考圖", expanded=False):
            st.caption(
                "如果互動模式載入失敗，下面兩張是後端先抓好的靜態備援圖。"
            )

            st.markdown("**方向預覽備援圖**")
            if directional_view.get("status") == "OK":
                st.image(directional_view["image_bytes"], use_container_width=True)
                st.caption(
                    f"目前方向預覽：heading {directional_view['heading']}°，pitch {directional_view['pitch']}°，fov {directional_view['fov']}。"
                )
            else:
                st.error("方向預覽抓取失敗。請確認 API Key 已啟用 Street View Static API。")

            st.markdown("**俯視比例圖備援圖**")
            st.caption(
                f"紅點是地址中心，紅線是你現在設定的面向方向。當前 zoom {preview['map_zoom']}。"
            )
            if static_map.get("status") == "OK":
                st.image(static_map["image_bytes"], use_container_width=True)
            else:
                st.error("俯視比例圖抓取失敗。請確認 API Key 已啟用 Maps Static API。")

    with info_col:
        st.subheader("定位品質")
        st.metric("地址來源", preview["geocode_source"].upper())
        st.metric("解析精度", preview["location_type"])
        st.metric("海拔來源", preview["elevation_source"])
        st.caption("如果這裡不是 `GOOGLE + ROOFTOP`，就代表目前定位可能還不是精確門牌。")

        st.subheader("高度摘要")
        st.metric("樓層相對高度", f"{preview['floor_height_m']} m")
        st.metric("地面海拔", f"{preview['ground_elevation_m']} m")
        st.metric("絕對高度", f"{preview['absolute_altitude_m']} m")
        st.caption("這三個數字現在只拿來輔助推估方向預覽的仰角，不代表街景相機真的被放到該高度。")

        st.subheader("方向預覽狀態")
        status = directional_view.get("status")

        if status == "OK":
            st.metric("Street View", "可用")
            st.metric("街景 heading", f"{directional_view['heading']}°")
            st.metric("街景 pitch", f"{directional_view['pitch']}°")
            st.metric("街景 zoom", str(preview["street_zoom"]))
            st.metric("俯視 zoom", str(preview["map_zoom"]))
        elif status == "REQUEST_DENIED":
            st.info("你的 API Key 尚未啟用 Street View Static API，所以無法輸出清楚街景主圖。")
        elif status == "ZERO_RESULTS":
            st.info("這個位置附近沒有可用的 Google 街景資料。")
        else:
            st.info("暫時抓不到街景主圖。")

else:
    if preview_error:
        st.error(preview_error)
    else:
        st.info("先在左側輸入地址與樓層，系統會自動生成參考圖。")


if admin_unlocked:
    st.divider()
    st.subheader("Admin Panel")
    if DATA_BACKEND_NAME == "cloud-postgres":
        st.caption("這個 admin panel 目前已經接到 cloud Postgres。客戶狀態與 usage 不再依賴本機 JSON。")
    else:
        st.caption("這個 admin panel 目前仍在使用本機 JSON。部署前請設定 `DATABASE_URL` 切到 cloud Postgres。")

    usage_rows = build_customer_usage_rows()
    if usage_rows:
        st.dataframe(usage_rows, use_container_width=True, hide_index=True)

        customer_options = [row["customer_id"] for row in usage_rows]
        selected_customer_id = st.selectbox("選擇要管理的客戶", customer_options)
        selected_customer = load_customers().get(selected_customer_id, {})

        status_col, action_col = st.columns([1, 2], gap="large")
        with status_col:
            st.metric(
                "目前狀態",
                "active" if selected_customer.get("active", True) else "paused",
            )
            st.metric("客戶名稱", selected_customer.get("customer_name", "") or "-")

        with action_col:
            activate_col, pause_col = st.columns(2)
            with activate_col:
                if st.button("啟用客戶", use_container_width=True):
                    set_customer_active(selected_customer_id, True)
                    append_usage_event(
                        selected_customer_id,
                        "status_changed",
                        {
                            "session_id": st.session_state.session_id,
                            "active": True,
                        },
                    )
                    st.rerun()
            with pause_col:
                if st.button("暫停客戶", use_container_width=True):
                    set_customer_active(selected_customer_id, False)
                    append_usage_event(
                        selected_customer_id,
                        "status_changed",
                        {
                            "session_id": st.session_state.session_id,
                            "active": False,
                        },
                    )
                    st.rerun()
    else:
        st.info("目前還沒有客戶資料。")
