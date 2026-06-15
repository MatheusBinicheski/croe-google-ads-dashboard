"""
CROE Odonto — Dashboard Google Ads
FastAPI + Chart.js + Google Ads API
"""

import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from google.ads.googleads.client import GoogleAdsClient

# ============================================================
# CONFIG
# ============================================================
CUSTOMER_ID = "1528629564"

GOOGLE_ADS_CONFIG = {
    "developer_token": os.environ["GOOGLE_ADS_DEV_TOKEN"],
    "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
    "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
    "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
    "use_proto_plus": True,
}

DASH_USER = os.environ.get("DASH_USER", "croe")
DASH_PASS = os.environ["DASH_PASS"]

app = FastAPI(title="CROE Google Ads Dashboard")
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")

_client: Optional[GoogleAdsClient] = None


def get_ads_client() -> GoogleAdsClient:
    global _client
    if _client is None:
        _client = GoogleAdsClient.load_from_dict(GOOGLE_ADS_CONFIG)
    return _client


def authenticate(creds: HTTPBasicCredentials = Depends(security)):
    ok_u = secrets.compare_digest(creds.username, DASH_USER)
    ok_p = secrets.compare_digest(creds.password, DASH_PASS)
    if not (ok_u and ok_p):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Auth invalida",
            headers={"WWW-Authenticate": "Basic"},
        )
    return creds.username


# ============================================================
# GOOGLE ADS QUERIES
# ============================================================
def micros(v):
    return (v or 0) / 1_000_000


def query(query_str: str):
    c = get_ads_client()
    svc = c.get_service("GoogleAdsService")
    return list(svc.search(customer_id=CUSTOMER_ID, query=query_str))


def get_summary(period: str = "LAST_30_DAYS"):
    """KPIs agregados do periodo."""
    q = f"""
        SELECT metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.average_cpc, metrics.ctr
        FROM customer
        WHERE segments.date DURING {period}
    """
    for r in query(q):
        cost = micros(r.metrics.cost_micros)
        conv = r.metrics.conversions
        return {
            "impressions": r.metrics.impressions,
            "clicks": r.metrics.clicks,
            "cost": cost,
            "conversions": conv,
            "ctr": (r.metrics.ctr * 100) if r.metrics.ctr else 0,
            "cpc": micros(r.metrics.average_cpc),
            "cpa": (cost / conv) if conv else 0,
        }
    return {
        "impressions": 0, "clicks": 0, "cost": 0,
        "conversions": 0, "ctr": 0, "cpc": 0, "cpa": 0,
    }


def get_campaigns():
    """Performance por campanha (ultimos 30 dias)."""
    q = """
        SELECT campaign.id, campaign.name, campaign.status,
               campaign.primary_status,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions
        FROM campaign
        WHERE segments.date DURING LAST_30_DAYS
          AND campaign.status != 'REMOVED'
        ORDER BY metrics.cost_micros DESC
    """
    out = []
    for r in query(q):
        cost = micros(r.metrics.cost_micros)
        conv = r.metrics.conversions
        clicks = r.metrics.clicks
        out.append({
            "id": r.campaign.id,
            "name": r.campaign.name,
            "status": r.campaign.status.name,
            "primary": r.campaign.primary_status.name,
            "impressions": r.metrics.impressions,
            "clicks": clicks,
            "cost": cost,
            "conversions": conv,
            "cpc": (cost / clicks) if clicks else 0,
            "cpa": (cost / conv) if conv else 0,
        })
    return out


def get_timeline():
    """Cliques + custo + conversoes por dia (ultimos 30 dias)."""
    q = """
        SELECT segments.date, metrics.clicks, metrics.cost_micros,
               metrics.conversions
        FROM customer
        WHERE segments.date DURING LAST_30_DAYS
        ORDER BY segments.date
    """
    out = []
    for r in query(q):
        out.append({
            "date": r.segments.date,
            "clicks": r.metrics.clicks,
            "cost": micros(r.metrics.cost_micros),
            "conversions": r.metrics.conversions,
        })
    return out


def get_keywords():
    """Top 20 keywords por cliques (ultimos 30 dias)."""
    q = """
        SELECT campaign.name, ad_group.name,
               ad_group_criterion.keyword.text,
               ad_group_criterion.keyword.match_type,
               ad_group_criterion.status,
               ad_group_criterion.approval_status,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions
        FROM keyword_view
        WHERE segments.date DURING LAST_30_DAYS
        ORDER BY metrics.clicks DESC
        LIMIT 30
    """
    out = []
    for r in query(q):
        cost = micros(r.metrics.cost_micros)
        clicks = r.metrics.clicks
        conv = r.metrics.conversions
        out.append({
            "campaign": r.campaign.name,
            "ad_group": r.ad_group.name,
            "keyword": r.ad_group_criterion.keyword.text,
            "match_type": r.ad_group_criterion.keyword.match_type.name,
            "approval": r.ad_group_criterion.approval_status.name,
            "impressions": r.metrics.impressions,
            "clicks": clicks,
            "cost": cost,
            "conversions": conv,
            "cpa": (cost / conv) if conv else 0,
        })
    return out


def get_search_terms():
    """Top 30 termos que pessoas digitaram (ultimos 30 dias)."""
    q = """
        SELECT search_term_view.search_term, campaign.name,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions
        FROM search_term_view
        WHERE segments.date DURING LAST_30_DAYS
        ORDER BY metrics.impressions DESC
        LIMIT 30
    """
    out = []
    for r in query(q):
        cost = micros(r.metrics.cost_micros)
        clicks = r.metrics.clicks
        conv = r.metrics.conversions
        out.append({
            "term": r.search_term_view.search_term,
            "campaign": r.campaign.name,
            "impressions": r.metrics.impressions,
            "clicks": clicks,
            "cost": cost,
            "conversions": conv,
            "ctr": (clicks / r.metrics.impressions * 100) if r.metrics.impressions else 0,
        })
    return out


# ============================================================
# ROTAS
# ============================================================
@app.get("/healthz")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, _: str = Depends(authenticate)):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/data")
def api_data(_: str = Depends(authenticate)):
    try:
        return JSONResponse({
            "today": get_summary("TODAY"),
            "yesterday": get_summary("YESTERDAY"),
            "last_7d": get_summary("LAST_7_DAYS"),
            "last_30d": get_summary("LAST_30_DAYS"),
            "campaigns": get_campaigns(),
            "timeline": get_timeline(),
            "keywords": get_keywords(),
            "search_terms": get_search_terms(),
            "fetched_at": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
