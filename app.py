from flask import Flask, render_template, request, url_for, jsonify, json, Blueprint
import numpy as np
import pandas as pd
import logging
from logging.handlers import RotatingFileHandler
from ddtrace import tracer, patch_all, config
from datadog import statsd, initialize, api
from flasgger import Swagger
import os
from sklearn.preprocessing import StandardScaler
#import src.utils as utils
from google.cloud import bigquery
from google.cloud import spanner
from google.oauth2 import service_account
import logging
from dotenv import load_dotenv
load_dotenv()

# Initialize Flask app with swagger
app = Flask(__name__)
swagger = Swagger(app)  

# Configure logging
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
stream_handler = logging.StreamHandler()  
stream_handler.setFormatter(log_formatter)  
app.logger.addHandler(stream_handler)  
app.logger.setLevel(logging.INFO)

# Spanner setup
spanner_instance_id = os.getenv('SPANNER_INSTANCE_ID')
spanner_database_id = os.getenv('SPANNER_DATABASE_ID')
google_credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

credentials = service_account.Credentials.from_service_account_file(google_credentials_path)
spanner_client = spanner.Client(credentials=credentials)
instance = spanner_client.instance(spanner_instance_id)
database = instance.database(spanner_database_id)

@app.route('/pwa_recommendations_endpoint', methods=['POST'])
def pwa_recommendations_endpoint():
    """
    Geo Recommendations Endpoint
    ---
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            country:
              type: string
              example: "South Africa"
            city:
              type: string
              example: "Cape Town"
            region:
              type: string
              example: "Western Cape"
    responses:
      200:
        description: List of recommendations
        schema:
          type: array
          items:
            type: object
            properties:
              continent:
                type: string
              country:
                type: string
              region:
                type: string
              city:
                type: string
              recommendation_id:
                type: string
              Ranking:
                type: integer
              recommendation_type:
                type: string
              recommendation_activity:
                type: string
      400:
        description: Missing parameters
      500:
        description: Internal server error
    """
    try:
        app.logger.info("Geo recommendations endpoint called")
        
        data = request.get_json()
        app.logger.info(f"Request data: {data}")
        
        country = data.get('country')
        city = data.get('city')
        region = data.get('region')

        if not (country or city or region):
            app.logger.error("At least one of country, city, or region must be provided")
            return jsonify({"error": "At least one of country, city, or region must be provided"}), 400

        # Build query dynamically
        conditions = []
        query_params = {}

        if country:
            conditions.append("country = @country")
            query_params["country"] = spanner.param_types.STRING
        if city:
            conditions.append("city = @city")
            query_params["city"] = spanner.param_types.STRING
        if region:
            conditions.append("region = @region")
            query_params["region"] = spanner.param_types.STRING

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT continent, country, region, city, GameID AS recommendation_id, City_Ranking AS Ranking, recommendation_type, recommendation_activity
            FROM games_geo_popularity
            WHERE {where_clause}
            UNION ALL
            SELECT continent, country, region, city, appID AS recommendation_id, City_Ranking AS Ranking, recommendation_type, recommendation_activity
            FROM microapps_geo_popularity
            WHERE {where_clause}
            UNION ALL
            SELECT continent, country, region, city, cardID AS recommendation_id, City_Ranking AS Ranking, recommendation_type, recommendation_activity
            FROM cards_geo_popularity
            WHERE {where_clause}
        """

        # Execute query in Spanner
        with database.snapshot() as snapshot:
            results = snapshot.execute_sql(query, params=data, param_types=query_params)
            records = [
                {
                    "continent": row[0],
                    "country": row[1],
                    "region": row[2],
                    "city": row[3],
                    "recommendation_id": row[4],
                    "Ranking": row[5],
                    "recommendation_type": row[6],
                    "recommendation_activity": row[7]
                }
                for row in results
            ]

        app.logger.info(f"Retrieved {len(records)} records for country: {country}, city: {city}, region: {region}")
        app.logger.info(f"Recommendations: {records}")  # Log retrieved recommendations
        if not records:
            app.logger.info(f"No recommendations found for provided parameters")
            return jsonify([]), 200
        else:
            return jsonify(records), 200

    except Exception as e:
        app.logger.error(f"Error in recommendations_pwa endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
