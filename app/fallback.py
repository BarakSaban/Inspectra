# Lightweight fallback data providers used when the DB is unavailable.

def sample_inspectors():
    return [
        {
            "inspector_id": "I001",
            "name": "Fallback Inspector 1",
            "latitude": 32.0853,
            "longitude": 34.7818,
            "available": True,
            "total_fines": 0,
            "completed_trips": 0
        },
        {
            "inspector_id": "I002",
            "name": "Fallback Inspector 2",
            "latitude": 32.1093,
            "longitude": 34.8555,
            "available": False,
            "total_fines": 0,
            "completed_trips": 0
        }
    ]


def sample_analytics():
    return {
        "totalFines": 0,
        "weeklyTotal": 0,
        "activeInspectors": 1,
        "avgEfficiency": 0,
        "inspectors": sample_inspectors()
    }


def sample_profile(username):
    return {
        "username": username or "guest",
        "role": "guest",
        "inspector_id": None,
        "manager_code": None,
        "full_name": "Guest User"
    }
