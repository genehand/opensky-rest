"""Constants for the OpenSky REST integration."""

from __future__ import annotations

import logging
from typing import Final

from homeassistant.const import Platform

LOGGER = logging.getLogger(__package__)

DOMAIN: Final = "opensky_ng"
MANUFACTURER: Final = "OpenSky Network"
DEFAULT_NAME: Final = "OpenSky"
DEFAULT_ALTITUDE: Final = 0

PLATFORMS: Final = [Platform.SENSOR, Platform.SWITCH]

# Configuration keys
CONF_ALTITUDE: Final = "altitude"
CONF_CLIENT_ID: Final = "client_id"
CONF_CLIENT_SECRET: Final = "client_secret"

# Event names
EVENT_OPENSKY_ENTRY: Final = f"{DOMAIN}_entry"
EVENT_OPENSKY_EXIT: Final = f"{DOMAIN}_exit"

# Attribute keys
ATTR_CALLSIGN: Final = "callsign"
ATTR_ICAO24: Final = "icao24"
ATTR_AIRLINE: Final = "airline"
ATTR_ALTITUDE: Final = "altitude"
ATTR_BARO_ALTITUDE: Final = "baro_altitude"
ATTR_GEO_ALTITUDE: Final = "geo_altitude"
ATTR_VELOCITY: Final = "velocity"
ATTR_TRUE_TRACK: Final = "true_track"
ATTR_VERTICAL_RATE: Final = "vertical_rate"
ATTR_LATITUDE: Final = "latitude"
ATTR_LONGITUDE: Final = "longitude"
ATTR_ORIGIN_COUNTRY: Final = "origin_country"
ATTR_ON_GROUND: Final = "on_ground"
ATTR_CATEGORY: Final = "category"
ATTR_CATEGORY_NAME: Final = "category_name"
ATTR_SQUAWK: Final = "squawk"
ATTR_SPI: Final = "spi"
ATTR_POSITION_SOURCE: Final = "position_source"
ATTR_POSITION_SOURCE_NAME: Final = "position_source_name"
ATTR_TIME_POSITION: Final = "time_position"
ATTR_LAST_CONTACT: Final = "last_contact"
ATTR_SENSORS: Final = "sensors"
ATTR_ALTITUDE_FT: Final = "altitude_ft"
ATTR_SPEED_KTS: Final = "speed_kts"
ATTR_STATS: Final = "stats"
ATTR_AIRCRAFT: Final = "aircraft"
ATTR_COUNT: Final = "count"
ATTR_REGISTRATION: Final = "registration"
ATTR_AIRCRAFT_IMAGE_URL: Final = "aircraft_image_url"
ATTR_DEPARTURE_AIRPORT: Final = "departure_airport"
ATTR_DEPARTURE_CITY: Final = "departure_city"
ATTR_DEPARTURE_COUNTRY: Final = "departure_country"
ATTR_ARRIVAL_AIRPORT: Final = "arrival_airport"
ATTR_ARRIVAL_CITY: Final = "arrival_city"
ATTR_ARRIVAL_COUNTRY: Final = "arrival_country"

# Sensor/switch translations
TRANSLATION_KEY_FLIGHTS: Final = "flights"
TRANSLATION_KEY_ENABLED: Final = "enabled"

# Category mapping from OpenSky API
CATEGORY_MAP: Final[dict[int, str]] = {
    0: "No information",
    1: "No ADS-B category",
    2: "Light (< 15500 lbs)",
    3: "Small (15500 to 75000 lbs)",
    4: "Large (75000 to 300000 lbs)",
    5: "High Vortex Large (e.g., B-757)",
    6: "Heavy (> 300000 lbs)",
    7: "High Performance",
    8: "Rotorcraft",
    9: "Glider / sailplane",
    10: "Lighter-than-air",
    11: "Parachutist / Skydiver",
    12: "Ultralight / hang-glider / paraglider",
    13: "Reserved",
    14: "Unmanned Aerial Vehicle",
    15: "Space / Trans-atmospheric",
    16: "Surface Vehicle – Emergency",
    17: "Surface Vehicle – Service",
    18: "Point Obstacle",
    19: "Cluster Obstacle",
    20: "Line Obstacle",
}

# Position source mapping
POSITION_SOURCE_MAP: Final[dict[int, str]] = {
    0: "ADS-B",
    1: "ASTERIX",
    2: "MLAT",
    3: "FLARM",
}

