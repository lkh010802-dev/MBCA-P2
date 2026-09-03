"""
백엔드 연동 예시.

실제 서비스에서는 /recommend/course 응답 dict를
generate_course_message()에 그대로 전달하면 됩니다.
"""

from llm_output import generate_course_message


course_result = {
    "optimized_places": [
        {
            "name": "A카페",
            "category": "cafe",
            "latitude": 37.0,
            "longitude": 127.1,
            "specified_duration_minutes": 45,
        },
        {
            "name": "B전시관",
            "category": "culture",
            "latitude": 37.1,
            "longitude": 127.2,
            "specified_duration_minutes": 60,
        },
    ],
    "legs": [],
    "total_stay_time_minutes": 105,
    "total_travel_time_minutes": 35,
    "total_required_minutes": 140,
    "available_time_minutes": 180,
    "remaining_time_minutes": 40,
    "status": "FEASIBLE",
}


message = generate_course_message(course_result)

print(message)
