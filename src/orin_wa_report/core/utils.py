import os
import json
from enum import Enum
from typing import Dict, List

import requests
import pandas as pd

from src.orin_wa_report.core.logger import get_logger
from src.orin_wa_report.core.config import DB_QUERY_ENDPOINT

from dotenv import load_dotenv

load_dotenv()
vps_ip = os.getenv("VPS_IP")
vps_db_port = os.getenv("VPS_DB_PORT")
vps_db_base_url = f"http://{vps_ip}:{vps_db_port}"

logger = get_logger(__name__)

def get_db_query_endpoint(db_base_url: str = vps_db_base_url, name: str = ""):
    url = DB_QUERY_ENDPOINT.get(name, "")
    if name == "":
        url = f"{db_base_url}/query"  # default to /query
    else:
        url = url.format(db_base_url=db_base_url)
    return url

def get_user_id_from_api_token(db_base_url: str, api_token: str):
    try:
        url = get_db_query_endpoint(db_base_url=db_base_url)
        
        response_user_ids = requests.post(url, json={
            "query": "SELECT id FROM users WHERE api_token = :api_token AND deleted_at IS NULL LIMIT 10",
            "params": {"api_token": api_token}
        }).json()
        
        logger.info(f"User IDs: {response_user_ids}")
        
        df_device_summaries = pd.DataFrame(response_user_ids.get("rows", {}))
        
        if len(df_device_summaries) == 0:
            logger.error("No user_id found from the api_token")
            raise RuntimeError("No user_id found from the api_token")
        
        user_ids = df_device_summaries["id"].tolist()
        logger.info(f"User IDs: {user_ids}")
        
        if len(df_device_summaries) > 1:
            logger.warning(f"Get {len(user_ids)} user_ids, will choose the first one")
            
        return user_ids[0]
    except Exception as e:
        logger.error(f"Error when get user_id from api_token: {str(e)}")
        raise RuntimeError(f"Error when get user_id from api_token: {str(e)}")
    
import requests

def get_request_bearer(url: str, token: str) -> Dict:
    """
    Sends a GET request to the specified URL with a Bearer token
    and returns the JSON response.

    Args:
        url (str): The URL to send the GET request to.
        token (str): The Bearer token for authentication.

    Returns:
        dict: The JSON response from the API.

    Raises:
        requests.HTTPError: If the request fails (non-2xx status code).
        ValueError: If the response is not valid JSON.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    response = requests.get(url, headers=headers)
    
    # Raise an exception for HTTP errors
    response.raise_for_status()

    # Return the JSON content
    return response.json()

def get_device_id_from_device_sn(device_sn: str | int) -> int:
    try:
        url = get_db_query_endpoint(name="devsites_orin")
        
        response_device_id = requests.post(url, json={
            "query": "SELECT id FROM devices WHERE device_sn = :device_sn AND deleted_at IS NULL LIMIT 1",
            "params": {"device_sn": device_sn}
        }).json()
        
        logger.info(f"Device ID: {response_device_id}")
        
        df_device_id = pd.DataFrame(response_device_id.get("rows", {}))
        
        if len(df_device_id) == 0:
            logger.error("No id found from the device_sn")
            raise RuntimeError("No id found from the device_sn")
        
        device_id = df_device_id["id"].tolist()
        # logger.info(f"User IDs: {user_ids}")
        
        # if len(df_device_summaries) > 1:
        #     logger.warning(f"Get {len(user_ids)} user_ids, will choose the first one")
            
        return device_id[0]
    except Exception as e:
        logger.error(f"Error when get device_id from device_sn: {str(e)}")
        raise RuntimeError(f"Error when get device_id from device_sn: {str(e)}")

def get_orin_reverse_geocode(
    latitude: float,
    longitude: float,
    token: str,
):
    url = f"https://api-v2.orin.id/api/google/reverse_geocode?lat={latitude}&lng={longitude}"
    
    result = get_request_bearer(url, token)
    
    address = result.get("address")
    
    return address

class Orin_Reports_Action(str, Enum):
    GET_STOP = "get_idle",
    GET_MOVING = "get_moving",

def get_orin_reports(
    device_sn: str | int,
    token: str,
    date: str,
    action: Orin_Reports_Action,
):
    logger.info(f"Get ORIN Reports: device_sn: {device_sn}, token: {token}, date: {date}, action: {action}")
    try:
        device_id = get_device_id_from_device_sn(device_sn=device_sn)
        url = f"https://api-v2.orin.id/api/devices/{device_id}/history_routes_total?geocode=false&start_date={date}%2000:00:00&end_date={date}%2023:59:59&export=undefined"

        result = get_request_bearer(url, token)
        
        data: List[Dict[str, str]] = result.get("data").get("data")
        
        # Filter status
        status_filter = []
        if action == "get_idle": status_filter.append("stop")
        if action == "get_moving": status_filter.append("moving")
        
        data_filtered = [
            val for val in data
            if val.get("status") in status_filter
        ]
        
        # Convert From To
        result = []
        for d in data_filtered:
            status = d.get("status")
            if status == "stop": status = "idle"
            
            if action == "get_idle":
                time = round(d.get("total_acc_on_sec")/60, 2)
                if time == 0: continue
                # time = round(d.get("stop_sec")/60, 2)
                time = f"{time} minutes"
            elif action == "get_moving":
                time = round(d.get("moving_sec")/60, 2)
                time = f"{time} minutes"
            
            start_time = d.get("start_row").get("dt")
            
            start_address = d.get("start_row").get("poi")
            if start_address == "":
                start_address = get_orin_reverse_geocode(
                    latitude=d.get("start_row").get("lat"),
                    longitude=d.get("start_row").get("lng"),
                    token=token
                )
                
            end_time = d.get("end_row").get("dt")
            if action == "get_moving":
                end_address = d.get("end_row").get("poi")
                if end_address == "":
                    end_address = get_orin_reverse_geocode(
                        latitude=d.get("end_row").get("lat"),
                        longitude=d.get("end_row").get("lng"),
                        token=token
                    )
            else:
                end_address = None
                
            result_dict = {
                "status": status,
                "time": time,
                "start_time": start_time,
                "end_time": end_time,
            }
            
            if action == "get_idle":
                result_dict["address"] = start_address
            elif action == "get_moving":
                result_dict["start_address"] = start_address
                result_dict["end_adress"] = end_address
                
            result.append(result_dict)
    except Exception as e:
        logger.error(f"Error when get_orin_reports: {str(e)}")
        raise RuntimeError(f"Error when get orin reports: {str(e)}")
    
    return result
    