"""
Weather Intelligence - a Databricks App that:
- Harvest unstructured weather text from the National Weather Service API via weather_client.py
- Vectorize that text and load it into Lakebase (Postgres + pgvector) via weather_db.py
- Add a retrieval endpoint to the Flask REST API that performs semantic search over the ingested weather documents

Run locally (python app.py) or
Deploy as a Databricks App using app.yaml
"""

import logging
import os

import requests
from databricks.sdk import WorkspaceClient
from flask import Flask, jsonify, render_template, request

import weather_client
import weather_db
from weather_client import NWSClient, UnknownLocationError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weather-app")

app = Flask(__name__)
_w = WorkspaceClient()

# Locations synced by POST /weather/sync when the request body doesn't name any
DEFAULT_WEATHER_LOCATIONS = [
    loc.strip()
    for loc in os.environ.get(
        "WEATHER_LOCATIONS", "Chicago, IL;Austin, TX;Miami, FL"
    ).split(";")
    if loc.strip()
]


# ---------
# ENDPOINTS
@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
@app.route("/weather")
def weather_page():
    """Browser UI for weather sync + semantic search"""
    return render_template("weather.html")


@app.route("/weather/sync", methods=["POST"])
def sync_weather_from_nws():
    """"""
    if request.is_json else 


@app.route("/healthz")
@app.route("/healthz")



if __name__ == '__main__':
    host = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_RUN_PORT', 8000))
    app.run(debug=True, host=host, port=port)