# Airline callsign prefix lookup table.
# The first 2-3 characters of an aircraft's callsign typically identify the airline.
# Source: ICAO airline designators
AIRLINE_LOOKUP: Final[dict[str, str]] = {
    # North America
    "AAL": "American Airlines",
    "DAL": "Delta Air Lines",
    "UAL": "United Airlines",
    "SWA": "Southwest Airlines",
    "JBU": "JetBlue Airways",
    "ASA": "Alaska Airlines",
    "FFT": "Frontier Airlines",
    "AAY": "Allegiant Air",
    "SKW": "SkyWest Airlines",
    "ENY": "Envoy Air",
    "RPA": "Republic Airways",
    "ASH": "Mesa Airlines",
    "CPZ": "Compass Airlines",
    "QXE": "Horizon Air",
    "ACA": "Air Canada",
    "WJA": "WestJet",
    "ROU": "Air Canada Rouge",
    "JZA": "Jazz Aviation",
    "AMX": "Aeromexico",
    "VOI": "Volaris",
    "VIV": "VivaAerobus",
    "CMP": "Copa Airlines",
    # Europe
    "BAW": "British Airways",
    "DLH": "Lufthansa",
    "AFR": "Air France",
    "KLM": "KLM Royal Dutch Airlines",
    "RYR": "Ryanair",
    "EZY": "EasyJet",
    "WZZ": "Wizz Air",
    "IBE": "Iberia",
    "VLG": "Vueling Airlines",
    "SWR": "Swiss International Air Lines",
    "AUA": "Austrian Airlines",
    "THY": "Turkish Airlines",
    "FIN": "Finnair",
    "SAS": "Scandinavian Airlines",
    "NAX": "Norwegian Air Shuttle",
    "TAP": "TAP Air Portugal",
    "LOT": "LOT Polish Airlines",
    "CSA": "Czech Airlines",
    "EXS": "Jet2.com",
    "TOM": "TUI Airways",
    "WUK": "Wizz Air UK",
    "LOG": "Loganair",
    "EIN": "Aer Lingus",
    "JAF": "TUI fly Belgium",
    "BEL": "Brussels Airlines",
    "KAR": "Air Malta",
    "ADR": "Adria Airways",
    "AZA": "Alitalia",
    "ITY": "ITA Airways",
    "AEA": "Air Europa",
    "ANE": "Air Nostrum (Iberia Regional)",
    "SDR": "Swiftair",
    "PLM": "Pegasus Airlines",
    "SXS": "SunExpress",
    "TWI": "Tailwind Airlines",
    "LLR": "Air India (cargo)",
    # UK
    "VIR": "Virgin Atlantic",
    "TCO": "Titan Airways",
    "CFE": "BA CityFlyer",
    # Middle East
    "UAE": "Emirates",
    "QTR": "Qatar Airways",
    "ETD": "Etihad Airways",
    "FDB": "flydubai",
    "ABY": "Air Arabia",
    "AZD": "Air Arabia (Egypt)",
    "JZR": "Jazeera Airways",
    "KAC": "Kuwait Airways",
    "OYA": "Oman Air",
    "SVA": "Saudia",
    "MEA": "Middle East Airlines",
    "PIA": "Pakistan International Airlines",
    # Asia
    "SIA": "Singapore Airlines",
    "CPA": "Cathay Pacific",
    "JAL": "Japan Airlines",
    "ANA": "All Nippon Airways",
    "CES": "China Eastern Airlines",
    "CCA": "Air China",
    "CSN": "China Southern Airlines",
    "HDA": "Hong Kong Airlines",
    "KAL": "Korean Air",
    "AAR": "Asiana Airlines",
    "THA": "Thai Airways",
    "GIA": "Garuda Indonesia",
    "LNI": "Lion Air",
    "MAS": "Malaysia Airlines",
    "PAL": "Philippine Airlines",
    "CAB": "Cebu Pacific Air",
    "VTI": "Vistara",
    "IGO": "IndiGo",
    "AIC": "Air India",
    "SEP": "SpiceJet",
    "AXB": "Air India Express",
    "EVA": "EVA Air",
    "CAL": "China Airlines",
    "BAV": "Bamboo Airways",
    "VJC": "VietJet Air",
    "HVN": "Vietnam Airlines",
    "TBA": "Thai Airways (old code)",
    # Oceania
    "QFA": "Qantas",
    "VOZ": "Virgin Australia",
    "JST": "Jetstar Airways",
    "REX": "Rex Regional Express",
    "ANZ": "Air New Zealand",
    "FJI": "Fiji Airways",
    # Africa
    "ETH": "Ethiopian Airlines",
    "RAM": "Royal Air Maroc",
    "MSR": "EgyptAir",
    "KQA": "Kenya Airways",
    "SAA": "South African Airways",
    "AFM": "Air Mauritius",
    "TAY": "Tunisair",
    "ALG": "Air Algerie",
    "RBA": "Royal Brunei Airlines",
    # Latin America
    "LAT": "LATAM Airlines",
    "TAM": "LATAM Brasil",
    "LAN": "LATAM Chile",
    "AZU": "Azul Brazilian Airlines",
    "GLO": "Gol Transportes Aereos",
    "AVA": "Avianca",
    "ARE": "Avianca (Colombia)",
    "LAU": "LAN Argentina",
    "SKU": "Sky Airline",
    "JAT": "JetSmart",
    "WAL": "West Air Sweden",
    "ABQ": "Aerobus",
    # Cargo / Freight
    "UPS": "UPS Airlines",
    "FDX": "FedEx Express",
    "CKS": "Kalitta Air",
    "GTI": "Atlas Air",
    "CLX": "Cargolux",
    "SQC": "Singapore Airlines Cargo",
    "KZU": "K-Mile Air",
    "RUN": "Runway Airlines",
    "ABD": "Atlas Air (cargo)",
    "DXH": "DHL Air UK",
    "BCS": "DHL (European)",
    "SWN": "Swift Cargo",
}
